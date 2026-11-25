"""MCP testpilot — два инструмента search и execute (изменение testpilot-search-execute, задачи 4.1–4.13 матрицы):
требования «Два инструмента», «Каталог и документация действий», «Доступность действий», «Исполнение вызовов»,
«Пачка до первого отказа», «Ссылки на ответы прошлых шагов», «Скриншоты в ответе пачки», «Служебные действия
без очереди», «Подсказки называют действия» (specs/mcp-tools) и сценарий «Клиент из dev_ib.py client start»
(specs/client-profiles). Задача 4.13 — записи нет: ни один спайк не получил от get_cell_text text: null
с suggested_call.

Записи (копии в tests/recordings/, байт в байт docs/spikes):
  docs/spikes/testpilot-goto-row-list-load/recording/goto-row-refresh.jsonl (spike:spk_b232b1dd6d@v3) — ответы
    MCP прежних групп: get_active_window → окно «Информация», click → effect_not_observed; connection_id
    ответов и пространство имён ссылок (e1a26d020552e-N);
  docs/spikes/testpilot-helper-restore/recording/10-live-check.jsonl (spike:spk_cff9b4db89@v3) — то же окно
    «Информация» с ключом (Python API), версия платформы 8.3.27.2342;
  docs/spikes/testpilot-helper-restore/recording/05-protocol-only.jsonl — объекты формы Request (find_objects),
    кнопка RunClient с ключом и handle;
  docs/spikes/testpilot-cell-edit/recording/05-read-rows-focus.jsonl (spike:spk_d8a5084a0c@v1) — таблица
    «Список» и её колонки (find_objects): get_cell_text с text: null предлагает is_visible колонки.

Клиент 1С — заглушка с реестром ссылок записи (первая ссылка — e1a26d020552e-1, как в записи) в соединении пула
с connection_id записи; чтения runtime (_window, _search_objects, _ref_live_object) отвечают записанным. Кадры
проверки цели и наблюдения эффекта вокруг tc_click (CurrentVisible, снимки) в записях нет, поэтому обработчик
click на время публикации подменён функцией той же сигнатуры: возвращает записанный ответ действия и собирает
полученные аргументы. Ответ execute без изображений — toon-текст, его декодирует toon_format.
"""
import asyncio
import base64
import dataclasses
import functools
import inspect
import io
import json
import re
import threading
import time
from contextlib import asynccontextmanager
from unittest.mock import patch

import anyio
import pytest
import toon_format
from mcp.client.session import ClientSession
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, ImageContent, TextContent, ToolListChangedNotification
from PIL import Image

import _connections
import _helper_client as H
import _mcp
import _recording as recorded
import _refs
import server as S

pytestmark = pytest.mark.anyio

REFRESH = recorded.exchange(recorded.REFRESH)
INFO_WINDOW = REFRESH[1]                      # tc_app get_active_window: окно «Информация»
assert INFO_WINDOW['tool'] == 'tc_app' and INFO_WINDOW['action'] == 'get_active_window'
CLICK_NOT_OBSERVED = REFRESH[14]['response']  # tc_field click: эффект не наблюдается
assert REFRESH[14]['action'] == 'click'
NAMESPACE = '1a26d020552e'                    # пространство имён ссылок записи (e1a26d020552e-1, -3, -6, -c, …)
CONNECTION_ID = 'caa09f086787d4e15'           # connection_id отказов той же записи
PLATFORM = H.calls(recorded.RESTORE_LIVE, 'get_active_window', 'startup')[0]['result']['platform_version']
REQUEST_OBJECTS = next(r for r in H.calls(recorded.RESTORE_PROTOCOL, 'find_objects', 'child_run'))['result']['objects']
RUN_CLIENT = next(o for o in REQUEST_OBJECTS if o.get('name') == 'RunClient')
RUN_CLIENT_FOUND = {'ok': True, 'objects': [
    {'ref': 'e1a26d020552e-1', **{k: v for k, v in RUN_CLIENT.items() if k not in ('key', 'handle')}}]}
