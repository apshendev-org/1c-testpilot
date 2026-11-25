"""Отказы execute testpilot 2.1.0 (изменение testpilot-execute-errors, матрица tasks.md 5.1–5.9): требования
«Исполнение вызовов», «Синонимы аргументов», «Подсказка в отказе на аргументы», «Действие без подключения»,
«Применимость действия», «Контекст формы по элементу» (specs/mcp-tools) и «Подключение по профилю запуска»
(specs/client-profiles).

Записи живого спайка spike:spk_21dac6344d@v1 (WS, 1С 8.3.27.2342, профиль ib, порт 30000), копии в
tests/recordings/ байт в байт:
  docs/spikes/testpilot-execute-errors/recording/execute-errors-no-client.jsonl — живых клиентов нет;
  docs/spikes/testpilot-execute-errors/recording/execute-errors-connected.jsonl — клиент ib поднят client start.
Строка записи — {ms, dir, msg}: agent→proxy (tools/call), proxy→agent (ответ), note (этап). Ответ execute — toon,
его декодирует toon_format; ожидаемое — ответ записи, а не вычисленное проверяемым кодом.

Откуда что в фейках:
  - ответы шагов, которые дала 1С (find_objects, read_document, get_area_text…), — шаги ответов записи;
  - сессия и версия connect — ответ connect записи («подключено, сессия 273b0a5c-…, платформа 8.3.27.2342»);
  - отказы choose_row / choose_from_drop_list — tc1c.OperationError со статусом записи (10 и 17);
  - объекты окна, формы и поля — ответы execute_command, find_object и get_context записи. Запись в режиме
    ссылок id: ключей и handle в ней нет. Ключи собраны из записанных имён по иерархии записи (поле —
    прямо в форме: parent_ref поля — ref формы), сегмент окна и handle — заглушки (WINDOW_GUID, HANDLES).
  - живость процесса клиента (_client_registry.alive: psutil и порт) — подмена: это ОС, а не 1С.
Разбор аргументов (синонимы, keys, подсказки, проверка пачки) — fuzzing: random.Random(seed), 200 пачек
с шумом; зерно — FUZZ_SEED или время, оно в тексте падения.
"""
import dataclasses
import json
import os
import random
import re
import subprocess
import time
from pathlib import Path

import pytest
import toon_format

import _client_registry
import _connections
import _mcp
import _refs
import server as S

pytestmark = pytest.mark.anyio

RECORDINGS = Path(__file__).resolve().parent / 'recordings'
NO_CLIENT = RECORDINGS / 'execute-errors-no-client.jsonl'
CONNECTED = RECORDINGS / 'execute-errors-connected.jsonl'
TOOLS_MD = Path(__file__).resolve().parent.parent / 'docs' / 'TOOLS.md'


def exchange(path):
    """Вызовы инструментов записи по id JSON-RPC: {tool, arguments, text}."""
    pending, calls = {}, {}
    for line in path.read_text(encoding='utf-8').splitlines():
        msg = json.loads(line).get('msg')
        if not isinstance(msg, dict):
            continue                                   # этап: {ms, dir: "note", note}
        if msg.get('method') == 'tools/call':
            pending[msg['id']] = msg['params']
        elif 'result' in msg and msg.get('id') in pending:
            params = pending.pop(msg['id'])
            calls[msg['id']] = dict(tool=params['name'], arguments=params['arguments'],
                                    text=msg['result']['content'][0]['text'])
    return calls


OFF = exchange(NO_CLIENT)
ON = exchange(CONNECTED)


def calls_of(recording, n):
    call = recording[n]
    assert call['tool'] == 'execute'
    return call['arguments']['calls']


def answer_of(recording, n):
    return toon_format.decode(recording[n]['text'])


# ---- объекты записи connected ----------------------------------------------------------------------------
NAMESPACE = '5fbbee04bd01'                       # ссылки записи e5fbbee04bd01-N
CONNECTION_ID = answer_of(ON, 10)['steps'][0]['connection_id']          # cc48dce49162a40a8
SESSION_TEXT = answer_of(ON, 4)['steps'][0]['message']                  # «подключено, сессия …, платформа …»
SESSION, PLATFORM = re.fullmatch(r'подключено, сессия (\S+), платформа (\S+)', SESSION_TEXT).groups()
OPENED = answer_of(ON, 6)['steps']               # execute_command отчёта, find_object поля
CONTEXT = answer_of(ON, 12)['steps'][0]          # get_context(ref=поле)
WINDOW_GUID = '00000000-0000-0000-0000-0000000000a1'      # заглушка: ключа окна в записи нет
HANDLES = {'window': '00000000-0000-0000-0000-0000000000b1', 'form': '00000000-0000-0000-0000-0000000000b2',
           'field': '00000000-0000-0000-0000-0000000000b3'}  # заглушки (UUID, как требует tc1c): handle в записи нет
