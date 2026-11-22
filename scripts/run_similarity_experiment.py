"""Воспроизводимый эксперимент ЛР 2.

Запуск: python scripts/run_similarity_experiment.py --repeats 3 --seed 42
Нагрузочные записи синтетические и не участвуют в оценке качества.
"""

import argparse
import gc
import hashlib
import json
import platform
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

from lab_checker.bootstrap import load_assignments, similarity_config
from lab_checker.comparison import ComparisonService
from lab_checker.corpus import (
    CorpusManifest,
    LabelledPair,
    load_corpus,
    read_labelled_pairs,
    validate_labelled_pairs,
)
from lab_checker.evaluation import (
    ScoredPair,
    choose_threshold,
    classification_errors,
    classification_metrics,
    metric_rows,
    score_pairs,
)
from lab_checker.similarity import SimilarityConfig

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TEMPLATE = "from typing import Iterable\n"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_pairs(path: Path, manifest: CorpusManifest) -> tuple[LabelledPair, ...]:
    pairs: list[LabelledPair] = []
    for record in read_labelled_pairs(path):
        if record.error is not None:
            raise ValueError(f"Ошибка разметки в строке {record.line_no}: {record.error}")
        assert record.value is not None
        pairs.append(record.value)
    return validate_labelled_pairs(iter(pairs), manifest)


def load_record(index: int, rng: random.Random) -> dict[str, object]:
    if index % 5 == 0:
        code = "def solve(values):\n    return sum(x * x for x in values if x >= 0)\n"
    else:
        statements = rng.randint(1, 40)
        body = "\n".join(
            f"    local_{index}_{position} = {rng.randint(0, 999)}"
            for position in range(statements)
        )
        code = (
            f"def solve_{index}(value_{index}):\n{body}\n"
            f"    return value_{index} + local_{index}_0\n"
        )
    return {
        "schema_version": 1,
        "submission_id": f"load-{index:06d}",
        "student_id": f"load-student-{index:06d}",
        "assignment_id": "assignment-01",
        "submitted_at": "2026-09-08T12:00:00+03:00",
        "text": "Синтетическая запись только для нагрузочного замера.",
        "code": TEMPLATE + "\n" + code,
        "template_id": "template-01",
        "ai_declaration": {
            "used": False,
            "tool": None,
            "purpose": None,
            "verified_by_student": True,
        },
        "family_id": f"load-family-{index:06d}",
        "parent_id": None,
        "transformation": "Нагрузочная синтетическая запись",
        "split": "tuning",
    }


def build_load_file(directory: Path, size: int, seed: int) -> Path:
    rng = random.Random(seed + size)
    path = directory / f"load-{size}.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for index in range(size):
            stream.write(json.dumps(load_record(index, rng), ensure_ascii=False) + "\n")
    return path


def build_service(path: Path, config: SimilarityConfig) -> ComparisonService:
    loaded = load_corpus(path)
    if loaded.errors:
        raise ValueError(f"Ошибки нагрузочного корпуса: {loaded.errors[:1]}")
    return ComparisonService(loaded.repository, config)


def measure_processing(path: Path, config: SimilarityConfig, repeats: int) -> dict[str, object]:
    durations: list[float] = []
    peaks: list[int] = []
    for _ in range(repeats):
        started = time.perf_counter()
        service = build_service(path, config)
        durations.append(time.perf_counter() - started)
        del service
        gc.collect()
    for _ in range(repeats):
        tracemalloc.start()
        try:
            service = build_service(path, config)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        del service
        gc.collect()
    return {
        "repeats": repeats,
        "seconds_runs": durations,
        "seconds_median": statistics.median(durations),
        "peak_bytes_runs": peaks,
        "python_peak_bytes_median": statistics.median(peaks),
    }


def query_ids(size: int, count: int = 20) -> list[str]:
    return [f"load-{index * size // count:06d}" for index in range(count)]


def candidate_recall(service: ComparisonService, queries: list[str]) -> float | None:
    reference_count = 0
    preserved_count = 0
    for query_id in queries:
        full = service.top_k(query_id, service.document_count, "full")
        indexed = service.top_k(query_id, service.document_count, "index")
        reference = {
            item.right_id for item in full.candidates if item.score is not None and item.score > 0
        }
        candidates = {item.right_id for item in indexed.candidates}
        reference_count += len(reference)
        preserved_count += len(reference & candidates)
    return preserved_count / reference_count if reference_count else None


def measure_retrieval(
    service: ComparisonService, repeats: int, queries: list[str] | None = None
) -> dict[str, object]:
    queries = query_ids(service.document_count) if queries is None else queries
    measurements: dict[str, object] = {}
    medians: dict[str, float] = {}
    for strategy in ("full", "index"):
        durations: list[float] = []
        examined = 0
        for _ in range(repeats):
            service.clear_pair_cache()
            started = time.perf_counter()
            for query_id in queries:
                result = service.top_k(query_id, 3, strategy)
                examined += result.examined
            durations.append(time.perf_counter() - started)
        medians[strategy] = statistics.median(durations)
        measurements[strategy] = {
            "seconds_runs": durations,
            "seconds_median": medians[strategy],
            "examined_comparisons_runs_total": examined,
        }
    return {
        "queries": queries,
        "top_k": 3,
        "candidate_reference": "все допустимые кандидаты полного перебора со score > 0",
        "candidate_recall": candidate_recall(service, queries),
        "speedup_median": medians["full"] / medians["index"],
        "strategies": measurements,
    }


