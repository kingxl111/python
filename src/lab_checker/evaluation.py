"""Выбор порога и метрики размеченных отношений происхождения."""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Literal

from lab_checker.comparison import ComparisonService
from lab_checker.corpus import CorpusManifest, LabelledPair, SplitName
from lab_checker.similarity import SimilarityStatus


@dataclass(frozen=True, slots=True)
class Metrics:
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float | None
    recall_defined: float | None
    f1_defined: float | None
    abstention_rate: float | None
    positive_abstentions: int
    recall_all_positives: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScoredPair:
    left_id: str
    right_id: str
    split: SplitName
    derivation_relation: bool
    template_only: bool
    score: float | None
    status: SimilarityStatus


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def classification_metrics(rows: Iterable[tuple[bool, float | None]], threshold: float) -> Metrics:
    """Матрица считается на определённых score, отказы показываются отдельно."""
    values = tuple(rows)
    tp = fp = fn = tn = abstentions = positive_abstentions = positives = 0
    for label, score in values:
        positives += bool(label)
        if score is None:
            abstentions += 1
            positive_abstentions += bool(label)
            continue
        predicted = score >= threshold
        if label and predicted:
            tp += 1
        elif label:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    return Metrics(
        tp,
        fp,
        fn,
        tn,
        _ratio(tp, tp + fp),
        _ratio(tp, tp + fn),
        _ratio(2 * tp, 2 * tp + fp + fn),
        _ratio(abstentions, len(values)),
        positive_abstentions,
        _ratio(tp, positives),
    )


def choose_threshold(rows: Iterable[tuple[bool, float | None]]) -> float:
    """Максимизирует F1 на настройке; при равенстве выбирает больший порог."""
    values = tuple(rows)
    thresholds = sorted({0.0, 1.000001} | {score for _, score in values if score is not None})
    candidates = [
        (threshold, classification_metrics(values, threshold)) for threshold in thresholds
    ]
    return max(
        candidates,
        key=lambda item: (
            item[1].f1_defined if item[1].f1_defined is not None else -1,
            item[0],
        ),
    )[0]


def score_pairs(
    service: ComparisonService, pairs: Iterable[LabelledPair], manifest: CorpusManifest
) -> tuple[ScoredPair, ...]:
    entries = {entry.submission_id: entry for entry in manifest.entries}
    result = []
    for pair in pairs:
        comparison = service.compare(pair.left_id, pair.right_id)
        result.append(
            ScoredPair(
                pair.left_id,
                pair.right_id,
                entries[pair.left_id].split,
                pair.derivation_relation,
                pair.template_only,
                comparison.score,
                comparison.status,
            )
        )
    return tuple(result)


def metric_rows(pairs: Iterable[ScoredPair], split: SplitName) -> list[tuple[bool, float | None]]:
    return [(pair.derivation_relation, pair.score) for pair in pairs if pair.split == split]


def classification_errors(
    pairs: Iterable[ScoredPair], split: SplitName, threshold: float
) -> tuple[dict[str, object], ...]:
    errors = []
    for pair in pairs:
        if pair.split != split or pair.score is None:
            continue
        predicted = pair.score >= threshold
        if predicted == pair.derivation_relation:
            continue
        kind: Literal["FP", "FN"] = "FP" if predicted else "FN"
        errors.append(
            {
                "left_id": pair.left_id,
                "right_id": pair.right_id,
                "kind": kind,
                "score": pair.score,
                "threshold": threshold,
                "derivation_relation": pair.derivation_relation,
                "template_only": pair.template_only,
            }
        )
    return tuple(errors)
