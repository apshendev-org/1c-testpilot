import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _runtime as R  # noqa: E402
import _typed_input as T  # noqa: E402
import _value_selection as V  # noqa: E402
import _field_batches as B  # noqa: E402

SERVICE = dict(separators={'Fractions': ',', 'Groups': '\xa0'}, date_sample='22.11.2004 17:48:59')
DATE = {'$type': 'date', 'value': '2026-01-15T00:00:00'}


@pytest.mark.parametrize('kind, text, value, expected', [
    ('number', '2', 2, True), ('number', '2,000', 2, True), ('number', '2', 20, False),
    ('number', '1\xa0234,5', 1234.5, True), ('number', 'два', 2, False),
    ('date', '15.01.2026', DATE, True), ('date', '15.01.2026 00:00:00', DATE, True),
    ('date', '16.01.2026', DATE, False),
    ('boolean', 'Да', True, True), ('boolean', 'Ложь', False, True), ('boolean', 'Нет', True, False),
    ('string', 'Протон', 'Протон', True), ('string', 'Протон', 'Протон-2', False),
    ('string', '2', '2,000', False), ('reference', 'x', {'$type': 'ref'}, None),
])
def test_matches_by_value_kind(kind, text, value, expected):
    assert T.matches(kind, text, value, SERVICE) is expected


def verdict(monkeypatch, kind, value, text, presentation):
    monkeypatch.setattr(T, 'field_value', lambda S, c, key: (kind, value))
    return R._typed_verdict(SimpleNamespace(), 'F.EditField[Поле]', text, presentation)


def test_verdict_accepts_formatted_number(monkeypatch):
    result = verdict(monkeypatch, 'number', 2, '2', '2,000')
    assert result['committed'] is True and result['verification'] == 'number'


def test_verdict_rejects_string_suffix(monkeypatch):
    result = verdict(monkeypatch, 'string', 'Протон-2', 'Протон', 'Протон-2')
    assert result['ok'] is False and result['code'] == 'value_mismatch' and result['actual'] == 'Протон-2'


def test_verdict_without_helper_is_exact_text(monkeypatch):
    assert verdict(monkeypatch, None, None, '2', '2')['committed'] is True
    assert verdict(monkeypatch, None, None, '2', '2,000')['code'] == 'value_mismatch'
    assert verdict(monkeypatch, None, None, '2', None) == {}


class Dropdown:
    """Choice-list stub for Selector.dropdown."""

    def __init__(self, presentations):
        self.presentations, self.chosen = presentations, None
        items = [dict(presentation=p) for p in presentations]
        ok = lambda **kw: dict(ok=True)  # noqa: E731
        self.S = SimpleNamespace(
            _cell_window=lambda c, expected=None: None,
            tc_open_drop_list=ok, tc_close_drop_list=ok,
            tc_drop_list_is_open=lambda **kw: dict(ok=True, open=True),
            tc_get_choice_list=lambda **kw: dict(ok=True, status='ok', presentations=list(presentations), items=items),
            tc_choose_from_drop_list=lambda value, **kw: setattr(self, 'chosen', value) or dict(ok=True))

    def select(self, value):
        selector = V.Selector(self.S, None, 'F.EditField[Номенклатура]', 'h', 500)
        selector.origin = None
        return selector.dropdown(value)


def test_exact_item_is_chosen_over_group():
    stub = Dropdown(['Программные продукты 1С', '1С:Бухгалтерия 8'])
    assert stub.select('1С:Бухгалтерия 8') is True and stub.chosen == 1


def test_two_exact_items_are_ambiguous_with_candidates():
    stub = Dropdown(['Иванов', 'Иванов'])
    with pytest.raises(B.Failure) as error:
        stub.select('Иванов')
    assert error.value.code == 'ambiguous_choice' and len(error.value.details['candidates']) == 2


