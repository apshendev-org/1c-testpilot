"""Прежние пути возврата окна после кода Helper — записи, которыми изменение helper-request-form закрывает эти
пути (REMOVED «Исполнение при активной рабочей форме»), и новый путь по тому же сценарию — форма выбора из ячейки
табличного документа (R3C9 «Подразделение» макета АРМ КС).

docs/spikes/testpilot-cell-edit/recording/04-find-rows-focus.jsonl — find_rows при форме выбора: table_read_failed, затем no_active_work_window
docs/spikes/testpilot-cell-edit/recording/05-read-rows-focus.jsonl — read_rows → окно потеряно; activate по ключу формы — ok, окно не вернулось
docs/spikes/testpilot-cell-edit/recording/06-restore-with-handle.jsonl — find_rows с возвратом по handle — table_read_failed → no_active_work_window
docs/spikes/testpilot-cell-edit/recording/07-any-helper-code.jsonl — любой execute_code при форме выбора → no_active_work_window
docs/spikes/testpilot-cell-edit/recording/08-activate-from-code.jsonl — Активизировать() формы выбора из кода Helper: до и после — Testpilot: Helper
docs/spikes/testpilot-helper-restore/recording/01-idle-activate.jsonl — Активизировать() в обработчике ожидания после команды: не возвращает
docs/spikes/testpilot-helper-restore/recording/02-lock-copy.jsonl — закрытие формы с блокировкой окна владельца возвращает активность владельцу; после публичного execute_code Helper забирает её после choose_row
docs/spikes/testpilot-helper-restore/recording/03-child-request.jsonl — Request открыт кодом Helper: публичные действия в Request выполняются, но Helper забирает активность после choose_row
docs/spikes/testpilot-helper-restore/recording/04-click-without-activate.jsonl — кнопка Helper протоколом без ACTIVATE работает; публичные input_html/click в Request — теряют окно
docs/spikes/testpilot-helper-idle/recording/01-interval-half.jsonl — обработчик ожидания с интервалом 0,5 с: execution_failed
docs/spikes/testpilot-helper-idle/recording/02-choice-from-cell.jsonl — обмен файлами через обработчик ожидания: окно не теряется, задержка до интервала (владелец отклонил)
"""
import pytest

import _helper_client as H
import _recording as recorded

CELL = 'M_choice_from_cell'          # шаг записей cell-edit: форма выбора открыта из ячейки
NO_WINDOW = 'no_active_work_window'
FORMER = [  # (запись cell-edit, действие testpilot при активной форме выбора, ответ действия)
    (recorded.CELL_FIND_ROWS, 'find_rows', {'ok': False, 'code': 'table_read_failed'}),
    (recorded.CELL_READ_ROWS, 'read_rows', {'ok': False}),
    (recorded.CELL_RESTORE_HANDLE, 'find_rows', {'ok': False, 'code': 'table_read_failed'}),
    (recorded.CELL_ANY_CODE, 'execute_code', {'ok': True}),
    (recorded.CELL_ACTIVATE_CODE, 'execute_code',
     {'ok': True, 'result': {'after': 'Testpilot: Helper', 'found': True, 'before': 'Testpilot: Helper'}}),
]


def next_window(rows, done):
    return next(r for r in rows[rows.index(done) + 1:] if r['action'] == 'get_active_window')['response']


@pytest.mark.parametrize('path, action, answer', FORMER,
                         ids=['04-find-rows', '05-read-rows', '06-restore-with-handle', '07-any-helper-code', '08-activate-from-code'])
def test_former_path_lost_the_choice_form_recorded(path, action, answer):
    """Прежний путь (ACTIVATE Helper перед командой): при форме выбора из ячейки после команды активное окно —
    no_active_work_window (записи cell-edit 04–08); choose_row после этого всё же выбирает значение."""
    rows = recorded.direct(path, step=CELL)
    assert next(r for r in rows if r['action'] == 'get_active_window')['response']['title'] == 'Подразделения'
    done = next(r for r in rows if r['action'] == action)
    assert {k: done['response'].get(k) for k in answer} == answer
    assert next_window(rows, done)['code'] == NO_WINDOW
    chosen = next(r for r in rows if r['action'] == 'choose_row')
    assert chosen['response']['ok'] and next(r for r in rows if r['action'] == 'get_area_text')['response']['text'] == 'Администрация'


