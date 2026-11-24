## Why

Агент проекта 1c_bgu20 («Макет АРМ КС», thr_tipdp79usa) на макете обработки с табличным документом и клиентом на WS потерял время на поведении testpilot, которое нельзя обойти из теста:
- окно клиента открывается с сохранённым размером шире экрана WS (1438 px при экране 1024): часть формы за краем, снимки обрезаны;
- `click` по сворачиваемой группе и по кнопке, меняющей только текущую область табличного документа, не даёт видимого эффекта, testpilot через половину таймаута нажимает второй раз — группа переключается дважды, команда выполняется дважды. Повтор вредил уже трижды (спайк spike:spk_d8a5084a0c@v1, шаг D; группа; кнопка «Найти»), а случаев, где он спас потерянное нажатие, не записано;
- `find_objects(cls="FormGroup")` даёт пустой результат: класс называется `Group`, а агент берёт имя из типа платформы;
- `set_area_text` на защищённой ячейке — «The element is not in a state that permits this action» без слова о защите: агент 4 раза гадал про фокус и устаревшие ссылки;
- `current_opened` у развёрнутой группы отвечает `opened: false` — testpilot инвертирует ответ платформы;
- переключить вкладку по заголовку нечем: `activate_window` параметров не принимает, агент писал цикл по `ПолучитьОкна()` кодом.

Спайк UI (spike:spk_91306bdbfc@v1, `docs/spikes/testpilot-ui-feedback`, записи `recording/01`–`06`, 8.3.27.2342) снял остальные жалобы: кириллические имена параметров `execute_code` работают (`05`); устаревший `ref` после переоткрытия формы даёт `target_unavailable`, клика нет (`02`); активное окно после `ОткрытьФорму` из кода — поведение прежнего релиза, его исправляет helper-request-form (PR #129), проверка — в перечне выпуска (`06`).

Спайк: spike:spk_d1fe75e265@v1, `docs/spikes/testpilot-maximized-window` (флаг процесса `SW_MAXIMIZE` разворачивает окно тонкого и толстого клиента, запись `recording/recording.txt`). Повтор клика и имена классов — поведение самого testpilot, обмен с клиентом 1С прежний: тесты — на существующих записях `tests/recordings`.

## What Changes

- Клиент 1С, запущенный testpilot на Windows, открывается развёрнутым окном (флаг `STARTUPINFO.wShowWindow = SW_MAXIMIZE`). Изолированный рабочий стол не меняется.
- `click` больше не повторяет нажатие: только ожидание эффекта до `timeout`. Поле `repeated` из ответа уходит.
- `click` по группе формы — без ожидания эффекта, как `expect="none"`: у переключения группы нет наблюдаемого состояния.
- `begin_edit_current_area`, `set_area_text`: отказ правки со статусом 11 несёт `message` о защите ячейки.
- `current_opened` без инверсии: `opened: true` у развёрнутой группы.
- `activate_window(title=None)`: с `title` активизирует форму с этим заголовком, без формы — `window_not_found` со списком заголовков.
- `find_objects`, `find_object`: `cls` принимает имена типов платформы (`FormGroup`, `FormButton`, `FormField`, `FormTable`, `FormDecoration`, `ГруппаФормы`, `КнопкаФормы`, `ПолеФормы`, `ТаблицаФормы`, `ДекорацияФормы`) как классы `Group`, `Button`, `EditField`, `Table`, `Decoration`.

## Capabilities

### New Capabilities
- `object-search`: фильтр класса в поиске объектов формы.
- `window-activation`: активизация окна по заголовку формы.
- `form-groups`: состояние раскрытия группы.

### Modified Capabilities
- `action-effects`: без повтора клика; клик по группе — без ожидания эффекта.
- `client-launch-cli`: окно запущенного клиента развёрнуто.
- `spreadsheet-edit`: отказ правки защищённой ячейки называет защиту.

## Impact

- `app/_runtime.py` — `tc_launch_client` (флаг окна), `_find_wait`, `tc_find_objects`, `tc_find_object` (имена классов), `tc_begin_edit_current_area`, `tc_set_area_text` (защита), `tc_current_opened`, `tc_activate_window`.
- `app/_effects.py` — `run()` без повтора.
- `docs/TOOLS.md` — `click`, `find_objects`, `activate_window`, правка ячейки.
- Кит: скилл `testpilot-testing` (`click` с `expect="none"` для группы больше не нужен) — отдельным PR после релиза.
