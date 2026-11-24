"""Клиент 1С с обработкой Testpilot для тестов исполнения через форму Request — по записям спайка
testpilot-helper-restore (spike:spk_cff9b4db89@v3): docs/spikes/testpilot-helper-restore/recording/, копии —
tests/recordings/.

Из записи: ключи окон Helper и Request (эхо-ключ кадра CLICK, find_objects окна Request), окна и их порядок
(get_active_window), ответы протокола — CLICK (opcode 66, ok), ввод в поле (ok, target_check present), чтение
поля (ok, presentation), окно, которое открывает код (08), отказ CLICK при модальном окне (07: OperationError,
статус 9). Из исходников обработки (_forms.py): состав элементов Helper и Request — в записи спайка форма
Request ещё копия разметки Helper (поле ClientRequest), кнопка Helper зовётся RunServer.

Модель: кнопка OpenRequest Helper (CLICK, действие и фиксация) открывает окно Request записи, оно активно;
RunClient/RunServer в Request выполняют введённый запрос — только код спайков (spike_helper_restore.py:
ОткрытьФорму открывает окно формы списка записи 08, АктивноеОкно().Заголовок — заголовок активного окна;
check_request_form.py: ОткрытьФорму… Результат = Истина, закрытие формы-владельца «Информация при запуске»,
запрос названия подразделения — «Администрация») или запрос «ВЫБРАТЬ 1 КАК А» (запись 10); Helper пишет конверт продукта (Module.bsl, ВыполнитьЗапросСервиса:
protocol, request_id, ok, result) в своё поле ответа, Request закрывается — активен владелец. Всё, что
отправляет testpilot, — журнал frames (guid, ключ, вид кадра), inputs (текст ввода), reads, closes, activated.
"""
import html
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _forms  # noqa: E402
import _recording as recorded  # noqa: E402
import _code_execution as E  # noqa: E402
import guids as G  # noqa: E402
import tc1c  # noqa: E402

HELPER_NAME = 'ВнешняяОбработка.Testpilot.Форма.Helper'
REQUEST_NAME = 'ВнешняяОбработка.Testpilot.Форма.Request'
HELPER_TITLE = 'Testpilot: Helper'          # slow-start.jsonl: окно SecondaryFrame «Testpilot: Helper»
# Код спайков в Request: spike_helper_restore.py (CHILD_CODE, OPEN_FORM_CODE; длины ввода в записях 48 и 102 —
# <pre>…</pre> с этими текстами) и check_request_form.py (живая проверка кода ветки, запись 10).
CHILD_CODE = 'Результат = АктивноеОкно().Заголовок;'
OPEN_FORM_CODE = 'ОткрытьФорму("Справочник.Подразделения.ФормаСписка");\nРезультат = АктивноеОкно().Заголовок;'
OPEN_FORM_TRUE_CODE = 'ОткрытьФорму("Справочник.Подразделения.ФормаСписка");\nРезультат = Истина;'
# Код закрывает форму «Информация при запуске» — владельца Request (сценарий «Код закрывает форму-владельца»).
CLOSE_OWNER_CODE = '''Закрыто = 0;
Для Каждого Ок Из ПолучитьОкна() Цикл
	Для Каждого Ф Из Ок.Содержимое Цикл
		Если СтрНайти(Ф.ИмяФормы, Параметры["part"]) > 0 Тогда
			Ф.Закрыть();
			Закрыто = Закрыто + 1;
		КонецЕсли;
	КонецЦикла;
КонецЦикла;
Результат = Закрыто;'''
DEPT_CODE = '''Запрос = Новый Запрос("ВЫБРАТЬ ПЕРВЫЕ 1 Т.Наименование КАК Имя ИЗ Справочник.Подразделения КАК Т
|ГДЕ НЕ Т.ПометкаУдаления УПОРЯДОЧИТЬ ПО Т.Наименование");
В = Запрос.Выполнить().Выбрать();
Результат = ?(В.Следующий(), В.Имя, "");'''          # следующее исполнение после закрытия владельца — «Администрация»
QUERY = 'ВЫБРАТЬ 1 КАК А'                    # check_request_form.py: execute_query публичным инструментом
# Запись 10, work_form: ответ execute_query — конверт ВыполнитьЗапрос (columns, rows, returned_rows, limit, truncated).
QUERY_RESULT = {'columns': ['А'], 'rows': [{'А': 1}], 'returned_rows': 1, 'limit': 100, 'truncated': False}
# Helper, ПриСозданииНаСервере: конверты полей до первого запроса.
READY = json.dumps({'protocol': 1, 'request_id': '', 'ok': True, 'status': 'ready'})
INFO = json.dumps({'protocol': 1, 'request_id': '', 'ok': True, 'functions': [],
                   'capabilities': 'metadata,tester_metadata,custom_functions,form_context,form_details,'
                                   'table_selection,form_state'.split(',')})
