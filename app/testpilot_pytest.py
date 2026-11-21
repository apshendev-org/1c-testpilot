"""Pytest fixtures for direct 1C testing. Loaded by the testpilot pytest entry point."""
import hashlib
import json
import os
import logging
from pathlib import Path
import re
import time
import uuid

import pytest
import _log_reports
from _effects import ref_from_url  # noqa: F401  (часть API плагина)


def pytest_addoption(parser):
    group = parser.getgroup('testpilot', '1C Testpilot')
    group.addoption('--tc-profile', help='YAML profile from TC1C_PROFILES_FILE for the testpilot fixture.')
    group.addoption('--tc-artifacts', default='test-results', help='Directory for per-test Testpilot artifacts.')
    group.addoption('--tc-reports', help='html, allure, html,allure, or none (JSONL only); default TC1C_LOG_REPORTS or html.')
    group.addoption('--tc-screenshots', choices=('off', 'actions', 'all'), default='off',
                    help='Call-journal screenshots; default off. Requires server screenshot settings to allow capture.')
    group.addoption('--tc-client-scope', choices=('test', 'session'), default='test',
                    help='Client lifetime: test (default) or session. Session reuses application state; '
                         'journals and artifacts remain separate for each test.')


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    config.addinivalue_line('markers', 'testpilot(user=None, profile=None): infobase user or profile of the testpilot client.')
    try:
        config._testpilot_reports = _log_reports.formats(config.getoption('--tc-reports')
                                                        or os.environ.get('TC1C_LOG_REPORTS', 'html'))
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from None
    if 'allure' in config._testpilot_reports:
        if not hasattr(config.option, 'allure_report_dir'):
            raise pytest.UsageError('Allure reports require allure-pytest. Install 1c-testpilot[allure] '
                                    'and enable its pytest plugin (allure_pytest.plugin).')
        if not config.option.allure_report_dir:
            config.option.allure_report_dir = str(Path(config.getoption('--tc-artifacts')) / 'allure-results')


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, '_testpilot_report_' + report.when, report)


@pytest.fixture
def testpilot_artifacts(request):
    """Unique artifact directory for this test, including parameterized/parallel runs."""
    name = re.sub(r'[^\w.-]+', '_', request.node.name)[:70]
    digest = hashlib.sha256(request.node.nodeid.encode('utf8')).hexdigest()[:10]
    directory = Path(request.config.getoption('--tc-artifacts')).resolve() / f'{name}-{digest}-{uuid.uuid4().hex[:8]}'
    directory.mkdir(parents=True)
    request.node.user_properties.append(('testpilot_artifacts', str(directory)))
    return directory


class _ClientSession:
    """Own the client until close succeeds, including partially failed starts."""

    def __init__(self, profile):
        self.profile = profile
        self.client = None
        self.started = False
        self.recovery = None

    def prepare(self, logs):
        from testpilot import Client
        self.recovery = None
        if self.client is not None:
            reason = self._reuse_failure() if self.started else 'previous_setup_or_cleanup_failed'
            if reason:
                self.recovery = reason
                logging.getLogger(__name__).warning('Preparing a new Testpilot client: %s', reason)
                self.close()  # Do not replace an owner whose cleanup failed.
        if self.client is None:
            self.client = Client(profile=self.profile)
            self.client._runtime.logs = logs
            self.client.start()
            self.started = True
        else:
            self.client._runtime.logs = logs
        return self.client

    def _reuse_failure(self):
        from testpilot import ActionError
        import _connections
        client = self.client
        with client._access('pytest_prepare'):
            if client._closed:
                return 'client_closed'
            pool = client._runtime.pool
            with pool.lock:
                entry = next(iter(pool.entries.values()), None)
            if entry is None:
                return 'disconnected'
            with pool.use(entry, action='pytest_prepare'):
                proc = entry.state.get('launched_process')
                if proc is not None and proc.poll() is not None:
                    return 'process_exited'
                wire = entry.state.get('client')
                if not _connections.client_connected(wire):
                    return 'connection_closed'
                if getattr(wire, '_pending', 0):
                    # Read only outstanding replies; never send a probe or repeat an action.
                    previous = wire._io_deadline
                    deadline = time.monotonic() + wire.RESYNC_TIMEOUT
                    wire._io_deadline = min(previous, deadline) if previous is not None else deadline
                    try:
                        wire._resync()
                    except (OSError, RuntimeError) as exc:
                        raise ActionError('pytest_prepare', dict(ok=False, code='connection_not_ready',
                            error='The previous reply could not be recovered. The client was not restarted; '
                                  'the previous action may still be running.', details=str(exc))) from exc
                    finally:
                        wire._io_deadline = previous
        return None

    def close(self):
        if self.client is not None:
            self.started = False
            try:
                self.client.close()
            finally:
                _stop_test_logging(self.client)
            self.client = None


