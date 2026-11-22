import pytest

from lab_checker.similarity import (
    InvalidSource,
    SimilarityConfig,
    TemplateRule,
    compare_features,
    extract_features,
    jaccard,
    source_tokens,
)

TEMPLATE = "from typing import Iterable\n"
BASE = TEMPLATE + (
    "\ndef solve(values):\n    total = 0\n    for value in values:\n"
    "        if value >= 0:\n            total += value * value\n    return total\n"
)
FORMATTED = TEMPLATE + (
    "\n# комментарий\ndef solve(values):\n    total=0\n    for value in values:\n"
    "        if value>=0: total+=value*value\n    return total\n"
)
RENAMED = TEMPLATE + (
    "\ndef solve(items):\n    result = 0\n    for item in items:\n"
    "        if item >= 0:\n            result += item * item\n    return result\n"
)
INDEPENDENT = TEMPLATE + "\ndef solve(values):\n    return sum(x ** 2 for x in values if x >= 0)\n"


def test_formatting_and_comments_do_not_change_features() -> None:
    assert (
        extract_features(BASE, TEMPLATE).features == extract_features(FORMATTED, TEMPLATE).features
    )
    assert source_tokens("x = 1 # comment\n") == source_tokens("x=1\n")


def test_exact_rename_and_independent_scores() -> None:
    base = extract_features(BASE, TEMPLATE)

    assert jaccard(base.features, base.features) == 1
    renamed_score = jaccard(base.features, extract_features(RENAMED, TEMPLATE).features)
    independent_score = jaccard(base.features, extract_features(INDEPENDENT, TEMPLATE).features)
    assert renamed_score is not None and 0 < renamed_score < 1
    assert independent_score is not None and independent_score < 1


def test_jaccard_empty_and_manual_examples() -> None:
    assert jaccard(frozenset(), frozenset()) is None
    assert jaccard(frozenset(), frozenset({(("NAME", "x"),)})) == 0
    left = frozenset({(("NAME", "a"),), (("NAME", "b"),), (("NAME", "c"),)})
    right = frozenset({(("NAME", "b"),), (("NAME", "c"),), (("NAME", "d"),)})
    assert jaccard(left, right) == jaccard(right, left) == 0.5


def test_template_windows_are_removed_without_bridge() -> None:
    source = "left = 1\n" + TEMPLATE + "right = 2\n"

    features = extract_features(source, TEMPLATE)

    assert features.template_ranges == ((2, 2),)
    assert [(item.start_line, item.end_line) for item in features.occurrences] == [(1, 1), (3, 3)]


def test_template_only_signal_disappears_after_exclusion() -> None:
    left = TEMPLATE + "x = 1\n"
    right = TEMPLATE + "y = 2\n"

    with_template = compare_features(
        "left",
        extract_features(left),
        "right",
        extract_features(right),
    )
    without_template = compare_features(
        "left",
        extract_features(left, TEMPLATE),
        "right",
        extract_features(right, TEMPLATE),
        left_template=TEMPLATE,
        right_template=TEMPLATE,
    )

    assert with_template.score == pytest.approx(0.25)
    assert without_template.score == 0
    assert without_template.evidence == ()
    assert len(without_template.templates[0].ranges) == 1


def test_evidence_uses_original_lines_and_is_deterministic() -> None:
    left = extract_features(BASE, TEMPLATE)
    right = extract_features(FORMATTED, TEMPLATE)

    first = compare_features("left", left, "right", right, evidence_limit=20)
    second = compare_features("left", left, "right", right, evidence_limit=20)

    assert first == second
    assert first.score == 1
    assert first.evidence
    for item in first.evidence:
        for evidence, source in ((item.left, BASE), (item.right, FORMATTED)):
            lines = source.splitlines()
            assert 1 <= evidence.start_line <= evidence.end_line <= len(lines)
            assert evidence.start_line != 1


def test_empty_features_are_insufficient_data() -> None:
    empty = extract_features("# только комментарий\n")

    result = compare_features("left", empty, "right", empty)

    assert result.score is None
    assert result.status == "insufficient_data"


def test_syntax_error_is_explicit() -> None:
    with pytest.raises(InvalidSource, match="Некорректный Python"):
        extract_features("def broken(:\n")


def test_config_hash_includes_template_and_parameters() -> None:
    config = SimilarityConfig(rules=(TemplateRule("assignment-01", TEMPLATE),))

    assert config.config_hash == SimilarityConfig(config.rules).config_hash
    assert config.config_hash != SimilarityConfig(config.rules, n=4).config_hash
    assert (
        config.config_hash
        != SimilarityConfig(rules=(TemplateRule("assignment-01", "return 0\n"),)).config_hash
    )
