"""MCP publication and response encoding for the shared 1C runtime."""
import base64
import difflib
import functools
import inspect
import json
import logging
import os
import re
import weakref
import anyio
import pydantic
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent
from mcp.server.lowlevel import NotificationOptions
import _response
import _screenshots

CUSTOM_TOOLS = frozenset({'tc_list_custom_bsl_functions', 'tc_execute_custom_bsl_function'})
CUSTOM_ACTIONS = frozenset(group[3:] for group in CUSTOM_TOOLS)
MAX_CALLS = 20
SEARCH_DOCS = 8
STEP_REF = re.compile(r'^\$(\d+)\.(.+)$')
SEARCH_DOC = ('Find 1C test-client actions for execute. Empty query: groups and action names. '
              'An action name: its parameters (* required) and documentation. '
              'Words: matching actions, documentation of the first %d.' % SEARCH_DOCS)


class TestpilotMCP(FastMCP):
    """Custom functions appear in execute only while a connected processing registers them."""
    def __init__(self, runtime, **kwargs):
        self.runtime = runtime
        self._sessions = weakref.WeakSet()
        self._custom_visible = False
        super().__init__('1c-testpilot', **kwargs)
        create = self._mcp_server.create_initialization_options
        self._mcp_server.create_initialization_options = functools.partial(
            create, notification_options=NotificationOptions(tools_changed=True))

    def custom_visible(self):
        if not self.runtime._code_execution.SETTINGS.functions:
            return False
        pool = self.runtime._pool
        with pool.lock:
            clients = [entry.state.get('client') for entry in pool.entries.values()]
        return any(client is not None and vars(client).get('_testpilot_service', {}).get('functions')
                   for client in clients)

    def remember_session(self):
        try:
            self._sessions.add(self.get_context().session)
        except (ValueError, LookupError):
            pass  # Direct Python calls to FastMCP have no protocol session.

    async def list_tools(self):
        self.remember_session()
        tools = await super().list_tools()
        if self.custom_visible():
            return tools
        out = []
        for tool in tools:
            if tool.name == 'execute':
                tool = tool.model_copy(deep=True)
                action = tool.inputSchema['properties']['calls']['items']['properties']['action']
                action['enum'] = [a for a in action['enum'] if a not in CUSTOM_ACTIONS]
            out.append(tool)
        return out

    async def call_tool(self, name, arguments):
        self.remember_session()
        try:
            return await super().call_tool(name, arguments)
        finally:
            visible = self.custom_visible()
            if visible != self._custom_visible:
                self._custom_visible = visible
                for session in list(self._sessions):
                    try:
                        await session.send_tool_list_changed()
                    except Exception:
                        # Notification delivery must not replace an already completed action.
                        logging.getLogger(__name__).debug('Could not notify an MCP session of tool changes', exc_info=True)
                        self._sessions.discard(session)


def format_result(result, *, addrs=False):
    if isinstance(result, _screenshots.Screenshot):
        message = _response.respond(result.metadata)
        if not isinstance(message, str):
            message = json.dumps(message, ensure_ascii=False)
        return CallToolResult(content=[TextContent(type='text', text=message),
            ImageContent(type='image', mimeType='image/png', data=base64.b64encode(result.png).decode('ascii'))],
            structuredContent=result.metadata)
    return _response.respond(result, addrs=addrs)


