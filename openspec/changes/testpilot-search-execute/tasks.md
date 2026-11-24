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

- [ ] 4.1 Список инструментов — только `search`, `execute`; описания и схемы вместе ≤ 8000 символов при включённых коде, запросах, скриншотах
- [ ] 4.2 Один вызов `get_active_window` через `execute` даёт тот же ответ, что прежний вызов действия (по записи)
- [ ] 4.3 Лишний аргумент, нет обязательного, неизвестное действие — отказ до отправки, в ответе сигнатура или ближайшие имена
- [ ] 4.4 Пачка 21 — отказ, ни один шаг не исполнен
- [ ] 4.5 Отказ во втором из трёх шагов — третий не исполнен, `ok: false`, `stopped_at: 1`
- [ ] 4.6 `$0.object.ref` из `find_object` подставлен в `click`; отсутствующий путь — `unresolved_reference`, клик не отправлен; `$$x` передан как `$x`
- [ ] 4.7 Пачка `[click, get_screenshot]` — текст двух шагов и одно изображение, отмеченное шагом 1
- [ ] 4.8 `search`: пустой запрос — группы и имена; `click` — сигнатура и документация; слова — найдено `set_area_text`; выключенные скриншоты — нет `get_screenshot` ни в `search`, ни в схеме `execute`
- [ ] 4.9 Пользовательские функции: появились у подключённой обработки — `tools/list_changed` и имя в схеме `execute`; скрытая — отказ прежним сообщением
- [ ] 4.10 Пачка только из `list_connections` отвечает, пока рабочий вызов ждёт 1С
- [ ] 4.11 В документации действий, описаниях `search`/`execute` и текстах подсказок нет `tc_[a-z_]+\(`
- [ ] 4.12 Сценарий `client-profiles`: `connect` через `execute` без `version` повторяет рукопожатие с версией из отказа
- [ ] 4.13 `suggested_call` у `get_cell_text` с `text: null` — `{action, args}`, повтор его через `execute` проходит без правки

## 5. Кит (вне `testpilot/`)

- [x] 5.1 `payload/.claude/agent-kit/AGENTS.template.md` §3, §13: вызовы testpilot через `search`/`execute`. Проверка: `grep -nE "tc_[a-z]+" payload/.claude/agent-kit/AGENTS.template.md` пусто; тесты `payload/tests` проходят
- [ ] 5.2 Отдельный PR после релиза кита: скиллы `testpilot-testing` (правило «одно действие — один шаг» → «пачка до первого отказа»; ловушки), `report-verification`, `1c-run-diagnostics` — вызовы через `execute`, `metadata.version` MAJOR. Проверка: `uv run python -m unittest discover -s payload/tests -p test_kit_skills.py`

## Workflow follow-up

- Проверки выпуска: живой тред проекта с UI-задачей вроде thr_tipdp79usa до и после — `tools[]`, число шагов, вход; изображения в ответе пачки в Claude Code и pi.
- `/opsx:archive` в ветке изменения до слияния в `master`.
