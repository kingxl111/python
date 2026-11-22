"""Создаёт синтетический корпус и размеченные пары ЛР 2.

Запуск: python scripts/build_similarity_corpus.py
"""

import itertools
import json
import re
from pathlib import Path

TEMPLATE = "from typing import Iterable\n"
DATA = Path(__file__).resolve().parent.parent / "data"

BASES = [
    (
        "def solve(values):\n    total = 0\n    for value in values:\n"
        "        if value >= 0:\n            total += value * value\n    return total\n"
    ),
    "def solve(values):\n    return sum(value * value for value in values if value >= 0)\n",
    (
        "def solve(values):\n    positive = filter(lambda value: value >= 0, values)\n"
        "    return sum(map(lambda value: value ** 2, positive))\n"
    ),
    (
        "def solve(values):\n    total = 0\n    index = 0\n    while index < len(values):\n"
        "        value = values[index]\n        if value >= 0:\n"
        "            total += value * value\n        index += 1\n    return total\n"
    ),
    (
        "def solve(values):\n"
        "    squares = [value ** 2 for value in values if value >= 0]\n"
        "    return sum(squares)\n"
    ),
    "def solve(values):\n    return sum([value * value for value in values if value >= 0])\n",
    (
        "def solve(values):\n    total = 0\n    for value in values:\n"
        "        if value < 0:\n            continue\n"
        "        total += value * value\n    return total\n"
    ),
    (
        "from functools import reduce\n\ndef solve(values):\n"
        "    return reduce(\n"
        "        lambda total, value: total + (value * value if value >= 0 else 0), values, 0\n"
        "    )\n"
    ),
    (
        "def solve(values):\n    iterator = iter(values)\n    total = 0\n    while True:\n"
        "        try:\n            value = next(iterator)\n"
        "        except StopIteration:\n            break\n"
        "        if value >= 0:\n            total += value * value\n    return total\n"
    ),
    (
        "def solve(values):\n    return sum(\n"
        "        map(lambda value: value ** 2, [value for value in values if value >= 0])\n"
        "    )\n"
    ),
    "def solve(values):\n    return sum(value * value for value in values if value >= 0)\n",
    (
        "def solve(values):\n    total = 0\n    for value in values:\n"
        "        if value >= 0:\n            total += value * value\n    return total\n"
    ),
]

TEMPLATE_SOURCES = [
    "alpha = 1\n",
    "def other(data):\n    return list(data)\n",
    "class Example:\n    pass\n",
    "import math\n\nresult = math.pi\n",
    "for item in range(3):\n    print(item)\n",
    'if True:\n    text = "ok"\n',
]

RENAMES = {
    "values": "items",
    "value": "item",
    "total": "result",
    "positive": "selected",
    "squares": "powers",
    "index": "position",
    "iterator": "stream",
}


def renamed(source: str) -> str:
    return re.sub(
        r"\b(" + "|".join(RENAMES) + r")\b", lambda match: RENAMES[match.group(0)], source
    )


def formatted(source: str) -> str:
    return "# Изменено только оформление\n" + source.replace(" = ", "=").replace(" >= ", ">=")


def record(
    submission_id: str,
    student_id: str,
    family_id: str,
    split: str,
    code: str,
    parent_id: str | None,
    transformation: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "submission_id": submission_id,
        "student_id": student_id,
        "assignment_id": "assignment-01",
        "submitted_at": "2026-09-08T12:00:00+03:00",
        "text": "Синтетическая учебная сдача для анализа сходства.",
        "code": TEMPLATE + "\n" + code,
        "template_id": "template-01",
        "ai_declaration": {
            "used": False,
            "tool": None,
            "purpose": None,
            "verified_by_student": True,
        },
        "family_id": family_id,
        "parent_id": parent_id,
        "transformation": transformation,
        "split": split,
    }


def build() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    cross_pairs = ((0, 2), (1, 3), (2, 4), (3, 5), (4, 5), (0, 5))
    for split in ("tuning", "evaluation"):
        prefix = "tune" if split == "tuning" else "eval"
        offset = 0 if split == "tuning" else 6
        for local_family in range(6):
            family_number = offset + local_family
            family_id = f"{prefix}-family-{local_family + 1:02d}"
            base_id = f"{prefix}-f{local_family + 1:02d}-v1"
            base = BASES[family_number]
            variants = [
                (base, None, "Независимое синтетическое исходное решение"),
                (
                    base if local_family % 2 == 0 else formatted(base),
                    base_id,
                    "Точная копия" if local_family % 2 == 0 else "Изменение форматирования",
                ),
                (renamed(base), base_id, "Последовательное переименование переменных"),
            ]
            for variant, (code, parent_id, transformation) in enumerate(variants, 1):
                submission_id = f"{prefix}-f{local_family + 1:02d}-v{variant}"
                student_id = f"{prefix}-student-{local_family + 1:02d}-{variant}"
                if split == "tuning" and local_family == 0 and variant == 2:
                    student_id = f"{prefix}-student-{local_family + 1:02d}-1"
                records.append(
                    record(
                        submission_id,
                        student_id,
                        family_id,
                        split,
                        code,
                        parent_id,
                        transformation,
                    )
                )
            ids = [f"{prefix}-f{local_family + 1:02d}-v{number}" for number in range(1, 4)]
            students = {
                item["submission_id"]: item["student_id"]
                for item in records
                if item["submission_id"] in ids
            }
            for left, right in itertools.combinations(ids, 2):
                if students[left] == students[right]:
                    continue
                pairs.append(
                    {
                        "left_id": left,
                        "right_id": right,
                        "derivation_relation": True,
                        "template_only": False,
                    }
                )
        for left_family, right_family in cross_pairs:
            pairs.append(
                {
                    "left_id": f"{prefix}-f{left_family + 1:02d}-v1",
                    "right_id": f"{prefix}-f{right_family + 1:02d}-v1",
                    "derivation_relation": False,
                    "template_only": False,
                }
            )
        template_ids = []
        sources = TEMPLATE_SOURCES[:3] if split == "tuning" else TEMPLATE_SOURCES[3:]
        for local_template, code in enumerate(sources, 1):
            submission_id = f"{prefix}-template-{local_template}"
            template_ids.append(submission_id)
            records.append(
                record(
                    submission_id,
                    f"{prefix}-template-student-{local_template}",
                    f"{prefix}-template-family-{local_template}",
                    split,
                    code,
                    None,
                    "Независимый синтетический пример только с общим шаблоном",
                )
            )
        for left, right in itertools.combinations(template_ids, 2):
            pairs.append(
                {
                    "left_id": left,
                    "right_id": right,
                    "derivation_relation": False,
                    "template_only": True,
                }
            )
    assert len(records) >= 30
    assert len(pairs) >= 40
    assert sum(bool(pair["template_only"]) for pair in pairs) >= 5
    return records, pairs


def main() -> None:
    records, pairs = build()
    for name, values in (("similarity_corpus.jsonl", records), ("similarity_pairs.jsonl", pairs)):
        target = DATA / name
        with target.open("w", encoding="utf-8") as stream:
            for value in values:
                stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"Сдач: {len(records)}; размеченных пар: {len(pairs)}")


if __name__ == "__main__":
    main()