ROOT = object()


def raw(path, button=None, step=None):
    """Строки raw_click записи: CLICK кнопки, ввод в поле или чтение поля протоколом."""
    return [r for r in recorded.rows(path, kind='raw_click')
            if button in (None, r['button']) and step in (None, r['step'])]


def calls(path, action, step=None):
    """Вызовы testpilot записи (ответ живого клиента) по действию и шагу."""
    return [r for r in recorded.rows(path, kind='call', step=step) if r['action'] == action]


def clicked_key(row):
    """Эхо-ключ кадра в ответе действия CLICK — ключ кнопки, которую нажал спайк."""
    return next(value for tag, value in row['result']['replies'][0]['values'] if tag == 'str')


def split_form(key):
    """Ключ элемента → (окно, guid формы, имя элемента)."""
    window, rest = key.split('.ManagedForm[')
    form, item = rest.split('].', 1)
    return window, form, item


def payload(text):
    """Текст ввода <pre>…</pre> → запрос testpilot (JSON)."""
    return json.loads(html.unescape(text.removeprefix('<pre>').removesuffix('</pre>')))


class Facts:
    """Факты одной записи: ключи Helper и Request, объекты окна Request, активные окна по шагам, ответы протокола."""

    def __init__(self, path, *, opened, run):
        self.path = path
        helper = split_form(clicked_key(raw(path, step=opened)[0]))
        self.helper_window, self.helper_form = helper[0], helper[1]
        found = next(r for r in calls(path, 'find_objects', run) if 'root_key' in r['args'])
        self.request_objects = found['result']['objects']
        self.request_window = found['args']['root_key']
        self.request_form = next(o for o in self.request_objects if o['class'] == 'ManagedForm')['name']
        self.windows = [(r['step'], recorded.window(r)) for r in calls(path, 'get_active_window')]
        self.click = raw(path, step=opened)[0]['result']['replies']       # [действие, фиксация]: opcode 66, ok
        self.input = next(r for r in raw(path, step=run) if r['input'])['result']['replies'][0]
        self.read = next((r['result']['replies'][0] for r in raw(path, step=run) if r['button'] == 'ClientResult'), None)

    def window(self, step, title, index=0):
        """Активное окно шага записи по заголовку (и порядковому номеру среди окнов с этим заголовком)."""
        return [w for s, w in self.windows if s == step and w.get('title') == title][index]


PROTOCOL = Facts(recorded.RESTORE_PROTOCOL, opened='child_open', run='child_run')       # 05, restore-4c
READ_RESULT = Facts(recorded.RESTORE_READ_RESULT, opened='child_open', run='child_run')  # 06, restore-5
OPEN_FORM = Facts(recorded.RESTORE_OPEN_FORM, opened='open_form', run='open_form')      # 08, restore-7
CHOICE = 'Подразделения'                                   # форма выбора из ячейки R3C9 макета АРМ КС
ARM = 'АРМ контрактной службы (макет)'                     # рабочая форма макета
REQUEST = 'Testpilot: запрос: Request'                     # окно Request: заголовок формы + имя формы
# Запись 05, start: после закрытия окна «Информация при запуске» активно окно обработки — для агента рабочего окна нет.
NO_WORK = recorded.window(calls(recorded.RESTORE_PROTOCOL, 'get_active_window', 'start')[0])


def window_by_title(path, step, title, index=0):
    """Активное окно шага записи по заголовку (и номеру среди опросов с этим заголовком)."""
    found = [recorded.window(r) for r in calls(path, 'get_active_window', step)
             if recorded.window(r).get('title') == title]
    return found[index]


