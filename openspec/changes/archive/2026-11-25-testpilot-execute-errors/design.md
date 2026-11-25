## Context

- `execute` (`app/_mcp.py`): `check()` до запуска проверяет только форму вызова и имя действия. Имена и типы аргументов проверяет `type_error()` внутри `run()` перед каждым шагом (`_action_argument_error` из `_runtime.py` и `pydantic.TypeAdapter`). Поэтому пачка исполняется до шага с плохими аргументами.
- `_action_argument_error` возвращает `unexpected_parameters`, `missing_parameters` и `signature`, но не подсказывает, какое имя нужно.
- Без подключения `Pool.select` при пустом пуле возвращает `None` (ветка прежнего Python API). Действие идёт в `_need()`, тот бросает `RuntimeError('not connected — call connect first')`, а `run()` превращает его в `code: "error"`. Код `not_connected` (`_connections.ConnectionError`) бывает только при непустом пуле без клиента.
- `_profiles.resolve` отказывает `connect` с профилем запуска (`base` в профиле) — `profile_action_mismatch`. `launch_client(profile)` уже переиспользует клиент по `.testpilot-clients.json` (`_client_registry.live`: процесс `1cv8*` с `-TPort<порт>`, порт слушает). Профили той же базы и пользователя находит `_profiles.find(user, like)`.
- Применимость к типам есть только в `docs/TOOLS.md` (столбец «Применим к типам», типы 1С). В коде — проверки отдельных действий (`_key_class(key) != 'Table'` и т. п.) и `VERIFY_CLASS_BY_TYPE` для шести типов.
- Агент видит класс элемента в `class` ответов `find_objects`/`get_child_objects`: `EditField`, `Table`, `Button`, `Group`, `Decoration`, `Additional`, `ManagedForm`, `MainFrame`, `SecondaryFrame`, `CI`, `CIButton`. Он же — последний сегмент ключа (`_key_class`), поэтому класс `ref` известен без запроса к 1С.

## Goals / Non-Goals

**Goals:** отказы из спайка, которые даёт сам testpilot, исправляются молча (синонимы, `keys`, форма по элементу) или за один ход по подсказке из ответа.

**Non-Goals:** переименовывать параметры действий (это сломало бы Python API, pytest и скиллы); угадывать синонимы вне таблицы; подключаться без явного `connect`; менять ответы 1С.

## Decisions

### 1. Синонимы — таблица, канонические имена прежние

| Действия | Параметр | Принимаемые синонимы |
|---|---|---|
| `set_current_area`, `set_area_text`, `included_in_merged_area` | `address` | `area`, `cell` |
| `get_area_text`, `get_current_area_text`, `text_within_area_bounds` | `area` | `address`, `range` |
| `read_document`, `find_text` | `area` | `range`; `address` со значением с `:` |
| `read_document`, `find_text` | `start_address` | `cell`; `address` без `:` |
| `find_objects`, `find_object` | `root_ref` (в режимах `off`/`prefix` — `root_key`) | `ref` (`key`) |
| `send_keys` | `keys` — список | строка → `[s.strip() for s in keys.split('+')]` |

Синоним применяется, только если у действия нет параметра с этим именем, а канонический не передан. Если переданы оба, синоним — лишний аргумент с `did_you_mean`. Таблица живёт рядом с проверкой аргументов в `_mcp.py`. Пример: `set_current_area(ref, area="R2C3")` → шаг исполнен, в ответе `renamed: {"area": "address"}`. Альтернатива — переименовать всё в одно `address` — отвергнута: ломает Python API и записанные сценарии, а `area` (диапазон) и `start_address` (точка) различаются по смыслу.

### 2. Подсказки отказа

`did_you_mean` берётся сначала из таблицы синонимов, затем из `difflib.get_close_matches` по параметрам действия (порог 0.6), затем из таблицы подсказок без автозамены: `values` → `fields` (`goto_row`), `text` → `title` (`activate_window`, `find_object`, `find_objects`). Имя с непечатаемыми символами (`not str.isprintable()`) подсказки не получает: `did_you_mean` делает имя ключом, а `toon_format` 0.9.0-beta.1 не берёт в кавычки ключ с `\n` в конце (`VALID_KEY_REGEX` с `$`), и ответ перестаёт читаться. Пример текста:

```
ok: false
code: invalid_arguments
step: 1
error: Use only the parameters of the selected action; supply all required parameters. Nothing was executed.
unexpected_parameters[1]: values
missing_parameters[0]:
did_you_mean:
  values: fields
signature: goto_row(ref, column=null, value=null, direction='down', toggle_selection=False, fields=null)
```

Если передан `ref`, а у действия его нет, добавляется `suggested_actions`: действия с `ref`, близкие по имени (difflib, порог 0.5, до 5). Пример: `activate_window(ref)` → `suggested_actions: [activate, …]`.

### 3. Проверка пачки до запуска

`check()` для каждого шага: синонимы → `_action_argument_error` → типы литералов. Значение `"$N.путь"` считается переданным, его тип не проверяется до подстановки; `N ≥ i` — `unresolved_reference` сразу. Первая ошибка возвращается как отказ пачки: `{ok: false, code, step, error: '… Nothing was executed.', …}` — та же форма, что у нынешних `unknown_action` и предела 1..20. `run()` повторяет проверку типов после подстановки ссылок: путь мог дать значение не того типа. Альтернатива — собрать ошибки всех шагов — отвергнута: агент исправляет по одной, а ответ раздувается.

### 4. `not_connected`

