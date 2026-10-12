"""Доменные ошибки. Коды ответов внешних интерфейсов здесь не определяются."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    field: str
    message: str


class IntakeError(Exception):
    """Сдача не принята. Причины перечислены в ``issues``."""

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        if not issues:
            raise ValueError("IntakeError требует хотя бы одну причину")
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{issue.field}: {issue.message}" for issue in self.issues))


class MalformedPayloadError(IntakeError):
    """Ошибка формата: запись не разбирается как JSON."""


class SchemaViolationError(IntakeError):
    """JSON разобран, но не соответствует схеме сдачи."""


class SubmissionConflictError(IntakeError):
    """``submission_id`` уже занят сдачей с другим содержимым."""

    def __init__(self, submission_id: str) -> None:
        super().__init__(
            [
                ValidationIssue(
                    code="submission_conflict",
                    field="submission_id",
                    message=f"сдача {submission_id!r} уже принята с другим содержимым",
                )
            ]
        )
        self.submission_id = submission_id


class AnalysisError(Exception):
    """Анализ нельзя запустить."""


class UnknownAnalyzerError(AnalysisError):
    def __init__(self, analyzer_id: str) -> None:
        super().__init__(f"анализатор {analyzer_id!r} не зарегистрирован")
        self.analyzer_id = analyzer_id


class SubmissionNotFoundError(AnalysisError):
    def __init__(self, submission_id: str) -> None:
        super().__init__(f"сдача {submission_id!r} не найдена")
        self.submission_id = submission_id


class AssignmentNotFoundError(AnalysisError):
    def __init__(self, assignment_id: str) -> None:
        super().__init__(f"задание {assignment_id!r} не найдено")
        self.assignment_id = assignment_id
