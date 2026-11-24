"""Живая проверка кода ветки публичными инструментами — запись 10 спайка testpilot-helper-restore (restore-8b,
check_request_form.py; spike:spk_cff9b4db89@v3) и запись 09 (restore-8, до исправления):
  docs/spikes/testpilot-helper-restore/recording/10-live-check.jsonl
  docs/spikes/testpilot-helper-restore/recording/09-owner-closed.jsonl
Сценарии «Код закрывает форму-владельца», «Запрос после действий с формой», «Код открывает форму», «Форма выбора
из ячейки табличного документа» и «Нет рабочего окна» (старт): ожидаемые ответы — записанные, кадры протокола —
клиент _helper_client.Client с окнами записи 10 и ключами окон Helper и Request записи 05.
"""
import pytest

import _helper_client as H
import _recording as recorded
import guids as G

LIVE = recorded.RESTORE_LIVE
REQUEST = H.PROTOCOL.window('child_open', H.REQUEST)


def live(step, action, index=0):
    return H.calls(LIVE, action, step)[index]


def titles(step):
    return [recorded.window(r)['title'] for r in H.calls(LIVE, 'get_active_window', step)]


def client_at(window):
    client = H.Client(H.PROTOCOL, active=window['key'])
    for recorded_window in (H.LIVE_INFO, H.LIVE_ARM, H.LIVE_LIST, H.LIVE_CHOICE, H.LIVE_QUESTION, H.LIVE_ERROR):
        client.show(recorded_window)
    for _, recorded_window in H.PROTOCOL.windows:
        client.show(recorded_window)
    return client


def test_code_closing_owner_form_answer_received_and_next_execution_runs():
    """Сценарий «Код закрывает форму-владельца» (запись 10, startup; 09 — до исправления): execute_code закрывает
    «Информацию при запуске» — владельца Request; ответ получен, окна ошибки нет, следующее исполнение проходит."""
    # Запись 09: Request закрывала себя уже закрытой — окно ошибки «1С:Предприятие», всё после — target_not_interactive.
    before = recorded.direct(recorded.RESTORE_OWNER_CLOSED)
    first = next(r for r in before if r['action'] == 'execute_code')
    assert first['arguments'] == {'context': 'client', 'parameters': {'part': 'ИнформацияПриЗапуске'}}
    assert first['response']['code'] == 'target_not_interactive'
    rest = before[before.index(first) + 1:]
    assert next(r for r in rest if r['action'] == 'get_active_window')['response']['title'] == '1С:Предприятие'
    assert {r['response']['code'] for r in rest if r['action'] == 'execute_code'} == {'target_not_interactive'}
    # Запись 10 (Request закрывается, только если ещё открыта): ответ 1, рабочего окна нет, следующее исполнение — ок.
    closed = live('startup', 'execute_code')
    assert closed['args'] == {'context': 'client', 'parameters': {'part': 'ИнформацияПриЗапуске'}}
    assert {k: closed['result'][k] for k in ('ok', 'result')} == {'ok': True, 'result': 1}
    assert titles('startup') == ['Информация', None]
    assert {k: live('startup', 'execute_code', 1)['result'][k] for k in ('ok', 'result')} == {'ok': True, 'result': 'Администрация'}
    # Код ветки: владелец закрыт кодом, Request закрылась вместе с ним, ответ читается из Helper; следующее
    # исполнение — без рабочего окна, над обработкой.
    client = client_at(H.LIVE_INFO)
    result = H.execute(client, mode='code', context='client', code=H.CLOSE_OWNER_CODE,
                       parameters={'part': 'ИнформацияПриЗапуске'})
    assert result['ok'] and result['result'] == 1
    assert H.payload(client.inputs[0])['parameters'] == {'part': 'ИнформацияПриЗапуске'}
    assert H.frames(client, G.CLICK) == [('OpenRequest', 'action'), ('OpenRequest', 'commit'),
                                         ('RunClient', 'action'), ('RunClient', 'commit')]
    assert client.closes == [] and client.active is None and client._request_windows == set()
    second = H.execute(client, mode='code', context='server', code=H.DEPT_CODE)
    assert second['ok'] and second['result'] == 'Администрация'
    assert client.history == [H.LIVE_INFO['key'], REQUEST['key'], None, REQUEST['key'], None]
    assert client.activated == [] and client.facts.helper_window not in client.history


