"""Встроенные анализаторы."""

from collections.abc import Iterable

from lab_checker.analysis import AnalysisContext
from lab_checker.models import AnalysisReport, Evidence, Submission, split_lines


def _count_non_blank(content: str) -> int:
    return sum(1 for line in split_lines(content) if line.strip())


def _consecutive_ranges(numbers: Iterable[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for number in numbers:
        if ranges and ranges[-1][1] == number - 1:
            ranges[-1] = (ranges[-1][0], number)
        else:
            ranges.append((number, number))
    return ranges


class LengthAnalyzer:
    """Считает непустые строки текста и кода. Оценку не выставляет."""

    analyzer_id = "length"
    analyzer_version = "1.0.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        text_lines = _count_non_blank(submission.text)
        code_lines = _count_non_blank(submission.code)
        return AnalysisReport(
            submission_id=submission.submission_id,
            analyzer_id=self.analyzer_id,
            analyzer_version=self.analyzer_version,
            score=None,
            similarity=None,
            rubric_feedback=(
                f"Непустых строк текста: {text_lines}.",
                f"Непустых строк кода: {code_lines}.",
                "Объём не определяет качество работы, поэтому оценка не выставляется.",
            ),
        )


class TemplateAnalyzer:
    """Находит в коде строки, точно совпадающие со строками разрешённого шаблона.

    ``similarity`` — доля непустых строк кода, совпавших с шаблоном. Пустые строки
    не учитываются ни в коде, ни в шаблоне.
    """

    analyzer_id = "template"
    analyzer_version = "1.0.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        template = {line for line in split_lines(context.assignment.template_code) if line.strip()}
        code_lines = split_lines(submission.code)
        candidates = [number for number, line in enumerate(code_lines, start=1) if line.strip()]
        matched = [number for number in candidates if code_lines[number - 1] in template]

        if not candidates:
            similarity = None
            feedback = "В коде нет непустых строк: сходство с шаблоном не вычисляется."
        elif not template:
            similarity = 0.0
            feedback = "У задания нет разрешённого шаблона: совпадений нет."
        else:
            similarity = len(matched) / len(candidates)
            feedback = (
                f"С разрешённым шаблоном совпадает {len(matched)} из {len(candidates)} "
                "непустых строк кода."
            )
        rubric_feedback = [feedback]
        if matched:
            rubric_feedback.append(
                "Использование разрешённого шаблона допустимо: совпадение не является нарушением."
            )

        evidence = tuple(
            Evidence(
                source="code",
                start_line=start,
                end_line=end,
                note="строки совпадают с разрешённым шаблоном задания",
            )
            for start, end in _consecutive_ranges(matched)
        )
        return AnalysisReport(
            submission_id=submission.submission_id,
            analyzer_id=self.analyzer_id,
            analyzer_version=self.analyzer_version,
            score=None,
            similarity=similarity,
            rubric_feedback=tuple(rubric_feedback),
            evidence=evidence,
        )
