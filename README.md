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
lab-checker import data/submissions.jsonl --assignments data/assignments.json
lab-checker import data/invalid_submissions.jsonl --assignments data/assignments.json --analyzers length
```

Команда выводит JSON с полями `accepted`, `duplicate`, `errors` (с номером строки), `reports` и
`analysis_errors`. Код выхода 0 — файл обработан, даже если в нём есть ошибочные записи; 2 —
ошибка конфигурации или недоступный файл. Принятый код сдач не запускается.

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

Файлы в `data/` синтетические. Исходные `submissions.jsonl`, `invalid_submissions.jsonl`,
`assignments.json` и памятка с общим контрактом не были доступны, поэтому схема ниже — допущение
этой реализации.

Сдача — одна строка JSONL:

| Поле | Тип | Правило |
|---|---|---|
| `submission_id`, `assignment_id`, `student_id` | строка | непустая |
| `timestamp` | строка | ISO 8601 с временной зоной |
| `text`, `code` | строка | обязательны, могут быть пустыми |
| `ai_declaration` | объект | `used`: bool, `description`: строка или `null` |

Неизвестные поля запрещены, типы не приводятся (`"yes"` не становится `true`). `assignment_id`
должен существовать в `assignments.json`. Задание: `assignment_id`, `title`, `requirements`
(список строк), `template_code` (разрешённый шаблон кода).

Ошибка записи содержит `code`, `field`, `message`. Коды: `invalid_json` (ошибка формата);
`missing_field`, `unknown_field`, `invalid_type`, `empty_value`, `invalid_string` (строка не
кодируется в UTF-8), `invalid_timestamp`, `timestamp_without_timezone`, `unknown_assignment`
(нарушение схемы); `submission_conflict` (конфликт идентификатора).

## Устройство

```
src/lab_checker/
  models.py        доменные объекты (frozen dataclass), хеш сдачи
  errors.py        доменные исключения и ValidationIssue
  schemas.py       входные модели Pydantic и преобразование в доменные объекты
  repositories.py  интерфейсы хранения и in-memory реализации
  sources.py       источники JSONL и in-memory (контекстные менеджеры)
  intake.py        сервис приёма
  analysis.py      контракт Analyzer, реестр фабрик, сервис анализа
  analyzers.py     LengthAnalyzer, TemplateAnalyzer
  bootstrap.py     сборка зависимостей из конфигурации
  adapter.py       тестовый адаптер на месте будущего HTTP
  cli.py           командная строка
```

- **Валидация** выполняется на границе, в `schemas.py`: входная модель Pydantic в строгом режиме
  преобразуется в неизменяемый доменный объект. Аннотации типов не проверяются во время
  выполнения, поэтому сами по себе вход не защищают.
- **Идемпотентность.** `submission_hash` — SHA-256 канонического содержимого без
  `submission_id`; время приводится к UTC. Повтор с тем же хешем возвращает уже принятую сдачу,
  другое содержимое под тем же id даёт `submission_conflict`, исходная запись не меняется.
- **Исключения.** Пользователь видит `MalformedPayloadError`, `SchemaViolationError`,
  `SubmissionConflictError` со списком `issues`. HTTP-коды (400, 422, 409, 201, 200) назначает
  только `adapter.py`.
- **Ресурс** файла открывает и закрывает вызывающий код через `with JsonlSubmissionSource(...)`;
  сервис приёма получает только итератор записей.
- **Анализаторы** реализуют протокол `Analyzer` и выбираются `AnalysisService` по реестру
  фабрик. Неизвестный идентификатор анализатора — ошибка до запуска любого из них. Исключение при
  создании или работе анализатора и отчёт, нарушающий контракт (неверные типы, evidence вне строк,
  similarity вне [0, 1]), превращаются в `AnalysisFailure` и не мешают остальным.

### Подключение нового анализатора

1. Написать класс с атрибутами `analyzer_id`, `analyzer_version` и методом
   `analyze(submission, context) -> AnalysisReport`.
2. Зарегистрировать фабрику в `build_registry()` в `bootstrap.py`.
3. Добавить анализатор в контрактный тест `tests/test_analyzers.py`.

`AnalysisService` при этом не меняется.

## Ограничения

- Хранилище только в памяти: каждый запуск CLI начинает с пустого репозитория.
- `TemplateAnalyzer` сравнивает строки точно, включая отступы и пробелы в конце строки.
- Схема данных — допущение (см. «Формат данных»).
