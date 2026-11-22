import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contains_every_app_module(tmp_path):
    """Новый модуль app/ без записи в py-modules pyproject.toml не попадает в wheel.

    Wheel собирается из sdist: устаревший build/lib дерева не подмешивает файлы."""
    subprocess.run(['uv', 'build', '--out-dir', str(tmp_path), str(ROOT)],
                   check=True, capture_output=True)
    wheel, = tmp_path.glob('*.whl')
    packaged = set(zipfile.ZipFile(wheel).namelist())
    missing = sorted(p.name for p in (ROOT / 'app').glob('*.py') if p.name not in packaged)
    assert missing == []
