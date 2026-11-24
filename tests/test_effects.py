import os
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _effects  # noqa: E402
import _recording as recorded  # noqa: E402

WINDOW = 'Window[w]'
FORM = WINDOW + '.ManagedForm[f-1]'
DIALOG = 'Window[d]'


class Failure(Exception):
    pass


class World:
    """1C client stub: form state plus delayed consequences of clicks and dialog answers."""

    def __init__(self, helper=True, admin=None, **state):
        self.helper, self.admin = helper, admin
        self.state = dict(window=WINDOW, open=True, modified=True, posted=False, ref=None,
                          values={'Сумма': 0}, messages=[], dialog=None, focus=FORM + '.EditField[Сумма]', editing=False)
        self.state.update(state)
        self.events, self.clicks, self.on_answer = [], 0, {}

    def later(self, delay, **changes):
        self.events.append((time.monotonic() + delay, changes))

    def tick(self):
        now = time.monotonic()
        for event in [e for e in self.events if e[0] <= now]:
            self.events.remove(event)
            self.state.update(event[1])

    def send(self, effect=None):
        def send():
            self.clicks += 1
            if effect:
                effect(self)
            return {'ok': True, 'target': 'button'}
        return send

    def runtime(self):
        st = self.state
        world = self

        def window(c):
            world.tick()
            if st['dialog']:
                return dict(key=DIALOG, title='1С:Предприятие')
            return dict(key=st['window'], title='Форма ' + st['window'], url=st.get('url'))

        def search(c, key):
            if key == DIALOG:
                question, buttons = st['dialog']
                return [dict(key=DIALOG + '.ManagedForm[m].Decoration[Message]', name='Message', title=question,
                             **{'class': 'Decoration'})] + [
                    {'key': f'{DIALOG}.ManagedForm[m].Group[Buttons].Button[Button{i}]', 'name': f'Button{i}',
                     'title': t, 'class': 'Button', 'handle': 'h'} for i, t in enumerate(buttons)]
            return [{'name': n, 'class': 'EditField', 'key': FORM + f'.EditField[{n}]'} for n in st['values']]

        def form_state(R, c, form, names):
            world.tick()
            if not world.helper:
                return None
            if not st['open']:
                return dict(found=False)
            return dict(found=True, modified=st['modified'], values={n: st['values'].get(n) for n in names},
                        object=dict(ref=st['ref'], is_new=st['ref'] is None, posted=st['posted']))

        def send_cmd(guid, key, **kw):
            if guid == 'click' and key.startswith(DIALOG) and kw['kind'] == 'commit':
                caption = st['dialog'][1][int(key[-2])]
                st['dialog'] = None
                st.update(world.on_answer.get(caption, {}))
            return {'ok': True}

        live = lambda c, key: {'handle': 'h'} if st['open'] else None  # noqa: E731
        S = SimpleNamespace(
            G=SimpleNamespace(CLICK='click', GET_USER_MESSAGE_TEXTS='messages', CURRENT_MODIFIED='modified',
                              CURRENT_MODE_IS_EDIT='edit'),
            _input_current=lambda c, form: st['focus'], _cell_flag=lambda c, guid, key, handle: st['editing'],
            _key_class=lambda key: key.rsplit('.', 1)[-1].split('[')[0],
            RC=b'', RS=b'', _state={}, tc1c=SimpleNamespace(OperationError=Failure),
            _batches=SimpleNamespace(owner=lambda S, key: FORM),
            _collection_parent=lambda key: key.rsplit('.', 1)[0] if '.' in key else None,
            _window=window, _form_title=lambda c, key: ('', 'MessageBox' if key == DIALOG else 'Форма'),
            _search_objects=search, _guid_available=lambda c, guid: True,
            _user_messages_result=lambda reply: dict(ok=True, messages=list(st['messages'])),
            _code_execution=SimpleNamespace(form_state=form_state, Failure=Failure),
            _ref_live_object=live, _admin_client=world.admin, _scalar=lambda reply, fn: st['modified'], _bool_from_resp=None,
            tc_get_context=lambda **kw: dict(ok=True, form='context'))
        return S, SimpleNamespace(send_cmd=send_cmd)


def click(world, name, effect=None, kind='Button', **kw):
    S, c = world.runtime()
    kw.setdefault('interval', 0.02)
    return _effects.run(S, c, f'{FORM}.{kind}[{name}]', world.send(effect), **kw)


