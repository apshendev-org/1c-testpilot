## 1. Реализация

- [x] 1.1 `_native_window.login_dialog(pid)`: верхнее видимое окно процесса без владельца с заголовком «Доступ к информационной базе» → заголовок, иначе `None`
- [x] 1.2 `_runtime._launch_failure`: выход процесса → `client_exited`; Windows, `desktop=default`, окно входа → `login_failed` с `dialog`; проверка — в цикле подключения и в `prepare(..., stop=)` на каждом круге
- [x] 1.3 Описание `tc_launch_client`: `login_failed`, `client_exited`

## 2. Тесты (поток тестов)

| Сценарий | Запись | Тест |
|---|---|---|
| Пользователя нет в базе | `login-failed.jsonl`, `no_user` | отказ `login_failed` до срока, процесс остановлен |
| Неверный пароль | `login-failed.jsonl`, `bad_password` | то же |
| Процесс вышел во время подготовки | — | `client_exited` до срока |
| Долгий обычный старт | `slow-start.jsonl` | окна загрузки и главное — не отказ, `ok: true` |

- [x] 2.1 Тесты по матрице, копии записей в `tests/recordings/`

## 3. Проверка

- [x] 3.1 Тесты testpilot, `payload/tests`, `openspec validate --all --strict`
