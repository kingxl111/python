"""Контракт анализатора, реестр фабрик и центральный сервис анализа."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from lab_checker.errors import (
    AssignmentNotFoundError,
    SubmissionNotFoundError,
    UnknownAnalyzerError,
)
from lab_checker.models import (
    AnalysisFailure,
    AnalysisReport,
    Assignment,
    Evidence,
    Submission,
    split_lines,
)
from lab_checker.repositories import AssignmentCatalog, SubmissionReader


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    assignment: Assignment
    submissions: SubmissionReader


class Analyzer(Protocol):
    @property
    def analyzer_id(self) -> str: ...

    @property
    def analyzer_version(self) -> str: ...

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport: ...


AnalyzerFactory = Callable[[], Analyzer]
AnalysisOutcome = AnalysisReport | AnalysisFailure


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AnalyzerFactory] = {}

    def register(self, analyzer_id: str, factory: AnalyzerFactory) -> None:
        if analyzer_id in self._factories:
            raise ValueError(f"анализатор {analyzer_id!r} уже зарегистрирован")
        self._factories[analyzer_id] = factory

    def __contains__(self, analyzer_id: object) -> bool:
        return analyzer_id in self._factories

    def create(self, analyzer_id: str) -> Analyzer:
        factory = self._factories.get(analyzer_id)
        if factory is None:
            raise UnknownAnalyzerError(analyzer_id)
        analyzer = factory()
        if analyzer.analyzer_id != analyzer_id:
            raise ValueError(f"фабрика {analyzer_id!r} создала анализатор {analyzer.analyzer_id!r}")
        return analyzer


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_line_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def find_report_problems(report: object, submission: Submission, analyzer: Analyzer) -> list[str]:
    """Проверяет отчёт анализатора по общему контракту."""
    if not isinstance(report, AnalysisReport):
        return [f"ожидался AnalysisReport, получен {type(report).__name__}"]
    problems: list[str] = []
    if report.submission_id != submission.submission_id:
        problems.append("submission_id отчёта не совпадает со сдачей")
    if report.analyzer_id != analyzer.analyzer_id:
        problems.append("analyzer_id отчёта не совпадает с анализатором")
    if report.analyzer_version != analyzer.analyzer_version:
        problems.append("analyzer_version отчёта не совпадает с анализатором")
    if report.score is not None and not (_is_number(report.score) and math.isfinite(report.score)):
        problems.append(f"score {report.score!r} должен быть конечным числом или null")
    if report.similarity is not None and not (
        _is_number(report.similarity) and 0.0 <= report.similarity <= 1.0
    ):
        problems.append(f"similarity {report.similarity!r} должна быть числом в диапазоне [0, 1]")
    if not isinstance(report.rubric_feedback, tuple) or not all(
        isinstance(item, str) for item in report.rubric_feedback
    ):
        problems.append("rubric_feedback должен быть кортежем строк")
    if not isinstance(report.evidence, tuple):
        problems.append("evidence должен быть кортежем Evidence")
        return problems
    for item in report.evidence:
        if not isinstance(item, Evidence):
            problems.append(f"ожидался Evidence, получен {type(item).__name__}")
            continue
        if not (_is_line_number(item.start_line) and _is_line_number(item.end_line)):
            problems.append("номера строк evidence должны быть целыми числами")
            continue
        if item.source not in ("text", "code"):
            problems.append(f"неизвестный источник evidence {item.source!r}")
            continue
        line_count = len(split_lines(submission.content(item.source)))
        if not 1 <= item.start_line <= item.end_line <= line_count:
            problems.append(
                f"evidence {item.source}:{item.start_line}-{item.end_line} вне строк 1-{line_count}"
            )
    return problems


class AnalysisService:
    """Запускает анализаторы, выбранные по реестру. Ошибка одного анализатора
    становится ``AnalysisFailure`` и не мешает остальным."""

    def __init__(
        self,
        submissions: SubmissionReader,
        assignments: AssignmentCatalog,
        registry: AnalyzerRegistry,
    ) -> None:
        self._submissions = submissions
        self._assignments = assignments
        self._registry = registry

    def analyze(
        self, submission_id: str, analyzer_ids: Sequence[str]
    ) -> tuple[AnalysisOutcome, ...]:
        submission = self._submissions.get(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)
        assignment = self._assignments.get(submission.assignment_id)
        if assignment is None:
            raise AssignmentNotFoundError(submission.assignment_id)
        for analyzer_id in analyzer_ids:
            if analyzer_id not in self._registry:
                raise UnknownAnalyzerError(analyzer_id)
        context = AnalysisContext(assignment=assignment, submissions=self._submissions)
        return tuple(self._run(analyzer_id, submission, context) for analyzer_id in analyzer_ids)

    def _run(
        self, analyzer_id: str, submission: Submission, context: AnalysisContext
    ) -> AnalysisOutcome:
        try:
            analyzer = self._registry.create(analyzer_id)
            report = analyzer.analyze(submission, context)
            problems = find_report_problems(report, submission, analyzer)
        except Exception as exc:
            return AnalysisFailure(
                submission_id=submission.submission_id,
                analyzer_id=analyzer_id,
                code="analyzer_error",
                message=f"{type(exc).__name__}: {exc}",
            )
        if problems:
            return AnalysisFailure(
                submission_id=submission.submission_id,
                analyzer_id=analyzer_id,
                code="invalid_report",
                message="; ".join(problems),
            )
        return report
