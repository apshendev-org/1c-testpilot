## 1. Реализация

- [x] 1.1 `_typed_verdict`: тип не прочитан — текст и представление, разобранные как одна дата, принимаются (`verification: date_text`)
- [x] 1.2 `Client.reset`: до `close_window` — `close_drop_list` и `cancel_edit` текущего поля форм окна с открытым списком
- [x] 1.3 `--tc-keep-data`: `testpilot_data` не удаляет данные
- [x] 1.4 `docs/PYTHON_TESTING.md`: сброс и `--tc-keep-data`

## 2. Проверка

- [x] 2.1 Тесты на заглушках: `tests/test_typed_input.py` (1.1), `tests/test_pytest_plugin.py` (1.2, 1.3)

Живая проверка на клиенте 1С — в перечне проверок выпуска кита v2.22.0.
