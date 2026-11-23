"""Старт клиента при неудачном входе и при выходе процесса — отказ сразу (изменение login-fail-fast).

Сценарии client-launch-cli проверяются по записи живой системы: окна процесса 1С, ошибки
discover и итог старта взяты из docs/spikes/testpilot-login-fail-fast/recording/login-failed.jsonl
(случаи no_user, bad_password) и docs/spikes/testpilot-login-fail-fast/recording/slow-start.jsonl
(обычный долгий старт). Копии записей в tests/recordings/ байт в байт (testpilot уходит в форк
без docs/ кита, совпадение проверяет payload/tests/test_spike_recordings.py). Windows-модули
win32gui/win32process подменены перечислителем записанных окон: реальная логика login_dialog,
_launch_failure и prepare(stop=) работает против записи. Платформе выставлен os.name='nt' —
запись снята на Windows обычного рабочего стола, окно входа там и ищется.
"""
import inspect
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

WINDOWS = {}


class FakeWin32Gui:
    """win32gui против записи: EnumWindows перечисляет снимок show(); записанные окна видимы."""

    error = type('error', (Exception,), {})

    @staticmethod
    def EnumWindows(callback, extra):
        for hwnd in list(WINDOWS):
            try:
                if callback(hwnd, extra) is False:
                    return
            except FakeWin32Gui.error:
                raise
            except Exception as exc:
                raise FakeWin32Gui.error(repr(exc)) from exc

    @staticmethod
    def IsWindowVisible(hwnd):
        return True

    @staticmethod
    def GetWindowText(hwnd):
        return WINDOWS[hwnd][1]['title']

    @staticmethod
    def GetClassName(hwnd):
        return WINDOWS[hwnd][1]['class']

    @staticmethod
    def GetWindow(hwnd, command):
        return WINDOWS[hwnd][1]['owner']

    @staticmethod
    def GetWindowLong(hwnd, index):
        return WINDOWS[hwnd][1]['style']


class FakeWin32Process:
    @staticmethod
    def GetWindowThreadProcessId(hwnd):
        return 1, WINDOWS[hwnd][0]


# На Linux реальных win32-модулей нет; на Windows живые не подменять.
for name, fake in (('win32gui', FakeWin32Gui), ('win32process', FakeWin32Process)):
    sys.modules.setdefault(name, fake)

import _code_execution  # noqa: E402
import _native_window  # noqa: E402
import _service_metadata  # noqa: E402  ленивый импорт в discover не должен случиться под патчем os.name (см. recorded_launch)
import server as R  # noqa: E402

RECORDINGS = Path(__file__).resolve().parent / 'recordings'
LOGIN_DIALOG_TITLE = 'Доступ к информационной базе'
DISCOVER_ERROR = 'Could not read application windows; retry the search.'
MAIN_WINDOW_TITLE = 'DEV / Бухгалтерия государственного учреждения, редакция 2.0'
# Причины отказа входа из требования: нет пользователя, пароль неверный или не передан, нет права входа.
REASONS = ('not in the infobase', 'password is wrong or was not passed', 'right to log in')


def show(pid, windows):
    """Показать процессу pid снимок окон из записи."""
    WINDOWS.clear()
    for window in windows:
        WINDOWS[window['hwnd']] = (pid, window)


def records(name, case=None, kind=None, t=None):
    """Строки записи {case, t, kind, ...} с фильтром по полям."""
    rows = []
    with (RECORDINGS / name).open(encoding='utf-8') as source:
        for line in source:
            row = json.loads(line)
            if case in (None, row.get('case')) and kind in (None, row.get('kind')) and t in (None, row.get('t')):
                rows.append(row)
    return rows


def snapshot(name, case):
    """Снимок окон процесса с окном входа: единственный живой снимок случая с отказом."""
    return records(name, case=case, kind='process')[0]


class FakeProcess:
    """Процесс 1С: жив до остановки или собственного выхода, код выхода — как сказано в тесте."""

    def __init__(self, pid):
        self.pid, self.returncode = pid, None

    def poll(self):
        return self.returncode


