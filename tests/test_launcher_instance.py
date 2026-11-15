"""Real process leases, listener identities and desktop ownership policy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from queue import Queue
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from nuclemu.launcher_instance import ServiceRegistration, discover_services, plan_start
from nuclemu.web_service import WorkbenchService


WORKER = '''
import json,sys
from nuclemu.launcher_instance import plan_start
input()
plan=plan_start(registry_directory=sys.argv[1],port=int(sys.argv[2]))
print(json.dumps(plan.kind),flush=True)
if plan.owner:
    try:
        for command in sys.stdin:
            if command.strip()=='poll': print(json.dumps(plan.owner.take_activation()),flush=True)
            if command.strip()=='close': break
    finally: plan.close()
'''


class LauncherInstanceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = self.root / 'store'
        self.resources = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for resource in reversed(self.resources):
            if isinstance(resource, WorkbenchService):
                resource.stop(force=True)
                self.assertTrue(resource.join(5))
            elif isinstance(resource, subprocess.Popen):
                if resource.poll() is None:
                    resource.kill()
                resource.communicate(timeout=5)
            else:
                resource.close()

    def plan(self, paths=(), **fields):
        result = plan_start(paths, directory=self.store, registry_directory=self.root, **fields)
        self.resources.append(result)
        return result

    def start(self, plan):
        selected = plan.start_new()
        service = WorkbenchService(directory=self.store, port=selected, registration=plan.owner).start()
        self.resources.append(service)
        service.wait_ready(5)
        return service

    def test_same_canonical_starting_configuration_coalesces(self):
        original = self.plan([self.root / 'course', self.root / './course'])
        self.assertEqual(original.kind, 'start')
        same = self.plan([self.root / 'course'])
        self.assertEqual(same.kind, 'activated')
        self.assertTrue(original.owner.take_activation())
        self.assertFalse(original.owner.take_activation())
        with self.assertRaisesRegex(OSError, '正在启动'):
            self.plan([self.root / 'other-course'])
        with self.assertRaisesRegex(OSError, '正在启动'):
            self.plan(new_instance=True)

    def test_first_owner_is_preferred_then_surviving_independent_window_is_activated(self):
        first = self.plan()
        first_service = self.start(first)
        second = self.plan(new_instance=True)
        self.assertEqual(second.kind, 'choose')
        second_service = self.start(second)
        self.assertNotEqual(first_service.status().url, second_service.status().url)
        self.assertEqual(self.plan().kind, 'activated')
        self.assertTrue(first.owner.take_activation())
        self.assertFalse(second.owner.take_activation())
        first_service.stop(force=True)
        self.assertTrue(first_service.join(5))
        self.assertEqual(self.plan().kind, 'activated')
        self.assertTrue(second.owner.take_activation())
        self.assertEqual(second_service.status().phase, 'ready')

    def test_startup_becoming_ready_between_samples_still_activates_existing_gui(self):
        first = self.plan()
        def became_ready(port):
            first.owner.publish('http://127.0.0.1:54321/', 'listener-identity')
            return False
        with patch('nuclemu.launcher_instance._port_occupied', side_effect=became_ready):
            repeated = self.plan()
        self.assertEqual(repeated.kind, 'activated')
        self.assertTrue(first.owner.take_activation())
        self.assertEqual(len(list((self.root / 'services').glob('*.instance'))), 1)

    def test_temporary_health_probe_failure_does_not_duplicate_live_matching_gui(self):
        first = self.plan()
        self.start(first)
        with patch('nuclemu.launcher_instance.service_is_ready', return_value=False):
            repeated = self.plan()
        self.assertEqual(repeated.kind, 'activated')
        self.assertTrue(first.owner.take_activation())

    def test_headless_or_different_course_offer_explicit_choice_without_changing_old_service(self):
        registration = ServiceRegistration(directory=self.root, workbench_directory=self.store)
        self.resources.append(registration)
        old = WorkbenchService(directory=self.store, registration=registration).start()
        self.resources.append(old)
        old.wait_ready(5)
        choice = self.plan([self.root / 'new-course'])
        self.assertEqual(choice.kind, 'choose')
        self.assertFalse(choice.existing[0].gui)
        self.assertEqual(choice.use_existing(choice.existing[0]), old.status().url)
        # A failed browser handoff can retain this choice and try another action.
        self.assertIsNotNone(choice.owner._fd)
        self.assertEqual(old.status().phase, 'ready')
        self.assertEqual(len(discover_services(self.root)), 1)

    def test_real_headless_cli_is_discoverable_and_reuse_preserves_its_process(self):
        home = self.root / 'cli-home'
        home.mkdir()
        environment = dict(os.environ, USERPROFILE=str(home), HOME=str(home), PYTHONIOENCODING='utf-8')
        process = subprocess.Popen([sys.executable, '-u', '-m', 'nuclemu', 'serve', '--no-gui'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env=environment)
        self.resources.append(process)
        output = Queue()
        Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()
        line = output.get(timeout=10)
        self.assertIn('http://127.0.0.1:', line)
        registry = home / '.nuclemu'
        records = discover_services(registry)
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].gui)
        self.assertIn(records[0].url, line)
        choice = plan_start(directory=self.store, registry_directory=registry)
        self.resources.append(choice)
        self.assertEqual(choice.kind, 'choose')
        self.assertEqual(choice.use_existing(choice.existing[0]), records[0].url)
        self.assertIsNone(process.poll())
        choice.close()
        self.assertEqual(len(discover_services(registry)), 1)
        stale = registry / 'services' / (records[0].registration_id + '.instance')
        process.kill()
        process.wait(5)
        self.assertEqual(discover_services(registry), [])
        self.assertFalse(stale.exists())

    def test_choice_placeholder_is_not_activated_as_a_workbench(self):
        first = self.plan()
        self.start(first)
        waiting = self.plan([self.root / 'other-course'])
        another = self.plan([self.root / 'other-course'])
        self.assertEqual((waiting.kind, another.kind), ('choose', 'choose'))
        self.assertFalse(waiting.owner.take_activation())

    def test_occupied_registered_port_changes_only_explicit_parallel_start_to_auto(self):
        first = self.plan()
        old = self.start(first)
        port = int(old.status().url.rsplit(':', 1)[1].rstrip('/'))
        parallel = self.plan(port=port)
        self.assertEqual(parallel.kind, 'choose')
        self.assertEqual(parallel.start_new(), 0)
        self.assertEqual(old.status().phase, 'ready')

    def test_unknown_occupied_port_is_an_error_and_never_becomes_an_automatic_port(self):
        with socket.socket() as foreign:
            foreign.bind(('127.0.0.1', 0))
            foreign.listen()
            port = foreign.getsockname()[1]
            with self.assertRaisesRegex(OSError, str(port)):
                self.plan(port=port)
            self.assertNotEqual(foreign.fileno(), -1)

    def test_foreign_listener_on_original_fixed_port_blocks_activation_of_parallel_survivor(self):
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        first = self.plan(port=port)
        original = self.start(first)
        second = self.plan(port=port, new_instance=True)
        survivor = self.start(second)
        self.assertNotEqual(original.status().url, survivor.status().url)
        self.assertEqual(self.plan(port=port).kind, 'activated')
        self.assertTrue(first.owner.take_activation())
        self.assertFalse(second.owner.take_activation())
        original.stop(force=True)
        self.assertTrue(original.join(5))
        with socket.socket() as foreign:
            if os.name != 'nt':
                # Rebind the released listener while accepted connections are in TIME_WAIT.
                foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            foreign.bind(('127.0.0.1', port))
            foreign.listen()
            with self.assertRaisesRegex(OSError, str(port)):
                self.plan(port=port)
            self.assertFalse(second.owner.take_activation())
            self.assertEqual(survivor.status().phase, 'ready')
            self.assertEqual(len(discover_services(self.root)), 1)
        self.assertEqual(self.plan(port=port).kind, 'activated')
        self.assertTrue(second.owner.take_activation())

    def test_occupied_fixed_port_without_verified_identity_does_not_activate_ready_gui(self):
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        first = self.plan(port=port)
        self.start(first)
        with patch('nuclemu.launcher_instance.service_is_ready', return_value=False):
            with self.assertRaisesRegex(OSError, str(port)):
                self.plan(port=port)
        self.assertFalse(first.owner.take_activation())

    def test_occupied_fixed_port_during_matching_startup_requests_retry_without_activation(self):
        with socket.socket() as foreign:
            foreign.bind(('127.0.0.1', 0))
            port = foreign.getsockname()[1]
            with patch('nuclemu.launcher_instance._port_occupied', return_value=False):
                first = self.plan(port=port)
            foreign.listen()
            with self.assertRaisesRegex(OSError, '正在启动'):
                self.plan(port=port)
            self.assertFalse(first.owner.take_activation())

    def test_identity_mismatch_and_malformed_http_are_not_reusable(self):
        class Identity(BaseHTTPRequestHandler):
            body = b'{"product":"Nuclemu","instance_id":"wrong","ready":true}'
            malformed = False
            def do_GET(self):
                if self.malformed:
                    self.wfile.write(b'not-an-http-response\r\n')
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(self.body)))
                self.end_headers()
                self.wfile.write(self.body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Identity)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            registration = ServiceRegistration(directory=self.root)
            self.resources.append(registration)
            registration.publish(f'http://127.0.0.1:{server.server_port}/', 'expected')
            self.assertEqual(discover_services(self.root), [])
            Identity.body = b'{'
            self.assertEqual(discover_services(self.root), [])
            Identity.malformed = True
            self.assertEqual(discover_services(self.root), [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

    def test_simultaneous_processes_and_killed_owner_recovery(self):
        self.concurrent_processes_and_recovery(0)

    def test_simultaneous_fixed_port_processes_and_killed_owner_recovery(self):
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        self.concurrent_processes_and_recovery(port)

    def concurrent_processes_and_recovery(self, port):
        processes = []
        for _ in range(6):
            process = subprocess.Popen([sys.executable, '-u', '-c', WORKER, str(self.root), str(port)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.resources.append(process)
            processes.append(process)
        for process in processes:
            process.stdin.write('go\n')
            process.stdin.flush()
        results = []
        for process in processes:
            queue = Queue()
            Thread(target=lambda p=process,q=queue: q.put(p.stdout.readline()), daemon=True).start()
            line = queue.get(timeout=10)
            self.assertTrue(line)
            results.append(json.loads(line))
        self.assertEqual(results.count('start'), 1)
        self.assertEqual(results.count('activated'), 5)
        owner = processes[results.index('start')]
        owner.kill()
        owner.wait(5)
        stale = list((self.root / 'services').glob('*.instance'))
        self.assertEqual(len(stale), 1)
        replacement = plan_start(registry_directory=self.root, port=port)
        self.resources.append(replacement)
        self.assertEqual(replacement.kind, 'start')
        self.assertFalse(replacement.owner.take_activation())
        self.assertFalse(stale[0].exists())

    def test_bad_private_registry_fails_without_bypassing_discovery(self):
        (self.root / 'services').write_text('not a directory')
        with self.assertRaises(OSError):
            self.plan()

    def test_service_closing_before_poll_or_close_acquires_registry_lock_is_safe(self):
        from nuclemu.launcher_instance import _registry_lock
        for operation in ('take_activation', 'close'):
            with self.subTest(operation=operation):
                registration = ServiceRegistration(directory=self.root)
                self.resources.append(registration)
                raced = False
                def close_before_lock(root, *, wait=True):
                    nonlocal raced
                    if not raced:
                        raced = True
                        registration.close()
                    return _registry_lock(root, wait=wait)
                with patch('nuclemu.launcher_instance._registry_lock', side_effect=close_before_lock):
                    result = getattr(registration, operation)()
                if operation == 'take_activation':
                    self.assertFalse(result)
                self.assertIsNone(registration._fd)

    @unittest.skipIf(os.name == 'nt', 'POSIX private-directory permission check')
    def test_world_readable_registry_is_rejected(self):
        root = self.root / 'services'
        root.mkdir(mode=0o755)
        with self.assertRaises(OSError):
            self.plan()


if __name__ == '__main__':
    unittest.main()
