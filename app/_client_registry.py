"""Machine-wide port pool and the per-tree registry of running test clients (.testpilot-clients.json)."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import time

FILENAME = '.testpilot-clients.json'


class RegistryError(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details

    def result(self):
        return dict(ok=False, code=self.code, error=str(self), **self.details)


def parse_range(text):
    match = re.fullmatch(r'\s*(\d{1,5})\s*-\s*(\d{1,5})\s*', text) if isinstance(text, str) else None
    if not match:
        return None
    start, end = int(match[1]), int(match[2])
    return (start, end) if 1 <= start <= end <= 65535 else None


def machine_dir():
    configured = os.environ.get('TC1C_MACHINE_DIR', '').strip()
    if configured:
        return Path(configured).expanduser()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / '1c-testpilot'
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state') / '1c-testpilot'


class MachineLock:
    """Exclusive lock on launch.lock in the machine directory, shared by every testpilot process."""

    def __init__(self, wait):
        self.wait, self.stream = wait, None

    def acquire(self):
        directory = machine_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.stream = open(directory / 'launch.lock', 'a+b')
        deadline = time.monotonic() + self.wait
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self.stream.seek(0)
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.stream.close()
                    self.stream = None
                    raise RegistryError('machine_lock_timeout', 'Another testpilot process is launching a client. Retry later.',
                                        lock=str(directory / 'launch.lock'))
                time.sleep(0.1)

    def release(self):
        if self.stream is None:
            return
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None


@contextmanager
def machine_lock(wait):
    lock = MachineLock(wait).acquire()
    try:
        yield lock
    finally:
        lock.release()


def port_free(port):
    with socket.socket() as s:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind(('127.0.0.1', port))
        except OSError:
            return False
        return True


def first_free(port_range, exclude=()):
    """First port of the range that can be bound now; call it under the machine lock."""
    start, end = port_range
    busy = []
    for port in range(start, end + 1):
        if port not in exclude and port_free(port):
            return port
        busy.append(port)
    raise RegistryError('port_pool_exhausted', f'All test-client ports {start}-{end} are busy.', busy_ports=busy)


def path(profiles_path):
    return Path(profiles_path).parent / FILENAME


def read(file):
    try:
        data = json.loads(Path(file).read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(file, data):
    file = Path(file)
    fd, temporary = tempfile.mkstemp(prefix=FILENAME, dir=file.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, file)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def record(file, profile, **entry):
    data = read(file)
    data[profile] = dict(entry, started=time.strftime('%Y-%m-%dT%H:%M:%S'))
    _write(file, data)


def forget(file, profile, port=None):
    data = read(file)
    if profile in data and (port is None or data[profile].get('port') == port):
        data.pop(profile)
        _write(file, data)


def owned(entry):
    """The process of a registry entry is still our 1C client: name 1cv8* and -TPort<port>, listening or not."""
    import psutil
    try:
        pid, port = int(entry['pid']), int(entry['port'])
        process = psutil.Process(pid)
        name = process.name().lower()
        arguments = [a.lower() for a in process.cmdline()]
    except (KeyError, TypeError, ValueError, psutil.Error):
        return False
    # Имя и -TPort защищают от pid, который ОС уже отдала другому процессу.
    return name.startswith('1cv8') and f'-tport{port}' in arguments


def alive(entry):
    """A registry entry still names our 1C test client: its process, command line and listening port."""
    if not owned(entry):
        return False
    port = int(entry['port'])
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def live(file, profile):
    """The live entry of a profile, dropping a stale one."""
    entry = read(file).get(profile)
    if entry is None:
        return None
    if alive(entry):
        return entry
    forget(file, profile, entry.get('port'))
    return None