def register(S):
    """Публикация двух инструментов: search (каталог действий) и execute (пачка вызовов)."""
    # Status and forced disconnection must remain reachable even when ordinary
    # workers are all waiting for 1C or for a connection lock.
    control_limiter = anyio.CapacityLimiter(4)
    tv = S._ver_tuple(S._TARGET) if S._TARGET else None
    # сначала отбираем ВСЕ публикуемые действия: схема execute, каталог search и указатели на
    # общие операции строятся от одного набора, иначе они сошлются на исключённое действие
    published = {}
    for group, actions in S._ACTIONS.items():
        if group == 'tc_run_compatible_scenario' and not S._call_logging.enabled('TC1C_COMPATIBLE_SCENARIOS', 'false'):
            continue
        if group == 'tc_execute_code' and not S._code_execution.SETTINGS.code:
            continue
        if group == 'tc_execute_query' and not S._code_execution.SETTINGS.query:
            continue
        if group == 'tc_get_metadata' and not S._code_execution.SETTINGS.metadata_enabled:
            continue
        if group in CUSTOM_TOOLS and not S._code_execution.SETTINGS.functions:
            continue
        acts = {a: fn for a, fn in actions.items()
                if not (tv and S._ver_tuple(S.TOOL_MIN_VERSION.get('tc_' + a, '')) > tv)
                and (a != 'get_screenshot' or S.SCREENSHOTS)
                and (a not in S._call_logging.ACTIONS or S.LOGGING)}
        if acts:
            published[group] = acts        # группа без доступных действий не публикуется вовсе
    pub_group = {a: g for g, acts in published.items() for a in acts}
    names = sorted(pub_group)
    adapters = {}

    def visible_names():
        shown = S.mcp.custom_visible()
        return [a for a in names if shown or a not in CUSTOM_ACTIONS]

    def group_line(group, acts):
        doc = S._GROUP_DOC.get(group) or (inspect.getdoc(next(iter(acts.values()))) or group).splitlines()[0]
        return '%s: %s\n  %s' % (group[3:], doc, ', '.join(sorted(acts)))

    def action_doc(action):
        group = pub_group[action]
        fn = published[group][action]
        return '%s%s%s%s' % (S._fmt_action(action, fn), S._PARAM_NOTE,
                             S._EFFECT_NOTE if action in S._VERIFY_ACTIONS else '',
                             S._common_hint(group, {action: fn}, pub_group))

    def search(query: str = '') -> str:
        shown = set(visible_names())
        query = query.strip()
        if not query:
            lines = ['Actions by group. search(query="<action>") gives its parameters and documentation.']
            for group, acts in published.items():
                acts = {a: fn for a, fn in acts.items() if a in shown}
                if acts:
                    lines.append(group_line(group, acts))
            return '\n'.join(lines)
        if query in shown:
            return action_doc(query)
        words = query.lower().split()
        scored = []
        for action in shown:
            group = pub_group[action]
            doc = (inspect.getdoc(published[group][action]) or '').lower()
            text = ' '.join((action, group, doc))
            hits = sum(w in text for w in words)
            if hits:
                # имя, вся фраза, первая строка документации (назначение действия), затем остальное
                first = doc.split('\n', 1)[0]
                scored.append((-sum(w in action for w in words), -(query.lower() in text),
                               -sum(w in first for w in words), -hits, action))
        if not scored:
            similar = difflib.get_close_matches(query, sorted(shown), 5, 0.5)
            return 'No actions match %r.%s search() lists all actions.' % (
                query, ' Similar: %s.' % ', '.join(similar) if similar else '')
        found = [a for *_, a in sorted(scored)]
        text = '\n\n'.join(action_doc(a) for a in found[:SEARCH_DOCS])
        if found[SEARCH_DOCS:]:
            text += '\n\nAlso matching: %s.' % ', '.join(found[SEARCH_DOCS:])
        return text

    def type_error(action, args):
        """Типы аргументов — как прежняя схема группы: pydantic, нестрогий режим."""
        fn = published[pub_group[action]][action]
        # Имена — до разрешения ссылок и выбора соединения: лишний аргумент не должен дойти до 1С.
        # code_epf у connect/launch_client отклоняет _dispatch_action своим сообщением.
        names_error = S._action_argument_error(fn, {k: v for k, v in args.items() if k != 'code_epf'})
        if names_error:
            return args, names_error
        if action not in adapters:
            adapters[action] = {p.name: pydantic.TypeAdapter(p.annotation) for p in S._public_parameters(fn)
                                if p.annotation is not inspect.Parameter.empty and p.kind not in
                                (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)}
        out, errors = dict(args), []
        for name, value in args.items():
            adapter = adapters[action].get(name)
            if adapter is None or value is None:
                continue
            try:
                out[name] = adapter.validate_python(value)
            except pydantic.ValidationError as exc:
                errors.append('%s: %s' % (name, '; '.join(e['msg'] for e in exc.errors())))
        if not errors:
            return out, None
        return out, {'ok': False, 'code': 'invalid_arguments', 'error': 'Wrong argument types: ' + ', '.join(errors) + '.',
                     'signature': S._fmt_action(action, fn).splitlines()[0][2:]}

    def check(calls):
        if not 1 <= len(calls) <= MAX_CALLS:
            return {'ok': False, 'code': 'invalid_arguments',
                    'error': 'calls must contain 1 to %d calls; nothing was executed.' % MAX_CALLS}
        shown = visible_names()
        for i, call in enumerate(calls):
            extra = sorted(set(call) - {'action', 'args', 'connection_id'})
            action = call.get('action')
            if extra or not isinstance(call.get('args', {}), (dict, type(None))):
                return {'ok': False, 'code': 'invalid_arguments', 'step': i, 'error':
                        'A call is {action, args, connection_id}; nothing was executed.', 'unexpected_parameters': extra}
            if action in CUSTOM_ACTIONS and action in pub_group and action not in shown:
                raise ValueError('Custom BSL functions are not available in connected clients.')
            if action not in pub_group:
                return {'ok': False, 'code': 'unknown_action', 'step': i,
                        'error': 'Unknown action %r; nothing was executed. search() lists actions.' % action,
                        'similar': difflib.get_close_matches(str(action), names, 5, 0.5)}
        return None

    def run(calls):
        token = S._batch.set(True)
        steps, images, stopped = [], [], None
        try:
            for i, call in enumerate(calls):
                action = call['action']
                try:
                    args, error = type_error(action, resolve(call.get('args') or {}, steps, i))
                    result = error or S._dispatch_action(published[pub_group[action]], pub_group[action],
                        {'action': action, 'connection_id': call.get('connection_id'), **args})
                except Unresolved as exc:
                    result = {'ok': False, 'code': 'unresolved_reference', 'error': str(exc)}
                except Exception as exc:
                    result = {'ok': False, 'code': 'error', 'exception': type(exc).__name__, 'error': str(exc)}
                if isinstance(result, _screenshots.Screenshot):
                    images.append(result.png)
                    result = {**result.metadata, 'image': len(images) - 1}
                steps.append(result)
                if isinstance(result, dict) and result.get('ok') is False:
                    stopped = i
                    break
        finally:
            S._batch.reset(token)
        batch = {'ok': stopped is None, **({'stopped_at': stopped} if stopped is not None else {}), 'steps': steps}
        return encode(batch, images)

    async def execute(calls: list[dict]):
        error = check(calls)
        if error:
            return encode(error, [])
        control = all(c['action'] == 'list_connections' or (c['action'] == 'disconnect' and
                      (c.get('args') or {}).get('force') is True) for c in calls)
        return await anyio.to_thread.run_sync(functools.partial(run, calls),
                                              limiter=control_limiter if control else None)

    S.mcp.tool(name='search', description=SEARCH_DOC)(search)
    S.mcp.tool(name='execute', description=execute_doc(S))(execute)
    tool = S.mcp._tool_manager._tools['execute']
    tool.parameters = execute_schema(names)
    S.mcp.execute_names = names


