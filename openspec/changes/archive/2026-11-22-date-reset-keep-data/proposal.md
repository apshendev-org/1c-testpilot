## Why

Поток проекта 1c_bgu20 при переводе feature Vanessa в pytest (кит v2.21.0) упёрся в три места testpilot:

- Дата в поле периода отчёта (`КомпоновщикНастроекПользовательскиеНастройкиЭлемент…`) даёт `value_mismatch` между «01.01.2026» и «01.01.2026 0:00:00»: поле не реквизит формы, `form_state` его тип не находит, сравнение идёт строкой.
- Открытый список подбора поля не даёт `reset()` закрыть форму (`window_not_closed`), следующий прогон падает на подготовке.
- `testpilot_data` всегда удаляет данные теста. Многошаговый тест на общих данных после каждой правки заново гонит все шаги: 4–10 минут на прогон.

## What Changes

- Тип поля не прочитан, текст и представление различаются: если оба разбираются как одна дата в формате сеанса (`date_sample`), ввод принят, `verification: date_text`.
- `reset()` перед закрытием окна закрывает открытый список подбора текущего поля каждой формы окна и отменяет его редактирование.
- Опция pytest `--tc-keep-data`: `testpilot_data` не удаляет данные после теста. По умолчанию — удаляет, как раньше.

## Capabilities

### New Capabilities

### Modified Capabilities
- `action-effects`: дата при неизвестном типе поля.
- `pytest-isolation`: `reset()` закрывает список подбора; `--tc-keep-data`.

## Impact

- `app/_typed_input.py`, `app/_runtime.py`, `app/testpilot.py`, `app/testpilot_pytest.py`, `docs/PYTHON_TESTING.md`; тесты `tests/test_typed_input.py`, `tests/test_pytest_plugin.py`.
- Кит: `dev_ib.py pytest --keep-data` передаёт `--tc-keep-data`; скилл `testpilot-testing` 1.3.
