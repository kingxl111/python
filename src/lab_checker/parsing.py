"""Разбор JSON и входные модели Pydantic с преобразованием в доменные объекты."""

import json
from datetime import datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, TypeAdapter, model_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import ErrorDetails, PydanticCustomError

from lab_checker.errors import ConfigurationError, ErrorCode, SubmissionError
from lab_checker.models import AIDeclaration, Assignment, Submission

SUPPORTED_SCHEMA_VERSION = 1


def _printable(text: str) -> str:
    """Имя поля из входа может содержать одиночные суррогаты, которые не выводятся в UTF-8."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _reject_repeated_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SubmissionError(
                "invalid_json", _printable(key), "Повтор ключа в JSON-объекте не допускается"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise SubmissionError("invalid_json", "json", f"Нестандартное значение не допускается: {value}")


def decode_json(raw: str | bytes) -> object:
    """Синтаксический разбор одной записи; схема здесь не проверяется."""
    try:
        return json.loads(
            raw, object_pairs_hook=_reject_repeated_keys, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise SubmissionError(
            "invalid_json", "json", f"Некорректный JSON: {exc.msg} (позиция {exc.pos})"
        ) from exc
    except ValueError as exc:
        raise SubmissionError("invalid_json", "json", f"Некорректный JSON: {exc}") from exc


_NOT_UTF8 = "Строка содержит символы, недопустимые в UTF-8"


def _require_utf8(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise PydanticCustomError("schema_error", _NOT_UTF8) from None
    return value


def _require_nonempty(value: str) -> str:
    if not value.strip():
        raise PydanticCustomError("schema_error", "Ожидается непустая строка")
    return value


def _require_aware_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise PydanticCustomError(
            "schema_error", "Ожидается дата и время ISO с часовым поясом"
        ) from None
    if parsed.utcoffset() is None:
        raise PydanticCustomError("schema_error", "Часовой пояс обязателен")
    return value


def _require_supported_version(value: int) -> int:
    if value != SUPPORTED_SCHEMA_VERSION:
        raise PydanticCustomError(
            "unsupported_version", f"Поддерживается версия схемы {SUPPORTED_SCHEMA_VERSION}"
        )
    return value


Utf8Str = Annotated[str, AfterValidator(_require_utf8)]
NonEmptyStr = Annotated[Utf8Str, AfterValidator(_require_nonempty)]
Timestamp = Annotated[Utf8Str, AfterValidator(_require_aware_timestamp)]
SchemaVersion = Annotated[int, AfterValidator(_require_supported_version)]


class _Input(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class DeclarationInput(_Input):
    used: bool
    tool: NonEmptyStr | None
    purpose: NonEmptyStr | None
    verified_by_student: bool

    @model_validator(mode="after")
    def _tool_and_purpose_when_used(self) -> Self:
        if self.used and (self.tool is None or self.purpose is None):
            raise PydanticCustomError(
                "schema_error", "При used=true обязательны инструмент и цель применения ИИ"
            )
        return self

    def to_domain(self) -> AIDeclaration:
        return AIDeclaration(
            used=self.used,
            tool=self.tool,
            purpose=self.purpose,
            verified_by_student=self.verified_by_student,
        )


class SubmissionInput(_Input):
    schema_version: SchemaVersion
    submission_id: NonEmptyStr
    student_id: NonEmptyStr
    assignment_id: NonEmptyStr
    submitted_at: Timestamp
    text: Utf8Str
    code: Utf8Str
    template_id: NonEmptyStr | None
    ai_declaration: DeclarationInput

    @model_validator(mode="after")
    def _text_or_code(self) -> Self:
        if not self.text.strip() and not self.code.strip():
            raise PydanticCustomError(
                "schema_error", "Текст или код должны быть непустыми", {"field": "text/code"}
            )
        return self

    def to_domain(self) -> Submission:
        return Submission(
            schema_version=self.schema_version,
            submission_id=self.submission_id,
            student_id=self.student_id,
            assignment_id=self.assignment_id,
            submitted_at=self.submitted_at,
            text=self.text,
            code=self.code,
            template_id=self.template_id,
            ai_declaration=self.ai_declaration.to_domain(),
        )


class AssignmentInput(_Input):
    assignment_id: NonEmptyStr
    allowed_template: Utf8Str
    requirements: list[NonEmptyStr]

    def to_domain(self) -> Assignment:
        return Assignment(
            assignment_id=self.assignment_id,
            allowed_template=self.allowed_template,
            requirements=tuple(self.requirements),
        )


_BUILTIN_MESSAGES = {
    "missing": "Обязательное поле отсутствует",
    "extra_forbidden": "Неизвестное поле не допускается",
    "string_unicode": _NOT_UTF8,
}


def _message(error: ErrorDetails) -> str:
    if error["type"] in ("schema_error", "unsupported_version"):
        return error["msg"]
    if error["type"] in _BUILTIN_MESSAGES:
        return _BUILTIN_MESSAGES[error["type"]]
    if error["type"].endswith("_type"):
        return "Неверный тип значения; преобразование типов не выполняется"
    return error["msg"]


def to_submission_error(exc: PydanticValidationError, root: str) -> SubmissionError:
    """Первая ошибка Pydantic в общем формате ``code``, ``field``, ``message``."""
    error = exc.errors()[0]
    context = error.get("ctx") or {}
    field = context.get("field") or ".".join(str(part) for part in error["loc"]) or root
    code: ErrorCode = (
        "unsupported_version" if error["type"] == "unsupported_version" else "schema_error"
    )
    return SubmissionError(code, _printable(field), _message(error))


def validate_submission_input(raw: object) -> SubmissionInput:
    """Проверяет декодированную запись; ``raw`` не изменяется."""
    try:
        return SubmissionInput.model_validate(raw)
    except PydanticValidationError as exc:
        raise to_submission_error(exc, "submission") from exc


def parse_submission(raw: object) -> Submission:
    return validate_submission_input(raw).to_domain()


_ASSIGNMENTS = TypeAdapter(list[AssignmentInput])


def parse_assignments(raw: object) -> dict[str, Assignment]:
    try:
        dtos = _ASSIGNMENTS.validate_python(raw)
    except PydanticValidationError as exc:
        error = to_submission_error(exc, "assignments")
        raise ConfigurationError(f"{error.field}: {error.message}") from exc
    assignments: dict[str, Assignment] = {}
    for dto in dtos:
        if dto.assignment_id in assignments:
            raise ConfigurationError(f"Задание {dto.assignment_id!r} описано повторно")
        assignments[dto.assignment_id] = dto.to_domain()
    return assignments
