"""Сервис сравнения, кеш результатов и версионируемый инвертированный индекс."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol

from lab_checker.hashing import stable_hash, submission_hash
from lab_checker.models import Submission
from lab_checker.similarity import (
    Feature,
    InvalidSource,
    PairResult,
    SimilarityConfig,
    SourceFeatures,
    compare_features,
    extract_features,
)

RetrievalStrategy = Literal["full", "index"]
INDEX_IMPLEMENTATION = "token-postings-1.0"


class SubmissionCatalog(Protocol):
    def get(self, submission_id: str) -> Submission | None: ...

    def iter(self) -> Iterator[Submission]: ...


@dataclass(frozen=True, slots=True)
class ComparisonError:
    submission_id: str
    message: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    query_id: str
    strategy: RetrievalStrategy
    candidates: tuple[PairResult, ...]
    examined: int
    insufficient_data: int
    errors: tuple[ComparisonError, ...]
    index_version: str


class TokenIndex:
    """Хранит ``3-грамма -> сдачи`` без отсечения частых признаков."""

    def __init__(
        self,
        documents: tuple[Submission, ...],
        features: dict[str, SourceFeatures],
        config: SimilarityConfig,
    ) -> None:
        postings: dict[Feature, set[str]] = {}
        for submission_id, source_features in features.items():
            for feature in source_features.features:
                postings.setdefault(feature, set()).add(submission_id)
        self._postings = {feature: frozenset(ids) for feature, ids in postings.items()}
        self.version = stable_hash(
            {
                "implementation": INDEX_IMPLEMENTATION,
                "config": config.payload(),
                "documents": sorted(
                    (item.submission_id, submission_hash(item)) for item in documents
                ),
            }
        )

    @property
    def postings_count(self) -> int:
        return len(self._postings)

    @property
    def references_count(self) -> int:
        return sum(len(ids) for ids in self._postings.values())

    def candidates(self, features: SourceFeatures) -> frozenset[str]:
        result: set[str] = set()
        for feature in features.features:
            result.update(self._postings.get(feature, ()))
        return frozenset(result)


class ComparisonService:
    """Работает с неизменяемым снимком каталога; новый корпус требует нового сервиса."""

    def __init__(self, catalog: SubmissionCatalog, config: SimilarityConfig) -> None:
        self.config = config
        self._documents = tuple(sorted(catalog.iter(), key=lambda item: item.submission_id))
        self._by_id = {item.submission_id: item for item in self._documents}
        self._hashes = {item.submission_id: submission_hash(item) for item in self._documents}
        if len(self._by_id) != len(self._documents):
            raise ValueError("Каталог содержит повторный submission_id")
        self._features: dict[str, SourceFeatures] = {}
        self._errors: dict[str, str] = {}
        for submission in self._documents:
            try:
                template = (
                    config.template_for(submission.assignment_id) if config.exclude_template else ""
                )
                self._features[submission.submission_id] = extract_features(
                    submission.code, template, config.n
                )
            except InvalidSource as exc:
                self._errors[submission.submission_id] = str(exc)
        self.index = TokenIndex(self._documents, self._features, config)
        self._pair_cache: dict[str, PairResult] = {}

    @property
    def document_count(self) -> int:
        return len(self._documents)

    @property
    def cache_entries(self) -> int:
        return len(self._pair_cache)

    def clear_pair_cache(self) -> None:
        self._pair_cache.clear()

    def _get(self, submission_id: str) -> Submission:
        try:
            return self._by_id[submission_id]
        except KeyError as exc:
            raise KeyError(f"Неизвестная сдача: {submission_id}") from exc

    def _cache_key(self, left: Submission, right: Submission) -> str:
        return stable_hash(
            {
                "left_submission_hash": self._hashes[left.submission_id],
                "right_submission_hash": self._hashes[right.submission_id],
                "config": self.config.payload(),
            }
        )

    def compare(self, left_id: str, right_id: str) -> PairResult:
        left = self._get(left_id)
        right = self._get(right_id)
        key = self._cache_key(left, right)
        cached = self._pair_cache.get(key)
        if cached is not None:
            return cached
        messages = [
            f"{item.submission_id}: {self._errors[item.submission_id]}"
            for item in (left, right)
            if item.submission_id in self._errors
        ]
        if messages:
            result = PairResult(
                left_id,
                right_id,
                None,
                "invalid_source",
                (),
                (),
                "; ".join(messages),
            )
        else:
            result = compare_features(
                left_id,
                self._features[left_id],
                right_id,
                self._features[right_id],
                left_template=self.config.template_for(left.assignment_id),
                right_template=self.config.template_for(right.assignment_id),
                evidence_limit=self.config.evidence_limit,
            )
        self._pair_cache[key] = result
        return result

    @staticmethod
    def eligible(left: Submission, right: Submission) -> bool:
        return (
            left.submission_id != right.submission_id
            and left.assignment_id == right.assignment_id
            and left.student_id != right.student_id
        )

    def top_k(
        self, query_id: str, k: int | None = None, strategy: RetrievalStrategy = "full"
    ) -> SearchResult:
        if strategy not in ("full", "index"):
            raise ValueError("Неизвестная стратегия отбора")
        limit = self.config.top_k if k is None else k
        if type(limit) is not int or limit < 1:
            raise ValueError("k должен быть положительным int")
        query = self._get(query_id)
        if query_id in self._errors:
            return SearchResult(
                query_id,
                strategy,
                (),
                0,
                0,
                (ComparisonError(query_id, self._errors[query_id]),),
                self.index.version,
            )
        if strategy == "index":
            candidate_ids = self.index.candidates(self._features[query_id])
            candidates = [self._by_id[item] for item in sorted(candidate_ids)]
        else:
            candidates = list(self._documents)
        ranked: list[PairResult] = []
        errors: list[ComparisonError] = []
        insufficient_data = 0
        examined = 0
        for candidate in candidates:
            if not self.eligible(query, candidate):
                continue
            examined += 1
            result = self.compare(query_id, candidate.submission_id)
            if result.status == "invalid_source":
                errors.append(ComparisonError(candidate.submission_id, result.explanation))
            elif result.status == "insufficient_data":
                insufficient_data += 1
            elif result.score is not None:
                ranked.append(result)
        ranked.sort(key=lambda item: (-(item.score or 0), item.right_id))
        return SearchResult(
            query_id,
            strategy,
            tuple(ranked[:limit]),
            examined,
            insufficient_data,
            tuple(errors),
            self.index.version,
        )
