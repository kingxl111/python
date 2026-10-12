import pytest
from conftest import PayloadFactory, to_line

from lab_checker.errors import SchemaViolationError, SubmissionConflictError
from lab_checker.intake import IntakeService, RecordError
from lab_checker.repositories import InMemorySubmissionRepository
from lab_checker.sources import SourceRecord


def records(*lines: str) -> list[SourceRecord]:
    return [SourceRecord(line=number, raw=line) for number, line in enumerate(lines, start=1)]


def test_valid_submission_is_accepted(
    intake: IntakeService, repository: InMemorySubmissionRepository, make_payload: PayloadFactory
) -> None:
    result = intake.submit(make_payload())

    assert result.status == "accepted"
    assert repository.get("sub-001") == result.submission
    assert repository.count() == 1


def test_duplicate_returns_stored_submission_and_does_not_grow(
    intake: IntakeService, repository: InMemorySubmissionRepository, make_payload: PayloadFactory
) -> None:
    first = intake.submit(make_payload(timestamp="2026-10-01T10:15:00+03:00"))
    second = intake.submit(make_payload(timestamp="2026-10-01T07:15:00Z"))

    assert second.status == "duplicate"
    assert second.submission is first.submission
    assert repository.count() == 1


def test_duplicate_json_with_other_formatting(
    intake: IntakeService, make_payload: PayloadFactory
) -> None:
    payload = make_payload()
    intake.submit_json(to_line(payload))
    reordered = dict(reversed(list(payload.items())))

    assert intake.submit_json(to_line(reordered).replace(", ", ",   ")).status == "duplicate"


def test_conflict_does_not_overwrite_original(
    intake: IntakeService, repository: InMemorySubmissionRepository, make_payload: PayloadFactory
) -> None:
    original = intake.submit(make_payload()).submission

    with pytest.raises(SubmissionConflictError) as exc:
        intake.submit(make_payload(code="print('другое')\n"))

    assert [(issue.code, issue.field) for issue in exc.value.issues] == [
        ("submission_conflict", "submission_id")
    ]
    assert repository.get("sub-001") is original
    assert repository.count() == 1


def test_new_version_with_new_id_is_accepted(
    intake: IntakeService, repository: InMemorySubmissionRepository, make_payload: PayloadFactory
) -> None:
    intake.submit(make_payload())
    intake.submit(make_payload(submission_id="sub-002", code="print('v2')\n"))

    assert repository.count() == 2


def test_unknown_assignment_is_rejected(
    intake: IntakeService, repository: InMemorySubmissionRepository, make_payload: PayloadFactory
) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        intake.submit(make_payload(assignment_id="lab-99"))

    assert [(issue.code, issue.field) for issue in exc.value.issues] == [
        ("unknown_assignment", "assignment_id")
    ]
    assert repository.count() == 0


def test_import_continues_after_bad_lines(
    intake: IntakeService, repository: InMemorySubmissionRepository, make_payload: PayloadFactory
) -> None:
    report = intake.import_records(
        records(
            to_line(make_payload()),
            '{"submission_id": "broken"',
            to_line(make_payload(submission_id="sub-002", student_id="")),
            to_line(make_payload()),
            to_line(make_payload(text="изменено")),
            to_line(make_payload(submission_id="sub-003")),
        )
    )

    assert report.accepted == ("sub-001", "sub-003")
    assert report.duplicate == ("sub-001",)
    assert [(error.line, error.issues[0].code) for error in report.errors] == [
        (2, "invalid_json"),
        (3, "empty_value"),
        (5, "submission_conflict"),
    ]
    assert all(isinstance(error, RecordError) for error in report.errors)
    assert repository.count() == 2


def test_import_of_empty_source(intake: IntakeService) -> None:
    report = intake.import_records([])

    assert (report.accepted, report.duplicate, report.errors) == ((), (), ())
