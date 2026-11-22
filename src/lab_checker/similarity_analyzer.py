"""Адаптер сервиса сравнения к общему контракту ``Analyzer``."""

from lab_checker.analysis import AnalysisContext, make_report
from lab_checker.comparison import ComparisonService
from lab_checker.errors import AnalysisFailure
from lab_checker.models import AnalysisReport, Finding, Submission


class SimilarityAnalyzer:
    analyzer_id = "similarity"
    analyzer_version = "1.0"

    def __init__(self, service: ComparisonService) -> None:
        self._service = service

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        if submission.assignment_id != context.assignment.assignment_id:
            raise AnalysisFailure("Контекст относится к другому заданию")
        configured = self._service.config.template_for(submission.assignment_id)
        if configured != context.assignment.allowed_template:
            raise AnalysisFailure("Конфигурация сходства содержит устаревший шаблон")
        search = self._service.top_k(submission.submission_id, strategy="index")
        findings: list[Finding] = []
        for candidate in search.candidates:
            right_ranges = [
                (item.right.start_line, item.right.end_line) for item in candidate.evidence
            ]
            evidence = tuple(item.left for item in candidate.evidence)
            template_ranges = candidate.templates[0].ranges if candidate.templates else ()
            evidence += template_ranges
            findings.append(
                Finding(
                    "similarity",
                    candidate.score,
                    evidence,
                    f"Кандидат {candidate.right_id}; его диапазоны evidence: {right_ranges}. "
                    f"{candidate.explanation}",
                )
            )
        findings.extend(
            Finding("processing_error", None, (), f"{error.submission_id}: {error.message}")
            for error in search.errors
        )
        if not search.candidates and not search.errors:
            findings.append(
                Finding(
                    "similarity",
                    None,
                    (),
                    "Кандидаты с определённым сходством не найдены; "
                    f"неопределённых сравнений: {search.insufficient_data}.",
                )
            )
        review_required = bool(search.errors) or any(
            candidate.score is not None and candidate.score >= self._service.config.threshold
            for candidate in search.candidates
        )
        return make_report(
            submission,
            context,
            self.analyzer_id,
            self.analyzer_version,
            tuple(findings),
            review_required=review_required,
        )
