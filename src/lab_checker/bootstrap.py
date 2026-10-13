"""Сборка приложения из конфигурации."""

from dataclasses import dataclass
from pathlib import Path

from lab_checker.analysis import AnalysisService, AnalyzerRegistry
from lab_checker.analyzers import LengthAnalyzer, TemplateAnalyzer
from lab_checker.errors import ConfigurationError, SubmissionError
from lab_checker.models import Assignment
from lab_checker.parsing import decode_json, parse_assignments
from lab_checker.repositories import InMemorySubmissionRepository
from lab_checker.services import SubmissionService

DEFAULT_ANALYZERS = (LengthAnalyzer.analyzer_id, TemplateAnalyzer.analyzer_id)


@dataclass(frozen=True, slots=True)
class AppConfig:
    analyzers: tuple[str, ...] = DEFAULT_ANALYZERS


@dataclass(frozen=True, slots=True)
class Application:
    repository: InMemorySubmissionRepository
    submission_service: SubmissionService
    analysis_service: AnalysisService
    analyzers: tuple[str, ...]


def build_registry() -> AnalyzerRegistry:
    """Новый анализатор подключается регистрацией здесь; сервисы не меняются."""
    registry = AnalyzerRegistry()
    registry.register(LengthAnalyzer.analyzer_id, LengthAnalyzer)
    registry.register(TemplateAnalyzer.analyzer_id, TemplateAnalyzer)
    return registry


def build_application(
    config: AppConfig | None = None, registry: AnalyzerRegistry | None = None
) -> Application:
    """Неизвестный анализатор в конфигурации — отказ до первого вызова."""
    config = config if config is not None else AppConfig()
    registry = registry if registry is not None else build_registry()
    for name in config.analyzers:
        if name not in registry:
            raise ConfigurationError(f"Неизвестный анализатор в конфигурации: {name}")
    repository = InMemorySubmissionRepository()
    return Application(
        repository=repository,
        submission_service=SubmissionService(repository),
        analysis_service=AnalysisService(repository, registry),
        analyzers=config.analyzers,
    )


def load_assignments(path: Path) -> dict[str, Assignment]:
    try:
        raw = decode_json(path.read_bytes())
    except OSError as exc:
        raise ConfigurationError(f"Файл заданий недоступен: {exc}") from exc
    except SubmissionError as exc:
        raise ConfigurationError(f"Файл заданий не является корректным JSON: {exc}") from exc
    return parse_assignments(raw)
