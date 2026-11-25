"""Обратная связь проекта по testpilot (изменение testpilot-ui-feedback, матрица tasks.md п. 2):
`cls` именами типов платформы (object-search) и окно запущенного клиента развёрнуто
(client-launch-cli; изменение testpilot-maximize-optional — разворот только при TC1C_MAXIMIZE_WINDOW=true,
матрица его tasks.md п. 2). Требование action-effects (клик без повтора, группа без ожидания эффекта) —
tests/test_effects.py.

Записи (копии в tests/recordings/, байт в байт docs/spikes):
  docs/spikes/testpilot-helper-restore/recording/05-protocol-only.jsonl,
  docs/spikes/testpilot-helper-restore/recording/09-owner-closed.jsonl,
  docs/spikes/testpilot-helper-restore/recording/03-child-request.jsonl (spike:spk_cff9b4db89@v3) —
    ответы find_objects записанных форм: группы, кнопки, поля, декорации, таблица; фейковый поиск
    отвечает записанным списком, фильтр — настоящий (_find, _find_wait);
  docs/spikes/testpilot-maximized-window/recording/recording.txt (spike:spk_d1fe75e265@v1) — живая
    проверка флага процесса на WS с экраном 1024x768: без флага (случай 1, ps-normal) окно клиента
    0,9 1438x759 — шире экрана, IsZoomed=False; с STARTF_USESHOWWINDOW и wShowWindow=3 из Python
    Popen (случаи 4, 6, 10, py-max — «как будет testpilot») дочерний процесс получает dwFlags=1,
    wShowWindow=3, окно -8,-8 1040x784, IsZoomed=True. Числа в тестах — из этой записи.
Запуск клиента — tc_launch_client против фейков процесса, порта и изолированного рабочего стола.
"""
import inspect
import os
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _code_execution  # noqa: E402
import _helper_client as H  # noqa: E402
import _recording as recorded  # noqa: E402
import server as R  # noqa: E402

PLATFORM = H.calls(recorded.RESTORE_LIVE, 'get_active_window', 'startup')[0]['result']['platform_version']
FIELDS = ('key', 'handle', 'name', 'class', 'type', 'title')      # строка объекта ответа find_objects
FORMS = {  # записи find_objects: шаг → объекты формы (классы в списке)
    'request': H.calls(recorded.RESTORE_PROTOCOL, 'find_objects', 'child_run')[0]['result']['objects'],
    'error_window': H.calls(recorded.RESTORE_OWNER_CLOSED, 'find_objects', 'open')[0]['result']['objects'],
    'list': H.calls(recorded.RESTORE_CHILD_REQUEST, 'find_objects', 'child_after')[0]['result']['objects'],
}
ALIASES = {  # имя типа платформы → класс testpilot (требование «Класс по имени типа платформы»)
    'FormGroup': 'Group', 'ГруппаФормы': 'Group', 'FormButton': 'Button', 'КнопкаФормы': 'Button',
    'FormField': 'EditField', 'ПолеФормы': 'EditField', 'FormTable': 'Table', 'ТаблицаФормы': 'Table',
    'FormDecoration': 'Decoration', 'ДекорацияФормы': 'Decoration',
}


def rows(objects):
    """Объекты записи в строках ответа поиска: шесть полей строки и поля формы, когда они есть."""
    return [{**{k: o.get(k) for k in FIELDS}, **{f: o[f] for f in ('form_name', 'url', 'home_page', 'is_main') if f in o}}
            for o in objects]


@pytest.fixture
def find(monkeypatch):
    """Поиск по записанным объектам формы: клиент подключения, активное окно и нативный поиск — фейки,
    фильтры и диагностика — настоящие. Возвращает call(form, action, **args)."""
    monkeypatch.setattr(R, '_state', {'client': SimpleNamespace(platform_version=PLATFORM)})
    monkeypatch.setattr(R, '_window', lambda c: {'key': 'SecondaryFrame[root]'})
    monkeypatch.setattr(R, '_search_objects', lambda c, root=None: list(FORMS[find.form]))
    find.form = None

    def call(form, action='find_objects', **args):
        find.form = form
        return getattr(R, 'tc_' + action)(**args)
    return call


