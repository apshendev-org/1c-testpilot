import json
import os
import subprocess
import sys

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
