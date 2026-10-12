"""Входные модели Pydantic и их преобразование в доменные объекты."""

import json
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import ErrorDetails, PydanticCustomError

from lab_checker.errors import MalformedPayloadError, SchemaViolationError, ValidationIssue
from lab_checker.models import AIDeclaration, Assignment, Submission


def _require_utf8(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise PydanticCustomError(
            "invalid_string", "строка содержит символы, недопустимые в UTF-8"
        ) from None
    return value


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise PydanticCustomError("empty_value", "значение не должно быть пустым")
    return value


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise PydanticCustomError("invalid_type", "ожидается строка даты и времени ISO 8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise PydanticCustomError(
            "invalid_timestamp", "некорректная дата и время ISO 8601"
        ) from None
    if parsed.utcoffset() is None:
        raise PydanticCustomError("timestamp_without_timezone", "не указана временная зона")
    try:
        parsed.astimezone(UTC)
    except OverflowError:
        raise PydanticCustomError(
            "invalid_timestamp", "дата и время вне допустимого диапазона"
        ) from None
    return parsed


Utf8Str = Annotated[str, AfterValidator(_require_utf8)]
NonBlankStr = Annotated[Utf8Str, AfterValidator(_require_non_blank)]
Timestamp = Annotated[datetime, BeforeValidator(_parse_timestamp)]


class _InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AIDeclarationIn(_InputModel):
    used: bool
    description: Utf8Str | None = None

    def to_domain(self) -> AIDeclaration:
        return AIDeclaration(used=self.used, description=self.description)


class SubmissionIn(_InputModel):
    submission_id: NonBlankStr
    assignment_id: NonBlankStr
    student_id: NonBlankStr
    timestamp: Timestamp
    text: Utf8Str
    code: Utf8Str
    ai_declaration: AIDeclarationIn

    def to_domain(self) -> Submission:
        return Submission(
            submission_id=self.submission_id,
            assignment_id=self.assignment_id,
            student_id=self.student_id,
            timestamp=self.timestamp,
            text=self.text,
            code=self.code,
            ai_declaration=self.ai_declaration.to_domain(),
        )


class AssignmentIn(_InputModel):
    assignment_id: NonBlankStr
    title: NonBlankStr
    requirements: list[NonBlankStr]
    template_code: Utf8Str = ""

    def to_domain(self) -> Assignment:
        return Assignment(
            assignment_id=self.assignment_id,
            title=self.title,
            requirements=tuple(self.requirements),
            template_code=self.template_code,
        )


_ASSIGNMENT_LIST = TypeAdapter(list[AssignmentIn])

_OWN_CODES = frozenset(
    {
        "empty_value",
        "invalid_string",
        "invalid_type",
        "invalid_timestamp",
        "timestamp_without_timezone",
    }
)
_MESSAGES = {
    "missing_field": "обязательное поле отсутствует",
    "unknown_field": "неизвестное поле",
    "invalid_type": "неверный тип значения",
}


def _issue_code(error_type: str) -> str:
    if error_type in _OWN_CODES:
        return error_type
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type.endswith("_type"):
        return "invalid_type"
    return "invalid_value"


def _issue_from(error: ErrorDetails) -> ValidationIssue:
    code = _issue_code(error["type"])
    field = ".".join(str(part) for part in error["loc"]) or "$"
    own_message = error["type"] in _OWN_CODES
    message = error["msg"] if own_message else _MESSAGES.get(code, error["msg"])
    return ValidationIssue(code=code, field=field, message=message)


def _schema_error(exc: PydanticValidationError) -> SchemaViolationError:
    return SchemaViolationError([_issue_from(error) for error in exc.errors()])


def decode_json(raw: str | bytes) -> object:
    """Разбирает одну JSON-запись. Синтаксические ошибки и неверная кодировка — ошибка формата."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        message = f"некорректный JSON: {exc.msg} (строка {exc.lineno}, столбец {exc.colno})"
    except ValueError as exc:
        message = f"некорректный JSON: {exc}"
    raise MalformedPayloadError([ValidationIssue(code="invalid_json", field="$", message=message)])


def parse_submission(payload: object) -> Submission:
    """Проверяет декодированную запись и возвращает доменную сдачу; ``payload`` не изменяется."""
    try:
        model = SubmissionIn.model_validate(payload)
    except PydanticValidationError as exc:
        raise _schema_error(exc) from None
    return model.to_domain()


def parse_assignments(payload: object) -> tuple[Assignment, ...]:
    try:
        models = _ASSIGNMENT_LIST.validate_python(payload)
    except PydanticValidationError as exc:
        raise _schema_error(exc) from None
    assignments = tuple(model.to_domain() for model in models)
    seen: set[str] = set()
    for index, assignment in enumerate(assignments):
        if assignment.assignment_id in seen:
            raise SchemaViolationError(
                [
                    ValidationIssue(
                        code="duplicate_assignment",
                        field=f"{index}.assignment_id",
                        message=f"задание {assignment.assignment_id!r} описано повторно",
                    )
                ]
            )
        seen.add(assignment.assignment_id)
    return assignments
