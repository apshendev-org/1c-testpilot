"""Синонимы аргументов шага и подсказки к отказу invalid_arguments.

Канонические имена параметров не меняются: синоним заменяется именем параметра, только если у
действия нет параметра с именем синонима, а сам параметр не передан. Подсказки (HINTS) ничего не
заменяют: они только называют параметр в did_you_mean.
"""
import difflib

_CELL = ('set_current_area', 'set_area_text', 'included_in_merged_area')
_AREA = ('get_area_text', 'get_current_area_text', 'text_within_area_bounds')
_READ = ('read_document', 'find_text')


def _address_for_read(value):
    """address у чтения документа: прямоугольник (с «:») — area, ячейка — start_address."""
    return 'area' if isinstance(value, str) and ':' in value else 'start_address'


# действие -> {синоним: параметр или функция значения -> параметр}
SYNONYMS = {
    **{a: {'area': 'address', 'cell': 'address'} for a in _CELL},
    **{a: {'address': 'area', 'range': 'area'} for a in _AREA},
    **{a: {'address': _address_for_read, 'range': 'area', 'cell': 'start_address'} for a in _READ},
    **{a: {'ref': 'root_ref', 'key': 'root_key'} for a in ('find_objects', 'find_object')},
}

# Подсказки без замены: имя, которое агенты путают, но по смыслу оно не всегда то же.
HINTS = {
    'goto_row': {'values': 'fields'},
    'activate_window': {'text': 'title', 'name': 'title'},
    'find_object': {'text': 'title'},
    'find_objects': {'text': 'title'},
}


def split_keys(keys):
    """keys строкой ("CTRL+S") -> список частей между «+»; пустые части отбрасываются."""
    if not isinstance(keys, str):
        return keys
    return [part.strip() for part in keys.split('+') if part.strip()]


def normalize(action, params, args):
    """(аргументы с каноническими именами, renamed). params — имена параметров действия."""
    out = dict(args)
    renamed = {}
    for alias, target in SYNONYMS.get(action, {}).items():
        if alias in params or alias not in out:
            continue
        name = target(out[alias]) if callable(target) else target
        if name not in params or name in out:
            continue        # и синоним, и параметр — синоним остаётся лишним аргументом
        out[name] = out.pop(alias)
        renamed[alias] = name
    if action == 'send_keys' and isinstance(out.get('keys'), str):
        out['keys'] = split_keys(out['keys'])
    return out, renamed


def did_you_mean(action, params, unexpected):
    """{лишний: параметр} по синонимам, подсказкам, затем по близости имени."""
    out = {}
    for name in unexpected:
        if not isinstance(name, str) or not name.isprintable():
            continue  # ключ ответа: toon_format не берёт в кавычки ключ с '\n' в конце
        guess = SYNONYMS.get(action, {}).get(name) or HINTS.get(action, {}).get(name)
        if callable(guess):
            guess = None
        if guess not in params:
            close = difflib.get_close_matches(str(name), sorted(params), 1, 0.6)
            guess = close[0] if close else None
        if guess is not None:
            out[name] = guess
    return out


def ref_actions(action, actions_with_ref, limit=5):
    """Близкие по имени действия, которые принимают ref, — для действия без ref."""
    return difflib.get_close_matches(action, sorted(actions_with_ref), limit, 0.5)