def test_query_after_form_actions_keeps_the_form_active():
    """Сценарий «Запрос после действий с формой» (запись 10, work_form): при активной АРМ execute_code — в команде
    активна Request; execute_query — записанный ответ (columns, rows, returned_rows, limit, truncated); после
    каждого ответа активна АРМ (по три опроса)."""
    client = client_at(H.LIVE_ARM)
    code = H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert code['result'] == H.REQUEST == live('work_form', 'execute_code')['result']['result']
    query = H.execute(client, mode='query', context='server', query=H.QUERY)
    recorded_query = live('work_form', 'execute_query')['result']
    assert query['ok'] and query['result'] == H.QUERY_RESULT == {k: recorded_query[k] for k in H.QUERY_RESULT}
    assert recorded_query['columns'] == ['А'] and recorded_query['rows'] == [{'А': 1}]
    assert titles('work_form') == [H.ARM] * 4
    assert client.history == [H.LIVE_ARM['key'], REQUEST['key'], H.LIVE_ARM['key'], REQUEST['key'], H.LIVE_ARM['key']]
    assert client.reads[-1] == f'{client.facts.helper_window}.ManagedForm[{client.facts.helper_form}].EditField[ServerResult]'
    assert client.activated == []


def test_form_opened_by_code_stays_active_and_helper_does_not_take_over_after_it_closes():
    """Сценарий «Код открывает форму» (запись 10, open_form): после ответа активна открытая форма списка; после её
    close_window активна АРМ — окно обработки не получает активность и после закрытия этой формы (записи 02, 03:
    активизированный Helper забирал бы её)."""
    client = client_at(H.LIVE_ARM)
    client.list_window = H.LIVE_LIST['key']
    result = H.execute(client, mode='code', context='client', code=H.OPEN_FORM_TRUE_CODE)
    assert result['result'] is True and live('open_form', 'execute_code')['result']['result'] is True
    assert client.active == H.LIVE_LIST['key'] and client.owner == H.LIVE_ARM['key']
    closed = live('open_form', 'close_window')['result']
    assert {k: v for k, v in closed.items() if k != 'connection_id'} == {'ok': True, 'closed': H.LIVE_LIST['key']}
    assert titles('open_form') == ['Подразделения'] * 3 + [H.ARM] * 3
    assert client.close(key=H.LIVE_LIST['key']) == {'ok': True, 'closed': H.LIVE_LIST['key']}
    assert client.active == H.LIVE_ARM['key'] and client.facts.helper_window not in client.history


def test_choice_form_from_cell_with_public_tools():
    """Сценарий «Форма выбора из ячейки табличного документа» публичными инструментами (запись 10, choice_from_cell):
    read_rows и find_rows в форме выбора оставляют её активной, после choose_row — АРМ (пять опросов), в ячейке
    «Администрация»; исполнение перед поиском — без ACTIVATE, форма выбора остаётся активной."""
    assert titles('choice_from_cell') == ['Подразделения'] * 3 + [H.ARM] * 5
    read = live('choice_from_cell', 'read_rows')['result']
    assert read['ok'] and read['rows'][0]['Наименование'] == 'Администрация'
    found = live('choice_from_cell', 'find_rows')['result']
    assert found['ok'] and found['target'] == read['target'] and found['scope'] == 'current_table'
    chosen = live('choice_from_cell', 'choose_row')['result']
    assert chosen['observed'] == {'kind': 'active_window'}
    assert chosen['value_before'] == H.LIVE_CHOICE['key'] and chosen['value_after'] == H.LIVE_ARM['key']
    assert live('choice_from_cell', 'get_area_text')['result']['text'] == 'Администрация'
    client = client_at(H.LIVE_CHOICE)
    assert H.execute(client, mode='code', context='client', code=H.CHILD_CODE)['ok']
    assert client.history == [H.LIVE_CHOICE['key'], REQUEST['key'], H.LIVE_CHOICE['key']] and client.activated == []


@pytest.mark.parametrize('step', ['question', 'error'])
def test_modal_windows_of_the_live_check_left_no_trace(step):
    """Запись 10, шаги question и error: после ответа на вопрос и закрытия окна ошибки код «Результат = 2;» выполняется,
    активна АРМ, окно обработки не получало активность; итог проверки — ответ «Нет» (end)."""
    assert H.calls(LIVE, 'execute_code', step)[-1]['result']['result'] == 2
    assert titles(step)[1:] == [H.ARM] * 6
    assert live('end', 'execute_code')['result']['result'] == 'Нет'
    children = live('end', 'get_child_objects')['result']['children']
    assert [c['title'] for c in children][:1] == [H.ARM] and not any('Testpilot' in c['title'] for c in children)
