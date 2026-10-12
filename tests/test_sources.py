"""Контрактные тесты источников: одинаковые проверки для JSONL и in-memory."""

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from conftest import PayloadFactory, to_line

from lab_checker.intake import ImportReport, IntakeService
from lab_checker.repositories import InMemoryAssignmentCatalog, InMemorySubmissionRepository
from lab_checker.sources import InMemorySubmissionSource, JsonlSubmissionSource

Source = JsonlSubmissionSource | InMemorySubmissionSource
SourceFactory = Callable[[Sequence[str]], Source]


def jsonl_source(directory: Path, lines: Sequence[str]) -> JsonlSubmissionSource:
    path = directory / "submissions.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return JsonlSubmissionSource(path)


@pytest.fixture(params=["jsonl", "memory"])
def make_source(request: pytest.FixtureRequest, tmp_path: Path) -> SourceFactory:
    if request.param == "jsonl":
        return lambda lines: jsonl_source(tmp_path, lines)
    return InMemorySubmissionSource


def import_all(source: Source, catalog: InMemoryAssignmentCatalog) -> ImportReport:
    intake = IntakeService(InMemorySubmissionRepository(), catalog)
    with source:
        return intake.import_records(source.records())


def test_records_keep_line_numbers_and_skip_blank_lines(
    make_source: SourceFactory, make_payload: PayloadFactory, catalog: InMemoryAssignmentCatalog
) -> None:
    lines = [
        "",
        to_line(make_payload()),
        "   ",
        "{broken",
        to_line(make_payload(submission_id="b")),
    ]

    report = import_all(make_source(lines), catalog)

    assert report.accepted == ("sub-001", "b")
    assert [(error.line, error.issues[0].code) for error in report.errors] == [(4, "invalid_json")]


def test_records_require_open_source(make_source: SourceFactory) -> None:
    with pytest.raises(RuntimeError):
        make_source(["{}"]).records()


def test_source_cannot_be_entered_twice(make_source: SourceFactory) -> None:
    source = make_source(["{}"])

    with source, pytest.raises(RuntimeError):
        source.__enter__()


def test_source_is_closed_after_error(
    make_source: SourceFactory, make_payload: PayloadFactory
) -> None:
    source = make_source([to_line(make_payload())])

    with pytest.raises(ZeroDivisionError), source:
        next(source.records())
        _ = 1 / 0

    assert source.closed


def test_source_is_closed_after_early_stop(make_source: SourceFactory) -> None:
    source = make_source(["{}", "{}", "{}"])

    with source:
        for record in source.records():
            if record.line == 1:
                break

    assert source.closed


def test_jsonl_and_memory_sources_give_same_import(
    tmp_path: Path, make_payload: PayloadFactory, catalog: InMemoryAssignmentCatalog
) -> None:
    lines = [
        to_line(make_payload()),
        "[]",
        to_line(make_payload()),
        to_line(make_payload(text="x")),
    ]

    from_file = import_all(jsonl_source(tmp_path, lines), catalog)
    from_memory = import_all(InMemorySubmissionSource(lines), catalog)

    assert from_file == from_memory
    assert from_file.accepted == ("sub-001",)
    assert from_file.duplicate == ("sub-001",)
    assert [error.issues[0].code for error in from_file.errors] == [
        "invalid_type",
        "submission_conflict",
    ]


def test_jsonl_line_with_bad_encoding_does_not_stop_import(
    tmp_path: Path, make_payload: PayloadFactory, catalog: InMemoryAssignmentCatalog
) -> None:
    path = tmp_path / "mixed.jsonl"
    path.write_bytes(
        b'{"text": "\xc3\x28"}\r\n' + to_line(make_payload()).encode("utf-8") + b"\r\n"
    )

    report = import_all(JsonlSubmissionSource(path), catalog)

    assert report.accepted == ("sub-001",)
    assert [(error.line, error.issues[0].code) for error in report.errors] == [(1, "invalid_json")]
