"""Live listeners and readiness must identify the exact owning service."""

from dataclasses import replace
from http.client import HTTPConnection
import json
import os
import socket
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch

from nuclemu import web
from nuclemu.web_service import WorkbenchService
from tests.test_web_instrument_records import course


class ServiceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.services = []
        self.addCleanup(self.stop)
        self.now = 0

    def stop(self):
        for service in self.services:
            service.stop(force=True)
            self.assertTrue(service.join(3))

    def service(self, name, port=0):
        definition = replace(course(), id=name)
        service = WorkbenchService(port=port, directory=self.folder.name, clock=lambda: self.now)
        self.services.append(service)
        with patch.object(web, 'discover', return_value={name: definition}):
            service.start()
            service.wait_ready(3)
        return service

    def request(self, service, route, data=None):
        server = service._server
        connection = HTTPConnection(*server.server_address, timeout=2)
        try:
            connection.request('POST' if data is not None else 'GET', route,
                json.dumps(data) if data is not None else None,
                {'Content-Type': 'application/json'} if data is not None else {})
            response = connection.getresponse()
            return response.status, json.loads(response.read()), response.getheader('X-Nuclemu-Instance-ID')
        finally:
            connection.close()

    def test_fixed_port_conflict_never_reports_the_previous_service_as_ready(self):
        first = self.service('first')
        second = WorkbenchService(port=first._server.server_port, directory=self.folder.name)
        self.services.append(second)
        second.start()
        with self.assertRaises(OSError):
            second.wait_ready(3)
        self.assertTrue(second.join(3))
        self.assertIsNone(second.status().url)
        self.assertEqual(second.status().phase, 'failed')
        status, identity, header = self.request(first, '/api/identity')
        self.assertEqual(status, 200)
        self.assertEqual(identity['instance_id'], first.instance_id)
        self.assertEqual(header, first.instance_id)
        self.assertNotEqual(first.instance_id, second.instance_id)
        self.assertEqual(self.request(first, '/api/open', dict(experiment='second'))[0], 400)
        self.assertIsNone(first.active_session())

    def test_loopback_binding_does_not_reverse_resolve_a_hostname(self):
        with patch('socket.getfqdn', side_effect=AssertionError('Unexpected reverse DNS')) as lookup:
            service = self.service('first')
            self.assertEqual(service._server.server_name, '127.0.0.1')
            self.assertEqual(service._server.server_port, service._server.server_address[1])
            self.assertFalse(service._server.allow_reuse_port)
            self.assertEqual(self.request(service, '/api/identity')[1]['instance_id'], service.instance_id)
            lookup.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Winsock exclusive binding')
    def test_windows_exclusive_listener_cannot_be_rebound_with_reuseaddr(self):
        service = self.service('first')
        self.assertEqual(service._server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE), 1)
        self.assertEqual(service._server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR), 0)
        with socket.socket() as other:
            other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                other.bind(service._server.server_address)

    def test_valid_catalog_from_another_real_listener_is_not_our_readiness(self):
        first = self.service('first')
        second = WorkbenchService(directory=self.folder.name)
        self.services.append(second)
        # Simulate misrouting to a genuine older listener, not a malformed reply.
        def wrong_listener(*args, **kwargs):
            return HTTPConnection(*first._server.server_address, timeout=2)
        with patch('nuclemu.web_service.HTTPConnection', side_effect=wrong_listener):
            second.start()
            with self.assertRaisesRegex(OSError, 'different service instance'):
                second.wait_ready(3)
            self.assertTrue(second.join(3))
        self.assertIsNone(second.status().url)
        self.assertEqual(self.request(first, '/api/catalog')[1]['experiments'][0]['id'], 'first')

    def test_identity_read_is_lightweight_and_cannot_mutate_the_session(self):
        service = self.service('first')
        replies = []
        with service._server.app_lock:
            thread = Thread(target=lambda: replies.append(self.request(service, '/api/identity')))
            thread.start()
            thread.join(1)
            self.assertFalse(thread.is_alive(), 'identity waited for the application lock')
        self.assertEqual(replies[0][1], dict(product='Nuclemu', instance_id=service.instance_id, ready=True))
        self.assertEqual(service.status().instance_id, service.instance_id)
        self.assertEqual(self.request(service, '/api/identity', {})[0], 405)
        self.assertIsNone(service.active_session())
        with self.assertRaises(AttributeError):
            service.instance_id = 'changed'

    def test_os_ports_and_two_sessions_keep_acquisition_and_close_independent(self):
        first, second = self.service('first'), self.service('second')
        self.assertNotEqual(first.status().url, second.status().url)
        self.assertNotEqual(first.instance_id, second.instance_id)
        sessions = []
        for service, name, seed in ((first, 'first', 11), (second, 'second', 22)):
            status, state, header = self.request(service, '/api/open', dict(experiment=name, seed=seed))
            self.assertEqual(status, 200)
            self.assertEqual(header, service.instance_id)
            sessions.append(state['id'])
            self.request(service, '/api/action', dict(session=state['id'], action='output', output='detector', enabled=True))
            self.request(service, '/api/action', dict(session=state['id'], action='start_group', component='pair'))
        self.assertNotEqual(*sessions)
        self.now = 3
        self.assertEqual(self.request(first, '/api/state')[1]['instruments']['a']['exposure_s'], 3)
        self.assertEqual(self.request(second, '/api/state')[1]['instruments']['a']['exposure_s'], 3)
        self.assertEqual(self.request(second, '/api/action', dict(session=sessions[0], action='freeze'))[0], 400)
        first.discard_close(first.begin_close())
        self.assertTrue(first.join(3))
        self.now = 4
        state = self.request(second, '/api/state')[1]
        self.assertEqual(state['id'], sessions[1])
        self.assertFalse(state['frozen'])
        self.assertEqual(state['instruments']['a']['exposure_s'], 4)
        self.assertEqual(second.status().phase, 'ready')

    def test_injected_registration_is_published_with_our_ready_identity_and_closed(self):
        from nuclemu.launcher_instance import ServiceRegistration, discover_services
        from pathlib import Path
        root = Path(self.folder.name) / 'registration'
        registration = ServiceRegistration(directory=root)
        service = WorkbenchService(directory=self.folder.name, registration=registration).start()
        self.services.append(service)
        url = service.wait_ready(3)
        records = discover_services(directory=root)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].url, url)
        self.assertEqual(records[0].instance_id, service.instance_id)
        service.stop(force=True)
        self.assertTrue(service.join(3))
        self.assertEqual(discover_services(directory=root), [])

    def test_registration_failure_never_publishes_ready_and_closes_owner(self):
        registration = Mock()
        registration.publish.side_effect = OSError('registration write failed')
        service = WorkbenchService(directory=self.folder.name, registration=registration).start()
        self.services.append(service)
        with self.assertRaisesRegex(OSError, 'registration write failed'):
            service.wait_ready(3)
        self.assertTrue(service.join(3))
        self.assertIsNone(service.status().url)
        registration.close.assert_called_once()

    def test_cancel_without_start_releases_injected_registration(self):
        for method in ('begin_close', 'cancel_start', 'stop'):
            with self.subTest(method=method):
                registration = Mock()
                service = WorkbenchService(registration=registration)
                getattr(service, method)()
                registration.publish.assert_not_called()
                registration.close.assert_called_once()
                service.stop()
                registration.close.assert_called_once()

    def test_cancel_during_registration_publish_drops_late_ready_and_then_closes(self):
        entered, release = Event(), Event()
        registration = Mock()
        def publish(url, instance_id):
            entered.set()
            self.assertTrue(release.wait(3))
        registration.publish.side_effect = publish
        service = WorkbenchService(directory=self.folder.name, registration=registration).start()
        self.services.append(service)
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(service.status().phase, 'starting')
            self.assertTrue(service.cancel_start())
            self.assertEqual(service.status().phase, 'stopping')
            registration.close.assert_not_called()
        finally:
            release.set()
        self.assertTrue(service.join(3))
        self.assertIsNone(service.status().url)
        self.assertEqual(service.status().phase, 'stopped')
        registration.close.assert_called_once()

    def test_start_thread_failure_releases_injected_registration(self):
        registration = Mock()
        service = WorkbenchService(registration=registration)
        with patch('nuclemu.web_service.Thread.start', side_effect=RuntimeError('cannot start worker')):
            service.start()
        self.assertEqual(service.status().phase, 'failed')
        self.assertTrue(service.join(0))
        registration.publish.assert_not_called()
        registration.close.assert_called_once()
