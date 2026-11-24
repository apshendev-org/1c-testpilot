"""Записи спайка testpilot-ui-feedback (spike:spk_91306bdbfc@v1) — новые строки матрицы тестов изменения
testpilot-ui-feedback (tasks.md 2.2): защита ячейки (spreadsheet-edit), current_opened (form-groups),
activate_window(title) (window-activation) и факты записей без правки кода: ref после переоткрытия формы,
кириллица в параметрах execute_code, ОткрытьФорму при другой вкладке, сеанс.

Записи — MCP-уровня: вызов инструмента testpilot прежнего кода (релиз v2.24.2) и его ответ (копии —
tests/recordings/, байт в байт); TC1C_COMPACT_REFS=id, ответ JSON,
пространство имён ссылок e4b5202213268-N (02–04) и ed62d72777fd8-N (01, 06). Полному адресу внутри runtime
соответствует имя (GUID) из get_child_objects записи: окно — SecondaryFrame[<GUID>], форма — его
ManagedForm[<GUID>]. Заглушка клиента отвечает тем, что в записи ответила 1С: отказ статуса 11 в начале правки
защищённой R2C4 и успех у R2C5; Скрыта() группы кодом; ManagedForm и заголовки из find_objects; статус 7 по
адресу закрытой формы (docs/spikes/testpilot-ui-feedback/recording-off/02b-ref-after-reopen-off.jsonl — та же
ситуация с полными адресами и handle, копией не стала: источник копии ищется только в recording/).

Записи спайка (tests/_recording.py: UI_*):
- docs/spikes/testpilot-ui-feedback/recording/00-session.jsonl — сеанс: инструменты прежнего кода, платформа;
- docs/spikes/testpilot-ui-feedback/recording/01-protected-cell.jsonl — защищённая и свободная ячейка R2C4/R2C5;
- docs/spikes/testpilot-ui-feedback/recording/02-ref-after-reopen.jsonl — ссылка кнопки после переоткрытия формы;
- docs/spikes/testpilot-ui-feedback/recording/03-current-opened.jsonl — Скрыта() группы и current_opened;
- docs/spikes/testpilot-ui-feedback/recording/04-windows-by-title.jsonl — две вкладки, активизация по заголовку;
- docs/spikes/testpilot-ui-feedback/recording/05-cyrillic-parameters.jsonl — кириллица в параметрах кода;
- docs/spikes/testpilot-ui-feedback/recording/06-open-form-while-other-tab-active.jsonl — ОткрытьФорму при другой вкладке.

Ожидания — из нового интерфейса; прежний ответ записи сравнивается там, где поведение не менялось.
Действия правки ячейки и current_opened вызываются обработчиками без обёрток MCP (inspect.unwrap, как
tests/test_cell_edit.py); окна, поиск и клик — через execute (S.mcp.call_tool), ответ — toon-текст.
"""
import dataclasses
import inspect
import json
import os
import re
import sys
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
import toon_format

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _code_execution as E  # noqa: E402
import _connections  # noqa: E402
import _helper_client as H  # noqa: E402
import _mcp  # noqa: E402
import _recording as recorded  # noqa: E402
import _refs  # noqa: E402
import guids as G  # noqa: E402
import tc1c  # noqa: E402
import _runtime as R  # noqa: E402
import server as S  # noqa: E402

pytestmark = pytest.mark.anyio

PROTECTED = recorded.ui(recorded.UI_PROTECTED)
REOPEN = recorded.ui(recorded.UI_REOPEN)
OPENED = recorded.ui(recorded.UI_OPENED)
WINDOWS = recorded.ui(recorded.UI_WINDOWS)
CYRILLIC = recorded.ui(recorded.UI_CYRILLIC)
OPEN_FORM = recorded.ui(recorded.UI_OPEN_FORM)
SESSION = recorded.ui(recorded.UI_SESSION)
PLATFORM = '8.3.27.2342'
SESSION_0204 = 'cb6989a815f664409'          # connection_id записей 02–05 (один сеанс)
SESSION_06 = 'c61e5f4d1317a45ed'            # connection_id записей 00, 01, 06
SPIKE_TITLE = 'Спайк АРМ КС: сетка'


def one(calls, step, action, nth=0):
    """Вызов записи (step, action); nth — порядковый номер, если в шаге несколько таких вызовов."""
    rows = [c for c in calls if c['step'] == step and c['action'] == action]
    assert len(rows) > nth, (step, action, nth)
    return rows[nth]


def answer(call):
    """Ответ записи без connection_id (сеанс добавляет его снаружи)."""
    return {k: v for k, v in call['response'].items() if k != 'connection_id'}


def window_of(call):
    """Окно из ответа get_active_window записи, как его читает runtime (_window): без версии и connection_id."""
    return {k: v for k, v in call['response'].items() if k not in ('platform_version', 'connection_id')}


def without_ids(call):
    """Ответ execute_code записи без request_id и connection_id."""
    return {k: v for k, v in call['response'].items() if k not in ('request_id', 'connection_id')}


def frames(client, guid):
    """Кадры метода, ушедшие в клиента-заглушку: [(ключ, вид кадра)]."""
    return [(key, kind) for g, key, kind in client.frames if g == guid]


def action(name, **arguments):
    """Обработчик без обёрток MCP (проверка адреса и цели, диагностика) — как tests/test_cell_edit.py."""
    return inspect.unwrap(getattr(R, 'tc_' + name))(**arguments)


# ---- защита ячейки (spreadsheet-edit, запись 01) ----------------------------------------------

