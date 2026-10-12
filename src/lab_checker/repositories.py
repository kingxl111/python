"""Интерфейсы хранения и их in-memory реализации."""

from collections.abc import Iterable
from typing import Protocol

from lab_checker.models import Assignment, Submission


class SubmissionReader(Protocol):
    def get(self, submission_id: str) -> Submission | None: ...


class SubmissionRepository(SubmissionReader, Protocol):
    def add(self, submission: Submission) -> None: ...

    def count(self) -> int: ...


class AssignmentCatalog(Protocol):
    def get(self, assignment_id: str) -> Assignment | None: ...


class InMemorySubmissionRepository:
    def __init__(self) -> None:
        self._items: dict[str, Submission] = {}

    def get(self, submission_id: str) -> Submission | None:
        return self._items.get(submission_id)

    def add(self, submission: Submission) -> None:
        if submission.submission_id in self._items:
            raise ValueError(f"сдача {submission.submission_id!r} уже сохранена")
        self._items[submission.submission_id] = submission

    def count(self) -> int:
        return len(self._items)


class InMemoryAssignmentCatalog:
    def __init__(self, assignments: Iterable[Assignment]) -> None:
        self._items: dict[str, Assignment] = {}
        for assignment in assignments:
            if assignment.assignment_id in self._items:
                raise ValueError(f"задание {assignment.assignment_id!r} описано повторно")
            self._items[assignment.assignment_id] = assignment

    def get(self, assignment_id: str) -> Assignment | None:
        return self._items.get(assignment_id)
