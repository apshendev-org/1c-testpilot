## Why

На WS развёрнутый клиент 1С (флаг процесса SW_MAXIMIZE, изменение testpilot-ui-feedback, кит v2.25.0-rc1) заблокировал владельцу мышь, клавиатуру и меню Windows. Причина не разобрана; до разбора разворот должен быть выключен.

## What Changes

- Разворот окна запущенного клиента — только при TC1C_MAXIMIZE_WINDOW=true, по умолчанию выключен.
- .env.example: ключ с описанием.

Спайк: не нужен — откат к поведению до v2.25.0-rc1 под флагом; разбор причины блокировки — отдельный спайк (issue кита).

## Capabilities

### Modified Capabilities

- client-launch-cli: требование «Окно запущенного клиента развёрнуто» — только при TC1C_MAXIMIZE_WINDOW.

## Impact

testpilot/app/_runtime.py (tc_launch_client), testpilot/.env.example.
