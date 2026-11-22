import html as markup
import json
import os
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _code_execution as E  # noqa: E402
import guids as G  # noqa: E402

MAIN = 'MainFrame[m]'
HELPER = 'SecondaryFrame[s]'
SERVICE = HELPER + '.ManagedForm[s]'
WORK = 'SecondaryFrame[w]'
NEWS = 'SecondaryFrame[n]'


class Client:
    """1C client stub with the Testpilot form in its own window: fields accept input only while
    their window is active; Run* commit executes the stored request."""

    def __init__(self, active=HELPER, refuse_activation=()):
        self.active, self.refuse = active, set(refuse_activation)
        self.request, self.results, self.executed, self.activated = None, {}, [], []

    def send_cmd(self, guid, key, kind='read', middle=b'', handle=None, **kw):
        if guid == G.ACTIVATE:
            if key in self.refuse:
                return dict(ok=False, code='target_not_interactive', error='refused')
            if kind == 'commit':
                self.activated.append(key)
                self.active = key.split('.ManagedForm[', 1)[0]
            return dict(ok=True)
        if guid == G.CLICK and kind == 'commit':
            request = json.loads(self.request)
            self.executed.append(request['code'])
            field = 'ClientResult' if key.endswith('[RunClient]') else 'ServerResult'
            self.results[field] = dict(protocol=1, ok=True, request_id=request['request_id'], result=request['code'])
        return dict(ok=True)


def runtime(client, extra=()):
    names = ('ClientRequest', 'ClientResult', 'RunClient', 'ServerRequest', 'ServerResult', 'RunServer')
    objects = [dict(key=SERVICE, form_name=E.FORM_NAME, handle='hs', **{'class': 'ManagedForm'})]
    objects += [dict(key=f'{SERVICE}.Field[{n}]', name=n, handle=n, **{'class': 'Field'}) for n in names]
    objects += list(extra)

    def presentation(key, handle):
        result = client.results.get(handle, dict(protocol=1, ok=True, request_id=''))
        return dict(ok=True, presentation=json.dumps(result))

    def input_html(key, handle, html):
        if client.active != HELPER:
            return dict(ok=False, code='target_not_interactive', error='inactive window')
        client.request = markup.unescape(html.removeprefix('<pre>').removesuffix('</pre>'))
        return dict(ok=True)

    return SimpleNamespace(_APPLICATION_ROOT=None, _state={}, _search_objects=lambda c, root: objects,
                           _window=lambda c: dict(key=client.active), tc_get_data_presentation=presentation,
                           tc_input_html=input_html)


def execute(client, code='Результат = 1;'):
    return E.execute(runtime(client), client, mode='code', context='server', code=code,
                     timeout=5, check_permissions=False)


def test_query_while_work_window_is_active_restores_it():
    client = Client(active=WORK)
    result = execute(client)
    assert result['ok'] and result['result'] == 'Результат = 1;'
    assert client.activated == [SERVICE, WORK] and client.active == WORK


def test_service_window_already_active_is_not_switched():
    client = Client()
    assert execute(client)['ok'] and client.activated == []


def test_new_request_runs_after_previous_completed():
    client = Client()
    client._service_pending = dict(request_id='old', field='ServerResult', mode='code')
    client.results['ServerResult'] = dict(protocol=1, ok=True, request_id='old', result='прежний')
    result = execute(client, 'Константы.Х.Установить(1);')
    assert result['ok'] and client.executed == ['Константы.Х.Установить(1);']
    assert result['previous_result']['result'] == 'прежний' and client._service_pending is None


def test_startup_window_refusing_activation_is_bypassed():
    # У админа при старте открыты «Новости»: форма отказывает в активации, главное окно — нет.
    client = Client(refuse_activation={NEWS + '.ManagedForm[n]'})
    news = dict(key=NEWS + '.ManagedForm[n]', form_name='Обработка.Новости.Форма', handle='hn', **{'class': 'ManagedForm'})
    E.prepare(runtime(client, [news, dict(key=MAIN, **{'class': 'MainFrame'})]), client, 'Testpilot.epf',
              time.monotonic() + 2)
    assert client.activated == [MAIN]


def test_startup_activation_refused_everywhere_is_retried_until_deadline():
    client = Client(refuse_activation={MAIN})
    started = time.monotonic()
    with pytest.raises(E.Failure) as error:
        E.prepare(runtime(client, [dict(key=MAIN, **{'class': 'MainFrame'})]), client, 'Testpilot.epf',
                  time.monotonic() + 0.5)
    assert error.value.result['code'] == 'helper_not_ready' and time.monotonic() - started >= 0.4
    assert error.value.result['last_error']['code'] == 'target_not_interactive'