FIELD_RECORD = OPENED[1]['object']
assert FIELD_RECORD['ref'] == 'e5fbbee04bd01-6' and FIELD_RECORD['type'] == 'SpreadsheetDocumentField'
assert next(e for e in CONTEXT['elements'] if e['ref'] == FIELD_RECORD['ref'])['parent_ref'] == CONTEXT['form']['ref']
WINDOW_KEY = 'SecondaryFrame[%s]' % WINDOW_GUID
FORM_KEY = '%s.ManagedForm[%s]' % (WINDOW_KEY, CONTEXT['form']['name'])
FIELD_KEY = '%s.EditField[%s]' % (FORM_KEY, FIELD_RECORD['name'])
WINDOW = {'key': WINDOW_KEY, 'handle': HANDLES['window'], 'class': 'SecondaryFrame',
          **{k: v for k, v in OPENED[0]['window'].items() if k != 'ref'}}
FORM = {'key': FORM_KEY, 'handle': HANDLES['form'],
        **{k: v for k, v in CONTEXT['form'].items() if k not in ('ref', 'modified')}}
FIELD = {'key': FIELD_KEY, 'handle': HANDLES['field'], **{k: v for k, v in FIELD_RECORD.items() if k != 'ref'}}


class Client:
    """Клиент 1С записи: версия платформы, реестр ссылок с пространством имён записи; кадры — в журнал,
    статус отказа клиента (refuse) — tc1c.OperationError, как ответ 1С записи."""
    def __init__(self):
        self.platform_version = PLATFORM
        self.frames, self.refuse = [], None
        self._object_handles = _refs.Registry()
        self._object_handles._namespace = NAMESPACE

    def send_cmd(self, guid, key, **kw):
        self.frames.append((guid, key, kw.get('kind')))
        if self.refuse is not None:
            raise S.tc1c.OperationError(self.refuse, key)
        return {'ok': True, 'raw': b''}

    def ref(self, obj):
        return self._object_handles.remember(obj['key'], obj['handle'])


class Recorded:
    """tc1c.TestClient записи: рукопожатие отвечает сессией записи только с версией записи; made — (host,
    port, version) каждого созданного клиента."""
    DEFAULT_VER = S.tc1c.TestClient.DEFAULT_VER
    made = []

    def __init__(self, host, port):
        self.host, self.port, self.platform_version = host, port, None
        Recorded.made.append([host, port, None])

    def connect(self):
        Recorded.made[-1][2] = self.platform_version
        if self.platform_version != PLATFORM:
            raise S.tc1c.ConnectionFailure(self.host, self.port, 'authentication',
                                           f'Различаются версии клиента и сервера ({self.platform_version} - {PLATFORM})')
        return SESSION

    def attach(self):
        pass

    def close(self):
        pass


# ---- фикстуры ----------------------------------------------------------------------------------------------
@pytest.fixture
def mcp(monkeypatch):
    """Свежая публикация search/execute на текущих настройках S; после теста пул пуст, S.mcp прежний."""
    def publish():
        monkeypatch.setattr(S, 'mcp', _mcp.TestpilotMCP(S))
        S._register_groups()
        return S.mcp
    yield publish
    S._pool.close()
    S._pool.entries.clear()


@pytest.fixture
def server(mcp):
    return mcp()


@pytest.fixture
def dispatched(monkeypatch):
    """Шпион _dispatch_action: dispatched.calls — аргументы шагов, дошедших до исполнения (после синонимов);
    dispatched.answers — ответы по порядку (по умолчанию {'ok': True})."""
    def spy(acts, group, kw):
        spy.calls.append(dict(kw))
        return spy.answers.pop(0) if spy.answers else {'ok': True}
    spy.calls, spy.answers = [], []
    monkeypatch.setattr(S, '_dispatch_action', spy)
    return spy


@pytest.fixture
def connected(monkeypatch):
    """Соединение пула с клиентом записи (connection_id записи); чтения runtime отвечают объектами записи."""
    client = Client()
    connection = _connections.Connection('127.0.0.1', 30000)
    connection.id = CONNECTION_ID
    connection.state['connection_id'] = CONNECTION_ID
    connection.starting = False
    connection.state['client'] = client
    S._pool.entries[CONNECTION_ID] = connection
    live = {o['key']: o for o in (WINDOW, FORM, FIELD)}
    monkeypatch.setattr(S, '_window', lambda c: dict(WINDOW))
    monkeypatch.setattr(S, '_ref_live_object', lambda c, key: dict(live[key]) if key in live else None)
    monkeypatch.setattr(S, '_search_objects', lambda c, root=None: [dict(FIELD)] if root == FORM_KEY else [])
    return client


PROFILES = """profiles:
  ib:
    base: bgu-dev-ib-1
    server: true
    user: Тестировщик
  ib-debug:
    base: bgu-dev-ib-1
    server: true
    user: Тестировщик
  ib-other:
    base: bgu-dev-ib-1
    server: true
    user: Бухгалтер
"""
# Порты: ib — порт записи (30000), остальные — соседние.
PORTS = {'ib': 30000, 'ib-debug': 30001, 'ib-other': 30002}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    """Профили запуска ib, ib-debug (та же база, сервер и пользователь), ib-other (другой пользователь) и реестр
    .testpilot-clients.json. clients(*имена) — какие клиенты живы. Запуск процесса и TestClient — под журналом:
    clients.spawned — запуски процессов, Recorded.made — созданные TestClient."""
    profiles = tmp_path / 'profiles.yaml'
    profiles.write_text(PROFILES, encoding='utf-8')
    monkeypatch.setenv('TC1C_PROFILES_FILE', str(profiles))
    registry = _client_registry.path(profiles)
    alive = set()
    monkeypatch.setattr(_client_registry, 'alive', lambda entry: entry.get('port') in alive)
    Recorded.made = []
    monkeypatch.setattr(S.tc1c, 'TestClient', Recorded)
    spawned = []
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: spawned.append(a) or pytest.fail('процесс запущен'))

    def run(*names):
        for name in PORTS:
            _client_registry.record(registry, name, port=PORTS[name], pid=4000 + PORTS[name] % 100,
                                    host='127.0.0.1', version=PLATFORM)
        alive.clear()
        alive.update(PORTS[n] for n in names)
    run.registry, run.spawned = registry, spawned
    return run


