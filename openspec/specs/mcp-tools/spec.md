# mcp-tools Specification

## Purpose

Какие инструменты публикует сервер MCP testpilot: поиск действий клиента тестирования 1С и их исполнение по одному или пачкой, чтобы схемы инструментов не занимали контекст агента.

## Requirements

### Requirement: Два инструмента
Сервер MCP MUST публиковать ровно два инструмента: `search` и `execute`. Инструменты групп `tc_*` MUST NOT публиковаться. Схема `execute` MUST перечислять имена доступных действий. Описания двух инструментов вместе MUST быть не длиннее 8000 символов.

#### Scenario: Список инструментов
- **WHEN** клиент MCP запрашивает список инструментов
- **THEN** в нём только `search` и `execute`, `tc_field` и другие группы отсутствуют

#### Scenario: Размер схем
- **WHEN** сервер запущен с исполнением кода, запросами и скриншотами
- **THEN** описания и схемы `search` и `execute` вместе занимают не больше 8000 символов

### Requirement: Каталог и документация действий
`search` без запроса MUST вернуть группы действий с одной строкой описания и именами действий. Запрос с именем действия MUST вернуть его сигнатуру и полную документацию. Запрос словами MUST вернуть действия, в имени, группе или документации которых они встречаются: полную документацию не больше 8 действий, остальные — только имена.

#### Scenario: Пустой запрос
- **WHEN** агент вызывает `search` без запроса
- **THEN** ответ перечисляет группы и имена всех доступных действий, без документации действий

#### Scenario: Действие по имени
- **WHEN** агент вызывает `search(query="click")`
- **THEN** ответ — сигнатура `click` с обязательными параметрами и её документация

#### Scenario: Поиск словами
- **WHEN** агент вызывает `search(query="spreadsheet cell")`
- **THEN** ответ содержит `set_area_text` с документацией

### Requirement: Доступность действий
Действие, которое сейчас не публикуется (версия платформы ниже нужной, исполнение кода, запросы, метаданные, скриншоты или журнал выключены), MUST отсутствовать в схеме `execute` и в ответах `search`. Пользовательские функции BSL MUST быть доступны только пока подключённая обработка их регистрирует. Об изменении сервер MUST сообщать уведомлением `tools/list_changed`.

#### Scenario: Скриншоты выключены
- **WHEN** скриншоты на сервере выключены
- **THEN** `get_screenshot` нет в схеме `execute` и в ответе `search`

#### Scenario: Функции появились
- **WHEN** подключается клиент, обработка которого регистрирует функции
- **THEN** сервер шлёт `tools/list_changed`, `execute_custom_bsl_function` появляется в схеме `execute`

### Requirement: Исполнение вызовов
`execute` MUST принимать список вызовов `{action, args, connection_id}` длиной от 1 до 20. Каждое действие MUST исполняться так же, как прежний вызов его группы: те же аргументы, проверки, ожидания и ответ. Аргументы всех шагов MUST проверяться по сигнатурам действий до исполнения первого шага: неизвестный или лишний аргумент, нет обязательного, неверный тип — отказ `invalid_arguments` с номером шага `step` и сигнатурой, ни один шаг не исполнен.

#### Scenario: Один вызов
- **WHEN** `execute(calls=[{"action": "get_active_window", "args": {}}])`
- **THEN** ответ шага совпадает с прежним `tc_app(action="get_active_window")`

#### Scenario: Лишний аргумент
- **WHEN** шаг `{"action": "click", "args": {"ref": "<ref>", "text": "X"}}`
- **THEN** шаг отклонён `invalid_arguments` с сигнатурой `click`, команда в 1С не отправлена

#### Scenario: Неизвестное действие
- **WHEN** шаг `{"action": "list_windows"}`
- **THEN** отказ `unknown_action` до исполнения пачки, в ответе — ближайшие по имени действия

#### Scenario: Пачка длиннее 20
- **WHEN** `execute` получает 21 вызов
- **THEN** отказ `invalid_arguments`, ни один шаг не исполнен

#### Scenario: Ошибка в третьем шаге
- **WHEN** пачка `[find_object, click, set_current_area(ref, cell_address)]`, у третьего шага нет `ref`
- **THEN** отказ `invalid_arguments` со `step: 2` и `missing_parameters: ["ref"]`, `find_object` и `click` не исполнены, в 1С ничего не отправлено

