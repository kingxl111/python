import copy
from datetime import UTC, datetime, timedelta, timezone

import pytest
from conftest import PayloadFactory, to_line

from lab_checker.errors import MalformedPayloadError, SchemaViolationError
from lab_checker.models import AIDeclaration, Submission
from lab_checker.schemas import SubmissionIn, decode_json, parse_assignments, parse_submission


def issue_codes(exc: pytest.ExceptionInfo[SchemaViolationError]) -> set[tuple[str, str]]:
    return {(issue.code, issue.field) for issue in exc.value.issues}


def test_valid_payload_becomes_domain_submission(make_payload: PayloadFactory) -> None:
    submission = parse_submission(make_payload())

    assert submission == Submission(
        submission_id="sub-001",
        assignment_id="lab-01-sum",
        student_id="student-01",
        timestamp=datetime(2026, 10, 1, 10, 15, tzinfo=timezone(timedelta(hours=3))),
        text="Пояснение к решению.\n\nСложность O(n).",
        code="def solve(numbers):\n    return sum(numbers)\n",
        ai_declaration=AIDeclaration(used=False),
    )


def test_input_model_converts_to_domain_object(make_payload: PayloadFactory) -> None:
    model = SubmissionIn.model_validate(make_payload())

    assert isinstance(model.to_domain(), Submission)
    assert model.to_domain() == parse_submission(make_payload())


def test_payload_is_not_mutated(make_payload: PayloadFactory) -> None:
    payload = make_payload(ai_declaration={"used": True, "description": "подсказка"})
    snapshot = copy.deepcopy(payload)

    parse_submission(payload)

    assert payload == snapshot


def test_invalid_payload_is_not_mutated(make_payload: PayloadFactory) -> None:
    payload = make_payload(student_id="", extra="x")
    snapshot = copy.deepcopy(payload)

    with pytest.raises(SchemaViolationError):
        parse_submission(payload)

    assert payload == snapshot


@pytest.mark.parametrize("field", ["submission_id", "assignment_id", "student_id"])
@pytest.mark.parametrize("value", ["", "   "])
def test_blank_identifier_is_rejected(make_payload: PayloadFactory, field: str, value: str) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(**{field: value}))

    assert issue_codes(exc) == {("empty_value", field)}


@pytest.mark.parametrize(
    "field",
    ["submission_id", "assignment_id", "student_id", "timestamp", "text", "code", "ai_declaration"],
)
def test_missing_required_field(make_payload: PayloadFactory, field: str) -> None:
    payload = make_payload()
    del payload[field]

    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(payload)

    assert issue_codes(exc) == {("missing_field", field)}


def test_unknown_field_is_rejected(make_payload: PayloadFactory) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(grade=10))

    assert issue_codes(exc) == {("unknown_field", "grade")}


def test_unknown_nested_field_is_rejected(make_payload: PayloadFactory) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(ai_declaration={"used": False, "model": "x"}))

    assert issue_codes(exc) == {("unknown_field", "ai_declaration.model")}


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"student_id": 7}, "student_id"),
        ({"text": None}, "text"),
        ({"code": ["print(1)"]}, "code"),
        ({"ai_declaration": {"used": "yes"}}, "ai_declaration.used"),
        ({"ai_declaration": {"used": 1}}, "ai_declaration.used"),
        ({"ai_declaration": {"used": True, "description": 5}}, "ai_declaration.description"),
        ({"ai_declaration": True}, "ai_declaration"),
        ({"timestamp": 1_700_000_000}, "timestamp"),
    ],
)
def test_wrong_types_are_rejected_without_coercion(
    make_payload: PayloadFactory, overrides: dict[str, object], field: str
) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(**overrides))

    assert issue_codes(exc) == {("invalid_type", field)}


@pytest.mark.parametrize(
    "value", ["01.10.2026 10:15", "2026-13-01T10:15:00+03:00", "", "1700000000"]
)
def test_invalid_timestamp(make_payload: PayloadFactory, value: str) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(timestamp=value))

    assert issue_codes(exc) == {("invalid_timestamp", "timestamp")}


