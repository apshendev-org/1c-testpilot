## 1. Подготовка

- [x] 1.1 Начать после слияния `bb/bug/testpilot-helper-focus` в `master`: ветку перебазировать на `origin/master`, `openspec validate --all --strict` в `testpilot/` — код 0
- [x] 1.2 Найти, где ответ действия получает `ref` (`_refs`, `format_result`), и записать в design.md решение 4: какой слой отключается на время пачки. Проверка: строка в design.md

## 2. Публикация search/execute (`app/_mcp.py`)

- [x] 2.1 Проверка имён (`_action_argument_error`) и типов (`TypeAdapter`) до выбора соединения (решение 3). Проверка: `invalid_arguments` с сигнатурой для лишнего и пропущенного аргумента, команда не отправлена (тест 4.3)
- [x] 2.2 `execute`: исполнение по `_ACTION_GROUP` через `_dispatch_action`, пачка до первого отказа, `ok`/`stopped_at`/`steps`, предел 1..20 (решения 2, 4). Проверка: тесты 4.2, 4.4, 4.5
- [x] 2.3 Ссылки `$N.путь` и `$$` (решение 5). Проверка: тест 4.6
- [x] 2.4 Скриншоты в ответе пачки (решение 6). Проверка: тест 4.7
- [x] 2.5 `search` (решение 7). Проверка: тест 4.8
- [x] 2.6 Схема `execute`, видимость пользовательских функций, `tools/list_changed`, ограничитель служебных вызовов (решения 8, 9); прежняя регистрация групп удалена. Проверка: тесты 4.1, 4.9, 4.10

## 3. Подсказки и документация

- [x] 3.1 Переписать `tc_<группа>(action="x")` на имя действия в `app/_runtime.py`, `app/tc1c.py`, `app/_mcp.py` (решение 10). Проверка: тест 4.11
- [x] 3.2 `docs/TOOLS.md`: в начале — `search`/`execute`, `$N`, остановка на отказе; разделы групп остаются каталогом действий, примеры — через `execute`. `README.md`, `onec/Testpilot/README.md`, `onec/Testpilot/CUSTOM_FUNCTIONS.md` — то же. Проверка: `grep -rnE "tc_[a-z_]+\(" docs README.md onec/Testpilot/*.md` пусто
- [x] 3.3 Версия пакета в `pyproject.toml` — MAJOR (BREAKING). Проверка: `uv run --no-project --with ".[test]" pytest tests -q` проходит

## 4. Тесты (поток тестов, на записях `tests/recordings`)

Матрица для потока тестов: требования `specs/mcp-tools/spec.md` и сценарий `specs/client-profiles/spec.md`.

- [x] 4.1 Список инструментов — только `search`, `execute`; описания и схемы вместе ≤ 8000 символов при включённых коде, запросах, скриншотах — `test_search_execute.py::test_two_tools_fit_8000_characters_with_code_queries_and_screenshots`
- [x] 4.2 Один вызов `get_active_window` через `execute` даёт тот же ответ, что прежний вызов действия (по записи) — `::test_single_call_answers_as_the_former_group_call`
- [x] 4.3 Лишний аргумент, нет обязательного, неизвестное действие — отказ до отправки, в ответе сигнатура или ближайшие имена — `::test_wrong_arguments_are_refused_before_anything_is_sent`
- [x] 4.4 Пачка 21 — отказ, ни один шаг не исполнен — `::test_batch_outside_1_to_20_is_refused_with_nothing_executed` (0 и 21)
- [x] 4.5 Отказ во втором из трёх шагов — третий не исполнен, `ok: false`, `stopped_at: 1` — `::test_batch_stops_at_the_first_refusal`
- [x] 4.6 `$0.object.ref` из `find_object` подставлен в `click`; отсутствующий путь — `unresolved_reference`, клик не отправлен; `$$x` передан как `$x` — `::test_reference_to_an_earlier_step_takes_the_found_button_and_dd_keeps_one_dollar`, `::test_unresolved_reference_stops_the_step_without_sending`
- [x] 4.7 Пачка `[click, get_screenshot]` — текст двух шагов и одно изображение, отмеченное шагом 1 — `::test_screenshot_step_is_one_image_marked_with_its_step`
- [x] 4.8 `search`: пустой запрос — группы и имена; `click` — сигнатура и документация; слова — найдено `set_area_text`; выключенные скриншоты — нет `get_screenshot` ни в `search`, ни в схеме `execute` — `::test_search_without_query_lists_groups_and_names_without_documentation`, `::test_search_by_action_name_gives_signature_and_documentation`, `::test_search_by_words_finds_actions_by_their_documentation`, `::test_disabled_screenshots_leave_the_catalog_and_the_execute_schema`
- [x] 4.9 Пользовательские функции: появились у подключённой обработки — `tools/list_changed` и имя в схеме `execute`; скрытая — отказ прежним сообщением — `::test_custom_functions_appear_with_list_changed_and_hidden_ones_are_refused`
- [x] 4.10 Пачка только из `list_connections` отвечает, пока рабочий вызов ждёт 1С — `::test_list_connections_answers_while_a_worker_waits_for_1c`
- [x] 4.11 В документации действий, описаниях `search`/`execute` и текстах подсказок нет `tc_[a-z_]+\(` — `::test_action_documentation_and_tool_descriptions_name_actions_not_group_calls` (и каждый ответ модуля — `plain_text`)
- [x] 4.12 Сценарий `client-profiles`: `connect` через `execute` без `version` повторяет рукопожатие с версией из отказа — `::test_connect_through_execute_without_version_takes_the_running_version`
- [x] 4.13 `suggested_call` у `get_cell_text` с `text: null` — `{action, args}`, повтор его через `execute` проходит без правки — `::test_suggested_call_is_an_execute_step` (таблица «Список» записи 05-read-rows-focus; кадр чтения ячейки — заглушка)

## 5. Кит (вне `testpilot/`)

- [x] 5.1 `payload/.claude/agent-kit/AGENTS.template.md` §3, §13: вызовы testpilot через `search`/`execute`. Проверка: `grep -nE "tc_[a-z]+" payload/.claude/agent-kit/AGENTS.template.md` пусто; тесты `payload/tests` проходят
- [ ] 5.2 Отдельный PR после релиза кита: скиллы `testpilot-testing` (правило «одно действие — один шаг» → «пачка до первого отказа»; ловушки), `report-verification`, `1c-run-diagnostics` — вызовы через `execute`, `metadata.version` MAJOR. Проверка: `uv run python -m unittest discover -s payload/tests -p test_kit_skills.py`

## Workflow follow-up

- Проверки выпуска: живой тред проекта с UI-задачей вроде thr_tipdp79usa до и после — `tools[]`, число шагов, вход; изображения в ответе пачки в Claude Code и pi.
- `/opsx:archive` в ветке изменения до слияния в `master`.
