import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _code_execution as ce  # noqa: E402

FORM = 'MainFrame[w].ManagedForm[f-1]'


def client(capabilities=('form_state',)):
    c = SimpleNamespace()
    c._testpilot_service = dict(capabilities=list(capabilities))
    return c


def test_without_helper_or_capability_state_is_unknown():
    assert ce.form_state(None, SimpleNamespace(), FORM) is None
    assert ce.form_state(None, client(capabilities=('form_details',)), FORM) is None


def test_state_is_parsed(monkeypatch):
    calls = []

    def execute(R, c, **kwargs):
        calls.append(kwargs)
        return dict(ok=True, result=dict(found=True, form_id='f-1', modified=False,
            object=dict(ref={'$type': 'ref', 'uuid': 'u'}, is_new=False, posted=True),
            items=[dict(name='Количество', value=2), dict(name='Партнер', value={'$type': 'ref'})], errors=[]))
    monkeypatch.setattr(ce, 'execute', execute)
    state = ce.form_state(None, client(), FORM, ['Количество', 'Партнер'])
    assert state['modified'] is False and state['object']['posted'] is True
    assert state['values'] == {'Количество': 2, 'Партнер': {'$type': 'ref'}}
    assert calls[0]['mode'] == 'form_state' and calls[0]['options'] == dict(form_id='f-1', items=['Количество', 'Партнер'])
    assert calls[0]['check_permissions'] is False


def test_closed_form_and_foreign_form(monkeypatch):
    monkeypatch.setattr(ce, 'execute', lambda R, c, **k: dict(ok=True, result=dict(found=False, form_id='f-1')))
    assert ce.form_state(None, client(), FORM) == dict(found=False)
    monkeypatch.setattr(ce, 'execute', lambda R, c, **k: dict(ok=True, result=dict(found=True, form_id='other')))
    with pytest.raises(ce.Failure):
        ce.form_state(None, client(), FORM)


@pytest.mark.parametrize('value, kind', [
    (None, 'empty'), (True, 'boolean'), (2, 'number'), (2.5, 'number'), ('Протон', 'string'),
    ({'$type': 'date', 'value': '2026-01-01T00:00:00'}, 'date'), ({'$type': 'ref'}, 'reference'),
    ({'$type': 'enum'}, 'reference'), ([1], 'other'),
])
def test_value_kind(value, kind):
    assert ce.value_kind(value) == kind


def test_packaged_processing_is_the_default(monkeypatch):
    import dataclasses
    monkeypatch.setattr(ce, 'SETTINGS', dataclasses.replace(ce.SETTINGS, epf=''))
    path = ce.packaged_epf()
    assert path.is_file() and path.name == 'Testpilot.epf' and path.parent.name == 'testpilot_assets'
    assert ce.launch_path(None, python_api=True) == str(path)
    assert ce.launch_path('', python_api=True) is None
