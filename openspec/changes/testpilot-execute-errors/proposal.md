## Why

После перехода на `search`/`execute` (v2.25.0 кита) доля отказов UI-действий не упала: 23% до, 25% после. Разбор 42 отказов `execute` в трёх сессиях — spike:spk_7429445fbc@v1 (`docs/spikes/testpilot-execute-analysis/` кита). Больше половины отказов дают сам testpilot и его описания, а не 1С:
- неверные аргументы — 9 (21%). 4 из 9 — разнобой `area`/`address`/`start_address` у действий табличного документа, 1 — `keys` строкой. Отказ не говорит, какое имя нужно;
- действие не для этого элемента — 9 (21%). В описании действия нет, к каким элементам оно применимо. 2 из 9 — `get_context` с `ref` элемента вместо формы;
- старт без `connect` — 3 (7%): `RuntimeError` без кода и подсказки. Затем `connect(profile)` на профиль запуска — `profile_action_mismatch` (2, 5%), хотя клиент этого профиля уже запущен. Каждая сессия тратит на старт 2–3 лишних хода;
- пачка проверяет аргументы шага только перед ним, поэтому падает на середине, а хвост теряется.

Спайк: стенограммы — spike:spk_7429445fbc@v1. Ответы testpilot и 1С на новые отказы и подхват запущенного клиента записаны живьём на WS — spike:spk_21dac6344d@v1 (`docs/spikes/testpilot-execute-errors/recording/` кита, копии в `tests/recordings`), тесты — на этих записях.

## What Changes

- Синонимы аргументов табличного документа: `address` ↔ `area`, `cell`, `range` у действий, где один из них — параметр (таблица в design.md); `ref` → `root_ref` у `find_objects`/`find_object`. Принятый синоним шаг называет в ответе: `renamed: {"area": "address"}`.
- `keys` строкой у `send_keys` становится списком: `"CTRL+S"` → `["CTRL", "S"]`.
- В отказе `invalid_arguments` на лишний аргумент — подсказка `did_you_mean: {"<лишнее>": "<параметр>"}`. Если у действия нет `ref`, а агент его передал, — `suggested_actions`: похожие действия, которые принимают `ref` (`activate_window` → `activate`).
- `execute` проверяет аргументы всех шагов до запуска первого: имена после синонимов, обязательные, типы литералов, ссылки `$N` вперёд. Ошибка в любом шаге — отказ `invalid_arguments` со `step`, ни один шаг не исполнен.
- Действие без подключения отвечает кодом `not_connected` вместо `RuntimeError`. Если жив ровно один клиент из реестра `.testpilot-clients.json`, в ответе `suggested_call` `{"action": "connect", "args": {"profile": …}}`. Иначе — список запущенных клиентов или `list_profiles`.
- `connect(profile)` с профилем запуска подключается к уже запущенному клиенту, только если жив ровно один подходящий: тот же профиль или профиль той же базы и пользователя. Ни одного — прежний `profile_action_mismatch` с `suggested_call` `launch_client(profile)`. Несколько — отказ `client_ambiguous` со списком; testpilot ничего не запускает и не выбирает сам.
- `search` по имени действия показывает строку `Applies to: <классы элементов>` (классы — как `class` в ответах `find_objects`). Источник — столбец «Применим к типам» `docs/TOOLS.md`.
- Отказ `unsupported_element_type`/`unsupported_receiver` по `ref` дополняется полями `element_class`, `applies_to` и `suggested_actions` — действиями, применимыми к классу элемента.
- `get_context` с `ref` элемента формы читает форму, в которой этот элемент лежит. В ответе `form_ref` — ссылка на эту форму.
- Описание `execute` (в пределах 8000 символов на оба инструмента) говорит о проверке пачки до запуска, синонимах и `not_connected` с `suggested_call`. Версия пакета — MINOR.

Не делаем: `on_error: continue` и авто-`connect` при первом действии. Пункты 5–8 анализа (диалоги, эффект, ячейки, окно) — #188.

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `mcp-tools`: синонимы и подсказки в проверке аргументов, проверка пачки до запуска, `not_connected` с `suggested_call`, применимость действий в `search` и в отказе, `get_context` по элементу.
- `client-profiles`: `connect(profile)` с профилем запуска подхватывает единственный живой подходящий клиент.

## Impact

- `app/_mcp.py`: проверка пачки, синонимы, описание `execute`, строка `Applies to` в `search`.
- `app/_runtime.py`: `_action_argument_error` (подсказки), `_need`/`_dispatch_action` (`not_connected`, `connect(profile)`), обогащение отказа о типе элемента.
- `app/_snapshots.py`: форма по элементу. `app/_profiles.py`, `app/_client_registry.py`: поиск живых подходящих клиентов.
- Новый модуль таблицы применимости действий. Тест сверяет его со столбцом `docs/TOOLS.md`.
- `docs/TOOLS.md`, `README.md` (подключение, синонимы); `pyproject.toml` — 2.1.0.
- Кит вне `testpilot/`: спайк с записями в `docs/spikes/testpilot-execute-errors/`. Скилл `testpilot-testing` пишет, что `connect` с профилем `ib` отказывает. Его правят отдельным issue после релиза кита; `kit-skills/` в этом изменении не трогаем.
