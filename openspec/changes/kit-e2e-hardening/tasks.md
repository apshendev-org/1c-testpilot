# Tasks

## 1. Исполнение кода без фильтра

- [ ] 1.1 Удалить `DEFAULT_FORBIDDEN`, `ALWAYS_FORBIDDEN`, `Settings.forbidden` и чтение `TC1C_CODE_FORBIDDEN_WORDS`/`TC1C_CODE_ALLOWED_WORDS` в `app/_code_execution.py`; `validate_code` проверяет только непустую строку и незакрытый литерал. Проверка: `grep -rn "FORBIDDEN\|ALLOWED_WORDS" app` пуст.
- [ ] 1.2 Переписать `tests/test_code_filter.py` под сценарии `specs/code-execution`: `Выполнить`, `Запрос.Выполнить()`, `Записать`, `Удалить` проходят, старая переменная запрета игнорируется, пустой код и незакрытая строка дают `invalid_code`. Проверка: `uv run --extra test pytest tests/test_code_filter.py -q` зелёный.
- [ ] 1.3 Обновить `onec/Testpilot/README.md` и `README.md`: убрать раздел о запрещённых словах и переменные, написать, что защита — `TC1C_CODE_EXECUTION=false` и права пользователя 1С. Проверка: grep переменных по `*.md` вне `openspec/` пуст.

## 2. Эффект click и input_text

- [ ] 2.1 `click`: чтение состояния до и после (окно, url, `modified`, число окон), поля `before`/`after`/`changed`, параметр `expect` (`changed|saved|closed|window`) с `effect_not_observed`; при `TC1C_READBACK=false` `expect` даёт `invalid_argument`. Проверка: unit-тесты на фейковом клиенте по сценариям `specs/action-effects` (запись прошла, запись не прошла, новое окно, без `expect`).
- [ ] 2.2 `input_text`: `verified` и `value_mismatch` по правилу «равные числа или префикс». Проверка: unit-тесты: группа вместо номенклатуры → `value_mismatch`; «2» → «2,000» и дата с временем → `verified: true`; без фиксации → `verified: null`.
- [ ] 2.3 Обновить описания действий MCP и `docs/TOOLS.md`, `docs/PYTHON_TESTING.md` (`expect`, `verified`, ограничение префикса). Проверка: тест версий инструментов (`tool_versions`), если он есть, зелёный; документация описывает новые поля.

## 3. Повтор select_value

- [ ] 3.1 В `app/_value_selection.py` повторять шаг выбора при `unsupported_receiver` (статус 17), пока значение поля не изменилось и не истёк `timeout`; добавить `attempts` в ответ. Проверка: unit-тесты: отказ, затем успех → `ok`, `attempts=2`; отказ до таймаута → `unsupported_receiver` с числом попыток; значение изменилось → повтора нет.
- [ ] 3.2 Описать повтор в `docs/TOOLS.md`. Проверка: раздел `select_value` упоминает `attempts`.

## 4. answer_dialog без ожидания

- [ ] 4.1 Параметр `wait` (по умолчанию 0), `timeout` — его псевдоним с умолчанием 0, `code: no_dialog` при отсутствии вопроса. Проверка: unit-тест: без диалога ответ за один обход (время вызова меньше 0,3 с на фейке); `wait=2` с вопросом через 0,5 с нажимает кнопку; `timeout=1` ждёт как `wait=1`.
- [ ] 4.2 Обновить описание инструмента и `docs/TOOLS.md` (смена умолчания с 5 с на 0). Проверка: описание упоминает `wait`.

## 5. Сброс клиента в pytest

- [ ] 5.1 `Client.reset()` в `app/testpilot.py` по design: отмена редактирования строк, закрытие окон, «Нет» на вопрос о сохранении, ошибка с ключом и заголовком незакрывшегося окна. Проверка: unit-тесты на фейке: модифицированный документ с редактируемой строкой → начальная страница; окно не закрывается → ошибка.
- [ ] 5.2 Фикстура `testpilot` вызывает `reset()` перед тестом при любой `--tc-client-scope`; ошибка — провал setup. Проверка: тест плагина через `pytester` (фейковый `Client`): `reset` вызван для каждого теста, ошибка даёт `error` на setup.
- [ ] 5.3 Описать сброс в `docs/PYTHON_TESTING.md`. Проверка: раздел о фикстурах упоминает `reset()`.

