"""Explicit server modes keep desktop dependencies out of terminal service startup."""
from contextlib import redirect_stderr
from io import StringIO
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

from nuclemu.cli import main


class ServeCliTests(unittest.TestCase):
    def test_mode_is_required_and_mutually_exclusive_before_starting(self):
        for flags in ([], ['--gui', '--no-gui']):
            with self.subTest(flags=flags), patch('nuclemu.cli.discover') as discover:
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                    main(['serve', *flags])
                self.assertEqual(error.exception.code, 2)
                discover.assert_not_called()

    def test_headless_forwards_both_path_positions_without_browser_or_desktop(self):
        web = types.ModuleType('nuclemu.web')
        web.launch = Mock()
        with patch.dict(sys.modules, {'nuclemu.web': web, 'nuclemu.desktop': None, 'tkinter': None}):
            self.assertEqual(main(['--path', 'first', 'serve', '--no-gui', '--path', 'second']), 0)
        web.launch.assert_called_once_with(paths=['first', 'second'], open_browser=False)

    def test_desktop_forwards_paths_without_entering_the_old_browser_launcher(self):
        desktop = types.ModuleType('nuclemu.desktop')
        desktop.launch = Mock()
        with patch.dict(sys.modules, {'nuclemu.desktop': desktop, 'nuclemu.web': None}):
            self.assertEqual(main(['serve', '--gui', '--path', 'course']), 0)
        desktop.launch.assert_called_once_with(paths=['course'])

    def test_service_interrupt_is_a_clean_exit_and_startup_error_is_nonzero(self):
        for gui in (False, True):
            module = types.ModuleType('nuclemu.desktop' if gui else 'nuclemu.web')
            module.launch = Mock(side_effect=KeyboardInterrupt)
            flags = ['serve', '--gui' if gui else '--no-gui']
            with patch.dict(sys.modules, {module.__name__: module}):
                self.assertEqual(main(flags), 0)
                module.launch.side_effect = OSError('controlled startup failure')
                output = StringIO()
                with redirect_stderr(output), self.assertRaises(SystemExit) as error:
                    main(flags)
                self.assertEqual(error.exception.code, 2)
                self.assertIn('controlled startup failure', output.getvalue())
                if gui:
                    self.assertIn('nuclemu serve --no-gui', output.getvalue())

    def test_old_gui_still_uses_the_browser_launcher_defaults(self):
        web = types.ModuleType('nuclemu.web')
        web.launch = Mock()
        with patch.dict(sys.modules, {'nuclemu.web': web, 'nuclemu.desktop': None}):
            self.assertEqual(main(['gui', '--path', 'course']), 0)
        web.launch.assert_called_once_with(paths=['course'])

    def test_unavailable_desktop_reports_headless_alternative_before_service_start(self):
        tkinter = types.ModuleType('tkinter')
        tkinter.TclError = type('TclError', (Exception,), {})
        tkinter.Tk = Mock(side_effect=tkinter.TclError('display unavailable'))
        output = StringIO()
        with patch.dict(sys.modules, {'tkinter': tkinter, 'nuclemu.web_service': None}):
            with redirect_stderr(output), self.assertRaises(SystemExit) as error:
                main(['serve', '--gui'])
        self.assertEqual(error.exception.code, 2)
        self.assertIn('display unavailable', output.getvalue())
        self.assertIn('nuclemu serve --no-gui', output.getvalue())

    def test_parser_error_does_not_import_window_dependencies(self):
        code = """from nuclemu.cli import main
import sys
try:
    main(['serve'])
except SystemExit as error:
    assert error.code == 2
assert 'nuclemu.desktop' not in sys.modules
assert 'tkinter' not in sys.modules
assert 'nuclemu.web' not in sys.modules
"""
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
