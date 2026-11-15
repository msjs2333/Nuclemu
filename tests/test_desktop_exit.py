"""Real Tk and HTTP exit transactions; the native chooser is stubbed in tests."""

from base64 import b64encode
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, current_thread
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

from nuclemu import desktop
from nuclemu.exchange import load_package
from nuclemu.web_service import WorkbenchService, CloseSaveResult


@unittest.skipUnless(os.environ.get('NUCLEMU_TEST_TK') == '1', 'Set NUCLEMU_TEST_TK=1 with a display')
class DesktopExitTkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        desktop.enable_windows_dpi_awareness()
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.target = Path(self.folder.name) / '实验.nuclemu'
        self.root = tk.Tk()
        self.now = 0
        self.service = WorkbenchService(directory=self.folder.name, clock=lambda: self.now)
        self.addCleanup(self.cleanup)
        self.window = desktop._Launcher(self.root, self.service)
        self.until(lambda: self.window.url is not None)
        self.post('open', experiment='beta')
        self.action('output', output='beta_detector', enabled=True)
        self.action('window_config', component='counter', device='counter_b', window_s=5)
        self.action('start_group', component='counter')
        self.now = 3
        self.action('snapshot_group', component='counter', device='counter', title='3 s',
                    acquisitions={'counter': 1, 'counter_b': 1})
        self.now = 5

    def cleanup(self):
        self.service.stop(force=True)
        self.assertTrue(self.service.join(5))
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

    def post(self, route, **data):
        request = Request(self.window.url + 'api/' + route,
                          json.dumps(data).encode(), {'Content-Type': 'application/json'})
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def state(self):
        with urlopen(self.window.url + 'api/state', timeout=3) as response:
            return json.load(response)

    def action(self, action, **data):
        return self.post('action', session=self.service.active_session(), action=action, **data)

    def close_dialog(self):
        self.window.request_close()
        self.until(lambda: self.window.close_window is not None)
        return self.window.close_window

    def test_cancel_defaults_repeat_activation_and_other_actions_are_gated(self):
        self.window.show_settings()
        settings = self.window.settings_window
        with patch.object(self.service, 'begin_close', wraps=self.service.begin_close) as begin:
            dialog = self.close_dialog()
            context = self.window.close_context
            self.assertTrue(context.has_uncached)
            self.assertIn('当前未保存的读数', dialog.description['text'])
            self.assertEqual(str(self.root.tk.call('focus', '-lastfor', dialog.root)), str(dialog.cancel_button))
            self.window.request_close()
            self.window.show_settings()
            with patch('nuclemu.desktop.webbrowser.open') as browser:
                self.window.open_browser()
                browser.assert_not_called()
            self.assertEqual(begin.call_count, 1)
            self.assertIs(self.window.close_window, dialog)
            self.assertIs(self.window.settings_window, settings)
            self.assertFalse(settings.root.winfo_ismapped())
            self.window.activate()
            self.assertIs(self.window.close_context, context)
            dialog.cancel_button.invoke()
            self.until(lambda: not self.window.checking_close)
            self.assertTrue(settings.root.winfo_ismapped())
            self.assertFalse(self.state()['frozen'])
            self.now = 6
            self.assertEqual(self.state()['instruments']['counter_b']['exposure_s'], 6)

    def test_save_real_beta_cached_three_seconds_not_five_then_reopen(self):
        dialog = self.close_dialog()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.target)) as chooser:
            dialog.save_button.invoke()
        self.until(lambda: self.window.closed)
        self.assertEqual(chooser.call_args.kwargs['parent'], dialog.root)
        self.assertTrue(chooser.call_args.kwargs['initialfile'].endswith('.nuclemu'))
        document = load_package(self.target)
        measurements = [item for item in document['items'] if item['kind'] == 'measurement']
        self.assertEqual(len(measurements), 2)
        for item in measurements:
            self.assertEqual(item['document']['snapshot']['exposure_s'], 3)
        from nuclemu.web_session import Application
        from nuclemu.catalog import discover
        app = Application(discover(), Path(self.folder.name) / 'reopened', lambda: 0)
        reopened = app.request('/api/open_package', {'file': b64encode(self.target.read_bytes()).decode()})
        self.assertTrue(reopened['id'])
        self.assertEqual(len(app.lab.exchange.document['items']), 2)

    def test_cancel_file_choice_retains_confirmation_and_cancel_returns(self):
        dialog = self.close_dialog()
        context = self.window.close_context
        with patch('tkinter.filedialog.asksaveasfilename', return_value=''), \
                patch.object(self.service, 'save_close', wraps=self.service.save_close) as save:
            dialog.save_button.invoke()
            save.assert_not_called()
        self.assertIs(self.window.close_context, context)
        self.assertTrue(self.state()['frozen'])
        self.assertIn('未选择文件', dialog.message.get())
        dialog.cancel_button.invoke()
        self.until(lambda: not self.window.checking_close)
        self.assertFalse(self.state()['frozen'])

    def test_write_failure_preserves_original_and_can_retry_same_round(self):
        self.target.write_bytes(b'original')
        dialog = self.close_dialog()
        context = self.window.close_context
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.target)), \
                patch('os.fsync', side_effect=OSError('disk full')):
            dialog.save_button.invoke()
            self.until(lambda: not self.window._close_busy)
        self.assertIn('disk full', dialog.message.get())
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertIs(self.window.close_context, context)
        self.assertTrue(self.state()['frozen'])
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.target)):
            dialog.save_button.invoke()
        self.until(lambda: self.window.closed)
        self.assertEqual(len(load_package(self.target)['items']), 2)

    def test_encoding_value_error_keeps_cancel_entry_and_can_resume(self):
        dialog = self.close_dialog()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.target)), \
                patch.object(self.service, 'save_close', side_effect=ValueError('invalid package')):
            dialog.save_button.invoke()
            self.until(lambda: not self.window._close_busy)
        self.assertIs(self.window.close_window, dialog)
        self.assertIn('invalid package', dialog.message.get())
        dialog.cancel_button.invoke()
        self.until(lambda: not self.window.checking_close)
        self.assertFalse(self.state()['frozen'])

    def test_browser_cancels_and_replaces_during_chooser_old_save_cannot_overwrite(self):
        self.target.write_bytes(b'original')
        dialog = self.close_dialog()
        def chooser(**kwargs):
            self.assertTrue(self.window._choosing_path)
            self.action('continue', confirmation_id=self.window.close_context.confirmation_id)
            token = self.action('freeze')['confirmation_id']
            self.action('discard', confirmation_id=token)
            self.post('open', experiment='alpha')
            self.window.activate()  # Must not steal focus from the system chooser.
            return str(self.target)
        with patch('tkinter.filedialog.asksaveasfilename', side_effect=chooser):
            dialog.save_button.invoke()
        self.until(lambda: not self.window.checking_close)
        self.assertIsNone(self.window.close_window)
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertIn('未关闭', self.window.message.get())
        self.assertEqual(self.state()['experiment'], 'alpha')
        self.assertEqual(self.service.status().phase, 'ready')

    def test_worker_and_repeated_close_do_not_block_tk_or_duplicate_transaction(self):
        entered, release = Event(), Event()
        original = self.service.begin_close
        threads = []
        def slow():
            threads.append(current_thread().name)
            entered.set()
            release.wait(3)
            return original()
        ticks = []
        with patch.object(self.service, 'begin_close', side_effect=slow) as begin:
            self.window.request_close()
            self.until(entered.is_set)
            self.root.after(0, lambda: ticks.append(True))
            self.until(lambda: bool(ticks))
            self.window.request_close()
            self.assertEqual(begin.call_count, 1)
            release.set()
            self.until(lambda: self.window.close_window is not None)
        self.assertEqual(threads, ['nuclemu-desktop-begin'])
        self.window.close_window.discard_button.invoke()
        self.until(lambda: self.window.closed)

    def test_success_warning_is_visible_without_retry_or_resume(self):
        dialog = self.close_dialog()
        original = self.service.save_close
        def warning(context, path):
            original(context, path)
            return CloseSaveResult(str(path), '文件已保存，旧恢复草稿未清理。')
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.target)), \
                patch.object(self.service, 'save_close', side_effect=warning):
            dialog.save_button.invoke()
            self.until(lambda: dialog.completed)
        self.assertFalse(self.window.closed)
        self.assertEqual(dialog.heading['text'], '文件已保存')
        self.assertFalse(dialog.save_button.shell.winfo_ismapped())
        self.assertFalse(dialog.discard_button.shell.winfo_ismapped())
        self.assertEqual(dialog.cancel_button['text'], '关闭')
        dialog.cancel_button.invoke()
        self.until(lambda: self.window.closed)

    def test_exit_layout_bounds_across_simulated_dpi(self):
        dialog = self.close_dialog()
        for dpi in (96, 144, 192, 144, 96):
            with self.subTest(dpi=dpi), patch('nuclemu.desktop_exit.window_dpi', return_value=dpi):
                dialog._apply_dpi()
                self.root.update()
                for button in dialog.buttons:
                    right = button.winfo_rootx() - dialog.root.winfo_rootx() + button.winfo_width()
                    bottom = button.winfo_rooty() - dialog.root.winfo_rooty() + button.winfo_height()
                    self.assertLessEqual(right, dialog.root.winfo_width())
                    self.assertLessEqual(bottom, dialog.root.winfo_height())
                self.assertFalse(dialog.message_label.winfo_ismapped())

    def test_legacy_whole_session_exit_has_no_lost_readings_warning(self):
        from nuclemu.catalog import describe
        from nuclemu.core import Device, Experiment
        from nuclemu.web_session import WebLab
        definition = Experiment('old', 'Old', '', (), (Device('c', 'counter', 'C'),),
            lambda settings, start, end, rng: {'c': (round(end - start),)})
        with self.service._server.app_lock:
            app = self.service._server.app
            app.lab = WebLab(definition, describe(definition), 0, app.store, lambda: self.now)
            app.lab.work.session.start(10)
            self.now += 3
            app.state()
        dialog = self.close_dialog()
        self.assertFalse(self.window.close_context.has_uncached)
        self.assertEqual(dialog.description['text'], '')
        self.assertFalse(dialog.description.winfo_ismapped())
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.target)):
            dialog.save_button.invoke()
        self.until(lambda: self.window.closed)
        segments = load_package(self.target)['legacy']['document']['product']['segments']
        self.assertEqual(sum(segment['readings']['c'][0] for segment in segments), 3)


if __name__ == '__main__':
    unittest.main()
