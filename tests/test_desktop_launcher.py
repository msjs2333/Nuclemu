"""Real Tk checks for preferences, attempts and single-owner activation."""

import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import Mock, patch

from nuclemu import desktop
from nuclemu.launcher_settings import LauncherSettings, load_settings


class DesktopOwnershipTests(unittest.TestCase):
    def test_failed_tk_creation_does_not_claim_a_service(self):
        import tkinter as tk
        with patch('tkinter.Tk', side_effect=tk.TclError('no display')), \
                patch('nuclemu.launcher_instance.plan_start') as plan:
            with self.assertRaisesRegex(OSError, 'no display'):
                desktop.launch()
        plan.assert_not_called()

    def test_missing_tk_does_not_claim_a_service(self):
        with patch.dict(sys.modules, {'tkinter': None}), \
                patch('nuclemu.launcher_instance.plan_start') as plan:
            with self.assertRaises(ImportError):
                desktop.launch()
        plan.assert_not_called()


@unittest.skipUnless(os.environ.get('NUCLEMU_TEST_TK') == '1', 'Set NUCLEMU_TEST_TK=1 with a display')
class DesktopPreferencesTkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        desktop.enable_windows_dpi_awareness()
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'launcher.json'
        self.root = tk.Tk()
        self.services = []
        self.addCleanup(self.cleanup)

    def factory(self, port):
        from nuclemu.web_service import WorkbenchService
        service = WorkbenchService(port=port, directory=Path(self.folder.name) / 'store',
                                   registration=getattr(self, 'registration', None))
        self.services.append(service)
        return service

    def cleanup(self):
        for service in self.services:
            service.stop(force=True)
            self.assertTrue(service.join(5))
        try:
            self.root.destroy()
        except Exception:
            pass

    def until(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Tk/service condition did not complete')

    def window(self, settings=LauncherSettings(), **kwargs):
        window = desktop._Launcher(self.root, self.factory(settings.port), settings=settings,
            settings_path=self.path, service_factory=self.factory, **kwargs)
        self.root.update_idletasks()
        return window

    def test_automatic_once_activation_and_manual_repeat(self):
        owner = Mock()
        owner.take_activation.return_value = False
        with patch('nuclemu.desktop.webbrowser.open', return_value=True) as opened:
            window = self.window(LauncherSettings(open_browser=True), instance=owner)
            self.until(lambda: window.url is not None)
            opened.assert_called_once_with(window.url)
            window.show_settings()
            dialog = window.settings_window
            with patch.object(dialog, 'activate', wraps=dialog.activate) as activate:
                owner.take_activation.return_value = True
                window.poll()
                activate.assert_called_once_with()
            owner.take_activation.return_value = False
            opened.assert_called_once_with(window.url)
            window.open_button.invoke()
            window.open_button.invoke()
            self.assertEqual(opened.call_count, 3)

    def test_settings_cancel_validation_failure_then_save_keep_current_url(self):
        window = self.window()
        self.until(lambda: window.url is not None)
        url, service = window.url, window.service
        window.show_settings()
        dialog = window.settings_window
        dialog.automatic.set(False)
        dialog.port.set('12345')
        dialog.open_browser.set(True)
        with patch('nuclemu.launcher_settings.save_settings') as save:
            dialog.cancel_button.invoke()
            save.assert_not_called()
        self.assertEqual(window.settings, LauncherSettings())
        window.show_settings()
        dialog = window.settings_window
        dialog.automatic.set(False)
        for invalid in ('0', '65536', '-1', '1.2', 'abc', '１２３'):
            dialog.port.set(invalid)
            dialog.save_button.invoke()
            self.assertIs(window.settings_window, dialog)
            self.assertIn('1–65535', dialog.error.get())
        dialog.port.set('12345')
        dialog.open_browser.set(True)
        with patch('nuclemu.launcher_settings.save_settings', side_effect=OSError('磁盘不可写')):
            dialog.save_button.invoke()
        self.assertIn('磁盘不可写', dialog.error.get())
        self.assertEqual(window.settings, LauncherSettings())
        self.assertFalse(self.path.exists())
        dialog.save_button.invoke()
        self.assertIsNone(window.settings_window)
        self.assertEqual(load_settings(self.path), LauncherSettings(12345, True))
        self.assertEqual(window.url, url)
        self.assertIs(window.service, service)
        self.assertEqual(service.status().url, url)

    def test_port_conflict_modify_retry_and_browser_failure_retains_address(self):
        occupied = socket.socket()
        self.addCleanup(occupied.close)
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        with patch('nuclemu.desktop.webbrowser.open', return_value=False) as opened:
            window = self.window(LauncherSettings(occupied.getsockname()[1], True))
            self.until(lambda: window.status.get() == '启动失败')
            opened.assert_not_called()
            window.settings_button.invoke()
            window.settings_window.automatic.set(True)
            window.settings_window.save_button.invoke()
            window.retry_button.invoke()
            self.until(lambda: window.url is not None)
            opened.assert_called_once_with(window.url)
            self.assertIn('无法打开浏览器', window.message.get())
            self.assertEqual(window.address.get(), window.url)
            self.assertNotIn(f':{occupied.getsockname()[1]}/', window.url)
            self.assertNotEqual(occupied.fileno(), -1)
            window.poll()
            self.assertEqual(opened.call_count, 1)

    def test_cancel_retry_startup_never_opens_browser(self):
        from nuclemu.web import make_server
        entered, release = Event(), Event()
        def delayed(*args, **kwargs):
            entered.set()
            release.wait(4)
            return make_server(*args, **kwargs)
        occupied = socket.socket()
        self.addCleanup(occupied.close)
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        with patch('nuclemu.desktop.webbrowser.open') as opened:
            window = self.window(LauncherSettings(occupied.getsockname()[1], True))
            self.until(lambda: window.status.get() == '启动失败')
            window.save_settings(LauncherSettings(open_browser=True))
            with patch('nuclemu.web.make_server', side_effect=delayed):
                window.retry_button.invoke()
                self.until(entered.is_set)
                window.request_close()
                self.until(lambda: window.closing)
                release.set()
                self.until(lambda: window.closed)
            opened.assert_not_called()

    def test_loaded_error_is_visible_and_explicit_save_recovers(self):
        self.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError) as problem:
            load_settings(self.path)
        window = self.window(settings_error=str(problem.exception))
        self.until(lambda: window.url is not None)
        self.assertIn(str(self.path), window.message.get())
        window.show_settings()
        self.assertIn('设置无效', window.settings_window.error.get())
        window.settings_window.cancel()
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{broken')
        window.show_settings()
        window.settings_window.save_button.invoke()
        self.assertEqual(load_settings(self.path), LauncherSettings())
        self.assertIsNone(window.settings_error)

    def test_segment_switch_and_settings_layout_across_simulated_dpi(self):
        window = self.window()
        self.until(lambda: window.url is not None)
        window.show_settings()
        dialog = window.settings_window
        self.assertEqual(str(dialog.port_entry['state']), 'disabled')
        self.assertFalse(dialog.entry_shell.winfo_ismapped())
        dialog.radios[1].invoke()
        self.root.update_idletasks()
        self.assertFalse(dialog.automatic.get())
        self.assertEqual(str(dialog.port_entry['state']), 'normal')
        self.assertTrue(dialog.entry_shell.winfo_ismapped())
        dialog.port.set('23456')
        dialog.radios[0].invoke()
        self.root.update_idletasks()
        self.assertTrue(dialog.automatic.get())
        self.assertEqual(str(dialog.port_entry['state']), 'disabled')
        self.assertFalse(dialog.entry_shell.winfo_ismapped())
        dialog.radios[1].invoke()
        self.assertEqual(dialog.port.get(), '23456')
        self.assertFalse(dialog.open_browser.get())
        dialog.open_check.invoke()
        self.assertTrue(dialog.open_browser.get())
        self.assertEqual(dialog.open_check['text'], '开启')
        for dpi in (96, 144, 192, 144, 96):
            with self.subTest(dpi=dpi), patch('nuclemu.desktop_settings.window_dpi', return_value=dpi):
                dialog._apply_dpi()
                self.root.update()
                self.assertEqual(dialog.switch_images[True].width(), round(48 * dpi / 96))
                self.assertEqual(dialog.fonts['body']['size'], -round(window._body_size * dpi / 96))
                self.assertFalse(dialog.error_label.winfo_ismapped())
                for control in (*dialog.radios, dialog.port_entry, dialog.open_check,
                                dialog.cancel_button, dialog.save_button):
                    right = control.winfo_rootx() - dialog.root.winfo_rootx() + control.winfo_width()
                    bottom = control.winfo_rooty() - dialog.root.winfo_rooty() + control.winfo_height()
                    self.assertLessEqual(right, dialog.root.winfo_width(), str(control))
                    self.assertLessEqual(bottom, dialog.root.winfo_height(), str(control))
        self.assertTrue(dialog.radios[0].bind('<Right>'))
        self.assertTrue(dialog.radios[1].bind('<Left>'))
        self.assertTrue(dialog.open_check.bind('<Return>'))

    def test_secondary_process_restores_same_window_and_settings_during_startup(self):
        from nuclemu.launcher_instance import ServiceRegistration
        from nuclemu.launcher_settings import save_settings
        from nuclemu.web import make_server
        instance_root = Path(self.folder.name) / 'instance'
        owner = ServiceRegistration(gui=True, directory=instance_root,
            workbench_directory=Path(self.folder.name) / 'store')
        self.registration = owner
        save_settings(LauncherSettings(open_browser=True), self.path)
        self.addCleanup(owner.close)
        entered, release = Event(), Event()
        def delayed(*args, **kwargs):
            entered.set()
            release.wait(5)
            return make_server(*args, **kwargs)
        def secondary():
            result = subprocess.run([sys.executable, '-c',
                'from nuclemu.desktop import launch; launch(instance_directory=' + repr(str(instance_root))
                + ', directory=' + repr(str(Path(self.folder.name) / 'store'))
                + ', settings_path=' + repr(str(self.path)) + ')'],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
        with patch('nuclemu.web.make_server', side_effect=delayed), \
                patch('nuclemu.desktop.webbrowser.open', return_value=True) as opened:
            window = self.window(LauncherSettings(open_browser=True), instance=owner)
            self.until(entered.is_set)
            window.show_settings()
            dialog = window.settings_window
            self.root.iconify()
            self.root.update()
            secondary()
            self.until(lambda: self.root.state() == 'normal' and dialog.root.winfo_ismapped())
            self.assertIs(window.settings_window, dialog)
            self.assertEqual(len(self.services), 1)
            opened.assert_not_called()
            release.set()
            self.until(lambda: window.url is not None)
            opened.assert_called_once_with(window.url)
            secondary()
            self.root.update()
            self.assertEqual(len(self.services), 1)
            self.assertEqual(opened.call_count, 1)


if __name__ == '__main__':
    unittest.main()
