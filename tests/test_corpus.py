import json
from pathlib import Path

import pytest
from conftest import DATA

from lab_checker.corpus import (
    LabelledPair,
    build_manifest,
    load_corpus,
    read_corpus,
    read_labelled_pairs,
    validate_labelled_pairs,
)


def labelled_pairs() -> tuple[LabelledPair, ...]:
    records = read_labelled_pairs(DATA / "similarity_pairs.jsonl")
    assert all(record.error is None for record in records)
    return tuple(
        record.value
        for record in read_labelled_pairs(DATA / "similarity_pairs.jsonl")
        if record.value
    )


def test_fixed_corpus_size_labels_and_family_split() -> None:
    loaded = load_corpus(DATA / "similarity_corpus.jsonl")
    pairs = validate_labelled_pairs(iter(labelled_pairs()), loaded.manifest)

    assert loaded.errors == ()
    assert len(loaded.manifest.entries) >= 30
    assert len(pairs) >= 40
    assert sum(pair.template_only for pair in pairs) >= 5
    assert set(loaded.manifest.tuning_families).isdisjoint(loaded.manifest.evaluation_families)
    assert len({entry.student_id for entry in loaded.manifest.entries}) >= 30


def test_streaming_reader_continues_after_bad_json(tmp_path: Path) -> None:
    source = (DATA / "similarity_corpus.jsonl").read_text("utf-8").splitlines()
    first = json.loads(source[0])
    second = json.loads(source[1])
    second["submission_id"] = "second-valid"
    second["parent_id"] = None
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        "\n".join((json.dumps(first), "{broken", json.dumps(second))) + "\n",
        encoding="utf-8",
    )

    records = read_corpus(path)
    assert next(records).value is not None
    broken = next(records)
    assert broken.error is not None and broken.error.code == "invalid_json"
    assert broken.line_no == 2
    assert next(records).value is not None
    with pytest.raises(StopIteration):
        next(records)


def test_unknown_corpus_field_is_rejected(tmp_path: Path) -> None:
    raw = json.loads((DATA / "similarity_corpus.jsonl").read_text("utf-8").splitlines()[0])
    raw["unexpected"] = True
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    (record,) = tuple(read_corpus(path))

    assert record.error is not None
    assert record.error.code == "schema_error"
    assert record.error.field == "unexpected"


def test_pair_cannot_cross_tuning_and_evaluation() -> None:
    loaded = load_corpus(DATA / "similarity_corpus.jsonl")
    left = next(entry for entry in loaded.manifest.entries if entry.split == "tuning")
    right = next(
        entry
        for entry in loaded.manifest.entries
        if entry.split == "evaluation" and entry.student_id != left.student_id
    )
    pair = LabelledPair(left.submission_id, right.submission_id, False, False)

    with pytest.raises(ValueError, match="пересекает"):
        validate_labelled_pairs(iter((pair,)), loaded.manifest)


def test_derivation_label_is_checked_against_family() -> None:
    loaded = load_corpus(DATA / "similarity_corpus.jsonl")
    left = loaded.manifest.entries[0]
    right = next(
        entry
        for entry in loaded.manifest.entries
        if entry.family_id == left.family_id and entry.student_id != left.student_id
    )
    pair = LabelledPair(left.submission_id, right.submission_id, False, False)

    with pytest.raises(ValueError, match="derivation_relation"):
        validate_labelled_pairs(iter((pair,)), loaded.manifest)


def test_manifest_rejects_family_leakage() -> None:
    records = [record.value for record in read_corpus(DATA / "similarity_corpus.jsonl")]
    first = next(value for value in records if value is not None)
    second = next(
        value
        for value in records
        if value is not None
        and value.family_id == first.family_id
        and value.submission.submission_id != first.submission.submission_id
    )
    moved = type(second)(
        second.submission, second.family_id, second.parent_id, second.transformation, "evaluation"
    )

    with pytest.raises(ValueError, match="оба набора"):
        build_manifest(iter((first, moved)))
