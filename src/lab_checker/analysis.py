"""Контракт анализатора, проверка отчёта, реестр фабрик и сервис анализа."""

import math
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from lab_checker.errors import AnalysisFailure
from lab_checker.hashing import stable_hash, submission_hash
from lab_checker.models import AnalysisReport, Assignment, Evidence, Finding, Submission
from lab_checker.repositories import SubmissionRepository

FINDING_KINDS = ("similarity", "rubric_feedback", "processing_error")


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    assignment: Assignment
    mode: Literal["baseline", "stub"] = "baseline"
    config_version: str = "1"

    def config_payload(self) -> dict[str, object]:
        return {
            "assignment": asdict(self.assignment),
            "mode": self.mode,
            "config_version": self.config_version,
        }

    @property
    def config_hash(self) -> str:
        return stable_hash(self.config_payload())


class Analyzer(Protocol):
    @property
    def analyzer_id(self) -> str: ...

    @property
    def analyzer_version(self) -> str: ...

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport: ...


AnalyzerFactory = Callable[[], Analyzer]


def _check_evidence(evidence: object, submission: Submission) -> None:
    if not isinstance(evidence, Evidence):
        raise AnalysisFailure("Ожидается Evidence")
    if evidence.submission_id != submission.submission_id or evidence.field not in ("text", "code"):
        raise AnalysisFailure("Evidence ссылается на неизвестный объект или поле")
    if type(evidence.start_line) is not int or type(evidence.end_line) is not int:
        raise AnalysisFailure("Номер строки должен быть int")
    line_count = len(getattr(submission, evidence.field).splitlines())
    if not 1 <= evidence.start_line <= evidence.end_line <= line_count:
        raise AnalysisFailure("Evidence выходит за границы исходного текста")


def _check_finding(finding: object, submission: Submission) -> None:
    if not isinstance(finding, Finding):
        raise AnalysisFailure("Ожидается Finding")
    if finding.kind not in FINDING_KINDS:
        raise AnalysisFailure("Неизвестный kind")
    score = finding.score
    if score is not None and not (
        type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1
    ):
        raise AnalysisFailure("score должен быть конечным числом 0–1 либо None")
    if not isinstance(finding.explanation, str) or not finding.explanation.strip():
        raise AnalysisFailure("Объяснение наблюдения обязательно")
    if not isinstance(finding.evidence, tuple):
        raise AnalysisFailure("evidence должен быть кортежем")
    for evidence in finding.evidence:
        _check_evidence(evidence, submission)


def validate_report(report: object, submission: Submission, context: AnalysisContext) -> None:
    if not isinstance(report, AnalysisReport):
        raise AnalysisFailure("Ожидается AnalysisReport")
    if (
        report.submission_id != submission.submission_id
        or report.submission_hash != submission_hash(submission)
    ):
        raise AnalysisFailure("Отчёт ссылается на другую версию сдачи")
    if report.config_hash != context.config_hash:
        raise AnalysisFailure("Отчёт использует другую конфигурацию")
    if not report.report_id or not report.analyzer_id or not report.analyzer_version:
        raise AnalysisFailure("Идентификаторы отчёта и анализатора обязательны")
    if type(report.review_required) is not bool:
        raise AnalysisFailure("review_required должен быть bool")
    try:
        created = datetime.fromisoformat(report.created_at)
    except (ValueError, TypeError) as exc:
        raise AnalysisFailure("Время отчёта имеет неверный формат") from exc
    if created.utcoffset() is None:
        raise AnalysisFailure("Часовой пояс времени отчёта обязателен")
    if not isinstance(report.findings, tuple):
        raise AnalysisFailure("findings должен быть кортежем")
    for finding in report.findings:
        _check_finding(finding, submission)


def make_report(
    submission: Submission,
    context: AnalysisContext,
    analyzer_id: str,
    analyzer_version: str,
    findings: tuple[Finding, ...],
    *,
    review_required: bool = False,
) -> AnalysisReport:
    report = AnalysisReport(
        report_id=str(uuid.uuid4()),
        submission_id=submission.submission_id,
        submission_hash=submission_hash(submission),
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        config_hash=context.config_hash,
        findings=findings,
        created_at=datetime.now(UTC).isoformat(),
        review_required=review_required,
    )
    validate_report(report, submission, context)
    return report


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AnalyzerFactory] = {}

    def register(self, name: str, factory: AnalyzerFactory) -> None:
        if not name.strip() or name in self._factories:
            raise AnalysisFailure(f"Требуется непустое уникальное имя анализатора: {name!r}")
        self._factories[name] = factory

    def __contains__(self, name: object) -> bool:
        return name in self._factories

    def create(self, name: str) -> Analyzer:
        try:
            factory = self._factories[name]
        except KeyError as exc:
            raise AnalysisFailure(f"Неизвестный анализатор: {name}") from exc
        analyzer = factory()
        if analyzer.analyzer_id != name:
            raise AnalysisFailure("Имя регистрации не совпадает с analyzer_id")
        return analyzer


class AnalysisService:
    def __init__(self, repository: SubmissionRepository, registry: AnalyzerRegistry) -> None:
        self.repository = repository
        self.registry = registry

    def run(
        self, submission_id: str, analyzer_name: str, context: AnalysisContext
    ) -> AnalysisReport:
        """Запускает анализатор по имени из реестра. Любой отказ — ``AnalysisFailure``."""
        submission = self.repository.get(submission_id)
        if submission is None:
            raise AnalysisFailure("Анализ возможен после приёма сдачи")
        if submission.assignment_id != context.assignment.assignment_id:
            raise AnalysisFailure("Требуется контекст соответствующего задания")
        try:
            analyzer = self.registry.create(analyzer_name)
            report = analyzer.analyze(submission, context)
        except AnalysisFailure:
            raise
        except Exception as exc:
            raise AnalysisFailure(
                f"Анализатор {analyzer_name} завершился ошибкой {type(exc).__name__}: {exc}"
            ) from exc
        validate_report(report, submission, context)
        if (
            report.analyzer_id != analyzer.analyzer_id
            or report.analyzer_version != analyzer.analyzer_version
        ):
            raise AnalysisFailure("Отчёт не соответствует вызванному анализатору")
        return report
