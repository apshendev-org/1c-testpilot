## ADDED Requirements

### Requirement: Стартовое окно, отказывающее в активации
Если при подготовке рабочее окно отказывает в активации с `target_not_interactive`, `invalid_element_state`, `client_busy` или `target_unavailable`, подготовка MUST пробовать остальные рабочие окна, затем повторять до срока `wait`, как при поиске обработки. Срок истёк — `helper_not_ready` с `last_error`.

#### Scenario: Новости у администратора
- **WHEN** `client start --profile ib`, при старте открыто окно «Новости», и его форма отказывает в активации
- **THEN** активируется главное окно, `client start` завершается с `ok: true`
