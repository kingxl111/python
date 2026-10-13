import pytest
from conftest import RAW_EXAMPLE, changed

from lab_checker.adapter import SubmissionTestAdapter
from lab_checker.bootstrap import Application


@pytest.fixture
def adapter(app: Application) -> SubmissionTestAdapter:
    return SubmissionTestAdapter(app.submission_service)


def test_accepted_then_duplicate(adapter: SubmissionTestAdapter) -> None:
    first = adapter.accept_payload(RAW_EXAMPLE)
    second = adapter.accept_payload(RAW_EXAMPLE)

    assert first.status_code == 201
    assert first.body["status"] == "accepted"
    assert second.status_code == 200
    assert second.body["status"] == "duplicate"


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        (changed(student_id=""), 422, "schema_error"),
        (changed(schema_version=2), 422, "unsupported_version"),
        ("not an object", 422, "schema_error"),
    ],
)
def test_errors(adapter: SubmissionTestAdapter, payload: object, status: int, code: str) -> None:
    response = adapter.accept_payload(payload)

    assert response.status_code == status
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == code


def test_conflict(adapter: SubmissionTestAdapter) -> None:
    adapter.accept_payload(RAW_EXAMPLE)

    response = adapter.accept_payload(changed(text="Другая версия"))

    assert response.status_code == 409