@pytest.fixture(autouse=True)
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv('TC1C_ARTIFACTS_DIR', str(tmp_path))


@pytest.mark.parametrize('name, effect', [
    ('ФормаЗаписать', 'saved'), ('ФормаПровестиИЗакрыть', 'posted_closed'), ('ФормаСоздать', 'opened'),
    ('ФормаОК', 'closed'), ('Заполнить', 'changed'), ('ФормаЗаполнить', 'changed'),
])
def test_expected_effect_by_button_name(name, effect):
    assert _effects.expected_effect(f'{FORM}.Button[{name}]') == effect


def test_added_row_is_seen_by_focus_and_edit_mode():
    world = World(focus=FORM + '.Table[Товары]')
    result = click(world, 'ТоварыДобавить', lambda w: w.later(0, editing=True), timeout=2)
    assert result['ok'] and result['changes'] == {'current': [FORM + '.Table[Товары]', True]}


def test_save_succeeds_with_ref():
    world = World()
    result = click(world, 'ФормаЗаписать', lambda w: w.later(0, modified=False, ref='ref-1'), timeout=2)
    assert result['ok'] and result['effect'] == 'saved' and result['ref'] == 'ref-1'
    assert world.clicks == 1


def test_save_failure_reports_message_and_snapshot_at_once():
    world = World()
    started = time.monotonic()
    result = click(world, 'ФормаЗаписать', lambda w: w.later(0, messages=['Поле "Контрагент" не заполнено']), timeout=5)
    assert time.monotonic() - started < 1
    assert result['code'] == 'effect_not_observed' and result['expected'] == 'saved'
    assert result['messages'] == ['Поле "Контрагент" не заполнено']
    assert result['window']['key'] == WINDOW and os.path.exists(result['snapshot'])


def test_post_with_helper_and_without():
    world = World()
    result = click(world, 'ФормаПровести', lambda w: w.later(0, modified=False, ref='r', posted=True), timeout=2)
    assert result['ok'] and result['effect'] == 'posted'


URL = 'e1cib/data/Документ.Р?ref=8ca0000d8843cd1b11dc8d8c3d7a1aab'


class Admin:
    """Admin client stub: answers the posting query; profile() refuses when no profile is known."""

    def __init__(self, posted=True, missing=False):
        self.posted, self.missing, self.queries = posted, missing, []

    def profile(self, S):
        if self.missing:
            raise Failure('admin_client_unavailable')
        return 'ib'

    def call(self, S, action, arguments):
        self.queries.append((action, arguments))
        return dict(ok=True, rows=[{'Проведен': self.posted}], delegated_to='ib')


def test_post_without_helper_is_confirmed_by_admin_query():
    admin = Admin()
    world = World(helper=False, admin=admin)
    result = click(world, 'ФормаПровести', lambda w: w.later(0, modified=False, url=URL), timeout=2)
    assert result['ok'] and result['effect'] == 'posted' and result['delegated_to'] == 'ib'
    action, arguments = admin.queries[0]
    assert action == 'execute_query' and arguments['parameters']['Ссылка']['metadata'] == 'Документ.Р'


def test_post_without_helper_and_admin_is_refused_before_click():
    world = World(helper=False, admin=Admin(missing=True))
    with pytest.raises(Failure):
        click(world, 'ФормаПровести', lambda w: w.later(0, modified=False, url=URL), timeout=2)
    assert world.clicks == 0


def test_create_opens_new_form():
    result = click(World(), 'ФормаСоздать', lambda w: w.later(0, window='Window[new]'), timeout=2)
    assert result['ok'] and result['effect'] == 'opened' and result['window']['key'] == 'Window[new]'


def test_arbitrary_command_reports_changed_field():
    result = click(World(), 'Заполнить', lambda w: w.later(0, values={'Сумма': 100}), timeout=2)
    assert result['ok'] and result['effect'] == 'changed' and result['changes']['fields'] == {'Сумма': 100}


def test_slow_save_is_waited_without_second_click():
    # «Медленная запись» (testpilot-ui-feedback): запись заканчивается после половины срока — прежний
    # повтор на половине срока нажал бы «Записать» второй раз; теперь ждёт до timeout, нажата один раз.
    world = World()
    result = click(world, 'ФормаЗаписать', lambda w: w.later(0.6, modified=False, ref='r'), timeout=1)
    assert result['ok'] and result['effect'] == 'saved' and world.clicks == 1 and 'repeated' not in result


