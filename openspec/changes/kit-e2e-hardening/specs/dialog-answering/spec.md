# Spec Delta

## Purpose

Ответ на модальный вопрос Да/Нет не тратит время теста, когда вопроса нет.

## ADDED Requirements

### Requirement: Без диалога ответ сразу
Если на момент вызова модального вопроса нет, а время ожидания не задано или равно 0, система MUST вернуть `answer_dialog` без ожидания: `ok: true`, `answered: null`, `question: null`, `code: no_dialog`.

#### Scenario: Диалога нет
- **WHEN** тест вызывает `answer_dialog(confirm=False)` при отсутствии вопроса
- **THEN** ответ приходит не позже одного обхода окна, `code: no_dialog`

### Requirement: Явное ожидание появления диалога
Система MUST принимать у `answer_dialog` параметр `wait` (секунды, по умолчанию 0) и ждать появления вопроса не дольше `wait`. Прежний параметр `timeout` MUST работать как псевдоним `wait`.

#### Scenario: Диалог появляется с задержкой
- **WHEN** тест вызывает `answer_dialog(confirm=True, wait=2)`, а вопрос появляется через 0,5 с
- **THEN** система нажимает «Да» и возвращает текст вопроса

#### Scenario: Диалог не появился за wait
- **WHEN** вопроса нет `wait` секунд
- **THEN** ответ `code: no_dialog` через `wait` секунд

#### Scenario: Старый вызов с timeout
- **WHEN** тест вызывает `answer_dialog(confirm=False, timeout=1)`
- **THEN** система ждёт вопрос не дольше 1 с, как при `wait=1`
