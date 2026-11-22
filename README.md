# lab-checker

Учебная система онлайн-школы: приём сдач, валидация, заменяемые анализаторы и поиск сходства.
Текущее состояние — ЛР 2, траектория Backend, основной уровень. Сданный код анализируется только как
данные и никогда не выполняется.

## Установка

Нужен Python 3.12 или новее; проверено на 3.14.4.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Запуск

Импорт сдач и анализаторы ЛР 1:

```bash
lab-checker import data/submissions.jsonl
lab-checker import data/submissions.jsonl --assignments data/assignments.json --analyzers length
lab-checker import data/invalid_submissions.jsonl
```

В stdout выводится один JSON с полями `accepted`, `duplicate` и `errors` (у каждой ошибки есть
`line_no`). С `--assignments` добавляются `reports` и `analysis_errors`. Диагностика пишется в stderr.
Коды выхода: 0 — всё успешно; 1 — ошибки отдельных строк или анализа при частичном успехе;
2 — недоступный источник (`source_unavailable`) или конфигурация (`configuration_error`).

Поиск top-k похожих сдач из корпуса ЛР 2:

```bash
lab-checker compare data/similarity_corpus.jsonl \
  --assignments data/assignments.json \
  --submission-id tune-f01-v1 --strategy full --top-k 3
lab-checker compare data/similarity_corpus.jsonl \
  --assignments data/assignments.json \
  --submission-id tune-f01-v1 --strategy index --top-k 3
```

`full` выполняет полный перебор и включает определённые нулевые score. `index` сначала объединяет
postings общих 3-грамм и возвращает только положительные кандидаты. Ответ содержит `candidates`,
двусторонние evidence, сведения о шаблоне, `index_version`, число проверенных кандидатов и ошибки.
Self-match, другой `assignment_id` и другая версия того же студента исключаются.

## Проверки и эксперимент

```bash
ruff check .
ruff format --check .
mypy src tests scripts
pytest
python scripts/benchmark_import.py
python scripts/build_similarity_corpus.py
python scripts/run_similarity_experiment.py --repeats 3 --seed 42
```

Эксперимент создаёт `reports/lab-2-experiment.json`: конфигурацию, хеши корпуса и разметки, split,
порог, метрики, ошибки, версии индекса и сырые повторы измерений. Нагрузочные записи синтетические,
создаются во временном каталоге и не участвуют в оценке качества. Требуется не меньше трёх повторов.
Человекочитаемый отчёт — `reports/lab-2.md`.

Те же статические проверки и тесты запускает GitHub Actions на Python 3.12–3.14. Отдельная джоба
собирает wheel, устанавливает его в чистое окружение и запускает CLI.

## Формат данных

Все данные в `data/` синтетические. `submissions.jsonl` содержит 12 публичных сдач из ноутбука,
`invalid_submissions.jsonl` — ошибки, дубликат и конфликт.

Сдача, версия схемы 1:

| Поле | Тип | Правило |
|---|---|---|
| `schema_version` | `int` | только 1; `bool` не допускается |
| `submission_id`, `student_id`, `assignment_id` | `str` | непустая после `strip()` |
| `submitted_at` | `str` | ISO 8601 с часовым поясом, хранится в исходном виде |
| `text`, `code` | `str` | хотя бы одно непустое после `strip()` |
| `template_id` | `str` или `null` | строка непустая |
| `ai_declaration` | объект | `used`, `tool`, `purpose`, `verified_by_student` |

При `used=true` поля `tool` и `purpose` обязательны. Неизвестные поля отклоняются, типы не
приводятся. В JSON запрещены повторные ключи и `NaN`/`Infinity`. Пустая строка JSONL считается
ошибкой `invalid_json`, чтение продолжается. Ошибка: `{"code", "field", "message"}`.

Задание (`assignments.json`) — список объектов с полями `assignment_id`, `allowed_template`,
`requirements`.

Корпус `similarity_corpus.jsonl` добавляет к каждой сдаче:

| Поле | Назначение |
|---|---|
| `family_id` | Семейство общего происхождения; целиком находится в одном split |
| `parent_id` | Исходная версия внутри семейства или `null` |
| `transformation` | Синтетическое происхождение и преобразование варианта |
| `split` | `tuning` для выбора порога или `evaluation` для итоговой оценки |

Эти поля принадлежат отдельному DTO корпуса и не меняют схему/хеш `Submission`. В
`similarity_pairs.jsonl` каждая строка содержит `left_id`, `right_id`, `derivation_relation` и
`template_only`. Разметка описывает построение учебного примера, а не вердикт о плагиате.

## Устройство

```
src/lab_checker/
  models.py              доменные объекты ЛР 1
  parsing.py             строгие DTO Pydantic и преобразование в домен
  sources.py             ленивые JSONL и in-memory источники
  services.py            приём сдач
  repositories.py        in-memory хранение и итерация снимка
  analysis.py            Analyzer, AnalysisContext, реестр, проверка отчёта
  analyzers.py           LengthAnalyzer и TemplateAnalyzer
  templates.py           точные диапазоны разрешённого шаблона
  similarity.py          tokenize, n-граммы, Jaccard и двусторонние evidence
  corpus.py              DTO корпуса, потоковое чтение, manifest и разметка
  comparison.py          сервис top-k, парный кеш и инвертированный индекс
  similarity_analyzer.py адаптер сходства к общему Analyzer
  evaluation.py          порог, матрица ошибок, precision/recall/F1 и отказы
  bootstrap.py           сборка зависимостей
  adapter.py             тестовый адаптер вместо HTTP
  cli.py                 команды import и compare
```

Ключ парного кеша включает SHA-256 обеих версий сдачи и полную конфигурацию. Evidence ориентированы,
поэтому обратный порядок пары имеет отдельный ключ. Индекс версионируется содержимым корпуса,
реализацией и конфигурацией. Сервис работает с фиксированным снимком: после изменения корпуса или
шаблона создаётся новый экземпляр.

## Ограничения

- Хранилище, кеш и индекс находятся в памяти; между запусками CLI состояние не сохраняется.
- Потоковое чтение не ограничивает память полного индекса: при N документах и L признаках возможны
  до O(N·L) хранимых связей, плюс координаты и кеш.
- Score — сигнал для ручного разбора, а не доказательство нарушения, общего происхождения или
  корректности кода. Решение принимает преподаватель.
- Метрики получены на маленьком синтетическом корпусе и не переносятся на реальных студентов.
- AST-нормализация, TF-IDF и детектор ИИ не входят в выбранный основной Backend-вариант.
