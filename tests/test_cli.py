import json
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _cli  # noqa: E402
import _client_registry as CR  # noqa: E402
import testpilot  # noqa: E402


class FakeClient:
    calls = []
    outcome = dict(ok=True, pid=4242, port=30001, version='8.3.27.1859', execution_ready=True)

    def __init__(self, profile=None):
        self.profile = profile

    def start(self):
        FakeClient.calls.append('start')
        if not self.outcome['ok']:
            raise testpilot.ActionError('launch_client', dict(self.outcome))
        return dict(self.outcome)

    def call(self, action, check=True, **kw):
        FakeClient.calls.append(action)
        return {'ok': True}

    def close(self):
        FakeClient.calls.append('close')


@pytest.fixture
def fake(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(testpilot, 'Client', FakeClient)
    return FakeClient


def test_start_prints_json_and_disconnects(fake, capsys):
    fake.outcome = dict(ok=True, pid=4242, port=30001, version='8.3.27.1859', execution_ready=True)
    assert _cli.client_start('ib') == 0
    out = json.loads(capsys.readouterr().out)
    assert out == dict(ok=True, profile='ib', pid=4242, host='127.0.0.1', port=30001,
                       version='8.3.27.1859', execution_ready=True, reused=False)
    assert fake.calls == ['start', 'disconnect']


def test_repeated_start_reports_reuse(fake, capsys):
    fake.outcome = dict(ok=True, pid=4242, port=30001, reused=True)
    assert _cli.client_start('ib') == 0
    assert json.loads(capsys.readouterr().out)['reused'] is True


def test_failed_start_exits_nonzero_with_error(fake, capsys):
    fake.outcome = dict(ok=False, code='helper_startup_failed', error='no form', pid=4242, client_stopped=True)
    assert _cli.client_start('ib') == 1
    err = json.loads(capsys.readouterr().err)
    assert err['code'] == 'helper_startup_failed' and err['client_stopped'] is True
    assert 'disconnect' not in fake.calls and 'close' not in fake.calls


def profiles(tmp_path, monkeypatch):
    (tmp_path / 'profiles.yaml').write_text("profiles:\n  ib: {base: ib}\n", encoding='utf8')
    monkeypatch.setenv('TC1C_PROFILES_FILE', str(tmp_path / 'profiles.yaml'))
    return tmp_path / CR.FILENAME


def test_stop_of_dead_profile_client(tmp_path, monkeypatch, capsys):
    registry = profiles(tmp_path, monkeypatch)
    done = subprocess.Popen([sys.executable, '-c', 'pass'])
    done.wait()
    CR.record(registry, 'ib', port=30001, pid=done.pid, host='127.0.0.1')
    assert _cli.client_stop(profile='ib') == 0
    assert json.loads(capsys.readouterr().out)['stopped'] is False and CR.read(registry) == {}


def test_stop_by_pid_refuses_other_programs(tmp_path, monkeypatch, capsys):
    profiles(tmp_path, monkeypatch)
    assert _cli.client_stop(pid=os.getpid()) == 1
    assert json.loads(capsys.readouterr().err)['code'] == 'not_a_test_client'


def test_stop_by_pid_of_finished_process(tmp_path, monkeypatch, capsys):
    profiles(tmp_path, monkeypatch)
    done = subprocess.Popen([sys.executable, '-c', 'pass'])
    done.wait()
    assert _cli.client_stop(pid=done.pid) == 0
    assert json.loads(capsys.readouterr().out)['stopped'] is False


def test_without_command_runs_server_parser():
    args = _cli.parser().parse_args([])
    assert args.command is None
    args = _cli.parser().parse_args(['client', 'start', '--profile', 'роль:kfk_user'])
    assert (args.command, args.client_command, args.profile) == ('client', 'start', 'роль:kfk_user')


# Изменение client-stop-live-process (матрица — пп. 3.1–3.2 openspec/changes/dev-ib-client-stop-start/tasks.md кита).
# Состояние — запись спайка dev-ib-client-security-restart (копии в tests/recordings/, байт в байт
# docs/spikes/dev-ib-client-security-restart/recording/05-role-stop.txt и
# docs/spikes/dev-ib-client-security-restart/recording/05-after-stop-snap.txt): ролевой клиент
# после «непредвиденной ошибки» жив, -TPort30002 не слушается, порт runMcp держит он же, а client stop отвечал
# stopped: false. Процесс здесь настоящий: исполняемый файл с именем 1cv8 (ссылка на Python) с аргументами
# командной строки из записи, дочерний процесс 1cv8 и занятый порт (runMcp).
RECORDINGS = os.path.join(os.path.dirname(__file__), 'recordings')
# Ответ client stop этого клиента до исправления: stopped: false; профиль — из него.
ROLE = json.loads(open(os.path.join(RECORDINGS, '05-role-stop.txt'), encoding='utf-8').read())['profile']
TPORT = 30002                           # -TPort записи


def recorded_arguments(pid):
    """Аргументы процесса pid из снимка 05-after-stop-snap.txt (строка cmd, перенесённая по ширине, без exe)."""
    lines = open(os.path.join(RECORDINGS, '05-after-stop-snap.txt'), encoding='utf-8').read().splitlines()
    start = lines.index(next(line for line in lines if line.startswith(f'PID {pid} '))) + 1
    cmd = lines[start].removeprefix('  cmd: ')
    for line in lines[start + 1:]:
        if line.startswith(('порт ', 'PID ', 'окно ')):
            break
        cmd += line
    return cmd.split('" ', 1)[1].split()


FAKE_CLIENT = r'''
import socket, subprocess, sys, time
runmcp = socket.socket(); runmcp.bind(('127.0.0.1', 0)); runmcp.listen()
if sys.argv[3] != '0':
    tport = socket.socket(); tport.bind(('127.0.0.1', int(sys.argv[3]))); tport.listen()
child = subprocess.Popen([sys.argv[2], '-c', 'import time; time.sleep(120)'])
open(sys.argv[1], 'w').write('%d %d' % (child.pid, runmcp.getsockname()[1]))
time.sleep(120)
'''


@pytest.fixture
def client_process(tmp_path):
    """Запуск процесса с именем name и аргументами args (tport — слушать этот порт клиента тестирования);
    возвращает (pid, pid потомка, порт runMcp)."""
    started = []

    def launch(args, name='1cv8', tport=0):
        exe = tmp_path / name
        if not exe.exists():
            try:
                os.symlink(sys.executable, exe)
            except OSError:
                pytest.skip('symlink unavailable')
        ready = tmp_path / f'ready-{len(started)}'
        process = subprocess.Popen([str(exe), '-c', FAKE_CLIENT, str(ready), str(exe), str(tport), *args])
        started.append(process)
        for _ in range(200):
            if ready.exists() and ready.read_text():
                break
            process.poll()
            assert process.returncode is None, 'fake client exited'
            time.sleep(0.05)
        child, port = map(int, ready.read_text().split())
        started.append(child)
        return process.pid, child, port

    yield launch
    import psutil
    for item in started:
        try:
            (psutil.Process(item) if isinstance(item, int) else psutil.Process(item.pid)).kill()
        except psutil.Error:
            pass
    for item in started:
        if not isinstance(item, int):
            item.wait()


def gone(pid):
    import psutil
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def port_free(port):
    import socket
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


@pytest.mark.parametrize('by', ['profile', 'pid'])
def test_stop_client_that_lost_its_test_port(by, tmp_path, monkeypatch, capsys, client_process):
    registry = profiles(tmp_path, monkeypatch)
    args = recorded_arguments(95756)
    assert f'-TPort{TPORT}' in args
    pid, child, runmcp = client_process(args)
    CR.record(registry, ROLE, port=TPORT, pid=pid, host='127.0.0.1')
    code = _cli.client_stop(profile=ROLE) if by == 'profile' else _cli.client_stop(pid=pid)
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out == dict(ok=True, pid=pid, stopped=True, **({'profile': ROLE} if by == 'profile' else {}))
    deadline = time.monotonic() + 15
    while not (gone(pid) and gone(child)) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert gone(pid) and gone(child)
    assert port_free(runmcp)
    assert CR.read(registry) == {}


@pytest.mark.parametrize('name, args', [
    ('python-client', recorded_arguments(95756)),                                  # не 1cv8*: pid отдан другой программе
    ('1cv8', [a for a in recorded_arguments(95756) if not a.startswith('-TPort')] + ['-TPort30003']),  # другой -TPort
    ('1cv8', [a for a in recorded_arguments(95756) if not a.startswith('-TPort')]),                    # без -TPort
])
def test_stop_does_not_touch_foreign_process_of_entry(name, args, tmp_path, monkeypatch, capsys, client_process):
    registry = profiles(tmp_path, monkeypatch)
    pid, child, runmcp = client_process(args, name=name)
    CR.record(registry, ROLE, port=TPORT, pid=pid, host='127.0.0.1')
    assert _cli.client_stop(profile=ROLE) == 0
    assert json.loads(capsys.readouterr().out) == dict(ok=True, profile=ROLE, stopped=False)
    time.sleep(0.3)
    assert not gone(pid) and not gone(child)
    assert CR.read(registry) == {}


def test_owned_without_listening_port_is_not_alive(client_process):
    # alive (переиспользование клиента в launch_client) по-прежнему требует слушающий -TPort; owned — нет.
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    args = [a for a in recorded_arguments(95756) if not a.startswith('-TPort')] + [f'-TPort{port}']
    pid, _, _ = client_process(args)
    entry = dict(pid=pid, port=port)
    assert (CR.owned(entry), CR.alive(entry)) == (True, False)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', port))
        listener.listen()
        assert (CR.owned(entry), CR.alive(entry)) == (True, True)


def free_port():
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize('recorded', ['01c-daily-stop.txt', '09-ib-stop.txt'])
def test_stop_live_client_as_recorded(recorded, tmp_path, monkeypatch, capsys, client_process):
    # Штатный stop живого клиента (-TPort слушает): ответ — как в записи (копия
    # docs/spikes/dev-ib-client-security-restart/recording/01c-daily-stop.txt и
    # docs/spikes/dev-ib-client-security-restart/recording/09-ib-stop.txt, pid — свой),
    # после — как снимок docs/spikes/dev-ib-client-security-restart/recording/09-after.txt: процессов нет, порты свободны.
    expected = json.loads(open(os.path.join(RECORDINGS, recorded), encoding='utf-8').read())
    after = open(os.path.join(RECORDINGS, '09-after.txt'), encoding='utf-8').read()
    assert 'процессов 1С дерева: 0' in after and after.count('слушает: никто') == 3
    registry = profiles(tmp_path, monkeypatch)
    tport = free_port()
    args = [a for a in recorded_arguments(95756) if not a.startswith('-TPort')] + [f'-TPort{tport}']
    pid, child, runmcp = client_process(args, tport=tport)
    CR.record(registry, expected['profile'], port=tport, pid=pid, host='127.0.0.1')
    assert CR.alive(CR.read(registry)[expected['profile']])
    assert _cli.client_stop(profile=expected['profile']) == 0
    assert json.loads(capsys.readouterr().out) == {**expected, 'pid': pid}
    deadline = time.monotonic() + 15
    while not (gone(pid) and gone(child)) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert gone(pid) and gone(child) and port_free(tport) and port_free(runmcp)
    assert CR.read(registry) == {}
