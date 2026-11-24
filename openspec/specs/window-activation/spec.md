# window-activation Specification

## Purpose

Переключение активного окна клиента 1С: какая форма становится активной по запросу агента.

## Requirements

### Requirement: Активизация окна по заголовку формы
`activate_window` MUST принимать необязательный `title` (точно или с `*` `?`). С ним MUST активизировать форму приложения с этим заголовком, при нескольких — последнюю открытую, и при нескольких указать их число в `matches`. Если такой формы нет, MUST вернуть `ok: false`, `code: window_not_found` и заголовки открытых форм в `titles`. Без `title` поведение прежнее.

#### Scenario: Две вкладки
- **WHEN** открыты две формы, активна первая, агент вызывает `activate_window(title=<заголовок второй>)`
- **THEN** `get_active_window` возвращает окно второй формы

#### Scenario: Нет такой формы
- **WHEN** агент вызывает `activate_window(title="Нет такой")`
- **THEN** `ok: false`, `code: window_not_found`, `titles` — заголовки открытых форм
