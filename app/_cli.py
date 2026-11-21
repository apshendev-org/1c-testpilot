"""Load explicit startup configuration before importing the MCP server; client start/stop commands."""
import argparse
import json
from pathlib import Path
import sys


def parser():
    root = argparse.ArgumentParser(prog='1c-testpilot', description='1C Testpilot MCP server; without a command runs the server.')
    root.add_argument('--env-file', metavar='PATH',
                      help='Load a UTF-8 .env file; existing environment variables take precedence.')
    commands = root.add_subparsers(dest='command')
    client = commands.add_parser('client', help='Start or stop a test client without the MCP server.')
    actions = client.add_subparsers(dest='client_command', required=True)
    start = actions.add_parser('start', help='Launch a client by profile (or reuse its running client), '
                                             'prepare Testpilot.epf, disconnect and leave it running.')
    start.add_argument('--profile', required=True, help='Profile name from TC1C_PROFILES_FILE.')
    stop = actions.add_parser('stop', help='Stop a client started by client start.')
    target = stop.add_mutually_exclusive_group(required=True)
    target.add_argument('--profile', help='Profile whose client is recorded in .testpilot-clients.json.')
    target.add_argument('--pid', type=int, help='Process id printed by client start.')
    return root


def configure(argv=None):
    root = parser()
    args = root.parse_args(argv)
    if args.env_file is not None:
        try:
            with Path(args.env_file).open(encoding='utf-8-sig') as stream:
                from dotenv import load_dotenv
                load_dotenv(stream=stream, override=False)
        except OSError as exc:
            root.error(f'Cannot read env file {args.env_file!r}: {exc.strerror or type(exc).__name__}')
        except UnicodeError:
            root.error(f'Cannot read env file {args.env_file!r}: expected UTF-8 text.')
    return args


def _emit(data, stream=None):
    print(json.dumps(data, ensure_ascii=False), file=stream or sys.stdout)


def client_start(profile):
    from testpilot import ActionError, Client
    client = Client(profile=profile)
    try:
        result = client.start()
    except ActionError as exc:
        # Неудачный запуск launch_client уже остановил свой процесс.
        _emit({k: v for k, v in exc.result.items() if k in ('code', 'error', 'dialog', 'connect_error', 'pid', 'client_stopped')}
              | dict(ok=False, code=exc.code), sys.stderr)
        return 1
    # Отключение, а не close(): процесс 1С продолжает работать для pytest и MCP.
    client.call('disconnect', check=False)
    _emit(dict(ok=True, profile=profile, pid=result.get('pid'), host='127.0.0.1', port=result.get('port'),
               version=result.get('version'), execution_ready=result.get('execution_ready'),
               reused=bool(result.get('reused')),
               **({'execution_reason': result['execution_reason']} if result.get('execution_reason') else {})))
    return 0


def _terminate(pid):
    """Stop a 1cv8 process; False if it is already gone. Never signals other programs."""
    import psutil
    try:
        process = psutil.Process(pid)
        if not process.name().lower().startswith('1cv8'):
            raise ValueError(f'Process {pid} is not a 1C client.')
        process.terminate()
        process.wait(timeout=15)
    except psutil.NoSuchProcess:
        return False
    except psutil.TimeoutExpired:
        process.kill()
    return True


def client_stop(profile=None, pid=None):
    import _client_registry as registry
    import _profiles
    file = _profiles.registry_file()
    entries = registry.read(file) if file is not None else {}
    if profile is not None:
        entry = entries.get(profile)
        if entry is None or not registry.alive(entry):
            if entry is not None:
                registry.forget(file, profile)
            _emit(dict(ok=True, profile=profile, stopped=False))
            return 0
        pid = entry['pid']
    try:
        stopped = _terminate(pid)
    except ValueError as exc:
        _emit(dict(ok=False, code='not_a_test_client', error=str(exc)), sys.stderr)
        return 1
    for name, entry in entries.items():
        if entry.get('pid') == pid:
            registry.forget(file, name)
    _emit(dict(ok=True, pid=pid, stopped=stopped, **({'profile': profile} if profile else {})))
    return 0


def main(argv=None):
    args = configure(argv)
    if args.command == 'client':
        if args.client_command == 'start':
            sys.exit(client_start(args.profile))
        sys.exit(client_stop(args.profile, args.pid))
    from server import main as run_server
    run_server()


if __name__ == '__main__':
    main()
