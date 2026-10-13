from dataclasses import replace

import pytest
from conftest import RAW_EXAMPLE, changed

from lab_checker.hashing import canonical_json, stable_hash, submission_hash
from lab_checker.models import Submission
from lab_checker.parsing import parse_submission


def test_key_order_does_not_change_hash(submission: Submission) -> None:
    reordered = dict(reversed(list(RAW_EXAMPLE.items())))

    assert submission_hash(parse_submission(reordered)) == submission_hash(submission)


def test_content_change_changes_hash(submission: Submission) -> None:
    digest = submission_hash(submission)

    assert submission_hash(replace(submission, code=submission.code + "\n")) != digest
    assert submission_hash(replace(submission, student_id="student-other")) != digest


def test_same_moment_in_other_representation_is_other_hash(submission: Submission) -> None:
    utc = parse_submission(changed(submitted_at="2026-09-01T07:01:00+00:00"))

    assert submission_hash(utc) != submission_hash(submission)


def test_canonical_json_format() -> None:
    assert canonical_json({"b": 1, "a": "й"}) == '{"a":"й","b":1}'
    assert len(stable_hash({})) == 64
    with pytest.raises(ValueError):
        canonical_json(float("nan"))
