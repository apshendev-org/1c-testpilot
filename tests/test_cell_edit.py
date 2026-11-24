"""Правка ячейки табличного документа (изменение spreadsheet-cell-edit, spike:spk_d8a5084a0c@v1).

Записи спайка docs/spikes/testpilot-cell-edit/recording/ (копии — tests/recordings/): строка — вызов
testpilot из спайка и ответ живого клиента 1С.
- docs/spikes/testpilot-cell-edit/recording/01-cell-edit.jsonl — форма «Спайк АРМ КС: сетка», ячейка R2C4
  сделана ссылочной (СправочникСсылка.Подразделения): B защищённая ячейка, C1 begin_edit с флагом правки
  false, C2 текст, которого нет в справочнике, C3 end_edit с отменой, C4 точное представление
  «Администрация», C5 end_edit без отмены, C7 select_value по полю документа;
- docs/spikes/testpilot-cell-edit/recording/03-choice-from-cell.jsonl — макет АРМ: begin_edit по ячейке
  R3C9 открыл форму выбора «Подразделения».

Действия вызываются как обработчики без обёрток MCP (inspect.unwrap, как tests/test_runtime_fixes.py).
Чтения runtime, идущие в клиент по протоколу, отвечают записанными ответами: _window — get_active_window,
_cell_flag — current_mode_is_edit, _observe_area — get_area_text, _kind_of и _ref_live_object — find_objects,
tc_input_text — input_text (C5); адрес текущей области — адрес шагов записи (set_current_area, get_area_text).
Клиент кадры send_cmd только журналирует: по журналу видно, что нажатие при незаконченной правке не ушло,
а отмена после несовпавшего текста — ушла.
"""
import inspect
import os
import sys
from contextlib import ExitStack, contextmanager
from functools import partial
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _recording as recorded  # noqa: E402
import _runtime as R  # noqa: E402
import guids as G  # noqa: E402
import tc1c  # noqa: E402

MISSING = 'ОАИС-нет-такого'       # C2: текста нет в справочнике — ячейка осталась пустой
DEPARTMENT = 'Администрация'      # C4: точное представление существующего элемента — принято
CELL = partial(recorded.direct, recorded.CELL_EDIT)   # вызовы записи 01
CHOICE_STEP = 'M_choice_from_cell'


def call(rows):
    """Единственный записанный вызов."""
    assert len(rows) == 1, len(rows)
    return rows[0]


def answer(rows):
    """Записанный ответ действия без connection_id (добавляет сеанс Python API) и target_check
    (обёртка проверки цели)."""
    return {k: v for k, v in call(rows)['response'].items() if k not in ('connection_id', 'target_check')}


def window(rows, index=0):
    """Активное окно, как его читает runtime (_window): без platform_version и connection_id."""
    reply = rows[index]['response']
    return {k: v for k, v in reply.items() if k not in ('platform_version', 'connection_id')}


class Client:
    """Клиент 1С без протокола: кадры журналирует, отвечает ok; заданные формой события — как в записи."""

    def __init__(self, grid):
        self.grid, self.frames, self.platform_version = grid, [], grid.version

    def send_cmd(self, guid, key, kind='read', middle=b'', handle=None, **kw):
        self.frames.append((guid, key, kind, middle))
        if guid == G.BEGIN_EDIT_CURRENT_AREA and self.grid.refuses_edit:
            raise tc1c.OperationError(11, key)       # B: «not in a state that permits this action»
        if guid == G.BEGIN_EDIT_CURRENT_AREA and self.grid.opens is not None:
            self.grid.window = self.grid.opens       # 03: по ячейке открылась форма выбора
        return {'ok': True}


class Grid:
    """Поле табличного документа из записи: чтения runtime, идущие в клиент, отвечают записью."""

    def __init__(self, path, objects_step, window_step):
        rows = recorded.direct(path, objects_step, 'find_objects')
        objects = call(rows)['response']['objects']
        self.doc = next(o for o in objects if o.get('type') == 'SpreadsheetDocumentField')
        self.button = next((o for o in objects if o.get('name') == 'ФормаИтогДанных'), None)
        windows = recorded.direct(path, window_step, 'get_active_window')
        self.version = windows[0]['response']['platform_version']
        self.window = window(windows)
        self.opens = None           # окно, открывающееся по begin_edit (03)
        self.refuses_edit = False   # клиент отказывает begin_edit (B)
        self.edit_flag = False      # current_mode_is_edit после begin_edit — записанный false
        self.area = 'R2C4'
        self.text = ''              # текст текущей ячейки
        self.after = {MISSING: '', DEPARTMENT: DEPARTMENT}   # записанный текст ячейки после ввода (C2, C4)
        self.typed = []
        self.c = Client(self)

    def kind(self, c, key):
        return self.doc['type'] if key == self.doc['key'] else None

    def live(self, c, key):
        """find_objects по ключу: строка поля документа, иначе объект не найден."""
        return dict(self.doc) if key == self.doc['key'] else None

    def flag(self, c, guid, key, handle):
        return self.edit_flag

    def observe(self, c, key, handle, prepared=None):
        return {'kind': 'area_text', 'area': prepared['area'] if prepared else self.area}, self.text

    def input_text(self, key, text, handle):
        self.typed.append(text)
        self.text = self.after.get(text, self.text)
        return {'ok': True, 'target': key, 'text': text}


