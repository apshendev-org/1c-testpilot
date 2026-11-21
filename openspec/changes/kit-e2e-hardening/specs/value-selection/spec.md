# Spec Delta

## Purpose

Выбор значения поля через список или форму выбора устойчив к временной неготовности списка в тестируемом клиенте.

## ADDED Requirements

### Requirement: Повтор выбора при неготовом списке
Если клиент отклонил шаг выбора с «The test client does not support this action on this object» (`unsupported_receiver`), система MUST повторять этот шаг с перечитыванием списка до успеха или до истечения `timeout`. Повтор MUST NOT выполняться, если значение поля уже изменилось.

#### Scenario: Список сформировался со второй попытки
- **WHEN** первый выбор пункта отклонён с `unsupported_receiver`, а следующий проходит
- **THEN** ответ `ok: true`, `verified: true`, `attempts` больше 1

#### Scenario: Список так и не сформировался
- **WHEN** отказ повторяется до истечения `timeout`
- **THEN** ответ `ok: false`, `code: unsupported_receiver`, `selection_sent: true` и число попыток

#### Scenario: Значение уже изменилось
- **WHEN** после отказа значение поля отличается от исходного
- **THEN** повтора нет, итог определяет обычная проверка `expected`