LIST_CALLS = H.calls(recorded.CELL_READ_ROWS, 'find_objects', 'M_choice_from_cell')
LIST_TABLE = LIST_CALLS[0]['result']['objects'][0]            # таблица «Список» формы выбора
LIST_CHILDREN = LIST_CALLS[1]['result']['objects']            # её подчинённые: группы, кнопки, 4 колонки EditField
NAME_COLUMN = next(o for o in LIST_CHILDREN if o.get('name') == 'Наименование')
TC_CALL = re.compile(r'tc_[a-z_]+\(')
CUSTOM = ('execute_custom_bsl_function', 'list_custom_bsl_functions')


class Client:
    """Клиент 1С записи: версия платформы, реестр ссылок с пространством имён записи, окна и журнал кадров."""
    def __init__(self):
        self.platform_version = PLATFORM
        self.windows, self.frames = {}, []
        self._object_handles = _refs.Registry()
        self._object_handles._namespace = NAMESPACE

    def show(self, window):
        self.windows[window['key']] = dict(window)

    def window(self):
        return dict(self.windows[self._active]) if getattr(self, '_active', None) else dict(H.NO_WORK)

    def object_(self, key):
        return RUN_CLIENT if key == RUN_CLIENT['key'] else None

    def send_cmd(self, guid, key, **kw):
        self.frames.append((guid, key, kw.get('kind')))
        return {'ok': True, 'raw': b''}      # кадр без значения: чтение ячейки → text: null


def connect(client, cid=CONNECTION_ID):
    """Соединение пула с клиентом: зарегистрировано, не starting, connection_id записи."""
    connection = _connections.Connection('127.0.0.1', 30000)
    connection.id = cid
    connection.state['connection_id'] = cid
    connection.starting = False
    connection.state['client'] = client
    S._pool.entries[cid] = connection
    return connection


def reads(monkeypatch, client):
    """Чтения runtime отвечают записанным: активное окно — окно записи, поиск — объекты Request записи,
    живость объекта — кнопка RunClient записи. Возвращает список обращений к активному окну."""
    windows = []
    monkeypatch.setattr(S, '_window', lambda c: windows.append(1) or client.window())
    monkeypatch.setattr(S, '_search_objects', lambda c, root=None: [dict(o) for o in REQUEST_OBJECTS])
    monkeypatch.setattr(S, '_ref_live_object', lambda c, key: client.object_(key))
    return windows


@pytest.fixture
def mcp(monkeypatch):
    """Публикация инструментов теста: publish() ставит свежий TestpilotMCP и регистрирует search/execute
    на текущих настройках S (SCREENSHOTS, SETTINGS кода и запросов) и обработчиках _ACTIONS; после теста
    S.mcp прежний."""
    def publish():
        monkeypatch.setattr(S, 'mcp', _mcp.TestpilotMCP(S))
        S._register_groups()
        return S.mcp
    return publish


@pytest.fixture
def server(mcp):
    return mcp()


@pytest.fixture
def pool():
    """Пул с одним подключённым клиентом записи; после теста пула пуст."""
    client = Client()
    connection = connect(client)
    yield client, connection
    S._pool.entries.clear()


@pytest.fixture
def click(mcp, monkeypatch):
    """Действие click в публикации теста — функция с сигнатурой tc_click: click.result — её ответ,
    click.calls — аргументы шагов (имена параметров сигнатуры)."""
    @functools.wraps(S.tc_click)
    def click(*args, **kwargs):
        click.calls.append(dict(inspect.signature(click).bind(*args, **kwargs).arguments))
        return click.result
    click.result, click.calls = {'ok': True}, []
    monkeypatch.setitem(S._ACTIONS['tc_field'], 'click', click)
    mcp()
    return click


async def plain_text(result):
    """Текст ответа S.mcp.call_tool без изображений (search с output schema возвращает кортеж — его
    structured content тот же текст); в тексте нет tc_<группа>( (4.11 — все ответы модуля)."""
    if isinstance(result, tuple):
        assert dict(result[1]) == {'result': result[0][0].text}
        result = result[0]
    assert isinstance(result, list) and [c.type for c in result] == ['text']
    assert not TC_CALL.search(result[0].text), result[0].text
    return result[0].text


