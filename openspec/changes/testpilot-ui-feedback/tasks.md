## 1. Код

- [x] 1.1 `tc_launch_client`: `STARTUPINFO` с `SW_MAXIMIZE` на Windows, изолированный рабочий стол без изменений
- [x] 1.2 `_effects.run`: удалить повтор и поле `repeated`
- [x] 1.3 `_effects.run`: клик по группе — как `expect="none"`
- [x] 1.4 `_find_wait`: имена типов платформы в `cls`
- [x] 1.5 `docs/TOOLS.md`: `click`, `find_objects`, `activate_window`, правка ячейки
- [x] 1.6 отказ правки со статусом 11 — `message` о защите
- [x] 1.7 `current_opened` без инверсии
- [x] 1.8 `activate_window(title)`

## 2. Тесты (отдельный поток)

| Требование | Сценарий | Тест |
|---|---|---|
| Ожидание и повтор до таймаута | Медленная запись | `test_effects.py::test_slow_save_is_waited_without_second_click` |
| Ожидание и повтор до таймаута | Окно ошибки | `test_effects.py::test_error_window_fails_at_once` |
| Ожидание и повтор до таймаута | Значения полей не читаются | `test_effects.py::test_unreadable_form_state_is_pressed_once` |
| Ожидание и повтор до таймаута | Эффект не виден | `test_effects.py::test_unchanged_state_is_pressed_once_then_fails` |
| Исключение без видимого эффекта | Кнопка без эффекта | `test_effects.py::test_expect_none_skips_observation` |
| Исключение без видимого эффекта | Сворачиваемая группа | `test_effects.py::test_group_click_does_not_wait_for_effect` |
| Окно запущенного клиента развёрнуто | Сохранённый размер шире экрана (запись спайка) | `test_ui_feedback.py::test_windows_client_is_launched_maximized`, `::test_isolated_desktop_launch_is_unchanged` |
| Окно запущенного клиента развёрнуто | Не Windows | `test_ui_feedback.py::test_client_without_startupinfo_is_launched_without_the_window_flag` |
| Отказ правки защищённой ячейки называет защиту | Защищённая ячейка; Свободная ячейка (запись `docs/spikes/testpilot-ui-feedback/recording/01-protected-cell.jsonl`) | `test_ui_feedback_spike.py::test_set_area_text_of_protected_cell_names_the_protection` (красный: `set_area_text` не возвращает `message` — код 1.6), `::test_begin_edit_of_protected_cell_names_the_protection`, `::test_set_area_text_of_free_cell_passes_without_protection_message`, `::test_other_refusals_of_begin_edit_do_not_name_the_protection` |
| current_opened отвечает состояние раскрытия группы | Развёрнутая группа; Свёрнутая группа (запись `03-current-opened.jsonl`) | `test_ui_feedback_spike.py::test_current_opened_answers_the_platform_without_inversion` (5 состояний), `::test_unreadable_current_opened_is_null` |
| Активизация окна по заголовку формы | Две вкладки; Нет такой формы (запись `04-windows-by-title.jsonl`) | `test_ui_feedback_spike.py::test_activate_window_by_title_switches_to_the_last_opened_form`, `::test_activate_window_title_accepts_wildcards`, `::test_unique_title_activates_that_form_without_matches`, `::test_activate_window_without_such_title_lists_open_titles`, `::test_activate_window_without_title_is_former_behaviour`, `::test_activate_window_refuses_ref_parameter` |
| Класс по имени типа платформы | Имя типа платформы | `test_ui_feedback.py::test_platform_type_name_in_cls_finds_the_recorded_class` |
| Класс по имени типа платформы | Неизвестный класс | `test_ui_feedback.py::test_unknown_class_is_empty_with_the_spelling_diagnostic`, `::test_diagnostics_of_a_missing_alias_name_the_reduced_class` (решение 4) |

- [x] 2.1 Тесты по матрице, запись `docs/spikes/testpilot-maximized-window/recording/recording.txt` — со ссылкой из теста
- [x] 2.2 Тесты новых строк матрицы (защита ячейки, current_opened, activate_window) на записях `docs/spikes/testpilot-ui-feedback/recording/`; каждая запись спайка — со ссылкой из теста — `test_ui_feedback_spike.py` (записи 00, 02, 05, 06 — факты без правки кода; `test_set_area_text_of_protected_cell_names_the_protection` красный до правки 1.6)

## 3. Проверка

- [ ] 3.1 `pytest tests`, `openspec validate --all --strict`