async def execute(calls):
    result = await S.mcp.call_tool('execute', {'calls': calls})
    if isinstance(result, tuple):
        result = result[0]
    assert [c.type for c in result] == ['text']
    return toon_format.decode(result[0].text)


async def search(query):
    result = await S.mcp.call_tool('search', {'query': query})
    if isinstance(result, tuple):
        result = result[0]
    return result[0].text


def without(step, *names):
    return {k: v for k, v in step.items() if k not in names}


# ---------------------------------------------------------------- 5.1: проверка пачки до запуска
@pytest.mark.parametrize('recording, n', [(OFF, 4), (ON, 5), (OFF, 5)],
                         ids=['no-client-step2-missing-ref', 'connected-step2-missing-address', 'forward-reference'])
async def test_recorded_batch_with_bad_step_is_refused_before_the_first_step(server, dispatched, recording, n):
    """5.1, сценарии «Ошибка в третьем шаге» и «Ссылка на шаг впереди»: пачки записи (шаг 2 без обязательного
    ref / address; $1 в шаге 0) отказаны целиком, как в записи: step, «Nothing was executed», без steps;
    ни один шаг (в записи connected — execute_command отчёта) до исполнения не дошёл."""
    out = await execute(calls_of(recording, n))
    assert out == answer_of(recording, n)
    assert 'steps' not in out and 'othing was executed' in out['error']
    assert dispatched.calls == []


@pytest.mark.parametrize('third, expected', [
    ({'action': 'click', 'args': {'ref': 'e5fbbee04bd01-6', 'text': 'X'}},
     {'code': 'invalid_arguments', 'unexpected_parameters': ['text'], 'missing_parameters': []}),
    ({'action': 'set_current_area', 'args': {'ref': 'e5fbbee04bd01-6'}},
     {'code': 'invalid_arguments', 'unexpected_parameters': [], 'missing_parameters': ['address']}),
    ({'action': 'find_object', 'args': {'name': 'ОтчетТабличныйДокумент', 'timeout': 'долго'}},
     {'code': 'invalid_arguments'}),
    ({'action': 'set_current_area', 'args': {'ref': '$2.object.ref', 'address': 'R1C1'}},
     {'code': 'unresolved_reference'}),
], ids=['extra', 'missing', 'literal-type', 'forward-reference'])
async def test_any_bad_third_step_refuses_the_whole_batch(server, dispatched, third, expected):
    """5.1: лишний, нет обязательного, неверный тип литерала, $N вперёд — в шаге 2 пачки записи
    [execute_command, find_object, …]: отказ пачки со step: 2, ничего не исполнено."""
    batch = calls_of(ON, 6) + [third]
    out = await execute(batch)
    assert out['ok'] is False and out['step'] == 2 and 'steps' not in out, out
    assert {k: out.get(k) for k in expected} == expected
    assert 'othing was executed' in out['error']
    if third['action'] == 'find_object':
        assert out['error'].startswith('Wrong argument types: timeout:')
        assert out['signature'].startswith('find_object(')
    assert dispatched.calls == []


async def test_reference_to_an_earlier_step_passes_the_check_and_is_typed_after_substitution(server, dispatched):
    """5.1, сценарий «Значение из прошлого шага»: обязательный ref шага 1 — "$0.objects.0.ref": пачка проходит
    проверку, ref подставлен из записанного ответа find_objects (поле e5fbbee04bd01-6). Тип проверяется после
    подстановки: timeout = "$0.objects.0.name" (строка ОтчетТабличныйДокумент) — шаг 1 отказан по типу,
    шаг 0 исполнен."""
    found = without(answer_of(ON, 8)['steps'][0], 'renamed')
    dispatched.answers = [dict(found), {'ok': True}]
    out = await execute([{'action': 'find_objects', 'args': {'name': FIELD_RECORD['name']}},
                         {'action': 'set_current_area', 'args': {'ref': '$0.objects.0.ref', 'address': 'R1C1'}}])
    assert out == {'ok': True, 'steps': [found, {'ok': True}]}
    assert [(c['action'], c.get('ref'), c.get('address')) for c in dispatched.calls] == [
        ('find_objects', None, None), ('set_current_area', FIELD_RECORD['ref'], 'R1C1')]

    dispatched.calls.clear()
    dispatched.answers = [dict(found)]
    out = await execute([{'action': 'find_objects', 'args': {'name': FIELD_RECORD['name']}},
                         {'action': 'find_object', 'args': {'name': 'x', 'timeout': '$0.objects.0.name'}}])
    assert out['ok'] is False and out['stopped_at'] == 1 and out['steps'][0] == found
    assert out['steps'][1]['code'] == 'invalid_arguments'
    assert out['steps'][1]['error'].startswith('Wrong argument types: timeout:')
    assert [c['action'] for c in dispatched.calls] == ['find_objects']


