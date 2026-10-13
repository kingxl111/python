from dataclasses import replace

import pytest

from lab_checker.analysis import AnalysisContext, Analyzer, validate_report
from lab_checker.analyzers import (
    LengthAnalyzer,
    TemplateAnalyzer,
    nonempty_line_numbers,
    template_ranges,
)
from lab_checker.errors import AnalysisFailure
from lab_checker.models import Assignment, Submission


@pytest.mark.parametrize("analyzer", [LengthAnalyzer(), TemplateAnalyzer()])
def test_analyzer_contract(
    analyzer: Analyzer, submission: Submission, context: AnalysisContext
) -> None:
    first = analyzer.analyze(submission, context)
    second = analyzer.analyze(submission, context)

    validate_report(first, submission, context)
    assert first.findings == second.findings
    assert first.submission_hash == second.submission_hash
    assert first.config_hash == second.config_hash
    assert first.report_id != second.report_id
    assert (first.analyzer_id, first.analyzer_version) == (
        analyzer.analyzer_id,
        analyzer.analyzer_version,
    )


def test_length_analyzer(submission: Submission, context: AnalysisContext) -> None:
    (finding,) = LengthAnalyzer().analyze(submission, context).findings

    assert finding.kind == "rubric_feedback"
    assert finding.score is None
    assert finding.explanation.startswith("Непустые строки: text=1, code=3.")
    assert [(e.field, e.start_line) for e in finding.evidence] == [
        ("text", 1),
        ("code", 1),
        ("code", 3),
        ("code", 4),
    ]


def test_template_analyzer_finds_allowed_block(
    submission: Submission, context: AnalysisContext
) -> None:
    (finding,) = TemplateAnalyzer().analyze(submission, context).findings

    assert finding.kind == "similarity"
    assert finding.score is None
    assert [(e.start_line, e.end_line) for e in finding.evidence] == [(1, 1)]


def test_template_analyzer_without_match(submission: Submission, context: AnalysisContext) -> None:
    other = replace(submission, code="print(1)\n")

    (finding,) = TemplateAnalyzer().analyze(other, context).findings

    assert finding.evidence == ()
    assert "не найдено" in finding.explanation


def test_template_analyzer_rejects_other_assignment(submission: Submission) -> None:
    context = AnalysisContext(Assignment("assignment-02", "", ()))

    with pytest.raises(AnalysisFailure):
        TemplateAnalyzer().analyze(submission, context)


def test_line_helpers() -> None:
    assert nonempty_line_numbers("a\n\n  \nb\r\nc") == (1, 4, 5)
    assert template_ranges("a\nb\na\nb\n", "a\nb\n") == ((1, 2), (3, 4))
    assert template_ranges("a\n", "") == ()
    assert template_ranges("a\n", "a\nb\n") == ()
