"""execute_command на уже открытом окне списка (изменение list-refresh-on-reopen).

Записи спайка testpilot-goto-row-list-load (spike:spk_b232b1dd6d@v3), копии в tests/recordings/:
- docs/spikes/testpilot-goto-row-list-load/recording/goto-row-stale-window.jsonl — список открыт
  до фикстуры; повторный execute_command вернул то же окно, нового документа в нём нет;
- docs/spikes/testpilot-goto-row-list-load/recording/goto-row-refresh.jsonl — тот же сценарий:
  кнопка ФормаОбновить найдена (Button) и нажата, после нажатия goto_row находит новый документ;
- docs/spikes/testpilot-goto-row-list-load/recording/goto-row-fixture.jsonl,
  docs/spikes/testpilot-goto-row-list-load/recording/goto-row-preloaded.jsonl — список
  открывается впервые: окно новое.

Заглушки внутренних чтений runtime (_read_open_windows, _window, _form_title, _find, tc_click)
отвечают записанными ответами: ref в записи переводится в key загрузчиком _recording. Кнопку для
записи stale-window даёт прогон refresh — в самой записи stale-window кнопку не читали, форма та же.
Успешный ответ нажатия (ok: true) — единственный не записанный ответ: expect='none' не ждёт
эффекта, а сам эффект нажатия запись подтверждает (после него goto_row нашёл новый документ).
"""
import inspect
import os
import sys
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _recording as recorded  # noqa: E402
import _runtime as R  # noqa: E402

COMMAND = 'e1cib/list/Документ.ГНЦА_РМЗДС'


def refresh_button():
    """Записанное чтение кнопки ФормаОбновить и записанный ответ её нажатия (прогон refresh)."""
    found = [c for c in recorded.exchange(recorded.REFRESH)
             if c['action'] == 'find_object' and c['arguments'].get('name') == 'ФормаОбновить']
    clicked = [c for c in recorded.exchange(recorded.REFRESH) if c['action'] == 'click']
    assert len(found) == len(clicked) == 1     # в записи одно чтение кнопки и одно нажатие
    return found[0]['response']['object'], clicked[0]['response']


def stale_reopen(path):
    """Окно списка из записи: ответ execute_command до фикстуры и повторный после неё."""
    opens = recorded.responses('execute_command', path)
    before, after = opens[0]['window'], opens[1]['window']
    assert before['key'] == after['key'], 'запись: повторный вызов вернул то же окно'
    return before, after


class World:
    """Внутренние чтения runtime с ответами из записи; вызовы _find и tc_click собирает."""

    def __init__(self, opened=(), window=None, form_title=(None, None), button=None, click_reply=None):
        self.opened = list(opened)             # окна, открытые до команды
        self.window = dict(window or {})       # окно, возвращённое командой
        self.form_title = form_title
        self.button = dict(button) if button else None
        self.click_reply = click_reply
        self.finds, self.clicks = [], []
        self.c = SimpleNamespace(send_cmd=lambda guid, key, **kw: {'ok': True})

    def find(self, c, name=None, cls=None, root_key=None, **kw):
        self.finds.append((name, cls, root_key))
        if not self.button:
            return []
        row = dict(self.button)
        # handle в ответ MCP не входит (MCP адресует кнопку ref-ом); заглушке хватит непустого
        row['handle'] = row['key']
        return [row]

    def click(self, **kw):
        self.clicks.append(kw)
        return dict(self.click_reply) if self.click_reply else {'ok': True}


def run(world):
    """execute_command с заглушками внутренних чтений."""
    patches = (patch.object(R, '_need', return_value=world.c),
               patch.object(R, '_window', lambda c: dict(world.window)),
               patch.object(R, '_read_open_windows', lambda c: [dict(w) for w in world.opened]),
               patch.object(R, '_form_title', lambda c, key: world.form_title),
               patch.object(R, '_find', world.find),
               patch.object(R, 'tc_click', world.click))
    with ExitStack() as stack:
        for target in patches:
            stack.enter_context(target)
        return inspect.unwrap(R.tc_execute_command)(COMMAND)


@pytest.mark.parametrize('path', [recorded.STALE_WINDOW, recorded.REFRESH],
                         ids=['stale-window', 'refresh'])
def test_reopened_window_with_button_is_refreshed(path):
    """Список открыт до фикстуры, execute_command вернул то же окно: ФормаОбновить нажата
    с expect='none', ответ ok: true и refreshed: true."""
    before, after = stale_reopen(path)
    button, _ = refresh_button()
    world = World(opened=[before], window=after, form_title=(after['title'], after['form_name']),
                  button=button)
    result = run(world)
    assert result['ok'] is True
    assert result['refreshed'] is True
    assert world.finds == [('ФормаОбновить', 'Button', after['key'])]
    assert len(world.clicks) == 1
    assert world.clicks[0]['key'] == button['key']
    assert world.clicks[0]['expect'] == 'none'
    assert result['window']['key'] == after['key']


@pytest.mark.parametrize('path', [recorded.FIXTURE, recorded.PRELOADED],
                         ids=['fixture', 'preloaded'])
def test_first_open_is_not_refreshed(path):
    """Список открывается впервые: окно новое, ничего не ищется и не нажимается,
    refreshed в ответе нет."""
    window = recorded.responses('execute_command', path)[0]['window']
    world = World(window=window, form_title=(window['title'], window['form_name']))
    result = run(world)
    assert result['ok'] is True
    assert 'refreshed' not in result
    assert world.finds == [] and world.clicks == []
    assert result['window']['key'] == window['key']
    assert result['window']['title'] == window['title']
    assert result['window']['form_name'] == window['form_name']


def test_reopened_window_without_button_answers_as_before():
    """Открытое окно без ФормаОбновить (окно «Информация» из записи refresh): поиск кнопки
    ничего не нашёл — ответ ok: true без refreshed и без ошибки, нажатия нет."""
    info = recorded.responses('get_active_window', recorded.REFRESH)[0]
    world = World(opened=[info], window=info, form_title=(info['title'], None))
    result = run(world)
    assert result['ok'] is True
    assert 'refreshed' not in result
    assert 'error' not in result and 'code' not in result
    assert world.finds == [('ФормаОбновить', 'Button', info['key'])]
    assert world.clicks == []
    assert result['window']['key'] == info['key']


def test_failed_refresh_click_keeps_old_answer():
    """Нажатие ФормаОбновить вернуло записанный отказ прогона refresh (effect_not_observed):
    ответ ok: true без refreshed и без ошибки, как раньше."""
    before, after = stale_reopen(recorded.REFRESH)
    button, click_reply = refresh_button()
    world = World(opened=[before], window=after, form_title=(after['title'], after['form_name']),
                  button=button, click_reply=click_reply)
    result = run(world)
    assert result['ok'] is True
    assert 'refreshed' not in result
    assert 'error' not in result and 'code' not in result
    assert len(world.clicks) == 1 and world.clicks[0]['expect'] == 'none'
