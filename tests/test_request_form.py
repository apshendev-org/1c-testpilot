"""Изменение helper-request-form: исполнение через форму Request без активизации Helper — задачи 4.1–4.6
матрицы tests и сценарии требования «Исполнение не меняет активное окно» (specs/code-execution/spec.md).

Записи спайка testpilot-helper-restore (spike:spk_cff9b4db89@v3):
  docs/spikes/testpilot-helper-restore/recording/05-protocol-only.jsonl — весь путь протоколом над формой выбора
  docs/spikes/testpilot-helper-restore/recording/06-read-result.jsonl — ответ читается из поля неактивного Helper
  docs/spikes/testpilot-helper-restore/recording/08-open-form.jsonl — код в Request открывает форму списка
Сценарий «Запрос после действий с формой» с записанным ответом запроса и старт — test_live_check (запись 10).
Клиент — _helper_client.Client: кадры и ответы по записям, состав форм — по исходникам обработки (_forms.py).
"""
import json

import pytest

import _code_execution as E
import _helper_client as H
import _recording as recorded
import guids as G
import server as R

PROTOCOL, READ_RESULT, OPEN_FORM = H.PROTOCOL, H.READ_RESULT, H.OPEN_FORM
CHOICE = PROTOCOL.window('choice_from_cell', H.CHOICE)        # «Подразделения» — форма выбора из ячейки R3C9
ARM = PROTOCOL.window('child_after', H.ARM)                   # «АРМ контрактной службы (макет)» — рабочая форма
REQUEST = PROTOCOL.window('child_open', H.REQUEST)            # «Testpilot: запрос: Request'
HELPER = {'key': PROTOCOL.helper_window, 'title': H.HELPER_TITLE}


def client_for(facts=PROTOCOL, active=CHOICE):
    client = H.Client(facts, active=active['key'] if active else None)
    if active:
        client.show(active)
    for _, window in facts.windows:
        client.show(window)
    return client


def helper_field(client, name):
    return f'{client.facts.helper_window}.ManagedForm[{client.facts.helper_form}].EditField[{name}]'


def clicks(client):
    return H.frames(client, G.CLICK)


def test_protocol_path_opens_request_runs_and_reads_helper_without_activate():
    """4.1: OpenRequest (действие и фиксация) → ввод JSON-запроса в поле Request → RunClient (действие и фиксация)
    → чтение ClientResult Helper; окно Request открылось к первому опросу, ни одного ACTIVATE."""
    client = client_for()
    result = H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    # Запись 05, код спайка: «активно в команде=Testpilot: запрос: Request» — в команде активно окно Request.
    assert result == dict(request_id=result['request_id'], ok=True, result='Testpilot: запрос: Request')
    assert clicks(client) == [('OpenRequest', 'action'), ('OpenRequest', 'commit'),
                              ('RunClient', 'action'), ('RunClient', 'commit')]
    assert [guid for guid, _, _ in client.frames] == [G.CLICK] * 4 and client.activated == []
    # Один ввод — конверт продукта (protocol 1, идентификатор запроса, режим и контекст); код — как в записи
    # (len 48 — <pre> с кодом спайка).
    request = H.payload(client.inputs[0])
    assert request == dict(protocol=1, request_id=result['request_id'], mode='code', context='client',
                           code=H.CHILD_CODE, query=None, parameters={}, limit=100)
    assert PROTOCOL.input['len'] == len('<pre>' + H.CHILD_CODE + '</pre>') == 48
    # Чтения: три поля Helper при поиске обработки (ClientResult, ServerResult, ServiceInfo), затем ответ.
    assert client.reads == [helper_field(client, n) for n in ('ClientResult', 'ServerResult', 'ServiceInfo', 'ClientResult')]
    # Активное окно: форма выбора → Request (запись child_open) → форма выбора после «Выполнить» (запись child_run).
    assert client.history == [CHOICE['key'], REQUEST['key'], CHOICE['key']] and client.closes == []


