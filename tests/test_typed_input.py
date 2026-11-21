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
