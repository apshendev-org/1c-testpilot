import inspect
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import guids as G  # noqa: E402
import server as R  # noqa: E402
import tc1c  # noqa: E402

CHOICE = 'SecondaryFrame[c]'
BUTTON = CHOICE + '.ManagedForm[f].Button[ФормаВыбрать]'


class Closing:
    """Client whose action frame closes the element's window: the commit frame no longer finds it."""

    def __init__(self, status=7):
        self.status, self.frames = status, []

    def send_cmd(self, guid, key, kind='read', **kw):
        self.frames.append(kind)
        if kind == 'commit':
            raise tc1c.OperationError(self.status, key)
        return {'ok': True}


@pytest.mark.parametrize('action, arguments', [
    ('tc_click', dict(key=BUTTON, handle='h', expect='none')),
    ('tc_choose_row', dict(key=CHOICE + '.ManagedForm[f].Table[Список]', handle='h')),
])
def test_command_closing_its_window_is_ok(action, arguments):
    client = Closing()
    with patch.object(R, '_need', return_value=client), patch.object(R, '_ref_live_object', return_value=None):
        result = inspect.unwrap(getattr(R, action))(**arguments)
    assert result['ok'] is True and client.frames[:2] == ['action', 'commit']


def test_missing_element_of_an_open_window_is_still_an_error():
    with patch.object(R, '_need', return_value=Closing()), \
            patch.object(R, '_ref_live_object', return_value={'key': CHOICE}):
        with pytest.raises(tc1c.OperationError):
            inspect.unwrap(R.tc_click)(key=BUTTON, handle='h', expect='none')


class Versioned:
    """TestClient stub that refuses the handshake until the running platform version is sent."""
    DEFAULT_VER = tc1c.TestClient.DEFAULT_VER
    running = '8.3.27.2342'
    tried = []

    def __init__(self, host, port):
        self.host, self.port, self.platform_version = host, port, None

    def connect(self):
        sent = self.platform_version or self.DEFAULT_VER
        Versioned.tried.append(sent)
        if sent != self.running:
            raise tc1c.ConnectionFailure(self.host, self.port, 'authentication',
                                         f'Различаются версии клиента и сервера ({sent} - {self.running})')
        return 'session'

    def attach(self):
        pass

    def close(self):
        pass


def test_connect_by_port_takes_the_running_version():
    Versioned.tried = []
    with patch.object(R.tc1c, 'TestClient', Versioned), patch.dict(R._state, client=None):
        reply = inspect.unwrap(R.tc_connect)(30000)
        assert R._state['client'].platform_version == Versioned.running
    assert Versioned.tried == [Versioned.DEFAULT_VER, Versioned.running]
    assert Versioned.running in reply


def test_explicit_version_is_not_replaced():
    Versioned.tried = []
    with patch.object(R.tc1c, 'TestClient', Versioned), patch.dict(R._state, client=None):
        with pytest.raises(tc1c.ConnectionFailure):
            inspect.unwrap(R.tc_connect)(30000, version='8.3.27.1000')
    assert Versioned.tried == ['8.3.27.1000']


ERROR_WINDOW = 'SecondaryFrame[e]'


def test_current_error_reads_the_error_window():
    objects = [dict(key=ERROR_WINDOW + '.ManagedForm[f].Button[ОК]', title='ОК', **{'class': 'Button'}),
               dict(key=ERROR_WINDOW + '.ManagedForm[f].Decoration[Message]', name='Message',
                    title='Не удалось записать "Поступление 0001"!', **{'class': 'Decoration'})]

    class Client:
        def send_cmd(self, guid, key, **kw):
            assert guid == G.GET_CURRENT_ERROR
            return {'ok': True}

    with patch.object(R, '_need', return_value=Client()), patch.object(R, '_vals', return_value=[]), \
            patch.object(R, '_window', return_value={'key': ERROR_WINDOW}), \
            patch.object(R, '_form_title', return_value=('1С:Предприятие', 'ErrorWindow')), \
            patch.object(R, '_search_objects', return_value=objects):
        result = inspect.unwrap(R.tc_get_current_error)()
    assert result == dict(ok=True, error='Не удалось записать "Поступление 0001"!', details=[], window=ERROR_WINDOW)
