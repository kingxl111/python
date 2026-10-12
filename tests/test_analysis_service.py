from dataclasses import replace

import pytest
from conftest import PayloadFactory

from lab_checker.analysis import AnalysisContext, AnalysisService, AnalyzerRegistry
from lab_checker.bootstrap import build_registry
from lab_checker.errors import (
    AssignmentNotFoundError,
    SubmissionNotFoundError,
    UnknownAnalyzerError,
)
from lab_checker.intake import IntakeService
from lab_checker.models import AnalysisFailure, AnalysisReport, Evidence, Submission
from lab_checker.repositories import InMemoryAssignmentCatalog, InMemorySubmissionRepository


class FailingAnalyzer:
    analyzer_id = "failing"
    analyzer_version = "0.1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        raise RuntimeError("сбой анализатора")


class OutOfRangeAnalyzer:
    analyzer_id = "out-of-range"
    analyzer_version = "0.1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        return AnalysisReport(
            submission_id=submission.submission_id,
            analyzer_id=self.analyzer_id,
            analyzer_version=self.analyzer_version,
            score=None,
            similarity=1.5,
            rubric_feedback=("x",),
            evidence=(Evidence("code", 1, 999, "нет такой строки"),),
        )


class MalformedAnalyzer:
    analyzer_id = "malformed"
    analyzer_version = "0.1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        return AnalysisReport(
            submission_id=submission.submission_id,
            analyzer_id=self.analyzer_id,
            analyzer_version=self.analyzer_version,
            score=float("nan"),
            similarity="0.5",  # type: ignore[arg-type]
            rubric_feedback=("x", 1),  # type: ignore[arg-type]
            evidence=(("code", 1, 1),),  # type: ignore[arg-type]
        )


class BrokenConstructorAnalyzer:
    analyzer_id = "broken-constructor"
    analyzer_version = "0.1.0"

    def __init__(self) -> None:
        raise RuntimeError("нет конфигурации")

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        raise AssertionError("не должен вызываться")


class DeclarationAnalyzer:
    """Пример внешнего анализатора, подключаемого без изменения сервиса."""

    analyzer_id = "ai-declaration"
    analyzer_version = "0.1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        declaration = submission.ai_declaration
        missing = declaration.used and not (declaration.description or "").strip()
        return AnalysisReport(
            submission_id=submission.submission_id,
            analyzer_id=self.analyzer_id,
            analyzer_version=self.analyzer_version,
            score=None,
            similarity=None,
            rubric_feedback=("декларация пуста" if missing else "декларация в порядке",),
        )


@pytest.fixture
def registry() -> AnalyzerRegistry:
    registry = build_registry()
    registry.register(FailingAnalyzer.analyzer_id, FailingAnalyzer)
    registry.register(OutOfRangeAnalyzer.analyzer_id, OutOfRangeAnalyzer)
    registry.register(MalformedAnalyzer.analyzer_id, MalformedAnalyzer)
    registry.register(BrokenConstructorAnalyzer.analyzer_id, BrokenConstructorAnalyzer)
    return registry


@pytest.fixture
def service(
    repository: InMemorySubmissionRepository,
    catalog: InMemoryAssignmentCatalog,
    registry: AnalyzerRegistry,
) -> AnalysisService:
    return AnalysisService(repository, catalog, registry)


@pytest.fixture
def submission(intake: IntakeService, make_payload: PayloadFactory) -> Submission:
    return intake.submit(make_payload()).submission


def test_runs_selected_analyzers_in_order(service: AnalysisService, submission: Submission) -> None:
    outcomes = service.analyze(submission.submission_id, ["template", "length"])

    assert [(type(o), o.analyzer_id) for o in outcomes] == [
        (AnalysisReport, "template"),
        (AnalysisReport, "length"),
    ]


def test_analyzer_error_does_not_affect_others(
    service: AnalysisService, submission: Submission
) -> None:
    outcomes = service.analyze(submission.submission_id, ["length", "failing", "template"])

    assert isinstance(outcomes[0], AnalysisReport)
    assert outcomes[1] == AnalysisFailure(
        submission_id="sub-001",
        analyzer_id="failing",
        code="analyzer_error",
        message="RuntimeError: сбой анализатора",
    )
    assert isinstance(outcomes[2], AnalysisReport)