@pytest.mark.parametrize('code, mapped', [('ambiguous_choice', 'ambiguous_value'), ('choice_not_found', 'value_not_found')])
def test_reference_input_reports_candidates(monkeypatch, code, mapped):
    monkeypatch.setattr(V, 'run', lambda S, c, key, handle, value: dict(ok=False, code=code, candidates=['a']))
    result = R._reference_input(None, 'F.EditField[Поле]', 'h', 'a')
    assert result['code'] == mapped and result['candidates'] == ['a'] and result['committed'] is False


def flaky(refusals, field=lambda: 'old'):
    """Dropdown whose choice step is refused `refusals` times with status 17."""
    stub = Dropdown(['Программные продукты 1С', '1С:Бухгалтерия 8'])
    calls = []

    def choose(value, **kw):
        calls.append(value)
        if len(calls) <= refusals:
            return dict(ok=False, code='unsupported_receiver')
        stub.chosen = value
        return dict(ok=True)
    stub.S.tc_choose_from_drop_list = choose
    selector = V.Selector(stub.S, SimpleNamespace(_io_deadline=None), 'F.EditField[Номенклатура]', 'h', 500)
    selector.origin, selector.result['value_before'] = None, 'old'
    selector.field_text = field
    return selector, stub, calls


def test_refused_choice_is_repeated(monkeypatch):
    monkeypatch.setattr(V, '_RETRY_PAUSE', 0.01)
    selector, stub, calls = flaky(2)
    assert selector.retry(lambda: selector.dropdown('1С:Бухгалтерия 8')) is True
    assert stub.chosen == 1 and selector.attempts == 3


def test_refusal_until_timeout_reports_attempts(monkeypatch):
    monkeypatch.setattr(V, '_RETRY_PAUSE', 0.01)
    selector, stub, calls = flaky(10 ** 6)
    selector.c._io_deadline = __import__('time').monotonic() + 0.1
    with pytest.raises(B.Failure) as error:
        selector.retry(lambda: selector.dropdown('1С:Бухгалтерия 8'))
    assert error.value.code == 'unsupported_receiver' and error.value.details['attempts'] > 1
    assert selector.selection_sent is True


def test_changed_value_stops_repeating(monkeypatch):
    monkeypatch.setattr(V, '_RETRY_PAUSE', 0.01)
    selector, stub, calls = flaky(5, field=lambda: '1С:Бухгалтерия 8')
    assert selector.retry(lambda: selector.dropdown('1С:Бухгалтерия 8')) == 'changed' and len(calls) == 1


def choice_form(search_result):
    """Choice form whose value is hidden in a group until the list search string is used."""
    searched = []
    S = SimpleNamespace(_cell_window=lambda c, expected=None: 'Choice', _read_open_windows=lambda c: [],
                        _list_search=SimpleNamespace(run=lambda S, c, key, handle, text, **kw:
                                                     searched.append(text) or search_result))
    selector = V.Selector(S, SimpleNamespace(_io_deadline=None), 'F.EditField[Номенклатура]', 'h', 500)
    selector.origin = 'Form'
    table = dict(key='Choice.ManagedForm[c].Table[Список]', handle='t')
    selector.call = lambda action, obj, **kw: dict(ok=True)
    selector.objects = lambda: [table]
    selector.table_for = lambda objects, name: table

    def locate(table, match, value, column):
        if not searched:
            raise B.Failure('choice_not_found', 'No exact value.', details={'candidates': []})
        return {'Наименование': value}
    selector.locate = locate
    return selector, searched


def test_value_inside_group_is_found_by_list_search():
    selector, searched = choice_form(dict(ok=True))
    selector.form('1С:Бухгалтерия 8', None, None, None, None)
    assert searched == ['1С:Бухгалтерия 8'] and selector.result['matched_row'] == {'Наименование': '1С:Бухгалтерия 8'}


def test_unavailable_list_search_keeps_not_found():
    selector, searched = choice_form(dict(ok=False, code='search_field_unavailable', error='no search'))
    with pytest.raises(B.Failure) as error:
        selector.form('1С:Бухгалтерия 8', None, None, None, None)
    assert error.value.code == 'choice_not_found' and error.value.details['search']['code'] == 'search_field_unavailable'
