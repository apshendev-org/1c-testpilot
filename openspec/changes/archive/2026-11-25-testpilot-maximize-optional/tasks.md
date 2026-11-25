## 1. Код

- [x] 1.1 tc_launch_client: SW_MAXIMIZE только при TC1C_MAXIMIZE_WINDOW=true
- [x] 1.2 .env.example: TC1C_MAXIMIZE_WINDOW=false с описанием

## 2. Тесты (отдельный поток)

| Требование | Сценарий | Тест |
|---|---|---|
| Окно запущенного клиента развёрнуто | Сохранённый размер шире экрана | `test_ui_feedback.py::test_windows_client_is_launched_maximized_when_TC1C_MAXIMIZE_WINDOW_is_true`, `::test_isolated_desktop_launch_is_unchanged` (изолированный стол не меняется и при true) |
| Окно запущенного клиента развёрнуто | Разворот выключен по умолчанию | `test_ui_feedback.py::test_windows_client_is_launched_without_the_window_flag_by_default` (unset, false) |
| Окно запущенного клиента развёрнуто | Не Windows | `test_ui_feedback.py::test_client_without_startupinfo_is_launched_without_the_window_flag` (при true) |

- [x] 2.1 тесты по матрице
