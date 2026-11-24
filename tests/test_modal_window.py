"""Требование «Исполнение при модальном окне» и задача 4.7 матрицы — записи спайка testpilot-helper-restore
(spike:spk_cff9b4db89@v3):
  docs/spikes/testpilot-helper-restore/recording/07-modal.jsonl — протокол: при вопросе и окне ошибки клиент отклоняет
    CLICK по кнопке Helper (OperationError, статус 9 target_not_interactive), Request не открывается; прежний
    execute_code получал тот же отказ; после answer_dialog / close_window активна рабочая форма АРМ
  docs/spikes/testpilot-helper-restore/recording/10-live-check.jsonl — публичные инструменты кода ветки: execute_code и
    execute_query при вопросе и окне ошибки падали с TypeError (Failure с именованным message); после исправления
    отказ — Failure modal_window_open с подсказкой answer_dialog, после ответа и закрытия — исполнение, активна АРМ
Клиент — _helper_client.Client (modal=True отклоняет CLICK записанным отказом).
"""
import pytest

import _code_execution as E
import _helper_client as H
import _recording as recorded
import guids as G
import tc1c

HINT = 'Answer it with answer_dialog, or read it with get_current_error and close it with close_window, then retry.'
REFUSAL = {'ok': False, 'code': 'modal_window_open', 'suggested_action': 'answer_dialog'}
TYPE_ERROR = {'ok': False, 'exception': "TypeError(\"Failure.__init__() got multiple values for argument 'message'\")"}


def client_at(window, work):
    """Клиент с открытым модальным окном window поверх рабочей формы work; окно Request и прочие — из записи 05."""
    client = H.Client(H.PROTOCOL, active=window['key'], owner=work['key'], modal=True)
    client.show(window)
    client.show(work)
    for _, recorded_window in H.PROTOCOL.windows:
        client.show(recorded_window)
    return client


def refused(client, **arguments):
    """Отказ — Failure (не TypeError записи 10) с кодом и подсказкой; вызов отправил только действие OpenRequest
    (без фиксации, ввода, запуска и чтения ответа) и ничего не оставил: ожидающего запроса и открытой Request нет."""
    sent = len(client.frames)
    with pytest.raises(E.Failure) as info:
        H.execute(client, **arguments)
    assert {k: info.value.result.get(k) for k in REFUSAL} == REFUSAL   # код и подсказка — требование
    assert all(word in info.value.result['error'] for word in ('answer_dialog', 'get_current_error', 'close_window'))
    open_request = f'{client.facts.helper_window}.ManagedForm[{client.facts.helper_form}].Button[OpenRequest]'
    assert client.frames[sent:] == [(G.CLICK, open_request, 'action')]
    assert client.inputs == [] and client.active != client.facts.request_window
    assert client._service_pending is None and client._request_windows == set()
    assert client.reads == [f'{client.facts.helper_window}.ManagedForm[{client.facts.helper_form}].EditField[{n}]'
                            for n in ('ClientResult', 'ServerResult', 'ServiceInfo')]   # только поиск обработки


def test_question_window_refuses_code_with_answer_dialog_hint():
    """4.7, сценарий «Открыт вопрос» (запись 07): поверх рабочей формы вопрос «Да/Нет» — execute_code отказывает
    modal_window_open с подсказкой answer_dialog; после answer_dialog тот же execute_code выполняется, активна АРМ."""
    new_path = recorded.rows(recorded.RESTORE_MODAL, kind='call', step='question_new')
    question = next(r for r in new_path if r['action'] == 'answer_dialog')
    assert question['args'] == {'answer': 'Нет'}
    assert {k: v for k, v in question['result'].items() if k != 'dialog'} == {
        'ok': True, 'answered': 'Нет', 'question': 'Спайк: вопрос?', 'connection_id': 'c1662d899933e4038'}
    assert question['result']['dialog']['buttons'][:2] == ['Да', 'Нет']
    client = client_at(H.MODAL_QUESTION, H.MODAL_ARM)
    refused(client, mode='code', context='client', code=H.CHILD_CODE)
    polls = [recorded.window(r)['key'] for r in new_path if r['action'] == 'get_active_window']
    assert polls == [H.MODAL_QUESTION['key']] * 11 + [H.MODAL_ARM['key']] * 5   # до и после отказа — вопрос, после ответа — АРМ
    client.active = H.MODAL_ARM['key']               # после ответа на вопрос платформа вернула активность АРМ
    client.modal = False
    result = H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert result['ok'] and result['result'] == H.REQUEST and client.active == H.MODAL_ARM['key']
    assert H.frames(client, G.CLICK) == [('OpenRequest', 'action'), ('OpenRequest', 'action'), ('OpenRequest', 'commit'),
                                         ('RunClient', 'action'), ('RunClient', 'commit')]


