"""Desktop import stays headless; optional real Tk checks exercise its service owner."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from nuclemu import desktop


class DesktopImportTests(unittest.TestCase):
    def test_import_does_not_initialize_tk_or_the_web_service(self):
        result = subprocess.run([sys.executable, '-c',
            "import sys; import nuclemu.desktop; "
            "assert 'tkinter' not in sys.modules; assert 'nuclemu.web_service' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(os.environ.get('NUCLEMU_TEST_TK') == '1', 'Set NUCLEMU_TEST_TK=1 with a display')
class DesktopTkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from nuclemu.web_service import WorkbenchService
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = tk.Tk()
        self.addCleanup(self.destroy)
        self.now = 0
        self.service = WorkbenchService(directory=self.folder.name, clock=lambda: self.now)
        self.addCleanup(self.stop)

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def stop(self):
        self.service.stop(force=True)
        self.assertTrue(self.service.join(5))

    def until(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            self.root.update()
            time.sleep(.01)
        self.fail('Tk/service condition did not complete')

    def post(self, route, data):
        request = Request(self.service.status().url + 'api/' + route,
                          json.dumps(data).encode(), {'Content-Type':'application/json'})
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def window(self):
        window = desktop._Launcher(self.root, self.service)
        self.root.update_idletasks()
        return window

    def test_first_frame_then_ready_copy_open_and_idle_close(self):
        with patch.object(self.service, 'start', wraps=self.service.start) as start:
            window = self.window()
            self.assertTrue(self.root.winfo_ismapped())
            self.assertEqual(window.status.get(), '正在启动…')
            self.assertFalse(start.called)
            self.until(lambda: window.url is not None)
        with urlopen(window.url + 'api/catalog', timeout=3) as response:
            self.assertEqual({c['id'] for c in json.load(response)['experiments']}, {'alpha', 'beta'})
        window.copy_button.invoke()
        self.assertEqual(self.root.clipboard_get(), window.url)
        with patch('nuclemu.desktop.webbrowser.open', return_value=False) as opened:
            window.open_button.invoke()
            self.assertEqual(opened.call_args.args, (window.url,))
            self.assertIn('复制地址', window.message.get())
        window.close_button.invoke()
        self.until(lambda: window.closed)
        self.assertTrue(self.service.join(0))

    def test_active_session_close_preserves_data_then_workbench_exit_allows_close(self):
        window = self.window()
        self.until(lambda: window.url is not None)
        opened = self.post('open', {'experiment':'beta'})
        self.post('action', {'session':opened['id'], 'action':'output', 'output':'beta_detector', 'enabled':True})
        self.post('action', {'session':opened['id'], 'action':'start_group', 'component':'counter'})
        self.now = 3
        with urlopen(window.url + 'api/state', timeout=3) as response:
            before = json.load(response)
        self.assertGreater(sum(before['instruments']['counter']['counts']), 0)
        window.close_button.invoke()
        self.until(lambda: not window.checking_close)
        self.assertFalse(window.closed)
        self.assertIn('返回工作台退出实验', window.message.get())
        with urlopen(window.url + 'api/state', timeout=3) as response:
            after = json.load(response)
        self.assertEqual(after['id'], opened['id'])
        self.assertEqual(after['instruments'], before['instruments'])
        self.assertTrue(after['any_running'])
        frozen = self.post('action', {'session':opened['id'], 'action':'freeze'})
        self.post('action', {'session':opened['id'], 'action':'discard', 'confirmation_id':frozen['confirmation_id']})
        window.close_button.invoke()
        self.until(lambda: window.closed)

    def test_startup_cancel_does_not_publish_ready_or_open_browser(self):
        from threading import Event
        from nuclemu.web import make_server
        entered, release = Event(), Event()
        def delayed(*args, **kwargs):
            entered.set()
            release.wait(3)
            return make_server(*args, **kwargs)
        with patch('nuclemu.web.make_server', side_effect=delayed), patch('nuclemu.desktop.webbrowser.open') as opened:
            window = self.window()
            self.until(entered.is_set)
            window.close_button.invoke()
            self.until(lambda: window.closing)
            self.assertIsNone(window.url)
            release.set()
            self.until(lambda: window.closed)
            opened.assert_not_called()

    def test_startup_failure_stays_visible_and_can_close(self):
        from nuclemu.web_service import WorkbenchService
        occupied = socket.socket()
        self.addCleanup(occupied.close)
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        self.service = WorkbenchService(port=occupied.getsockname()[1], directory=self.folder.name)
        window = self.window()
        self.until(lambda: window.status.get() == '启动失败')
        self.assertIn('no-gui', window.message.get())
        self.assertIsNone(window.url)
        window.close_button.invoke()
        self.until(lambda: window.closed)


if __name__ == '__main__':
    unittest.main()
