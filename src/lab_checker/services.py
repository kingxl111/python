"""Сервис приёма сдач и импорт из источника."""

from dataclasses import asdict, dataclass, field
from typing import Literal

from lab_checker.errors import SubmissionError
from lab_checker.hashing import submission_hash
from lab_checker.models import Submission
from lab_checker.parsing import parse_submission
from lab_checker.repositories import SubmissionRepository
from lab_checker.sources import SubmissionSource


@dataclass(frozen=True, slots=True)
class Acceptance:
    status: Literal["accepted", "duplicate"]
    submission_id: str
    content_hash: str


class SubmissionService:
    def __init__(self, repository: SubmissionRepository) -> None:
        self.repository = repository

    def accept(self, raw: object) -> Acceptance:
        return self.accept_submission(parse_submission(raw))

    def accept_submission(self, submission: Submission) -> Acceptance:
        """Принимает уже провалидированную сдачу. Тот же id с другим содержимым — ``conflict``."""
        digest = submission_hash(submission)
        previous = self.repository.get(submission.submission_id)
        if previous is not None:
            if submission_hash(previous) != digest:
                raise SubmissionError(
                    "conflict", "submission_id", "Для новой версии требуется новый submission_id"
                )
            return Acceptance("duplicate", submission.submission_id, digest)
        self.repository.add(submission)
        return Acceptance("accepted", submission.submission_id, digest)


@dataclass
class ImportSummary:
    accepted: list[str] = field(default_factory=list)
    duplicate: list[str] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def import_source(source: SubmissionSource, service: SubmissionService) -> ImportSummary:
    """Импорт атомарен на уровне одной сдачи: ошибка строки не отменяет принятые ранее."""
    summary = ImportSummary()
    with source.open() as records:
        for record in records:
            if record.error is not None:
                summary.errors.append({"line_no": record.line_no, **record.error.to_dict()})
                continue
            try:
                result = service.accept(record.raw)
            except SubmissionError as exc:
                summary.errors.append({"line_no": record.line_no, **exc.to_dict()})
                continue
            target = summary.accepted if result.status == "accepted" else summary.duplicate
            target.append(result.submission_id)
    return summary
