# Spec Delta

## Purpose

Запуск и остановка тест-клиента 1С с обработкой Testpilot из командной строки, без MCP-сервера, чтобы внешние инструменты (dev_ib.py кита) готовили клиент для последующих pytest-прогонов.

## ADDED Requirements

### Requirement: Запуск клиента по профилю из командной строки
Команда `1c-testpilot client start --profile <имя>` MUST запустить клиент по профилю: `/TESTCLIENT -TPort`, `/Execute` с обработкой, подтверждение предупреждения безопасности, ожидание готовности. Затем MUST отключиться, оставить процесс работать и вывести JSON с `pid`, `host`, `port`, `version`, `execution_ready`.

#### Scenario: Успешный запуск
- **WHEN** выполняется `1c-testpilot client start --profile ws_epf`
- **THEN** код выхода 0, в stdout JSON с `pid` и `port`, процесс 1С продолжает работать после выхода команды, pytest с профилем на этот `host`/`port` подключается и исполняет код

#### Scenario: Неудачная подготовка
- **WHEN** клиент не стал готов за `wait` профиля или обработка не открылась
- **THEN** запущенный процесс завершён, код выхода ненулевой, в stderr JSON с `code` и `error`

### Requirement: Остановка клиента из командной строки
Команда `1c-testpilot client stop` MUST завершить клиент, запущенный `client start`, по `--pid` или по `--profile` (порт профиля), и вернуть код 0, если процесса уже нет.

#### Scenario: Остановка по pid
- **WHEN** выполняется `1c-testpilot client stop --pid <pid из start>`
- **THEN** процесс 1С завершён, код выхода 0

#### Scenario: Процесса нет
- **WHEN** процесс с указанным pid уже завершился
- **THEN** код выхода 0, в stdout `"stopped": false`
