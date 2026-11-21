import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _dialogs  # noqa: E402

WINDOW = 'Window[d]'


def button(name, title):
    return dict(cls='Button', name=name, title=title)


def fake(dialog_buttons=None, question='Записать изменения?', appear_after=0.0):
    """Runtime stub: the active window turns into a MessageBox after appear_after seconds."""
    started = time.monotonic()
    client = Mock()
    pressed = []
    client.send_cmd.side_effect = lambda guid, key, **kw: pressed.append((key, kw['kind'])) or {'ok': True}

    def shown():
        return dialog_buttons is not None and time.monotonic() - started >= appear_after

    def objects(c, key):
        out = [dict(key=WINDOW + '.ManagedForm[m]', class_='ManagedForm', form_name='MessageBox'),
               dict(key=WINDOW + '.ManagedForm[m].Decoration[Message]', name='Message',
                    title=question, **{'class': 'Decoration'})]
        for b in dialog_buttons:
            out.append({'key': f"{WINDOW}.ManagedForm[m].Group[Buttons].Button[{b['name']}]",
                        'name': b['name'], 'title': b['title'], 'class': 'Button', 'handle': 'h-' + b['name']})
        return out

    S = SimpleNamespace(
        G=SimpleNamespace(CLICK='click'), _state={},
        _window=lambda c: dict(key=WINDOW if shown() else 'MainFrame[x]'),
        _form_title=lambda c, key: ('1С:Предприятие', 'MessageBox') if key == WINDOW else ('Документ', 'Форма'),
        _search_objects=objects)
    return S, client, pressed


def test_detect_reports_question_and_buttons():
    S, c, _ = fake([button('Button0', 'Да'), button('Button1', 'Нет'), button('Button2', 'Отмена')])
    dialog = _dialogs.detect(S, c)
    assert _dialogs.public(dialog) == dict(question='Записать изменения?', buttons=['Да', 'Нет', 'Отмена'])


def test_no_dialog_on_ordinary_window():
    S, c, _ = fake(None)
    assert _dialogs.detect(S, c) is None


@pytest.mark.parametrize('answer, confirm, expected', [
    ('Отмена', None, 'Button2'), ('да', None, 'Button0'), (None, True, 'Button0'), (None, False, 'Button1'),
])
def test_choose_by_caption_or_confirm(answer, confirm, expected):
    S, c, _ = fake([button('Button0', 'Да'), button('Button1', 'Нет'), button('Button2', 'Отмена')])
    assert _dialogs.choose(_dialogs.detect(S, c), answer, confirm)['name'] == expected


def test_choose_without_captions_uses_button_order():
    S, c, _ = fake([button('Button0', None), button('Button1', None)])
    dialog = _dialogs.detect(S, c)
    assert _dialogs.choose(dialog, 'Нет')['name'] == 'Button1'
    assert _dialogs.choose(dialog, None, True)['name'] == 'Button0'


def test_answer_presses_as_soon_as_dialog_appears():
    S, c, pressed = fake([button('Button0', 'Да'), button('Button1', 'Нет')], appear_after=0.3)
    started = time.monotonic()
    result = _dialogs.answer(S, c, confirm=True, timeout=5, interval=0.05)
    assert time.monotonic() - started < 1.5
    assert result['ok'] and result['answered'] == 'Да' and result['question'] == 'Записать изменения?'
    assert [kind for _, kind in pressed] == ['action', 'commit']


def test_answer_without_dialog_fails_after_timeout():
    S, c, pressed = fake(None)
    started = time.monotonic()
    result = _dialogs.answer(S, c, timeout=0.3, interval=0.05)
    assert 0.3 <= time.monotonic() - started < 1.0
    assert result == dict(ok=False, code='no_dialog', answered=None, question=None,
                          error='No modal dialog appeared before the timeout.')
    assert pressed == []


def test_answer_with_missing_button_lists_buttons():
    S, c, pressed = fake([button('Button0', 'ОК')])
    result = _dialogs.answer(S, c, answer='Да', timeout=1)
    assert result['code'] == 'dialog_button_not_found' and result['dialog']['buttons'] == ['ОК']
    assert pressed == []