def test_read_from_inactive_helper_keeps_the_choice_form_active():
    """4.1, чтение ответа (запись 06, restore-5): ответ читается из поля Helper, который не был активен;
    после чтения активна форма выбора — «Подразделения» (запись child_run)."""
    client = client_for(READ_RESULT, READ_RESULT.window('choice_from_cell', H.CHOICE))
    result = H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert result['result'] == 'Testpilot: запрос: Request'
    assert READ_RESULT.read['presentation'].startswith(
        'ok: Testpilot: запрос: Request; активно в команде=Testpilot: запрос: Request; после Закрыть=Подразделения')
    assert client.reads[-1] == helper_field(client, 'ClientResult')
    assert client.history == [READ_RESULT.window('choice_from_cell', H.CHOICE)['key'],
                              READ_RESULT.window('child_open', H.REQUEST)['key'],
                              READ_RESULT.window('choice_from_cell', H.CHOICE)['key']]
    assert READ_RESULT.helper_window not in client.history and client.activated == []


def test_choice_form_stays_active_after_execution_and_after_choose_row():
    """4.2, сценарий «Форма выбора из ячейки табличного документа» (запись 05): форма выбора активна до и после
    исполнения; после choose_row в ячейке выбранное значение и активна форма с табличным документом, а не
    no_active_work_window; следующий код тоже не меняет активное окно."""
    client = client_for()
    assert client.window() == CHOICE                      # запись choice_from_cell: активна «Подразделения»
    first = H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert first['ok'] and client.active == CHOICE['key']  # запись child_run: после «Выполнить» — «Подразделения»
    chosen = H.calls(recorded.RESTORE_PROTOCOL, 'choose_row', 'child_after')[0]
    assert chosen['result']['value_before'] == CHOICE['key'] and chosen['result']['value_after'] == ARM['key']
    client.active = ARM['key']                             # платформа закрыла форму выбора, значение — в ячейке
    second = H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert second['ok'] and client.active == ARM['key']    # запись child_after: пять опросов — АРМ
    assert [w.get('title') for s, w in PROTOCOL.windows if s == 'child_after'] == [H.ARM] * 5
    cell = H.calls(recorded.RESTORE_PROTOCOL, 'get_area_text', 'child_after')[0]
    assert cell['args']['area'] == 'R3C9' and cell['result']['text'] == 'Администрация'   # выбранное значение в ячейке
    assert client.window()['title'] == H.ARM and 'code' not in client.window()
    assert client.history == [CHOICE['key'], REQUEST['key'], CHOICE['key'], ARM['key'], REQUEST['key'], ARM['key']]
    assert client.activated == []


def test_code_opening_form_leaves_the_opened_form_active():
    """Сценарий «Код открывает форму» (запись 08, restore-7): после ответа активна открытая форма списка
    «Подразделения», а не форма-владелец АРМ; Helper не получал активность."""
    opened = OPEN_FORM.window('open_form', 'Подразделения')
    assert opened['url'] == 'e1cib/list/Справочник.Подразделения'   # форма списка, открытая кодом
    client = client_for(OPEN_FORM, OPEN_FORM.window('open_form', H.ARM))
    client.list_window = opened['key']
    result = H.execute(client, mode='code', context='client', code=H.OPEN_FORM_CODE)
    assert result['result'] == 'Подразделения'          # запись: «ok: Подразделения; … после Закрыть=Подразделения»
    assert OPEN_FORM.read['presentation'].startswith(
        'ok: Подразделения; активно в команде=Testpilot: запрос: Request; после кода=Подразделения; '
        'после Закрыть=Подразделения; после Активизировать окна кода=Подразделения')
    assert OPEN_FORM.input['len'] == len('<pre>' + H.OPEN_FORM_CODE + '</pre>') == 102
    # Запись: АРМ → Request → форма списка (11 опросов после ответа — «Подразделения»).
    assert [w.get('title') for s, w in OPEN_FORM.windows if s == 'open_form'] == [H.ARM, H.REQUEST] + ['Подразделения'] * 10
    assert client.history == [OPEN_FORM.window('open_form', H.ARM)['key'], OPEN_FORM.window('open_form', H.REQUEST)['key'],
                              opened['key']]
    assert OPEN_FORM.helper_window not in client.history and client.activated == []


