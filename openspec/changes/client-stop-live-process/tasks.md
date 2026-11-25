## 1. Код

- [ ] 1.1 `app/_client_registry.py`: признак «процесс записи — свой клиент» (`1cv8*`, `-TPort<порт>`) без проверки порта; `alive` = свой + порт слушается
- [ ] 1.2 `app/_cli.py` `client_stop`: по `--profile` — свой процесс завершается и без слушающего порта; `_terminate` — сначала дочерние процессы, затем сам (`terminate`, ожидание, `kill`); `stopped: false` — только без процесса или при чужом PID

## 2. Тесты (поток тестов кита)

- [ ] 2.1 Матрица — в `openspec/changes/dev-ib-client-stop-start/tasks.md` кита, пп. 3.1–3.2; `tests/` testpilot, процессы — фейки по записям `docs/spikes/dev-ib-client-security-restart/recording/` кита

## 3. Проверка

- [ ] 3.1 `uv run --no-project --with ".[test]" pytest tests -q`, `openspec validate --all --strict` — зелёные