#### Scenario: Ссылка на шаг впереди
- **WHEN** шаг 0 пачки передаёт `"$1.object.ref"`
- **THEN** отказ `unresolved_reference` со `step: 0` до исполнения пачки

#### Scenario: Значение из прошлого шага
- **WHEN** обязательный аргумент шага 1 — `"$0.object.ref"`
- **THEN** проверка до запуска считает аргумент переданным, его тип проверяется после подстановки

### Requirement: Пачка до первого отказа
Шаги пачки MUST исполняться по порядку. Шаг с `ok: false` или исключением MUST остановить пачку: следующие шаги не исполняются. Ответ MUST содержать ответ каждого исполненного шага по порядку, `ok` всей пачки (истина, только если исполнены все шаги) и номер остановившего шага.

#### Scenario: Отказ в середине
- **WHEN** пачка из трёх шагов, второй отвечает `effect_not_observed`
- **THEN** третий шаг не исполнен, ответ: `ok: false`, `stopped_at: 1`, ответы шагов 0 и 1

#### Scenario: Все шаги прошли
- **WHEN** все шаги пачки ответили `ok: true`
- **THEN** ответ `ok: true` и ответы всех шагов

### Requirement: Ссылки на ответы прошлых шагов
Строковое значение аргумента вида `$N.путь` (`$0.object.ref`, `$1.objects.0.ref`) MUST заменяться значением из ответа шага `N` той же пачки до проверки аргументов. `N` не меньше текущего шага или путь, которого нет в ответе, — отказ `unresolved_reference` на этом шаге, команда в 1С не отправляется. Значение, которое начинается с `$$`, MUST передаваться с одним `$` без подстановки.

#### Scenario: Найти и нажать
- **WHEN** пачка `[{"action": "find_object", "args": {"title": "Записать"}}, {"action": "click", "args": {"ref": "$0.object.ref"}}]`
- **THEN** `click` получает ссылку найденной кнопки

#### Scenario: Пути нет
- **WHEN** второй шаг ссылается на `$0.objects.5.ref`, а `find_objects` нашёл один элемент
- **THEN** второй шаг — `unresolved_reference`, клик не отправлен

### Requirement: Скриншоты в ответе пачки
Если шаг пачки вернул скриншот, ответ `execute` MUST содержать изображение этого шага, а текст ответа MUST отмечать, к какому шагу оно относится.

#### Scenario: Действие и снимок
- **WHEN** пачка `[click, get_screenshot]` прошла
- **THEN** в ответе текст двух шагов и одно изображение PNG, отмеченное шагом 1

### Requirement: Служебные действия без очереди
Пачка только из `list_connections` и `disconnect(force=true)` MUST исполняться без ожидания рабочих вызовов, занятых 1С. Пачка, где они смешаны с другими действиями, MUST исполняться как обычная.

#### Scenario: Список подключений при занятом клиенте
- **WHEN** рабочие вызовы ждут ответа 1С, агент вызывает `execute` с одним `list_connections`
- **THEN** ответ приходит без ожидания рабочих вызовов

### Requirement: Подсказки называют действия
Тексты ответов, ошибок и документации testpilot MUST называть другие действия по имени (`get_current_error`), а не вызовом группы (`tc_app(action="get_current_error")`). `suggested_call` в ответе MUST быть шагом `execute`: `{action, args, connection_id}`.

#### Scenario: Подсказка после отказа
- **WHEN** ответ действия советует прочитать текущую ошибку
- **THEN** в тексте `get_current_error`, строки `tc_app(` нет

#### Scenario: Предложенный вызов
- **WHEN** `get_cell_text` вернул `text: null` и `suggested_call`
- **THEN** `suggested_call` — `{"action": "is_visible", "args": {"ref": …}}`, его можно передать в `execute` без правки

### Requirement: Синонимы аргументов
Шаг MUST принимать синоним вместо параметра действия по таблице синонимов: `address`, `area`, `cell`, `range`, `start_address` у действий табличного документа, `ref` вместо `root_ref` у `find_objects` и `find_object`. Синоним MUST применяться, только если у действия нет параметра с этим именем, а сам параметр не передан. Ответ шага MUST содержать `renamed: {синоним: параметр}`. Строка `keys` у `send_keys` MUST становиться списком частей между `+`.