# Полный адрес и handle поля ТаблицаАРМ той же формы — из записи спайка cell-edit (Python API): в записи 01
# адреса компактные, а set_area_text проверяет класс адреса.
DOC = next(o for o in recorded.direct(recorded.CELL_EDIT, 'start', 'find_objects')[0]['response']['objects']
           if o.get('type') == 'SpreadsheetDocumentField')
REFUSED_R2C4 = one(PROTECTED, 'cell_R2C4', 'set_area_text')     # «проба» → stage: begin_edit (отказ 11)
EDITED_R2C5 = one(PROTECTED, 'cell_R2C5', 'set_area_text')      # «101» → stage: done, numeric_equivalent
BEGIN_R2C4 = one(PROTECTED, 'cell_R2C4', 'begin_edit_current_area')
PROTECTION = ('protected', 'ЗащитаДокумента', 'Защита = Истина', 'not focus or a stale ref')


class Cells:
    """Поле табличного документа записи 01 на заглушке: адрес текущей области — из кадра SET_CURRENT_AREA,
    текст области — записанный (value_before/value_after ответов set_area_text); begin_edit защищённой R2C4
    (Защита = Истина кодом в записи) клиент отвергает статусом 11, свободной R2C5 — принимает."""

    def __init__(self):
        self.doc, self.platform_version = dict(DOC), PLATFORM
        self.text = {'R2C4': REFUSED_R2C4['response']['value_before'], 'R2C5': EDITED_R2C5['response']['value_before']}
        self.after = {EDITED_R2C5['arguments']['text']: EDITED_R2C5['response']['value_after']}
        self.area, self.frames, self.typed, self.refusal = None, [], [], 11

    def kind(self, c, key):
        return self.doc['type'] if key == self.doc['key'] else None

    def live(self, c, key):
        return dict(self.doc) if key == self.doc['key'] else None

    def flag(self, c, guid, key, handle):
        return False                          # current_mode_is_edit записи — false

    def observe(self, c, key, handle, prepared=None):
        return {'kind': 'area_text', 'area': prepared['area'] if prepared else self.area}, self.text[self.area]

    def input_text(self, key, text, handle):
        self.typed.append(text)
        self.text[self.area] = self.after.get(text, text)
        return {'ok': True, 'target': key, 'text': text}

    def send_cmd(self, guid, key, kind='read', middle=b'', handle=None, **kw):
        self.frames.append((guid, key, kind))
        if guid == G.SET_CURRENT_AREA:
            self.area = re.search(rb'R\d+C\d+', middle)[0].decode()
        if guid == G.BEGIN_EDIT_CURRENT_AREA and self.area == 'R2C4':
            raise tc1c.OperationError(self.refusal, key)
        return {'ok': True}


@contextmanager
def runtime(cells):
    """Обработчики правки ячейки на заглушке: чтения, идущие в клиент, отвечают записью."""
    window = {'ok': True, 'key': 'SecondaryFrame[s]', 'class': 'SecondaryFrame', 'title': SPIKE_TITLE, 'addressable': True}
    with ExitStack() as stack:
        for target in (
                patch.object(R, '_need', return_value=cells),
                patch.object(R, '_window', lambda c: dict(window)),
                patch.object(R, '_ref_live_object', cells.live),
                patch.object(R, '_kind_of', cells.kind),
                patch.object(R, '_cell_flag', cells.flag),
                patch.object(R, '_cell_ready', lambda c, key, handle: None),
                patch.object(R, '_observe_area', cells.observe),
                patch.object(R, '_vals', lambda r, min_len=1: [cells.area]),
                patch.object(R, 'tc_input_text', cells.input_text)):
            stack.enter_context(target)
        yield


def edit(address, text):
    return dict(key=DOC['key'], address=address, text=text, handle=DOC['handle'])


def compact(result, call):
    """Ответ обработчика с полным адресом цели — как в записи id-режима: target = компактная ссылка."""
    return dict(result, target=call['response']['target'])


def test_set_area_text_of_protected_cell_names_the_protection():
    """Сценарий «Защищённая ячейка» (запись 01, cell_R2C4): 1С отказывает в начале правки статусом 11 —
    set_area_text отвечает ok: false, stage: begin_edit с записанными value_before/changed/verified и message
    о защите ячейки — тот же текст, что begin_edit_current_area; ввода и отмены правки не было."""
    cells = Cells()
    with runtime(cells):
        result = action('set_area_text', **edit('R2C4', REFUSED_R2C4['arguments']['text']))
        began = action('begin_edit_current_area', key=DOC['key'], handle=DOC['handle'])
    # Текст ошибки статуса 11 у нынешнего кода другой (справочник tc1c.OperationError), остальное — как в записи
    assert {k: v for k, v in compact(result, REFUSED_R2C4).items() if k != 'message'} == dict(answer(REFUSED_R2C4), error=result['error'])
    assert all(part in result['message'] for part in PROTECTION), result['message']
    assert result['message'] == began['message']
    assert cells.typed == [] and frames(cells, G.END_EDIT_CURRENT_AREA) == []


def test_begin_edit_of_protected_cell_names_the_protection():
    """Запись 01, cell_R2C4: begin_edit_current_area по защищённой ячейке (текущая область — R2C4 с попытки
    set_area_text записи) — записанный отказ (invalid_element_state, статус 11) и message о защите ячейки."""
    cells = Cells()
    cells.area = 'R2C4'
    with runtime(cells):
        began = action('begin_edit_current_area', key=DOC['key'], handle=DOC['handle'])
    assert compact(began, BEGIN_R2C4) == dict(answer(BEGIN_R2C4), message=began['message'], error=began['error'])
    assert began['code'] == 'invalid_element_state' and began['status_code'] == 11
    assert all(part in began['message'] for part in PROTECTION), began['message']