def test_error_window_refuses_query_and_close_window_then_query_runs():
    """4.7, сценарий «Окно ошибки» (запись 07): открыто окно ошибки 1С — execute_query отказывает modal_window_open;
    после close_window запрос выполняется, активна АРМ."""
    error = H.calls(recorded.RESTORE_MODAL, 'get_current_error', 'error_new')[0]
    assert error['result']['error'] == '{ВнешняяОбработка.Testpilot.Форма.Helper.Форма(1251)}: Спайк: ошибка'
    closed = H.calls(recorded.RESTORE_MODAL, 'close_window', 'error_new')[0]
    assert {k: v for k, v in closed['result'].items() if k != 'connection_id'} == {'ok': True, 'closed': H.MODAL_ERROR['key']}
    client = client_at(H.MODAL_ERROR, H.MODAL_ARM)
    refused(client, mode='query', context='server', query=H.QUERY)
    client.active = H.MODAL_ARM['key']               # окно ошибки закрыто
    client.modal = False
    result = H.execute(client, mode='query', context='server', query=H.QUERY)
    assert result['ok'] and result['result'] == H.QUERY_RESULT and client.active == H.MODAL_ARM['key']
    assert H.frames(client, G.CLICK)[1:] == [('OpenRequest', 'action'), ('OpenRequest', 'commit'),
                                             ('RunServer', 'action'), ('RunServer', 'commit')]


def test_recorded_protocol_refusal_is_status_9_as_the_former_path_got():
    """Запись 07: отказ клиента на CLICK по кнопке Helper — OperationError, статус 9 (target_not_interactive);
    прежний execute_code (через ACTIVATE) отвечал тем же кодом без подсказки, новый путь даёт modal_window_open."""
    refusal = H.raw(recorded.RESTORE_MODAL, step='question_new')[0]
    assert refusal['button'] == 'RunServer' and refusal['input'] is False
    assert refusal['result'] == {'ok': False, 'exception': f"OperationError({str(tc1c.OperationError(9, 'k'))!r})"}
    assert tc1c.OperationError(9, 'k').result() == {
        'ok': False, 'target': 'k', 'code': 'target_not_interactive', 'error': str(tc1c.OperationError(9, 'k')),
        'status_code': 9}
    old = H.calls(recorded.RESTORE_MODAL, 'execute_code', 'error_old')[1]['result']
    assert old['code'] == 'target_not_interactive' and old['error'] == str(tc1c.OperationError(9, 'k'))
    assert old['status_code'] == 9 and 'suggested_action' not in old
    assert H.raw(recorded.RESTORE_MODAL, step='error_new')[0]['result'] == refusal['result']   # окно ошибки — то же


@pytest.mark.parametrize('step, window, resolve', [('question', 'LIVE_QUESTION', 'answer_dialog'),
                                                   ('error', 'LIVE_ERROR', 'close_window')])
def test_live_check_modal_refusal_is_failure_not_typeerror(step, window, resolve):
    """Запись 10, шаги question и error: execute_code и execute_query публичными инструментами падали с TypeError
    (Failure с message=); код ветки отказывает Failure modal_window_open с кодом и подсказкой answer_dialog,
    после answer_dialog («Нет») / close_window исполнение проходит, активна АРМ."""
    window = getattr(H, window)
    calls = recorded.rows(recorded.RESTORE_LIVE, kind='call', step=step)
    failed = [r['result'] for r in calls
              if r['action'] in ('execute_code', 'execute_query') and r['result'].get('exception')]
    assert failed == [TYPE_ERROR, TYPE_ERROR]
    resolved = H.calls(recorded.RESTORE_LIVE, resolve, step)[0]['result']
    assert resolved['ok'] and resolved[{'answer_dialog': 'answered', 'close_window': 'closed'}[resolve]] == \
        {'answer_dialog': 'Нет', 'close_window': window['key']}[resolve]
    polls = [recorded.window(r) for r in H.calls(recorded.RESTORE_LIVE, 'get_active_window', step)]
    assert polls[0]['key'] == window['key'] and [p['key'] for p in polls[1:]] == [H.LIVE_ARM['key']] * 6
    assert H.calls(recorded.RESTORE_LIVE, 'execute_code', step)[-1]['result']['result'] == 2
    client = client_at(window, H.LIVE_ARM)
    refused(client, mode='code', context='client', code='Результат = 1;')
    refused(client, mode='query', context='server', query=H.QUERY)
    client.active = H.LIVE_ARM['key']
    client.modal = False
    assert H.execute(client, mode='code', context='client', code='Результат = 2;')['result'] == 2
    assert client.active == H.LIVE_ARM['key'] and client.activated == []
