# spreadsheet-edit Specification

## Purpose

Правка ячеек табличного документа: незаконченная правка не забирает нажатия молча, несовпавший ввод отменяется, ссылочная ячейка получает значение точным представлением.

## Requirements

### Requirement: Незаконченная правка ячейки — состояние testpilot
Незаконченную правку ячейки табличного документа MUST вести сам testpilot: `begin_edit_current_area`, принятый клиентом без смены активного окна, MUST оставлять правку незаконченной и при флаге платформы `edit_mode: false`; снимает её только `end_edit_current_area` (с `cancel` или без). Ответ с `edit_mode: false` MUST говорить, что правка не подтверждена и её надо закончить или отменить.

#### Scenario: Флаг отвечает false
- **WHEN** `begin_edit_current_area` по ссылочной ячейке принят, окно не сменилось, флаг правки `false`
- **THEN** правка числится незаконченной до `end_edit_current_area`

### Requirement: click при незаконченной правке ячейки
`click` MUST отказывать до нажатия, пока в подключении есть незаконченная правка ячейки: `ok: false`, `code: "other_input_pending"`, `suggested_action: "end_edit_current_area"`. Нажатие MUST NOT уходить в клиент.

#### Scenario: Нажатие после неудачного ввода
- **WHEN** правка ячейки начата и не закончена, агент нажимает кнопку формы
- **THEN** отказ `other_input_pending` с адресом поля, кнопка не нажата

### Requirement: set_area_text отменяет несовпавшую правку
Если текст ячейки после завершения правки не совпал с заданным, `set_area_text` MUST отправить `end_edit_current_area(cancel=true)` и вернуть `ok: false`, `edit_cancelled` с итогом отмены и подсказку: для ссылочной ячейки нужен точный текст представления существующего элемента.

#### Scenario: Текста нет в справочнике
- **WHEN** `set_area_text` ссылочной ячейки текстом, которого нет в справочнике
- **THEN** `ok: false`, `edit_cancelled: true`, следующий `click` не отказывает из-за правки

### Requirement: select_value по ячейке табличного документа
`select_value` по полю табличного документа MUST ставить `value` в текущую ячейку как `set_area_text` с точным представлением и возвращать его итог (`verified`). `match`, `choice_table`, `choice_column`, `data_type`, `expected` с полем документа MUST давать `invalid_argument` до действий в клиенте.

#### Scenario: Значение справочника в ячейке
- **WHEN** текущая ячейка ссылочная, `select_value(value="Администрация")` — существующий элемент
- **THEN** `ok: true`, `verified: true`, в ячейке «Администрация»
