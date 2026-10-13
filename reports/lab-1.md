# Отчёт по ЛР 1. Приём работ и расширяемые анализаторы

Траектория: **Backend**. Уровень: **основной**, без углубления. Контракт данных и поведения взят
из ноутбука лекции.

## Выполненные требования

### Этап А. Приём и валидация

| Требование | Где |
|---|---|
| Пакет в src-layout, устанавливается в чистое окружение | `pyproject.toml`, `src/lab_checker` |
| DTO Pydantic в строгом режиме, преобразование в доменный объект | `parsing.py`: `SubmissionInput.to_domain()` |
| Версия схемы, временная зона, AI-декларация, запрет неизвестных полей | `parsing.py` |
| Ошибка `code`, `field`, `message`; коды `invalid_json`, `schema_error`, `unsupported_version`, `conflict` | `errors.py` |
| Стабильный хеш, `duplicate` при том же хеше, `conflict` при другом | `hashing.py`, `services.py` |
| In-memory репозиторий за протоколом | `repositories.py` |
| Тестовый адаптер вместо HTTP; HTTP-коды назначаются только в нём | `adapter.py` |
| Ошибка строки не останавливает импорт, у ошибки есть `line_no` | `services.import_source` |

### Этап Б. Контракты и расширения

| Требование | Где |
|---|---|
| `Analyzer.analyze(submission, context) -> AnalysisReport`, `AnalysisContext` с `config_payload()` | `analysis.py` |
| Проверка отчёта: версия сдачи, конфигурация, kind, score, evidence | `analysis.validate_report` |
| `LengthAnalyzer`: `rubric_feedback`, `score=None`, evidence по непустым строкам | `analyzers.py` |
| `TemplateAnalyzer`: `similarity`, точные блоки разрешённого шаблона | `analyzers.py` |
| Источники JSONL и in-memory с `open()` как контекстным менеджером | `sources.py` |
| Выбор анализатора по реестру фабрик | `AnalyzerRegistry`, `AnalysisService` |
| Сборка зависимостей; неизвестный анализатор — ошибка до первого вызова | `bootstrap.py` |
| CLI: JSON в stdout, диагностика в stderr, коды выхода 0/1/2 | `cli.py` |

## Обязательные проверки

| Сценарий | Тест |
|---|---|
| Валидный импорт и повторный импорт | `test_services.py::test_repeated_import_gives_duplicates`, `test_cli.py` |
| Повреждённый JSON, повтор ключа, NaN, пустая строка | `test_parsing.py::test_decode_json_rejects`, `test_sources.py` |
| Неверные типы, версия, timestamp, пустой `student_id`, неизвестное поле | `test_parsing.py::test_invalid_submission` |
| Дубликат не увеличивает число сдач, конфликт не перезаписывает | `test_services.py::test_acceptance_contract` |
| Смешанный JSONL с номерами строк | `test_services.py::test_mixed_jsonl_import` |
| Дефектный и падающий анализатор | `test_analysis_service.py::test_defective_analyzer_is_stopped` |
| Закрытие файла при досрочном выходе и ошибке | `test_sources.py::test_jsonl_is_closed_after_*` |
| Диапазоны evidence и прочие проверки отчёта | `test_analysis_service.py::test_validate_report_rejects` |
| Неизменность исходного объекта | `test_parsing.py`, `test_sources.py::test_records_are_copies` |
| Полный сценарий: 12 сдач, 24 отчёта | `test_analysis_service.py::test_end_to_end` |

Контрактные тесты: `test_sources.py::test_source_contract` выполняется на обоих источниках,
`test_analyzers.py::test_analyzer_contract` — на обоих анализаторах.

## Команды проверки

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy src tests scripts
pytest
lab-checker import data/submissions.jsonl --assignments data/assignments.json
```

Чистое окружение: wheel собран `python -m build --wheel`, установлен в новый venv во временном
каталоге, CLI запущен оттуда.

## Измерения

`python scripts/benchmark_import.py`, seed 42, 3 повтора, медиана. Python 3.14.4, macOS 26.5,
arm64. Синтетические сдачи одного задания, 1–40 строк кода, около 5 % повреждённых записей;
источник in-memory, анализаторы `length` и `template`.

| Записей | Импорт, с | Анализ, с | Записей/с (импорт) |
|---|---|---|---|
| 1 042 | 0.022 | 0.153 | около 47 000 |
| 10 476 | 0.207 | 1.526 | около 51 000 |

Время растёт линейно: каждая запись проверяется и анализируется независимо. Анализ занимает
больше времени, чем импорт: на каждую сдачу строятся два отчёта, у каждого вычисляются хеш
сдачи и хеш конфигурации, отчёт проверяется дважды. Профилирование не проводилось. Числа
относятся только к этому набору и этой машине.

## Известные ограничения

- Хранилище только в памяти; между запусками CLI данные не сохраняются.
- `TemplateAnalyzer` требует точного совпадения блока строк, включая отступы.
- Совпадение с шаблоном — сведения для преподавателя, а не вывод о нарушении.