@pytest.mark.parametrize("value", ["2026-10-01T10:15:00", "2026-10-01"])
def test_timestamp_without_timezone(make_payload: PayloadFactory, value: str) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(timestamp=value))

    assert issue_codes(exc) == {("timestamp_without_timezone", "timestamp")}


@pytest.mark.parametrize("value", ["0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00"])
def test_timestamp_outside_utc_range(make_payload: PayloadFactory, value: str) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(timestamp=value))

    assert issue_codes(exc) == {("invalid_timestamp", "timestamp")}


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"text": "\ud800"}, "text"),
        ({"code": "x = '\udfff'"}, "code"),
        ({"student_id": "st\ud800"}, "student_id"),
        ({"ai_declaration": {"used": True, "description": "\ud800"}}, "ai_declaration.description"),
    ],
)
def test_lone_surrogate_is_rejected(
    make_payload: PayloadFactory, overrides: dict[str, object], field: str
) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(**overrides))

    assert issue_codes(exc) == {("invalid_string", field)}


def test_lone_surrogate_from_json_escape_is_rejected(make_payload: PayloadFactory) -> None:
    raw = to_line(make_payload(text="PLACEHOLDER")).replace("PLACEHOLDER", "\\ud800")

    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(decode_json(raw))

    assert issue_codes(exc) == {("invalid_string", "text")}


def test_utc_designator_is_accepted(make_payload: PayloadFactory) -> None:
    submission = parse_submission(make_payload(timestamp="2026-10-01T07:15:00Z"))

    assert submission.timestamp == datetime(2026, 10, 1, 7, 15, tzinfo=UTC)


def test_all_issues_are_reported_at_once(make_payload: PayloadFactory) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(make_payload(student_id="", timestamp="bad", extra=1))

    assert issue_codes(exc) == {
        ("empty_value", "student_id"),
        ("invalid_timestamp", "timestamp"),
        ("unknown_field", "extra"),
    }


@pytest.mark.parametrize("payload", [["список"], "строка", 42, None])
def test_non_object_payload(payload: object) -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_submission(payload)

    assert issue_codes(exc) == {("invalid_type", "$")}


@pytest.mark.parametrize("raw", ['{"submission_id": ', "", "не json", b"\xff\xfe\x00{"])
def test_malformed_json_is_format_error(raw: str | bytes) -> None:
    with pytest.raises(MalformedPayloadError) as exc:
        decode_json(raw)

    assert [(issue.code, issue.field) for issue in exc.value.issues] == [("invalid_json", "$")]


def test_invalid_utf8_is_format_error() -> None:
    with pytest.raises(MalformedPayloadError):
        decode_json(b'{"text": "\xc3\x28"}')


def test_same_moment_in_different_offsets_has_same_hash(make_payload: PayloadFactory) -> None:
    local = parse_submission(make_payload(timestamp="2026-10-01T10:15:00+03:00"))
    utc = parse_submission(make_payload(timestamp="2026-10-01T07:15:00Z"))

    assert local.submission_hash == utc.submission_hash


def test_hash_depends_on_content(make_payload: PayloadFactory) -> None:
    original = parse_submission(make_payload())
    changed = parse_submission(make_payload(code="def solve(numbers):\n    return 0\n"))

    assert original.submission_hash != changed.submission_hash


def test_parse_assignments_rejects_duplicates() -> None:
    item = {"assignment_id": "a", "title": "t", "requirements": []}

    with pytest.raises(SchemaViolationError) as exc:
        parse_assignments([item, item])

    assert issue_codes(exc) == {("duplicate_assignment", "1.assignment_id")}


def test_parse_assignments_reports_location() -> None:
    with pytest.raises(SchemaViolationError) as exc:
        parse_assignments([{"assignment_id": "a", "title": "t", "requirements": [""]}])

    assert issue_codes(exc) == {("empty_value", "0.requirements.0")}
