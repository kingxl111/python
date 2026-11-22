"""Токеновые признаки, исключение шаблона и попарный коэффициент Jaccard."""

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import Literal

from lab_checker.hashing import stable_hash
from lab_checker.models import Evidence
from lab_checker.templates import template_ranges

type TokenValue = tuple[str, str]
type Feature = tuple[TokenValue, ...]
type SimilarityStatus = Literal["ok", "insufficient_data", "invalid_source"]


class InvalidSource(ValueError):
    """Исходный код нельзя разобрать без его исполнения."""


@dataclass(frozen=True, slots=True)
class TemplateRule:
    assignment_id: str
    allowed_template: str


@dataclass(frozen=True, slots=True)
class SimilarityConfig:
    rules: tuple[TemplateRule, ...] = ()
    n: int = 3
    exclude_template: bool = True
    evidence_limit: int = 3
    top_k: int = 3
    threshold: float = 0.2

    def __post_init__(self) -> None:
        if type(self.n) is not int or self.n < 1:
            raise ValueError("n должен быть положительным int")
        if type(self.evidence_limit) is not int or self.evidence_limit < 0:
            raise ValueError("evidence_limit должен быть неотрицательным int")
        if type(self.top_k) is not int or self.top_k < 1:
            raise ValueError("top_k должен быть положительным int")
        if not 0 <= self.threshold <= 1:
            raise ValueError("threshold должен быть в диапазоне 0–1")
        assignment_ids = [rule.assignment_id for rule in self.rules]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("Шаблон задания описан повторно")

    def payload(self) -> dict[str, object]:
        return {
            "method": "token-ngram-jaccard",
            "implementation": "similarity-1.0",
            "n": self.n,
            "exclude_template": self.exclude_template,
            "evidence_limit": self.evidence_limit,
            "top_k": self.top_k,
            "threshold": self.threshold,
            "rules": [
                {"assignment_id": rule.assignment_id, "allowed_template": rule.allowed_template}
                for rule in sorted(self.rules, key=lambda item: item.assignment_id)
            ],
        }

    @property
    def config_hash(self) -> str:
        return stable_hash(self.payload())

    def template_for(self, assignment_id: str) -> str:
        for rule in self.rules:
            if rule.assignment_id == assignment_id:
                return rule.allowed_template
        return ""


@dataclass(frozen=True, slots=True)
class LocatedToken:
    value: TokenValue
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class Occurrence:
    feature: Feature
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class SourceFeatures:
    features: frozenset[Feature]
    occurrences: tuple[Occurrence, ...]
    template_ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class PairEvidence:
    feature: Feature
    left: Evidence
    right: Evidence


@dataclass(frozen=True, slots=True)
class TemplateEvidence:
    submission_id: str
    ranges: tuple[Evidence, ...]
    template_hash: str


@dataclass(frozen=True, slots=True)
class PairResult:
    left_id: str
    right_id: str
    score: float | None
    status: SimilarityStatus
    evidence: tuple[PairEvidence, ...]
    templates: tuple[TemplateEvidence, ...]
    explanation: str


_SKIPPED_TOKENS = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
    tokenize.ENCODING,
}


def source_tokens(source: str) -> tuple[LocatedToken, ...]:
    """Читает значимые токены; ``ast.parse`` только проверяет синтаксис."""
    try:
        ast.parse(source)
        result = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in _SKIPPED_TOKENS:
                continue
            if token.type == tokenize.ERRORTOKEN:
                raise InvalidSource("Недопустимый токен в исходном коде")
            result.append(
                LocatedToken(
                    (tokenize.tok_name[token.type], token.string),
                    token.start[0],
                    token.end[0],
                )
            )
        return tuple(result)
    except (SyntaxError, tokenize.TokenError) as exc:
        raise InvalidSource(f"Некорректный Python: {exc}") from exc


def ngram_occurrences(tokens: tuple[LocatedToken, ...], n: int = 3) -> tuple[Occurrence, ...]:
    if type(n) is not int or n < 1:
        raise ValueError("n должен быть положительным int")
    return tuple(
        Occurrence(
            tuple(token.value for token in tokens[index : index + n]),
            tokens[index].start_line,
            tokens[index + n - 1].end_line,
        )
        for index in range(max(0, len(tokens) - n + 1))
    )


def _overlaps_template(occurrence: Occurrence, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(
        occurrence.start_line <= end and start <= occurrence.end_line for start, end in ranges
    )


def extract_features(source: str, template: str = "", n: int = 3) -> SourceFeatures:
    """Строит окна до исключения шаблона, сохраняя координаты оригинала."""
    ranges = template_ranges(source, template)
    occurrences = tuple(
        occurrence
        for occurrence in ngram_occurrences(source_tokens(source), n)
        if not _overlaps_template(occurrence, ranges)
    )
    return SourceFeatures(
        frozenset(occurrence.feature for occurrence in occurrences), occurrences, ranges
    )


def jaccard(left: frozenset[Feature], right: frozenset[Feature]) -> float | None:
    intersection = len(left & right)
    union = len(left) + len(right) - intersection
    return intersection / union if union else None


def _first_occurrences(
    features: SourceFeatures,
) -> dict[Feature, Occurrence]:
    result: dict[Feature, Occurrence] = {}
    for occurrence in features.occurrences:
        current = result.get(occurrence.feature)
        if current is None or (occurrence.start_line, occurrence.end_line) < (
            current.start_line,
            current.end_line,
        ):
            result[occurrence.feature] = occurrence
    return result


def pair_evidence(
    left_id: str,
    left: SourceFeatures,
    right_id: str,
    right: SourceFeatures,
    limit: int,
) -> tuple[PairEvidence, ...]:
    shared = left.features & right.features
    if not shared or limit == 0:
        return ()
    left_occurrences = _first_occurrences(left)
    right_occurrences = _first_occurrences(right)
    result = []
    for feature in sorted(shared)[:limit]:
        left_occurrence = left_occurrences[feature]
        right_occurrence = right_occurrences[feature]
        result.append(
            PairEvidence(
                feature,
                Evidence(left_id, "code", left_occurrence.start_line, left_occurrence.end_line),
                Evidence(right_id, "code", right_occurrence.start_line, right_occurrence.end_line),
            )
        )
    return tuple(result)


def template_evidence(
    submission_id: str, features: SourceFeatures, template: str
) -> TemplateEvidence:
    return TemplateEvidence(
        submission_id,
        tuple(
            Evidence(submission_id, "code", start, end) for start, end in features.template_ranges
        ),
        stable_hash({"template": template}),
    )


def compare_features(
    left_id: str,
    left: SourceFeatures,
    right_id: str,
    right: SourceFeatures,
    *,
    left_template: str = "",
    right_template: str = "",
    evidence_limit: int = 3,
) -> PairResult:
    score = jaccard(left.features, right.features)
    templates = (
        template_evidence(left_id, left, left_template),
        template_evidence(right_id, right, right_template),
    )
    if score is None:
        return PairResult(
            left_id,
            right_id,
            None,
            "insufficient_data",
            (),
            templates,
            "Объединение признаков пусто: данных для сходства недостаточно.",
        )
    evidence = pair_evidence(left_id, left, right_id, right, evidence_limit)
    excluded = len(left.template_ranges) + len(right.template_ranges)
    return PairResult(
        left_id,
        right_id,
        score,
        "ok",
        evidence,
        templates,
        f"Jaccard по множествам токеновых n-грамм; исключено блоков шаблона: {excluded}. "
        "Score является сигналом для ручного разбора, а не доказательством нарушения.",
    )
