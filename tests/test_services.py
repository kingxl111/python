import copy
import json
from pathlib import Path

import pytest
from conftest import PUBLIC_SUBMISSIONS, RAW_EXAMPLE, changed

from lab_checker.errors import SubmissionError
from lab_checker.repositories import InMemorySubmissionRepository
from lab_checker.services import Acceptance, SubmissionService, import_source
from lab_checker.sources import InMemorySource, JSONLSource


def test_acceptance_contract() -> None:
    repo = InMemorySubmissionRepository()
    service = SubmissionService(repo)

    first = service.accept(RAW_EXAMPLE)
    assert first.status == "accepted"
    duplicate = service.accept(copy.deepcopy(RAW_EXAMPLE))
    assert duplicate == Acceptance("duplicate", "sub-001", first.content_hash)
    previous = repo.get("sub-001")

    with pytest.raises(SubmissionError) as conflict:
        service.accept(changed(code="print('другая версия')"))
    assert (conflict.value.code, conflict.value.field) == ("conflict", "submission_id")
    with pytest.raises(SubmissionError) as invalid:
        service.accept(changed(student_id=""))
    assert invalid.value.code == "schema_error"

    assert repo.get("sub-001") == previous
    assert len(repo) == 1


def test_repository_rejects_second_add() -> None:
    repo = InMemorySubmissionRepository()
    SubmissionService(repo).accept(RAW_EXAMPLE)
    stored = repo.get("sub-001")
    assert stored is not None

    with pytest.raises(SubmissionError) as info:
        repo.add(stored)

    assert info.value.code == "conflict"


def test_mixed_jsonl_import(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    lines = [
        json.dumps(RAW_EXAMPLE),
        "{broken",
        json.dumps(RAW_EXAMPLE),
        json.dumps(changed(text="Другое содержимое с тем же ID")),
        json.dumps(changed(submission_id="bad-record", student_id="")),
        json.dumps(PUBLIC_SUBMISSIONS[1]),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    repo = InMemorySubmissionRepository()

    summary = import_source(JSONLSource(path), SubmissionService(repo))

    assert summary.accepted == ["sub-001", "sub-002"]
    assert summary.duplicate == ["sub-001"]
    assert [(e["line_no"], e["code"]) for e in summary.errors] == [
        (2, "invalid_json"),
        (4, "conflict"),
        (5, "schema_error"),
    ]
    assert len(repo) == 2


def test_repeated_import_gives_duplicates() -> None:
    service = SubmissionService(InMemorySubmissionRepository())

    first = import_source(InMemorySource(PUBLIC_SUBMISSIONS), service)
    second = import_source(InMemorySource(PUBLIC_SUBMISSIONS), service)

    assert len(first.accepted) == 12
    assert not first.errors
    assert len(second.duplicate) == 12
    assert not second.accepted
    assert not second.errors
