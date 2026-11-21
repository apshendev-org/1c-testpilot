# Proposal

## Why

Кит 1c-agent-kit переходит с Vanessa на этот форк (UI e2e на pytest) и YAxUnit. Спайк `spike:spk_a831396b29@v3` (1С 8.3.27.2342, WS) показал, что сценарий через формы проходит, но агенту, который пишет тесты без человека, мешают:

- запрет `Выполнить` в коде: `Запрос.Выполнить()` недоступен;
- действия, которые отвечают `ok`, хотя эффекта нет;
- плавающий отказ `select_value`;
- нет сброса клиента и уборки тестовых данных.

## What Changes

- **BREAKING** Фильтр идентификаторов кода удалён целиком, включая «запрещённые всегда» `Выполнить`/`Execute`/`Вычислить`/`Eval`. Переменные `TC1C_CODE_FORBIDDEN_WORDS` и `TC1C_CODE_ALLOWED_WORDS` больше не действуют. Код ограничивают только права пользователя 1С и включение `TC1C_CODE_EXECUTION`.
- `click` возвращает наблюдаемый эффект: состояние до и после и `changed`. Новый необязательный параметр `expect` превращает неисполненное ожидание в ошибку.
- `input_text` сравнивает итоговое значение поля с введённым текстом и возвращает `verified`. Расхождение (например, подставилась группа) — `ok: false`.
- `select_value` повторяет выбор при отказе клиента «does not support this action on this object», пока список не сформирован, в пределах `timeout`.
- Новый сброс клиента к начальной странице (`Client.reset()`); фикстура `testpilot` вызывает его перед каждым тестом.
- `answer_dialog` без открытого диалога отвечает сразу. Ждать появления диалога можно только явно, параметром `wait`.
- Новая фикстура `testpilot_data`: учёт созданных тестом объектов и их удаление после теста.
- `Testpilot.epf` входит в пакет и используется по умолчанию.
- Версия 1.9.2.post3.

## Capabilities

### New Capabilities

- `code-execution`: исполнение кода и запросов через обработку Testpilot без фильтра идентификаторов.
- `action-effects`: проверка эффекта `click` и `input_text`.
- `value-selection`: устойчивость `select_value` к неготовому списку выбора.
- `dialog-answering`: поведение `answer_dialog` при отсутствии диалога.
- `pytest-isolation`: сброс клиента перед тестом и уборка созданных тестом данных.
- `helper-distribution`: поставка `Testpilot.epf` вместе с пакетом.

### Modified Capabilities

Нет: в `openspec/specs/` пока нет спецификаций.

## Impact

- Код: `app/_code_execution.py`, `app/_runtime.py` (click, input_text, answer_dialog), `app/_value_selection.py`, `app/testpilot.py` (`Client.reset`), `app/testpilot_pytest.py` (фикстуры), `pyproject.toml` (версия, package data).
- `onec/Testpilot/src` не меняется: в обработке фильтра нет, пересборка epf не нужна.
- Тесты: `tests/test_code_filter.py` переписывается, добавляются unit-тесты на фейковом клиенте.
- Документация: `README.md`, `onec/Testpilot/README.md`, `docs/PYTHON_TESTING.md`, `docs/TOOLS.md`.
- Совместимость: потребители, которые полагались на фильтр как на защиту, его теряют. Защиту даёт только `TC1C_CODE_EXECUTION=false` и права пользователя 1С.
