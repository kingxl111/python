"""Сервис приёма сдач."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from lab_checker.errors import (
    IntakeError,
    SchemaViolationError,
    SubmissionConflictError,
    ValidationIssue,
)
from lab_checker.models import Submission
from lab_checker.repositories import AssignmentCatalog, SubmissionRepository
from lab_checker.schemas import decode_json, parse_submission
from lab_checker.sources import SourceRecord

IntakeStatus = Literal["accepted", "duplicate"]


@dataclass(frozen=True, slots=True)
class IntakeResult:
    status: IntakeStatus
    submission: Submission


@dataclass(frozen=True, slots=True)
class RecordError:
    line: int
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class ImportReport:
    accepted: tuple[str, ...]
    duplicate: tuple[str, ...]
    errors: tuple[RecordError, ...]


class IntakeService:
    def __init__(self, submissions: SubmissionRepository, assignments: AssignmentCatalog) -> None:
        self._submissions = submissions
        self._assignments = assignments

    def submit(self, payload: object) -> IntakeResult:
        """Принимает декодированную запись.

        Повтор того же содержимого возвращает ранее принятую сдачу; тот же
        ``submission_id`` с другим содержимым вызывает ``SubmissionConflictError``.
        """
        submission = parse_submission(payload)
        if self._assignments.get(submission.assignment_id) is None:
            raise SchemaViolationError(
                [
                    ValidationIssue(
                        code="unknown_assignment",
                        field="assignment_id",
                        message=f"задание {submission.assignment_id!r} не найдено",
                    )
                ]
            )
        existing = self._submissions.get(submission.submission_id)
        if existing is None:
            self._submissions.add(submission)
            return IntakeResult(status="accepted", submission=submission)
        if existing.submission_hash == submission.submission_hash:
            return IntakeResult(status="duplicate", submission=existing)
        raise SubmissionConflictError(submission.submission_id)

    def submit_json(self, raw: str | bytes) -> IntakeResult:
        return self.submit(decode_json(raw))

    def import_records(self, records: Iterable[SourceRecord]) -> ImportReport:
        """Импортирует записи; ошибочная запись попадает в отчёт и не прерывает импорт."""
        accepted: list[str] = []
        duplicate: list[str] = []
        errors: list[RecordError] = []
        for record in records:
            try:
                result = self.submit_json(record.raw)
            except IntakeError as exc:
                errors.append(RecordError(line=record.line, issues=exc.issues))
                continue
            target = accepted if result.status == "accepted" else duplicate
            target.append(result.submission.submission_id)
        return ImportReport(
            accepted=tuple(accepted), duplicate=tuple(duplicate), errors=tuple(errors)
        )
