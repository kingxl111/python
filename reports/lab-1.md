# Отчёт по ЛР 1. Приём работ и расширяемые анализаторы

Траектория: **Backend**. Уровень: **основной**, без углубления.

## Выполненные требования

### Этап А. Приём и валидация

| Требование | Где |
|---|---|
| Пакет в src-layout, устанавливается в чистое окружение | `pyproject.toml`, `src/lab_checker` |
| Модели через Pydantic, преобразование входной модели в доменный объект | `schemas.py`: `SubmissionIn.to_domain()` |
| Валидация обязательных полей, временной зоны, AI-декларации; неизвестные поля запрещены | `schemas.py` |
| Ошибка с `code`, `field`, `message`; формат, схема и конфликт различаются | `errors.py` |
| Повтор с тем же хешем возвращает принятую сдачу, другое содержимое — conflict | `intake.py` |
| In-memory репозиторий | `repositories.py` |
| Тестовый адаптер вместо HTTP; HTTP-коды не определяют доменные исключения | `adapter.py` |
| Повреждённая строка не останавливает импорт, ошибка с номером строки | `IntakeService.import_records` |

### Этап Б. Контракты и расширения

| Требование | Где |
|---|---|
| Синхронный контракт `Analyzer.analyze(submission, context) -> AnalysisReport` | `analysis.py` |
| `AnalysisContext`: задание и доступ к сдачам через интерфейс `SubmissionReader` | `analysis.py` |
| `LengthAnalyzer`: непустые строки, пояснение в `rubric_feedback`, `score=null` | `analyzers.py` |
| `TemplateAnalyzer`: точные строки шаблона, `similarity`, пояснение о разрешённом совпадении | `analyzers.py` |
| Evidence в номерах исходных строк, проверка диапазонов | `find_report_problems` |
| Источники JSONL и in-memory вне сервиса приёма | `sources.py` |
| Выбор анализатора по реестру фабрик без ветвления по классам | `AnalyzerRegistry`, `AnalysisService` |
| Зависимости собирает конфигурация; ошибка конфигурации — до обработки | `bootstrap.py` |

## Обязательные проверки

| Сценарий | Тест |
|---|---|
| Валидный импорт | `test_intake.py::test_valid_submission_is_accepted`, `test_cli.py` |
| Повреждённый JSON | `test_schemas.py::test_malformed_json_is_format_error`, `test_intake.py::test_import_continues_after_bad_lines` |
| Неверные типы | `test_schemas.py::test_wrong_types_are_rejected_without_coercion` |
| Неверный timestamp, пустой `student_id`, неизвестное поле | `test_schemas.py` |
| Дубликат не увеличивает число сдач | `test_intake.py::test_duplicate_returns_stored_submission_and_does_not_grow` |
| Конфликт не перезаписывает запись | `test_intake.py::test_conflict_does_not_overwrite_original` |
| Ошибка анализатора | `test_analysis_service.py::test_analyzer_error_does_not_affect_others` |
| Освобождение ресурса при ошибке и досрочной остановке | `test_sources.py::test_source_is_closed_after_*` |
| Диапазоны evidence | `test_analyzers.py::test_evidence_range_validation`, `test_template_evidence_refers_to_original_lines` |
| Неизменность исходного объекта | `test_schemas.py::test_payload_is_not_mutated`, `test_analyzers.py::test_analyzer_contract` |
| Подключение нового анализатора без изменения сервиса | `test_analysis_service.py::test_new_analyzer_is_plugged_in_through_registry_only` |

Контрактные тесты: `test_sources.py` прогоняет одни и те же проверки на обоих источниках,
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
arm64. Синтетические сдачи одного задания, 1–40 строк кода, около 5 % повреждённых строк;
источник in-memory, анализаторы `length` и `template`.

| Записей | Импорт, с | Анализ, с | Записей/с (импорт) |
|---|---|---|---|
| 1 042 | 0.014 | 0.034 | ≈ 72 000 |
| 10 476 | 0.096 | 0.220 | ≈ 110 000 |

При росте числа записей в 10 раз время растёт примерно в 6,5–7 раз, то есть не быстрее
линейного: каждая запись проверяется и анализируется независимо, без сравнения с другими
сдачами. Причина отклонения от ровно линейного роста не исследовалась, профилирование не
проводилось. Числа относятся только к этому синтетическому набору и этой машине.

## Известные ограничения

- Схема данных — допущение: исходные файлы и памятка с контрактом не были предоставлены.
- Хранилище только в памяти; между запусками CLI данные не сохраняются.
- `TemplateAnalyzer` требует точного совпадения строки, включая отступы и пробелы в конце.
- Совпадение с шаблоном — сведения для преподавателя, а не вывод о нарушении.
