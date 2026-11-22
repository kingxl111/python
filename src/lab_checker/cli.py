"""Командная строка: приём сдач и сравнение версий из корпуса ЛР 2.

Коды завершения: 0 — всё успешно; 1 — ошибки отдельных строк или анализа;
2 — источник или конфигурация недоступны.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from lab_checker.analysis import AnalysisContext
from lab_checker.bootstrap import (
    DEFAULT_ANALYZERS,
    AppConfig,
    Application,
    build_application,
    load_assignments,
    similarity_config,
)
from lab_checker.comparison import ComparisonService
from lab_checker.corpus import load_corpus
from lab_checker.errors import AnalysisFailure, ConfigurationError, SubmissionError
from lab_checker.models import Assignment
from lab_checker.services import import_source
from lab_checker.sources import JSONLSource


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="lab-checker", description="Учебный анализ сдач")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("import", help="импорт файла сдач")
    run.add_argument("path", type=Path, help="JSONL-файл сдач")
    run.add_argument("--assignments", type=Path, help="JSON-файл заданий; включает анализ")
    run.add_argument(
        "--analyzers",
        default=",".join(DEFAULT_ANALYZERS),
        help="имена анализаторов через запятую (по умолчанию: %(default)s)",
    )
    compare = commands.add_parser("compare", help="top-k похожих сдач из корпуса ЛР 2")
    compare.add_argument("path", type=Path, help="JSONL-файл корпуса с family_id")
    compare.add_argument("--assignments", type=Path, required=True, help="JSON-файл заданий")
    compare.add_argument("--submission-id", required=True, help="сдача, для которой ищутся пары")
    compare.add_argument("--top-k", type=int, default=3, help="число кандидатов")
    compare.add_argument(
        "--strategy", choices=("full", "index"), default="full", help="способ отбора кандидатов"
    )
    return parser.parse_args(argv)


def _fail(code: str, message: str) -> int:
    print(json.dumps({"code": code, "message": message}, ensure_ascii=False), file=sys.stderr)
    return 2


def _analyze(
    app: Application, submission_ids: list[str], assignments: dict[str, Assignment]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    reports: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for submission_id in submission_ids:
        submission = app.repository.get(submission_id)
        assert submission is not None
        assignment = assignments.get(submission.assignment_id)
        for name in app.analyzers:
            if assignment is None:
                errors.append(
                    {
                        "submission_id": submission_id,
                        "analyzer": name,
                        "message": f"Задание {submission.assignment_id!r} не описано",
                    }
                )
                continue
            try:
                report = app.analysis_service.run(submission_id, name, AnalysisContext(assignment))
            except AnalysisFailure as exc:
                errors.append(
                    {"submission_id": submission_id, "analyzer": name, "message": str(exc)}
                )
            else:
                reports.append(asdict(report))
    return reports, errors


def _run_import(args: argparse.Namespace) -> int:
    names = tuple(dict.fromkeys(item.strip() for item in args.analyzers.split(",") if item.strip()))
    try:
        assignments = load_assignments(args.assignments) if args.assignments else None
        config = similarity_config(assignments) if assignments is not None else None
        app = build_application(
            AppConfig(analyzers=names, similarity=config)
            if config is not None
            else AppConfig(names)
        )
    except ConfigurationError as exc:
        return _fail("configuration_error", str(exc))

    try:
        summary = import_source(JSONLSource(args.path), app.submission_service)
    except OSError as exc:
        return _fail("source_unavailable", str(exc))

    result = summary.to_dict()
    failed = bool(summary.errors)
    if assignments is not None:
        result["reports"], result["analysis_errors"] = _analyze(app, summary.accepted, assignments)
        failed = failed or bool(result["analysis_errors"])
    print(json.dumps(result, ensure_ascii=False))
    return 1 if failed else 0


def _run_compare(args: argparse.Namespace) -> int:
    try:
        assignments = load_assignments(args.assignments)
        loaded = load_corpus(args.path)
        service = ComparisonService(loaded.repository, similarity_config(assignments))
        result = service.top_k(args.submission_id, args.top_k, args.strategy)
    except OSError as exc:
        return _fail("source_unavailable", str(exc))
    except (ConfigurationError, SubmissionError, ValueError, KeyError) as exc:
        return _fail("configuration_error", str(exc))
    errors = [*loaded.errors, *(asdict(error) for error in result.errors)]
    output = {
        "query_id": result.query_id,
        "strategy": result.strategy,
        "index_version": result.index_version,
        "examined": result.examined,
        "insufficient_data": result.insufficient_data,
        "candidates": [asdict(candidate) for candidate in result.candidates],
        "errors": errors,
    }
    print(json.dumps(output, ensure_ascii=False))
    return 1 if errors else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "compare":
        return _run_compare(args)
    return _run_import(args)
