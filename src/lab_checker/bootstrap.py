"""Сборка зависимостей приложения из конфигурации."""

from dataclasses import dataclass
from pathlib import Path

from lab_checker.analysis import AnalysisService, AnalyzerRegistry
from lab_checker.analyzers import LengthAnalyzer, TemplateAnalyzer
from lab_checker.errors import UnknownAnalyzerError
from lab_checker.intake import IntakeService
from lab_checker.models import Assignment
from lab_checker.repositories import InMemoryAssignmentCatalog, InMemorySubmissionRepository
from lab_checker.schemas import decode_json, parse_assignments

DEFAULT_ANALYZERS = (LengthAnalyzer.analyzer_id, TemplateAnalyzer.analyzer_id)


@dataclass(frozen=True, slots=True)
class AppConfig:
    assignments_path: Path
    analyzer_ids: tuple[str, ...] = DEFAULT_ANALYZERS


@dataclass(frozen=True, slots=True)
class Container:
    intake: IntakeService
    analysis: AnalysisService
    analyzer_ids: tuple[str, ...]


def build_registry() -> AnalyzerRegistry:
    """Новый анализатор подключается регистрацией здесь; сервисы не меняются."""
    registry = AnalyzerRegistry()
    registry.register(LengthAnalyzer.analyzer_id, LengthAnalyzer)
    registry.register(TemplateAnalyzer.analyzer_id, TemplateAnalyzer)
    return registry


def load_assignments(path: Path) -> tuple[Assignment, ...]:
    return parse_assignments(decode_json(path.read_bytes()))


def build_container(config: AppConfig, registry: AnalyzerRegistry | None = None) -> Container:
    """Проверяет конфигурацию до первой обработки: неизвестный анализатор — ошибка сразу."""
    registry = registry if registry is not None else build_registry()
    for analyzer_id in config.analyzer_ids:
        if analyzer_id not in registry:
            raise UnknownAnalyzerError(analyzer_id)
    catalog = InMemoryAssignmentCatalog(load_assignments(config.assignments_path))
    submissions = InMemorySubmissionRepository()
    return Container(
        intake=IntakeService(submissions, catalog),
        analysis=AnalysisService(submissions, catalog, registry),
        analyzer_ids=config.analyzer_ids,
    )