# Запись 10 — живая проверка кода ветки публичными инструментами (check_request_form.py): окна шагов.
# Ключи окон Helper и Request публичные инструменты не показывают — их клиент берёт из записи 05.
LIVE_INFO = window_by_title(recorded.RESTORE_LIVE, 'startup', 'Информация')            # «Информация при запуске»
LIVE_ARM = window_by_title(recorded.RESTORE_LIVE, 'open', ARM)
LIVE_LIST = window_by_title(recorded.RESTORE_LIVE, 'open_form', 'Подразделения')       # форма списка из кода
LIVE_CHOICE = window_by_title(recorded.RESTORE_LIVE, 'choice_from_cell', CHOICE)
LIVE_QUESTION = window_by_title(recorded.RESTORE_LIVE, 'question', '1С:Предприятие')   # вопрос «Да/Нет»
LIVE_ERROR = window_by_title(recorded.RESTORE_LIVE, 'error', '1С:Предприятие')         # окно ошибки 1С
# Запись 07 — вопрос и окно ошибки для протокола: CLICK по кнопке Helper отклонён.
MODAL_QUESTION = window_by_title(recorded.RESTORE_MODAL, 'question_new', '1С:Предприятие')
MODAL_ERROR = window_by_title(recorded.RESTORE_MODAL, 'error_new', '1С:Предприятие')
MODAL_ARM = window_by_title(recorded.RESTORE_MODAL, 'error_new', ARM, 1)


