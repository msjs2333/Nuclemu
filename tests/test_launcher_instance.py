"""Real process ownership, activation and recovery tests."""

import json
import os
from pathlib import Path
from queue import Queue
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic
import unittest
from unittest.mock import patch

from nuclemu.launcher_instance import acquire_or_activate


WORKER = r'''
import json, sys
from nuclemu.launcher_instance import acquire_or_activate
if sys.argv[2] == 'mailbox':
    import os
    from pathlib import Path
    from nuclemu.launcher_instance import _open_file, _try_lock
    fd = _open_file(Path(sys.argv[1]) / 'launcher-instance' / 'activation')
    print(json.dumps(_try_lock(fd)), flush=True)
    input()
    os.close(fd)
    sys.exit(0)
if sys.argv[2] == 'race':
    input()
owner = acquire_or_activate(sys.argv[1])
print(json.dumps(owner is not None), flush=True)
if owner is not None:
    try:
        for command in sys.stdin:
            if command.strip() == 'poll':
                print(json.dumps(owner.take_activation()), flush=True)
            elif command.strip() == 'close':
                break
    finally:
        owner.close()
'''


class LauncherInstanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / '用户 设置'
        self.processes = []
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    def worker(self, mode='hold', directory=None):
        process = subprocess.Popen(
            [sys.executable, '-u', '-c', WORKER, str(directory or self.directory), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', cwd=Path(__file__).resolve().parents[1])
        self.processes.append(process)
        return process

    def result(self, process):
        lines = Queue()
        Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        line = lines.get(timeout=5)
        self.assertTrue(line, 'worker exited before reporting a result')
        return json.loads(line)

    def command(self, process, command):
        process.stdin.write(command + '\n')
        process.stdin.flush()

    def test_repeat_launch_signals_starting_owner_and_coalesces(self):
        first = self.worker()
        self.assertTrue(self.result(first))
        # No GUI, service or URL is ready yet: ownership alone handles launches.
        for _ in range(3):
            other = self.worker()
            self.assertFalse(self.result(other))
            self.assertEqual(other.wait(timeout=5), 0)
        self.command(first, 'poll')
        self.assertTrue(self.result(first))
        self.command(first, 'poll')
        self.assertFalse(self.result(first))
        self.command(first, 'close')
        self.assertEqual(first.wait(timeout=5), 0)

    def test_simultaneous_processes_have_exactly_one_owner(self):
        processes = [self.worker('race') for _ in range(8)]
        for process in processes:
            self.command(process, 'go')
        results = [self.result(process) for process in processes]
        self.assertEqual(sum(results), 1)
        owner = processes[results.index(True)]
        self.command(owner, 'poll')
        self.assertTrue(self.result(owner))
        self.command(owner, 'close')
        self.assertEqual(owner.wait(timeout=5), 0)

    def test_killed_owner_is_reclaimed_and_old_activation_is_cleared(self):
        first = self.worker()
        self.assertTrue(self.result(first))
        other = self.worker()
        self.assertFalse(self.result(other))
        other.wait(timeout=5)
        first.kill()
        first.wait(timeout=5)
        replacement = self.worker()
        self.assertTrue(self.result(replacement))
        self.command(replacement, 'poll')
        self.assertFalse(self.result(replacement))

    def test_normal_close_then_restart_and_idempotent_close(self):
        owner = acquire_or_activate(self.directory)
        self.assertIsNotNone(owner)
        self.assertIsNone(acquire_or_activate(self.directory))
        self.assertTrue(owner.take_activation())
        owner.close()
        owner.close()
        self.assertFalse(owner.take_activation())
        replacement = acquire_or_activate(self.directory)
        self.addCleanup(replacement.close)
        self.assertFalse(replacement.take_activation())

    def test_two_settings_roots_are_independent(self):
        first = self.worker()
        second = self.worker(directory=self.directory / 'separate')
        self.assertTrue(self.result(first))
        self.assertTrue(self.result(second))

    def test_poll_does_not_wait_for_busy_mailbox_or_drop_activation(self):
        owner = acquire_or_activate(self.directory)
        self.addCleanup(owner.close)
        self.assertIsNone(acquire_or_activate(self.directory))
        blocker = self.worker('mailbox')
        self.assertTrue(self.result(blocker))
        started = monotonic()
        self.assertFalse(owner.take_activation())
        self.assertLess(monotonic() - started, .2)
        blocker.kill()
        blocker.wait(timeout=5)
        self.assertTrue(owner.take_activation())
        self.assertFalse(owner.take_activation())

    def test_signal_write_failure_releases_new_ownership(self):
        with patch('nuclemu.launcher_instance._signal', side_effect=OSError('write failed')):
            with self.assertRaisesRegex(OSError, 'write failed'):
                acquire_or_activate(self.directory)
        owner = acquire_or_activate(self.directory)
        self.assertIsNotNone(owner)
        owner.close()

    def test_repeated_launch_after_owner_exits_is_new_owner(self):
        first = self.worker()
        self.assertTrue(self.result(first))
        self.command(first, 'close')
        self.assertEqual(first.wait(timeout=5), 0)
        replacement = self.worker()
        self.assertTrue(self.result(replacement))

    def test_http_listener_and_headless_service_are_not_desktop_owners(self):
        from nuclemu.web_service import WorkbenchService
        with socket.socket() as unrelated:
            unrelated.bind(('127.0.0.1', 0))
            unrelated.listen()
            service = WorkbenchService(directory=self.directory / 'workbench').start()
            try:
                service.wait_ready(timeout=5)
                owner = acquire_or_activate(self.directory)
                try:
                    self.assertIsNotNone(owner)
                    self.assertFalse(owner.take_activation())
                    self.assertEqual(service.status().phase, 'ready')
                    self.assertGreater(unrelated.getsockname()[1], 0)
                finally:
                    owner.close()
            finally:
                service.stop(force=True)
                self.assertTrue(service.join(5))

    def test_invalid_instance_path_fails_instead_of_bypassing_lock(self):
        self.directory.mkdir(parents=True)
        (self.directory / 'launcher-instance').write_text('not a directory')
        with self.assertRaises(OSError):
            acquire_or_activate(self.directory)

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions')
    def test_shared_permissions_and_symlink_are_rejected(self):
        self.directory.mkdir(parents=True)
        root = self.directory / 'launcher-instance'
        root.mkdir(mode=0o755)
        root.chmod(0o755)
        with self.assertRaises(OSError):
            acquire_or_activate(self.directory)
        root.rmdir()
        target = self.directory / 'target'
        target.mkdir(mode=0o700)
        root.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            acquire_or_activate(self.directory)


if __name__ == '__main__':
    unittest.main()
