import copy

import pytest
from conftest import changed

from lab_checker.analysis import AnalysisContext, validate_report
from lab_checker.bootstrap import AppConfig, build_application
from lab_checker.comparison import ComparisonService
from lab_checker.errors import AnalysisFailure
from lab_checker.models import Assignment, Submission
from lab_checker.parsing import parse_submission
from lab_checker.repositories import InMemorySubmissionRepository
from lab_checker.similarity import SimilarityConfig, TemplateRule
from lab_checker.similarity_analyzer import SimilarityAnalyzer

TEMPLATE = "from typing import Iterable\n"
BASE = TEMPLATE + "\ndef solve(values):\n    return sum(x * x for x in values if x >= 0)\n"
COPY = BASE
FORMATTED = (
    TEMPLATE + "\n# comment\ndef solve(values):\n    return sum(x*x for x in values if x>=0)\n"
)
UNRELATED = "print('unrelated')\n"


def make_submission(
    submission_id: str,
    student_id: str,
    code: str = BASE,
    assignment_id: str = "assignment-01",
) -> Submission:
    return parse_submission(
        changed(
            submission_id=submission_id,
            student_id=student_id,
            assignment_id=assignment_id,
            code=code,
        )
    )


def make_service(
    submissions: list[Submission], config: SimilarityConfig | None = None
) -> ComparisonService:
    repository = InMemorySubmissionRepository()
    for submission in submissions:
        repository.add(submission)
    if config is None:
        config = SimilarityConfig(
            rules=(
                TemplateRule("assignment-01", TEMPLATE),
                TemplateRule("assignment-02", TEMPLATE),
            )
        )
    return ComparisonService(repository, config)


def test_top_k_filters_self_assignment_and_student_version() -> None:
    query = make_submission("query", "alice")
    service = make_service(
        [
            query,
            make_submission("copy", "bob", COPY),
            make_submission("formatted", "carol", FORMATTED),
            make_submission("version", "alice", FORMATTED),
            make_submission("other", "dave", COPY, "assignment-02"),
            make_submission("unrelated", "erin", UNRELATED),
        ]
    )

    result = service.top_k("query", 3)

    assert [item.right_id for item in result.candidates] == ["copy", "formatted", "unrelated"]
    assert [item.score for item in result.candidates[:2]] == [1, 1]
    assert result.candidates[2].score == 0
    assert result.examined == 3


def test_full_and_index_keep_all_positive_candidates() -> None:
    service = make_service(
        [
            make_submission("query", "alice"),
            make_submission("copy", "bob", COPY),
            make_submission("formatted", "carol", FORMATTED),
            make_submission("unrelated", "dave", UNRELATED),
        ]
    )

    full = service.top_k("query", 10, "full")
    indexed = service.top_k("query", 10, "index")
    reference = {item.right_id for item in full.candidates if (item.score or 0) > 0}

    assert {item.right_id for item in indexed.candidates} == reference
    assert "unrelated" in {item.right_id for item in full.candidates}
    assert indexed.examined < full.examined


def test_pair_cache_uses_content_config_and_orientation() -> None:
    service = make_service(
        [make_submission("left", "alice"), make_submission("right", "bob", FORMATTED)]
    )

    first = service.compare("left", "right")

    assert service.compare("left", "right") is first
    assert service.cache_entries == 1
    service.compare("right", "left")
    assert service.cache_entries == 2
    changed_content = make_service(
        [make_submission("left", "alice"), make_submission("right", "bob", UNRELATED)]
    )
    assert changed_content.compare("left", "right") != first


def test_index_version_changes_with_corpus_and_config() -> None:
    query = make_submission("query", "alice")
    other = make_submission("other", "bob", FORMATTED)
    service = make_service([query, other])
    with_new_document = make_service([query, other, make_submission("new", "carol", UNRELATED)])
    with_new_template = make_service(
        [query, other],
        SimilarityConfig(rules=(TemplateRule("assignment-01", "return 0\n"),)),
    )

    assert service.index.version != with_new_document.index.version
    assert service.index.version != with_new_template.index.version


def test_invalid_source_does_not_hide_other_results() -> None:
    service = make_service(
        [
            make_submission("query", "alice"),
            make_submission("broken", "bob", "def broken(:\n"),
            make_submission("copy", "carol", COPY),
        ]
    )

    comparison = service.compare("query", "broken")
    search = service.top_k("query")

    assert comparison.status == "invalid_source"
    assert comparison.score is None
    assert [item.right_id for item in search.candidates] == ["copy"]
    assert [error.submission_id for error in search.errors] == ["broken"]


def test_empty_union_is_not_ranked() -> None:
    service = make_service(
        [
            make_submission("empty-1", "alice", "# one\n"),
            make_submission("empty-2", "bob", "# two\n"),
        ]
    )

    assert service.compare("empty-1", "empty-2").status == "insufficient_data"
    result = service.top_k("empty-1")
    assert result.candidates == ()
    assert result.insufficient_data == 1


def test_similarity_analyzer_uses_common_report_contract() -> None:
    query = make_submission("query", "alice")
    service = make_service([query, make_submission("copy", "bob", COPY)])
    context = AnalysisContext(Assignment("assignment-01", TEMPLATE, ()))

    report = SimilarityAnalyzer(service).analyze(query, context)

    validate_report(report, query, context)
    assert report.analyzer_id == "similarity"
    assert report.review_required is True
    assert report.findings[0].score == 1
    assert all(evidence.submission_id == "query" for evidence in report.findings[0].evidence)


def test_similarity_analyzer_rejects_stale_template() -> None:
    query = make_submission("query", "alice")
    analyzer = SimilarityAnalyzer(make_service([query]))

    with pytest.raises(AnalysisFailure, match="устаревший шаблон"):
        analyzer.analyze(query, AnalysisContext(Assignment("assignment-01", "new\n", ())))


def test_similarity_is_registered_without_changing_analysis_service() -> None:
    config = SimilarityConfig(rules=(TemplateRule("assignment-01", TEMPLATE),), threshold=0.9)
    app = build_application(AppConfig(analyzers=("similarity",), similarity=config))
    app.submission_service.accept_submission(make_submission("query", "alice"))
    app.submission_service.accept_submission(make_submission("copy", "bob", COPY))
    context = AnalysisContext(Assignment("assignment-01", TEMPLATE, ()))

    report = app.analysis_service.run("query", "similarity", context)

    assert report.review_required is True
    assert report.findings[0].kind == "similarity"


def test_report_rejects_mismatched_assignment() -> None:
    submission = make_submission("query", "alice")
    analyzer = SimilarityAnalyzer(make_service([submission]))

    with pytest.raises(AnalysisFailure, match="другому заданию"):
        analyzer.analyze(submission, AnalysisContext(Assignment("other", "", ())))


def test_input_object_is_not_modified() -> None:
    raw = changed(submission_id="query", student_id="alice", code=BASE)
    before = copy.deepcopy(raw)

    parsed = parse_submission(raw)

    assert parsed.code == BASE
    assert raw == before


def test_config_can_disable_template_exclusion() -> None:
    left = make_submission("left", "alice", TEMPLATE + "x = 1\n")
    right = make_submission("right", "bob", TEMPLATE + "y = 2\n")
    rules = (TemplateRule("assignment-01", TEMPLATE),)
    excluded = make_service([left, right], SimilarityConfig(rules=rules))
    included = make_service([left, right], SimilarityConfig(rules=rules, exclude_template=False))

    assert excluded.compare("left", "right").score == 0
    assert included.compare("left", "right").score == pytest.approx(0.25)
    assert excluded.config.config_hash != included.config.config_hash