def execute_tool(tools):
    return next(t for t in tools if t.name == 'execute')


async def execute(calls):
    """execute через S.mcp.call_tool: toon-текст ответа, декодированный toon_format."""
    return toon_format.decode(await plain_text(await S.mcp.call_tool('execute', {'calls': calls})))


async def search(query=''):
    return await plain_text(await S.mcp.call_tool('search', {'query': query}))


def action_enum(tool):
    return tool.inputSchema['properties']['calls']['items']['properties']['action']['enum']


def catalog_names(catalog):
    """Имена действий из каталога search(''): строки-продолжения «  a, b, c» под строками групп."""
    return {name.strip() for line in catalog.splitlines() if line.startswith('  ')
            for name in line.strip().split(', ')}


async def listed(session):
    return (await session.list_tools()).tools


async def until(predicate, timeout=5):
    """Ждать условие (опрос 20 мс) — уведомление сервера приходит после ответа на вызов."""
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, 'условие не наступило за %s с' % timeout
        await asyncio.sleep(0.02)


@asynccontextmanager
async def memory_session(notifications):
    """Сеанс MCP по памяти с настоящим ServerSession: уведомления сервера — в список."""
    original = ClientSession._received_notification

    async def tap(self, notification):
        notifications.append(notification.root)
        await original(self, notification)
    with patch.object(ClientSession, '_received_notification', tap):
        async with create_connected_server_and_client_session(S.mcp) as session:
            yield session


# ---------------------------------------------------------------- 4.1, 4.8: инструменты и каталог
async def test_two_tools_fit_8000_characters_with_code_queries_and_screenshots(mcp, monkeypatch):
    """4.1: с исполнением кода и запросов и скриншотами публикуются только search и execute, их описания
    и схемы вместе не длиннее 8000 символов; схема execute перечисляет те же действия, что каталог search."""
    settings = S._code_execution.SETTINGS
    monkeypatch.setattr(S._code_execution, 'SETTINGS',
                        dataclasses.replace(settings, code=True, query=True))
    assert S.SCREENSHOTS
    mcp()
    tools = await S.mcp.list_tools()
    assert sorted(t.name for t in tools) == ['execute', 'search']
    assert sum(len(t.description) + len(json.dumps(t.inputSchema)) + len(json.dumps(t.outputSchema or {}))
               for t in tools) <= 8000
    calls = execute_tool(tools).inputSchema['properties']['calls']
    assert (calls['minItems'], calls['maxItems'], calls['items']['required'],
            calls['items']['additionalProperties']) == (1, 20, ['action'], False)
    assert sorted(calls['items']['properties']) == ['action', 'args', 'connection_id']
    names = set(action_enum(execute_tool(tools)))
    assert {'execute_code', 'execute_query', 'get_screenshot', 'get_active_window', 'connect'} <= names
    assert catalog_names(await search('')) == names


async def test_search_without_query_lists_groups_and_names_without_documentation(server):
    """4.8, сценарий «Пустой запрос»: группы с одной строкой описания и имена всех доступных действий,
    без документации действий (без сигнатур)."""
    catalog = await search('')
    lines = catalog.splitlines()
    assert lines[0] == 'Actions by group. search(query="<action>") gives its parameters and documentation.'
    groups = {S._ACTION_GROUP[name][3:] for name in catalog_names(catalog)}
    assert {line.split(':', 1)[0] for line in lines[1:] if not line.startswith(' ')} == groups
    assert 'find: Search the UI tree for objects.\n  find_object, find_objects, wait_for_object_displayed' in catalog
    assert {'get_active_window', 'get_screenshot', 'connect', 'click'} <= catalog_names(catalog)
    assert not any(line.startswith('- ') for line in lines) and 'click(' not in catalog


