"""Сборка приложения из конфигурации."""

from dataclasses import dataclass, field
from pathlib import Path

from lab_checker.analysis import AnalysisService, AnalyzerRegistry
from lab_checker.analyzers import LengthAnalyzer, TemplateAnalyzer
from lab_checker.comparison import ComparisonService, SubmissionCatalog
from lab_checker.errors import ConfigurationError, SubmissionError
from lab_checker.models import Assignment
from lab_checker.parsing import decode_json, parse_assignments
from lab_checker.repositories import InMemorySubmissionRepository
from lab_checker.services import SubmissionService
from lab_checker.similarity import SimilarityConfig, TemplateRule
from lab_checker.similarity_analyzer import SimilarityAnalyzer

DEFAULT_ANALYZERS = (LengthAnalyzer.analyzer_id, TemplateAnalyzer.analyzer_id)


@dataclass(frozen=True, slots=True)
class AppConfig:
    analyzers: tuple[str, ...] = DEFAULT_ANALYZERS
    similarity: SimilarityConfig = field(default_factory=SimilarityConfig)


@dataclass(frozen=True, slots=True)
class Application:
    repository: InMemorySubmissionRepository
    submission_service: SubmissionService
    analysis_service: AnalysisService
    analyzers: tuple[str, ...]


def build_registry(
    repository: SubmissionCatalog | None = None,
    similarity: SimilarityConfig | None = None,
) -> AnalyzerRegistry:
    """Новый анализатор подключается регистрацией здесь; сервисы не меняются."""
    similarity = similarity if similarity is not None else SimilarityConfig()
    registry = AnalyzerRegistry()
    registry.register(LengthAnalyzer.analyzer_id, LengthAnalyzer)
    registry.register(TemplateAnalyzer.analyzer_id, TemplateAnalyzer)
    if repository is not None:
        registry.register(
            SimilarityAnalyzer.analyzer_id,
            lambda: SimilarityAnalyzer(ComparisonService(repository, similarity)),
        )
    return registry


def build_application(
    config: AppConfig | None = None, registry: AnalyzerRegistry | None = None
) -> Application:
    """Неизвестный анализатор в конфигурации — отказ до первого вызова."""
    config = config if config is not None else AppConfig()
    repository = InMemorySubmissionRepository()
    registry = registry if registry is not None else build_registry(repository, config.similarity)
    for name in config.analyzers:
        if name not in registry:
            raise ConfigurationError(f"Неизвестный анализатор в конфигурации: {name}")
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


def similarity_config(assignments: dict[str, Assignment]) -> SimilarityConfig:
    return SimilarityConfig(
        rules=tuple(
            TemplateRule(assignment_id, assignment.allowed_template)
            for assignment_id, assignment in sorted(assignments.items())
        )
    )
