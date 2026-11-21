"""С Linux: TCP до порта тест-клиента на WS, рукопожатие (анонимный NTLM без SSPI) и одно действие."""
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'app'))
host, port = sys.argv[1], int(sys.argv[2])
no_sspi = '--no-sspi' in sys.argv   # путь Linux: SSPI нет, только анонимный NTLM

t = time.monotonic()
with socket.create_connection((host, port), timeout=5):
    print(f'tcp ok {time.monotonic() - t:.3f}s')

import tc1c  # noqa: E402
from testpilot import ActionError, Client  # noqa: E402

if no_sspi:
    tc1c.sspi = None
print('sspi used:', tc1c.sspi is not None)
client = Client()
t = time.monotonic()
try:
    print('connect:', client.connect(host=host, port=port), f'{time.monotonic() - t:.1f}s')
    window = client.call('get_active_window', check=False)
    print('active window:', {k: window.get(k) for k in ('ok', 'title', 'code', 'error')})
except ActionError as exc:
    print('ActionError:', exc.result)
finally:
    client.close()