# ---------------------------------------------------------------- 5.2: синонимы
# Таблица design, решение 1: (действия, синоним, значение, параметр).
CELL = ('set_current_area', 'set_area_text', 'included_in_merged_area')
AREA = ('get_area_text', 'get_current_area_text', 'text_within_area_bounds')
READ = ('read_document', 'find_text')
SYNONYMS = ([(a, s, 'R2C3', 'address') for a in CELL for s in ('area', 'cell')]
            + [(a, s, 'R1C1:R3C3', 'area') for a in AREA for s in ('address', 'range')]
            + [(a, 'range', 'R1C1:R3C3', 'area') for a in READ]
            + [(a, 'address', 'R1C1:R5C4', 'area') for a in READ]
            + [(a, 'address', 'R10C1', 'start_address') for a in READ]
            + [(a, 'cell', 'R10C1', 'start_address') for a in READ]
            + [(a, 'ref', 'e5fbbee04bd01-2', 'root_ref') for a in ('find_objects', 'find_object')])
REQUIRED = {'set_area_text': {'text': 'x'}, 'find_text': {'text': 'zzz'}}


@pytest.mark.parametrize('action, alias, value, parameter', SYNONYMS,
                         ids=['%s-%s-%s' % (a, s, v) for a, s, v, _ in SYNONYMS])
async def test_each_synonym_becomes_its_parameter_and_is_reported(server, dispatched, action, alias, value, parameter):
    """5.2, требование «Синонимы аргументов»: каждый синоним таблицы design даёт канонический параметр с тем же
    значением, ответ шага — renamed {синоним: параметр}; address у read_document/find_text — по «:»."""
    args = {alias: value, **REQUIRED.get(action, {})}
    if alias != 'ref':
        args['ref'] = FIELD_RECORD['ref']
    out = await execute([{'action': action, 'args': args}])
    assert out == {'ok': True, 'steps': [{'ok': True, 'renamed': {alias: parameter}}]}
    [call] = dispatched.calls
    assert call[parameter] == value and alias not in call or alias == 'ref' and 'ref' not in call


@pytest.mark.parametrize('n', [7, 8], ids=['spreadsheet-synonyms', 'find_objects-ref'])
async def test_recorded_synonym_batches_answer_as_in_the_recording(server, dispatched, n):
    """5.2, сценарии «area вместо address» и «address у чтения документа»: пачки синонимов записи connected
    (set_current_area(area), get_area_text(address), text_within_area_bounds(address), read_document(address
    с «:» и без), find_text(cell); find_objects(ref)) — ответ execute равен записанному: шаги 1С записи и
    renamed каждого шага; до 1С дошли канонические имена."""
    recorded = answer_of(ON, n)
    dispatched.answers = [without(step, 'renamed') for step in recorded['steps']]
    out = await execute(calls_of(ON, n))
    assert out == recorded
    for call, sent, step in zip(dispatched.calls, calls_of(ON, n), recorded['steps']):
        for alias, parameter in step['renamed'].items():
            assert alias not in call and call[parameter] == sent['args'][alias]


async def test_synonym_together_with_its_parameter_is_an_extra_argument(server, dispatched):
    """5.2, сценарий «Синоним и параметр вместе» (запись no-client): set_area_text с address и area —
    invalid_arguments, area лишний, did_you_mean {area: address}; ничего не исполнено."""
    out = await execute(calls_of(OFF, 8))
    assert out == answer_of(OFF, 8)
    assert out['unexpected_parameters'] == ['area'] and out['did_you_mean'] == {'area': 'address'}
    assert dispatched.calls == []


# ---------------------------------------------------------------- 5.3: send_keys строкой
@pytest.fixture
def keyboard(monkeypatch):
    """Клавиатура ОС: активизация цели и отправка сочетания — в журнал (сочетание после разбора keys)."""
    import _keyboard
    sent = []
    monkeypatch.setattr(_keyboard, 'activate_target', lambda S_, c, key, handle: WINDOW_KEY)
    monkeypatch.setattr(_keyboard, 'send_shortcut', lambda S_, c, wk, chord: sent.append((wk, list(chord))))
    return sent


async def test_keys_string_sends_the_same_chord_as_a_list(server, connected, keyboard):
    """5.3, сценарий «keys строкой»: send_keys записи (keys "CTRL+HOME" по полю) отвечает как в записи
    (keys [CTRL, HOME]) и отправляет то же сочетание, что keys списком. ref — ссылка поля этого прогона."""
    ref = connected.ref(FIELD)
    [call] = calls_of(ON, 9)
    assert call['args']['keys'] == 'CTRL+HOME'
    out = await execute([{**call, 'args': {**call['args'], 'ref': ref}}])
    assert out == answer_of(ON, 9)
    as_list = [{'action': 'send_keys', 'args': {'ref': ref, 'keys': ['CTRL', 'HOME']}}]
    assert await execute(as_list) == answer_of(ON, 9)
    assert keyboard == [(WINDOW_KEY, ['CTRL', 'HOME'])] * 2


