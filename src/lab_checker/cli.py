"""Командная строка: импорт JSONL-файла сдач и запуск анализаторов."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from lab_checker.bootstrap import DEFAULT_ANALYZERS, AppConfig, build_container
from lab_checker.errors import AnalysisError, IntakeError
from lab_checker.intake import ImportReport
from lab_checker.models import AnalysisReport
from lab_checker.sources import JsonlSubmissionSource


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="lab-checker", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("import", help="импортировать сдачи и проанализировать принятые")
    run.add_argument("submissions", type=Path, help="JSONL-файл сдач")
    run.add_argument("--assignments", type=Path, required=True, help="JSON-файл заданий")
    run.add_argument(
        "--analyzers",
        default=",".join(DEFAULT_ANALYZERS),
        help="идентификаторы анализаторов через запятую (по умолчанию: %(default)s)",
    )
    return parser.parse_args(argv)


def _import_report_json(report: ImportReport) -> dict[str, object]:
    return {
        "accepted": list(report.accepted),
        "duplicate": list(report.duplicate),
        "errors": [
            {"line": error.line, **asdict(issue)}
            for error in report.errors
            for issue in error.issues
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    analyzer_ids = tuple(
        dict.fromkeys(item.strip() for item in args.analyzers.split(",") if item.strip())
    )
    try:
        container = build_container(
            AppConfig(assignments_path=args.assignments, analyzer_ids=analyzer_ids)
        )
        with JsonlSubmissionSource(args.submissions) as source:
            report = container.intake.import_records(source.records())
        outcomes = [
            outcome
            for submission_id in report.accepted
            for outcome in container.analysis.analyze(submission_id, container.analyzer_ids)
        ]
    except (OSError, IntakeError, AnalysisError) as exc:
        print(f"lab-checker: ошибка: {exc}", file=sys.stderr)
        return 2

    result = _import_report_json(report)
    result["reports"] = [asdict(item) for item in outcomes if isinstance(item, AnalysisReport)]
    result["analysis_errors"] = [
        asdict(item) for item in outcomes if not isinstance(item, AnalysisReport)
    ]
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0
