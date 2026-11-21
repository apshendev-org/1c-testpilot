"""Click effect engine: the action confirms its own effect, waits, retries once and handles dialogs."""
import json
import os
import re
import tempfile
import time
import uuid

import _dialogs

# Стандартные команды формы: имя кнопки автокомандной панели — «Форма» + идентификатор команды.
_STANDARD = {
    'Записать': 'saved', 'Write': 'saved',
    'Провести': 'posted', 'Post': 'posted',
    'ЗаписатьИЗакрыть': 'saved_closed', 'WriteAndClose': 'saved_closed',
    'ПровестиИЗакрыть': 'posted_closed', 'PostAndClose': 'posted_closed',
    'Закрыть': 'closed', 'Close': 'closed', 'ОК': 'closed', 'OK': 'closed',
    'Выбрать': 'closed', 'Choose': 'closed', 'Select': 'closed',
    'Создать': 'opened', 'Create': 'opened',
}
_FIELD_LIMIT = 200
_POSTED = 'ВЫБРАТЬ Проведен ИЗ {} ГДЕ Ссылка = &Ссылка'


def ref_from_url(url):
    """Reference of an object form from its navigation link e1cib/data/<metadata>?ref=<32 hex>."""
    match = re.fullmatch(r'e1cib/data/([^?]+)\?ref=([0-9a-fA-F]{32})', url or '')
    if not match:
        return None
    h = match[2].lower()
    # В навигационной ссылке части UUID переставлены: ref = clock_seq+node, time_hi, time_mid, time_low.
    uuid_text = f'{h[24:32]}-{h[20:24]}-{h[16:20]}-{h[0:4]}-{h[4:16]}'
    return {'$type': 'ref', 'metadata': match[1], 'uuid': uuid_text}


def expected_effect(key):
    """Expected effect of a button by its name; 'changed' for everything else."""
    last = key.rsplit('.', 1)[-1]
    if not last.startswith('Button['):
        return 'changed'
    name = last[len('Button['):-1]
    for prefix in ('Форма', 'Form'):
        if name.startswith(prefix) and name[len(prefix):] in _STANDARD:
            return _STANDARD[name[len(prefix):]]
    return 'changed'


