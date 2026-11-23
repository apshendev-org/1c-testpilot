## 1. Реализация

- [x] 1.1 `tc_execute_command`: ключи открытых окон до команды (`_read_open_windows`); итоговое окно среди них и в нём `ФормаОбновить` (`Button`) → `tc_click(expect='none')`, `refreshed: true`; сбой чтения окон или нажатия — ответ как раньше
- [x] 1.2 Описание `execute_command`: `refreshed`

## 2. Тесты (поток тестов)

| Сценарий | Запись | Тест |
|---|---|---|
| Список открыт до фикстуры, команда вернула то же окно | `goto-row-stale-window.jsonl`, `goto-row-refresh.jsonl` | нажата `ФормаОбновить` с `expect='none'`, `refreshed: true` |
| Список открывается впервые | `goto-row-fixture.jsonl`, `goto-row-preloaded.jsonl` | без нажатия, без `refreshed` |
| Открытое окно без `ФормаОбновить` | — | без `refreshed`, без ошибки |

- [ ] 2.1 Тесты по матрице, копии записей в `tests/recordings/`

## 3. Проверка

- [x] 3.1 Живой прогон сценария `stale` на паре WS с кодом ветки: `execute_command` вернул то же окно за 327 мс с `refreshed: true`, первый `goto_row` — `found: true`
- [ ] 3.2 Тесты testpilot, `payload/tests`, `openspec validate --all --strict`
