import json
from collections.abc import Callable
from typing import Any

import pytest

from lab_checker.analysis import AnalysisService
from lab_checker.bootstrap import build_registry
from lab_checker.intake import IntakeService
from lab_checker.models import Assignment
from lab_checker.repositories import InMemoryAssignmentCatalog, InMemorySubmissionRepository

TEMPLATE_CODE = (
    'def solve(numbers):\n    pass\n\n\nif __name__ == "__main__":\n    print(solve([1, 2, 3]))\n'
)

PayloadFactory = Callable[..., dict[str, Any]]


@pytest.fixture
def assignment() -> Assignment:
    return Assignment(
        assignment_id="lab-01-sum",
        title="Сумма элементов списка",
        requirements=("Функция solve(numbers) возвращает сумму",),
        template_code=TEMPLATE_CODE,
    )


@pytest.fixture
def make_payload() -> PayloadFactory:
    def factory(**overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "submission_id": "sub-001",
            "assignment_id": "lab-01-sum",
            "student_id": "student-01",
            "timestamp": "2026-10-01T10:15:00+03:00",
            "text": "Пояснение к решению.\n\nСложность O(n).",
            "code": "def solve(numbers):\n    return sum(numbers)\n",
            "ai_declaration": {"used": False},
        }
        payload.update(overrides)
        return payload

    return factory


def to_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def repository() -> InMemorySubmissionRepository:
    return InMemorySubmissionRepository()


@pytest.fixture
def catalog(assignment: Assignment) -> InMemoryAssignmentCatalog:
    return InMemoryAssignmentCatalog([assignment])


@pytest.fixture
def intake(
    repository: InMemorySubmissionRepository, catalog: InMemoryAssignmentCatalog
) -> IntakeService:
    return IntakeService(repository, catalog)


@pytest.fixture
def analysis(
    repository: InMemorySubmissionRepository, catalog: InMemoryAssignmentCatalog
) -> AnalysisService:
    return AnalysisService(repository, catalog, build_registry())
