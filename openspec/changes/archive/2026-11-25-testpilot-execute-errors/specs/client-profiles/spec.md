## ADDED Requirements

### Requirement: Подключение по профилю запуска
`connect(profile)` с профилем запуска MUST подключаться к живому клиенту из `.testpilot-clients.json`, только если подходящий клиент ровно один. Подходящий — клиент этого профиля или профиля той же базы, сервера и пользователя (с `port` — на этом порту). Ответ MUST содержать `reused: true` и профиль клиента. Ни одного — `profile_action_mismatch` с `suggested_call` `launch_client(profile)`. Несколько — отказ `client_ambiguous` со списком `running`. `connect` MUST NOT запускать процесс.

#### Scenario: Клиент запущен
- **WHEN** `client start --profile ib` завершился, агент вызывает `connect(profile="ib")`
- **THEN** MCP подключён к порту клиента `ib`, ответ `ok: true`, `reused: true`, `profile: "ib"`

#### Scenario: Клиент не запущен
- **WHEN** живого клиента профиля `ib` и его базы с тем же пользователем нет
- **THEN** отказ `profile_action_mismatch` с `suggested_call` `{"action": "launch_client", "args": {"profile": "ib"}}`, процесс не запущен

#### Scenario: Два подходящих клиента
- **WHEN** живы клиенты профилей `ib` и `ib-debug` с одной базой и пользователем
- **THEN** отказ `client_ambiguous`, `running` перечисляет оба профиля и порты, подключения нет
