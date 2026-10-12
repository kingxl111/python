"""Источники записей сдач. Ресурсом источника управляет вызывающий код через ``with``."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Protocol, Self


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Одна запись источника. ``line`` — номер строки, нумерация с 1."""

    line: int
    raw: str | bytes


class SubmissionSource(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def records(self) -> Iterator[SourceRecord]:
        """Записи по порядку; пустые строки пропускаются, номера строк сохраняются."""
        ...


class JsonlSubmissionSource:
    """JSONL-файл. Строки читаются в байтах, чтобы неверная кодировка одной строки
    стала ошибкой этой записи, а не всего импорта."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: BinaryIO | None = None

    def __enter__(self) -> Self:
        if self._file is not None:
            raise RuntimeError("источник уже открыт")
        self._file = self._path.open("rb")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    @property
    def closed(self) -> bool:
        return self._file is None

    def records(self) -> Iterator[SourceRecord]:
        if self._file is None:
            raise RuntimeError("источник не открыт: используйте with")
        return self._iterate(self._file)

    @staticmethod
    def _iterate(file: BinaryIO) -> Iterator[SourceRecord]:
        for number, line in enumerate(file, start=1):
            if line.strip():
                yield SourceRecord(line=number, raw=line.rstrip(b"\r\n"))


class InMemorySubmissionSource:
    """Источник из готовых строк: один элемент — одна строка JSONL."""

    def __init__(self, lines: Sequence[str]) -> None:
        self._lines = tuple(lines)
        self._opened = False

    def __enter__(self) -> Self:
        if self._opened:
            raise RuntimeError("источник уже открыт")
        self._opened = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._opened = False

    @property
    def closed(self) -> bool:
        return not self._opened

    def records(self) -> Iterator[SourceRecord]:
        if not self._opened:
            raise RuntimeError("источник не открыт: используйте with")
        return (
            SourceRecord(line=number, raw=line)
            for number, line in enumerate(self._lines, start=1)
            if line.strip()
        )
