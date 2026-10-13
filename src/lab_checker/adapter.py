"""Тестовый адаптер на месте будущего HTTP-интерфейса.

Только здесь коды доменных ошибок сопоставляются с кодами ответа.
"""

from dataclasses import asdict, dataclass

from lab_checker.errors import ErrorCode, SubmissionError
from lab_checker.parsing import validate_submission_input
from lab_checker.services import SubmissionService

_STATUS_BY_ERROR: dict[ErrorCode, int] = {
    "invalid_json": 400,
    "schema_error": 422,
    "unsupported_version": 422,
    "conflict": 409,
}


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    status_code: int
    body: dict[str, object]


class SubmissionTestAdapter:
    def __init__(self, service: SubmissionService) -> None:
        self._service = service

    def accept_payload(self, payload: object) -> AdapterResponse:
        try:
            dto = validate_submission_input(payload)
            result = self._service.accept_submission(dto.to_domain())
        except SubmissionError as exc:
            return AdapterResponse(_STATUS_BY_ERROR[exc.code], {"error": exc.to_dict()})
        return AdapterResponse(201 if result.status == "accepted" else 200, asdict(result))