async def test_search_by_action_name_gives_signature_and_documentation(server):
    """4.8, сценарий «Действие по имени»: сигнатура click с обязательными параметрами и её документация."""
    doc = await search('click')
    assert doc.splitlines()[0] == '- click(ref*, answer=null, expect=null, timeout=10, diagnostics=False, diagnostics_wait=2.0)'
    assert '\n    Click a button, field, group, decoration or command-interface button.\n' in doc
    assert '\n' + S._PARAM_NOTE.strip() in doc and not TC_CALL.search(doc)


async def test_search_by_words_finds_actions_by_their_documentation(server):
    """4.8, сценарий «Поиск словами»: слова из документации находят set_area_text — с документацией."""
    found = await search('spreadsheet cell')
    assert "- set_area_text(ref*, address*, text*)\n    Set a spreadsheet cell's text by address, e.g. R2C1. Selects the cell, starts and" in found
    documented = [line for line in found.splitlines() if line.startswith('- ')]
    assert 1 < len(documented) <= 8 and '- get_cell_text(ref*, column*)' == documented[0]
    assert 'Also matching:' in found and 'find_object' not in found and 'find_objects' not in found


async def test_disabled_screenshots_leave_the_catalog_and_the_execute_schema(mcp, monkeypatch):
    """4.8, сценарий «Скриншоты выключены» (требование «Доступность действий»): get_screenshot нет ни в схеме
    execute, ни в ответах search; прочие действия на месте."""
    monkeypatch.setattr(S, 'SCREENSHOTS', False)
    mcp()
    tools = await S.mcp.list_tools()
    names = set(action_enum(execute_tool(tools)))
    assert 'get_screenshot' not in names and 'get_active_window' in names
    catalog = await search('')
    assert 'get_screenshot' not in catalog and catalog_names(catalog) == names
    assert await search('get_screenshot') == 'No actions match \'get_screenshot\'. Similar: get_parent, get_current_row, ' \
        'delete_snapshot, create_snapshot, get_current_element. search() lists all actions.'


# ---------------------------------------------------------------- 4.2–4.7: исполнение
async def test_single_call_answers_as_the_former_group_call(server, pool, monkeypatch):
    """4.2, сценарий «Один вызов»: execute с одним get_active_window даёт ответ шага, байт в байт равный
    записанному ответу прежнего tc_app(action="get_active_window") — с той же ссылкой e1a26d020552e-1."""
    client, _ = pool
    client.show(H.LIVE_INFO)
    client._active = H.LIVE_INFO['key']
    reads(monkeypatch, client)
    out = await execute([{'action': 'get_active_window', 'args': {}}])
    # запись разобрана _recording._parse: ref в ней переименован в key
    assert recorded._rename_refs(out) == {'ok': True, 'steps': [INFO_WINDOW['response']]}
    assert client.frames == []


async def test_wrong_arguments_are_refused_before_anything_is_sent(server, click, pool, monkeypatch):
    """4.3: лишний аргумент, нет обязательного — invalid_arguments с сигнатурой click до разрешения ссылки
    и выбора соединения; неизвестное действие — unknown_action с ближайшими именами. Ничего не отправлено.
    С testpilot-execute-errors (сценарий «Лишний аргумент») отказ — на пачку до запуска, со step; did_you_mean
    (если есть) называет параметр click — подсказки проверяет test_execute_errors."""
    client, _ = pool
    reads(monkeypatch, client)
    signature = 'click(ref, answer=null, expect=null, timeout=10, diagnostics=False, diagnostics_wait=2.0)'
    extra = await execute([{'action': 'click', 'args': {'ref': 'e1a26d020552e-c', 'text': 'X'}}])
    assert {k: v for k, v in extra.items() if k != 'did_you_mean'} == {
        'ok': False, 'code': 'invalid_arguments', 'step': 0,
        'error': 'Use only the parameters of the selected action; supply all required parameters. Nothing was executed.',
        'unexpected_parameters': ['text'], 'missing_parameters': [], 'signature': signature}
    assert set(extra.get('did_you_mean', {}).values()) <= {'ref', 'answer', 'expect', 'timeout', 'diagnostics', 'diagnostics_wait'}
    missing = await execute([{'action': 'click', 'args': {}}])
    assert missing['unexpected_parameters'] == [] and missing['missing_parameters'] == ['ref']
    assert missing['signature'].startswith('click(ref') and 'steps' not in missing
    unknown = await execute([{'action': 'list_windows'}])
    assert unknown['ok'] is False and unknown['code'] == 'unknown_action' and unknown['step'] == 0
    assert unknown['similar'] and set(unknown['similar']) <= set(action_enum(
        execute_tool(await S.mcp.list_tools())))
    assert 'close_window' in unknown['similar'] and 'steps' not in unknown
    assert click.calls == [] and client.frames == []


