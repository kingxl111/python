"""Доменные объекты. Не зависят от Pydantic, HTTP и способа хранения."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

ContentSource = Literal["text", "code"]

_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def split_lines(content: str) -> list[str]:
    """Делит содержимое на строки по правилам текстового режима ``open``.

    Номер строки равен индексу в результате плюс один.
    """
    if not content:
        return []
    lines = _LINE_BREAK.split(content)
    if lines[-1] == "":
        lines.pop()
    return lines


@dataclass(frozen=True, slots=True)
class AIDeclaration:
    used: bool
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Submission:
    submission_id: str
    assignment_id: str
    student_id: str
    timestamp: datetime
    text: str
    code: str
    ai_declaration: AIDeclaration

    @property
    def submission_hash(self) -> str:
        """SHA-256 канонического содержимого сдачи без ``submission_id``.

        Время приводится к UTC, поэтому один момент с разными смещениями даёт один хеш.
        """
        payload = {
            "assignment_id": self.assignment_id,
            "student_id": self.student_id,
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
            "text": self.text,
            "code": self.code,
            "ai_declaration": {
                "used": self.ai_declaration.used,
                "description": self.ai_declaration.description,
            },
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def content(self, source: ContentSource) -> str:
        return self.text if source == "text" else self.code


@dataclass(frozen=True, slots=True)
class Assignment:
    assignment_id: str
    title: str
    requirements: tuple[str, ...]
    template_code: str


@dataclass(frozen=True, slots=True)
class Evidence:
    """Основание вывода: диапазон строк исходного содержимого, нумерация с 1, включительно."""

    source: ContentSource
    start_line: int
    end_line: int
    note: str


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    submission_id: str
    analyzer_id: str
    analyzer_version: str
    score: float | None
    similarity: float | None
    rubric_feedback: tuple[str, ...]
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisFailure:
    submission_id: str
    analyzer_id: str
    code: str
    message: str
