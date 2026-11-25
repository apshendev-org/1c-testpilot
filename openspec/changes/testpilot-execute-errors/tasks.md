## 1. Аргументы шагов (`app/_mcp.py`, `app/_runtime.py`)

- [x] 1.1 Таблица синонимов и нормализация аргументов шага, `renamed` в ответе шага, `keys` строкой → список (design, решение 1). Проверка: тесты 5.2, 5.3
- [x] 1.2 `did_you_mean` и `suggested_actions` в `_action_argument_error`: таблица синонимов, таблица подсказок, difflib (решение 2). Проверка: тест 5.4
- [x] 1.3 `check()` проверяет все шаги до запуска: синонимы, имена, обязательные, типы литералов, `$N` вперёд; `run()` проверяет типы после подстановки (решение 3). Проверка: тест 5.1

## 2. Подключение

- [x] 2.1 `not_connected` вместо `RuntimeError` при пустом пуле; `suggested_call`/`running` по живым записям реестра (решение 4). Проверка: тест 5.5
- [x] 2.2 `connect(profile)` с профилем запуска: один живой подходящий клиент → подключение с `reused: true`; ни одного → `profile_action_mismatch` с `suggested_call`; несколько → `client_ambiguous` (решение 5). Проверка: тест 5.6

## 3. Применимость

- [x] 3.1 `app/_applicability.py` из столбца «Применим к типам» `docs/TOOLS.md` с уточнениями вида поля для `doc`/`calendar`; строка `Applies to` в `search` (решение 6). Проверка: тест 5.7
- [x] 3.2 Отказ `unsupported_element_type`/`unsupported_receiver` по `ref` получает `element_class`, `applies_to`, `suggested_actions` (решение 6). Проверка: тест 5.8
- [x] 3.3 `get_context` с `ref` элемента читает его форму и возвращает `form_ref` (решение 7). Проверка: тест 5.9

## 4. Описание, документация, спайк

- [x] 4.1 Описание `execute` (решение 8); `docs/TOOLS.md` — синонимы, проверка пачки, `not_connected`, `connect(profile)`; `README.md` — подключение; `pyproject.toml` — 2.1.0. Проверка: `uv run --no-project --with ".[test]" pytest tests -q`
- [ ] 4.2 Спайк `docs/spikes/testpilot-execute-errors/` кита (`bb spike record`): живой прогон на WS в дереве 1c_bgu20 (серверная ИБ) с testpilot из ветки, сырой обмен MCP в `recording/`, копии в `tests/recordings`. Записи: `area`/`address`/`ref`→`root_ref`/`keys` строкой; пачка с ошибкой в шаге 2 (ничего не исполнено); действие без `connect` (`not_connected`); `connect(profile)` к запущенному `client start` клиенту; `choose_from_drop_list`/`choose_row` не для элемента; `get_context` с `ref` поля. Проверка: файлы есть, `spike:<id>@v1` вписан в proposal.md
- [ ] 4.3 Issue кита на после релиза: скилл `testpilot-testing` — `connect(profile)` больше не отказывает, `not_connected` с `suggested_call`, синонимы (`kit-skills/` в этом изменении не правится). Проверка: номер issue в PR

## 5. Тесты (поток тестов, на записях 4.2)

Матрица для потока тестов: требования `specs/mcp-tools/spec.md` и `specs/client-profiles/spec.md` изменения. Разбор аргументов (синонимы, `keys`, подсказки, проверка пачки) — fuzzing по правилу кита: `random.Random(seed)`, 200 входов с шумом (управляющие последовательности, CRLF, обрыв, Юникод), зерно в тексте падения; без исключений и без значений, которых нет во входе.

- [ ] 5.1 Пачка с ошибкой аргументов в шаге 2 (нет обязательного, лишний, неверный тип литерала, `$N` вперёд) — отказ со `step`, ни один шаг не исполнен, в 1С ничего не отправлено; `$0.x` в обязательном аргументе — проверка проходит, тип проверяется после подстановки
- [ ] 5.2 Синонимы по таблице design (решение 1): каждый синоним каждого действия даёт канонический параметр и `renamed`; `address` у `read_document`/`find_text` по `:`; синоним вместе с каноническим — `invalid_arguments` с `did_you_mean`
- [ ] 5.3 `send_keys` с `keys` строкой отправляет то же сочетание, что списком (по записи)
- [ ] 5.4 `did_you_mean` (`goto_row` + `values`, синоним при каноническом) и `suggested_actions` (`activate_window` + `ref` → есть `activate`); fuzzing имён аргументов: подсказка — только существующий параметр действия
- [ ] 5.5 `not_connected`: один живой клиент — `suggested_call` connect(profile), и этот вызов проходит через `execute` без правки; два — `running` без `suggested_call`; ни одного — `list_profiles`; testpilot не подключается сам
- [ ] 5.6 `connect(profile)`: живой клиент профиля (по записи) — `reused: true`, `profile`; клиент профиля той же базы и пользователя — подключение к нему; ни одного — `profile_action_mismatch` с `suggested_call` `launch_client`, процесс не запущен; два — `client_ambiguous`; с `port` — только этот порт
- [ ] 5.7 `search(query="choose_row")` — `Applies to: Table`; таблица применимости совпадает со столбцом «Применим к типам» `docs/TOOLS.md` для каждого действия; описания `search`/`execute` вместе ≤ 8000 символов
- [ ] 5.8 Отказ `unsupported_receiver`/`unsupported_element_type` по записи — `element_class`, `applies_to`, `suggested_actions` (до 5, без вызванного, все применимы к классу)
- [ ] 5.9 `get_context(ref=<поле>)` по записи — контекст формы поля и `form_ref`; элемент вне формы — `unsupported_receiver` с `suggested_actions`

## 6. Проверки и выпуск

- [ ] 6.1 `(cd testpilot && uv run --no-project --with ".[test]" pytest tests -q)`, `uv run python -m unittest discover -s payload/tests`, `uv run python -m unittest discover -s testmanager/tests`, `openspec validate --all --strict` в корне кита и в `testpilot/`, `uv run python ci/test_authorship.py origin/master` — код 0
- [ ] 6.2 Живая проверка ветки на WS (сценарии 4.2 на итоговом коде); после прогона — `remote_ws.py down`, временное дерево 1c_bgu20 и его ветка удалены, процессов 1С и окон на WS нет
- [ ] 6.3 `/opsx:archive` в ветке; PR `Closes #187` с напоминанием о `git subtree push --prefix testpilot … fork` после слияния
