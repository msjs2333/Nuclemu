"""Service startup, cancellation and idle stopping use real loopback requests."""

from contextlib import redirect_stdout
from http.client import HTTPConnection
from io import StringIO
import json
import socket
from tempfile import TemporaryDirectory
from threading import Event, Thread, current_thread
import unittest
from unittest.mock import patch

from nuclemu import web
from nuclemu.web_service import WorkbenchService


class WorkbenchServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.services = []
        self.addCleanup(self.stop_services)

    def stop_services(self):
        for service in self.services:
            service.stop(force=True)
            self.assertTrue(service.join(3))

    def service(self, **kwargs):
        service = WorkbenchService(directory=self.folder.name, **kwargs)
        self.services.append(service)
        return service

    def request(self, url, route, data=None):
        host, port = url.removeprefix('http://').rstrip('/').split(':')
        connection = HTTPConnection(host, int(port), timeout=3)
        try:
            connection.request('POST' if data is not None else 'GET', route,
                None if data is None else json.dumps(data),
                {} if data is None else {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def unused_port(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            return listener.getsockname()[1]

    def assert_port_released(self, port):
        with web.make_server(port=port, directory=self.folder.name):
            pass

    def test_ready_url_serves_catalog_without_creating_a_session_and_stops_repeatedly(self):
        service = self.service().start()
        url = service.wait_ready(3)
        status, doc = self.request(url, '/api/catalog')
        self.assertEqual(status, 200)
        self.assertEqual({e['id'] for e in doc['experiments']}, {'alpha', 'beta'})
        self.assertEqual(service.status().phase, 'ready')
        self.assertIsNone(service.active_session())
        self.assertFalse(service.cancel_start())
        self.assertTrue(service.stop_if_idle())
        self.assertTrue(service.stop_if_idle())
        self.assertTrue(service.join(3))
        self.assertEqual(service.status().phase, 'stopped')
        self.assert_port_released(int(url.split(':')[-1].rstrip('/')))

    def test_delayed_discovery_can_be_cancelled_without_publishing_a_url(self):
        entered, release = Event(), Event()
        original = web.discover
        def delayed(paths):
            entered.set()
            self.assertTrue(release.wait(3))
            return original(paths)
        port = self.unused_port()
        with patch.object(web, 'discover', side_effect=delayed):
            service = self.service(port=port).start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(service.status().phase, 'starting')
                self.assertIsNone(service.status().url)
                self.assertTrue(service.cancel_start())
                self.assertFalse(service.join(.01))
            finally:
                release.set()
            self.assertTrue(service.join(3))
        self.assertEqual(service.status().phase, 'stopped')
        self.assertIsNone(service.status().url)
        self.assert_port_released(port)

    def test_cancel_after_binding_before_request_loop_never_calls_shutdown(self):
        entered, release = Event(), Event()
        original = web.make_server
        port = self.unused_port()
        def delayed(*args, **kwargs):
            server = original(*args, **kwargs)
            server.shutdown = lambda: self.fail('shutdown before serving would deadlock')
            entered.set()
            self.assertTrue(release.wait(3))
            return server
        with patch.object(web, 'make_server', side_effect=delayed):
            service = self.service(port=port).start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(service.stop_if_idle())
            finally:
                release.set()
            self.assertTrue(service.join(3))
        self.assertIsNone(service.status().url)
        self.assert_port_released(port)

    def test_catalog_failure_is_not_readiness_and_releases_port(self):
        port = self.unused_port()
        with patch.object(web.Application, 'catalog', side_effect=OSError('catalog failed')):
            service = self.service(port=port).start()
            with self.assertRaises(OSError):
                service.wait_ready(3)
            self.assertTrue(service.join(3))
        self.assertEqual(service.status().phase, 'failed')
        self.assertIsNone(service.status().url)
        self.assert_port_released(port)

    def test_cancel_during_catalog_probe_drops_late_ready_result(self):
        entered, release = Event(), Event()
        original = web.Application.catalog
        def delayed(app, **kwargs):
            entered.set()
            release.wait(3)
            return original(app, **kwargs)
        port = self.unused_port()
        with patch.object(web.Application, 'catalog', delayed):
            service = self.service(port=port).start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(service.cancel_start())
                self.assertEqual(service.status().phase, 'stopping')
            finally:
                release.set()
            self.assertTrue(service.join(3))
        self.assertEqual(service.status().phase, 'stopped')
        self.assertIsNone(service.status().url)
        self.assert_port_released(port)

    def test_initialization_failure_after_binding_does_not_leak_listener(self):
        port = self.unused_port()
        with patch.object(web, 'Application', side_effect=OSError('store failed')):
            service = self.service(port=port).start()
            with self.assertRaisesRegex(OSError, 'store failed'):
                service.wait_ready(3)
            self.assertTrue(service.join(3))
        self.assert_port_released(port)

    def test_readiness_thread_start_failure_reports_error_and_releases_listener(self):
        port = self.unused_port()
        class UnstartedProbe:
            def start(self):
                raise RuntimeError('readiness thread unavailable')
            def join(self):
                raise AssertionError('must not join an unstarted probe')
        def thread_factory(*args, **kwargs):
            return UnstartedProbe() if kwargs.get('name') == 'Nuclemu-ready' else Thread(*args, **kwargs)
        with patch('nuclemu.web_service.Thread', side_effect=thread_factory):
            service = self.service(port=port).start()
            with self.assertRaisesRegex(OSError, 'readiness thread unavailable'):
                service.wait_ready(3)
            self.assertTrue(service.join(3))
        self.assertEqual(service.status().phase, 'failed')
        self.assert_port_released(port)

    def test_occupied_port_fails_without_touching_its_owner_and_new_attempt_succeeds(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            address = listener.getsockname()
            service = self.service(port=address[1]).start()
            with self.assertRaises(OSError):
                service.wait_ready(3)
            self.assertTrue(service.join(3))
            self.assertEqual(listener.getsockname(), address)
            with socket.create_connection(address, timeout=1):
                pass
        replacement = self.service().start()
        self.assertTrue(replacement.wait_ready(3).startswith('http://127.0.0.1:'))

    def test_active_session_blocks_idle_stop_without_freezing_or_discarding(self):
        now = [0]
        service = self.service(clock=lambda: now[0]).start()
        url = service.wait_ready(3)
        _, state = self.request(url, '/api/open', dict(experiment='beta'))
        identity = state['id']
        self.request(url, '/api/action', dict(session=identity, action='start_group', component='counter'))
        self.assertEqual(service.active_session(), identity)
        self.assertFalse(service.stop_if_idle())
        now[0] = 1
        _, state = self.request(url, '/api/state')
        self.assertTrue(state['running'])
        self.assertFalse(state['frozen'])
        self.assertEqual(state['instrument']['exposure_s'], 1)
        _, state = self.request(url, '/api/action', dict(session=identity, action='freeze'))
        self.request(url, '/api/action', dict(session=identity, action='discard', confirmation_id=state['confirmation_id']))
        self.assertTrue(service.stop_if_idle())
        self.assertTrue(service.join(3))

    def test_idle_stop_rejects_an_already_accepted_open_request_under_same_lock(self):
        accepted = Event()
        original = web.WorkbenchHandler.do_POST
        def observed(handler):
            accepted.set()
            return original(handler)
        service = self.service().start()
        url = service.wait_ready(3)
        server = service._server
        result = []
        with patch.object(web.WorkbenchHandler, 'do_POST', observed):
            with server.app_lock:
                request = Thread(target=lambda: result.append(self.request(url, '/api/open', dict(experiment='alpha'))))
                request.start()
                self.assertTrue(accepted.wait(2))
                self.assertTrue(service.stop_if_idle())
            request.join(3)
            self.assertFalse(request.is_alive())
        self.assertEqual(result[0][0], 503)
        self.assertIsNone(server.app.lab)
        self.assertTrue(service.join(3))

    def test_cancel_without_start_and_invalid_ports_are_safe(self):
        service = self.service()
        self.assertTrue(service.cancel_start())
        self.assertTrue(service.join(0))
        with self.assertRaises(ValueError):
            service.start()
        for port in (-1, 65536, True, '80'):
            with self.subTest(port=port):
                service = self.service(port=port).start()
                with self.assertRaises(ValueError):
                    service.wait_ready(3)
                self.assertTrue(service.join(3))

    def test_existing_launch_opens_browser_only_after_ready(self):
        service = self.service()
        def browser(url):
            self.assertEqual(service.status().phase, 'ready')
            self.assertEqual(self.request(url, '/api/catalog')[0], 200)
            service.stop(force=True)
        output = StringIO()
        with patch('nuclemu.web_service.WorkbenchService', return_value=service), patch.object(web.webbrowser, 'open', side_effect=browser) as opened, redirect_stdout(output):
            web.launch(directory=self.folder.name)
        opened.assert_called_once()
        self.assertIn(opened.call_args.args[0], output.getvalue())
        self.assertEqual(service.status().phase, 'stopped')

    def test_status_poll_stays_responsive_while_stop_waits_for_application_request(self):
        entered, release, checking, polled = Event(), Event(), Event(), Event()
        service = self.service().start()
        url = service.wait_ready(3)
        server = service._server
        original_lock = server.app_lock
        stopper = None
        class ObservedLock:
            def __enter__(self):
                if current_thread() is stopper:
                    checking.set()
                return original_lock.__enter__()
            def __exit__(self, *args):
                return original_lock.__exit__(*args)
        server.app_lock = ObservedLock()
        original_catalog = server.app.catalog
        def slow_catalog(**kwargs):
            entered.set()
            release.wait(3)
            return original_catalog(**kwargs)
        def poll():
            service.status()
            polled.set()
        with patch.object(server.app, 'catalog', side_effect=slow_catalog):
            reader = Thread(target=lambda: self.request(url, '/api/catalog'))
            reader.start()
            self.assertTrue(entered.wait(2))
            stopper = Thread(target=service.stop_if_idle)
            stopper.start()
            self.assertTrue(checking.wait(2))
            observer = Thread(target=poll)
            observer.start()
            try:
                self.assertTrue(polled.wait(.3), 'window status polling must not wait for the application lock')
            finally:
                release.set()
                reader.join(3)
                stopper.join(3)
                observer.join(3)
        self.assertTrue(service.join(3))


if __name__ == '__main__':
    unittest.main()