## 6. Учёт и удаление тестовых данных

- [ ] 6.1 Фикстура `testpilot_data` с `create`, `track`, `track_window` и удалением в teardown по В1 (обратный порядок, `ОбменДанными.Загрузка`, отмена проведения, пропуск отсутствующих, общий список ошибок). Проверка: тесты через `pytester` на фейковом клиенте: порядок удаления, пропуск удалённого, падение со списком неудалённых при ошибке одного объекта.
- [ ] 6.2 Разбор `ref=` из url окна в GUID. Проверка: unit-тест на образце url из спайка (`e1cib/data/Документ._ДемоРеализацияТоваров?ref=…`) и известном GUID.
- [ ] 6.3 Описать фикстуру в `docs/PYTHON_TESTING.md` с примером по мотивам `test_sale_data.py` из спайка. Проверка: пример в документации совпадает с API фикстуры.

## 7. Поставка Testpilot.epf и версия

- [ ] 7.1 Перенести `Testpilot.epf` в `app/testpilot_assets/` (`git mv`), добавить `package-data`, путь по умолчанию через `importlib.resources`, `onec/Testpilot/build.py` пишет туда же. Проверка: `uv build` и список файлов wheel содержит `testpilot_assets/Testpilot.epf`; unit-тест: без `code_epf` и `TC1C_CODE_EPF` путь указывает на файл пакета, `code_epf=""` — без обработки.
- [ ] 7.2 Обновить ссылки на путь в `README.md`, `onec/Testpilot/README.md`, `profiles.example.yaml`, `docs/PYTHON_TESTING.md`; записать в README форка пункт синхронизации с апстримом: обновлённый апстримом `onec/Testpilot/Testpilot.epf` переносить в `app/testpilot_assets/`. Проверка: grep `onec/Testpilot/Testpilot.epf` вне `openspec/` даёт только пункт синхронизации.
- [ ] 7.3 Версия `1.9.2.post3` в `pyproject.toml`. Проверка: `uv build` создаёт `1c_testpilot-1.9.2.post3`.

## 8. CLI запуска клиента

- [ ] 8.1 Подкоманда `1c-testpilot client start|stop` в `app/_cli.py` по `specs/client-launch-cli`; без подкоманды — MCP-сервер, как раньше. Проверка: unit-тесты на фейковом `Client`: `start` печатает JSON и вызывает `disconnect`, а не `close`; при ошибке подготовки процесс остановлен и код выхода ненулевой; `stop` по отсутствующему pid даёт 0 и `"stopped": false`.
- [ ] 8.2 Описать команды в `README.md` и `docs/PYTHON_TESTING.md` (запуск для внешнего инструмента и последующий pytest по `host`/`port`). Проверка: пример из документации совпадает с `1c-testpilot client --help`.

## 9. Интеграционная проверка

- [ ] 9.1 Полный прогон тестов форка. Проверка: `uv run --extra test pytest -q` зелёный, вывод приложен к PR.
- [ ] 9.2 По согласованию владельца: живой прогон в отдельной dev-ИБ на WS — тесты спайка `test_sale.py` и `test_sale_data.py`, переписанные на `reset()`, `testpilot_data`, `click(expect="saved")`, клиент поднят `1c-testpilot client start`, по 2 прогона подряд; проверить удаление проведённого документа в режиме загрузки. Проверка: 2 зелёных прогона, запрос остатков пуст, вывод в PR.
- [ ] 9.3 По решению владельца, не делать без его ок: короткий спайк Linux→WS — слушает ли порт TestClient (`-TPort`) не-loopback интерфейс и проходит ли анонимный NTLM с Linux. Проверка: запись спайка в реестре (`bb spike record`) с итогом «работает / не работает» и цитатами ошибок.

## Workflow follow-up

- Слить PR в `fork` и выпустить тег `v1.9.2.post3` только после ок владельца.
- После слияния архивировать изменение (`openspec archive kit-e2e-hardening`) и проверить, что спецификации появились в `openspec/specs/`.