CellGrid = partial(Grid, recorded.CELL_EDIT, 'start', 'C1_begin_edit')


@contextmanager
def runtime(grid):
    """Действия runtime на клиенте-заглушке; чтения, идущие в клиент, отвечают записью."""
    c = grid.c
    with ExitStack() as stack:
        for target in (
                patch.object(R, '_need', return_value=c),
                patch.object(R, '_window', lambda c: dict(grid.window)),
                patch.object(R, '_ref_live_object', grid.live),
                patch.object(R, '_kind_of', grid.kind),
                patch.object(R, '_cell_flag', grid.flag),
                patch.object(R, '_cell_ready', lambda c, key, handle: None),
                patch.object(R, '_observe_area', grid.observe),
                patch.object(R, '_vals', lambda r, min_len=1: [grid.area]),
                patch.object(R, 'tc_input_text', grid.input_text)):
            stack.enter_context(target)
        yield


def action(name, **arguments):
    """Обработчик действия без обёрток MCP (проверка адреса и цели, диагностика)."""
    return inspect.unwrap(getattr(R, 'tc_' + name))(**arguments)


def frames(grid, guid):
    """Кадры метода, ушедшие в клиент: [(kind, middle)]."""
    return [(kind, middle) for g, _, kind, middle in grid.c.frames if g == guid]


def begin_edit(grid):
    return action('begin_edit_current_area', key=grid.doc['key'], handle=grid.doc['handle'])


def end_edit(grid, cancel=False):
    return action('end_edit_current_area', key=grid.doc['key'], handle=grid.doc['handle'], cancel=cancel)


def click(grid):
    return action('click', key=grid.button['key'], handle=grid.button['handle'], expect='none')


def set_area_text(grid, text):
    return action('set_area_text', key=grid.doc['key'], address='R2C4', text=text, handle=grid.doc['handle'])


@pytest.mark.parametrize('cancel', [True, False], ids=['cancel', 'commit'])
def test_edit_with_false_flag_is_unfinished_until_end_edit(cancel):
    """C1 → C3/C5: begin_edit принят без смены окна, флаг правки false — правка числится незаконченной
    (нажатие отказывает) до end_edit_current_area; после неё нажатие уходит в клиент."""
    grid = CellGrid()
    with runtime(grid):
        began = begin_edit(grid)
        recorded_began = answer(CELL('C1_begin_edit', 'begin_edit_current_area'))
        assert {k: began[k] for k in ('ok', 'target', 'window_changed', 'edit_mode')} == \
            {k: recorded_began[k] for k in ('ok', 'target', 'window_changed', 'edit_mode')}
        assert began['suggested_action'] == 'end_edit_current_area'      # запись: execute_choice_from_menu
        assert 'not confirmed' in began['message'] and 'end_edit_current_area' in began['message']
        grid.c.frames.clear()
        assert click(grid)['code'] == 'other_input_pending'
        assert grid.c.frames == []
        ended = end_edit(grid, cancel)
        assert ended == {'ok': True, 'target': grid.doc['key'], 'cancelled': cancel}   # записанные C3/C5
        assert frames(grid, G.END_EDIT_CURRENT_AREA) == [
            ('action', R.CANCEL_EDIT_MID if cancel else R.RS), ('commit', R.CANCEL_EDIT_MID if cancel else R.RS)]
        grid.c.frames.clear()
        assert click(grid)['ok'] is True
        assert frames(grid, G.CLICK) == [('action', b''), ('commit', b'')]


def test_click_during_unfinished_cell_edit_is_refused_before_sending():
    """Нажатие «Итог данных» при незаконченной правке ячейки: отказ other_input_pending с адресом поля
    и подсказкой end_edit_current_area, в клиент ничего не ушло (в записи нажатие поглотил открытый
    редактор ячейки)."""
    grid = CellGrid()
    with runtime(grid):
        begin_edit(grid)
        sent = list(grid.c.frames)
        refused = click(grid)
        assert refused == {
            'ok': False, 'code': 'other_input_pending', 'target': grid.doc['key'],
            'suggested_action': 'end_edit_current_area',
            'error': 'A spreadsheet cell edit is unfinished; it would take this action.'}
        assert grid.c.frames == sent


