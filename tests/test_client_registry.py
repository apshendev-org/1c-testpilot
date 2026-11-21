import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _client_registry as CR  # noqa: E402
import _profiles  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def free_block(size):
    """Start of `size` consecutive ports that are currently free."""
    for start in range(40000, 60000, size):
        if all(CR.port_free(p) for p in range(start, start + size)):
            return start
    pytest.skip('no free port block')


def occupy(port):
    s = socket.socket()
    s.bind(('127.0.0.1', port))
    s.listen()
    return s


def test_busy_ports_are_skipped():
    start = free_block(3)
    held = [occupy(start), occupy(start + 1)]
    try:
        assert CR.first_free((start, start + 2)) == start + 2
    finally:
        for s in held:
            s.close()


def test_exhausted_pool_lists_busy_ports():
    start = free_block(2)
    held = [occupy(start), occupy(start + 1)]
    try:
        with pytest.raises(CR.RegistryError) as error:
            CR.first_free((start, start + 1))
        assert error.value.code == 'port_pool_exhausted'
        assert error.value.details['busy_ports'] == [start, start + 1]
    finally:
        for s in held:
            s.close()


def test_machine_lock_is_exclusive_and_released_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv('TC1C_MACHINE_DIR', str(tmp_path))
    with pytest.raises(RuntimeError):
        with CR.machine_lock(1):
            with pytest.raises(CR.RegistryError) as error:
                CR.MachineLock(0.2).acquire()
            assert error.value.code == 'machine_lock_timeout'
            raise RuntimeError('launch failed')
    CR.MachineLock(0.2).acquire().release()
    assert (tmp_path / 'launch.lock').exists()


def test_lock_excludes_another_process(tmp_path):
    code = ('import sys; sys.path.insert(0, sys.argv[1]); import _client_registry as CR\n'
            'try:\n    CR.MachineLock(0.3).acquire()\nexcept CR.RegistryError as e:\n    print(e.code)')
    env = dict(os.environ, TC1C_MACHINE_DIR=str(tmp_path))
    previous = os.environ.get('TC1C_MACHINE_DIR')
    os.environ['TC1C_MACHINE_DIR'] = str(tmp_path)
    try:
        with CR.machine_lock(1):
            out = subprocess.run([sys.executable, '-c', code, str(ROOT / 'app')], capture_output=True,
                                 text=True, env=env, timeout=30)
    finally:
        if previous is None:
            os.environ.pop('TC1C_MACHINE_DIR')
        else:
            os.environ['TC1C_MACHINE_DIR'] = previous
    assert out.stdout.strip() == 'machine_lock_timeout'


def test_live_entry_is_reused_and_stale_entries_dropped(tmp_path, monkeypatch):
    registry = tmp_path / CR.FILENAME
    CR.record(registry, 'ib', port=30000, pid=1, host='127.0.0.1')
    CR.record(registry, 'daily', port=30001, pid=2, host='127.0.0.1')
    monkeypatch.setattr(CR, 'alive', lambda entry: entry['port'] == 30000)
    assert CR.live(registry, 'ib')['port'] == 30000
    assert CR.live(registry, 'daily') is None
    assert set(CR.read(registry)) == {'ib'}


def test_dead_pid_and_foreign_process_are_not_alive():
    done = subprocess.Popen([sys.executable, '-c', 'pass'])
    done.wait()
    assert CR.alive(dict(pid=done.pid, port=30000)) is False
    # Живой процесс без 1cv8 и -TPort — переиспользованный pid или чужая программа.
    assert CR.alive(dict(pid=os.getpid(), port=30000)) is False


@pytest.mark.parametrize('value, valid', [('30000-30999', True), ('30000-30000', True),
                                          ('30999-30000', False), ('0-10', False), ('30000', False)])
def test_port_range_setting(value, valid):
    config = dict(base='ib', port_range=value)
    if valid:
        assert _profiles.validate('ib', config) == 'launch_client'
    else:
        with pytest.raises(_profiles.ProfileError):
            _profiles.validate('ib', config)


