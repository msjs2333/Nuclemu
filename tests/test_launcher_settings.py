"""Preferences persist only on explicit save and never leak into web CLI modes."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nuclemu.launcher_settings import LauncherSettings, load_settings, save_settings


class LauncherSettingsTests(unittest.TestCase):
    def test_missing_user_file_returns_defaults_without_creating_directory(self):
        with TemporaryDirectory() as directory, patch('pathlib.Path.home', return_value=Path(directory)):
            self.assertEqual(load_settings(), LauncherSettings(0, False))
            self.assertFalse((Path(directory) / '.nuclemu').exists())

    def test_save_and_reopen_user_file_without_read_side_effects(self):
        with TemporaryDirectory() as directory, patch('pathlib.Path.home', return_value=Path(directory)):
            save_settings(LauncherSettings(65535, True))
            target = Path(directory) / '.nuclemu' / 'launcher.json'
            original = target.read_bytes()
            self.assertFalse(original.startswith(b'\xef\xbb\xbf'))
            self.assertEqual(json.loads(original), {'port': 65535, 'open_browser': True})
            self.assertEqual(load_settings(), LauncherSettings(65535, True))
            self.assertEqual(target.read_bytes(), original)

    def test_invalid_fields_are_rejected_before_writing(self):
        for port in (-1, 65536, True, 1.0, '80', None):
            with self.subTest(port=port), self.assertRaises(ValueError):
                LauncherSettings(port, False)
        for opening in (0, 1, 'false', None):
            with self.subTest(open_browser=opening), self.assertRaises(ValueError):
                LauncherSettings(0, opening)

    def test_damaged_file_reports_recovery_and_is_untouched_until_explicit_save(self):
        damaged = [b'{', b'\xff', b'[]', b'{}', b'{"port": 0}',
                   b'{"port": true, "open_browser": false}',
                   b'{"port": 3, "open_browser": "false"}',
                   b'{"port": 3, "open_browser": false, "extra": 1}']
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'launcher.json'
            for raw in damaged:
                with self.subTest(raw=raw):
                    target.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, '保存有效值以恢复') as error:
                        load_settings(target)
                    self.assertIn(str(target), str(error.exception))
                    self.assertEqual(target.read_bytes(), raw)
            save_settings(LauncherSettings(), target)
            self.assertEqual(load_settings(target), LauncherSettings())

    def test_read_and_directory_creation_failures_are_explicit(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'launcher.json'
            with patch.object(Path, 'read_text', side_effect=PermissionError('read denied')):
                with self.assertRaisesRegex(OSError, 'read denied') as error:
                    load_settings(target)
                self.assertIn(str(target), str(error.exception))
            with patch.object(Path, 'mkdir', side_effect=PermissionError('create denied')):
                with self.assertRaisesRegex(OSError, 'create denied'):
                    save_settings(LauncherSettings(), target)
            self.assertFalse(target.exists())

    def test_failed_write_or_replace_keeps_old_bytes_and_removes_temporary_file(self):
        for failure in ('json.dump', 'os.fsync', 'os.replace'):
            with self.subTest(failure=failure), TemporaryDirectory() as directory:
                target = Path(directory) / 'launcher.json'
                save_settings(LauncherSettings(12345, True), target)
                old = target.read_bytes()
                with patch(f'nuclemu.launcher_settings.{failure}', side_effect=OSError('disk failure')):
                    with self.assertRaisesRegex(OSError, '原设置文件保持不变'):
                        save_settings(LauncherSettings(0, False), target)
                self.assertEqual(target.read_bytes(), old)
                self.assertEqual(list(Path(directory).iterdir()), [target])
                self.assertEqual(load_settings(target), LauncherSettings(12345, True))

    def test_web_cli_modes_do_not_read_desktop_settings(self):
        code = """import builtins, sys, tempfile, threading, _thread
from pathlib import Path
from unittest.mock import patch
from nuclemu.cli import main
import nuclemu.web as web
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in ('nuclemu.launcher_settings', 'launcher_settings'):
        raise AssertionError('CLI imported desktop settings')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
sys.modules['tkinter'] = None
sys.modules['nuclemu.desktop'] = None
for flags, expected_browser_calls in ((['serve', '--no-gui'], 0), (['gui'], 1)):
    with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'home', return_value=Path(directory)):
        timer = threading.Timer(1, _thread.interrupt_main)
        timer.start()
        try:
            with patch.object(web.webbrowser, 'open') as opening:
                assert main(flags) == 0
                assert opening.call_count == expected_browser_calls, opening.call_count
        finally:
            timer.cancel()
            timer.join()
assert 'nuclemu.launcher_settings' not in sys.modules
"""
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
