"""Одинаковый контракт для JSONL и in-memory источников."""

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from conftest import PUBLIC_SUBMISSIONS, RAW_EXAMPLE

from lab_checker.sources import InMemorySource, JSONLSource, SubmissionSource

SourceFactory = Callable[[Sequence[object]], SubmissionSource]


@pytest.fixture(params=["jsonl", "memory"])
def make_source(request: pytest.FixtureRequest, tmp_path: Path) -> SourceFactory:
    def jsonl(values: Sequence[object]) -> SubmissionSource:
        path = tmp_path / "submissions.jsonl"
        path.write_text("".join(json.dumps(v) + "\n" for v in values), encoding="utf-8")
        return JSONLSource(path)

    return jsonl if request.param == "jsonl" else InMemorySource


def test_source_contract(make_source: SourceFactory) -> None:
    with make_source(PUBLIC_SUBMISSIONS).open() as records:
        loaded = list(records)

    assert [r.line_no for r in loaded] == list(range(1, len(PUBLIC_SUBMISSIONS) + 1))
    assert [r.raw for r in loaded] == PUBLIC_SUBMISSIONS
    assert all(r.error is None for r in loaded)


def test_records_are_copies(make_source: SourceFactory) -> None:
    source = make_source([RAW_EXAMPLE])

    with source.open() as records:
        record = next(records)
    assert isinstance(record.raw, dict)
    record.raw["text"] = "изменено"

    with source.open() as records:
        assert next(records).raw == RAW_EXAMPLE


def test_jsonl_is_closed_after_early_exit(tmp_path: Path) -> None:
    path = tmp_path / "submissions.jsonl"
    path.write_text("{}\n{}\n", encoding="utf-8")

    with JSONLSource(path).open() as records:
        next(records)

    with pytest.raises(ValueError):
        next(records)


def test_jsonl_is_closed_after_consumer_error(tmp_path: Path) -> None:
    path = tmp_path / "submissions.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ZeroDivisionError), JSONLSource(path).open() as records:
        _ = 1 / 0

    with pytest.raises(ValueError):
        next(records)


def test_jsonl_line_errors_do_not_stop_reading(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    path.write_bytes(b'{"text": "\xc3\x28"}\r\n\r\n   \n{"a": 1, "a": 2}\n{}\r\n')

    with JSONLSource(path).open() as records:
        loaded = list(records)

    assert [(r.line_no, r.error.code if r.error else None) for r in loaded] == [
        (1, "invalid_json"),
        (2, "invalid_json"),
        (3, "invalid_json"),
        (4, "invalid_json"),
        (5, None),
    ]
    assert loaded[-1].raw == {}