@pytest.mark.parametrize('count', [0, 21])
async def test_batch_outside_1_to_20_is_refused_with_nothing_executed(server, pool, monkeypatch, count):
    """4.4, сценарий «Пачка длиннее 20» (и пустая): invalid_arguments на всю пачку, ни один шаг не исполнен."""
    client, _ = pool
    windows = reads(monkeypatch, client)
    out = await execute([{'action': 'get_active_window', 'args': {}}] * count)
    assert out == {'ok': False, 'code': 'invalid_arguments',
                   'error': 'calls must contain 1 to 20 calls; nothing was executed.'}
    assert windows == [] and client.frames == []


async def test_batch_stops_at_the_first_refusal(server, click, pool, monkeypatch):
    """4.5, сценарий «Отказ в середине»: пачка из трёх шагов, второй — click с записанным effect_not_observed
    (goto-row-refresh, click ФормаОбновить): третий не исполнен, ok: false, stopped_at: 1, ответы шагов 0 и 1."""
    client, _ = pool
    windows = reads(monkeypatch, client)
    click.result = {k: v for k, v in CLICK_NOT_OBSERVED.items() if k != 'connection_id'}   # ответ обработчика
    out = await execute([{'action': 'find_objects', 'args': {'name': 'RunClient'}},
                         {'action': 'click', 'args': {'ref': '$0.objects.0.ref'}},
                         {'action': 'get_active_window', 'args': {}}])
    # ответ второго шага — запись, с connection_id соединения от execute
    assert out == {'ok': False, 'stopped_at': 1, 'steps': [RUN_CLIENT_FOUND, CLICK_NOT_OBSERVED]}
    assert windows == []                                   # третий шаг не исполнен
    assert [(c['key'], c['handle']) for c in click.calls] == [(RUN_CLIENT['key'], RUN_CLIENT['handle'])]
    # Все шаги прошли — ok: true и ответы всех шагов.
    click.result = {'ok': True}
    out = await execute([{'action': 'find_objects', 'args': {'name': 'RunClient'}},
                         {'action': 'click', 'args': {'ref': '$0.objects.0.ref'}}])
    assert out == {'ok': True, 'steps': [RUN_CLIENT_FOUND, {'ok': True}]} and 'stopped_at' not in out


async def test_reference_to_an_earlier_step_takes_the_found_button_and_dd_keeps_one_dollar(server, click, pool, monkeypatch):
    """4.6, сценарий «Найти и нажать»: $0.objects.0.ref из find_objects подставлен в click — нажата кнопка
    RunClient записи (ключ и handle); $$Да передан как $Да без подстановки."""
    client, _ = pool
    reads(monkeypatch, client)
    out = await execute([{'action': 'find_objects', 'args': {'name': 'RunClient'}},
                         {'action': 'click', 'args': {'ref': '$0.objects.0.ref', 'answer': '$$Да'}}])
    assert out == {'ok': True, 'steps': [RUN_CLIENT_FOUND, {'ok': True}]}
    assert len(click.calls) == 1
    assert {k: click.calls[0][k] for k in ('key', 'handle', 'answer', 'expect')} == {
        'key': RUN_CLIENT['key'], 'handle': RUN_CLIENT['handle'], 'answer': '$Да', 'expect': None}