# ---------------------------------------------------------------- 5.4: подсказки
@pytest.mark.parametrize('n', [6, 7], ids=['activate_window-ref', 'goto_row-values'])
async def test_recorded_refusals_name_the_right_parameter_or_action(server, dispatched, n):
    """5.4, сценарии «Окно по ref» и «Похожее имя» (запись no-client): activate_window(ref) — suggested_actions
    с activate; goto_row(values) — did_you_mean {values: fields}. Ответ равен записанному, ничего не исполнено."""
    out = await execute(calls_of(OFF, n))
    assert out == answer_of(OFF, n)
    if n == 6:
        assert out['unexpected_parameters'] == ['ref'] and 'activate' in out['suggested_actions']
    else:
        assert out['did_you_mean'] == {'values': 'fields'}
    assert dispatched.calls == []


async def test_hint_for_a_name_with_a_line_break_keeps_the_answer_readable(server, dispatched):
    """5.4, найдено fuzzing (FUZZ_SEED=1795630285447278537, вход 123): лишний аргумент "ref\\n" у set_area_text
    получает did_you_mean {"ref\\n": "ref"} (difflib). Ответ execute остаётся toon, который читается обратно:
    имя из входа — как передано, подсказка — параметр действия."""
    args = {'ref': FIELD_RECORD['ref'], 'address': 'R1C1', 'text': 'x', 'ref\n': True}
    out = await execute([{'action': 'set_area_text', 'args': args}])
    assert out['code'] == 'invalid_arguments' and out['unexpected_parameters'] == ['ref\n']
    assert out['did_you_mean'] == {'ref\n': 'ref'}
    assert dispatched.calls == []


NOISE = ['\x1b[31m', '\x1b[0m', '\r\n', '\n', '\t', '\x00', '​', 'Ж', 'ё', '🙂', ' ', '+', ':', '$', '$$', '$0.']
FUZZ_ACTIONS = sorted({a for a, *_ in SYNONYMS} | {'send_keys', 'goto_row', 'activate_window', 'click'})


def noisy(rng, text):
    """Текст с шумом: управляющие последовательности, CRLF, Юникод, обрыв."""
    text = list(text)
    for _ in range(rng.randint(0, 3)):
        text.insert(rng.randint(0, len(text)), rng.choice(NOISE))
    text = ''.join(text)
    return text[:rng.randint(0, len(text))] if rng.random() < 0.2 else text


def signature_params(doc):
    """Параметры действия из первой строки search(<действие>): «- name(a*, b=1)» → {a, b}."""
    inner = re.match(r'- \w+\((.*)\)$', doc.splitlines()[0]).group(1)
    return {p.split('=')[0].rstrip('*').strip() for p in inner.split(', ') if p}


def fuzz_args(rng, params):
    names = sorted(params) + ['area', 'address', 'cell', 'range', 'ref', 'values', 'text', 'keys', 'key', 'name']
    args = {}
    for _ in range(rng.randint(0, 5)):
        name = rng.choice(names)
        name = noisy(rng, name) if rng.random() < 0.3 else name
        kind = rng.random()
        if name == 'keys' and kind < 0.5:
            value = noisy(rng, rng.choice(['CTRL+S', 'CTRL+SHIFT+F', 'ALT + F4', '+', '', 'ENTER']))
        elif kind < 0.6:
            value = noisy(rng, rng.choice(['R1C1', 'R1C1:R3C3', 'e5fbbee04bd01-6', 'Номер', 'x']))
        elif kind < 0.7:
            value = rng.choice([0, 1, -5, 10 ** 12, 2.5, True, None])
        elif kind < 0.85:
            value = [noisy(rng, 'CTRL'), noisy(rng, 'S')]
        else:
            value = {noisy(rng, 'Номер'): noisy(rng, '1')}
        args[name] = value
    return args


def strings(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)
    elif isinstance(value, str):
        yield value