class FakeSocket:
    def settimeout(self, timeout):
        pass

    def connect_ex(self, address):
        return 0  # порт отвечает: по записи tc_connect проходит на 15-й секунде

    def close(self):
        pass


class FakeClient:
    """Подключение из фейкового tc_connect: prepare касается только атрибутов крайнего срока."""

    _io_deadline = None


@pytest.fixture
def fake_time(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(time, 'sleep', lambda s: now.__setitem__(0, now[0] + max(s, 0)))
    return now


def recorded_launch(monkeypatch, tmp_path, pid, connect_result):
    """tc_launch_client против записи: процесс, порт, подключение и остановка — фейки."""
    proc = FakeProcess(pid)
    monkeypatch.setattr(os, 'name', 'nt')  # запись с Windows обычного рабочего стола
    monkeypatch.setenv('DISPLAY', ':99')   # default на Linux требует графический сеанс
    exe = tmp_path / '1cv8.exe'
    exe.write_bytes(b'')
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: FakeSocket())
    monkeypatch.setattr(subprocess, 'Popen', lambda args, **kw: proc)
    helper = records('login-failed.jsonl', case='no_user', kind='spawned')[0]['cmdline'][-1]
    monkeypatch.setattr(_code_execution, 'launch_path', lambda *a, **k: helper)
    stops = []

    def stop_client(graceful_timeout=15):
        stops.append(graceful_timeout)
        already = proc.returncode is not None
        if not already:
            proc.returncode = 1  # наша остановка: форсированное завершение
        return {'ok': True, 'stopped_pid': proc.pid, 'shutdown': 'already_exited' if already else 'forced'}

    monkeypatch.setattr(R, 'tc_stop_client', stop_client)
    monkeypatch.setattr(R, '_state', {'profile': 'ib'})  # запуск через профиль: запись снята с профилем ib

    def connect(port, host='127.0.0.1', version=None):
        R._state['client'] = FakeClient()
        return connect_result

    monkeypatch.setattr(R, 'tc_connect', connect)
    return proc, stops, exe


def stop_on_recorded_windows(pid, windows_by_round):
    """Фейковый клиент всегда отказывается читать окна, поиск ошибок по записи; снимки — по кругам."""
    shown = []

    def search(client, root_key=None):
        shown.append(1)
        show(pid, windows_by_round[min(len(shown), len(windows_by_round)) - 1])
        raise RuntimeError(DISCOVER_ERROR)

    return search, shown


def launch(exe, *, base, user, wait):
    return inspect.unwrap(R.tc_launch_client)(base=base, port=30000, server=True, user=user,
                                              wait=wait, exe=str(exe), desktop='default')


def test_login_dialog_recognizes_recorded_snapshots():
    # Окно входа есть в единственных живых снимках no_user (t=24,28) и bad_password (t=24,09);
    # все остальные снимки обоих файлов — загрузка, главное окно, служебные и пустые — не отказ.
    assert _native_window.LOGIN_TITLES == (LOGIN_DIALOG_TITLE,)
    for name, case in (('login-failed.jsonl', 'no_user'), ('login-failed.jsonl', 'bad_password')):
        row = snapshot(name, case)
        show(row['pid'], row['windows'])
        assert _native_window.login_dialog(row['pid']) == LOGIN_DIALOG_TITLE
    for name in ('login-failed.jsonl', 'slow-start.jsonl'):
        for row in records(name, kind='process'):
            if row['case'] in ('no_user', 'bad_password') and row.get('alive'):
                continue  # живые снимки отказов разобраны выше
            show(row['pid'], row['windows'])
            assert _native_window.login_dialog(row['pid']) is None, (name, row['case'], row['t'])


