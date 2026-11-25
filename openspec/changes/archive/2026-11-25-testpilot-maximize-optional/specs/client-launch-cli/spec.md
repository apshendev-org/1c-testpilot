## MODIFIED Requirements

### Requirement: Окно запущенного клиента развёрнуто
Клиент 1С, который testpilot запускает на Windows в рабочем сеансе, MUST открываться развёрнутым окном (флаг процесса SW_MAXIMIZE) только при TC1C_MAXIMIZE_WINDOW=true; без ключа или с false флаг окна MUST NOT передаваться. Запуск на изолированном рабочем столе MUST NOT меняться.

#### Scenario: Сохранённый размер шире экрана
- **WHEN** TC1C_MAXIMIZE_WINDOW=true, testpilot запускает клиент пользователя, чьё окно сохранено шириной 1438 px, на экране 1024 px
- **THEN** окно клиента развёрнуто на экран

#### Scenario: Разворот выключен по умолчанию
- **WHEN** TC1C_MAXIMIZE_WINDOW не задан или false, testpilot запускает клиент на Windows
- **THEN** процесс запускается без флага окна

#### Scenario: Не Windows
- **WHEN** testpilot запускает клиент не на Windows
- **THEN** процесс запускается без флага окна
