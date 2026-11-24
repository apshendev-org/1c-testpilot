"""Старт клиента версии не кластера: отказ client_version_mismatch без оставшегося процесса
(изменение client-version-relaunch, сценарии client-launch-cli).

Фейк psutil отдаёт дочерний клиент из записи живой системы
docs/spikes/testpilot-profile-version/recording/01-relaunched-child.txt (родитель — наш PID,
exe 8.3.27.2342, командная строка с -TPort30001); ожидаемый ответ отказа и удачного старта —
из docs/spikes/testpilot-profile-version/recording/02-mismatch-run.txt (spike:spk_e348d75193@v2).
Копии записей в tests/recordings/ байт в байт (совпадение проверяет payload/tests/test_spike_recordings.py).
PID дочернего процесса в записи нет — он взят условно; всё остальное в фейке — из записи.
"""
import inspect
import json
import ntpath
import os
import re
import socket
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _cli  # noqa: E402
import _code_execution  # noqa: E402
import server as R  # noqa: E402
import testpilot  # noqa: E402

RECORDINGS = Path(__file__).resolve().parent / 'recordings'
CHILD_PID = 85393  # shortcut: в записи PID дочернего не снят, только родитель


def recorded_child():
    """Строка процесса из 01: (родитель, exe, командная строка списком аргументов)."""
    line = (RECORDINGS / '01-relaunched-child.txt').read_text(encoding='utf-8').splitlines()[0]
    m = re.match(r'\S+ parent=(\d+) "([^"]+)" (.*)$', line)
    return int(m.group(1)), m.group(2), [m.group(2)] + m.group(3).split()


def recorded_runs():
    """Ответы 02 по заголовкам «--- start <версия>»: JSON (перенос терминала склеен) и код выхода."""
    runs, name, buf = {}, None, []
    for line in (RECORDINGS / '02-mismatch-run.txt').read_text(encoding='utf-8').splitlines():
        if line.startswith('--- '):
            name = line[4:] if line.startswith('--- start ') else None
            buf = []
        elif name and line.startswith('exit='):
            runs[name] = (json.loads(''.join(buf)), int(line[5:]))
            name = None
        elif name:
            buf.append(line)
    return runs


PARENT, CHILD_EXE, CHILD_CMDLINE = recorded_child()
RUNS = recorded_runs()
MISMATCH, MISMATCH_EXIT = RUNS['start 8.3.27.1688']
SUCCESS, SUCCESS_EXIT = RUNS['start 8.3.27.2342']
PORT = int(next(a for a in CHILD_CMDLINE if a.startswith('-TPort'))[6:])
PROFILE_VERSION = '8.3.27.1688'


class FakePsutil(types.ModuleType):
    """psutil.process_iter по снимку процессов; kill убирает процесс из снимка."""

    class Error(Exception):
        pass

    class NoSuchProcess(Error):
        pass

    class TimeoutExpired(Error):
        pass

    def __init__(self):
        super().__init__('psutil')
        self.processes, self.iterated = [], 0

    def process_iter(self, attrs=None):
        self.iterated += 1
        return list(self.processes)

    def alive_on_port(self, port):
        return [p for p in self.processes if '-TPort%s' % port in p.info['cmdline']]


class FakeChild:
    def __init__(self, ps, pid, ppid, exe, cmdline, kill_error=None):
        self.ps, self.pid, self.kill_error, self.killed = ps, pid, kill_error, False
        self.info = {'ppid': ppid, 'name': ntpath.basename(exe), 'exe': exe, 'cmdline': cmdline}

    def kill(self):
        if self.kill_error:
            raise self.kill_error
        self.killed = True
        self.ps.processes.remove(self)

    def wait(self, timeout=None):
        return 0


class FakeProcess:
    def __init__(self, pid, returncode=None):
        self.pid, self.returncode = pid, returncode

    def poll(self):
        return self.returncode


class FakeSocket:
    def __init__(self, answer):
        self.answer = answer

    def settimeout(self, timeout):
        pass

    def connect_ex(self, address):
        return self.answer

    def close(self):
        pass


class FakeClient:
    _io_deadline = None


@pytest.fixture
def env(monkeypatch, tmp_path):
    now = [0.0]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(time, 'sleep', lambda s: now.__setitem__(0, now[0] + max(s, 0)))
    monkeypatch.setenv('DISPLAY', ':99')
    ps = FakePsutil()
    monkeypatch.setitem(sys.modules, 'psutil', ps)
    monkeypatch.setattr(R, '_state', {'profile': 'ib'})
    exe = tmp_path / '1cv8' / PROFILE_VERSION / 'bin' / ('1cv8.exe' if os.name == 'nt' else '1cv8')
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'')
    stops = []

    def stop_client(graceful_timeout=15):
        stops.append(graceful_timeout)
        proc = R._state.get('launched_process')
        already = proc.returncode is not None
        proc.returncode = proc.returncode if already else 1
        return {'ok': True, 'stopped_pid': proc.pid, 'shutdown': 'already_exited' if already else 'forced'}

    monkeypatch.setattr(R, 'tc_stop_client', stop_client)

    def connect(port, host='127.0.0.1', version=None):
        R._state['client'] = FakeClient()
        return 'подключено'

    monkeypatch.setattr(R, 'tc_connect', connect)
    monkeypatch.setattr(_code_execution, 'launch_path', lambda *a, **k: 'Testpilot.epf')
    return types.SimpleNamespace(ps=ps, exe=exe, stops=stops, monkeypatch=monkeypatch)


