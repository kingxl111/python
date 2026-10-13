"""Доменные объекты. Не зависят от Pydantic, HTTP и способа хранения."""

from dataclasses import dataclass
from typing import Literal

ContentField = Literal["text", "code"]
FindingKind = Literal["similarity", "rubric_feedback", "processing_error"]


@dataclass(frozen=True, slots=True)
class AIDeclaration:
    used: bool
    tool: str | None
    purpose: str | None
    verified_by_student: bool


@dataclass(frozen=True, slots=True)
class Submission:
    """Неизменяемая версия работы. ``submitted_at`` хранится в исходном представлении."""

    schema_version: int
    submission_id: str
    student_id: str
    assignment_id: str
    submitted_at: str
    text: str
    code: str
    template_id: str | None
    ai_declaration: AIDeclaration


@dataclass(frozen=True, slots=True)
class Assignment:
    assignment_id: str
    allowed_template: str
    requirements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Evidence:
    """Включительный диапазон строк исходного поля, нумерация с 1."""

    submission_id: str
    field: ContentField
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class Finding:
    kind: FindingKind
    score: float | None
    evidence: tuple[Evidence, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    report_id: str
    submission_id: str
    submission_hash: str
    analyzer_id: str
    analyzer_version: str
    config_hash: str
    findings: tuple[Finding, ...]
    created_at: str
    review_required: bool
