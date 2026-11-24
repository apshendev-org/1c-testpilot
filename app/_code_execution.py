"""Optional execution through the protected Testpilot external processing form."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import html
import json
import os
from pathlib import Path
import re
import time
import uuid

import guids as G
import tc1c

FORM_NAME = 'ВнешняяОбработка.Testpilot.Форма.Helper'
HELPER_FORM_NAMES = frozenset({FORM_NAME, 'ExternalDataProcessor.Testpilot.Form.Helper'})
# Форма одного запроса: Helper открывает её над активной формой, она закрывается после ответа.
REQUEST_FORM_NAMES = frozenset({'ВнешняяОбработка.Testpilot.Форма.Request', 'ExternalDataProcessor.Testpilot.Form.Request'})
FORM_NAMES = HELPER_FORM_NAMES | REQUEST_FORM_NAMES
PROTOCOL = 1
_internal = ContextVar('testpilot_service_access', default=None)


class Failure(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.result = dict(ok=False, code=code, error=message, **details)


def _flag(name):
    value = os.environ.get(name, 'false').strip().lower()
    if value not in ('true', 'false', '1', '0', 'yes', 'no', 'on', 'off'):
        raise ValueError(name + ' must be true or false')
    return value in ('true', '1', 'yes', 'on')


@dataclass(frozen=True)
class Settings:
    code: bool
    query: bool
    epf: str
    metadata: str = 'auto'
    functions: bool = False
    form_details: str = 'auto'

    @property
    def metadata_enabled(self):
        return self.code or self.query if self.metadata == 'auto' else self.metadata == 'true'

    @property
    def enabled(self):
        return self.code or self.query or self.metadata_enabled or self.functions or self.form_details == 'true'


def settings():
    form_details = os.environ.get('TC1C_FORM_DETAILS', 'auto').strip().lower()
    if form_details not in ('auto', 'true', 'false'):
        raise ValueError('TC1C_FORM_DETAILS must be auto, true or false')
    metadata = os.environ.get('TC1C_METADATA', 'auto').strip().lower()
    if metadata not in ('auto', 'true', 'false'):
        raise ValueError('TC1C_METADATA must be auto, true or false')
    return Settings(_flag('TC1C_CODE_EXECUTION'), _flag('TC1C_QUERY_EXECUTION'),
                    os.environ.get('TC1C_CODE_EPF', '').strip(), metadata, _flag('TC1C_FUNCTIONS'), form_details)


SETTINGS = settings()


# BSL strings continue through lines starting with |. Blank/comment lines between
# their parts are not string content; quotes in those comments cannot end a string.
_BSL_STRING_PART = r'(?:""|[^"\n])*'
_BSL_STRING_GAP = r'(?:[ \t\f\v]*(?://[^\n]*)?\n)*[ \t\f\v]*'
_BSL_STRING = rf'"{_BSL_STRING_PART}(?:\n{_BSL_STRING_GAP}\|{_BSL_STRING_PART})*"'
_BSL_TOKENS = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|' + _BSL_STRING + r'|[\w]+|[^\s]', re.UNICODE)
_QUERY_TOKENS = re.compile(r'//[^\r\n]*|/\*[\s\S]*?\*/|"(?:""|[^"])*"|[\w]+|[^\s]', re.UNICODE)


def _bsl_lines(text):
    """Normalize CRLF/lone CR without shifting offsets in the original code."""
    return text.replace('\r\n', ' \n').replace('\r', '\n')


def tokens(text, *, bsl=True):
    """Yield identifiers/punctuation with positions; strings and comments are opaque."""
    pattern = _BSL_TOKENS if bsl else _QUERY_TOKENS
    for match in pattern.finditer(_bsl_lines(text) if bsl else text):
        word = match.group()
        if word.startswith(('//', '/*', '"')):
            if word == '"':
                raise Failure('invalid_code', 'Unterminated string literal.')
            continue
        yield word.casefold(), match.start(), match.end()


def validate_code(code):
    if not isinstance(code, str) or not code.strip():
        raise Failure('invalid_code', 'code must be a nonempty string.')
    # Identifiers are not filtered: the 1C user's rights are the boundary. Only reject malformed text.
    for _ in tokens(code):
        pass


def prepare_query(query):
    if not isinstance(query, str) or not query.strip():
        raise Failure('invalid_query', 'query must be nonempty query text.')
    try:
        parsed = list(tokens(query, bsl=False))
    except Failure as exc:
        raise Failure('invalid_query', str(exc)) from None
    if not parsed:
        raise Failure('invalid_query', 'query must be nonempty query text.')
    # A batch has independent statements separated by top-level semicolons.
    # Add ALLOWED to the first SELECT of each statement, never to UNION branches
    # or nested selections. Leave strings, comments and all other syntax to 1C.
    additions = []
    statement_start, depth = True, 0
    for index, (word, start, end) in enumerate(parsed):
        if word == ';' and depth == 0:
            statement_start = True
            continue
        if statement_start:
            if word in ('выбрать', 'select'):
                following = parsed[index + 1][0] if index + 1 < len(parsed) else None
                if following not in ('разрешенные', 'allowed'):
                    additions.append((end, ' РАЗРЕШЕННЫЕ' if word == 'выбрать' else ' ALLOWED'))
            statement_start = False
        if word == '(':
            depth += 1
        elif word == ')':
            depth -= 1
    for end, addition in reversed(additions):
        query = query[:end] + addition + query[end:]
    return query


@contextmanager
def internal(client):
    token = _internal.set(client)
    try:
        yield
    finally:
        _internal.reset(token)


def protected(client, key):
    return bool(key and any(key == root or key.startswith(root + '.')
                for root in vars(client).get('_service_roots', ())))


def internal_access(client):
    return _internal.get() is client


def guard(client, method, key):
    if _internal.get() is client:
        return
    # A server may reconnect with execution disabled while a previously opened
    # service still exists. Identify its form before accepting even guessed keys.
    if key and vars(client).get('_service_guard_installed') and not protected(client, key):
        window = key.split('.', 1)[0]
        checked = vars(client).setdefault('_service_checked_windows', set())
        if window.startswith(('MainFrame[', 'SecondaryFrame[')) and window not in checked:
            with internal(client):
                reply = client.send_cmd(G.GET_CHILD_OBJECTS, window, kind='read', middle=b'\xe1' + b'\x81' * 7)
                if reply.get('ok'):
                    objects = tc1c.decode_collection(reply['raw'], window)
                    filter_objects(client, objects)
                    if any(o.get('class') == 'ManagedForm' for o in objects):
                        checked.add(window)
                else:
                    raise Failure('window_identity_unavailable', 'Could not identify the target window before accessing it.')
    if protected(client, key):
        raise Failure('service_form_protected', 'Use the dedicated Testpilot processing tools to access this form.')


def filter_objects(client, objects):
    if client is None:
        return objects
    roots = vars(client).setdefault('_service_roots', set())
    for obj in objects:
        if obj.get('class') == 'ManagedForm' and obj.get('form_name') and obj.get('key'):
            vars(client).setdefault('_service_checked_windows', set()).add(obj['key'].split('.ManagedForm[', 1)[0])
        if obj.get('form_name') in FORM_NAMES:
            roots.add(obj['key'].split('.ManagedForm[', 1)[0])
    if _internal.get() is client:
        return objects
    return [obj for obj in objects if not protected(client, obj.get('key'))]


def install(client):
    client._service_guard_installed = True
    client._command_guard = lambda method, key: guard(client, method, key)


def check_screenshot(client):
    if client is not None and (vars(client).get('_service_guard_installed') or vars(client).get('_service_roots')):
        # OS capture does not pass through send_cmd and needs its own target check.
        reply = client.send_cmd(G.GET_ACTIVE_WINDOW, None, kind='read', middle=tc1c.RES_COLLECTION)
        keys = tc1c.extract_object_keys(reply['raw']) if reply.get('ok') else []
        if not keys:
            if reply.get('ok') and tc1c.empty_object_reply(reply['raw'], G.GET_ACTIVE_WINDOW):
                return  # Native preview: the OS capture identifies this window.
            raise Failure('screenshot_target_unavailable', 'Could not identify the active window for screenshot capture.')
        guard(client, G.GET_ACTIVE_WINDOW, keys[0])


def packaged_epf():
    """Testpilot.epf installed with the package."""
    from importlib.resources import files
    return Path(str(files('testpilot_assets') / 'Testpilot.epf'))


def launch_path(override=None, *, python_api=False):
    """Processing to open with the client: override, TC1C_CODE_EPF, else the packaged file; '' disables it."""
    if not python_api and not SETTINGS.enabled:
        return None
    if override == '':
        return None
    value = override if override is not None else SETTINGS.epf
    path = Path(value).expanduser().absolute() if value else packaged_epf()
    if not path.is_file() or path.suffix.lower() != '.epf':
        raise Failure('execution_not_configured', 'The configured Testpilot.epf file is unavailable.')
    return str(path)


def _configured_warning(message, path):
    if not isinstance(message, str):
        return False
    question = any(text in message for text in (
        'Разрешить открывать данный файл?', 'Allow opening this file?',
        'Do you want to open the file?'))
    filename = re.search(r'(?:из файла|from (?:the )?file)\s+"([^"]+)"', message, re.IGNORECASE)
    normal = lambda value: os.path.normcase(os.path.normpath(value))
    return bool(question and filename and normal(filename.group(1)) == normal(path))


def _address(obj):
    return {k: obj[k] for k in ('key', 'handle')}


def _checked(result):
    if not result.get('ok'):
        raise Failure(result.get('code', 'helper_operation_failed'), result.get('error', 'The helper operation failed.'))
    return result


def _read(R, obj):
    text = _checked(R.tc_get_data_presentation(**_address(obj))).get('presentation')
    try:
        result = json.loads(text)
    except (TypeError, ValueError):
        raise Failure('helper_protocol_error', 'The helper did not return a valid JSON response.') from None
    if not isinstance(result, dict) or type(result.get('protocol')) is not int or result.get('protocol') != PROTOCOL:
        raise Failure('helper_version_mismatch', 'Use the Testpilot.epf distributed with this server.')
    if type(result.get('ok')) is not bool or not isinstance(result.get('request_id'), str):
        raise Failure('helper_protocol_error', 'The helper returned an invalid result envelope.')
    return result


BSP_SECURITY_WARNING = ('ОбщаяФорма.ПредупреждениеБезопасности', 'CommonForm.ПредупреждениеБезопасности')
# Стартовые страницы формы БСП: «После появления права» — ЯОзнакомлен, «После обновления» — НеЗапрещать.
# Кнопку по умолчанию «ЗапретитьОткрытиеВнешнихОтчетовИОбработок» не нажимаем: Testpilot.epf перестал бы открываться.
BSP_SECURITY_ANSWERS = ('ЯОзнакомлен', 'НеЗапрещать')


def _acknowledge_security_warning(R, objects, form):
    """Ответить на стартовое предупреждение безопасности БСП; кнопка скрытой страницы — берём следующую."""
    buttons = {o.get('name'): o for o in objects
               if o.get('class') == 'Button' and o.get('key', '').startswith(form['key'] + '.')}
    for name in BSP_SECURITY_ANSWERS:
        if name not in buttons:
            continue
        # Кнопку невидимой страницы клиент принимает без эффекта: ok с target_hidden — не ответ.
        result = R.tc_click(**_address(buttons[name]), expect='none')
        if result.get('ok') and not result.get('target_hidden'):
            return
    raise Failure('helper_startup_blocked', 'A startup dialog requires attention.', dialog='ПредупреждениеБезопасности')


def discover(R, client, *, startup=False):
    with internal(client):
        objects = R._search_objects(client, R._APPLICATION_ROOT)
        # Register all protected roots, including when the processing is not configured.
        filter_objects(client, objects)
        if startup:
            active = R._window(client)
            active_forms = [o for o in objects if o.get('class') == 'ManagedForm'
                            and o.get('key', '').startswith((active.get('key') or '\0') + '.')]
            for form in active_forms:
                if form.get('form_name') in ('ОбщаяФорма.ПодключениеИнтернетПоддержки',
                                             'CommonForm.ПодключениеИнтернетПоддержки'):
                    _checked(R.tc_close_window(key=active['key']))
                    return None, []
                if form.get('form_name') in BSP_SECURITY_WARNING:
                    _acknowledge_security_warning(R, objects, form)
                    return None, []
                if form.get('form_name') == 'MessageBox':
                    # Read the startup question before trying fields behind its modal window.
                    return None, objects
        forms = [o for o in objects if o.get('form_name') in HELPER_FORM_NAMES]
        if not forms:
            return None, objects
        if len(forms) != 1:
            raise Failure('helper_ambiguous', 'More than one Testpilot service form is open.')
        form = forms[0]
        fields = {o.get('name'): o for o in objects if o.get('key', '').startswith(form['key'] + '.')}
        names = ('ClientResult', 'ServerResult', 'OpenRequest')
        if any(name not in fields for name in names):
            raise Failure('helper_version_mismatch', 'The Testpilot service form has an incompatible structure.')
        for name in ('ClientResult', 'ServerResult'):
            _read(R, fields[name])
        service = dict(form=form, fields=fields, capabilities=[], functions=[])
        if 'ServiceInfo' in fields:
            from _service_metadata import validate_registry
            info = _read(R, fields['ServiceInfo'])
            if not info['ok']:
                raise Failure('invalid_function_registry', info.get('error', 'Invalid custom BSL function registry.'))
            capabilities = info.get('capabilities', [])
            if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
                raise Failure('helper_protocol_error', 'The helper returned invalid capabilities.')
            service['capabilities'] = capabilities
            service['separators'] = info.get('separators')
            service['language'] = info.get('language')
            service['locale'] = info.get('locale')
            service['system_language'] = info.get('system_language')
            service['date_sample'] = info.get('date_sample')
            service['functions'] = validate_registry(info.get('functions', []))
        client._testpilot_service = service
        return service, objects


def forbidden(message):
    # shortcut: только русский текст платформы 8.3.27; английский добавить, когда встретится живьём.
    return 'запрещен запуск внешних обработок' in (message or '').lower()


# Отказы окна, которое ещё не готово к команде: при старте повторяются до срока.
_RETRY_CODES = ('target_not_interactive', 'invalid_element_state', 'client_busy', 'target_unavailable')


def prepare(R, client, path, deadline, stop=None):
    """Only startup may approve the exact configured file; never an arbitrary dialog.
    stop() returns a startup failure (code, error, details) that waiting cannot fix, or None."""
    old_deadline = getattr(client, '_io_deadline', None)
    client._io_deadline = deadline
    last_error = None
    try:
        while time.monotonic() < deadline:
            failure = stop() if stop else None
            if failure:
                raise Failure(failure.pop('code'), failure.pop('error'), **failure)
            with internal(client):
                try:
                    service, objects = discover(R, client, startup=True)
                except Failure as exc:
                    if exc.result['code'] not in _RETRY_CODES:
                        raise
                    last_error = exc.result
                    time.sleep(min(.2, max(0, deadline - time.monotonic())))
                    continue
                except (RuntimeError, TimeoutError) as exc:
                    last_error = {'error': str(exc)}
                    time.sleep(min(.2, max(0, deadline - time.monotonic())))
                    continue
                if service:
                    active = R._window(client)
                    if active.get('key') and not protected(client, active['key']):
                        return
                    work = [o for o in objects if o.get('class') in ('ManagedForm', 'MainFrame')
                            and not protected(client, o.get('key'))]
                    if not work:
                        raise Failure('helper_startup_blocked', 'No application window is available outside the service form.')
                    # Окно, открытое при старте (у админа — «Новости»), может отказать в активации:
                    # пробуем остальные рабочие окна, затем повтор до срока, как в discover.
                    work.sort(key=lambda o: o.get('class') != 'ManagedForm')
                    activated = False
                    for target in work:
                        try:
                            for kind in ('action', 'commit'):
                                _checked(client.send_cmd(G.ACTIVATE, target['key'], kind=kind,
                                                        handle=target.get('handle') if target.get('class') == 'ManagedForm' else None))
                        except (tc1c.OperationError, Failure) as exc:
                            code = exc.code if isinstance(exc, tc1c.OperationError) else exc.result['code']
                            if code not in _RETRY_CODES:
                                raise
                            last_error = dict(code=code, error=str(exc), target=target['key'])
                            continue
                        activated = True
                        break
                    if not activated:
                        time.sleep(min(.2, max(0, deadline - time.monotonic())))
                        continue
                    active = R._window(client)
                    if not active.get('key'):
                        time.sleep(min(.2, max(0, deadline - time.monotonic())))
                        continue
                    if protected(client, active['key']):
                        # An empty main window can accept navigation without becoming active.
                        # Ordinary navigation resolves it separately; the helper stays protected.
                        if not any(o.get('class') == 'MainFrame' for o in work):
                            raise Failure('helper_startup_blocked', 'Could not activate a work window.')
                    return
                for form in [o for o in objects if o.get('form_name') == 'MessageBox']:
                    children = [o for o in objects if o.get('key', '').startswith(form['key'] + '.')]
                    message = next((o.get('title', '') for o in children if o.get('name') == 'Message'), '')
                    if _configured_warning(message, path):
                        yes = [o for o in children if o.get('class') == 'Button' and o.get('title') in ('Да', 'Yes')]
                        if len(yes) == 1:
                            _checked(R.tc_click(**_address(yes[0]), expect='none'))
                            break
                    if forbidden(message):
                        buttons = [o for o in children if o.get('class') == 'Button']
                        if len(buttons) == 1:
                            _checked(R.tc_click(**_address(buttons[0]), expect='none'))
                        raise Failure('helper_forbidden', 'The user may not run external processing; the client works '
                                      'without it, code and checks go through the admin client.', execution_reason=message)
                    if message:
                        raise Failure('helper_startup_blocked', 'A startup dialog requires attention.', dialog=message)
            time.sleep(min(.2, max(0, deadline - time.monotonic())))
        raise Failure('helper_not_ready', 'Testpilot.epf did not become ready before the startup deadline. Check external-processing permissions and startup dialogs.',
                      **({'last_error': last_error} if last_error else {}))
    finally:
        client._io_deadline = old_deadline


def _remember_action_reply(pending, key, raw):
    status = tc1c.decode_operation_status(raw, G.CLICK)
    if status == 0:
        reply = {'ok': True}
    elif status is not None:
        reply = tc1c.OperationError(status, key).result()
    else:
        reply = dict(ok=False, code='helper_protocol_error', error='Could not confirm the delayed execution command.')
    pending['action_reply'] = reply


def _request_form(R, client, window):
    """Fields of the Request form in window, or None for any other window."""
    if not window:
        return None
    objects = R._search_objects(client, window)
    filter_objects(client, objects)
    form = next((o for o in objects if o.get('form_name') in REQUEST_FORM_NAMES), None)
    if form is None:
        return None
    return {o.get('name'): o for o in objects if o.get('key', '').startswith(form['key'] + '.')}


def _open_request(R, client, service):
    """Open a Request form over the active form without activating Helper; return its window and fields.

    Activating Helper would make the platform return focus to it when the work form closes,
    and ACTIVATE cannot restore a choice form opened from a spreadsheet cell (kit spike
    testpilot-helper-restore). Closing Request, opened with LockOwnerWindow, returns focus to its owner."""
    opened = vars(client).setdefault('_request_windows', set())
    active = R._window(client).get('key')
    helper_root = service['form']['key'].split('.ManagedForm[', 1)[0]
    if active in opened or (active != helper_root and protected(client, active)):
        # An interrupted call left its Request open; it blocks the owner window until closed.
        _checked(R.tc_close_window(key=active))
        opened.discard(active)
        active = R._window(client).get('key')
    button = service['fields']['OpenRequest']
    try:
        for kind in ('action', 'commit'):
            _checked(client.send_cmd(G.CLICK, button['key'], kind=kind, handle=button['handle']))
    except tc1c.OperationError:
        raise Failure('modal_window_open', 'A modal window (question, error) blocks the 1C interface; nothing was executed. '
                      'Answer it with answer_dialog, or read it with get_current_error and close it with close_window, then retry.',
                      suggested_action='answer_dialog') from None
    while True:
        window = R._window(client).get('key')
        # Only a newly active window is read: reading every element of the work form is costly.
        fields = _request_form(R, client, window) if window and window != active else None
        if fields is not None:
            opened.add(window)
            if any(name not in fields for name in ('Request', 'RunClient', 'RunServer')):
                raise Failure('helper_version_mismatch', 'The Testpilot request form has an incompatible structure.')
            return window, fields
        if time.monotonic() >= client._io_deadline:
            raise TimeoutError('The Testpilot request form did not open.')
        time.sleep(0.05)


def execute(R, client, *, mode, context, code=None, query=None, parameters=None, limit=100, timeout=180,
            check_permissions=True, options=None, name=None):
    permitted = {'code': SETTINGS.code, 'query': SETTINGS.query,
                 'metadata': SETTINGS.metadata_enabled, 'function': SETTINGS.functions,
                 'form_context': False, 'form_details': False, 'form_state': False}
    if mode not in permitted:
        raise Failure('invalid_execution_mode', 'Unknown execution mode.')
    if check_permissions and not permitted[mode]:
        raise Failure('execution_disabled', 'This execution mode is disabled in the server settings.')
    if R._state.get('rec_active') is True:
        raise Failure('execution_not_recordable', 'Finish XML scenario recording before using the Testpilot processing. Use Python tests for these calls.')
    if context not in ('client', 'server'):
        raise Failure('invalid_context', 'context must be client or server.')
    if mode in ('form_context', 'form_details', 'form_state') and context != 'client':
        raise Failure('invalid_context', 'Form properties are read in the client context.')
    if type(timeout) not in (int, float) or not 0 < timeout <= 3600:
        raise Failure('invalid_timeout', 'timeout must be greater than zero and at most 3600 seconds.')
    if mode == 'code':
        validate_code(code)
    elif mode == 'query':
        if type(limit) is not int or not 1 <= limit <= 500:
            raise Failure('invalid_limit', 'limit must be an integer from 1 to 500.')
        query = prepare_query(query)
    if parameters is not None and not isinstance(parameters, dict):
        raise Failure('invalid_parameters', 'parameters must be a JSON object.')
    request_id = uuid.uuid4().hex
    request = dict(protocol=PROTOCOL, request_id=request_id, mode=mode, context=context,
                   code=code, query=query, parameters=parameters or {}, limit=limit)
    if mode in ('metadata', 'form_context', 'form_details', 'form_state'):
        request['options'] = options
    if mode == 'function':
        request['name'] = name
    try:
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        raise Failure('invalid_parameters', 'Use JSON values and documented typed date/reference values.') from None
    old_deadline = getattr(client, '_io_deadline', None)
    old_track = getattr(client, '_track', None)
    old_max = getattr(client, '_max_action_time', None)
    old_resync = vars(client).get('RESYNC_TIMEOUT')
    client.RESYNC_TIMEOUT = timeout
    client._max_action_time = 0  # The total execution deadline governs every protocol read.
    client._io_deadline = time.monotonic() + timeout
    try:
        with internal(client):
            service = vars(client).get('_testpilot_service')
            if service is None:
                service, _ = discover(R, client)
            if service is None:
                raise Failure('helper_not_ready', 'Launch the client with the configured Testpilot processing enabled.')
            drained = None
            previous = vars(client).get('_service_pending')
            if previous:
                if previous.get('action_pending'):
                    client._resync()
                    reply = previous.get('action_reply')
                    if reply is None:
                        raise Failure('execution_pending', 'The previous execution command has not been confirmed.')
                    if not reply.get('ok'):
                        if reply.get('code') != 'helper_protocol_error':
                            client._service_pending = None
                        _checked(reply)
                    previous.pop('action_pending')
                    previous.pop('action_reply')
                commit = previous.get('commit_pending')
                if commit:
                    # An intervening UI command may still owe a reply. Drain it while
                    # the unsent commit remains recorded, including on resync failure.
                    if vars(client).get('_pending'):
                        client._resync()
                    # Only retry a frame proven not to have reached the socket.
                    # Once sent, even a receive timeout must never repeat this commit.
                    button = previous['button']
                    previous.pop('commit_pending')
                    try:
                        _checked(client.send_cmd(G.CLICK, button['key'], kind='commit', handle=button['handle']))
                    except tc1c.CommandNotSentTimeout:
                        previous['commit_pending'] = commit
                        raise
                response = _read(R, service['fields'][previous['field']])
                if response.get('request_id') != previous['request_id']:
                    raise Failure('execution_pending', 'The previous execution has no matching result yet.', **previous)
                client._service_pending = None
                # Прежний результат прочитан; новый запрос выполняется в том же вызове, а не теряется.
                drained = response
            if mode in ('metadata', 'function', 'form_context', 'form_details', 'form_state'):
                from _service_metadata import function_arguments
                capability = {'metadata': 'metadata', 'function': 'custom_functions',
                              'form_context': 'form_context', 'form_details': 'form_details',
                              'form_state': 'form_state'}[mode]
                if mode == 'metadata' and options and options.get('format') == 'tester':
                    capability = 'tester_metadata'
                if capability not in service.get('capabilities', []):
                    raise Failure('helper_version_mismatch', 'Rebuild or update Testpilot.epf to use this operation.')
                if mode == 'function':
                    definition, arguments = function_arguments(service['functions'], name, parameters)
                    context = definition['context']
                    request.update(context=context, parameters=arguments)
                    payload = json.dumps(request, ensure_ascii=False, allow_nan=False)
            prefix = 'Client' if context == 'client' else 'Server'
            fields = service['fields']
            client._track = None
            request_window, request_form = _open_request(R, client, service)
            _checked(R.tc_input_html(**_address(request_form['Request']),
                                    html='<pre>' + html.escape(payload) + '</pre>'))
            # Avoid public click readback: the result field itself synchronizes with 1C.
            button = request_form['Run' + prefix]
            client._service_pending = dict(request_id=request_id, field=prefix + 'Result', mode=mode, button=button)
            for kind in ('action', 'commit'):
                try:
                    _checked(client.send_cmd(G.CLICK, button['key'], kind=kind, handle=button['handle']))
                except tc1c.CommandNotSentTimeout:
                    if kind == 'action':
                        client._service_pending = None
                    else:
                        client._service_pending['commit_pending'] = 'Run' + prefix
                    raise
                except TimeoutError:
                    if kind == 'action' and vars(client).get('_pending'):
                        pending = client._service_pending
                        pending.update(action_pending=True, commit_pending='Run' + prefix)
                        client._pending_reply_callback = lambda raw: _remember_action_reply(pending, button['key'], raw)
                    raise
                except (tc1c.OperationError, Failure):
                    if kind == 'action':
                        # A complete rejection of the first frame confirms no execution.
                        client._service_pending = None
                    raise
            response = _read(R, fields[prefix + 'Result'])
            if response.get('request_id') != request_id:
                raise Failure('helper_protocol_error', 'The helper returned a result for a different request.', request_id=request_id)
            client._request_windows.discard(request_window)  # Request closed itself after the answer.
            client._service_pending = None
            response.pop('protocol', None)
            if drained is not None:
                response['previous_result'] = drained
            return response
    except TimeoutError:
        pending = vars(client).get('_service_pending')
        raise Failure('execution_timeout', 'The deadline expired. Execution may still be running; the next execution call first reads its result.',
                      request_id=pending['request_id'] if pending else request_id, may_be_running=bool(pending)) from None
    except RuntimeError as exc:
        pending = vars(client).get('_service_pending')
        if pending and isinstance(exc.__context__, TimeoutError):
            raise Failure('execution_timeout', 'The previous execution is still pending; no new request was sent.',
                          request_id=pending['request_id'], may_be_running=True) from None
        raise
    finally:
        # The cached active window is the closed Request; the next read must query 1C.
        R._state['window_key'] = None
        client._track = old_track
        client._io_deadline = old_deadline
        client._max_action_time = old_max
        if old_resync is None:
            vars(client).pop('RESYNC_TIMEOUT', None)
        else:
            client.RESYNC_TIMEOUT = old_resync


def form_id(form_key):
    """UUID of a ManagedForm key, as the helper identifies open forms."""
    return form_key.rsplit('.ManagedForm[', 1)[-1].removesuffix(']') if '.ManagedForm[' in (form_key or '') else None


def form_state(R, client, form_key, names=(), timeout=30):
    """Modified flag, main object reference/posting and field values of an open form.

    None when the helper or its form_state capability is unavailable: callers then rely
    on UI observations only. Raises Failure for protocol errors of an available helper.
    """
    service = vars(client).get('_testpilot_service')
    if service is None or 'form_state' not in service.get('capabilities', []):
        return None
    identifier = form_id(form_key)
    if identifier is None:
        return None
    response = execute(R, client, mode='form_state', context='client',
                       options=dict(form_id=identifier, items=list(names)), timeout=timeout, check_permissions=False)
    if not response.get('ok'):
        raise Failure(response.get('code', 'helper_operation_failed'), response.get('error', 'Could not read the form state.'))
    data = response.get('result')
    if not isinstance(data, dict) or data.get('form_id') != identifier:
        raise Failure('helper_protocol_error', 'The helper returned the state of a different form.')
    if data.get('found') is False:
        return dict(found=False)
    values = {}
    for item in data.get('items') or []:
        if isinstance(item, dict) and isinstance(item.get('name'), str):
            values[item['name']] = item.get('value')
    obj = data.get('object') if isinstance(data.get('object'), dict) else None
    return dict(found=True, modified=data.get('modified'), object=obj, values=values,
                errors=data.get('errors') or [])


def value_kind(value):
    """Kind of a helper-prepared value: number, date, boolean, string, reference or empty."""
    if value is None:
        return 'empty'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, dict):
        kind = value.get('$type')
        if kind == 'date':
            return 'date'
        if kind in ('ref', 'enum'):
            return 'reference'
    return 'other'
