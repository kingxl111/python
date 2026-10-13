"""Доменные ошибки. Коды ответов внешних интерфейсов здесь не определяются."""

from typing import Literal

ErrorCode = Literal["invalid_json", "schema_error", "unsupported_version", "conflict"]


class SubmissionError(Exception):
    def __init__(self, code: ErrorCode, field: str, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.field = field
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message}


class AnalysisFailure(Exception):
    """Анализ невозможен либо его результат нарушает контракт отчёта."""


class ConfigurationError(Exception):
    """Конфигурация приложения некорректна; обнаруживается до обработки данных."""