# ---------------------------------------------------------------- object-search
@pytest.mark.parametrize('form, alias, cls, count', [
    ('request', 'FormGroup', 'Group', 9), ('request', 'ГруппаФормы', 'Group', 9),
    ('request', 'FormButton', 'Button', 4), ('request', 'КнопкаФормы', 'Button', 4),
    ('request', 'FormField', 'EditField', 5), ('request', 'ПолеФормы', 'EditField', 5),
    ('error_window', 'FormGroup', 'Group', 7), ('error_window', 'FormDecoration', 'Decoration', 7),
    ('error_window', 'ДекорацияФормы', 'Decoration', 7),
    ('list', 'FormTable', 'Table', 1), ('list', 'ТаблицаФормы', 'Table', 1),
])
def test_platform_type_name_in_cls_finds_the_recorded_class(find, form, alias, cls, count):
    """«Имя типа платформы»: find_objects и find_object с cls=<имя типа> дают те же объекты записи,
    что cls=<класс>."""
    recorded_rows = rows([o for o in FORMS[form] if o['class'] == cls])
    assert len(recorded_rows) == count
    for action, field in (('find_objects', 'objects'), ('find_object', 'object')):
        by_alias, by_class = find(form, action, cls=alias), find(form, action, cls=cls)
        assert by_alias == by_class == {'ok': True, field: recorded_rows if field == 'objects' else recorded_rows[0]}


def test_unknown_class_is_empty_with_the_spelling_diagnostic(find):
    """«Неизвестный класс»: cls="Grup" — пустой результат и диагностика как прежде: класса нет
    в списке, сервер его не знает; имена, похожие на тип платформы, не сводятся."""
    out = find('request', cls='Grup')
    assert out == {'ok': True, 'objects': [], 'class_seen': False, 'class_known': False,
                   'classes_present': ['Button', 'EditField', 'Group', 'ManagedForm'],
                   'note': "nothing matched: class 'Grup' was not seen; and the server does not know it — "
                           'check the spelling'}


def test_diagnostics_of_a_missing_alias_name_the_reduced_class(find):
    """Диагностика пустого поиска видит сведённое имя: cls="FormDecoration" в форме без декораций —
    класс Decoration сервер знает, объекта нет."""
    out = find('list', cls='FormDecoration')
    assert out == {'ok': True, 'objects': [], 'class_seen': False, 'class_known': True, 'classes_present': ['Table'],
                   'note': "nothing matched: class 'Decoration' was not seen; the server knows it, "
                           'so the object may not have appeared yet'}


# ------------------------------------------- client-launch-cli (testpilot-maximize-optional)
STARTF_USESHOWWINDOW = 1   # winbase.h; запись: GetStartupInfo дочернего процесса — dwFlags=1 STARTF_USESHOWWINDOW=True
SW_MAXIMIZE = 3            # запись: wShowWindow=3 → окно -8,-8 1040x784 IsZoomed=True на экране 1024x768


class StartupInfo:
    """subprocess.STARTUPINFO (Windows): STARTUPINFOW для CreateProcess — dwFlags и wShowWindow."""
    def __init__(self):
        self.dwFlags, self.wShowWindow = 0, 0


class Process:
    pid = 4242
    returncode = None

    def poll(self):
        return self.returncode


class Port:
    """Порт тестового клиента: открыт сразу — проверяется только запуск процесса."""
    def settimeout(self, timeout):
        pass

    def connect_ex(self, address):
        return 0

    def close(self):
        pass


@pytest.fixture
def launch(monkeypatch, tmp_path):
    """tc_launch_client против фейков: процесс 1С, порт, обработка и изолированный рабочий стол;
    launch(**kw) вызывает его, popen — список (args, kwargs) вызовов Popen, isolated — аргументы IsolatedProcess."""
    exe = {name: tmp_path / name for name in ('1cv8', '1cv8c', '1cv8.exe', '1cv8c.exe')}
    for path in exe.values():
        path.write_bytes(b'')
    monkeypatch.setenv('DISPLAY', ':99')
    monkeypatch.delenv('TC1C_MAXIMIZE_WINDOW', raising=False)     # разворот выключен, пока тест не включит
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: Port())
    monkeypatch.setattr(_code_execution, 'launch_path', lambda *a, **k: None)
    monkeypatch.setattr(R, '_state', {'profile': 'ib'})
    launched = SimpleNamespace(popen=[], isolated=[])

    def popen(args, **kwargs):
        launched.popen.append((args, kwargs))
        return Process()
    monkeypatch.setattr(subprocess, 'Popen', popen)
    monkeypatch.setitem(sys.modules, '_desktop_windows',
                        SimpleNamespace(IsolatedProcess=lambda args: launched.isolated.append(args) or Process()))

    def launch(**kw):
        kw.setdefault('desktop', 'default')
        return inspect.unwrap(R.tc_launch_client)(base='exts-dev-ib', port=48101, server=True, user='Администратор',
                                                  wait=90, connect=False,
                                                  exe=str(exe['1cv8.exe' if os.name == 'nt' else '1cv8c']), **kw)
    return launch, launched


