import copy
from dataclasses import asdict
from typing import Any

import pytest
from conftest import RAW_EXAMPLE, changed

from lab_checker.errors import ConfigurationError, SubmissionError
from lab_checker.parsing import decode_json, parse_assignments, parse_submission


def test_valid_submission_keeps_original_values() -> None:
    raw = copy.deepcopy(RAW_EXAMPLE)

    submission = parse_submission(raw)

    assert asdict(submission) == RAW_EXAMPLE
    assert raw == RAW_EXAMPLE


@pytest.mark.parametrize(
    ("raw", "code", "field"),
    [
        (changed(schema_version=True), "schema_error", "schema_version"),
        (changed(schema_version=2), "unsupported_version", "schema_version"),
        (changed(code=123), "schema_error", "code"),
        (changed(submitted_at="2026-09-01T10:00:00"), "schema_error", "submitted_at"),
        (changed(submitted_at="01.09.2026"), "schema_error", "submitted_at"),
        (changed(student_id="  "), "schema_error", "student_id"),
        (changed(template_id=""), "schema_error", "template_id"),
        (changed(unknown="value"), "schema_error", "unknown"),
        (changed(text=" ", code="\n"), "schema_error", "text/code"),
        (changed(text="\ud800"), "schema_error", "text"),
        (
            changed(
                ai_declaration={
                    "used": True,
                    "tool": None,
                    "purpose": None,
                    "verified_by_student": False,
                }
            ),
            "schema_error",
            "ai_declaration",
        ),
        (
            changed(
                ai_declaration={
                    "used": "false",
                    "tool": None,
                    "purpose": None,
                    "verified_by_student": True,
                }
            ),
            "schema_error",
            "ai_declaration.used",
        ),
        ([], "schema_error", "submission"),
    ],
)
def test_invalid_submission(raw: Any, code: str, field: str) -> None:
    before = copy.deepcopy(raw)

    with pytest.raises(SubmissionError) as info:
        parse_submission(raw)

    assert (info.value.code, info.value.field) == (code, field)
    assert info.value.message
    assert raw == before


def test_missing_field_is_reported() -> None:
    raw = changed()
    del raw["template_id"]

    with pytest.raises(SubmissionError) as info:
        parse_submission(raw)

    assert info.value.to_dict() == {
        "code": "schema_error",
        "field": "template_id",
        "message": "Обязательное поле отсутствует",
    }


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ('{"a": 1', "json"),
        ("", "json"),
        ('{"a": 1, "a": 2}', "a"),
        ('{"a": NaN}', "json"),
        ('{"a": Infinity}', "json"),
        ('{"\\ud800": 1, "\\ud800": 2}', "\\ud800"),
        (b'{"a": "\xc3\x28"}', "json"),
    ],
)
def test_decode_json_rejects(text: str | bytes, field: str) -> None:
    with pytest.raises(SubmissionError) as info:
        decode_json(text)

    assert (info.value.code, info.value.field) == ("invalid_json", field)


def test_parse_assignments() -> None:
    raw = [{"assignment_id": "a", "allowed_template": "", "requirements": ["r"]}]

    assert parse_assignments(raw)["a"].requirements == ("r",)
    with pytest.raises(ConfigurationError):
        parse_assignments(raw * 2)
    with pytest.raises(ConfigurationError):
        parse_assignments([{"assignment_id": "a"}])