def test_unknown_user_fails_at_once_with_login_dialog(monkeypatch, tmp_path, fake_time):
    # «Пользователя нет в базе»: окно входа появилось на круге ожидания — отказ сразу, процесс остановлен.
    spawned = records('login-failed.jsonl', case='no_user', kind='spawned')[0]
    connected = records('login-failed.jsonl', case='no_user', kind='tc_connect')[0]['result']
    dialog = snapshot('login-failed.jsonl', 'no_user')['windows']
    proc, stops, exe = recorded_launch(monkeypatch, tmp_path, spawned['pid'], connected)
    search, shown = stop_on_recorded_windows(spawned['pid'], [[], dialog])
    monkeypatch.setattr(R, '_search_objects', search)

    result = launch(exe, base=spawned['cmdline'][2][2:], user='spike_no_such_user', wait=90)

    assert result['ok'] is False
    assert result['code'] == 'login_failed'
    assert result['dialog'] == LOGIN_DIALOG_TITLE
    assert 'ib' in result['error']
    assert 'spike_no_such_user' in result['error']
    assert all(reason in result['error'] for reason in REASONS)
    assert result['client_stopped'] is True
    assert result['connected'] == connected
    assert proc.poll() is not None          # процесса 1С нет
    assert stops == [0]                     # остановка форсированная, без graceful-ожидания
    assert len(shown) == 2                  # окно появилось на втором круге — отказ на следующем, не по сроку
    assert fake_time[0] < 90                # до срока wait


def test_wrong_password_fails_at_once_with_login_dialog(monkeypatch, tmp_path, fake_time):
    # «Неверный пароль»: отказ тот же, что без пользователя, с логином профиля в error.
    spawned = records('login-failed.jsonl', case='bad_password', kind='spawned')[0]
    connected = records('login-failed.jsonl', case='bad_password', kind='tc_connect')[0]['result']
    dialog = snapshot('login-failed.jsonl', 'bad_password')['windows']
    proc, stops, exe = recorded_launch(monkeypatch, tmp_path, spawned['pid'], connected)
    search, shown = stop_on_recorded_windows(spawned['pid'], [[], dialog])
    monkeypatch.setattr(R, '_search_objects', search)

    result = launch(exe, base=spawned['cmdline'][2][2:], user='Администратор', wait=90)

    assert result['ok'] is False
    assert result['code'] == 'login_failed'
    assert result['dialog'] == LOGIN_DIALOG_TITLE
    assert 'ib' in result['error']
    assert 'Администратор' in result['error']
    assert all(reason in result['error'] for reason in REASONS)
    assert result['client_stopped'] is True
    assert proc.poll() is not None
    assert len(shown) == 2                  # отказ сразу после появления окна, не по сроку
    assert fake_time[0] < 90


def test_login_error_without_user_and_profile_names_none(monkeypatch, tmp_path, fake_time):
    # Без логина и профиля error называет оба как (none) — причины те же.
    spawned = records('login-failed.jsonl', case='no_user', kind='spawned')[0]
    connected = records('login-failed.jsonl', case='no_user', kind='tc_connect')[0]['result']
    dialog = snapshot('login-failed.jsonl', 'no_user')['windows']
    proc, stops, exe = recorded_launch(monkeypatch, tmp_path, spawned['pid'], connected)
    R._state.pop('profile')
    search, shown = stop_on_recorded_windows(spawned['pid'], [[], dialog])
    monkeypatch.setattr(R, '_search_objects', search)

    result = launch(exe, base=spawned['cmdline'][2][2:], user=None, wait=90)

    assert result['code'] == 'login_failed'
    assert result['error'].count('(none)') == 2  # профиль и логин не переданы
    assert all(reason in result['error'] for reason in REASONS)
    assert result['client_stopped'] is True


def test_client_exit_during_startup_fails_at_once(monkeypatch, tmp_path, fake_time):
    # «Процесс вышел во время подготовки» (записи нет): после подключения процесс вышел —
    # отказ client_exited с кодом выхода, без ожидания wait и без поиска обработки.
    spawned = records('login-failed.jsonl', case='no_user', kind='spawned')[0]
    connected = records('login-failed.jsonl', case='no_user', kind='tc_connect')[0]['result']
    proc, stops, exe = recorded_launch(monkeypatch, tmp_path, spawned['pid'], connected)

    def connect_and_exit(port, host='127.0.0.1', version=None):
        proc.returncode = 137  # процесс завершился сразу после подключения
        R._state['client'] = FakeClient()
        return connected

    monkeypatch.setattr(R, 'tc_connect', connect_and_exit)

    def search(client, root_key=None):
        raise AssertionError('после выхода процесса обработку искать не должны')

    monkeypatch.setattr(R, '_search_objects', search)

    result = launch(exe, base=spawned['cmdline'][2][2:], user='spike_no_such_user', wait=600)

    assert result['ok'] is False
    assert result['code'] == 'client_exited'
    assert '137' in result['error']
    assert result['client_stopped'] is True
    assert proc.poll() == 137
    assert fake_time[0] < 600               # без ожидания до срока


