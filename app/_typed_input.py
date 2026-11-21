"""input_text verification by the field value type read through the Testpilot processing."""
import datetime
import re
from decimal import Decimal, InvalidOperation

_TRUE = ('да', 'истина', 'true', 'yes')
_FALSE = ('нет', 'ложь', 'false', 'no')


def _number(text, separators):
    separators = separators if isinstance(separators, dict) else {}
    fraction = separators.get('Fractions') or ','
    group = separators.get('Groups') or ' '
    cleaned = text.strip()
    for space in {group, ' ', ' ', ' '}:
        if space:
            cleaned = cleaned.replace(space, '')
    if fraction != '.':
        if '.' in cleaned and fraction in cleaned:
            return None
        cleaned = cleaned.replace(fraction, '.')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', cleaned):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _date_order(sample):
    """Indexes of day, month and year in the session date format (sample is 22.11.2004 17:48:59)."""
    groups = re.findall(r'\d+', sample or '')
    try:
        return groups.index('22'), groups.index('11'), groups.index('2004')
    except ValueError:
        return 0, 1, 2


def _date(text, sample):
    groups = [int(g) for g in re.findall(r'\d+', text)]
    if len(groups) not in (3, 5, 6):
        return None
    day, month, year = (groups[i] for i in _date_order(sample))
    if year < 100:
        year += 2000
    try:
        return datetime.datetime(year, month, day, *groups[3:6])
    except ValueError:
        return None


def matches(kind, text, value, service=None):
    """Whether the entered text denotes the field value; exact text equality for unknown kinds."""
    service = service or {}
    if kind == 'number':
        wanted = _number(text, service.get('separators'))
        return wanted is not None and not isinstance(value, bool) and wanted == Decimal(str(value))
    if kind == 'date':
        wanted = _date(text, service.get('date_sample'))
        try:
            actual = datetime.datetime.fromisoformat(value['value'])
        except (KeyError, TypeError, ValueError):
            return False
        return wanted is not None and wanted == actual
    if kind == 'boolean':
        word = text.strip().casefold()
        return (word in _TRUE and value is True) or (word in _FALSE and value is False)
    if kind == 'string':
        return value == text
    return None


def field_value(S, c, key):
    """(kind, value) of an input field through form_state, or (None, None) without the helper."""
    form = S._batches.owner(S, key)
    name = S._collection.object_name(key)
    if not form or not name:
        return None, None
    try:
        state = S._code_execution.form_state(S, c, form, [name])
    except S._code_execution.Failure:
        return None, None
    if not state or not state.get('found') or name not in state['values']:
        return None, None
    value = state['values'][name]
    return S._code_execution.value_kind(value), value


def service(c):
    return vars(c).get('_testpilot_service') or {}