@pytest.mark.parametrize('reference, complaint', [
    ('$0.objects.5.ref', "no '5' in the response of step 0"),     # сценарий «Пути нет»: найден один элемент
])
async def test_unresolved_reference_stops_the_step_without_sending(server, click, pool, monkeypatch, reference, complaint):
    """4.6, сценарий «Пути нет»: пути нет в ответе шага 0 — шаг unresolved_reference, клик не отправлен, пачка
    остановлена. Ссылку на шаг, который ещё не исполнен ($N, N ≥ текущего), с testpilot-execute-errors
    отказывает проверка пачки до запуска — test_execute_errors (5.1)."""
    client, _ = pool
    reads(monkeypatch, client)
    out = await execute([{'action': 'find_objects', 'args': {'name': 'RunClient'}},
                         {'action': 'click', 'args': {'ref': reference}}])
    assert out == {'ok': False, 'stopped_at': 1, 'steps': [RUN_CLIENT_FOUND, {
        'ok': False, 'code': 'unresolved_reference', 'error': '%s: %s.' % (reference, complaint)}]}
    assert click.calls == [] and client.frames == []


async def test_screenshot_step_is_one_image_marked_with_its_step(server, click, pool, monkeypatch):
    """4.7, сценарий «Действие и снимок»: пачка [click, get_screenshot] — текст двух шагов и одно изображение
    PNG, отмеченное шагом 1 (image: 0). Записи get_screenshot нет: PNG — 2×2 synthetic, метаданные — поля
    снимка (_screenshot_windows.py / _screenshot_linux.py: ok, capture_complete, title)."""
    client, _ = pool
    reads(monkeypatch, client)
    found = await execute([{'action': 'find_objects', 'args': {'name': 'RunClient'}}])
    buffer = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(buffer, 'PNG')
    png = buffer.getvalue()
    capture = {'ok': True, 'capture_complete': True, 'title': H.ARM}
    monkeypatch.setattr(S._screenshots, 'capture', lambda c, **kw: S._screenshots.Screenshot(png, capture))
    out = await S.mcp.call_tool('execute', {'calls': [
        {'action': 'click', 'args': {'ref': found['steps'][0]['objects'][0]['ref']}},
        {'action': 'get_screenshot', 'args': {}}]})
    assert isinstance(out, CallToolResult) and [c.type for c in out.content] == ['text', 'image']
    assert not TC_CALL.search(out.content[0].text)
    assert toon_format.decode(out.content[0].text) == {'ok': True, 'steps': [
        {'ok': True}, {**capture, 'connection_id': CONNECTION_ID, 'image': 0}]}
    image = out.content[1]
    assert isinstance(image, ImageContent) and image.mimeType == 'image/png'
    assert base64.b64decode(image.data) == png and len(click.calls) == 1


# ---------------------------------------------------------------- 4.9: пользовательские функции
async def test_custom_functions_appear_with_list_changed_and_hidden_ones_are_refused(mcp, monkeypatch):
    """4.9: у подключённого клиента, обработка которого зарегистрировала функции, сервер шлёт
    tools/list_changed и execute_custom_bsl_function появляется в схеме execute; когда таких клиентов
    нет — снова уведомление, действия скрыты, вызов скрытого отказа прежним сообщением. Состава реестра
    функций в записях нет — запись по формату onec/Testpilot/CUSTOM_FUNCTIONS.md."""
    monkeypatch.setattr(S._code_execution, 'SETTINGS',
                        dataclasses.replace(S._code_execution.SETTINGS, functions=True))
    mcp()
    notifications = []
    async with memory_session(notifications) as session:
        tools = await listed(session)
        assert not set(CUSTOM) & set(action_enum(execute_tool(tools)))
        assert 'execute_custom_bsl_function' not in await search('')
        client = Client()
        client._testpilot_service = {'functions': [
            {'name': 'Спайк', 'context': 'server', 'description': 'Функция записи', 'parameters': []}]}
        connect(client)
        try:
            result = await session.call_tool('execute', {'calls': [{'action': 'list_connections'}]})
            assert not result.isError
            await until(lambda: any(type(n) is ToolListChangedNotification for n in notifications))
            tools = await listed(session)
            assert set(CUSTOM) <= set(action_enum(execute_tool(tools)))
            assert '- execute_custom_bsl_function(' in await search('custom bsl')
            S._pool.entries.clear()                      # клиент с функциями отключился
            result = await session.call_tool('execute', {'calls': [{'action': 'list_connections'}]})
            assert not result.isError
            await until(lambda: sum(type(n) is ToolListChangedNotification for n in notifications) == 2)
            assert not set(CUSTOM) & set(action_enum(execute_tool(await listed(session))))
            assert 'execute_custom_bsl_function' not in await search('')
        finally:
            S._pool.entries.clear()
        with pytest.raises(ToolError, match='Custom BSL functions are not available in connected clients.'):
            await S.mcp.call_tool('execute', {'calls': [
                {'action': 'execute_custom_bsl_function', 'args': {'name': 'Спайк'}}]})