def test_set_area_text_of_free_cell_passes_without_protection_message():
    """Сценарий «Свободная ячейка» (запись 01, cell_R2C5): правка проходит — stage: done, числовой эквивалент
    «101,00», ответ совпадает с записанным (message записи — о числовом представлении, не о защите)."""
    cells = Cells()
    with runtime(cells):
        result = action('set_area_text', **edit('R2C5', EDITED_R2C5['arguments']['text']))
    assert compact(result, EDITED_R2C5) == answer(EDITED_R2C5)
    assert cells.typed == [EDITED_R2C5['arguments']['text']]
    assert frames(cells, G.END_EDIT_CURRENT_AREA) == [(DOC['key'], 'action'), (DOC['key'], 'commit')]


@pytest.mark.parametrize('status', [9, 17], ids=['target_not_interactive', 'unsupported_receiver'])
def test_other_refusals_of_begin_edit_do_not_name_the_protection(status):
    """«Прочие отказы MUST NOT получать это сообщение»: отказ begin_edit иным статусом — begin_edit_current_area
    поднимает ошибку клиента (ответ обёртки — без message), set_area_text отвечает stage: begin_edit без message."""
    cells = Cells()
    cells.refusal, cells.area = status, 'R2C4'
    with runtime(cells):
        with pytest.raises(tc1c.OperationError) as error:
            action('begin_edit_current_area', key=DOC['key'], handle=DOC['handle'])
        assert error.value.status == status
        result = action('set_area_text', **edit('R2C4', REFUSED_R2C4['arguments']['text']))
    # Текст ошибки статуса 17 у нынешнего кода другой (справочник ERRORS), остальное — как в записи
    assert compact(result, REFUSED_R2C4) == dict(answer(REFUSED_R2C4), error=result['error'])
    assert result['error'] and 'protected' not in result['error']


# ---- current_opened (form-groups, запись 03) ---------------------------------------------------

GROUP = dict(one(OPENED, 'state_initial', 'find_object')['response']['object'],      # ГруппаСвертываемая (Group, UsualGroup)
             key='Group[ГруппаСвертываемая]', handle='group')     # прямой вызов: адрес и handle уходят в клиента как есть
GROUP_STATES = ['state_initial', 'state_after_collapse', 'state_after_expand', 'state_after_helper_hide',
                'state_after_helper_show']


def hidden_by_code(step):
    """Скрыта() группы кодом (execute_code записи 03 в шаге состояния)."""
    rows = [c for c in OPENED if c['step'] == step and c['action'] == 'execute_code'
            and isinstance(c['response'].get('result'), dict) and 'Скрыта' in c['response']['result']['Данные']]
    assert len(rows) == 1, step
    return rows[0]['response']['result']['Данные']['Скрыта']


def old_opened(step):
    """Ответ прежнего кода (инвертирован) — current_opened записи 03 в шаге состояния."""
    return one(OPENED, step, 'current_opened')['response']['opened']


def opened_frame(value):
    """Кадр ответа CurrentOpened с булевым маркером перед эпилогом (e2 — Да, e1 — Нет)."""
    return b'\x42' + (b'\xe2' if value else b'\xe1') + b'\x20\xa1\xa3' + tc1c.TR


class GroupClient:
    def __init__(self, reply):
        self.reply, self.frames = reply, []

    def send_cmd(self, guid, key, **kw):
        self.frames.append((guid, key, kw.get('kind')))
        return dict(self.reply)


def current_opened(client):
    with patch.object(R, '_need', return_value=client):
        return inspect.unwrap(R.tc_current_opened)(key=GROUP['key'], handle=GROUP['handle'])


@pytest.mark.parametrize('step', GROUP_STATES, ids=GROUP_STATES)
def test_current_opened_answers_the_platform_without_inversion(step):
    """Сценарии «Развёрнутая группа» и «Свёрнутая группа» (запись 03, пять состояний: исходное, после collapse,
    expand, Скрыть() и Показать() кодом): платформа отвечает «раскрыта» = не Скрыта(); прежний код инвертировал
    ответ (запись) — новый возвращает его как есть: opened = not Скрыта(). Состояния формы — скриншоты записи:
    docs/spikes/testpilot-ui-feedback/recording/03-state_initial.png (группа раскрыта: поля «Подготовка»,
    «Группа1–3» видны под заголовком) и docs/spikes/testpilot-ui-feedback/recording/03-state_after_collapse.png
    (та же форма после collapse: заголовок «▸ Свертываемая группа», полей группы нет, таблица поднялась)."""
    hidden = hidden_by_code(step)
    client = GroupClient({'ok': True, 'raw': opened_frame(not hidden)})
    result = current_opened(client)
    assert result == {'ok': True, 'opened': not hidden}
    assert result['opened'] != old_opened(step)                    # запись 03: прежний код отвечал наоборот
    assert client.frames == [(G.CURRENT_OPENED, GROUP['key'], 'read')]


def test_unreadable_current_opened_is_null():
    """Нечитаемый ответ (отказ клиента, кадр без значения) — opened: null, не false."""
    for reply in ({'ok': False, 'raw': b''}, {'ok': True, 'raw': b'\x42garbage'}):
        assert current_opened(GroupClient(reply)) == {'ok': reply['ok'], 'opened': None}