def test_slow_start_waits_and_succeeds(monkeypatch, tmp_path, fake_time):
    # «Долгий обычный старт»: окна загрузки и главное из записи — не отказ; повторные ошибки
    # discover по записи ожидание не прекращают; готовность обработки — ok: true до срока.
    spawned = records('slow-start.jsonl', case='ok', kind='spawned')[0]
    connected = records('slow-start.jsonl', case='ok', kind='tc_connect')[0]['result']
    alive = [r['windows'] for r in records('slow-start.jsonl', case='ok', kind='process') if r.get('alive')]
    loading = alive[0]                       # «Загрузка конфигурационной информации...»
    main = next(s for s in alive if any(w['title'] == MAIN_WINDOW_TITLE for w in s))
    # search_objects записи — проекция перечисленных объектов; handle она не писала, пустой.
    objects = [dict(o, handle=None) for o in records('slow-start.jsonl', case='ok', kind='search_objects')[0]['objects']]
    proc, stops, exe = recorded_launch(monkeypatch, tmp_path, spawned['pid'], connected)
    shown = []

    def search_by_round(client, root_key=None):
        # поиск вызывается после stop(): круг 1 и 2 — снимок загрузки, круг 3 — главное окно
        shown.append(1)
        show(spawned['pid'], [loading, loading, main][len(shown) - 1])
        if len(shown) < 3:
            raise RuntimeError(DISCOVER_ERROR)
        return objects

    monkeypatch.setattr(R, '_search_objects', search_by_round)
    main_frame = next(o['key'] for o in objects if o['class'] == 'MainFrame')
    monkeypatch.setattr(R, '_window', lambda client: {'key': main_frame})
    envelope = json.dumps({'protocol': _code_execution.PROTOCOL, 'ok': True,
                           'request_id': 'slow-start', 'capabilities': []})
    monkeypatch.setattr(R, 'tc_get_data_presentation', lambda **kw: {'ok': True, 'presentation': envelope})

    result = launch(exe, base=spawned['cmdline'][2][2:], user='Администратор', wait=600)

    assert result['ok'] is True
    assert result['execution_ready'] is True
    assert result['connected'] == connected
    assert result['pid'] == spawned['pid'] and proc.poll() is None
    assert stops == []                       # успешный старт клиента не останавливает
    assert 'code' not in result and 'client_stopped' not in result
    assert len(shown) == 3                   # обе ошибки discover по записи — не отказ
    assert fake_time[0] < 600                # успех до срока wait


def test_prepare_reports_refusal_from_stop(monkeypatch, fake_time):
    # Контракт prepare(stop=): stop() зовётся на каждом круге ожидания; словарь отказа
    # превращается в Failure с теми же code, error и доп. полями.
    refusal = {'code': 'login_failed', 'error': 'окно входа из записи', 'dialog': LOGIN_DIALOG_TITLE}
    answers = iter([None, None, refusal])
    rounds = []

    def stop():
        rounds.append(1)
        return next(answers)

    def search(client, root_key=None):
        raise RuntimeError(DISCOVER_ERROR)

    monkeypatch.setattr(R, '_search_objects', search)
    client = FakeClient()

    with pytest.raises(_code_execution.Failure) as exc:
        _code_execution.prepare(R, client, 'Testpilot.epf', fake_time[0] + 600, stop=stop)

    assert exc.value.result == {'ok': False, 'code': 'login_failed', 'error': 'окно входа из записи',
                                'dialog': LOGIN_DIALOG_TITLE}
    assert len(rounds) == 3                  # stop() на каждом круге, отказ прекращает ожидание
    assert fake_time[0] < 600