@pytest.mark.parametrize('active, root', [(HELPER, PROTOCOL.helper_window), (None, None)],
                         ids=['окно обработки', 'нет активного окна'])
def test_no_work_window_opens_request_over_helper(active, root):
    """4.3, сценарий «Нет рабочего окна» (старт записи 05 — для агента no_active_work_window): активно только
    окно обработки или активного окна нет — запрос выполняется, форма запроса открывается над обработкой
    (владелец без активного окна — Helper, ОткрытьЗапрос в Module.bsl) и после ответа активна обработка."""
    assert H.NO_WORK['code'] == 'no_active_work_window' and H.NO_WORK['key'] is None
    client = client_for(active=active)
    result = H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert result['ok'] and result['result'] == H.REQUEST
    assert clicks(client) == [('OpenRequest', 'action'), ('OpenRequest', 'commit'),
                              ('RunClient', 'action'), ('RunClient', 'commit')]
    assert client.history == [root, REQUEST['key'], root]
    assert client.closes == [] and client.activated == []


def test_old_helper_structure_is_version_mismatch():
    """4.4, сценарий «Старая обработка»: обработка прежней структуры — поля запроса ClientRequest/ServerRequest
    на Helper и кнопки RunClient/RunServer (запись 05: Request спайка — копия прежнего Helper) —
    execute_code отвечает ok: false, code: helper_version_mismatch, ничего не отправив."""
    client = client_for()
    window, form = next(o for o in client.helper_objects if o['class'] == 'SecondaryFrame'), \
        next(o for o in client.helper_objects if o['class'] == 'ManagedForm')
    old_items = [dict(o, key=f"{PROTOCOL.helper_window}.ManagedForm[{PROTOCOL.helper_form}]."
                        f"{o['class']}[{o['name']}]") for o in PROTOCOL.request_objects if o['class'] != 'ManagedForm']
    assert {'ClientRequest', 'ServerRequest', 'RunClient', 'RunServer'} <= {o['name'] for o in old_items}
    assert 'OpenRequest' not in {o['name'] for o in old_items}
    client.helper_objects = [window, form] + old_items
    with pytest.raises(E.Failure) as info:
        H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert info.value.result['code'] == 'helper_version_mismatch' and info.value.result['ok'] is False
    assert client.frames == [] and client.inputs == [] and client.reads == []


def test_old_request_form_structure_is_version_mismatch_and_leftover_form_is_closed():
    """4.4: обработка с формой Request прежней структуры (запись 05: Request — копия Helper с полем ClientRequest,
    без поля Request) — helper_version_mismatch после открытия формы, без ввода и запуска; оставшаяся форма
    следующий вызов закрывает, прежде чем открыть новую."""
    client = client_for()
    client.request_objects = list(PROTOCOL.request_objects)     # объекты Request из записи спайка как есть
    with pytest.raises(E.Failure) as info:
        H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert info.value.result['code'] == 'helper_version_mismatch'
    assert clicks(client) == [('OpenRequest', 'action'), ('OpenRequest', 'commit')]
    assert client.inputs == [] and client._service_pending is None and client.active == REQUEST['key']
    with pytest.raises(E.Failure) as info:
        H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert info.value.result['code'] == 'helper_version_mismatch'
    assert client.closes == [REQUEST['key']] and client.inputs == []


def test_stalled_execution_result_is_drained_and_request_form_closed_before_new_request():
    """4.5, сценарий «Срок истёк», результат пришёл позже: исполнение истекло при открытой форме запроса; следующий
    execute_query читает прежний результат (previous_result), закрывает оставшуюся форму и выполняется."""
    client = client_for()
    client.stall = True                                     # «Выполнить» не ответило к сроку: исполнение идёт
    with pytest.raises(E.Failure) as info:
        H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert info.value.result['code'] == 'execution_timeout' and info.value.result['may_be_running'] is True
    request_id = client.text['request_id']
    assert client.active == REQUEST['key'] and client._request_windows == {REQUEST['key']}
    # Исполнение завершилось после срока: Helper записал ответ в своё поле, форма Request осталась открытой.
    drained = dict(protocol=1, request_id=request_id, ok=True, result=H.REQUEST)
    client.results['ClientResult'] = json.dumps(drained)
    client.stall = False
    result = H.execute(client, mode='query', context='server', query=H.QUERY)
    assert result['ok'] and result['result'] == H.QUERY_RESULT and result['previous_result'] == drained
    assert client.closes == [REQUEST['key']]                # оставшаяся форма закрыта до нового запроса
    assert clicks(client)[4:6] == [('OpenRequest', 'action'), ('OpenRequest', 'commit')]   # первый вызов — 4 кадра
    assert client.active == CHOICE['key'] and client._service_pending is None