def test_unchanged_state_is_pressed_once_then_fails():
    # «Эффект не виден» (testpilot-ui-feedback): форма читается, эффекта нет до timeout — ждать до срока
    # и не повторять. Запись — до правки: goto-row-refresh (spike:spk_b232b1dd6d@v3), click ФормаОбновить
    # в реестре дал effect_not_observed с повтором.
    recorded_reply = recorded.exchange(recorded.REFRESH)[14]
    assert recorded_reply['action'] == 'click' and recorded_reply['response']['repeated'] is True
    world = World()
    started = time.monotonic()
    result = click(world, 'Заполнить', timeout=0.4)
    assert time.monotonic() - started >= 0.4 and world.clicks == 1
    assert result['code'] == recorded_reply['response']['code'] == 'effect_not_observed'
    assert 'repeated' not in result and result['expected'] == 'changed'


def test_unreadable_form_state_is_pressed_once():
    """«Значения полей не читаются» (testpilot-ui-feedback): шаг D записи
    docs/spikes/testpilot-cell-edit/recording/02-no-work-window.jsonl (D_click_clean) — форму внешней
    обработки обработка Testpilot не читает, изменение поля «Замеры» движок не видит до timeout:
    effect_not_observed, нажата один раз, без repeated (в записи «Итог данных» дал +2 строки — повтор
    выполнил команду второй раз)."""
    recorded_reply = recorded.direct(recorded.NO_WORK_WINDOW, 'D_click_clean', 'click')
    assert len(recorded_reply) == 1 and recorded_reply[0]['response']['repeated'] is True   # запись — до правки
    world = World(helper=False)
    result = click(world, 'ФормаИтогДанных', lambda w: w.later(0, values={'Сумма': 100}), timeout=0.4)
    assert world.clicks == 1
    assert result['code'] == recorded_reply[0]['response']['code'] == 'effect_not_observed'
    assert 'repeated' not in result


def test_error_window_fails_at_once():
    world = World()
    started = time.monotonic()
    result = click(world, 'ФормаЗаписать', lambda w: w.later(0, dialog=('Ошибка при записи', ['ОК'])), timeout=5)
    assert time.monotonic() - started < 1
    assert result['code'] == 'error_dialog' and result['dialog']['question'] == 'Ошибка при записи'


def test_write_and_close_with_question_answered():
    world = World()
    world.on_answer['Да'] = dict(open=False, window='Window[list]')
    result = click(world, 'ФормаЗаписатьИЗакрыть', lambda w: w.later(0, dialog=('Записать?', ['Да', 'Нет'])),
                   answer='Да', timeout=2)
    assert result['ok'] and result['effect'] == 'saved_closed'
    assert result['dialog'] == dict(question='Записать?', buttons=['Да', 'Нет'], answered='Да')


def test_answer_without_dialog_is_ok():
    result = click(World(), 'ФормаЗакрыть', lambda w: w.later(0, open=False, window='Window[list]'),
                   answer='Да', timeout=2)
    assert result['ok'] and result['dialog'] is None


def test_question_without_answer_is_unexpected():
    result = click(World(), 'ФормаЗакрыть', lambda w: w.later(0, dialog=('Записать?', ['Да', 'Нет', 'Отмена'])),
                   timeout=2)
    assert result['code'] == 'unexpected_dialog'
    assert result['dialog'] == dict(question='Записать?', buttons=['Да', 'Нет', 'Отмена'])


def test_expect_none_skips_observation():
    world = World()
    started = time.monotonic()
    result = click(world, 'Обновить', expect='none', timeout=5)
    assert result == {'ok': True, 'target': 'button'} and time.monotonic() - started < 0.2


def test_group_click_does_not_wait_for_effect():
    # «Сворачиваемая группа» (testpilot-ui-feedback): клик по Group без expect — как expect="none": ответ
    # сразу после принятия команды, нажата один раз (записи нет — случай из живого потока thr_tipdp79usa).
    world = World()
    started = time.monotonic()
    result = click(world, 'ФормаСвернуть', kind='Group', timeout=5)
    assert result == {'ok': True, 'target': 'button'} and world.clicks == 1
    assert time.monotonic() - started < 0.2
