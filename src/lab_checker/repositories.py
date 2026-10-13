"""Контракт хранения сдач и in-memory реализация."""

from typing import Protocol

from lab_checker.errors import SubmissionError
from lab_checker.models import Submission


class SubmissionRepository(Protocol):
    def get(self, submission_id: str) -> Submission | None: ...

    def add(self, submission: Submission) -> None: ...


class InMemorySubmissionRepository:
    def __init__(self) -> None:
        self._items: dict[str, Submission] = {}

    def get(self, submission_id: str) -> Submission | None:
        return self._items.get(submission_id)

    def add(self, submission: Submission) -> None:
        if submission.submission_id in self._items:
            raise SubmissionError("conflict", "submission_id", "Идентификатор уже сохранён")
        self._items[submission.submission_id] = submission

    def __len__(self) -> int:
        return len(self._items)