`Pool.select` при пустом пуле и пустом прежнем клиенте бросает `ConnectionError('not_connected')`. Прежний Python API без пула не меняется: ветка `legacy` остаётся. Ответ дополняет `_dispatch_action` (там уже ловятся `not_connected` и `connections`):

```
ok: false
code: not_connected
error: No connected test client; nothing was sent. Run suggested_call, then repeat this step.
suggested_call:
  action: connect
  args:
    profile: ib
```

Живые клиенты — записи `.testpilot-clients.json`, у которых `_client_registry.alive`. Один — `suggested_call: connect(profile)`. Несколько — `running: [{profile, port}]` и текст «Several clients are running; connect with one of their profiles.» Ни одного при настроенных профилях — `suggested_call: {action: list_profiles}` и текст «launch_client(profile) starts one.» Без файла профилей — без `suggested_call`, текст «Use connect(port) or launch_client.» Это только подсказка: авто-`connect` нет (issue #187, «не делать»).

### 5. `connect(profile)` с профилем запуска

В `_dispatch_action` до `_profiles.resolve`: если профиль — профиль запуска, а действие `connect`, кандидаты — `_profiles.find(user, profile)` (сам профиль и профили той же базы, сервера и пользователя), у которых `_client_registry.live`; с `port` — только на этом порту.
- Один → `connect` к `127.0.0.1:<порт>` с `version` записи. Состояние подключения получает профиль клиента (пароль и прочее — из профиля), ответ — `reused: true`, `profile: <профиль клиента>`.
- Ни одного → `profile_action_mismatch` с `suggested_call: {action: launch_client, args: {profile}}`.
- Несколько → `client_ambiguous`, `running: [{profile, port}]`. Нужно выбрать порт (`connect(profile, port)`) или профиль.

Почему «той же базы и пользователя», а не только «того же профиля»: в реестре одна запись на профиль, и при одном профиле правило «ровно один» вырождается. Клиент того же пользователя той же базы равноценен для теста, а два таких клиента — неоднозначность, которую выбирает агент.

### 6. Применимость

Новый модуль `app/_applicability.py`: `APPLIES = {действие: (типы 1С…)}`, перенесённый из столбца `docs/TOOLS.md` (тест сверяет). Отображение типов в классы: `ТестируемоеПолеФормы` → `EditField`, `ТестируемаяТаблицаФормы` → `Table`, `ТестируемаяКнопкаФормы` → `Button`, `ТестируемаяГруппаФормы` → `Group`, `ТестируемаяДекорацияФормы` → `Decoration`, `ТестируемоеДополнениеЭлементаФормы` → `Additional`, `ТестируемаяФорма` → `ManagedForm`, `ТестируемоеОкноКлиентскогоПриложения` → `MainFrame`, `SecondaryFrame`, `ТестируемыйКомандныйИнтерфейсОкна` → `CI`, `ТестируемаяКнопкаКомандногоИнтерфейса` → `CIButton`. Уточнения вида поля для групп `doc` и `calendar`: `EditField (SpreadsheetDocumentField)`, `EditField (FormattedDocumentField, HTMLDocumentField)`, `EditField (CalendarField)` — по проверкам, которые уже есть в коде этих действий. `ТестируемоеПриложение` (действия без `ref`) строки `Applies to` не получает.

`search(query="choose_row")`: после сигнатуры строка `Applies to: Table`. Описания `search`/`execute` не растут: строка — в документации действия, а не в схеме инструмента.

Отказ о типе обогащается в `_dispatch_connected_action_impl`, где ключ цели известен:

```
ok: false
code: unsupported_receiver
error: The test client does not support this action on this object.
element_class: EditField
applies_to[1]: EditField
suggested_actions[3]: execute_choice_from_choice_list,select_value,select_option
```

`suggested_actions` — действия, у которых в `APPLIES` есть класс элемента. Сортировка: близость имени к вызванному (difflib), затем та же группа; до 5, без вызванного действия.

### 7. `get_context` по элементу

`_snapshots.form_object`: если класс ключа не `ManagedForm`, поднимается по сегментам ключа (`_collection_parent`) до ближайшего `ManagedForm`. Найден — читается эта форма, в ответе `form_ref` (ссылка регистрируется как у любого найденного объекта). Не найден — прежний `unsupported_receiver` (через решение 6 он получит `suggested_actions`).

### 8. Описание `execute`

Добавляется одна фраза: «Arguments of all calls are checked before the first runs; known synonyms (area/address/start_address, ref→root_ref) are accepted and reported as renamed. Without a connection the answer is not_connected with suggested_call.» Предел 8000 символов на оба инструмента проверяет существующий тест.

## Risks / Trade-offs

- Синоним `address` у `read_document`/`find_text` выбирается по значению (`:`). Ошибиться можно только на строке, которая не адрес; такую 1С всё равно отвергнет. `renamed` показывает агенту, что произошло.
- `did_you_mean` по difflib может предложить не то (`values` → `value`), поэтому таблица подсказок идёт раньше difflib. Это подсказка, а не автозамена.
- Таблица применимости — копия документации, может разойтись с кодом. Тест сверяет её с `docs/TOOLS.md`, а 1С остаётся окончательным судьёй: `Applies to` не запрещает вызов.
- `connect` к клиенту профиля той же базы и пользователя — неочевидное поведение. `profile` в ответе называет, к чьему клиенту подключились.
- Отказы, которые дают 1С и приложение (диалоги, эффект, ячейки, окно, ~40%), не меняются — это #188.