class _Sessions:
    """Clients by profile: several users of one test work at the same time."""

    def __init__(self):
        self.items = {}

    def get(self, profile):
        if profile not in self.items:
            self.items[profile] = _ClientSession(profile)
        return self.items[profile]

    def close(self):
        errors = []
        for session in self.items.values():
            try:
                session.close()
            except Exception as exc:
                errors.append(f'{session.profile}: {exc}')
        if errors:
            raise RuntimeError('; '.join(errors))


@pytest.fixture(scope='session')
def _testpilot_session(request):
    sessions = _Sessions()
    try:
        yield sessions
    finally:
        sessions.close()


@pytest.fixture
def testpilot_user(request):
    """Infobase user of the testpilot client; set it with indirect parametrization."""
    return getattr(request, 'param', None)


def _user_profile(base, user):
    """The single profile with this user and the base of the --tc-profile profile."""
    import _runtime as R
    from testpilot import ActionError
    found = R._profiles.find(user, base)
    if len(found) != 1:
        raise ActionError('as_user', dict(ok=False, code='ambiguous_profile' if found else 'profile_not_found',
            error=f'Expected one profile with user {user!r} and the base of {base!r}, found {len(found)}.',
            profiles=found))
    return found[0]


def _stop_test_logging(client):
    # Finalize even if the test disconnected or closed Client itself.
    with client._access('pytest_stop_logging'):
        with client._runtime.pool.lock:
            states = [entry.state for entry in client._runtime.pool.entries.values()]
        for state in [client._runtime.legacy, *states]:
            journal = state.get('_call_journal')
            if journal is not None:
                journal.stop()


