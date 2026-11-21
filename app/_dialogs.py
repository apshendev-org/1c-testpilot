"""Modal dialogs (questions, warnings, error boxes) recognised and answered by the engine."""
import time

# Платформенный MessageBox: заголовки кнопок есть в нативном поиске, но не в обходе дерева.
# Если заголовка нет, кнопка опознаётся по имени — порядок ДиалогРежим (Да/Нет/Отмена, ОК/Отмена).
_NAME_TITLES = {'Button0': ('Да', 'ОК', 'OK', 'Yes'), 'Button1': ('Нет', 'Отмена', 'No', 'Cancel'),
                'Button2': ('Отмена', 'Cancel')}
_YES = ('да', 'yes', 'ок', 'ok')
_NO = ('нет', 'no', 'отмена', 'cancel')


def detect(S, c, window=None):
    """The active modal message box, or None: window key, question text and buttons."""
    window = window if window is not None else S._window(c)
    key = window.get('key')
    if not key:
        return None
    _title, form_name = S._form_title(c, key)
    if form_name != 'MessageBox':
        return None
    objects = S._search_objects(c, key)
    question = next((o.get('title') for o in objects if o.get('name') == 'Message'
                     and o.get('class') == 'Decoration' and o.get('title')), None)
    buttons = [dict(title=o.get('title') or None, name=o.get('name'), key=o['key'], handle=o.get('handle'))
               for o in objects if o.get('class') == 'Button' and '.Group[Buttons].Button[' in (o.get('key') or '')]
    buttons.sort(key=lambda b: b['name'] or '')
    return dict(window=key, question=question, buttons=buttons)


def public(dialog):
    """Dialog description for an action result, without element addresses."""
    if dialog is None:
        return None
    return dict(question=dialog['question'], buttons=[b['title'] or b['name'] for b in dialog['buttons']])


def choose(dialog, answer=None, confirm=None):
    """The button for answer (exact caption, case-insensitive) or confirm=True/False."""
    buttons = dialog['buttons']
    if answer is not None:
        wanted = answer.strip().casefold()
        found = [b for b in buttons if (b['title'] or '').casefold() == wanted]
        if not found:
            found = [b for b in buttons if not b['title']
                     and wanted in (t.casefold() for t in _NAME_TITLES.get(b['name'], ()))]
        return found[0] if len(found) == 1 else None
    words = _YES if confirm else _NO
    found = [b for b in buttons if (b['title'] or '').casefold() in words]
    if found:
        return found[0]
    # Без заголовков сохраняется прежнее правило: Да — Button0, Нет — Button1.
    name = 'Button0' if confirm else 'Button1'
    return next((b for b in buttons if b['name'] == name), None)


def press(S, c, dialog, button):
    """Press a dialog button; returns the caption used in results."""
    for kind in ('action', 'commit'):
        c.send_cmd(S.G.CLICK, button['key'], kind=kind, middle=b'', handle=button.get('handle'))
    S._state['window_key'] = None
    title = button['title']
    if not title:
        titles = _NAME_TITLES.get(button['name'], ())
        title = titles[0] if titles else button['name']
    return title


def refusal(dialog, code='unexpected_dialog', error=None):
    return dict(ok=False, code=code,
                error=error or 'The action opened a modal dialog. Pass answer with one of its buttons.',
                dialog=public(dialog))


def answer(S, c, *, answer=None, confirm=True, timeout=5.0, interval=0.2):
    """Wait for a dialog to appear, press its button immediately, or report no_dialog."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        S._state['window_key'] = None
        dialog = detect(S, c)
        if dialog is not None:
            button = choose(dialog, answer, confirm)
            if button is None:
                return refusal(dialog, 'dialog_button_not_found',
                               'The dialog has no button with this caption.')
            pressed = press(S, c, dialog, button)
            return dict(ok=True, answered=pressed, question=dialog['question'], dialog=public(dialog))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return dict(ok=False, code='no_dialog', answered=None, question=None,
                        error='No modal dialog appeared before the timeout.')
        time.sleep(min(interval, remaining))
