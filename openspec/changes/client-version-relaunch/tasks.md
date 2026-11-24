## 1. Код

- [x] 1.1 Поиск дочернего клиента: `psutil`, `ppid` = запущенный PID, имя `1cv8*`, в командной строке `-TPort<порт>`; версия — имя каталога над `bin` его `1cv8.exe`
- [x] 1.2 `_finish_client_launch`: при любом неудачном старте дочерний клиент есть — `client_version_mismatch` с версиями (и в ветке раннего выхода процесса); наш процесс может ещё выходить
- [x] 1.3 `_finish_client_launch`: дочерние клиенты завершаются `psutil` (`kill`, `wait`), `client_stopped` — по факту; CLI выводит `cleanup_error`
- [x] 1.4 Живая проверка на WS (паре кита 1c_amu): профиль `ib` с `version: 8.3.27.1688` → `client_version_mismatch`, процессов 1С дерева нет; профиль 2342 — старт как раньше. Сырой вывод — `docs/spikes/testpilot-profile-version/recording/` кита, run v2 спайка spk_e348d75193

## 2. Матрица тестов (поток тестов)

| Сценарий | Тест |
|---|---|
| Клиент старее кластера | фейк `psutil` по записям `docs/spikes/testpilot-profile-version/recording/` кита (`01-relaunched-child.txt` — ppid, exe, командная строка; `02-mismatch-run.txt` — ответ), в том числе когда наш процесс ещё жив → `client_version_mismatch`, версии в `error`, дочерний завершён, `client_stopped: true` |
| Чужой процесс с тем же родителем | дочерний с другим `-TPort` → код отказа прежний, процесс не тронут |
| Удачный старт | дочерних процессов не ищем, ответ прежний |