def test_profile_lookup_by_user(tmp_path, monkeypatch):
    file = tmp_path / 'profiles.yaml'
    file.write_text(
        "profiles:\n"
        "  ib: {base: dev-ib, user: admin}\n"
        "  'роль:kassir': {base: dev-ib, user: kassir, port_range: '30000-30999'}\n"
        "  'роль:manager': {base: dev-ib, user: manager}\n"
        "  manager-copy: {base: dev-ib, user: manager}\n"
        "  other: {base: other-ib, user: kassir}\n", encoding='utf8')
    monkeypatch.setenv('TC1C_PROFILES_FILE', str(file))
    assert _profiles.find('kassir', 'ib') == ['роль:kassir']
    assert _profiles.find('nobody', 'ib') == []
    assert sorted(_profiles.find('manager', 'ib')) == ['manager-copy', 'роль:manager']
    assert _profiles.registry_file() == tmp_path / CR.FILENAME


def test_example_profiles_load(monkeypatch):
    monkeypatch.setenv('TC1C_PROFILES_FILE', str(ROOT / 'profiles.example.yaml'))
    profiles, _ = _profiles.load()
    assert profiles['роль:kfk_user']['port_range'] == '30000-30999'


def profiles_file(tmp_path, monkeypatch, **extra):
    base = tmp_path / 'ib'
    base.mkdir()
    file = tmp_path / 'profiles.yaml'
    settings = ''.join(f', {k}: {v}' for k, v in extra.items())
    file.write_text("profiles:\n  'роль:kassir': {base: ib, user: kassir" + settings + "}\n", encoding='utf8')
    monkeypatch.setenv('TC1C_PROFILES_FILE', str(file))
    monkeypatch.setenv('TC1C_MACHINE_DIR', str(tmp_path / 'machine'))
    return tmp_path / CR.FILENAME


def test_launch_reuses_live_client_of_profile(tmp_path, monkeypatch):
    import _runtime as R
    registry = profiles_file(tmp_path, monkeypatch)
    CR.record(registry, 'роль:kassir', port=30005, pid=4242, host='127.0.0.1', version='8.3.27.1859')
    monkeypatch.setattr(CR, 'alive', lambda entry: True)
    connected = []
    monkeypatch.setattr(R, 'tc_connect', lambda port, version=None: connected.append((port, version)) or 'connected')
    result = R.Runtime().call('launch_client', {'profile': 'роль:kassir'})
    assert result['ok'] and result['reused'] is True and result['port'] == 30005
    assert result['profile'] == 'роль:kassir' and connected == [(30005, '8.3.27.1859')]


def test_launch_takes_port_from_pool_under_lock(tmp_path, monkeypatch):
    import _runtime as R
    start = free_block(2)
    held = occupy(start)
    exe = tmp_path / ('1cv8.exe' if os.name == 'nt' else '1cv8')
    exe.write_bytes(b'')
    profiles_file(tmp_path, monkeypatch, port_range=f"'{start}-{start + 1}'", exe=f"'{exe}'")
    monkeypatch.setenv('DISPLAY', ':0')
    launched = []

    class Exited:
        pid, returncode = 4242, 1

        def __init__(self, args, **kw):
            with pytest.raises(CR.RegistryError):
                CR.MachineLock(0.1).acquire()   # Блокировка машины держится во время запуска.
            launched.append(args)

        def poll(self):
            return 1
    monkeypatch.setattr(R.subprocess, 'Popen', Exited)
    try:
        result = R.Runtime().call('launch_client', {'profile': 'роль:kassir'})
    finally:
        held.close()
    assert result['ok'] is False and '-TPort%d' % (start + 1) in launched[0]
    CR.MachineLock(0.1).acquire().release()   # Снята после неудачного запуска.
    assert CR.read(tmp_path / CR.FILENAME) == {}
