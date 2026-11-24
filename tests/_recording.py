"""Загрузчик записи спайка testpilot-report-recording: ответы живого клиента 1С для заглушек тестов.

Запись — JSONL обмена agent↔proxy сеанса MCP testpilot на WS (строка {ms, dir, msg}); ответ
инструмента — текст result.content[0].text строками «ключ: значение». MCP адресует элементы ref;
Client.call и действия runtime получают те же ответы с key/handle вместо ref (перевод ref ↔ key
в _runtime.py). По умолчанию — docs/spikes/testpilot-report-recording/recording/report-date-droplist.jsonl;
записи спайка goto-row (docs/spikes/testpilot-goto-row-list-load/recording/) — по имени ниже.
"""
import json
import re
from pathlib import Path

# Копии записей рядом с тестами: testpilot уходит в форк 1c-testpilot без docs/ кита; совпадение проверяет
# payload/tests/test_spike_recordings.py.
RECORDINGS = Path(__file__).resolve().parent / 'recordings'
RECORDING = RECORDINGS / 'report-date-droplist.jsonl'
# Прогон 2 спайка goto-row: список открыт до фикстуры, execute_command возвращает то же окно.
STALE_WINDOW = RECORDINGS / 'goto-row-stale-window.jsonl'
# Прогон 3: то же + чтение кнопки ФормаОбновить и её нажатие (список обновился).
REFRESH = RECORDINGS / 'goto-row-refresh.jsonl'
# Прогон 1: фикстура создаёт документ, затем первое открытие списка — окно новое.
FIXTURE = RECORDINGS / 'goto-row-fixture.jsonl'
PRELOADED = RECORDINGS / 'goto-row-preloaded.jsonl'
# Спайк testpilot-cell-edit: testpilot вызывался из Python напрямую (Client.call), ответ — dict.
CELL_EDIT = RECORDINGS / '01-cell-edit.jsonl'
NO_WORK_WINDOW = RECORDINGS / '02-no-work-window.jsonl'
CHOICE_FROM_CELL = RECORDINGS / '03-choice-from-cell.jsonl'


def _indent(line):
    return len(line) - len(line.lstrip(' '))


def _scalar(text):
    """Значение строки «ключ: значение»: true/false/null, кавычки снимаются."""
    if text == 'true':
        return True
    if text == 'false':
        return False
    if text == 'null':
        return None
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1].replace('\\"', '"')
    return text


def _rename_refs(value):
    """ref → key в разобранном ответе, на любой глубине."""
    if isinstance(value, dict):
        return {('key' if k == 'ref' else k): _rename_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rename_refs(v) for v in value]
    return value


def _block(lines, level):
    """Строки с отступом не меньше level как dict «ключ: значение». Блок глубже — вложенное значение;
    «item[N]{колонки}:» — список строк-словарей по колонкам. Возвращает (dict, число строк)."""
    result, i = {}, 0
    while i < len(lines):
        if _indent(lines[i]) < level:
            break
        key, _, body = lines[i].strip().partition(':')
        key, body = key.strip(), body.strip()
        item = re.fullmatch(r'(\w+)\[\d+\]\{(.*)\}', key)
        if not body and i + 1 < len(lines) and _indent(lines[i + 1]) > level:
            if item:
                columns = [c.strip() for c in item.group(2).split(',')]
                rows, i = [], i + 1
                while i < len(lines) and _indent(lines[i]) > level:
                    cells = [_scalar(c.strip()) for c in lines[i].strip().split(',')]
                    rows.append(dict(zip(columns, cells)))
                    i += 1
                result[item.group(1)] = rows
            else:
                result[key], consumed = _block(lines[i + 1:], level + 1)
                i += 1 + consumed
        else:
            result[key] = _scalar(body)
            i += 1
    return result, i


def _parse(text):
    """Текст ответа testpilot как dict, с ref → key."""
    value, _ = _block([line for line in text.splitlines() if line.strip()], 0)
    return _rename_refs(value)


def exchange(path=RECORDING):
    """Запись как последовательность вызовов инструментов: {tool, action, arguments, response}."""
    pending, calls = {}, []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        msg = json.loads(line).get('msg')
        if not isinstance(msg, dict):
            continue                     # этап прогона: {ms, dir: "note", note}
        if msg.get('method') == 'tools/call':
            pending[msg['id']] = msg['params']
        elif 'result' in msg and msg.get('id') in pending:
            params = pending.pop(msg['id'])
            calls.append({'tool': params['name'], 'action': params['arguments'].get('action'),
                          'arguments': params['arguments'],
                          'response': _parse(msg['result']['content'][0]['text'])})
    return calls


def responses(action, path=RECORDING):
    """Ответы записи для действия runtime (Client.call) в порядке записи, уже с key вместо ref."""
    return [call['response'] for call in exchange(path) if call['action'] == action]


def direct(path, step=None, action=None):
    """Вызовы testpilot напрямую из записи спайка cell-edit (строка {step, kind: "call", action, args,
    result}): {step, action, arguments, response} в порядке записи; step и action — отбор."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    return [dict(step=row['step'], action=row['action'], arguments=row.get('args') or {}, response=row['result'])
            for row in rows if row.get('kind') == 'call'
            and (step is None or row['step'] == step) and (action is None or row['action'] == action)]
