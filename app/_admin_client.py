"""Админ-клиент той же базы: код, запросы и проверки за клиента без обработки Testpilot."""
import _profiles
from _code_execution import Failure

DEFAULT = 'ib'
_clients = {}   # профиль -> testpilot.Client, поднятый движком (MCP и Python без pytest)


def profile(S):
    """Admin profile for the current connection: the caller's choice, else DEFAULT; same base and server."""
    own = S._state.get('profile')
    preferred = getattr(S._execution.get(), 'admin_profile', None)
    try:
        profiles, _ = _profiles.load()
    except _profiles.ProfileError:
        profiles = {}
    config = profiles.get(own) if own else None
    if not config or not config.get('base'):
        raise Failure('admin_client_unavailable', 'This client has no Testpilot processing and was not launched by '
                      f'a profile with base, so no admin client of its base is known. Launch it by profile and add '
                      f'profile "{DEFAULT}" for the same base with an administrator user.', profile=DEFAULT)
    for name in (preferred, DEFAULT):
        other = profiles.get(name) if name and name != own else None
        if (other and other.get('base') == config['base']
                and bool(other.get('server', False)) == bool(config.get('server', False))):
            return name
    raise Failure('admin_client_unavailable', f'This client has no Testpilot processing. Add profile "{DEFAULT}" '
                  f'with base {config["base"]!r} and an administrator user: code, queries and posting checks run there.',
                  profile=DEFAULT)


def client(S):
    """(profile, Client) of the admin client; started on demand, reusing a running client of the profile."""
    name = profile(S)
    resolver = getattr(S._execution.get(), 'admin', None)
    if resolver is not None:
        return name, resolver(name)
    found = _clients.get(name)
    if found is None or found._closed:
        from testpilot import ActionError, Client
        found = Client(profile=name)
        try:
            found.start()
        except ActionError as exc:
            raise Failure('admin_client_unavailable', f'The admin client {name!r} did not start: {exc}',
                          profile=name, cause=exc.result) from None
        _clients[name] = found
    return name, found


def call(S, action, arguments):
    """Run an action in the admin client; the result names the profile in delegated_to."""
    name, admin = client(S)
    result = admin.call(action, check=False, **{k: v for k, v in arguments.items() if v is not None})
    return dict(result, delegated_to=name) if isinstance(result, dict) else result
