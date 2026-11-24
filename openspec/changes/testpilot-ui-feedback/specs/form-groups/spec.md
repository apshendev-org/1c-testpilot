## ADDED Requirements

### Requirement: current_opened отвечает состояние раскрытия группы
`current_opened` MUST возвращать `opened: true` у развёрнутой сворачиваемой группы и `opened: false` у свёрнутой, как отвечает платформа, без инверсии. Нечитаемый ответ MUST давать `opened: null`.

#### Scenario: Развёрнутая группа
- **WHEN** сворачиваемая группа развёрнута (`Скрыта()` кодом — Ложь)
- **THEN** `current_opened` возвращает `opened: true`

#### Scenario: Свёрнутая группа
- **WHEN** группа свёрнута `collapse`
- **THEN** `current_opened` возвращает `opened: false`
