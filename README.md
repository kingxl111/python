# lab-checker

Учебная система онлайн-школы: приём сдач лабораторных, валидация и запуск заменяемых анализаторов.
Текущее состояние — ЛР 1, траектория Backend, основной уровень.

## Установка

Нужен Python 3.12 или новее; проверено на 3.14.4.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Запуск

```bash
lab-checker import data/submissions.jsonl
lab-checker import data/submissions.jsonl --assignments data/assignments.json --analyzers length
lab-checker import data/invalid_submissions.jsonl
```

В stdout выводится один JSON с полями `accepted`, `duplicate` и `errors` (у каждой ошибки есть
`line_no`). С `--assignments` к нему добавляются `reports` и `analysis_errors`. Диагностика
пишется в stderr как JSON с полями `code` и `message`. Коды выхода: 0 — всё успешно; 1 — есть
ошибки в отдельных строках или при анализе, корректные записи при этом приняты; 2 — источник
недоступен (`source_unavailable`) или ошибка конфигурации (`configuration_error`). Код сдач не
выполняется.

## Проверки

```bash
ruff check .
ruff format --check .
mypy src tests scripts
pytest
python scripts/benchmark_import.py
```

Те же проверки запускает GitHub Actions `.github/workflows/ci.yml` на push в `main` и на
pull request. Тесты идут на Python 3.12, 3.13 и 3.14. Если все проверки прошли, отдельная
джоба собирает пакет, ставит wheel в чистое окружение и запускает CLI на `data/`.

## Формат данных

Контракт взят из ноутбука лекции, данные в `data/` синтетические. `submissions.jsonl` содержит
12 публичных сдач из ноутбука, `invalid_submissions.jsonl` — по одной строке на каждый вид
ошибки, плюс дубликат и конфликт.

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
ошибкой `invalid_json`, чтение продолжается.

Ошибка: `{"code", "field", "message"}`. Коды: `invalid_json`, `schema_error`,
`unsupported_version`, `conflict`.

Задание (`assignments.json`) — список объектов с полями `assignment_id`, `allowed_template`,
`requirements`.

## Устройство

```
src/lab_checker/
  models.py        доменные объекты (frozen dataclass)
  hashing.py       канонический JSON и SHA-256
  errors.py        SubmissionError, AnalysisFailure, ConfigurationError
  parsing.py       разбор JSON и DTO Pydantic с to_domain()
  repositories.py  SubmissionRepository и in-memory реализация
  sources.py       InMemorySource и JSONLSource, open() как контекстный менеджер
  services.py      SubmissionService и import_source
  analysis.py      Analyzer, AnalysisContext, validate_report, реестр, AnalysisService
  analyzers.py     LengthAnalyzer, TemplateAnalyzer
  bootstrap.py     build_application
  adapter.py       тестовый адаптер на месте будущего HTTP
  cli.py           командная строка
```

- **Валидация** выполняется на границе: строгий DTO Pydantic превращается в неизменяемый
  доменный объект. Ошибка Pydantic приводится к `SubmissionError`.
- **Идемпотентность.** `submission_hash` — SHA-256 канонического JSON от `asdict(submission)`.
  Если хеш совпал, ответ `duplicate`. Если под тем же `submission_id` пришло другое содержимое,
  возвращается `conflict`, сохранённая запись не меняется.
- **HTTP-коды** назначает только `adapter.py`: 400, 422, 409, 201, 200.
- **Ресурс** файла принадлежит `JSONLSource.open()`. После выхода из `with` файл закрыт и при
  досрочном выходе, и при исключении.
- **Анализ.** `AnalysisService.run` создаёт анализатор по имени из реестра и проверяет отчёт
  через `validate_report`. Он также сверяет `analyzer_id` и версию. Любой сбой становится
  `AnalysisFailure`.

### Подключение нового анализатора

1. Написать класс с атрибутами `analyzer_id`, `analyzer_version` и методом
   `analyze(submission, context) -> AnalysisReport`; отчёт собирать через `make_report`.
2. Зарегистрировать фабрику в `build_registry()` в `bootstrap.py`.
3. Добавить анализатор в контрактный тест `tests/test_analyzers.py`.

`AnalysisService` при этом не меняется.

## Ограничения

- Хранилище только в памяти: каждый запуск CLI начинает с пустого репозитория.
- `TemplateAnalyzer` сравнивает строки точно, включая отступы и пробелы в конце строки.
