import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import testpilot  # noqa: E402
import testpilot_pytest as plugin  # noqa: E402

pytest_plugins = ['pytester']

PROFILES = """profiles:
  ib: {base: dev-ib, user: kfk_admin}
  'роль:kfk_user': {base: dev-ib, user: kfk_user}
  'роль:kfk_user2': {base: dev-ib, user: twin}
  twin-copy: {base: dev-ib, user: twin}
"""

CONFTEST = r'''
import json
import pytest
import _runtime as R
import testpilot
import testpilot_pytest

R.LOGGING = False
EVENTS = []
RealClient = testpilot.Client


class FakeClient:
    def __init__(self, profile=None):
        self.profile = profile
        self.deleted = None
        EVENTS.append(['new', profile])

    class _runtime:
        logs = None

    def start(self):
        EVENTS.append(['start', self.profile])

    def reset(self):
        if self.profile == 'broken':
            raise testpilot.ActionError('reset', dict(ok=False, code='reset_failed', window={'key': 'Window[x]'}))
        EVENTS.append(['reset', self.profile])

    def close(self):
        EVENTS.append(['close', self.profile])

    def call(self, action, **kw):
        return {'ok': True}

    def as_user(self, login):
        return RealClient.as_user(self, login)

    def execute_code(self, context, code, parameters):
        if 'Ссылки' in parameters:
            EVENTS.append(['delete', [r['uuid'] for r in parameters['Ссылки']]])
            errors = [dict(ref=r, error='locked') for r in parameters['Ссылки'] if r['uuid'] == 'bad']
            return {'ok': True, 'result': dict(deleted=1, skipped=0, errors=errors)}
        return {'ok': True, 'result': {'Партнер': {'$type': 'ref', 'metadata': 'Справочник.П', 'uuid': 'p'},
                                       'Строки': [{'$type': 'ref', 'metadata': 'Справочник.К', 'uuid': 'k'}]}}


testpilot.Client = FakeClient
testpilot_pytest._ClientSession._reuse_failure = lambda self: None
testpilot_pytest._stop_test_logging = lambda client: None


def pytest_sessionfinish(session):
    with open('events.json', 'w', encoding='utf8') as f:
        json.dump(EVENTS, f, ensure_ascii=False)
'''


@pytest.fixture
def run(pytester, monkeypatch):
    pytester.makefile('.yaml', profiles=PROFILES)
    monkeypatch.setenv('TC1C_PROFILES_FILE', str(pytester.path / 'profiles.yaml'))
    pytester.makeconftest(CONFTEST)

    def run(source, *args):
        pytester.makepyfile(test_case=source)
        result = pytester.runpytest_subprocess('--tc-profile', 'ib', '-p', 'no:cacheprovider', *args)
        import json
        events = json.loads((pytester.path / 'events.json').read_text(encoding='utf8'))
        return result, events
    return run


def test_marker_selects_user_profile(run):
    result, events = run('''
import pytest

@pytest.mark.testpilot(user="kfk_user")
def test_one(testpilot):
    assert testpilot.profile == "роль:kfk_user"
''')
    result.assert_outcomes(passed=1)
    assert ['reset', 'роль:kfk_user'] in events


def test_two_users_in_one_test_and_next_test_reuses(run):
    result, events = run('''
def test_one(testpilot):
    kassir = testpilot.as_user("kfk_user")
    assert kassir.profile == "роль:kfk_user"
    assert testpilot.as_user("kfk_user") is kassir
    assert kassir.as_user("kfk_admin") is testpilot

def test_two(testpilot):
    assert testpilot.as_user("kfk_user").profile == "роль:kfk_user"
''', '--tc-client-scope', 'session')
    result.assert_outcomes(passed=2)
    assert events.count(['new', 'ib']) == 1 and events.count(['new', 'роль:kfk_user']) == 1
    assert events.count(['reset', 'роль:kfk_user']) == 2 and events.count(['reset', 'ib']) == 2
    assert events[-2:] in (
        [['close', 'ib'], ['close', 'роль:kfk_user']], [['close', 'роль:kfk_user'], ['close', 'ib']])


def test_test_scope_closes_every_user(run):
    result, events = run('''
def test_one(testpilot):
    testpilot.as_user("kfk_user")
''')
    result.assert_outcomes(passed=1)
    assert ['close', 'ib'] in events and ['close', 'роль:kfk_user'] in events


@pytest.mark.parametrize('user, listed', [('nobody', '[]'), ('twin', 'twin-copy')])
def test_missing_or_ambiguous_profile_fails_setup(run, user, listed):
    result, _ = run(f'''
import pytest

@pytest.mark.testpilot(user="{user}")
def test_one(testpilot):
    pass
''')
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([f'*{listed}*'])


def test_reset_failure_fails_setup(run):
    result, _ = run('''
import pytest

@pytest.mark.testpilot(profile="broken")
def test_one(testpilot):
    pass
''')
    result.assert_outcomes(errors=1)


def test_data_is_deleted_in_reverse_order_and_failures_listed(run, pytester):
    result, events = run('''
def test_ok(testpilot_data):
    testpilot_data.create("...")
    testpilot_data.track({"$type": "ref", "metadata": "Документ.Р", "uuid": "d"})

def test_failed_delete(testpilot_data):
    testpilot_data.track({"$type": "ref", "metadata": "Документ.Р", "uuid": "bad"})
    assert False, "test failure does not skip deletion"
''', '--tc-artifacts', 'art')
    assert ['delete', ['d', 'k', 'p']] in events and ['delete', ['bad']] in events
    result.assert_outcomes(passed=1, failed=1, errors=1)
    result.stdout.fnmatch_lines(['*was not deleted*locked*'])
    summary = json.loads(next((pytester.path / 'art').glob('test_failed_delete*/result.json')).read_text(encoding='utf8'))
    assert summary['data_error'][0]['error'] == 'locked'


def test_ref_from_navigation_link():
    assert plugin.ref_from_url('e1cib/data/Справочник.Контрагенты?ref=8ca0000d8843cd1b11dc8d8c3d7a1aab') == {
        '$type': 'ref', 'metadata': 'Справочник.Контрагенты', 'uuid': '3d7a1aab-8d8c-11dc-8ca0-000d8843cd1b'}
    assert plugin.ref_from_url('e1cib/list/Документ.Р') is None


class Windows(testpilot.Client):
    """Client.reset over a scripted window stack."""

    def __init__(self, windows, stuck=False):
        self.windows, self.stuck, self.calls = windows, stuck, []

    def find_objects(self, **criteria):
        return []

    def call(self, action, check=True, **kw):
        self.calls.append((action, kw.get('answer')))
        if action == 'get_active_window':
            return self.windows[-1]
        if action == 'close_window' and not self.stuck:
            self.windows.pop()
        return {'ok': action != 'answer_dialog'}


def test_reset_closes_windows_to_start_page():
    client = Windows([dict(key='Home', home_page=True), dict(key='List'), dict(key='Doc', title='Реализация')])
    assert client.reset()['key'] == 'Home'
    assert client.calls.count(('close_window', None)) == 2 and ('answer_dialog', 'Нет') in client.calls


def test_reset_reports_window_that_did_not_close():
    client = Windows([dict(key='Home', home_page=True), dict(key='Doc', title='Реализация')], stuck=True)
    with pytest.raises(testpilot.ActionError) as error:
        client.reset(max_windows=2)
    assert error.value.code == 'reset_failed' and error.value.result['window']['key'] == 'Doc'