async def test_fuzzed_arguments_never_crash_and_hints_name_only_real_parameters(server, dispatched):
    """5.4 и требование fuzzing (tasks.md, группа 5): 200 пачек из 1–3 шагов действий таблицы синонимов,
    send_keys, goto_row, activate_window, click с шумными именами и значениями. Без исключений; отказ пачки —
    invalid_arguments или unresolved_reference со step в пачке; unexpected — из переданных имён,
    did_you_mean — {переданное: параметр действия}, suggested_actions — действия каталога; до исполнения
    доходят только параметры действия (кроме значений None — их отбрасывает _dispatch_action), значения — из входа (keys строкой — её части между «+»), renamed —
    {переданное: параметр}."""
    seed = int(os.environ.get('FUZZ_SEED') or time.time_ns())
    rng = random.Random(seed)
    params = {a: signature_params(await search(a)) for a in FUZZ_ACTIONS}
    catalog = set(re.findall(r'[a-z_]+', '\n'.join(l for l in (await search('')).splitlines() if l.startswith('  '))))
    for case in range(200):
        batch = [{'action': a, 'args': fuzz_args(rng, params[a])}
                 for a in (rng.choice(FUZZ_ACTIONS) for _ in range(rng.randint(1, 3)))]
        where = 'FUZZ_SEED=%d, вход %d: %r' % (seed, case, batch)
        dispatched.calls.clear()
        try:
            out = await execute(batch)
        except Exception as exc:                       # noqa: BLE001 — текст падения с зерном
            pytest.fail('%s: исключение %r' % (where, exc))
        assert isinstance(out, dict) and type(out.get('ok')) is bool, where
        if 'steps' not in out:                         # отказ пачки до запуска
            assert out['code'] in ('invalid_arguments', 'unresolved_reference'), where
            assert 0 <= out['step'] < len(batch) and dispatched.calls == [], where
            step = batch[out['step']]
            given = set(step['args'])
            assert set(out.get('unexpected_parameters', [])) <= given, where
            assert set(out.get('missing_parameters', [])) <= params[step['action']], where
            hint = out.get('did_you_mean', {})
            assert set(hint) <= set(out.get('unexpected_parameters', [])), where
            assert set(hint.values()) <= params[step['action']], where
            assert set(out.get('suggested_actions', [])) <= catalog, where
            continue
        # Шаг, отказанный в run() (тип или путь после подстановки $N), до исполнения не доходит — он последний.
        refused = len(out['steps']) - len(dispatched.calls)
        assert refused in (0, 1), where
        if refused:
            assert out['stopped_at'] == len(out['steps']) - 1, where
            assert out['steps'][-1]['code'] in ('invalid_arguments', 'unresolved_reference'), where
        for call, sent, step in zip(dispatched.calls, batch, out['steps']):
            # None — «не передан»: _dispatch_action отбрасывает такие аргументы до 1С.
            names = {k for k, v in call.items() if v is not None} - {'action', 'connection_id'}
            assert names <= params[sent['action']], where
            given = list(strings(sent['args']))
            for name in names:
                value = call[name]
                if sent['action'] == 'send_keys' and name == 'keys' and isinstance(sent['args'].get('keys'), str):
                    assert value == [p.strip() for p in sent['args']['keys'].split('+') if p.strip()], where
                    continue
                assert all(s in given for s in strings(value)), where
            renamed = step.get('renamed', {})
            assert set(renamed) <= set(sent['args']) and set(renamed.values()) <= params[sent['action']], where


# ---------------------------------------------------------------- 5.5, 5.6: подключение
async def test_not_connected_with_one_live_client_suggests_connect_and_that_call_connects(mcp, clients):
    """5.5, сценарий «Первое действие сессии», и 5.6, сценарий «Клиент запущен» (запись connected): жив клиент
    ib, MCP не подключён — get_active_window отвечает not_connected с suggested_call connect(profile=ib), как
    в записи, и testpilot сам не подключается; этот вызов без правки подключает к порту клиента ib (30000)
    с версией реестра: ok, profile ib, reused: true — ответ записи (connection_id — новый)."""
    mcp()
    clients('ib')
    out = await execute(calls_of(ON, 3))
    assert out == answer_of(ON, 3)
    assert Recorded.made == [] and S._pool.list() == []
    suggested = out['steps'][0]['suggested_call']
    out = await execute([suggested])
    expected = answer_of(ON, 4)
    connection_id = S._pool.list()[0]['connection_id']
    expected['steps'][0]['connection_id'] = connection_id
    assert out == expected
    assert Recorded.made == [['127.0.0.1', PORTS['ib'], PLATFORM]] and clients.spawned == []


async def test_not_connected_with_two_live_clients_lists_them_without_suggested_call(mcp, clients):
    """5.5, сценарий «Два клиента»: живы ib и ib-debug — not_connected с running (профиль, порт) обоих,
    без suggested_call; подключения нет."""
    mcp()
    clients('ib', 'ib-debug')
    out = await execute([{'action': 'get_active_window', 'args': {}}])
    [step] = out['steps']
    assert step['code'] == 'not_connected' and 'suggested_call' not in step
    assert sorted((r['profile'], r['port']) for r in step['running']) == [('ib', 30000), ('ib-debug', 30001)]
    assert Recorded.made == [] and S._pool.list() == []


async def test_not_connected_without_live_clients_suggests_list_profiles(mcp, clients):
    """5.5 (запись no-client): клиентов нет — not_connected с suggested_call list_profiles, как в записи;
    клиент не запущен, testpilot не подключается."""
    mcp()
    clients()
    out = await execute(calls_of(OFF, 3))
    assert out == answer_of(OFF, 3)
    assert Recorded.made == [] and clients.spawned == []


async def test_connect_profile_takes_the_client_of_the_same_base_and_user(mcp, clients):
    """5.6: жив только клиент ib-debug (та же база, сервер и пользователь) — connect(profile=ib) подключается
    к его порту, ответ называет его профиль, reused: true; клиент ib-other (другой пользователь) не в счёт."""
    mcp()
    clients('ib-debug', 'ib-other')
    out = await execute([{'action': 'connect', 'args': {'profile': 'ib'}}])
    [step] = out['steps']
    assert (step['ok'], step['profile'], step['reused'], step['message']) == (True, 'ib-debug', True, SESSION_TEXT)
    assert Recorded.made == [['127.0.0.1', PORTS['ib-debug'], PLATFORM]]


async def test_connect_profile_without_running_client_suggests_launch_and_starts_nothing(mcp, clients):
    """5.6, сценарий «Клиент не запущен» (запись no-client): жив только клиент другого пользователя —
    profile_action_mismatch с suggested_call launch_client(profile=ib), как в записи; процесс не запущен,
    TestClient не создан, подключения нет."""
    mcp()
    clients('ib-other')
    out = await execute(calls_of(OFF, 11))
    assert out == answer_of(OFF, 11)
    assert clients.spawned == [] and Recorded.made == [] and S._pool.list() == []


