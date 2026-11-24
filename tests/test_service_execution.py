"""Служебная форма Testpilot на заглушке без записей спайка: подготовка при старте (prepare) с окнами, отказывающими
в активации, и незавершённый запрос с прежним результатом (задача 4.5). Состав обработки — по исходникам (_forms.py),
ключи окон Helper и Request — записи 05; запись старта — slow-start.jsonl (окно «Новости» у админа). Остальное —
test_request_form, test_modal_window, test_live_check.
"""
import json
import time

import pytest

import _code_execution as E
import _helper_client as H

MAIN = 'MainFrame[m]'                                   # главное окно приложения
NEWS = 'SecondaryFrame[n]'                              # «Новости» у админа при старте
NEWS_FORM = NEWS + '.ManagedForm[n]'
ARM = H.PROTOCOL.window('child_after', H.ARM)


def startup_client(active=None, refuse=()):
    """Клиент с обработкой Testpilot (запись 05) и окнами приложения: главное и «Новости» (отказ активации — refuse)."""
    client = H.Client(H.PROTOCOL, active=active['key'] if active else None)
    for _, window in H.PROTOCOL.windows:
        client.show(window)
    client.show({'key': MAIN, 'title': 'DEV / Бухгалтерия государственного учреждения, редакция 2.0'})
    client.show({'key': NEWS, 'title': 'Начальная страница'})
    client.open_objects(MAIN, [dict(key=MAIN, name='m', handle='hm', **{'class': 'MainFrame'}, type=None,
                                    title='Главное окно', form_name=None)])
    client.open_objects(NEWS, [dict(key=NEWS_FORM, name='n', handle='hn', **{'class': 'ManagedForm'}, type=None,
                                    title='Новости', form_name='Обработка.Новости.Форма')])
    client.refuse_activation = set(refuse)
    return client


def test_startup_window_refusing_activation_is_bypassed():
    # У админа при старте открыты «Новости»: форма отказывает в активации, главное окно — нет.
    client = startup_client(refuse={NEWS_FORM})
    E.prepare(H.runtime(client), client, 'Testpilot.epf', time.monotonic() + 2)
    assert client.activated == [MAIN] and client.active == MAIN
    assert [(key, kind) for _, key, kind in client.frames] == [(NEWS_FORM, 'action'), (MAIN, 'action'), (MAIN, 'commit')]
    assert client.reads == [f'{H.PROTOCOL.helper_window}.ManagedForm[{H.PROTOCOL.helper_form}].EditField[{n}]'
                            for n in ('ClientResult', 'ServerResult', 'ServiceInfo')]


def test_startup_activation_refused_everywhere_is_retried_until_deadline():
    client = startup_client(refuse={MAIN, NEWS_FORM})
    started = time.monotonic()
    with pytest.raises(E.Failure) as error:
        E.prepare(H.runtime(client), client, 'Testpilot.epf', time.monotonic() + 0.5)
    assert error.value.result['code'] == 'helper_not_ready' and time.monotonic() - started >= 0.4
    assert error.value.result['last_error']['code'] == 'target_not_interactive'
    assert client.activated == []                       # ни одно окно не принято
    assert {key for _, key, _ in client.frames} == {MAIN, NEWS_FORM} and len(client.frames) >= 4   # повтор до срока


def test_new_request_runs_after_previous_completed():
    client = startup_client(active=ARM)
    button = next(o for o in client.request_objects if o.get('name') == 'RunServer')
    client._service_pending = dict(request_id='old', field='ServerResult', mode='code', button=button)
    client.results['ServerResult'] = json.dumps({'protocol': 1, 'request_id': 'old', 'ok': True, 'result': 'прежний'})
    result = H.execute(client, mode='code', context='server', code=H.DEPT_CODE)
    assert result['ok'] and result['result'] == 'Администрация'
    assert result['previous_result'] == {'protocol': 1, 'request_id': 'old', 'ok': True, 'result': 'прежний'}
    assert client._service_pending is None and H.payload(client.inputs[0])['request_id'] == result['request_id']
    assert client.active == ARM['key'] and client.activated == []
