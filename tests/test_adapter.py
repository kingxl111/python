import pytest
from conftest import PayloadFactory, to_line

from lab_checker.adapter import SubmissionTestAdapter
from lab_checker.intake import IntakeService


@pytest.fixture
def adapter(intake: IntakeService) -> SubmissionTestAdapter:
    return SubmissionTestAdapter(intake)


def test_accepted_then_duplicate(
    adapter: SubmissionTestAdapter, make_payload: PayloadFactory
) -> None:
    first = adapter.post_submission(to_line(make_payload()))
    second = adapter.post_submission(to_line(make_payload()).encode("utf-8"))

    assert first.status_code == 201
    assert first.body["status"] == "accepted"
    assert second.status_code == 200
    assert second.body == {**first.body, "status": "duplicate"}


def test_conflict(adapter: SubmissionTestAdapter, make_payload: PayloadFactory) -> None:
    adapter.post_submission(to_line(make_payload()))

    response = adapter.post_submission(to_line(make_payload(text="другое")))

    assert response.status_code == 409
    assert response.body["errors"] == [
        {
            "code": "submission_conflict",
            "field": "submission_id",
            "message": "сдача 'sub-001' уже принята с другим содержимым",
        }
    ]


def test_format_error(adapter: SubmissionTestAdapter) -> None:
    response = adapter.post_submission("{")

    assert response.status_code == 400
    assert response.body["errors"][0]["code"] == "invalid_json"  # type: ignore[index]


def test_schema_error(adapter: SubmissionTestAdapter, make_payload: PayloadFactory) -> None:
    response = adapter.post_submission(to_line(make_payload(student_id="")))

    assert response.status_code == 422
    assert response.body["errors"] == [
        {"code": "empty_value", "field": "student_id", "message": "значение не должно быть пустым"}
    ]
