"""Замер времени импорта и анализа на синтетических сдачах.

Запуск: python scripts/benchmark_import.py [--sizes 1000 10000] [--repeats 3] [--seed 42]
"""

import argparse
import platform
import random
import statistics
import sys
import time
from pathlib import Path

from lab_checker.analysis import AnalysisContext
from lab_checker.bootstrap import build_application, load_assignments
from lab_checker.services import import_source
from lab_checker.sources import InMemorySource

ASSIGNMENTS = Path(__file__).resolve().parent.parent / "data" / "assignments.json"


def synthetic_records(count: int, seed: int) -> list[object]:
    rng = random.Random(seed)
    records: list[object] = []
    for index in range(count):
        statements = rng.randint(1, 40)
        body = "\n".join(f"    value_{i} = {rng.randint(0, 999)}" for i in range(statements))
        records.append(
            {
                "schema_version": 1,
                "submission_id": f"syn-{index:06d}",
                "student_id": f"student-{rng.randint(1, 200):03d}",
                "assignment_id": "assignment-01",
                "submitted_at": "2026-09-01T10:00:00+03:00",
                "text": "Синтетическая сдача для нагрузки.",
                "code": f"from typing import Iterable\n\ndef solve(values):\n{body}\n",
                "template_id": None,
                "ai_declaration": {
                    "used": False,
                    "tool": None,
                    "purpose": None,
                    "verified_by_student": True,
                },
            }
        )
        if rng.random() < 0.05:
            records.append({"broken": True})
    return records


def measure(records: list[object]) -> tuple[float, float]:
    app = build_application()
    context = AnalysisContext(load_assignments(ASSIGNMENTS)["assignment-01"])
    started = time.perf_counter()
    summary = import_source(InMemorySource(records), app.submission_service)
    imported = time.perf_counter()
    for submission_id in summary.accepted:
        for name in app.analyzers:
            app.analysis_service.run(submission_id, name, context)
    finished = time.perf_counter()
    return imported - started, finished - imported


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"python {sys.version.split()[0]}, {platform.platform()}, seed={args.seed}")
    print("записей | импорт, медиана с | анализ, медиана с | записей/с (импорт)")
    for size in args.sizes:
        records = synthetic_records(size, args.seed)
        runs = [measure(records) for _ in range(args.repeats)]
        intake = statistics.median(run[0] for run in runs)
        analysis = statistics.median(run[1] for run in runs)
        rate = len(records) / intake
        print(f"{len(records):7d} | {intake:17.3f} | {analysis:17.3f} | {rate:10.0f}")


if __name__ == "__main__":
    main()
