import copy
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from conftest import TEMPLATE_CODE

from lab_checker.analysis import AnalysisContext, Analyzer, find_report_problems
from lab_checker.analyzers import LengthAnalyzer, TemplateAnalyzer
from lab_checker.models import AIDeclaration, AnalysisReport, Assignment, Evidence, Submission
from lab_checker.repositories import InMemorySubmissionRepository


def make_submission(text: str = "", code: str = "") -> Submission:
    return Submission(
        submission_id="sub-001",
        assignment_id="lab-01-sum",
        student_id="student-01",
        timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        text=text,
        code=code,
        ai_declaration=AIDeclaration(used=False),
    )


@pytest.fixture
def context(assignment: Assignment) -> AnalysisContext:
    return AnalysisContext(assignment=assignment, submissions=InMemorySubmissionRepository())


SUBMISSIONS = [
    make_submission(),
    make_submission(text="Пояснение\n\n", code=TEMPLATE_CODE),
    make_submission(text="a\r\nb\rc", code="\n\n" + TEMPLATE_CODE + "x = 1\n"),
    make_submission(code="def solve(numbers):  \n    return 1"),
]


@pytest.mark.parametrize(
    "analyzer", [LengthAnalyzer(), TemplateAnalyzer()], ids=lambda a: a.analyzer_id
)
@pytest.mark.parametrize("submission", SUBMISSIONS)
def test_analyzer_contract(
    analyzer: Analyzer, submission: Submission, context: AnalysisContext
) -> None:
    snapshot = copy.deepcopy(submission)

    report = analyzer.analyze(submission, context)

    assert isinstance(report, AnalysisReport)
    assert report.analyzer_id == analyzer.analyzer_id
    assert report.analyzer_version == analyzer.analyzer_version
    assert report.submission_id == submission.submission_id
    assert report.rubric_feedback
    assert find_report_problems(report, submission, analyzer) == []
    assert submission == snapshot


def test_length_counts_non_blank_lines_without_score(context: AnalysisContext) -> None:
    submission = make_submission(text="первая\n\n   \nвторая\r\nтретья", code="x = 1\n\n\ty = 2\n")

    report = LengthAnalyzer().analyze(submission, context)

    assert report.score is None
    assert report.similarity is None
    assert report.rubric_feedback[:2] == ("Непустых строк текста: 3.", "Непустых строк кода: 2.")


def test_template_evidence_refers_to_original_lines(context: AnalysisContext) -> None:
    code = (
        "# решение\n"
        "def solve(numbers):\n"
        "    return sum(numbers)\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    print(solve([1, 2, 3]))\n"
    )

    report = TemplateAnalyzer().analyze(make_submission(code=code), context)

    assert [(e.source, e.start_line, e.end_line) for e in report.evidence] == [
        ("code", 2, 2),
        ("code", 5, 6),
    ]
    lines = code.splitlines()
    assert lines[1] == "def solve(numbers):"
    assert lines[4:6] == ['if __name__ == "__main__":', "    print(solve([1, 2, 3]))"]
    assert report.similarity == pytest.approx(3 / 5)
    assert report.score is None
    assert any("не является нарушением" in item for item in report.rubric_feedback)


def test_template_requires_exact_line_match(context: AnalysisContext) -> None:
    report = TemplateAnalyzer().analyze(
        make_submission(code="def solve(numbers):  \n  pass\n"), context
    )

    assert report.similarity == 0.0
    assert report.evidence == ()


def test_full_template_copy_has_full_similarity(context: AnalysisContext) -> None:
    report = TemplateAnalyzer().analyze(make_submission(code=TEMPLATE_CODE), context)

    assert report.similarity == 1.0
    assert [(e.start_line, e.end_line) for e in report.evidence] == [(1, 2), (5, 6)]


def test_template_on_empty_code_is_undefined(context: AnalysisContext) -> None:
    report = TemplateAnalyzer().analyze(make_submission(code="\n   \n"), context)

    assert report.similarity is None
    assert report.evidence == ()


def test_template_without_assignment_template(context: AnalysisContext) -> None:
    no_template = replace(context, assignment=replace(context.assignment, template_code=""))

    report = TemplateAnalyzer().analyze(make_submission(code="x = 1\n"), no_template)

    assert report.similarity == 0.0
    assert report.evidence == ()


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (Evidence("code", 1, 2, "x"), []),
        (Evidence("code", 0, 1, "x"), ["вне строк"]),
        (Evidence("code", 2, 1, "x"), ["вне строк"]),
        (Evidence("code", 1, 3, "x"), ["вне строк"]),
        (Evidence("text", 1, 1, "x"), ["вне строк"]),
    ],
)
def test_evidence_range_validation(evidence: Evidence, expected: list[str]) -> None:
    submission = make_submission(code="a\nb\n")
    analyzer = LengthAnalyzer()
    report = AnalysisReport(
        submission_id=submission.submission_id,
        analyzer_id=analyzer.analyzer_id,
        analyzer_version=analyzer.analyzer_version,
        score=None,
        similarity=None,
        rubric_feedback=("x",),
        evidence=(evidence,),
    )

    problems = find_report_problems(report, submission, analyzer)

    assert len(problems) == len(expected)
    assert all(fragment in problem for fragment, problem in zip(expected, problems, strict=True))