# ---- окна по заголовку (window-activation, запись 04) --------------------------------------------

def addresses(children_rows):
    """Полные адреса окон и форм записи: {компактная ссылка: адрес} — окно <класс>[<GUID>], форма — его
    ManagedForm[<GUID>] (get_child_objects scope=application и scope=window записи)."""
    out = {}
    for row in children_rows:
        response = row['response']
        if response.get('parent') is None:
            for w in response['children']:
                out[w['key']] = '%s[%s]' % (w['class'], w['name'])
    for row in children_rows:
        response = row['response']
        if response.get('parent') is not None:
            for o in response['children']:
                out[o['key']] = '%s.%s[%s]' % (out[response['parent']], o['class'], o['name'])
    return out


ADDRESS = addresses([c for c in WINDOWS if c['step'] == 'state_two_forms' and c['action'] == 'get_child_objects'])
FORMS = one(WINDOWS, 'two_forms_forms', 'find_objects')['response']['objects']   # 7 ManagedForm, новые первыми
assert [f['title'] for f in FORMS[:2]] == [SPIKE_TITLE] * 2 and FORMS[0]['key'] == 'e4b5202213268-245'
FORM_OBJECTS = [dict(f, key=ADDRESS[f['key']], handle=None) for f in FORMS]
SECOND_FORM, FIRST_FORM = ADDRESS['e4b5202213268-245'], ADDRESS['e4b5202213268-22c']
FIRST_WINDOW = dict(window_of(one(WINDOWS, 'state_two_forms', 'get_active_window')), key=ADDRESS['e4b5202213268-22b'])
SECOND_WINDOW = dict(window_of(one(WINDOWS, 'activate_second_form', 'get_active_window')), key=ADDRESS['e4b5202213268-244'])
FORM_WINDOW = {SECOND_FORM: SECOND_WINDOW['key'], FIRST_FORM: FIRST_WINDOW['key']}
PRESENT = b'\x42\x81\x00\x00\x00\x20\xa1\xa3' + tc1c.TR     # CurrentVisible: цель есть (0x81 за 4 байта до эпилога)


def seed(client, addresses):
    """Реестр ссылок клиента — как в сеансе записи: {компактная ссылка: полный адрес}; remember() уже
    известного адреса вернёт записанную ссылку, счётчик продолжает пространство имён записи."""
    registry = client._object_handles
    registry._namespace = next(iter(addresses))[1:13]
    for ref, address in addresses.items():
        registry._entries[address] = (ref, None)
        registry._keys[ref] = address
    registry._counter = max([int(ref.rsplit('-', 1)[1], 16) for ref in addresses] + [0])


class Client:
    """Клиент 1С записи 02–04: активное окно переключает активизация его формы (activate(ref=<ManagedForm>)
    записи 04), goto_next_window с вкладки клиент отвергает статусом 17; реестр ссылок — как у соединения
    в id-режиме."""

    platform_version = PLATFORM

    def __init__(self, windows, active, addresses=None):
        self.windows, self.active, self.frames = windows, active, []
        self.dead = {}                       # адреса закрытых форм: клиент отвечает статусом 7
        self._object_handles = _refs.Registry()
        self._object_handles._namespace = '4b5202213268'
        seed(self, ADDRESS if addresses is None else addresses)

    def window(self):
        return dict(self.windows[self.active])

    def send_cmd(self, guid, key, kind='read', middle=b'', handle=None, **kw):
        self.frames.append((guid, key, kind))
        if key in self.dead:
            raise tc1c.OperationError(self.dead[key], key)
        if guid == G.ACTIVATE and kind == 'commit' and key in FORM_WINDOW:
            self.active = FORM_WINDOW[key]
        if guid == G.GOTO_NEXT_WINDOW:
            raise tc1c.OperationError(17, key)         # запись 04: с вкладки — unsupported_receiver
        return {'ok': True, 'raw': PRESENT if guid == G.CURRENT_VISIBLE else b''}


def connect(client, cid=SESSION_0204):
    """Соединение пула с клиентом: зарегистрировано, не starting, connection_id записи."""
    connection = _connections.Connection('127.0.0.1', 30000)
    connection.id = cid
    connection.state['connection_id'] = cid
    connection.starting = False
    connection.state['client'] = client
    S._pool.entries[cid] = connection
    return connection


def reads(monkeypatch, client, objects):
    """Чтения runtime отвечают записанным: активное окно — окно заглушки, поиск — объекты записи."""
    monkeypatch.setattr(S, '_window', lambda c: client.window())
    monkeypatch.setattr(S, '_search_objects', lambda c, root=None: [dict(o) for o in objects])


@pytest.fixture
def mcp(monkeypatch):
    """Публикация инструментов теста: publish() ставит свежий TestpilotMCP и регистрирует search/execute на
    текущих обработчиках _ACTIONS; после теста S.mcp прежний."""
    def publish():
        monkeypatch.setattr(S, 'mcp', _mcp.TestpilotMCP(S))
        S._register_groups()
        return S.mcp
    return publish


@pytest.fixture
def pool():
    """Пул с одним клиентом записи 04 (активна первая форма); после теста пула пуст."""
    client = Client({FIRST_WINDOW['key']: FIRST_WINDOW, SECOND_WINDOW['key']: SECOND_WINDOW}, FIRST_WINDOW['key'])
    connect(client)
    yield client
    S._pool.entries.clear()


