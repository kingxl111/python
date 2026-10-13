import json
from pathlib import Path
from typing import Any

import pytest
from conftest import DATA

from lab_checker.cli import main

ASSIGNMENTS = str(DATA / "assignments.json")


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any], str]:
    code = main(["import", *args])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if captured.out else {}, captured.err


def test_public_submissions(capsys: pytest.CaptureFixture[str]) -> None:
    code, result, err = run(capsys, str(DATA / "submissions.jsonl"))

    assert code == 0
    assert result == {
        "accepted": [f"sub-{n:03d}" for n in range(1, 13)],
        "duplicate": [],
        "errors": [],
    }
    assert err == ""


def test_public_submissions_with_analysis(capsys: pytest.CaptureFixture[str]) -> None:
    code, result, _ = run(capsys, str(DATA / "submissions.jsonl"), "--assignments", ASSIGNMENTS)

    assert code == 0
    assert len(result["reports"]) == 24
    assert result["analysis_errors"] == []


def test_invalid_submissions(capsys: pytest.CaptureFixture[str]) -> None:
    code, result, err = run(capsys, str(DATA / "invalid_submissions.jsonl"))

    assert code == 1
    assert result["accepted"] == ["sub-001", "sub-002"]
    assert result["duplicate"] == ["sub-001"]
    assert [e["line_no"] for e in result["errors"]] == [*range(2, 14), 15]
    assert err == ""


def test_missing_assignment_is_analysis_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "assignments.json"
    path.write_text("[]", encoding="utf-8")

    code, result, _ = run(capsys, str(DATA / "submissions.jsonl"), "--assignments", str(path))

    assert code == 1
    assert result["reports"] == []
    assert len(result["analysis_errors"]) == 24


def test_missing_source(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, result, err = run(capsys, str(tmp_path / "none.jsonl"))

    assert code == 2
    assert result == {}
    assert json.loads(err)["code"] == "source_unavailable"


@pytest.mark.parametrize("args", [("--analyzers", "nope"), ("--assignments", "/nonexistent")])
def test_bad_configuration(capsys: pytest.CaptureFixture[str], args: tuple[str, str]) -> None:
    code, result, err = run(capsys, str(DATA / "submissions.jsonl"), *args)

    assert code == 2
    assert result == {}
    assert json.loads(err)["code"] == "configuration_error"