class Unresolved(Exception):
    pass


def resolve(value, steps, current):
    """Подставить `$N.путь` из ответов прошлых шагов; `$$…` — строка с одним `$`."""
    if isinstance(value, dict):
        return {k: resolve(v, steps, current) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, steps, current) for v in value]
    if not isinstance(value, str) or not value.startswith('$'):
        return value
    if value.startswith('$$'):
        return value[1:]
    match = STEP_REF.match(value)
    if not match:
        return value
    n, path = int(match[1]), match[2]
    if n >= current:
        raise Unresolved('%s: step %d has no response yet.' % (value, n))
    node = steps[n]
    for part in path.split('.'):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise Unresolved('%s: no %r in the response of step %d.' % (value, part, n))
    return node


def encode(payload, images):
    text = _response.respond(payload)
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    if not images:
        return text
    return CallToolResult(content=[TextContent(type='text', text=text)] + [
        ImageContent(type='image', mimeType='image/png', data=base64.b64encode(png).decode('ascii'))
        for png in images])


def execute_schema(names):
    return {'type': 'object', 'required': ['calls'], 'properties': {'calls': {
        'type': 'array', 'minItems': 1, 'maxItems': MAX_CALLS, 'items': {
            'type': 'object', 'required': ['action'], 'additionalProperties': False, 'properties': {
                'action': {'type': 'string', 'enum': names},
                'args': {'type': 'object', 'description': 'Parameters of the action (search shows them).'},
                'connection_id': {'type': 'string'}}}}}}


def execute_doc(S):
    doc = ('Run 1C test-client actions in order: calls=[{action, args, connection_id}], 1-%d calls. '
           'The batch stops at the first step with ok=false or an error; the answer is {ok, stopped_at, steps}. '
           'Parameters and documentation of an action: search(query="<action>"); wrong names or types are '
           'refused before anything is sent, with the signature.\n'
           'A string argument "$N.path" takes a value from the response of step N of this batch '
           '(keys and list indexes by dots: "$0.object.ref"); start a literal "$" with "$$".\n' % MAX_CALLS)
    if S._response.REF_MODE == 'id':
        doc += ('Use returned ref/root_ref values unchanged; re-find expired elements. A ref selects its client; '
                'otherwise set connection_id when several clients are connected (list_connections).')
    else:
        doc += 'Set connection_id when several clients are connected (list_connections).'
    doc += S._EFFECT_NOTE
    if S._response.DETAIL == 'compact':
        doc += '\nSuccess may omit target/connection echoes and shorten window details.'
    if S._response.COMPACT:
        doc += S._response.HINT
    if S.SCREENSHOTS:
        doc += '\nScreenshots come as images; the step of an image has image=<number>.'
    return doc


def install(S):
    S.mcp = TestpilotMCP(S, host=os.environ.get('TC1C_HTTP_HOST', '127.0.0.1'),
                   port=int(os.environ.get('TC1C_HTTP_PORT', '6004')),
                   streamable_http_path=os.environ.get('TC1C_HTTP_PATH', '/mcp'))
    S._format_result = format_result
    S._register_groups = functools.partial(register, S)
    S._register_groups()
    def main():
        transport = os.environ.get('TC1C_TRANSPORT', 'stdio').strip().lower().replace('_', '-')
        try:
            S.mcp.run(transport='streamable-http' if transport in ('http', 'streamable-http') else
                      'sse' if transport == 'sse' else 'stdio')
        finally:
            try:
                for connection in list(S._pool.entries.values()):
                    with S._pool.use(connection):
                        journal = S._state.get('_call_journal')
                        if journal is not None:
                            journal.stop(reason='server_stopped')
            finally:
                S._pool.close()
    S.main = main
