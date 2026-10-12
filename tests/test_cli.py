import json
from pathlib import Path

import pytest

from lab_checker.bootstrap import AppConfig, build_container
from lab_checker.cli import main
from lab_checker.errors import SchemaViolationError, UnknownAnalyzerError

DATA = Path(__file__).resolve().parent.parent / "data"
ASSIGNMENTS = DATA / "assignments.json"


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, object], str]:
    code = main(["import", *args])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if captured.out else {}, captured.err


def test_import_sample_submissions(capsys: pytest.CaptureFixture[str]) -> None:
    code, result, _ = run(
        capsys, str(DATA / "submissions.jsonl"), "--assignments", str(ASSIGNMENTS)
    )

    assert code == 0
    assert result["accepted"] == ["sub-001", "sub-002", "sub-003"]
    assert result["duplicate"] == ["sub-001"]
    assert result["errors"] == [
        {
            "line": 5,
            "code": "submission_conflict",
            "field": "submission_id",
            "message": "сдача 'sub-001' уже принята с другим содержимым",
        }
    ]
    assert len(result["reports"]) == 6  # type: ignore[arg-type]
    assert result["analysis_errors"] == []


def test_import_invalid_submissions(capsys: pytest.CaptureFixture[str]) -> None:
    code, result, _ = run(
        capsys, str(DATA / "invalid_submissions.jsonl"), "--assignments", str(ASSIGNMENTS)
    )

    assert code == 0
    assert result["accepted"] == ["ok-001"]
    errors = result["errors"]
    assert isinstance(errors, list)
    assert sorted({error["line"] for error in errors}) == list(range(1, 10))


def test_missing_file_is_reported(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, result, err = run(capsys, str(tmp_path / "none.jsonl"), "--assignments", str(ASSIGNMENTS))

    assert code == 2
    assert result == {}
    assert "ошибка" in err


def test_unknown_analyzer_is_rejected_before_import() -> None:
    with pytest.raises(UnknownAnalyzerError):
        build_container(AppConfig(assignments_path=ASSIGNMENTS, analyzer_ids=("length", "nope")))


def test_invalid_assignments_file(tmp_path: Path) -> None:
    path = tmp_path / "assignments.json"
    path.write_text('[{"assignment_id": "a"}]', encoding="utf-8")

    with pytest.raises(SchemaViolationError):
        build_container(AppConfig(assignments_path=path))