def as_recorded(value):
    """Ответ execute к виду записи: ссылки реестра заглушки — уже записанные (seed), а названы ref — в записи
    прежнего кода key (окно get_active_window, объекты find_objects)."""
    if isinstance(value, dict):
        return {('key' if k == 'ref' else k): as_recorded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [as_recorded(v) for v in value]
    return value


async def execute(calls, client):
    """execute через S.mcp.call_tool: ответ toon, декодированный и приведённый к ссылкам записи."""
    result = await S.mcp.call_tool('execute', {'calls': calls})
    assert [c.type for c in result] == ['text']
    return as_recorded(toon_format.decode(result[0].text))


async def test_activate_window_by_title_switches_to_the_last_opened_form(mcp, pool, monkeypatch):
    """Сценарий «Две вкладки» (запись 04): открыты две формы с одним заголовком, активна первая; поиск форм
    отдаёт новую первой. activate_window(title) активизирует форму последней открытой — get_active_window
    возвращает окно второй формы (запись activate_second_form); в ответе matches: 2."""
    mcp()
    reads(monkeypatch, pool, FORM_OBJECTS)
    out = await execute([{'action': 'activate_window', 'args': {'title': SPIKE_TITLE}}], pool)
    assert out['ok'] is True and len(out['steps']) == 1
    assert {k: out['steps'][0][k] for k in ('ok', 'target', 'action', 'matches')} == {
        'ok': True, 'target': 'e4b5202213268-245', 'action': 'activate', 'matches': 2}
    assert frames(pool, G.ACTIVATE) == [(SECOND_FORM, 'action'), (SECOND_FORM, 'commit')]
    out = await execute([{'action': 'get_active_window', 'args': {}}], pool)
    assert out == {'ok': True, 'steps': [answer(one(WINDOWS, 'activate_second_form', 'get_active_window'))]}


@pytest.mark.parametrize('title', ['Спайк АРМ КС: *', 'Спайк ?РМ КС: сетка'], ids=['star', 'question'])
async def test_activate_window_title_accepts_wildcards(mcp, pool, monkeypatch, title):
    """Заголовок — точно или с * и ?: обе формы подходят, активизируется последняя открытая (запись 04)."""
    mcp()
    reads(monkeypatch, pool, FORM_OBJECTS)
    out = await execute([{'action': 'activate_window', 'args': {'title': title}}], pool)
    assert out['steps'][0]['target'] == 'e4b5202213268-245' and out['steps'][0]['matches'] == 2
    assert pool.active == SECOND_WINDOW['key']


async def test_unique_title_activates_that_form_without_matches(mcp, pool, monkeypatch):
    """Заголовок одной формы (запись 04: «Журнал документов» на начальной странице) — активизируется она,
    поля matches нет."""
    mcp()
    reads(monkeypatch, pool, FORM_OBJECTS)
    out = await execute([{'action': 'activate_window', 'args': {'title': 'Журнал документов'}}], pool)
    assert 'matches' not in out['steps'][0] and out['steps'][0]['ok'] is True
    journal = ADDRESS['e4b5202213268-1c']
    assert frames(pool, G.ACTIVATE) == [(journal, 'action'), (journal, 'commit')]


async def test_activate_window_without_such_title_lists_open_titles(mcp, pool, monkeypatch):
    """Сценарий «Нет такой формы»: ok: false, code: window_not_found, titles — заголовки всех открытых форм
    записи (7 форм two_forms_forms); окно не менялось — кадров активизации нет, get_active_window прежний."""
    mcp()
    reads(monkeypatch, pool, FORM_OBJECTS)
    out = await execute([{'action': 'activate_window', 'args': {'title': 'Нет такой'}}], pool)
    assert out == {'ok': False, 'stopped_at': 0, 'steps': [{
        'ok': False, 'code': 'window_not_found', 'error': 'No open form has this title.',
        'titles': [f['title'] for f in FORMS], 'connection_id': SESSION_0204}]}
    assert out['steps'][0]['titles'] == ['Спайк АРМ КС: сетка'] * 2 + [
        'Журнал документов', 'Текущая организация', 'Электронный документооборот', 'Информация и поддержка', 'Поиск']
    assert frames(pool, G.ACTIVATE) == []
    out = await execute([{'action': 'get_active_window', 'args': {}}], pool)
    assert out == {'ok': True, 'steps': [answer(one(WINDOWS, 'state_two_forms', 'get_active_window'))]}


async def test_activate_window_without_title_is_former_behaviour(mcp, pool, monkeypatch):
    """Без title — прежнее поведение (запись 04, activate_window_no_args): повторная активизация активного
    окна кадрами ACTIVATE, в ответе его ссылка."""
    mcp()
    reads(monkeypatch, pool, FORM_OBJECTS)
    out = await execute([{'action': 'activate_window', 'args': {}}], pool)
    assert out == {'ok': True, 'steps': [answer(one(WINDOWS, 'activate_window_no_args', 'activate_window'))]}
    assert frames(pool, G.ACTIVATE) == [(FIRST_WINDOW['key'], 'action'), (FIRST_WINDOW['key'], 'commit')]


async def test_goto_next_window_from_a_tab_is_refused(mcp, pool, monkeypatch):
    """Запись 04, goto_next_window (после activate_second_form): со второй вкладки (SecondaryFrame) клиент
    отвергает переход статусом 17 — unsupported_receiver, окно то же; потому вкладки переключают активизацией
    формы по заголовку."""
    mcp()
    reads(monkeypatch, pool, FORM_OBJECTS)
    await execute([{'action': 'activate_window', 'args': {'title': SPIKE_TITLE}}], pool)
    out = await execute([{'action': 'goto_next_window', 'args': {}}], pool)
    assert out == {'ok': False, 'stopped_at': 0, 'steps': [one(WINDOWS, 'goto_next_window', 'goto_next_window')['response']]}
    assert pool.active == SECOND_WINDOW['key']


async def test_activate_window_refuses_ref_parameter(mcp, pool):
    """Запись 04, activate_window_with_ref: параметр ref (как у действий с адресом) — invalid_arguments
    с именем лишнего параметра до выбора соединения; ничего не отправлено."""
    mcp()
    out = await execute([{'action': 'activate_window', 'args': {'ref': 'e4b5202213268-22c'}}], pool)
    step = out['steps'][0]
    assert out['ok'] is False and step['code'] == 'invalid_arguments' and step['unexpected_parameters'] == ['ref']
    assert {k: v for k, v in step.items() if k != 'signature'} == {
        k: v for k, v in answer(one(WINDOWS, 'activate_window_with_ref', 'activate_window')).items() if k != 'signature'}
    assert step['signature'].startswith('activate_window(title')          # запись: signature была activate_window()
    assert pool.frames == []


# ---- ref после переоткрытия формы (запись 02 — id; 02b — off) --------------------------------------------

# Адреса кнопки «Итог данных» до и после переоткрытия формы — из записи 02b (полные адреса и handle);
# ссылки e4b5202213268-14 и -23c — та же кнопка в записи 02 (id-режим), окно после переоткрытия — то же
# в обеих записях (GUID fbc4c4fb-e180-4873-a1d3-978023e0f54f).
REOPEN_OLD = ('SecondaryFrame[37677122-2d6a-4489-b21d-720b1fed51bc].ManagedForm[c2fc26d1-98fc-49e8-9af4-82d92677801f]'
              '.Group[ФормаКоманднаяПанель].Button[ФормаИтогДанных]')
REOPEN_NEW = ('SecondaryFrame[b83c6804-1517-49d4-ae60-34de6aef8ae0].ManagedForm[c7764a88-d848-4f39-8ea3-b282c9e2b984]'
              '.Group[ФормаКоманднаяПанель].Button[ФормаИтогДанных]')
REOPEN_HANDLE = '4e5a30e1-b455-471b-b7c8-4b409d934d51'                       # 02b: handle кнопки прежний
REOPEN_REFS = {'e4b5202213268-14': REOPEN_OLD, 'e4b5202213268-23c': REOPEN_NEW}


async def test_click_by_ref_of_closed_form_is_refused_and_refound_button_clicks(mcp, monkeypatch):
    """Запись 02 (id): после закрытия и открытия формы прежняя ссылка кнопки мертва — 1С отвечает статусом 7
    на первое же обращение по её адресу (запись click_old_ref: target_unavailable, нажатия нет, Замеры пуст);
    find_objects отдаёт новую ссылку с тем же именем — клик по ней проходит с записанным ответом (click_new_ref).
    Нынешний код отказывает устаревшую ссылку до действия, при разрешении ref: ref_unavailable."""
    window = dict(one(REOPEN, 'click_new_ref', 'click')['response']['window'], key=ADDRESS['e4b5202213268-22b'])
    client = Client({window['key']: window}, window['key'], dict(ADDRESS, **REOPEN_REFS))
    client.dead[REOPEN_OLD] = 7
    client._object_handles.remember(REOPEN_OLD, REOPEN_HANDLE)
    old_ref = 'e4b5202213268-14'
    found = dict(one(REOPEN, 'find_again', 'find_objects')['response']['objects'][0], key=REOPEN_NEW, handle=REOPEN_HANDLE)
    mcp()
    reads(monkeypatch, client, [found])
    # живость объекта: старого адреса в дереве нет (форма закрыта), новый — кнопка записи
    monkeypatch.setattr(S, '_ref_live_object', lambda c, key: dict(found) if key == REOPEN_NEW else None)
    connect(client)
    try:
        out = await execute([{'action': 'get_active_window', 'args': {}}], client)
        assert out == {'ok': True, 'steps': [answer(one(REOPEN, 'click_old_ref', 'get_active_window'))]}
        out = await execute([{'action': 'click', 'args': {'ref': old_ref, 'expect': 'none'}}], client)
        assert out == {'ok': False, 'stopped_at': 0, 'steps': [{
            'ok': False, 'code': 'ref_unavailable', 'error': 'The element is no longer available. Find the element again.',
            'connection_id': SESSION_0204}]}
        assert frames(client, G.CLICK) == []                              # клика нет
        found_out = await execute([{'action': 'find_objects', 'args': {'name': '*ИтогДанных*', 'scope': 'application'}}], client)
        assert found_out == {'ok': True, 'steps': [answer(one(REOPEN, 'find_again', 'find_objects'))]}
        assert found_out['steps'][0]['objects'][0]['key'] != old_ref
        pressed = await execute([{'action': 'click', 'args': {'ref': found_out['steps'][0]['objects'][0]['key'], 'expect': 'none'}}], client)
        # Клик прошёл: окно после нажатия — то же (запись click_new_ref); форма шага клика expect="none"
        # с описанием окна — test_effects.py
        assert pressed['ok'] is True and len(pressed['steps']) == 1
        assert pressed['steps'][0]['ok'] is True and pressed['steps'][0]['window'] == {'key': 'e4b5202213268-22b', 'title': SPIKE_TITLE}
        assert frames(client, G.CLICK) == [(REOPEN_NEW, 'action'), (REOPEN_NEW, 'commit')]
    finally:
        S._pool.entries.clear()


# ---- кириллица в параметрах execute_code (запись 05) ---------------------------------------------

WORK = dict(window_of(one(OPEN_FORM, 'open_independent', 'get_active_window')),            # рабочая форма записей
            key='SecondaryFrame[6451794a-def8-4586-a3ca-edbbcd3126aa]')


def helper_client():
    """Клиент с обработкой Testpilot (окна Helper и Request — записи протокола, tests/_helper_client.py),
    активна рабочая форма «Спайк АРМ КС: сетка» записей 01, 05 и 06."""
    client = H.Client(H.PROTOCOL, active=WORK['key'])
    for _, window in H.PROTOCOL.windows:
        client.show(window)
    client.show(WORK)
    return client


BOTH = 'Результат = Строка(Параметры["путь"]) + "|" + Строка(Параметры["path"]);'
KEYS = ('Ключи = Новый Массив;\nДля Каждого Кл Из Параметры Цикл\n\tКлючи.Добавить(Кл.Ключ);\nКонецЦикла;\n'
        'Результат = Новый Структура("Тип, Ключи", Строка(ТипЗнч(Параметры)), Ключи);')
ONLY = 'Результат = Строка(Параметры["путь"]);'


def helper(request):
    """Код записи 05 так, как его выполняет Helper: из параметров, дошедших до 1С."""
    parameters, code = request['parameters'], request['code']
    assert code in (BOTH, KEYS, ONLY), code
    if code == BOTH:
        return str(parameters['путь']) + '|' + str(parameters['path'])
    if code == KEYS:
        return {'Тип': 'Соответствие', 'Ключи': list(parameters)}
    return str(parameters['путь'])


@pytest.mark.parametrize('call', [c for c in CYRILLIC if c['action'] == 'execute_code'],
                         ids=lambda c: c['step'])
def test_cyrillic_parameter_names_reach_1c_as_they_are(call):
    """Запись 05: кириллические и латинские ключи parameters execute_code доходят до 1С как есть — в поле
    Request ушёл JSON с теми же ключами (без \\u-экранирования), код клиента и сервера читает Параметры["путь"]
    и отвечает записанным («x|x», Соответствие с ключами)."""
    client = helper_client()
    client.run = helper
    result = H.execute(client, mode='code', context=call['arguments']['context'], code=call['arguments']['code'],
                       parameters=call['arguments']['parameters'])
    assert result == dict(without_ids(call), request_id=result['request_id'])
    sent = H.payload(client.inputs[0])
    assert sent['parameters'] == call['arguments']['parameters'] and sent['context'] == call['arguments']['context']
    assert 'путь' in client.inputs[0]                                   # кириллица в JSON — как есть


# ---- ОткрытьФорму из кода при другой вкладке (запись 06) -------------------------------------------

OPEN_CODE = one(OPEN_FORM, 'open_independent', 'execute_code', 2)['arguments']       # unique=true, independent
OPEN_RESULT = one(OPEN_FORM, 'open_independent', 'execute_code', 2)          # ОткрытьФорму: код, параметры, ответ
OPENED_WINDOWS = one(OPEN_FORM, 'open_independent', 'get_child_objects')['response']['children']
OPENED_FORMS = one(OPEN_FORM, 'after_open_independent_forms', 'find_objects')['response']['objects']
SPIKE_WINDOWS = [w for w in OPENED_WINDOWS if w['title'] == SPIKE_TITLE]           # новые первыми: 244, 22b, 1
SPIKE_FORMS = [f for f in OPENED_FORMS if f['title'] == SPIKE_TITLE][:len(SPIKE_WINDOWS)]   # 245, 22c, 4
# Каждая форма — SecondaryFrame + ManagedForm (запись 04, get_child_objects scope=window); в записи 06 формы
# и окна перечислены в одном порядке — новые первыми.
HOME = next(w for w in OPENED_WINDOWS if w['class'] == 'HomePage')['name']       # начальная страница БГУ
OPEN_ADDRESS = {f['key']: '%s[%s].ManagedForm[%s]' % (w['class'], w['name'], f['name'])
                for f, w in zip(SPIKE_FORMS, SPIKE_WINDOWS)}
OPEN_ADDRESS.update({w['key']: '%s[%s]' % (w['class'], w['name']) for w in SPIKE_WINDOWS})
for f in OPENED_FORMS[len(SPIKE_FORMS):]:          # формы БГУ — адрес для реестра, в тесте не читаются
    OPEN_ADDRESS[f['key']] = 'HomePage[%s].ManagedForm[%s]' % (HOME, f['name'])
OPEN_FORM_OBJECTS = [dict(f, key=OPEN_ADDRESS[f['key']], handle=None) for f in OPENED_FORMS]
assert OPEN_ADDRESS['ed62d72777fd8-1'] == WORK['key']                      # форма, активная до ОткрытьФорму, — рабочая


async def test_open_form_from_code_keeps_former_tab_and_activate_window_switches(mcp, monkeypatch):
    """Запись 06 (open_independent): ОткрытьФорму из кода при другой активной вкладке — внутри кода новое окно
    активно (ФормаВАктивномОкне: true), сразу после get_active_window — прежняя вкладка; find_objects отдаёт
    новую форму первой, activate_window(title) переключает на неё (activate_independent_form)."""
    before = dict(WORK)
    after = dict(window_of(one(OPEN_FORM, 'activate_independent_form', 'get_active_window')),
                 key=OPEN_ADDRESS['ed62d72777fd8-244'])
    client = helper_client()
    client.platform_version = PLATFORM
    client._object_handles = _refs.Registry()
    seed(client, OPEN_ADDRESS)
    client.show(after)
    # Код ОткрытьФорму на заглушке только отвечает записанным (внутри кода активно новое окно — факт ответа
    # записи, ФормаВАктивномОкне: true); после закрытия Request платформа возвращает активность владельцу.
    client.run = lambda request: OPEN_RESULT['response']['result']
    result = H.execute(client, mode='code', context=OPEN_CODE['context'], code=OPEN_CODE['code'],
                       parameters=OPEN_CODE['parameters'])
    assert result == dict(without_ids(OPEN_RESULT), request_id=result['request_id'])
    assert client.owner == before['key'] and client.active == before['key']   # прежняя вкладка, не новая форма
    mcp()
    reads(monkeypatch, client, OPEN_FORM_OBJECTS)
    connect(client, SESSION_06)
    try:
        out = await execute([{'action': 'get_active_window', 'args': {}}], client)
        assert out == {'ok': True, 'steps': [answer(one(OPEN_FORM, 'open_independent', 'get_active_window'))]}
        out = await execute([{'action': 'find_objects', 'args': {'cls': 'ManagedForm', 'title': SPIKE_TITLE,
                                                                 'scope': 'application', 'timeout': 10}}], client)
        assert out['steps'][0]['objects'] == answer(one(OPEN_FORM, 'after_open_independent_forms', 'find_objects'))['objects'][:3]
        out = await execute([{'action': 'activate_window', 'args': {'title': SPIKE_TITLE}}], client)
        assert out['steps'][0]['matches'] == len(SPIKE_FORMS) and out['steps'][0]['target'] == SPIKE_FORMS[0]['key']
        out = await execute([{'action': 'get_active_window', 'args': {}}], client)
        assert out == {'ok': True, 'steps': [answer(one(OPEN_FORM, 'activate_independent_form', 'get_active_window'))]}
    finally:
        S._pool.entries.clear()


# ---- сеанс (запись 00) -------------------------------------------------------------------------------

START = recorded.ui_rows(recorded.UI_SESSION, 'start')[0]
FAILED = [c for c in SESSION if c['action'] == 'execute_code']          # СистемнаяИнформация не определена — клиент и сервер


class FailingHelper(H.Client):
    """Helper записи 00: код с ошибкой компиляции — ответ execution_failed с текстом 1С."""

    error = None

    def pressed(self, name):
        if name in ('RunClient', 'RunServer'):
            request = self.text
            field = 'ClientResult' if name == 'RunClient' else 'ServerResult'
            self.results[field] = json.dumps({'protocol': E.PROTOCOL, 'request_id': request['request_id'],
                                              'ok': False, 'code': 'execution_failed', 'error': self.error})
            self.opened.pop(self.facts.request_window, None)
            if self._active == self.facts.request_window:
                self.active = self.owner
            return
        super().pressed(name)


@pytest.mark.parametrize('call', FAILED, ids=lambda c: c['arguments']['context'])
def test_compile_error_of_execute_code_is_execution_failed_with_1c_text(call):
    """Запись 00, platform: СистемнаяИнформация не определена — execute_code отвечает ok: false,
    execution_failed с текстом ошибки 1С (номер строки Helper) в обоих контекстах."""
    client = FailingHelper(H.PROTOCOL, active=WORK['key'])
    for _, window in H.PROTOCOL.windows:
        client.show(window)
    client.show(WORK)
    client.error = call['response']['error']
    result = H.execute(client, mode='code', context=call['arguments']['context'], code=call['arguments']['code'])
    assert result == dict(without_ids(call), request_id=result['request_id'])


def catalog_names(catalog):
    """Имена действий из каталога search(''): строки-продолжение «  a, b, c» под строками групп."""
    return {name.strip() for line in catalog.splitlines() if line.startswith('  ')
            for name in line.strip().split(', ')}


async def test_actions_of_the_recorded_session_are_in_the_catalog(mcp, monkeypatch):
    """Запись 00, start: сеанс прежнего кода публиковал 14 групп tc_*; теперь инструменты — search и execute,
    и каждое действие записей спайка (правка ячейки, current_opened, окна, execute_code, launch_client,
    list_profiles) есть в каталоге под тем же именем (execute_code — как в сеансе записи, с включённым
    исполнением кода: TC1C_CODE_EXECUTION)."""
    monkeypatch.setattr(E, 'SETTINGS', dataclasses.replace(E.SETTINGS, code=True))
    mcp()
    tools = await S.mcp.list_tools()
    assert START['tools'] and set(START['tools']).isdisjoint({'search', 'execute'})
    assert {'search', 'execute'} <= {t.name for t in tools}
    used = {c['action'] for path in (recorded.UI_PROTECTED, recorded.UI_REOPEN, recorded.UI_OPENED, recorded.UI_WINDOWS,
                                     recorded.UI_CYRILLIC, recorded.UI_OPEN_FORM) for c in recorded.ui(path)}
    used |= {c['action'] for c in SESSION}
    assert used <= catalog_names(await search(''))


async def search(query=''):
    result = await S.mcp.call_tool('search', {'query': query})
    if isinstance(result, tuple):                      # search с output schema: (текст, structured content)
        result = result[0]
    return result[0].text