def windows(monkeypatch):
    """Windows для tc_launch_client: os.name='nt' и subprocess.STARTUPINFO (на Linux его нет)."""
    monkeypatch.setattr(os, 'name', 'nt')
    monkeypatch.setattr(subprocess, 'STARTUPINFO', StartupInfo, raising=False)
    monkeypatch.setattr(subprocess, 'STARTF_USESHOWWINDOW', STARTF_USESHOWWINDOW, raising=False)


def test_windows_client_is_launched_maximized_when_TC1C_MAXIMIZE_WINDOW_is_true(launch, monkeypatch):
    """«Сохранённый размер шире экрана» (запись спайка): при TC1C_MAXIMIZE_WINDOW=true на Windows процесс
    клиента создаётся с STARTF_USESHOWWINDOW и wShowWindow=SW_MAXIMIZE — теми dwFlags=1, wShowWindow=3,
    что разворачивают окно (1040x784 на экране 1024x768) вместо сохранённых 1438 px."""
    windows(monkeypatch)
    monkeypatch.setenv('TC1C_MAXIMIZE_WINDOW', 'true')
    launch, launched = launch
    result = launch()
    assert result['ok'] and result['pid'] == Process.pid and result['desktop'] == 'default'
    [(args, kwargs)], isolated = launched.popen, launched.isolated
    assert isolated == []
    assert args[0].endswith('1cv8.exe') and args[1] == 'ENTERPRISE' and '/TESTCLIENT' in args
    info = kwargs['startupinfo']
    assert isinstance(info, StartupInfo)
    assert (info.dwFlags, info.wShowWindow) == (STARTF_USESHOWWINDOW, SW_MAXIMIZE)


@pytest.mark.parametrize('value', [None, 'false'], ids=['unset', 'false'])
def test_windows_client_is_launched_without_the_window_flag_by_default(launch, monkeypatch, value):
    """«Разворот выключен по умолчанию»: TC1C_MAXIMIZE_WINDOW не задан или false — на Windows процесс
    запускается без флага окна (запись, случай 1 ps-normal: без флага окно приходит в сохранённом размере
    1438x759, шире экрана 1024x768; развёрнутый клиент блокировал ввод на WS — потому разворот выключен)."""
    windows(monkeypatch)
    if value is not None:
        monkeypatch.setenv('TC1C_MAXIMIZE_WINDOW', value)
    launch, launched = launch
    result = launch()
    assert result['ok'] and result['desktop'] == 'default'
    [(_, kwargs)], isolated = launched.popen, launched.isolated
    assert isolated == []
    assert 'startupinfo' in kwargs and kwargs['startupinfo'] is None


def test_client_without_startupinfo_is_launched_without_the_window_flag(launch, monkeypatch):
    """«Не Windows»: без subprocess.STARTUPINFO процесс запускается без флага окна — даже при
    TC1C_MAXIMIZE_WINDOW=true."""
    monkeypatch.delattr(subprocess, 'STARTUPINFO', raising=False)
    monkeypatch.setenv('TC1C_MAXIMIZE_WINDOW', 'true')
    launch, launched = launch
    result = launch()
    assert result['ok']
    [(_, kwargs)] = launched.popen
    assert 'startupinfo' in kwargs and kwargs['startupinfo'] is None


def test_isolated_desktop_launch_is_unchanged(launch, monkeypatch):
    """Запуск на изолированном рабочем столе не меняется и при TC1C_MAXIMIZE_WINDOW=true: IsolatedProcess
    получает командную строку, Popen с флагом окна не вызывается."""
    windows(monkeypatch)
    monkeypatch.setenv('TC1C_MAXIMIZE_WINDOW', 'true')
    launch, launched = launch
    result = launch(desktop='isolated')
    assert result['ok'] and result['desktop'] == 'isolated'
    [args], popen = launched.isolated, launched.popen
    assert popen == []
    assert args[0].endswith('1cv8.exe')
    assert args[1:] == ['ENTERPRISE', '/Sexts-dev-ib', '/TESTCLIENT', '-TPort48101', '/DisableStartupMessages',
                        '/NАдминистратор']