class Observer:
    """Reads the observable state around one clicked element."""

    def __init__(self, S, c, key):
        self.S, self.c = S, c
        self.form = S._batches.owner(S, key)
        self.form_window = S._collection_parent(self.form) if self.form else None
        self.helper = None   # None — неизвестно, False — обработки нет, True — form_state читается
        self.fields = []
        self.focus = False

    def prepare_fields(self):
        # Только для прочих команд: значения полей нужны лишь для «любого изменения».
        if not self.form:
            return
        # Добавление строки и подобные команды видны только по фокусу и режиму редактирования таблицы.
        self.focus = True
        try:
            objects = self.S._search_objects(self.c, self.form)
        except Exception:
            return
        self.fields = sorted({o['name'] for o in objects
                              if o.get('class') == 'EditField' and o.get('name')})[:_FIELD_LIMIT]

    def messages(self, window_key):
        S = self.S
        if not window_key or not S._guid_available(self.c, S.G.GET_USER_MESSAGE_TEXTS):
            return None
        try:
            reply = self.c.send_cmd(S.G.GET_USER_MESSAGE_TEXTS, window_key, kind='read', middle=S.RC)
        except S.tc1c.OperationError:
            return None
        parsed = S._user_messages_result(reply)
        return parsed.get('messages') if parsed.get('ok') else None

    def form_state(self):
        if not self.form or self.helper is False:
            return None
        try:
            state = self.S._code_execution.form_state(self.S, self.c, self.form, self.fields)
        except self.S._code_execution.Failure:
            state = None
        self.helper = state is not None
        return state

    def modified(self):
        """Modification flag without the helper; None if the form is gone or unreadable."""
        obj = self.S._ref_live_object(self.c, self.form) if self.form else None
        if not obj:
            return None
        S = self.S
        try:
            reply = self.c.send_cmd(S.G.CURRENT_MODIFIED, self.form, kind='read', middle=S.RS, handle=obj.get('handle'))
        except S.tc1c.OperationError:
            return None
        return S._scalar(reply, S._bool_from_resp)

    def current(self):
        """Focused element of the form and, for a table, whether its row is being edited."""
        S = self.S
        obj = S._ref_live_object(self.c, self.form)
        if not obj:
            return None
        try:
            key = S._input_current(self.c, dict(key=self.form, handle=obj.get('handle')))
            if not key or S._key_class(key) != 'Table':
                return key
            table = S._ref_live_object(self.c, key)
            return [key, S._cell_flag(self.c, S.G.CURRENT_MODE_IS_EDIT, key, table.get('handle')) if table else None]
        except S.tc1c.OperationError:
            return None

    def posted_by_admin(self, after):
        """Проведен of the form object, read by the admin client; None while the window has no ref."""
        ref = ref_from_url(after.get('url'))
        if ref is None:
            return None
        result = self.S._admin_client.call(self.S, 'execute_query', dict(
            query=_POSTED.format(ref['metadata']), parameters={'Ссылка': ref}, limit=1))
        if not result.get('ok'):
            raise self.S._code_execution.Failure(result.get('code') or 'admin_query_failed',
                                                 result.get('error') or 'The admin client could not read the object.',
                                                 delegated_to=result.get('delegated_to'))
        rows = result.get('rows') or []
        return dict(ref=ref, delegated_to=result.get('delegated_to')) if rows and rows[0].get('Проведен') is True else None

    def capture(self):
        S = self.S
        S._state['window_key'] = None
        window = S._window(self.c)
        dialog = _dialogs.detect(S, self.c, window)
        state = dict(window=window.get('key'), title=window.get('title'), url=window.get('url'),
                     dialog=dialog, messages=self.messages(self.form_window or window.get('key')))
        if dialog is not None:
            return state   # Модальное окно блокирует обработку и форму: остальное не читается.
        form = self.form_state()
        if form is not None:
            state.update(found=form['found'], modified=form.get('modified'),
                         object=form.get('object'), values=form.get('values'))
        elif self.form:
            open_ = self.S._ref_live_object(self.c, self.form) is not None
            state.update(found=open_, modified=self.modified() if open_ else None)
        if self.focus and state.get('found') is not False:
            state['current'] = self.current()
        return state


def _same(before, after):
    keys = ('window', 'title', 'url', 'found', 'modified', 'object', 'values', 'messages', 'current')
    return all(before.get(k) == after.get(k) for k in keys) and after.get('dialog') is None


def _new_messages(before, after):
    old, new = before.get('messages') or [], after.get('messages') or []
    return new[len(old):] if new[:len(old)] == old else (new if new != old else [])


def _changes(before, after):
    out = {}
    for k in ('window', 'title', 'url', 'modified', 'object', 'current'):
        if before.get(k) != after.get(k):
            out[k] = after.get(k)
    if before.get('found') and after.get('found') is False:
        out['form_closed'] = True
    values_before, values_after = before.get('values') or {}, after.get('values') or {}
    fields = {n: values_after.get(n) for n in set(values_before) | set(values_after)
              if values_before.get(n) != values_after.get(n)}
    if fields:
        out['fields'] = fields
    messages = _new_messages(before, after)
    if messages:
        out['messages'] = messages
    return out


def _closed(observer, after):
    if after.get('found') is not None:
        return after['found'] is False
    return bool(observer.form_window) and after.get('window') != observer.form_window