@pytest.fixture
def testpilot(request, testpilot_artifacts, testpilot_user):
    """Per-test artifacts and a test- or session-owned client selected by the profile.

    The client starts at the start page (Client.reset). @pytest.mark.testpilot(user=…|profile=…)
    or the testpilot_user parameter selects its user; testpilot.as_user(login) gives the client of
    another user of the same infobase without restarting either.
    """
    base = request.config.getoption('--tc-profile')
    if not base:
        raise pytest.UsageError('The testpilot fixture requires --tc-profile and TC1C_PROFILES_FILE.')
    import _runtime as R
    from testpilot import ActionError
    marker = request.node.get_closest_marker('testpilot')
    options = dict(marker.kwargs) if marker else {}
    user = options.get('user') or testpilot_user
    try:
        profile = options.get('profile') or (_user_profile(base, user) if user else base)
    except ActionError as exc:
        pytest.fail(f"{exc}: {exc.result.get('profiles')}", pytrace=False)

    mode = request.config.getoption('--tc-screenshots')
    if mode != 'off' and (not R.SCREENSHOTS or not R.LOGGING or not R._call_logging.enabled('TC1C_LOG_SCREENSHOTS')):
        raise pytest.UsageError('Screenshot logging must be enabled to use --tc-screenshots.')
    shared = request.config.getoption('--tc-client-scope') == 'session'
    sessions = request.getfixturevalue('_testpilot_session') if shared else _Sessions()
    session = sessions.get(profile)
    reports = getattr(request.config, '_testpilot_reports', None)
    allure_enabled = reports is not None and 'allure' in reports
    def journal(root):
        if not R.LOGGING:
            return None
        return R._call_logging.Store(root=root,
            screenshots=mode != 'off', default_mode=mode, reports=reports,
            allure_factory=_log_reports.PytestAllure if allure_enabled else None,
            allure_directory=request.config.option.allure_report_dir if allure_enabled else None)
    logs = journal(testpilot_artifacts)
    used = {}

    def as_user(login):
        return use(_user_profile(base, login))

    def bind(client):
        client._user_resolver = as_user
        # Код, запросы и проверка проведения клиента без обработки Testpilot идут через клиент --tc-profile.
        client._runtime.admin_profile = base
        client._runtime.admin = use

    def use(other):
        if other in used:
            return used[other]
        other_session = sessions.get(other)
        used[other] = None   # Сессия учтена для закрытия, даже если запуск упадёт.
        other_client = other_session.prepare(journal(testpilot_artifacts / re.sub(r'[^\w.-]+', '_', other)))
        if R.LOGGING:
            other_client.start_logging(screenshot_mode=mode)
        other_client.reset()
        bind(other_client)
        used[other] = other_client
        return other_client
    # Слепки неподтверждённых кликов попадают в артефакты этого теста.
    artifacts_env = os.environ.get('TC1C_ARTIFACTS_DIR')
    os.environ['TC1C_ARTIFACTS_DIR'] = str(testpilot_artifacts)
    cleanup_error = None
    diagnostics = None
    client = None
    prepared = False
    setup_error = None
    try:
        client = session.prepare(logs)
        if R.LOGGING:
            client.start_logging(screenshot_mode=mode)
        client.reset()
        bind(client)
        used[profile] = client
        prepared = True
        yield client
    except Exception as exc:
        if not prepared:
            setup_error = str(exc)
        raise
    finally:
        report = getattr(request.node, '_testpilot_report_call', None)
        setup = getattr(request.node, '_testpilot_report_setup', None)
        if prepared and ((report and report.failed) or (setup and setup.failed)):
            try:
                # No table selection or editing during failure diagnostics.
                diagnostics = client.call('get_context', result_mode='full', check=False)
            except Exception as exc:
                diagnostics = {'ok': False, 'error': str(exc)}
        for name in used:
            current = sessions.get(name)
            try:
                if not shared or (not prepared and not current.started):
                    current.close()
                elif current.client is not None and R.LOGGING:
                    _stop_test_logging(current.client)
            except Exception as exc:
                cleanup_error = (cleanup_error + '; ' if cleanup_error else '') + f'{name}: {exc}'
                current.started = False
        if profile not in used:
            try:
                if not shared or not session.started:
                    session.close()
            except Exception as exc:
                cleanup_error = (cleanup_error + '; ' if cleanup_error else '') + str(exc)
                session.started = False
        if artifacts_env is None:
            os.environ.pop('TC1C_ARTIFACTS_DIR', None)
        else:
            os.environ['TC1C_ARTIFACTS_DIR'] = artifacts_env
        summary = {'test': request.node.nodeid,
                   'outcome': report.outcome if report else (setup.outcome if setup else 'setup_failed'),
                   'cleanup_error': cleanup_error}
        if setup_error is not None:
            summary['setup_error'] = setup_error
        if getattr(request.node, '_testpilot_data_error', None) is not None:
            summary['data_error'] = request.node._testpilot_data_error
        if session.recovery is not None:
            summary['client_recovery'] = session.recovery
        (testpilot_artifacts/'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
        if diagnostics is not None:
            (testpilot_artifacts/'context.json').write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding='utf8')
        if allure_enabled:
            try:
                import allure
                for name, data in [('Testpilot result', summary), ('Form context', diagnostics)]:
                    if data is not None:
                        allure.attach(json.dumps(R._call_logging.clean(R._profiles.redact(data)), ensure_ascii=False),
                                      name=name, attachment_type=allure.attachment_type.JSON)
            except Exception as exc:
                logging.getLogger(__name__).warning('Could not attach Testpilot diagnostics to Allure: %s', exc)
        if cleanup_error is not None and setup_error is None:
            pytest.fail('Testpilot cleanup failed: ' + cleanup_error, pytrace=False)


