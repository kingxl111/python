"""Встроенные анализаторы."""

from lab_checker.analysis import AnalysisContext, make_report
from lab_checker.errors import AnalysisFailure
from lab_checker.models import AnalysisReport, Evidence, Finding, Submission


def nonempty_line_numbers(text: str) -> tuple[int, ...]:
    return tuple(number for number, line in enumerate(text.splitlines(), 1) if line.strip())


def template_ranges(source_code: str, template: str) -> tuple[tuple[int, int], ...]:
    """Диапазоны строк кода, где шаблон совпадает целиком; пробелы не нормализуются."""
    if not template.strip():
        return ()
    source_lines = source_code.splitlines()
    template_lines = template.splitlines()
    width = len(template_lines)
    return tuple(
        (index + 1, index + width)
        for index in range(len(source_lines) - width + 1)
        if source_lines[index : index + width] == template_lines
    )


class LengthAnalyzer:
    analyzer_id = "length"
    analyzer_version = "1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        text_lines = nonempty_line_numbers(submission.text)
        code_lines = nonempty_line_numbers(submission.code)
        evidence = tuple(
            Evidence(submission.submission_id, "text", n, n) for n in text_lines
        ) + tuple(Evidence(submission.submission_id, "code", n, n) for n in code_lines)
        finding = Finding(
            kind="rubric_feedback",
            score=None,
            evidence=evidence,
            explanation=(
                f"Непустые строки: text={len(text_lines)}, code={len(code_lines)}. "
                "Длина не оценивает корректность решения."
            ),
        )
        return make_report(submission, context, self.analyzer_id, self.analyzer_version, (finding,))


class TemplateAnalyzer:
    analyzer_id = "template"
    analyzer_version = "1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        if submission.assignment_id != context.assignment.assignment_id:
            raise AnalysisFailure("Контекст относится к другому заданию")
        ranges = template_ranges(submission.code, context.assignment.allowed_template)
        evidence = tuple(
            Evidence(submission.submission_id, "code", start, end) for start, end in ranges
        )
        explanation = (
            f"Найдены разрешённые блоки шаблона: {len(ranges)}. "
            "Это допустимое совпадение, а не основание санкции."
            if ranges
            else "Точное совпадение с разрешённым шаблоном не найдено. "
            "Нечёткое сходство не проверялось."
        )
        finding = Finding("similarity", None, evidence, explanation)
        return make_report(submission, context, self.analyzer_id, self.analyzer_version, (finding,))