#### Scenario: area вместо address
- **WHEN** шаг `{"action": "set_current_area", "args": {"ref": "<поле>", "area": "R2C3"}}`
- **THEN** область R2C3 установлена, ответ шага содержит `renamed: {"area": "address"}`

#### Scenario: address у чтения документа
- **WHEN** `read_document` получает `address: "R1C1:R5C4"`, затем `address: "R10C1"`
- **THEN** в первом вызове это `area`, во втором — `start_address`; в ответах — соответствующий `renamed`

#### Scenario: Синоним и параметр вместе
- **WHEN** `set_area_text` получает и `address`, и `area`
- **THEN** отказ `invalid_arguments`: `area` — лишний аргумент с `did_you_mean: {"area": "address"}`

#### Scenario: keys строкой
- **WHEN** `send_keys` получает `keys: "CTRL+S"`
- **THEN** отправлено сочетание `["CTRL", "S"]`

### Requirement: Подсказка в отказе на аргументы
Отказ `invalid_arguments` на лишний аргумент MUST содержать `did_you_mean: {лишний: параметр}`, если параметр нашёлся по таблице синонимов или по близости имени; имя с непечатаемыми символами подсказки не получает. Если агент передал `ref` действию без `ref`, отказ MUST содержать `suggested_actions` — до 5 близких по имени действий, которые принимают `ref`.

#### Scenario: Окно по ref
- **WHEN** шаг `{"action": "activate_window", "args": {"ref": "<окно>"}}`
- **THEN** отказ `invalid_arguments`, `unexpected_parameters: ["ref"]`, в `suggested_actions` есть `activate`

#### Scenario: Похожее имя
- **WHEN** `goto_row` получает `values`
- **THEN** отказ `invalid_arguments` содержит `did_you_mean` с параметром `goto_row`

#### Scenario: Имя с переводом строки
- **WHEN** `set_area_text` получает лишний аргумент `"ref\n"`
- **THEN** отказ `invalid_arguments` читается как TOON, `unexpected_parameters: ["ref\n"]`, без `did_you_mean`

### Requirement: Действие без подключения
Шаг, которому нужен клиент, при отсутствии подключения MUST отвечать `ok: false`, `code: "not_connected"`, без исключения. Если в реестре клиентов жив ровно один клиент, ответ MUST содержать `suggested_call` `{"action": "connect", "args": {"profile": <его профиль>}}`. Несколько живых — список `running` (профиль, порт) без `suggested_call`. Ни одного при настроенных профилях — `suggested_call` `list_profiles`. Сам testpilot MUST NOT подключаться.

#### Scenario: Первое действие сессии
- **WHEN** клиент профиля `ib` запущен `client start`, MCP не подключён, агент вызывает `get_active_window`
- **THEN** ответ `not_connected` с `suggested_call` `{"action": "connect", "args": {"profile": "ib"}}`; этот вызов проходит через `execute` без правки

#### Scenario: Два клиента
- **WHEN** живы клиенты двух профилей, MCP не подключён
- **THEN** ответ `not_connected` с `running` из двух записей, без `suggested_call`

### Requirement: Применимость действия
`search` по имени действия, которое адресует элемент, MUST показывать строку `Applies to:` с классами элементов, как `class` в ответах `find_objects`. Отказ `unsupported_element_type` или `unsupported_receiver` по `ref` MUST содержать `element_class`, `applies_to` действия и `suggested_actions` — до 5 действий, применимых к классу элемента, ближайших по имени к вызванному.

#### Scenario: Описание действия
- **WHEN** агент вызывает `search(query="choose_row")`
- **THEN** в ответе строка `Applies to: Table`

#### Scenario: Выбор из списка не для этого элемента
- **WHEN** `choose_from_drop_list` по `ref` поля отказан `unsupported_receiver`
- **THEN** отказ содержит `element_class: "EditField"` и `suggested_actions` с действиями выбора для `EditField`

### Requirement: Контекст формы по элементу
`get_context` с `ref` элемента формы MUST читать форму, в которой лежит элемент, и возвращать её `form_ref`. Элемент вне управляемой формы MUST отказываться `unsupported_receiver` с `suggested_actions`.

#### Scenario: ref поля
- **WHEN** `get_context(ref=<поле формы>)`
- **THEN** ответ — контекст формы этого поля и `form_ref` формы
