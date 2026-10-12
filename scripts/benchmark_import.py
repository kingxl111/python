"""Замер времени импорта и анализа на синтетических сдачах.

Запуск: python scripts/benchmark_import.py [--sizes 1000 10000] [--repeats 3] [--seed 42]
"""

import argparse
import json
import platform
import random
import statistics
import sys
import time
from pathlib import Path

from lab_checker.bootstrap import AppConfig, build_container
from lab_checker.sources import InMemorySubmissionSource

ASSIGNMENTS = Path(__file__).resolve().parent.parent / "data" / "assignments.json"


def synthetic_lines(count: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    lines = []
    for index in range(count):
        statements = rng.randint(1, 40)
        body = "\n".join(f"    value_{i} = {rng.randint(0, 999)}" for i in range(statements))
        payload = {
            "submission_id": f"syn-{index:06d}",
            "assignment_id": "lab-01-sum",
            "student_id": f"student-{rng.randint(1, 200):03d}",
            "timestamp": "2026-10-01T10:00:00+03:00",
            "text": "Синтетическая сдача для нагрузки.",
            "code": f"def solve(numbers):\n{body}\n    return sum(numbers)\n",
            "ai_declaration": {"used": False},
        }
        lines.append(json.dumps(payload, ensure_ascii=False))
        if rng.random() < 0.05:
            lines.append("{broken")
    return lines


def measure(lines: list[str]) -> tuple[float, float]:
    container = build_container(AppConfig(assignments_path=ASSIGNMENTS))
    started = time.perf_counter()
    with InMemorySubmissionSource(lines) as source:
        report = container.intake.import_records(source.records())
    imported = time.perf_counter()
    for submission_id in report.accepted:
        container.analysis.analyze(submission_id, container.analyzer_ids)
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
        lines = synthetic_lines(size, args.seed)
        runs = [measure(lines) for _ in range(args.repeats)]
        intake = statistics.median(run[0] for run in runs)
        analysis = statistics.median(run[1] for run in runs)
        print(f"{len(lines):7d} | {intake:17.3f} | {analysis:17.3f} | {len(lines) / intake:10.0f}")


if __name__ == "__main__":
    main()
