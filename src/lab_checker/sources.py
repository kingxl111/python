"""Источники записей сдач. Ресурсом владеет контекст ``open()``."""

import copy
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from lab_checker.errors import SubmissionError
from lab_checker.parsing import decode_json


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Разобранный JSON либо ошибка разбора; ``line_no`` нумеруется с 1."""

    line_no: int
    raw: object = None
    error: SubmissionError | None = None


class SubmissionSource(Protocol):
    def open(self) -> AbstractContextManager[Iterator[SourceRecord]]:
        """Итератор записей допустим только внутри контекста."""
        ...


class InMemorySource:
    def __init__(self, values: Sequence[object]) -> None:
        self._values = copy.deepcopy(list(values))

    @contextmanager
    def open(self) -> Iterator[Iterator[SourceRecord]]:
        yield (
            SourceRecord(number, raw=copy.deepcopy(raw))
            for number, raw in enumerate(self._values, start=1)
        )


class JSONLSource:
    """Читает файл построчно в байтах: неверная кодировка или пустая строка становятся
    ошибкой ``invalid_json`` этой строки, а чтение продолжается."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def open(self) -> Iterator[Iterator[SourceRecord]]:
        with self.path.open("rb") as handle:
            yield self._records(handle)

    @staticmethod
    def _records(handle: BinaryIO) -> Iterator[SourceRecord]:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                yield SourceRecord(
                    number, error=SubmissionError("invalid_json", "json", "Пустая строка")
                )
                continue
            try:
                raw = decode_json(line)
            except SubmissionError as exc:
                yield SourceRecord(number, error=exc)
            else:
                yield SourceRecord(number, raw=raw)
