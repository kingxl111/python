import copy
import json
from pathlib import Path
from typing import Any

import pytest

from lab_checker.analysis import AnalysisContext
from lab_checker.bootstrap import Application, build_application
from lab_checker.models import Assignment, Submission
from lab_checker.parsing import parse_submission

DATA = Path(__file__).resolve().parent.parent / "data"
PUBLIC_SUBMISSIONS: list[dict[str, Any]] = [
    json.loads(line) for line in (DATA / "submissions.jsonl").read_text("utf-8").splitlines()
]
RAW_EXAMPLE = PUBLIC_SUBMISSIONS[0]


def changed(**updates: Any) -> dict[str, Any]:
    result = copy.deepcopy(RAW_EXAMPLE)
    result.update(updates)
    return result


@pytest.fixture
def submission() -> Submission:
    return parse_submission(copy.deepcopy(RAW_EXAMPLE))


@pytest.fixture
def assignment() -> Assignment:
    return Assignment("assignment-01", "from typing import Iterable\n", ("Наличие функции solve",))


@pytest.fixture
def context(assignment: Assignment) -> AnalysisContext:
    return AnalysisContext(assignment)


@pytest.fixture
def app() -> Application:
    return build_application()