_DELETE = '''
Результат = Новый Структура("deleted,skipped,errors", 0, 0, Новый Массив);
Для Каждого Ссылка Из Параметры["Ссылки"] Цикл
    Попытка
        Объект = Ссылка.ПолучитьОбъект();
        Если Объект = Неопределено Тогда
            Результат.skipped = Результат.skipped + 1;
        Иначе
            // Режим загрузки: подписки и проверки не мешают удалять в любом порядке.
            Объект.ОбменДанными.Загрузка = Истина;
            Если Метаданные.Документы.Содержит(Объект.Метаданные()) Тогда
                // Отмена проведения в загрузке запрещена, а Удалить() движения не трогает: пустые наборы их стирают.
                Для Каждого Движения Из Объект.Движения Цикл
                    Движения.ОбменДанными.Загрузка = Истина;
                    Движения.Записать();
                КонецЦикла;
            КонецЕсли;
            Объект.Удалить();
            Результат.deleted = Результат.deleted + 1;
        КонецЕсли;
    Исключение
        Результат.errors.Добавить(Новый Структура("ref,error", Ссылка, КраткоеПредставлениеОшибки(ИнформацияОбОшибке())));
    КонецПопытки;
КонецЦикла;
'''


def _is_ref(value):
    return isinstance(value, dict) and value.get('$type') == 'ref' and isinstance(value.get('metadata'), str)


def _refs_in(value):
    if _is_ref(value):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _refs_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs_in(item)


class TestData:
    """Objects created by a test; deleted after it in reverse order."""
    __test__ = False

    def __init__(self, client):
        self.client, self.refs = client, []

    def track(self, ref):
        if not _is_ref(ref):
            raise TypeError('track expects a reference value: {"$type": "ref", "metadata": ..., "uuid": ...}.')
        if ref not in self.refs:
            self.refs.append(ref)
        return ref

    def create(self, code, parameters=None):
        """Run server code and track every reference in its Результат."""
        result = self.client.execute_code(context='server', code=code, parameters=parameters or {})['result']
        for ref in _refs_in(result):
            self.track(ref)
        return result

    def track_window(self):
        """Track the object of the active form; it must already be written."""
        from testpilot import ActionError
        window = self.client.call('get_active_window')
        ref = ref_from_url(window.get('url'))
        if ref is None:
            raise ActionError('track_window', dict(ok=False, code='window_ref_unavailable',
                error='The active window is not a written object form. Write the object first.',
                window={k: window.get(k) for k in ('key', 'title', 'url')}))
        return self.track(ref)

    def cleanup(self):
        if not self.refs:
            return None
        try:
            self.client.reset()   # Открытая модифицированная форма держит блокировку объекта.
        except Exception:
            pass
        return self.client.execute_code(context='server', code=_DELETE,
                                        parameters={'Ссылки': list(reversed(self.refs))})['result']


@pytest.fixture
def testpilot_data(testpilot, request):
    """create(code, parameters), track(ref), track_window(); deletion after the test, even a failed one."""
    data = TestData(testpilot)
    yield data
    try:
        result = data.cleanup()
    except Exception as exc:
        request.node._testpilot_data_error = str(exc)   # testpilot завершается позже и пишет это в result.json
        raise
    if result and result.get('errors'):
        request.node._testpilot_data_error = result['errors']
        pytest.fail('Testpilot data was not deleted: ' + json.dumps(result['errors'], ensure_ascii=False),
                    pytrace=False)
