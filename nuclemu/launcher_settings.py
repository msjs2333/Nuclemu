"""User preferences read only by the desktop launcher."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class LauncherSettings:
    port: int = 0
    open_browser: bool = False

    def __post_init__(self):
        if type(self.port) is not int or not 0 <= self.port <= 65535:
            raise ValueError('端口须为 0（自动）或 1–65535 的整数。')
        if type(self.open_browser) is not bool:
            raise ValueError('自动打开浏览器须为布尔值。')


def _path(path):
    return Path.home() / '.nuclemu' / 'launcher.json' if path is None else Path(path)


def load_settings(path=None):
    """Return defaults only for a missing file; leave damaged files untouched."""
    target = _path(path)
    try:
        text = target.read_text(encoding='utf-8')
    except FileNotFoundError:
        return LauncherSettings()
    except UnicodeError as error:
        raise ValueError(f'启动器设置无效（{target}）：不是 UTF-8 文件。请在设置中保存有效值以恢复。') from error
    except OSError as error:
        raise OSError(f'无法读取启动器设置（{target}）：{error}') from error
    try:
        value = json.loads(text)
        if not isinstance(value, dict) or value.keys() != {'port', 'open_browser'}:
            raise ValueError('须包含 port 和 open_browser 两项设置。')
        return LauncherSettings(**value)
    except ValueError as error:
        raise ValueError(f'启动器设置无效（{target}）：{error} 请在设置中保存有效值以恢复。') from error


def save_settings(settings: LauncherSettings, path=None):
    """Replace the file after a complete write; callers save only on acceptance."""
    if not isinstance(settings, LauncherSettings):
        raise TypeError('settings must be LauncherSettings')
    target = _path(path)
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=target.parent, prefix=f'.{target.name}.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(asdict(settings), stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as error:
        raise OSError(f'无法保存启动器设置（{target}）：{error}；原设置文件保持不变。') from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