def test_activate_by_key_does_not_return_the_choice_form_recorded():
    """cell-edit 05: после read_rows окно потеряно; activate по ключу таблицы формы выбора — ok, но окно не вернулось."""
    rows = recorded.direct(recorded.CELL_READ_ROWS, step=CELL)
    lost = next(r for r in rows if r['action'] == 'read_rows')
    assert next_window(rows, lost)['code'] == NO_WINDOW
    activate = next(r for r in rows if r['action'] == 'activate')
    assert {k: activate['response'].get(k) for k in ('ok', 'target_check')} == {'ok': True, 'target_check': 'present'}
    assert activate['arguments']['key'] == lost['arguments']['key']            # ключ таблицы «Список» формы выбора
    assert next_window(rows, activate)['code'] == NO_WINDOW


def test_deferred_activate_from_helper_code_is_not_used_recorded():
    """restore-1 (01): Активизировать() окна формы выбора в обработчике ожидания после команды Helper — до и после
    «Testpilot: Helper», агенту no_active_work_window, и после choose_row тоже; новый путь не шлёт ACTIVATE и не
    активизирует Helper кодом — по тому же сценарию форма выбора остаётся активной (запись 05)."""
    rows = recorded.direct(recorded.RESTORE_ACTIVATE, step='choice_from_cell')
    done = next(r for r in rows if r['action'] == 'execute_code' and isinstance(r['response'].get('result'), str))
    assert done['response']['result'] == 'до=Testpilot: Helper; найдено=Да; после окна=Testpilot: Helper; после формы=Testpilot: Helper'
    assert next_window(rows, done)['code'] == NO_WINDOW
    chosen = next(r for r in rows if r['action'] == 'choose_row')
    assert next_window(rows, chosen)['code'] == NO_WINDOW
    client = H.Client(H.PROTOCOL, active=H.PROTOCOL.window('choice_from_cell', H.CHOICE)['key'])
    for _, window in H.PROTOCOL.windows:
        client.show(window)
    assert H.execute(client, mode='code', context='client', code=H.CHILD_CODE)['ok']
    assert client.history == [H.PROTOCOL.window('choice_from_cell', H.CHOICE)['key'],
                              H.PROTOCOL.window('child_open', H.REQUEST)['key'],
                              H.PROTOCOL.window('choice_from_cell', H.CHOICE)['key']]
    assert client.activated == [] and H.PROTOCOL.helper_window not in client.history


def test_closing_locked_owner_form_returns_activity_but_activated_helper_takes_it_back_recorded():
    """restore-2b (02), restore-3c (03): закрытие формы, открытой с блокировкой окна владельца, возвращает активность
    владельцу — сразу, отложенно и из кода; но Helper, активизированный публичным execute_code хоть раз, забирает
    активность после закрытия рабочей формы (choose_row → no_active_work_window)."""
    rows = recorded.direct(recorded.RESTORE_LOCK_COPY)
    results = [r for r in recorded.direct(recorded.RESTORE_LOCK_COPY, step='choice_from_cell')
               if r['action'] == 'execute_code' and isinstance(r['response'].get('result'), str)]
    assert [r['response']['result'] for r in results] == [
        'до=Testpilot: Helper; найдено=Да; после окна=Testpilot: Helper; после формы=Testpilot: Helper',
        'открыта; активно=Testpilot: Helper | до закрытия=Testpilot: Helper; после=Подразделения',
        'открыта; активно=Testpilot: Helper',
        'до закрытия=Testpilot: Helper; после=Подразделения']
    assert [next_window(rows, r)['title'] for r in results[1:]] == ['Подразделения'] * 3
    assert next_window(rows, next(r for r in rows if r['action'] == 'choose_row'))['code'] == NO_WINDOW
    # 03: Request открыта кодом Helper (Helper активен), публичные input_html и click в ней выполняют код —
    # «Подразделения»; после choose_row — no_active_work_window (пять опросов).
    rows = recorded.direct(recorded.RESTORE_CHILD_REQUEST)
    after_click = next_window(rows, next(r for r in rows if r['action'] == 'click'))
    assert after_click['title'] == 'Подразделения'
    chosen = next(r for r in rows if r['action'] == 'choose_row')
    polls = [r['response']['code'] for r in rows[rows.index(chosen) + 1:] if r['action'] == 'get_active_window']
    assert polls == [NO_WINDOW] * 5
    # Новый путь: Request открывается кнопкой Helper протоколом — Helper не активен, после choose_row активна форма с таблицей.
    client = H.Client(H.PROTOCOL, active=H.PROTOCOL.window('choice_from_cell', H.CHOICE)['key'])
    for _, window in H.PROTOCOL.windows:
        client.show(window)
    H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    client.active = H.PROTOCOL.window('child_after', H.ARM)['key']
    H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert client.active == H.PROTOCOL.window('child_after', H.ARM)['key'] and client.activated == []


