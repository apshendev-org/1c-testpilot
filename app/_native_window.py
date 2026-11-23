"""Recover the launched client's active secondary window outside the 1C object tree."""
import ctypes
from ctypes import wintypes
import time
import win32gui
import win32process


class _GUIThreadInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                ('rcCaret', wintypes.RECT)]


def active_secondary_window(pid):
    if not pid:
        return None
    get_info = ctypes.windll.user32.GetGUIThreadInfo
    get_info.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUIThreadInfo)]
    get_info.restype = wintypes.BOOL
    found = []
    def inspect(hwnd, _):
        thread, owner = win32process.GetWindowThreadProcessId(hwnd)
        if owner != pid or not win32gui.IsWindowVisible(hwnd):
            return
        cls = win32gui.GetClassName(hwnd)
        # На 8.5 суффикс класса меняется при каждом запуске. Вторичное окно имеет
        # владельца в том же процессе и рамку с заголовком; главное окно владельца не имеет.
        owner_hwnd = win32gui.GetWindow(hwnd, 4)  # GW_OWNER
        style = win32gui.GetWindowLong(hwnd, -16) & 0xffffffff
        is_modern_secondary = (cls.startswith('V8Window0.') and owner_hwnd and
                               win32process.GetWindowThreadProcessId(owner_hwnd)[1] == pid and
                               style & 0x00c00000 == 0x00c00000 and not style & 0x40000000)
        if cls != 'V8TopLevelFrameSDIsec' and not is_modern_secondary:
            return
        info = _GUIThreadInfo(cbSize=ctypes.sizeof(_GUIThreadInfo))
        if get_info(thread, ctypes.byref(info)) and info.hwndActive == hwnd:
            found.append({'hwnd': hwnd, 'pid': pid, 'title': win32gui.GetWindowText(hwnd)})
    try:
        win32gui.EnumWindows(inspect, None)
    except win32gui.error:
        return None
    return found[0] if len(found) == 1 else None


# shortcut: заголовок русской платформы 8.3.27 (spike:spk_13e59c8b2b@v1); английский добавить, когда встретится живьём.
LOGIN_TITLES = ('Доступ к информационной базе',)
# Отказ до сеанса (нет прав на запуск клиента): окно сообщения поверх заставки, главного окна нет (spike:spk_13e59c8b2b@v2).
SPLASH_TITLES = ('Загрузка конфигурационной информации...',)
STARTUP_ERROR_CLASS = 'V8NewLocalFrameBaseWnd'


def refusal(windows):
    """Заголовок окна отказа входа среди видимых верхних окон процесса ({class, title, owner}) или None."""
    for w in windows:
        if not w['owner'] and w['title'] in LOGIN_TITLES:
            return w['title']
    splash = any(w['class'] == 'V8TopLevelFrameSDI' and w['title'] in SPLASH_TITLES for w in windows)
    main = any(w['class'] == 'V8TopLevelFrameSDI' and w['title'] not in SPLASH_TITLES for w in windows)
    if splash and not main:
        for w in windows:
            if w['class'] == STARTUP_ERROR_CLASS and w['owner']:
                return w['title']
    return None


def login_dialog(pid):
    """Заголовок окна отказа входа процесса pid или None: окно входа в базу или ошибка старта поверх заставки."""
    windows = []
    def inspect(hwnd, _):
        if win32process.GetWindowThreadProcessId(hwnd)[1] == pid and win32gui.IsWindowVisible(hwnd):
            windows.append({'class': win32gui.GetClassName(hwnd), 'title': win32gui.GetWindowText(hwnd),
                            'owner': win32gui.GetWindow(hwnd, 4)})  # 4 = GW_OWNER
    try:
        win32gui.EnumWindows(inspect, None)
    except win32gui.error:
        return None
    return refusal(windows)


def close_secondary_window(window):
    current = active_secondary_window(window['pid'])
    if current is None or current['hwnd'] != window['hwnd']:
        return False
    try:
        win32gui.PostMessage(current['hwnd'], 0x0010, 0, 0)
        for _ in range(40):
            if not win32gui.IsWindow(current['hwnd']):
                return True
            time.sleep(.05)
    except win32gui.error:
        return False
    return False