def diagnostic_cases(
    service: ComparisonService,
    config: SimilarityConfig,
    pairs: tuple[LabelledPair, ...],
    scored: tuple[ScoredPair, ...],
    manifest: CorpusManifest,
) -> dict[str, object]:
    entries = {entry.submission_id: entry for entry in manifest.entries}
    renamed = next(
        pair
        for pair in scored
        if pair.split == "evaluation" and "переименование" in entries[pair.right_id].transformation
    )
    template_pair = next(
        pair for pair in pairs if entries[pair.left_id].split == "evaluation" and pair.template_only
    )
    without_exclusion = replace(config, exclude_template=False)
    other_service = ComparisonService(
        load_corpus(DATA / "similarity_corpus.jsonl").repository, without_exclusion
    )
    template_before = other_service.compare(template_pair.left_id, template_pair.right_id)
    template_after = service.compare(template_pair.left_id, template_pair.right_id)
    independent = service.compare("eval-f05-v1", "eval-f06-v1")
    return {
        "renaming": {
            "left_id": renamed.left_id,
            "right_id": renamed.right_id,
            "score": renamed.score,
            "demonstration_threshold": 0.5,
            "kind": "FN при демонстрационном пороге 0.5",
        },
        "template": {
            "left_id": template_pair.left_id,
            "right_id": template_pair.right_id,
            "score_without_exclusion": template_before.score,
            "score_with_exclusion": template_after.score,
            "config_hash_without_exclusion": without_exclusion.config_hash,
            "config_hash_with_exclusion": config.config_hash,
            "index_version_without_exclusion": other_service.index.version,
            "index_version_with_exclusion": service.index.version,
        },
        "independent_standard_solution": {
            "left_id": independent.left_id,
            "right_id": independent.right_id,
            "score": independent.score,
            "kind": "FP: независимое происхождение не следует из совпадения представления",
        },
    }


def run(seed: int, repeats: int, sizes: list[int]) -> dict[str, object]:
    assignments = load_assignments(DATA / "assignments.json")
    config = similarity_config(assignments)
    corpus_path = DATA / "similarity_corpus.jsonl"
    pairs_path = DATA / "similarity_pairs.jsonl"
    loaded = load_corpus(corpus_path)
    if loaded.errors:
        raise ValueError(f"Основной корпус содержит ошибки: {loaded.errors}")
    pairs = load_pairs(pairs_path, loaded.manifest)
    service = ComparisonService(loaded.repository, config)
    scored = score_pairs(service, pairs, loaded.manifest)
    threshold = choose_threshold(metric_rows(scored, "tuning"))
    processing: list[dict[str, object]] = []
    retrieval: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="lab_checker_lab2_") as temporary:
        for size in sizes:
            path = build_load_file(Path(temporary), size, seed)
            measurements = measure_processing(path, config, repeats)
            processing.append(
                {
                    "records": size,
                    "all_unordered_pairs_upper_bound": size * (size - 1) // 2,
                    **measurements,
                }
            )
            load_service = build_service(path, config)
            retrieval.append(
                {
                    "records": size,
                    "index_version": load_service.index.version,
                    "postings": load_service.index.postings_count,
                    "posting_references": load_service.index.references_count,
                    **measure_retrieval(load_service, repeats),
                }
            )
    return {
        "trajectory": "Backend",
        "level": "основной",
        "seed": seed,
        "environment": {"python": sys.version, "platform": platform.platform()},
        "parameters": {
            "repeats": repeats,
            "sizes": sizes,
            "concurrency": False,
            "memory_metric": "tracemalloc: отслеживаемые Python-аллокации, не RSS",
            "processing_pipeline": "JSONL read -> validate -> features -> token index",
        },
        "config": config.payload(),
        "corpus_hash": file_hash(corpus_path),
        "pairs_hash": file_hash(pairs_path),
        "split": loaded.manifest.to_dict(),
        "quality": {
            "threshold_selected_on_tuning": threshold,
            "tuning": classification_metrics(metric_rows(scored, "tuning"), threshold).to_dict(),
            "evaluation": classification_metrics(
                metric_rows(scored, "evaluation"), threshold
            ).to_dict(),
            "evaluation_errors": classification_errors(scored, "evaluation", threshold),
            "pairs": [asdict(pair) for pair in scored],
        },
        "diagnostics": diagnostic_cases(service, config, pairs, scored, loaded.manifest),
        "index": {
            "version": service.index.version,
            "postings": service.index.postings_count,
            "posting_references": service.index.references_count,
            "policy": (
                "Индекс возвращает только пары с общим признаком; "
                "полный перебор также выдаёт score=0."
            ),
        },
        "processing_benchmark": processing,
        "fixed_retrieval": measure_retrieval(
            service,
            repeats,
            [entry.submission_id for entry in loaded.manifest.entries],
        ),
        "retrieval_benchmark": retrieval,
        "limitations": [
            "Небольшой синтетический корпус; метрики не переносятся на реальных студентов.",
            "Пары одной сдачи не являются независимыми наблюдениями.",
            (
                "Score измеряет представление кода и не доказывает нарушение "
                "или корректность программы."
            ),
            (
                "Сервис использует снимок корпуса; после изменения корпуса "
                "или конфигурации нужен новый сервис."
            ),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 5000])
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "lab-2-experiment.json")
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("repeats должно быть не меньше 3")
    report = run(args.seed, args.repeats, args.sizes)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    quality = cast(dict[str, object], report["quality"])
    print(f"Отчёт: {args.output}")
    print(f"Порог: {quality['threshold_selected_on_tuning']}")
    print(f"Оценка: {quality['evaluation']}")


if __name__ == "__main__":
    main()
