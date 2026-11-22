import pytest

from lab_checker.evaluation import choose_threshold, classification_metrics


def test_confusion_matrix_and_metrics() -> None:
    rows = [(True, 0.9)] * 18 + [(False, 0.8)] * 6 + [(True, 0.2)] * 12

    result = classification_metrics(rows, 0.5)

    assert (result.tp, result.fp, result.fn, result.tn) == (18, 6, 12, 0)
    assert result.precision == 0.75
    assert result.recall_defined == 0.6
    assert result.f1_defined == pytest.approx(2 / 3)
    assert result.abstention_rate == 0


def test_abstentions_are_not_hidden_by_conditional_recall() -> None:
    result = classification_metrics([(True, None), (True, 0.9), (False, 0.1)], 0.5)

    assert result.recall_defined == 1
    assert result.recall_all_positives == 0.5
    assert result.abstention_rate == pytest.approx(1 / 3)
    assert result.positive_abstentions == 1


def test_zero_denominator_is_unknown_not_zero() -> None:
    result = classification_metrics([], 0.5)

    assert result.precision is None
    assert result.recall_defined is None
    assert result.f1_defined is None
    assert result.abstention_rate is None


def test_threshold_uses_max_f1() -> None:
    rows = [(True, 0.8), (True, 0.2), (False, 0.5), (False, 0.1)]

    assert choose_threshold(rows) == 0.2
    assert classification_metrics(rows, choose_threshold(rows)).f1_defined == 0.8


def test_threshold_with_only_abstentions_disables_signals() -> None:
    assert choose_threshold([(True, None), (False, None)]) == 1.000001