async def test_connect_profile_with_two_fitting_clients_is_ambiguous_and_port_chooses(mcp, clients):
    """5.6, сценарий «Два подходящих клиента»: живы ib и ib-debug — client_ambiguous с running обоих,
    подключения нет; с port — только клиент этого порта (ib-debug, 30001)."""
    mcp()
    clients('ib', 'ib-debug')
    out = await execute([{'action': 'connect', 'args': {'profile': 'ib'}}])
    [step] = out['steps']
    assert step['ok'] is False and step['code'] == 'client_ambiguous'
    assert sorted((r['profile'], r['port']) for r in step['running']) == [('ib', 30000), ('ib-debug', 30001)]
    assert Recorded.made == [] and S._pool.list() == []
    out = await execute([{'action': 'connect', 'args': {'profile': 'ib', 'port': 30001}}])
    [step] = out['steps']
    assert (step['ok'], step['profile'], step['reused']) == (True, 'ib-debug', True)
    assert Recorded.made == [['127.0.0.1', 30001, PLATFORM]] and clients.spawned == []


# ---------------------------------------------------------------- 5.7: применимость в search
@pytest.mark.parametrize('n', [9, 10], ids=['choose_row', 'set_current_area'])
async def test_search_shows_applies_to_as_recorded(server, n):
    """5.7, сценарий «Описание действия» (запись no-client): search(choose_row) — строка «Applies to: Table.»,
    search(set_current_area) — «Applies to: EditField (SpreadsheetDocumentField).»; текст равен записанному."""
    query = OFF[n]['arguments']['query']
    text = await search(query)
    assert text == OFF[n]['text']
    assert {'choose_row': 'Applies to: Table.',
            'set_current_area': 'Applies to: EditField (SpreadsheetDocumentField).'}[query] in text.splitlines()


# Типы 1С столбца «Применим к типам» → классы элементов (`class` ответов find_objects). design, решение 6;
# HomePage — класс окна начальной страницы (get_active_window записи connected, id 14). Классы группы
# командного интерфейса design не называет — Navigation, SubSystems, SWINOpened (классы ключей _collection).
TYPE_CLASSES = {
    'ТестируемоеПолеФормы': {'EditField'}, 'ТестируемаяТаблицаФормы': {'Table'},
    'ТестируемаяКнопкаФормы': {'Button'}, 'ТестируемаяГруппаФормы': {'Group'},
    'ТестируемаяДекорацияФормы': {'Decoration'}, 'ТестируемоеДополнениеЭлементаФормы': {'Additional'},
    'ТестируемаяФорма': {'ManagedForm'},
    'ТестируемоеОкноКлиентскогоПриложения': {'MainFrame', 'SecondaryFrame', 'HomePage'},
    'ТестируемыйКомандныйИнтерфейсОкна': {'CI'}, 'ТестируемаяКнопкаКомандногоИнтерфейса': {'CIButton'},
    'ТестируемаяГруппаКомандногоИнтерфейса': {'Navigation', 'SubSystems', 'SWINOpened'},
    'ТестируемоеПриложение': set(),
    'Приложение': set(),           # так в TOOLS.md у get_screenshot: действие без элемента
}
assert re.search(r'HomePage', ON[14]['text'])


def documented_types():
    """{действие: типы 1С} из таблиц действий docs/TOOLS.md (первый столбец «Действие»): типы — столбец
    «Применим к типам»; «—» и таблица без этого столбца (keyboard, действия обработки Testpilot) — пусто."""
    out, column = {}, False
    for line in TOOLS_MD.read_text(encoding='utf-8').splitlines():
        if not line.startswith('|'):
            column = False
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if cells[0] == 'Действие':
            column = cells.index('Применим к типам') if 'Применим к типам' in cells else None
            continue
        if column is False or set(cells[0]) <= {'-'}:
            continue
        for action in re.findall(r'`(\w+)`', cells[0]):
            out[action] = set(re.findall(r'`(\w+)`', cells[column])) if column is not None else set()
    return out


async def test_applies_to_of_every_action_matches_the_tools_md_column(mcp, monkeypatch):
    """5.7: для каждого действия каталога с документированными типами строка Applies to в search(<действие>)
    перечисляет классы типов столбца «Применим к типам» docs/TOOLS.md (уточнение вида поля в скобках —
    только у EditField); у действий без элемента (ТестируемоеПриложение, «—») строки нет. Все действия
    каталога есть в таблицах."""
    monkeypatch.setattr(S._code_execution, 'SETTINGS',
                        dataclasses.replace(S._code_execution.SETTINGS, code=True, query=True))
    mcp()
    documented = documented_types()
    assert set(documented) >= {'choose_row', 'set_current_area', 'activate', 'connect'}
    assert documented and all(t in TYPE_CLASSES for ts in documented.values() for t in ts)
    catalog = re.findall(r'[a-z_]+', '\n'.join(l for l in (await search('')).splitlines() if l.startswith('  ')))
    mismatched = []
    for action in catalog:
        assert action in documented, action
        expected = set().union(*(TYPE_CLASSES[t] for t in documented[action])) if documented[action] else set()
        lines = [l for l in (await search(action)).splitlines() if l.startswith('Applies to: ')]
        shown = set()
        if lines:
            assert len(lines) == 1, action
            body = lines[0][len('Applies to: '):].rstrip('.')
            for part in re.findall(r'(\w+)(?: \(([^)]*)\))?', body):
                assert not part[1] or part[0] == 'EditField', (action, body)
                shown.add(part[0])
        if shown != expected:
            mismatched.append((action, sorted(expected), sorted(shown)))
    assert mismatched == []