def observed(expected, observer, before, after):
    """Effect name and details if the expected effect is visible, else None."""
    obj = after.get('object') or {}
    if expected == 'saved':
        if after.get('found') and after.get('modified') is False and (
                observer.helper is not True or (obj.get('ref') and not obj.get('is_new'))):
            return dict(effect='saved', ref=obj.get('ref'))
    elif expected == 'posted':
        if after.get('found') and obj.get('posted') is True and after.get('modified') is False:
            return dict(effect='posted', ref=obj.get('ref'))
    elif expected in ('saved_closed', 'posted_closed', 'closed'):
        # Форма закрывается после записи/проведения только при успехе.
        if _closed(observer, after):
            return dict(effect=expected, ref=(before.get('object') or {}).get('ref'))
    elif expected == 'opened':
        if after.get('window') and after.get('window') != before.get('window'):
            return dict(effect='opened')
    elif expected == 'changed':
        changes = _changes(before, after)
        if changes:
            return dict(effect='changed', changes=changes)
    return None


def artifacts_dir():
    return os.environ.get('TC1C_ARTIFACTS_DIR') or os.path.join(tempfile.gettempdir(), 'testpilot-snapshots')


def snapshot(S):
    """Full form context saved for diagnostics; returns the file path or None."""
    try:
        context = S.tc_get_context(result_mode='full')
    except Exception as exc:
        context = dict(ok=False, error=str(exc))
    try:
        directory = artifacts_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f'click-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}.json')
        with open(path, 'w', encoding='utf8') as f:
            json.dump(context, f, ensure_ascii=False, indent=2, default=str)
        return path
    except OSError:
        return None


def _failure(S, code, error, expected, after, messages=None, **extra):
    return dict(ok=False, code=code, error=error, expected=expected,
                window=dict(key=after.get('window'), title=after.get('title')),
                messages=after.get('messages') if messages is None else messages, snapshot=snapshot(S), **extra)


def run(S, c, key, send, *, answer=None, expect=None, timeout=10.0, interval=0.2):
    """Click with effect confirmation. send() performs the click and returns its raw result."""
    if expect == 'none':
        return send()
    expected = expected_effect(key)
    observer = Observer(S, c, key)
    if expected == 'changed':
        observer.prepare_fields()
    before = observer.capture()
    if expected == 'posted' and observer.helper is not True:
        observer.S._admin_client.profile(S)   # без обработки и админ-клиента — отказ до клика
    result = send()
    if not result.get('ok'):
        return result
    started = time.monotonic()
    deadline, half = started + timeout, started + timeout / 2
    repeated, answered = False, None
    while True:
        after = observer.capture()
        dialog = after['dialog']
        if dialog is not None:
            if answer is not None and answered is None:
                button = _dialogs.choose(dialog, answer)
                if button is None:
                    return dict(_dialogs.refusal(dialog, 'dialog_button_not_found',
                                                 'The dialog has no button with this caption.'), target=key)
                answered = dict(_dialogs.public(dialog), answered=_dialogs.press(S, c, dialog, button))
                continue
            if len(dialog['buttons']) == 1:
                return dict(_dialogs.refusal(dialog, 'error_dialog', 'The action opened an error window.'),
                            target=key, expected=expected)
            return dict(_dialogs.refusal(dialog), target=key, expected=expected)
        effect = observed(expected, observer, before, after)
        if (not effect and expected == 'posted' and observer.helper is not True
                and after.get('found') and after.get('modified') is False):
            effect = observer.posted_by_admin(after)
            if effect:
                effect = dict(effect='posted', **effect)
        if effect:
            out = dict(result, **{k: v for k, v in effect.items() if v is not None})
            out.update(window=dict(key=after.get('window'), title=after.get('title'), url=after.get('url')),
                       dialog=answered)
            new = _new_messages(before, after)
            if new:
                out['messages'] = new
            if repeated:
                out['repeated'] = True
            return out
        if expected != 'changed' and _new_messages(before, after):
            return dict(_failure(S, 'effect_not_observed', 'The command reported messages instead of its effect.',
                                 expected, after, messages=_new_messages(before, after)), target=key)
        now = time.monotonic()
        if now >= deadline:
            return dict(_failure(S, 'effect_not_observed', 'The expected effect was not observed before the timeout.',
                                 expected, after, repeated=repeated), target=key)
        if not repeated and answered is None and now >= half and _same(before, after):
            repeated = True
            result = send()
            if not result.get('ok'):
                return result
        time.sleep(min(interval, max(0.0, deadline - now)))