class Client:
    """Клиент 1С с обработкой Testpilot: кадры протокола журналирует, отвечает записанным.

    active — ключ активного окна (из окон записи, show(); None — активного окна нет); после закрытия Request платформа
    делает активным её владельца — окно, активное при открытии (запись 05). modal: клиент отклоняет CLICK (запись 07)."""

    def __init__(self, facts, *, active, owner=None, modal=False):
        self.facts = facts
        items = {name: name for name, *_ in _forms.items('Helper')}
        self.helper_objects = _forms.objects(facts.helper_window, facts.helper_form, HELPER_NAME, HELPER_TITLE,
                                             'Helper', handles=items)
        handles = {o['name']: o['handle'] for o in facts.request_objects if o.get('name')}
        handles['Request'] = handles.get('ClientRequest')   # запись: поле ввода Request — копия ClientRequest Helper
        self.request_objects = _forms.objects(facts.request_window, facts.request_form, REQUEST_NAME, REQUEST,
                                              'Request', handles=handles)
        self.windows, self.opened = {}, {}       # ключ → окно (get_active_window); ключ → объекты прочих открытых окон
        self.owner, self.modal = owner or active, modal
        self._active, self.history = None, []
        self.active = active
        self.results = {'ClientResult': READY, 'ServerResult': READY}
        self.text = None                         # текст в поле Request
        self.frames, self.inputs, self.reads, self.closes, self.activated = [], [], [], [], []
        self.stall, self.break_input, self.refuse_activation = False, False, set()
        self._pending, self._service_pending, self._track, self._io_deadline, self._max_action_time = False, None, None, None, None
        self._request_windows, self._service_roots, self._service_checked_windows = set(), set(), set()

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, key):
        self._active = key
        self.history.append(key)

    def show(self, window):
        self.windows[window['key']] = window

    def open_objects(self, key, objects):
        self.opened[key] = objects

    # Чтения runtime, идущие в клиент по протокому: ответы — записанной формы.
    def window(self):
        return dict(NO_WORK) if self._active is None else dict(self.windows[self._active])

    def search(self, root):
        if root is not ROOT:
            return self.objects(root)
        return self.objects(self.facts.helper_window) + [o for objects in self.opened.values() for o in objects]

    def objects(self, key):
        return list(self.helper_objects) if key == self.facts.helper_window else list(self.opened.get(key, ()))

    def presentation(self, key, handle):
        self.reads.append(key)
        return {'ok': True, 'presentation': self.results.get(handle) or INFO}

    def input(self, key, handle, html):
        if self.break_input:
            raise TimeoutError('The connection closed.')   # обрыв связи на вводе: Request открыта, запроса нет
        self.inputs.append(html)
        self.text = payload(html)
        return dict(self.facts.input, target=key, len=len(html))

    def close(self, key):
        self.closes.append(key)
        self.opened.pop(key, None)
        if self._active == key:
            self.active = self.owner
        return {'ok': True, 'closed': key}                  # запись 07: close_window → closed

    def _resync(self):
        self.resyncs += 1

    def send_cmd(self, guid, key, kind='read', middle=b'', handle=None, **kw):
        self.frames.append((guid, key, kind))
        if guid == G.GET_ACTIVE_WINDOW:
            return {'ok': True, 'raw': self._active}        # _runtime._window читает ключ из raw
        if guid == G.ACTIVATE:
            if key in self.refuse_activation:              # окно старта отказывает в активации — как запись 07 (статус 9)
                raise tc1c.OperationError(9, key)
            if kind == 'commit':                             # фиксация активации
                self.activated.append(key)
                self.active = key.split('.ManagedForm[', 1)[0]
            return {'ok': True}
        if guid != G.CLICK:
            return {'ok': True}
        if self.modal:
            # Запись 07: «The action is unavailable in the current form state…», статус 9 (target_not_interactive).
            raise tc1c.OperationError(9, key)
        if kind == 'commit':
            self.pressed(key.rsplit('[', 1)[1][:-1])
        return {k: v for k, v in self.facts.click[0].items() if k != 'values'}   # opcode 66, ok

    def pressed(self, name):
        if name == 'OpenRequest':
            self.opened[self.facts.request_window] = self.request_objects
            self.owner = self._active                      # владелец — форма активного окна (ОткрытьЗапрос)
            self.active = self.facts.request_window       # запись 05: после CLICK активно окно Request
        elif name in ('RunClient', 'RunServer'):
            if self.stall:                                # «Выполнить» не ответило к сроку — исполнение идёт
                raise TimeoutError('The deadline expired.')
            request = self.text
            result = self.run(request)
            field = 'ClientResult' if name == 'RunClient' else 'ServerResult'
            self.results[field] = json.dumps({'protocol': E.PROTOCOL, 'request_id': request['request_id'],
                                              'ok': True, 'result': result})
            # «Выполнить» закрывает Request, если код не закрыл её вместе с владельцем (Module.bsl: Открыта()).
            self.opened.pop(self.facts.request_window, None)
            if self._active == self.facts.request_window:
                self.active = self.owner                  # запись 05: после «Выполнить» активен владелец

    def run(self, request):
        """Запрос, как его выполняет Helper (Module.bsl): только код спайков из записей и запрос одной строки."""
        if request['mode'] == 'query':
            assert request['query'] == 'ВЫБРАТЬ РАЗРЕШЕННЫЕ 1 КАК А', request['query']   # prepare_query
            return dict(QUERY_RESULT)
        code = request['code']
        if code == DEPT_CODE:
            return 'Администрация'                        # запись 10, startup
        if code == CLOSE_OWNER_CODE:
            # Запись 10: код закрыл форму «Информация» — владельца Request; Request закрылась вместе с ней,
            # Helper успел записать ответ (1), окна ошибки нет, активного рабочего окна нет.
            self.windows.pop(self.owner, None)
            self.opened.pop(self.facts.request_window, None)
            self.active = None
            return 1
        result = None
        for statement in code.split('\n'):
            if statement == 'ОткрытьФорму("Справочник.Подразделения.ФормаСписка");':
                self.active = self.list_window            # записи 08, 10: форма списка открыта и активна
            elif statement == CHILD_CODE:
                result = self.windows[self._active]['title']
            elif statement in ('Результат = Истина;', 'Результат = 1;', 'Результат = 2;'):
                result = {'Результат = Истина;': True, 'Результат = 1;': 1, 'Результат = 2;': 2}[statement]
            else:
                raise AssertionError('код спайков в записях не встречался: ' + statement)
        return result

    list_window = None   # окно, которое открывает ОткрытьФорму (записи 08, 10), — задаёт тест


def runtime(client):
    """Действия runtime на клиенте-заглушке: чтения и ввод, которыми пользуется execute."""
    return SimpleNamespace(_state={}, _APPLICATION_ROOT=ROOT,
                           _window=lambda c: client.window(),
                           _search_objects=lambda c, root=None: client.search(root),
                           tc_get_data_presentation=client.presentation,
                           tc_input_html=client.input,
                           tc_close_window=client.close)


def execute(client, **arguments):
    arguments = dict(mode='code', context='client', timeout=5, check_permissions=False) | arguments
    return E.execute(runtime(client), client, **arguments)


def frames(client, guid):
    """Кадры метода, ушедшие в клиент: [(имя элемента, вид кадра)]."""
    return [(key.rsplit('[', 1)[1][:-1], kind) for g, key, kind in client.frames if g == guid]