# ---------------------------------------------------------------- 5.8: отказ о типе элемента
@pytest.mark.parametrize('n, status', [(10, 10), (11, 17)], ids=['choose_row', 'choose_from_drop_list'])
async def test_type_refusal_names_element_class_applies_to_and_fitting_actions(server, connected, n, status):
    """5.8, сценарий «Выбор из списка не для этого элемента» (запись connected): 1С отвергает choose_row по полю
    табличного документа статусом 10, choose_from_drop_list — 17. Отказ равен записанному: element_class
    EditField, applies_to действия, suggested_actions записи; их до 5, без вызванного, все применимы к
    EditField по docs/TOOLS.md. target — ссылка поля этого прогона (в записи e5fbbee04bd01-6)."""
    connected.refuse = status
    ref = connected.ref(FIELD)
    [call] = calls_of(ON, n)
    out = await execute([{**call, 'args': {**call['args'], 'ref': ref}}])
    recorded = answer_of(ON, n)
    assert without(out, 'steps') == without(recorded, 'steps')
    [step], [expected] = out['steps'], recorded['steps']
    assert without(step, 'target') == without(expected, 'target') and step['target'] == ref
    assert connected.frames and {f[1] for f in connected.frames} == {FIELD_KEY}
    documented = documented_types()
    suggested = step['suggested_actions']
    assert 0 < len(suggested) <= 5 and call['action'] not in suggested
    assert all('ТестируемоеПолеФормы' in documented[a] for a in suggested), suggested


# ---------------------------------------------------------------- 5.9: get_context по элементу
@pytest.fixture
def form_reads(monkeypatch):
    """Чтения формы записи: свойства поля (visible, enabled, readonly) и формы (modified, текущий элемент —
    поле, current_ref записи), текущая область табличного документа (documents записи: R1C1, не редактируется)."""
    recorded = next(e for e in CONTEXT['elements'] if e['ref'] == FIELD_RECORD['ref'])
    for prop in ('visible', 'enabled', 'readonly'):
        monkeypatch.setattr(S, 'tc_is_' + prop, lambda key, handle, prop=prop: {'ok': True, prop: recorded[prop]})
    monkeypatch.setattr(S, 'tc_current_modified', lambda key, handle: {'ok': True, 'modified': CONTEXT['form']['modified']})
    monkeypatch.setattr(S, 'tc_get_current_element', lambda key, handle: {'ok': True, 'item': [
        {'key': FIELD_KEY, 'handle': HANDLES['field']}]})
    [document] = CONTEXT['documents']
    monkeypatch.setattr(S, 'tc_get_current_area_address', lambda key, handle: {'ok': True, 'address': document['current_area']})
    monkeypatch.setattr(S, 'tc_current_mode_is_edit', lambda key, handle: {'ok': True, 'edit': document['editing'],
                                                                           'editing': document['editing']})
    return recorded


async def test_get_context_by_field_ref_reads_its_form_and_returns_form_ref(server, connected, form_reads):
    """5.9, сценарий «ref поля» (запись connected): get_context(ref=поле, result_mode=full) читает форму поля —
    form записи (заголовок, имя, form_name, modified), поле среди элементов с parent_ref формы, form_ref —
    ссылка этой формы."""
    form_ref = connected.ref(FORM)
    field_ref = connected.ref(FIELD)
    [call] = calls_of(ON, 12)
    out = await execute([{**call, 'args': {**call['args'], 'ref': field_ref}}])
    assert out['ok'] is True, out
    [step] = out['steps']
    assert step['form'] == {**CONTEXT['form'], 'ref': form_ref}
    assert step['form_ref'] == form_ref
    [field] = [e for e in step['elements'] if e['ref'] == field_ref]
    assert field['parent_ref'] == form_ref and field['name'] == FIELD_RECORD['name']
    assert {k: field[k] for k in ('visible', 'enabled', 'readonly', 'class', 'type')} == {
        k: form_reads[k] for k in ('visible', 'enabled', 'readonly', 'class', 'type')}


async def test_get_context_by_element_outside_a_form_is_refused_with_suggested_actions(server, connected, form_reads):
    """5.9: ref окна отчёта (SecondaryFrame записи, вне управляемой формы) — unsupported_receiver с element_class
    окна и suggested_actions, применимыми к окну по docs/TOOLS.md, без get_context."""
    window_ref = connected.ref(WINDOW)
    out = await execute([{'action': 'get_context', 'args': {'ref': window_ref}}])
    [step] = out['steps']
    assert out['ok'] is False and step['code'] == 'unsupported_receiver', step
    assert step['element_class'] == 'SecondaryFrame'
    documented = documented_types()
    assert 0 < len(step['suggested_actions']) <= 5 and 'get_context' not in step['suggested_actions']
    assert all('ТестируемоеОкноКлиентскогоПриложения' in documented[a] for a in step['suggested_actions'])