# ---------------------------------------------------------------- 4.10: служебные действия без очереди
async def test_list_connections_answers_while_a_worker_waits_for_1c(server, pool, monkeypatch):
    """4.10, сценарий «Список подключений при занятом клиенте»: рабочий вызов ждёт 1С (единственный поток
    исполнителя занят), пачка из одного list_connections отвечает без ожидания и показывает занятый вызов;
    смешанная пачка [list_connections, get_active_window] исполняется как обычная — ждёт рабочего."""
    client, _ = pool
    client.show(H.LIVE_INFO)
    client._active = H.LIVE_INFO['key']
    gate = threading.Event()

    def slow_window(c):                                  # 1C не отвечает на чтение окна
        gate.wait(10)
        return client.window()
    monkeypatch.setattr(S, '_window', slow_window)
    limiter = anyio.to_thread.current_default_thread_limiter()
    tokens = limiter.total_tokens
    limiter.total_tokens = 1
    worker = asyncio.create_task(S.mcp.call_tool('execute', {'calls': [{'action': 'get_active_window', 'args': {}}]}))
    mixed = None
    try:
        await until(lambda: S._pool.list()[0]['busy'])
        out = await asyncio.wait_for(S.mcp.call_tool('execute', {'calls': [{'action': 'list_connections'}]}), 5)
        connection = toon_format.decode(out[0].text)['steps'][0]['connections']
        assert len(connection) == 1 and not worker.done()
        assert {k: v for k, v in connection[0].items() if k != 'active_seconds'} == {
            'connection_id': CONNECTION_ID, 'profile': None, 'host': '127.0.0.1', 'port': 30000, 'base': None,
            'user': None, 'version': PLATFORM, 'connected': True, 'starting': False, 'launched': False,
            'desktop': None, 'recording': False, 'busy': True, 'active_action': 'get_active_window'}
        mixed = asyncio.create_task(S.mcp.call_tool('execute', {'calls': [
            {'action': 'list_connections'}, {'action': 'get_active_window', 'args': {}}]}))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(mixed), 0.5)
    finally:
        gate.set()
    assert (await worker)[0].text.startswith('ok: true') and (await mixed)[0].text.startswith('ok: true')
    assert toon_format.decode((await mixed)[0].text)['steps'][0]['connections'][0]['busy'] is False
    limiter.total_tokens = tokens


# ---------------------------------------------------------------- 4.11: подсказки называют действия
async def test_action_documentation_and_tool_descriptions_name_actions_not_group_calls(server):
    """4.11: в описаниях search и execute, каталоге и документации каждого действия схемы нет tc_<группа>(;
    тексты ответов всех тестов модуля проверяет text_of()."""
    tools = await S.mcp.list_tools()
    texts = [t.description for t in tools] + [await search('')]
    texts += [await search(name) for name in action_enum(execute_tool(tools))]
    assert len(texts) == 3 + len(catalog_names(texts[2]))
    assert [t for t in texts if TC_CALL.search(t)] == []


