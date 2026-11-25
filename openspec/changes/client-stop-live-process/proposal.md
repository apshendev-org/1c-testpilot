## Why

Клиент 1С, упавший в «непредвиденную ошибку» (пользователь с защитой от опасных действий, код во внешней обработке), перестаёт слушать `-TPort`, но живёт и держит другие порты (runMcp). `1c-testpilot client stop --profile` считает такую запись мёртвой — проверка `alive` требует слушающий порт — и отвечает `"stopped": false`, процесс не трогает. Сирота держит порт и базу, её снимают руками (`dev_ib.py kill`). Спайк кита spike:spk_e5d3098723@v1 (`docs/spikes/dev-ib-client-security-restart/recording/05-role-stop.txt`), issue кита #138.

## What Changes

- `client stop --profile`: процесс записи, который по-прежнему `1cv8*` с `-TPort<порт записи>`, завершается с дочерними процессами, даже если порт не слушается; `stopped: true`.
- `client stop --pid`: тоже с дочерними процессами.
- `stopped: false` — только когда процесса нет или PID занят чужим процессом (тот не трогается).
- `client start` (повторное использование живого клиента) не меняется.

## Capabilities

### New Capabilities

### Modified Capabilities
- `client-launch-cli`: остановка клиента без слушающего порта и с дочерними процессами.

## Impact

- `app/_cli.py` (`client_stop`, `_terminate`), `app/_client_registry.py` (признак своего процесса без порта).
- Кит 1c-agent-kit: `dev_ib.py client stop` снимает зависший клиент (изменение кита `dev-ib-client-stop-start`).
