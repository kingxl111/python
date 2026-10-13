from dataclasses import replace
from typing import Any

import pytest
from conftest import PUBLIC_SUBMISSIONS, RAW_EXAMPLE

from lab_checker.analysis import (
    AnalysisContext,
    AnalysisService,
    AnalyzerRegistry,
    validate_report,
)
from lab_checker.analyzers import LengthAnalyzer
from lab_checker.bootstrap import AppConfig, Application, build_application, build_registry
from lab_checker.errors import AnalysisFailure, ConfigurationError
from lab_checker.models import AnalysisReport, Assignment, Evidence, Finding, Submission
from lab_checker.repositories import InMemorySubmissionRepository
from lab_checker.services import SubmissionService, import_source
from lab_checker.sources import InMemorySource


def test_end_to_end(app: Application, context: AnalysisContext) -> None:
    summary = import_source(InMemorySource(PUBLIC_SUBMISSIONS), app.submission_service)
    reports = 0
    for submission_id in summary.accepted:
        original = app.repository.get(submission_id)
        assert original is not None
        for name in ("length", "template"):
            report = app.analysis_service.run(submission_id, name, context)
            validate_report(report, original, context)
            assert app.repository.get(submission_id) == original
            reports += 1

    assert reports == 24


def test_run_requires_accepted_submission_and_matching_context(
    app: Application, context: AnalysisContext
) -> None:
    with pytest.raises(AnalysisFailure):
        app.analysis_service.run("sub-001", "length", context)

    app.submission_service.accept(RAW_EXAMPLE)
    with pytest.raises(AnalysisFailure):
        app.analysis_service.run("sub-001", "length", AnalysisContext(Assignment("other", "", ())))
    with pytest.raises(AnalysisFailure):
        app.analysis_service.run("sub-001", "missing", context)


class BrokenHashAnalyzer:
    analyzer_id = "broken"
    analyzer_version = "1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        good = LengthAnalyzer().analyze(submission, context)
        return replace(good, submission_hash="incorrect")


class CrashingAnalyzer:
    analyzer_id = "crash"
    analyzer_version = "1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        raise RuntimeError("сбой")


class WrongVersionAnalyzer:
    analyzer_id = "length"
    analyzer_version = "2.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        return LengthAnalyzer().analyze(submission, context)


def failing_factory() -> LengthAnalyzer:
    raise RuntimeError("конструктор упал")


@pytest.mark.parametrize(
    ("name", "factory"),
    [
        ("broken", BrokenHashAnalyzer),
        ("crash", CrashingAnalyzer),
        ("length", WrongVersionAnalyzer),
        ("other-id", LengthAnalyzer),
        ("factory", failing_factory),
    ],
)
def test_defective_analyzer_is_stopped(name: str, factory: Any, context: AnalysisContext) -> None:
    repository = InMemorySubmissionRepository()
    SubmissionService(repository).accept(RAW_EXAMPLE)
    registry = AnalyzerRegistry()
    registry.register(name, factory)

    with pytest.raises(AnalysisFailure):
        AnalysisService(repository, registry).run("sub-001", name, context)


def test_registry_rejects_bad_names() -> None:
    registry = build_registry()

    with pytest.raises(AnalysisFailure):
        registry.register("length", LengthAnalyzer)
    with pytest.raises(AnalysisFailure):
        registry.register(" ", LengthAnalyzer)


def test_unknown_analyzer_in_config_fails_before_use() -> None:
    with pytest.raises(ConfigurationError):
        build_application(AppConfig(analyzers=("length", "nope")))


def report_with(submission: Submission, context: AnalysisContext, **changes: Any) -> AnalysisReport:
    return replace(LengthAnalyzer().analyze(submission, context), **changes)


def finding_with(**changes: Any) -> tuple[Finding, ...]:
    return (replace(Finding("rubric_feedback", None, (), "ok"), **changes),)


@pytest.mark.parametrize(
    "changes",
    [
        {"submission_id": "other"},
        {"config_hash": "other"},
        {"report_id": ""},
        {"review_required": 1},
        {"created_at": "2026-09-01T10:00:00"},
        {"created_at": "вчера"},
        {"findings": finding_with(kind="verdict")},
        {"findings": finding_with(score=1.5)},
        {"findings": finding_with(score=float("nan"))},
        {"findings": finding_with(score=True)},
        {"findings": finding_with(explanation=" ")},
        {"findings": finding_with(evidence=(Evidence("sub-001", "code", 1, 99),))},
        {"findings": finding_with(evidence=(Evidence("sub-001", "code", 0, 1),))},
        {"findings": finding_with(evidence=(Evidence("sub-002", "code", 1, 1),))},
        {"findings": finding_with(evidence=(Evidence("sub-001", "code", 2, 1),))},
        {"findings": ("not a finding",)},
        {"findings": finding_with(kind=["similarity"])},
    ],
)
def test_validate_report_rejects(
    changes: dict[str, Any], submission: Submission, context: AnalysisContext
) -> None:
    with pytest.raises(AnalysisFailure):
        validate_report(report_with(submission, context, **changes), submission, context)


def test_config_hash_depends_on_assignment(assignment: Assignment) -> None:
    first = AnalysisContext(assignment)
    other = AnalysisContext(replace(assignment, allowed_template=""))

    assert first.config_hash == AnalysisContext(assignment).config_hash
    assert first.config_hash != other.config_hash
    assert first.config_payload()["mode"] == "baseline"
