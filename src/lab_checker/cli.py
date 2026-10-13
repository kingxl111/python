"""Командная строка: импорт JSONL-файла сдач и, при наличии заданий, их анализ.

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
)
from lab_checker.errors import AnalysisFailure, ConfigurationError
from lab_checker.models import Assignment
from lab_checker.services import import_source
from lab_checker.sources import JSONLSource


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="lab-checker", description="Приём учебных сдач из JSONL")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("import", help="импорт файла сдач")
    run.add_argument("path", type=Path, help="JSONL-файл сдач")
    run.add_argument("--assignments", type=Path, help="JSON-файл заданий; включает анализ")
    run.add_argument(
        "--analyzers",
        default=",".join(DEFAULT_ANALYZERS),
        help="имена анализаторов через запятую (по умолчанию: %(default)s)",
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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    names = tuple(dict.fromkeys(item.strip() for item in args.analyzers.split(",") if item.strip()))
    try:
        app = build_application(AppConfig(analyzers=names))
        assignments = load_assignments(args.assignments) if args.assignments else None
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