# ---------------------------------------------------------------- 4.13: предложенный вызов
async def test_suggested_call_is_an_execute_step(mcp, pool, monkeypatch):
    """4.13, сценарий «Предложенный вызов»: get_cell_text с text: null предлагает is_visible колонки
    «Наименование» таблицы «Список» записи 05-read-rows-focus — шаг {action, args: {ref}, connection_id};
    переданный в execute как есть, он разрешает ref в ключ и handle колонки записи. Кадр GET_CELL_TEXT
    без текста — заглушка: записи чтения ячейки нет, suggested_call строит testpilot."""
    client, _ = pool
    monkeypatch.setattr(S, '_walk_tree',
                        lambda c, root_key=None: [dict(o) for o in LIST_CHILDREN] if root_key == LIST_TABLE['key'] else [])
    live = {o['key']: o for o in (LIST_TABLE, NAME_COLUMN)}
    monkeypatch.setattr(S, '_ref_live_object', lambda c, key: live.get(key))
    table_ref = client._object_handles.remember(LIST_TABLE['key'], LIST_TABLE['handle'])
    visible = []
    monkeypatch.setitem(S._ACTIONS[S._ACTION_GROUP['is_visible']], 'is_visible',
                        lambda key, handle: visible.append({'key': key, 'handle': handle}) or {'ok': True, 'visible': True})
    mcp()
    out = await execute([{'action': 'get_cell_text', 'args': {'ref': table_ref, 'column': 'Наименование'}}])
    assert out['ok'] is True and len(out['steps']) == 1, out
    step = out['steps'][0]
    assert step['text'] is None and step['value_status'] == 'unavailable' and step['column'] == 'Наименование'
    suggested = step['suggested_call']
    assert suggested['action'] == 'is_visible' and suggested['connection_id'] == CONNECTION_ID
    assert set(suggested) == {'action', 'args', 'connection_id'} and list(suggested['args']) == ['ref']
    out = await execute([suggested])                      # шаг — без правки
    assert out['ok'] is True and out['steps'] == [{'ok': True, 'visible': True}]
    assert visible == [{'key': NAME_COLUMN['key'], 'handle': NAME_COLUMN['handle']}]
    assert client.frames == [(S.G.GET_CELL_TEXT, LIST_TABLE['key'], 'read')]


# ---------------------------------------------------------------- 4.12: connect без version
class Versioned:
    """TestClient записи: рукопожатие отказывает, пока не отправлена версия работающей платформы
    (как test_runtime_fixes.Versioned — «Различаются версии клиента и сервера (A - B)»)."""
    DEFAULT_VER = S.tc1c.TestClient.DEFAULT_VER
    running = PLATFORM
    tried = []

    def __init__(self, host, port):
        self.host, self.port, self.platform_version = host, port, None

    def connect(self):
        sent = self.platform_version or self.DEFAULT_VER
        Versioned.tried.append(sent)
        if sent != self.running:
            raise S.tc1c.ConnectionFailure(self.host, self.port, 'authentication',
                                           f'Различаются версии клиента и сервера ({sent} - {self.running})')
        return 'session'

    def attach(self):
        pass

    def close(self):
        pass


async def test_connect_through_execute_without_version_takes_the_running_version(mcp, monkeypatch):
    """4.12, сценарий «Клиент из dev_ib.py client start»: connect без version через execute повторяет
    рукопожатие с версией из отказа; ответ называет платформу 8.3.27.2342 (формат «подключено, сессия …,
    платформа …» — записи 10-live-check, start)."""
    mcp()
    Versioned.tried = []
    monkeypatch.setattr(S.tc1c, 'TestClient', Versioned)
    try:
        out = await execute([{'action': 'connect', 'args': {'port': 30002}}])
        registered = S._pool.list()
    finally:
        S._pool.close()
    assert out['ok'] is True and len(out['steps']) == 1
    assert out['steps'][0] == {'ok': True, 'message': 'подключено, сессия session, платформа 8.3.27.2342',
                               'connection_id': registered[0]['connection_id']}
    assert Versioned.tried == [Versioned.DEFAULT_VER, '8.3.27.2342']
    assert registered[0]['port'] == 30002 and registered[0]['version'] == '8.3.27.2342'
