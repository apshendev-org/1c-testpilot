# object-search Specification

## Purpose

Поиск объектов формы и приложения: как фильтр класса понимает имена, которые агент берёт из типов платформы.

## Requirements

### Requirement: Класс по имени типа платформы
`find_objects` и `find_object` MUST принимать в `cls` имя типа элемента формы платформы как класс testpilot: `FormGroup`, `ГруппаФормы` — `Group`; `FormButton`, `КнопкаФормы` — `Button`; `FormField`, `ПолеФормы` — `EditField`; `FormTable`, `ТаблицаФормы` — `Table`; `FormDecoration`, `ДекорацияФормы` — `Decoration`. Прочие значения `cls` MUST сравниваться как прежде.

#### Scenario: Имя типа платформы
- **WHEN** агент ищет `find_objects(cls="FormGroup")` на форме с группами
- **THEN** ответ — те же группы, что при `cls="Group"`

#### Scenario: Неизвестный класс
- **WHEN** агент ищет `find_objects(cls="Grup")`
- **THEN** пустой результат с диагностикой неизвестного класса, как прежде