def test_interrupted_request_form_is_closed_before_new_request():
    """4.5, обрыв связи на вводе (форма Request открыта, запроса не было): следующее исполнение закрывает её и
    выполняется; после ответа активна форма-владелец."""
    client = client_for()
    client.break_input = True
    with pytest.raises(E.Failure) as info:
        H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert info.value.result['code'] == 'execution_timeout' and info.value.result['may_be_running'] is False
    assert client.active == REQUEST['key']
    client.break_input = False
    result = H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert result['ok'] and client.closes == [REQUEST['key']] and len(client.inputs) == 1
    assert clicks(client)[2:4] == [('OpenRequest', 'action'), ('OpenRequest', 'commit')]
    assert client.active == CHOICE['key'] and client._service_pending is None


def test_stalled_execution_without_result_is_closed_before_new_request():
    """4.5: срок истёк, результата нет — следующее исполнение закрывает оставшуюся форму запроса и выполняет новый
    запрос; оставшаяся форма не блокирует рабочее окно ожидающим запросом."""
    client = client_for()
    client.stall = True
    with pytest.raises(E.Failure) as info:
        H.execute(client, mode='code', context='client', code=H.CHILD_CODE)
    assert info.value.result['code'] == 'execution_timeout'
    client.stall = False
    result = H.execute(client, mode='query', context='server', query=H.QUERY)
    assert result['ok'] and client.closes == [REQUEST['key']] and client.active == CHOICE['key']


def test_request_form_is_hidden_from_agents_and_is_not_a_work_window(monkeypatch):
    """4.6: окна Helper и Request не попадают в объекты агентских поисков (filter_objects) и guard отказывает
    по их ключам (service_form_protected); активное окно Request — не рабочее окно (_runtime._window отвечает
    no_active_work_window); внутренний доступ исполнению открыт."""
    client = client_for()
    client.opened[REQUEST['key']] = client.request_objects
    everything = client.search(H.ROOT)
    assert [o['name'] for o in everything if o.get('form_name') in E.FORM_NAMES] == [PROTOCOL.helper_form, PROTOCOL.request_form]
    assert E.filter_objects(client, everything) == []
    assert client._service_roots == {PROTOCOL.helper_window, PROTOCOL.request_window}
    for key in (REQUEST['key'], f'{REQUEST["key"]}.ManagedForm[{PROTOCOL.request_form}].Button[RunClient]'):
        with pytest.raises(E.Failure) as info:
            E.guard(client, 'find_objects', key)
        assert info.value.result['code'] == 'service_form_protected'
        with E.internal(client):
            assert E.guard(client, 'find_objects', key) is None
    with E.internal(client):
        assert E.filter_objects(client, everything) == everything
    # Рабочее окно: _runtime._window по активному окну Request отвечает no_active_work_window.
    monkeypatch.setattr(R, '_state', {'window_key': 'stale'})
    client.active = REQUEST['key']
    monkeypatch.setattr(R.tc1c, 'extract_object_keys', lambda raw: [raw] if raw else [])
    monkeypatch.setattr(R.tc1c, 'decode_collection', lambda raw: [{'key': raw, 'title': client.windows[raw]['title']}] if raw else [])
    assert R._window(client) == H.NO_WORK and R._state['window_key'] is None
    client.active = CHOICE['key']
    assert R._window(client)['key'] == CHOICE['key'] == R._state['window_key']