def add_child(env, cmdline=CHILD_CMDLINE, **kw):
    child = FakeChild(env.ps, CHILD_PID, PARENT, CHILD_EXE, cmdline, **kw)
    env.ps.processes.append(child)
    return child


def launch(env, *, exited, helper_error=None):
    """Наш процесс PARENT: exited — вышел до порта; иначе жив, порт отвечает, помощник падает helper_error."""
    proc = FakeProcess(PARENT, 0 if exited else None)
    env.monkeypatch.setattr(subprocess, 'Popen', lambda args, **kw: proc)
    env.monkeypatch.setattr(socket, 'socket', lambda *a, **k: FakeSocket(1 if exited else 0))

    def prepare(*a, **k):
        if helper_error:
            raise helper_error

    env.monkeypatch.setattr(_code_execution, 'prepare', prepare)
    return proc, inspect.unwrap(R.tc_launch_client)(base='srv\\base', port=PORT, server=True, user='u',
                                                    wait=60, exe=str(env.exe))


def cli_emit(monkeypatch, capsys, result):
    """Ответ рантайма через `client start`: ActionError, как у testpilot.Client."""

    class Client:
        def __init__(self, profile=None):
            pass

        def start(self):
            if not result['ok']:
                raise testpilot.ActionError('launch_client', dict(result))
            return dict(result)

        def call(self, action, check=True, **kw):
            return {'ok': True}

    monkeypatch.setattr(testpilot, 'Client', Client)
    code = _cli.client_start('ib')
    captured = capsys.readouterr()
    return code, json.loads(captured.err or captured.out)


def test_recordings_parse():
    assert PORT == 30001 and ntpath.basename(CHILD_EXE) == '1cv8.exe'
    assert R._exe_version(CHILD_EXE) == '8.3.27.2342'
    assert MISMATCH['code'] == 'client_version_mismatch' and MISMATCH_EXIT == 1
    assert SUCCESS['ok'] is True and SUCCESS_EXIT == 0


# 10054 — ошибка помощника из прогона 1 (output/01-version-1688.txt): наш процесс ещё жив/выходит
@pytest.mark.parametrize('exited, helper_error', [
    (True, None),
    (False, ConnectionResetError(10054, 'An existing connection was forcibly closed by the remote host')),
], ids=['our-process-exited', 'our-process-still-alive'])
def test_older_client_than_cluster_is_refused_and_child_killed(env, monkeypatch, capsys, exited, helper_error):
    child = add_child(env)
    proc, result = launch(env, exited=exited, helper_error=helper_error)

    assert result['ok'] is False
    assert result['code'] == 'client_version_mismatch'
    assert result['error'] == MISMATCH['error']
    assert PROFILE_VERSION in result['error'] and '8.3.27.2342' in result['error']
    assert result['client_stopped'] is True and 'cleanup_error' not in result
    assert child.killed and env.ps.alive_on_port(PORT) == []
    assert env.stops == [0]

    code, err = cli_emit(monkeypatch, capsys, result)
    assert code == MISMATCH_EXIT
    assert {k: v for k, v in err.items() if k != 'pid'} == {k: v for k, v in MISMATCH.items() if k != 'pid'}
    assert err['pid'] == PARENT


def test_child_that_cannot_be_killed_reports_cleanup_error(env, monkeypatch, capsys):
    child = add_child(env, kill_error=FakePsutil.TimeoutExpired('kill timed out'))
    _, result = launch(env, exited=False, helper_error=ConnectionResetError(10054, 'reset'))

    assert result['code'] == 'client_version_mismatch'
    assert result['client_stopped'] is False
    assert str(CHILD_PID) in result['cleanup_error']
    assert not child.killed

    _, err = cli_emit(monkeypatch, capsys, result)
    assert err['client_stopped'] is False and err['cleanup_error'] == result['cleanup_error']


def foreign_cmdline():
    return [('-TPort%d' % (PORT + 1)) if a == '-TPort%d' % PORT else a for a in CHILD_CMDLINE]


def test_foreign_child_with_other_port_is_untouched_after_helper_failure(env):
    child = add_child(env, cmdline=foreign_cmdline())
    _, result = launch(env, exited=False, helper_error=ConnectionResetError(10054, 'reset'))

    assert result['ok'] is False and result['code'] == 'helper_startup_failed'
    assert 'client_version_mismatch' not in result['error']
    assert result['client_stopped'] is True
    assert not child.killed and child in env.ps.processes


def test_foreign_child_with_other_port_is_untouched_after_early_exit(env):
    child = add_child(env, cmdline=foreign_cmdline())
    _, result = launch(env, exited=True)

    assert result['ok'] is False and 'code' not in result  # прежний отказ раннего выхода — без кода
    assert 'exited (code 0)' in result['error']
    assert not child.killed and child in env.ps.processes


def test_successful_start_does_not_look_for_children(env, monkeypatch, capsys):
    def no_iter(attrs=None):
        raise AssertionError('удачный старт не ищет дочерние клиенты')

    env.ps.process_iter = no_iter
    proc, result = launch(env, exited=False)

    assert result['ok'] is True and result['execution_ready'] is True
    assert 'client_stopped' not in result and 'code' not in result
    assert env.stops == [] and proc.returncode is None

    code, out = cli_emit(monkeypatch, capsys, result)
    assert code == SUCCESS_EXIT
    assert set(out) == set(SUCCESS)
    assert out['ok'] is True and out['port'] == PORT and out['profile'] == SUCCESS['profile']
