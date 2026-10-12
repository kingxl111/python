"""Тестовый адаптер на месте будущего HTTP-интерфейса.

Только здесь доменные результаты и исключения сопоставляются с кодами ответа.
"""

from dataclasses import asdict, dataclass

from lab_checker.errors import (
    IntakeError,
    MalformedPayloadError,
    SchemaViolationError,
    SubmissionConflictError,
)
from lab_checker.intake import IntakeService


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    status_code: int
    body: dict[str, object]


_ERROR_STATUS: tuple[tuple[type[IntakeError], int], ...] = (
    (MalformedPayloadError, 400),
    (SchemaViolationError, 422),
    (SubmissionConflictError, 409),
)


class SubmissionTestAdapter:
    def __init__(self, intake: IntakeService) -> None:
        self._intake = intake

    def post_submission(self, body: str | bytes) -> AdapterResponse:
        try:
            result = self._intake.submit_json(body)
        except IntakeError as exc:
            status = next((code for kind, code in _ERROR_STATUS if isinstance(exc, kind)), 422)
            return AdapterResponse(
                status_code=status,
                body={"errors": [asdict(issue) for issue in exc.issues]},
            )
        return AdapterResponse(
            status_code=201 if result.status == "accepted" else 200,
            body={
                "status": result.status,
                "submission_id": result.submission.submission_id,
                "submission_hash": result.submission.submission_hash,
            },
        )
