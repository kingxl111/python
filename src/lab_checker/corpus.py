"""Потоковый корпус ЛР 2 с происхождением версий и разметкой пар."""

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from lab_checker.errors import SubmissionError
from lab_checker.models import Submission
from lab_checker.parsing import (
    NonEmptyStr,
    SubmissionInput,
    _Input,
    parse_submission,
    to_submission_error,
)
from lab_checker.repositories import InMemorySubmissionRepository
from lab_checker.services import SubmissionService
from lab_checker.sources import JSONLSource

SplitName = Literal["tuning", "evaluation"]


@dataclass(frozen=True, slots=True)
class CorpusSubmission:
    submission: Submission
    family_id: str
    parent_id: str | None
    transformation: str
    split: SplitName


class CorpusSubmissionInput(SubmissionInput):
    family_id: NonEmptyStr
    parent_id: NonEmptyStr | None
    transformation: NonEmptyStr
    split: SplitName

    def to_corpus(self) -> CorpusSubmission:
        return CorpusSubmission(
            self.to_domain(), self.family_id, self.parent_id, self.transformation, self.split
        )


@dataclass(frozen=True, slots=True)
class LabelledPair:
    left_id: str
    right_id: str
    derivation_relation: bool
    template_only: bool


class LabelledPairInput(_Input):
    left_id: NonEmptyStr
    right_id: NonEmptyStr
    derivation_relation: bool
    template_only: bool

    def to_domain(self) -> LabelledPair:
        return LabelledPair(
            self.left_id, self.right_id, self.derivation_relation, self.template_only
        )


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    line_no: int
    value: CorpusSubmission | None = None
    error: SubmissionError | None = None


@dataclass(frozen=True, slots=True)
class PairRecord:
    line_no: int
    value: LabelledPair | None = None
    error: SubmissionError | None = None


def read_corpus(path: Path) -> Iterator[CorpusRecord]:
    """Выдаёт записи по одной; файл открыт только во время итерации."""
    with JSONLSource(path).open() as records:
        for record in records:
            if record.error is not None:
                yield CorpusRecord(record.line_no, error=record.error)
                continue
            try:
                value = CorpusSubmissionInput.model_validate(record.raw).to_corpus()
            except ValidationError as exc:
                yield CorpusRecord(
                    record.line_no, error=to_submission_error(exc, "corpus_submission")
                )
            else:
                yield CorpusRecord(record.line_no, value=value)


def read_labelled_pairs(path: Path) -> Iterator[PairRecord]:
    with JSONLSource(path).open() as records:
        for record in records:
            if record.error is not None:
                yield PairRecord(record.line_no, error=record.error)
                continue
            try:
                value = LabelledPairInput.model_validate(record.raw).to_domain()
            except ValidationError as exc:
                yield PairRecord(record.line_no, error=to_submission_error(exc, "labelled_pair"))
            else:
                yield PairRecord(record.line_no, value=value)


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    submission_id: str
    student_id: str
    assignment_id: str
    family_id: str
    parent_id: str | None
    transformation: str
    split: SplitName


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    entries: tuple[CorpusEntry, ...]
    tuning_families: tuple[str, ...]
    evaluation_families: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [asdict(entry) for entry in self.entries],
            "families": {
                "tuning": list(self.tuning_families),
                "evaluation": list(self.evaluation_families),
            },
        }


def build_manifest(values: Iterator[CorpusSubmission]) -> CorpusManifest:
    """Материализует только метаданные, не создавая вторую копию исходного кода."""
    entries: list[CorpusEntry] = []
    by_id: dict[str, CorpusEntry] = {}
    family_splits: dict[str, SplitName] = {}
    for value in values:
        submission = parse_submission(asdict(value.submission))
        entry = CorpusEntry(
            submission.submission_id,
            submission.student_id,
            submission.assignment_id,
            value.family_id,
            value.parent_id,
            value.transformation,
            value.split,
        )
        if entry.submission_id in by_id:
            raise SubmissionError("conflict", "submission_id", "Повтор записи корпуса")
        previous_split = family_splits.get(entry.family_id)
        if previous_split is not None and previous_split != entry.split:
            raise ValueError(f"Семейство {entry.family_id} попало в оба набора")
        family_splits[entry.family_id] = entry.split
        by_id[entry.submission_id] = entry
        entries.append(entry)
    for entry in entries:
        if entry.parent_id is None:
            continue
        parent = by_id.get(entry.parent_id)
        if parent is None or parent.family_id != entry.family_id:
            raise ValueError(f"Некорректный parent_id у {entry.submission_id}")
    return CorpusManifest(
        tuple(entries),
        tuple(sorted(family for family, split in family_splits.items() if split == "tuning")),
        tuple(sorted(family for family, split in family_splits.items() if split == "evaluation")),
    )


@dataclass(frozen=True, slots=True)
class CorpusLoadResult:
    repository: InMemorySubmissionRepository
    manifest: CorpusManifest
    errors: tuple[dict[str, object], ...]


def load_corpus(path: Path) -> CorpusLoadResult:
    """Потоково заполняет репозиторий; ошибка одной строки не отменяет остальные."""
    repository = InMemorySubmissionRepository()
    service = SubmissionService(repository)
    values: list[CorpusSubmission] = []
    errors: list[dict[str, object]] = []
    for record in read_corpus(path):
        if record.error is not None:
            errors.append({"line_no": record.line_no, **record.error.to_dict()})
            continue
        assert record.value is not None
        try:
            service.accept_submission(parse_submission(asdict(record.value.submission)))
        except SubmissionError as exc:
            errors.append({"line_no": record.line_no, **exc.to_dict()})
        else:
            values.append(record.value)
    return CorpusLoadResult(repository, build_manifest(iter(values)), tuple(errors))


def validate_labelled_pairs(
    pairs: Iterator[LabelledPair], manifest: CorpusManifest
) -> tuple[LabelledPair, ...]:
    entries = {entry.submission_id: entry for entry in manifest.entries}
    seen: set[tuple[str, str]] = set()
    result = []
    for pair in pairs:
        key = (min(pair.left_id, pair.right_id), max(pair.left_id, pair.right_id))
        if key in seen:
            raise ValueError(f"Повторная разметка пары: {key}")
        seen.add(key)
        left = entries.get(pair.left_id)
        right = entries.get(pair.right_id)
        if left is None or right is None:
            raise ValueError("Пара ссылается на неизвестную сдачу")
        if left.split != right.split:
            raise ValueError("Пара пересекает настройку и оценку")
        if left.assignment_id != right.assignment_id or left.student_id == right.student_id:
            raise ValueError("Пара нарушает фильтр задания и разных студентов")
        if pair.derivation_relation != (left.family_id == right.family_id):
            raise ValueError(f"Неверная derivation_relation у {key}")
        if pair.template_only and pair.derivation_relation:
            raise ValueError("template_only не заменяет отношение происхождения")
        result.append(pair)
    return tuple(result)