def test_protocol_click_without_activate_works_and_public_actions_in_request_lose_the_window():
    """restore-4b (04): CLICK кнопки Helper протоколом без ACTIVATE открывает Request (активно окно Request);
    публичные input_html и click в Request выполняют код, но публичный click активизирует Helper — агенту
    no_active_work_window и после choose_row; окна Helper и Request агенту не видны. Поэтому новый путь вводит
    запрос и нажимает «Выполнить» только протоколом (test_request_form)."""
    rows = recorded.direct(recorded.RESTORE_CLICK)
    opened = H.raw(recorded.RESTORE_CLICK, step='child_open')[0]
    assert opened['button'] == 'RunServer' and not opened.get('input')       # клик, не ввод
    assert opened['result']['ok'] and [r['opcode'] for r in opened['result']['replies']] == [66, 66]
    opened_at = next(r for r in H.calls(recorded.RESTORE_CLICK, 'get_active_window', 'child_open'))
    assert recorded.window(opened_at)['title'] == 'Testpilot: запрос: Request'
    click = next(r for r in rows if r['action'] == 'click')
    assert click['arguments']['key'].endswith('.Button[RunClient]') and click['response']['ok']
    assert next_window(rows, click)['code'] == NO_WINDOW
    chosen = next(r for r in rows if r['action'] == 'choose_row')
    polls = [r['response']['code'] for r in rows[rows.index(chosen) + 1:] if r['action'] == 'get_active_window']
    assert polls == [NO_WINDOW] * 5
    children = next(r for r in rows if r['action'] == 'get_child_objects')['response']['children']
    assert [c['title'] for c in children] == ['АРМ контрактной службы (макет)',
                                              'DEV / Бухгалтерия государственного учреждения, редакция 2.0', 'Начальная страница']


def test_idle_handler_file_exchange_is_not_used():
    """Спайк testpilot-helper-idle: 01 — повторяющийся обработчик ожидания с интервалом 0,5 с недопустим
    (execution_failed); 02 — обмен файлами через обработчик ожидания не теряет окно, задержка до интервала;
    путь владелец отклонил (README helper-restore: второй канал и опрос). Новый путь — один ввод JSON-запроса в поле
    Request, без обработчика ожидания и файлов."""
    half = recorded.direct(recorded.IDLE_HALF)[1]
    assert half['action'] == 'execute_code' and half['response']['code'] == 'execution_failed'
    assert 'ПодключитьОбработчикОжидания' in half['response']['error']
    files = recorded.rows(recorded.IDLE_CHOICE, kind='file')
    assert [(f['name'], f['seconds']) for f in files] == [('work', 1.2), ('windows', 0.2), ('choice_form', 1.0)]
    assert all(f['request_left'] is False for f in files)
    windows = [recorded.window(r) for r in H.calls(recorded.IDLE_CHOICE, 'get_active_window')]
    assert [w.get('title') for w in windows] == [None, H.ARM, H.ARM, H.CHOICE, H.CHOICE, H.CHOICE, H.ARM]
    client = H.Client(H.PROTOCOL, active=H.PROTOCOL.window('choice_from_cell', H.CHOICE)['key'])
    for _, window in H.PROTOCOL.windows:
        client.show(window)
    H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert len(client.inputs) == 1
    assert set(H.payload(client.inputs[0])) == {'protocol', 'request_id', 'mode', 'context', 'code', 'query', 'parameters', 'limit'}
    assert 'ОбработчикОжидания' not in client.inputs[0] and client.activated == []