def test_invalid_report_is_rejected(service: AnalysisService, submission: Submission) -> None:
    (outcome,) = service.analyze(submission.submission_id, ["out-of-range"])

    assert isinstance(outcome, AnalysisFailure)
    assert outcome.code == "invalid_report"
    assert "similarity" in outcome.message
    assert "code:1-999" in outcome.message


def test_report_with_wrong_types_is_rejected(
    service: AnalysisService, submission: Submission
) -> None:
    (outcome,) = service.analyze(submission.submission_id, ["malformed"])

    assert isinstance(outcome, AnalysisFailure)
    assert outcome.code == "invalid_report"
    for fragment in ("score", "similarity", "rubric_feedback", "ожидался Evidence"):
        assert fragment in outcome.message


def test_analyzer_construction_error_does_not_affect_others(
    service: AnalysisService, submission: Submission
) -> None:
    outcomes = service.analyze(submission.submission_id, ["broken-constructor", "length"])

    assert outcomes[0] == AnalysisFailure(
        submission_id="sub-001",
        analyzer_id="broken-constructor",
        code="analyzer_error",
        message="RuntimeError: нет конфигурации",
    )
    assert isinstance(outcomes[1], AnalysisReport)


def test_unknown_analyzer_fails_before_running_any(
    repository: InMemorySubmissionRepository,
    catalog: InMemoryAssignmentCatalog,
    submission: Submission,
) -> None:
    calls: list[str] = []

    class Recording(DeclarationAnalyzer):
        def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
            calls.append(submission.submission_id)
            return super().analyze(submission, context)

    registry = AnalyzerRegistry()
    registry.register(Recording.analyzer_id, Recording)
    service = AnalysisService(repository, catalog, registry)

    with pytest.raises(UnknownAnalyzerError):
        service.analyze(submission.submission_id, ["ai-declaration", "missing"])
    assert calls == []


def test_new_analyzer_is_plugged_in_through_registry_only(
    repository: InMemorySubmissionRepository,
    catalog: InMemoryAssignmentCatalog,
    registry: AnalyzerRegistry,
    intake: IntakeService,
    make_payload: PayloadFactory,
) -> None:
    registry.register(DeclarationAnalyzer.analyzer_id, DeclarationAnalyzer)
    service = AnalysisService(repository, catalog, registry)
    intake.submit(
        make_payload(submission_id="empty", ai_declaration={"used": True, "description": " "})
    )

    (outcome,) = service.analyze("empty", ["ai-declaration"])

    assert isinstance(outcome, AnalysisReport)
    assert outcome.rubric_feedback == ("декларация пуста",)


def test_unknown_submission(service: AnalysisService) -> None:
    with pytest.raises(SubmissionNotFoundError):
        service.analyze("nope", ["length"])


def test_assignment_removed_after_intake(
    repository: InMemorySubmissionRepository, registry: AnalyzerRegistry, submission: Submission
) -> None:
    service = AnalysisService(repository, InMemoryAssignmentCatalog([]), registry)

    with pytest.raises(AssignmentNotFoundError):
        service.analyze(submission.submission_id, ["length"])


def test_analysis_does_not_change_stored_submission(
    service: AnalysisService, repository: InMemorySubmissionRepository, submission: Submission
) -> None:
    before = replace(submission)

    service.analyze(submission.submission_id, ["length", "template", "failing"])

    assert repository.get(submission.submission_id) == before


def test_registry_rejects_duplicate_registration() -> None:
    registry = build_registry()

    with pytest.raises(ValueError, match="уже зарегистрирован"):
        registry.register("length", DeclarationAnalyzer)


def test_registry_rejects_factory_with_other_id() -> None:
    registry = AnalyzerRegistry()
    registry.register("length", DeclarationAnalyzer)

    with pytest.raises(ValueError, match="создала анализатор"):
        registry.create("length")
