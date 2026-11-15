"""Real Tk start decisions with real registered services and private test roots."""

import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nuclemu import desktop
from nuclemu.launcher_instance import ServiceRegistration, plan_start, discover_services
from nuclemu.launcher_settings import LauncherSettings
from nuclemu.web_service import WorkbenchService


@unittest.skipUnless(os.environ.get('NUCLEMU_TEST_TK') == '1', 'Set NUCLEMU_TEST_TK=1 with a display')
class DesktopStartupTkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        desktop.enable_windows_dpi_awareness()
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.registry, self.store = self.base / 'registry', self.base / 'store'
        self.root = tk.Tk()
        self.now = 0
        self.services = []
        self.window = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.window is not None:
            self.window.shutdown()
        for service in self.services:
            service.stop(force=True)
            self.assertTrue(service.join(5))
        try:
            self.root.destroy()
        except Exception:
            pass

    def until(self, condition, timeout=7):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(.01)
        self.fail('Tk/start condition did not complete')

    def course(self, name):
        path = self.base / name
        path.mkdir()
        (path / 'course.py').write_text(
            "from nuclemu.core import Device, Experiment, SignalOutput, Component\n"
            f"EXPERIMENT = Experiment({name!r}, {name!r}, '', (), "
            "(Device('a','counter','Counter',input='detector'),), "
            "lambda settings,start,end,rng: {'detector':(round(10*(end-start)),)}, "
            "outputs=(SignalOutput('detector','Detector'),), "
            "components=(Component('counter','instrument','Counter',device='a',devices=('a',)),))\n",
            encoding='utf-8')
        return (str(path),)

    def old(self, paths=(), *, gui=False):
        owner = ServiceRegistration(paths, gui=gui, directory=self.registry, workbench_directory=self.store)
        service = WorkbenchService(paths, directory=self.store, registration=owner, clock=lambda: self.now).start()
        self.services.append(service)
        service.wait_ready(5)
        return service, owner

    def launch_window(self, paths=(), port=0, *, new_instance=False, prepare=None):
        initial = WorkbenchService(paths, port=port, directory=self.store, clock=lambda: self.now)
        def factory(selected):
            service = WorkbenchService(paths, port=selected, directory=self.store,
                registration=self.window.instance, clock=lambda: self.now)
            self.services.append(service)
            return service
        def startup(selected):
            return plan_start(paths, port=selected, directory=self.store,
                              registry_directory=self.registry, new_instance=new_instance)
        self.window = desktop._Launcher(self.root, initial, settings=LauncherSettings(port),
            service_factory=factory, startup=prepare or startup)
        self.root.update_idletasks()
        return self.window

    def post(self, service, route, **data):
        request = Request(service.status().url + 'api/' + route, json.dumps(data).encode(),
                          {'Content-Type':'application/json'})
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def state(self, service):
        with urlopen(service.status().url + 'api/state', timeout=3) as response:
            return json.load(response)

    def collect(self, service, name, seed):
        state = self.post(service, 'open', experiment=name, seed=seed)
        self.post(service, 'action', session=state['id'], action='output', output='detector', enabled=True)
        self.post(service, 'action', session=state['id'], action='start_group', component='counter')
        return state['id']

    def test_first_frame_and_responsive_cancel_during_slow_discovery(self):
        entered, release = Event(), Event()
        def slow(port):
            entered.set()
            release.wait(4)
            return plan_start(port=port, directory=self.store, registry_directory=self.registry)
        with patch('nuclemu.desktop.webbrowser.open') as browser:
            window = self.launch_window(prepare=slow)
            self.assertTrue(self.root.winfo_ismapped())
            self.assertFalse(entered.is_set())
            self.until(entered.is_set)
            ticks = []
            self.root.after(0, lambda: ticks.append(True))
            self.until(lambda: bool(ticks))
            window.request_close()
            self.until(lambda: window.closing)
            self.assertFalse(window.closed)
            release.set()
            self.until(lambda: window.closed)
            window.shutdown()
            self.assertEqual(discover_services(self.registry), [])
            self.assertEqual(self.services, [])
            browser.assert_not_called()

    def test_no_previous_service_starts_our_own_url(self):
        window = self.launch_window()
        self.until(lambda: window.url is not None)
        self.assertIsNone(window.startup_window)
        record, = discover_services(self.registry)
        self.assertEqual(record.url, window.url)
        self.assertEqual(record.instance_id, window.service.instance_id)

    def test_plain_same_configuration_activates_old_gui_without_browser(self):
        old, owner = self.old(gui=True)
        with patch('nuclemu.desktop.webbrowser.open') as browser:
            window = self.launch_window()
            self.until(lambda: window.closed)
            browser.assert_not_called()
        self.assertTrue(owner.take_activation())
        self.assertEqual(old.status().phase, 'ready')
        self.assertIsNone(window.url)

    def test_headless_existing_reuse_opens_actual_url_and_closes_only_new_window(self):
        paths = self.course('only_a')
        old, _ = self.old(paths)
        session = self.collect(old, 'only_a', 11)
        window = self.launch_window()
        self.until(lambda: window.startup_window is not None)
        with patch('nuclemu.desktop.webbrowser.open', return_value=True) as browser:
            window.startup_window.reuse_button.invoke()
            self.until(lambda: window.closed)
            browser.assert_called_once_with(old.status().url)
        self.now = 3
        state = self.state(old)
        self.assertEqual(state['id'], session)
        self.assertEqual(state['instruments']['a']['exposure_s'], 3)
        self.assertEqual(old.status().phase, 'ready')

    def test_reuse_browser_failure_keeps_choice_and_copyable_verified_url(self):
        old, _ = self.old()
        window = self.launch_window()
        self.until(lambda: window.startup_window is not None)
        dialog = window.startup_window
        with patch('nuclemu.desktop.webbrowser.open', return_value=False):
            dialog.reuse_button.invoke()
            self.until(lambda: not window._planning)
        self.assertIs(window.startup_window, dialog)
        self.assertIn(old.status().url, dialog.message.get())
        dialog.copy_button.invoke()
        self.assertEqual(self.root.clipboard_get(), old.status().url)
        dialog.new_button.invoke()
        self.until(lambda: window.url is not None)
        self.assertNotEqual(window.url, old.status().url)

    def test_parallel_on_nuclemu_port_uses_other_port_and_keeps_courses_independent(self):
        paths_a, paths_b = self.course('only_a'), self.course('only_b')
        old, _ = self.old(paths_a, gui=True)
        old_session = self.collect(old, 'only_a', 11)
        port = int(old.status().url.rstrip('/').rsplit(':', 1)[1])
        window = self.launch_window(paths_b, port)
        self.until(lambda: window.startup_window is not None)
        window.startup_window.new_button.invoke()
        self.until(lambda: window.url is not None)
        self.assertNotEqual(window.url, old.status().url)
        new_session = self.collect(window.service, 'only_b', 22)
        with self.assertRaises(HTTPError):
            self.post(window.service, 'open', experiment='only_a')
        self.now = 3
        self.assertEqual(self.state(old)['id'], old_session)
        self.assertEqual(self.state(window.service)['id'], new_session)
        self.assertEqual(self.state(window.service)['instruments']['a']['counts'], [30])
        window.request_close()
        self.until(lambda: window.close_window is not None)
        window.close_window.discard_button.invoke()
        self.until(lambda: window.closed)
        self.now = 4
        state = self.state(old)
        self.assertEqual(state['id'], old_session)
        self.assertFalse(state['frozen'])
        self.assertEqual(state['instruments']['a']['counts'], [40])

    def test_unknown_fixed_port_reports_conflict_then_settings_retry_uses_new_owner(self):
        with socket.socket() as other:
            other.bind(('127.0.0.1', 0))
            other.listen()
            port = other.getsockname()[1]
            window = self.launch_window(port=port)
            self.until(lambda: window.status.get() == '启动失败')
            self.assertIsNone(window.startup_window)
            self.assertIn(str(port), window.message.get())
            self.assertIsNone(window.instance)
            window.settings = LauncherSettings()
            window.retry_button.invoke()
            self.until(lambda: window.url is not None)
            self.assertTrue(other.fileno() >= 0)
            record, = discover_services(self.registry)
            self.assertEqual(record.instance_id, window.service.instance_id)

    def test_explicit_new_same_configuration_requires_choice(self):
        old, _ = self.old(gui=True)
        window = self.launch_window(new_instance=True)
        self.until(lambda: window.startup_window is not None)
        window.startup_window.new_button.invoke()
        self.until(lambda: window.url is not None)
        self.assertNotEqual(window.url, old.status().url)

    def test_reuse_nuclemu_occupied_port_uses_old_url_and_does_not_stop_it(self):
        old, owner = self.old(gui=True)
        port = int(old.status().url.rstrip('/').rsplit(':', 1)[1])
        window = self.launch_window(port=port)
        self.until(lambda: window.startup_window is not None)
        with patch('nuclemu.desktop.webbrowser.open', return_value=True) as browser:
            window.startup_window.reuse_button.invoke()
            self.until(lambda: window.closed)
            browser.assert_called_once_with(old.status().url)
        self.assertTrue(owner.take_activation())
        self.assertEqual(old.status().phase, 'ready')

    def test_failed_discovery_retry_gets_a_fresh_registration(self):
        paths = self.course('fixed_course')
        source = Path(paths[0]) / 'course.py'
        valid = source.read_text(encoding='utf-8')
        source.write_text("raise ValueError('broken course')\n", encoding='utf-8')
        window = self.launch_window(paths)
        self.until(lambda: window.status.get() == '启动失败' and window.service.join(0))
        first = window.instance.registration_id
        self.assertEqual(discover_services(self.registry), [])
        source.write_text(valid, encoding='utf-8')
        window.retry_button.invoke()
        self.until(lambda: window.url is not None)
        self.assertNotEqual(window.instance.registration_id, first)
        record, = discover_services(self.registry)
        self.assertEqual(record.instance_id, window.service.instance_id)

    def test_cancel_during_reuse_verification_prevents_late_browser(self):
        old, _ = self.old()
        window = self.launch_window()
        self.until(lambda: window.startup_window is not None)
        entered, release = Event(), Event()
        original = window.start_plan.use_existing
        def slow(entry):
            entered.set()
            release.wait(4)
            return original(entry)
        with patch.object(window.start_plan, 'use_existing', side_effect=slow), \
                patch('nuclemu.desktop.webbrowser.open') as browser:
            window.startup_window.reuse_button.invoke()
            self.until(entered.is_set)
            window.request_close()
            self.until(lambda: window.closing)
            release.set()
            self.until(lambda: window.closed)
            browser.assert_not_called()
        self.assertEqual(old.status().phase, 'ready')

    def test_multiple_existing_urls_are_selectable_and_layout_scales(self):
        self.old(self.course('only_a'))
        self.old(self.course('only_b'))
        window = self.launch_window(new_instance=True)
        self.until(lambda: window.startup_window is not None)
        dialog = window.startup_window
        self.assertEqual(len(dialog.existing), 2)
        dialog.selection.current(1)
        dialog.selection.event_generate('<<ComboboxSelected>>')
        dialog.copy_button.invoke()
        self.assertEqual(self.root.clipboard_get(), dialog.existing[1].url)
        self.assertIn(Path(dialog.existing[1].paths[0]).name, dialog.course.get())
        for dpi in (96, 144, 192, 144, 96):
            with self.subTest(dpi=dpi), patch('nuclemu.desktop_startup.window_dpi', return_value=dpi):
                dialog._apply_dpi()
                self.root.update()
                self.assertFalse(dialog.message_label.winfo_ismapped())
                for control in (*dialog.buttons, dialog.selection):
                    right = control.winfo_rootx() - dialog.root.winfo_rootx() + control.winfo_width()
                    bottom = control.winfo_rooty() - dialog.root.winfo_rooty() + control.winfo_height()
                    self.assertLessEqual(right, dialog.root.winfo_width())
                    self.assertLessEqual(bottom, dialog.root.winfo_height())