def test_refused_begin_edit_leaves_no_unfinished_edit():
    """B: защищённая ячейка — begin_edit отвергнут клиентом, правки нет: set_area_text отвечает как
    в записи, плюс message о защите ячейки (требование spreadsheet-edit «Отказ правки защищённой ячейки
    называет защиту»: ЗащитаДокумента и Защита области, не фокус и не устаревшая ссылка, Защита проверяется
    кодом), следующий click уходит в клиент."""
    grid = CellGrid()
    grid.refuses_edit = True
    grid.text = 'Бухгалтерия'        # записанный value_before
    with runtime(grid):
        refused = set_area_text(grid, 'ОАИС')
        message = refused.pop('message')
        assert refused == answer(CELL('B_protected_text', 'set_area_text'))
        assert all(part in message for part in ('protected', 'ЗащитаДокумента', 'Защита', 'not focus or a stale ref',
                                                'execute_code')), message
        assert frames(grid, G.END_EDIT_CURRENT_AREA) == []
        grid.c.frames.clear()
        assert click(grid)['ok'] is True
        assert frames(grid, G.CLICK) == [('action', b''), ('commit', b'')]


def test_begin_edit_opening_choice_window_is_not_an_unfinished_edit():
    """03: begin_edit по ячейке макета АРМ открыл форму выбора «Подразделения» (окно сменилось) —
    правка ячейки не числится незаконченной: click по полю документа уходит в клиент."""
    choice = recorded.direct(recorded.CHOICE_FROM_CELL, CHOICE_STEP, 'get_active_window')
    grid = Grid(recorded.CHOICE_FROM_CELL, 'M_open', 'M_open')
    grid.opens = window(choice)
    with runtime(grid):
        began = begin_edit(grid)
        assert began == answer(recorded.direct(recorded.CHOICE_FROM_CELL, CHOICE_STEP, 'begin_edit_current_area'))
        grid.c.frames.clear()
        clicked = action('click', key=grid.doc['key'], handle=grid.doc['handle'], expect='none')
        assert clicked['ok'] is True
        assert frames(grid, G.CLICK_FIELD) == [('action', b''), ('commit', b'')]


def test_set_area_text_with_text_missing_from_catalog_cancels_edit():
    """C2: ссылочная ячейка не приняла текст — правка отменена (end_edit с отменой ушёл в клиент),
    ok: false, edit_cancelled: true, подсказка о точном представлении; следующий click не отказывает
    из-за правки."""
    grid = CellGrid()
    with runtime(grid):
        result = set_area_text(grid, MISSING)
        recorded_reply = answer(CELL('C2_set_area_text_missing', 'set_area_text'))
        assert {k: v for k, v in result.items() if k != 'message'} == dict(recorded_reply, edit_cancelled=True)
        assert 'exact presentation of an existing item' in result['message']
        assert frames(grid, G.END_EDIT_CURRENT_AREA) == [
            ('action', R.RS), ('commit', R.RS), ('action', R.CANCEL_EDIT_MID), ('commit', R.CANCEL_EDIT_MID)]
        grid.c.frames.clear()
        assert click(grid)['ok'] is True
        assert frames(grid, G.CLICK) == [('action', b''), ('commit', b'')]


def test_select_value_types_the_presentation_into_the_cell():
    """C7 → C4: select_value по полю документа ставит value в текущую ячейку как set_area_text —
    ответ записи C4 (ok: true, verified: true, в ячейке «Администрация»; в записи C7 — unsupported_
    element_type); выбора из списка не было — только кадры правки ячейки."""
    grid = CellGrid()
    with runtime(grid):
        result = action('select_value', key=grid.doc['key'], handle=grid.doc['handle'], value=DEPARTMENT)
        assert result == answer(CELL('C4_set_area_text_existing', 'set_area_text'))
        assert grid.typed == [DEPARTMENT]
        assert {g for g, _, _, _ in grid.c.frames} == {G.GET_CURRENT_AREA_ADDRESS, G.SET_CURRENT_AREA,
                                                        G.BEGIN_EDIT_CURRENT_AREA, G.END_EDIT_CURRENT_AREA}


@pytest.mark.parametrize('other', [
    dict(match={'Наименование': DEPARTMENT}), dict(choice_table='Список'), dict(choice_column='Наименование'),
    dict(data_type='СправочникСсылка.Подразделения'), dict(expected=DEPARTMENT), dict(value=None)],
    ids=['match', 'choice_table', 'choice_column', 'data_type', 'expected', 'no value'])
def test_select_value_on_cell_refuses_other_parameters_before_the_client(other):
    """Для ячейки select_value принимает только value: прочие параметры — invalid_argument, в клиент
    ничего не ушло."""
    grid = CellGrid()
    arguments = dict(value=DEPARTMENT) | other
    with runtime(grid):
        refused = action('select_value', key=grid.doc['key'], handle=grid.doc['handle'], **arguments)
        assert refused['ok'] is False and refused['code'] == 'invalid_argument'
        assert grid.c.frames == []
