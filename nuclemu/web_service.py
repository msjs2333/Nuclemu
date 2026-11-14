"""Own one cancellable loopback service without a desktop dependency."""

from dataclasses import dataclass
from http.client import HTTPConnection
import json
from threading import Condition, Event, Thread
from time import monotonic


@dataclass(frozen=True)
class ServiceStatus:
    phase: str
    url: str | None = None
    error: Exception | None = None


class WorkbenchService:
    def __init__(self, paths=(), *, port=0, directory=None, clock=monotonic):
        self.paths = tuple(paths)
        self.port, self.directory, self.clock = port, directory, clock
        self._condition = Condition()
        self._cancel = Event()
        self._phase = 'new'
        self._url = None
        self._error = None
        self._server = None
        self._worker = None

    def status(self):
        with self._condition:
            return ServiceStatus(self._phase, self._url, self._error)

    def start(self):
        with self._condition:
            if self._phase != 'new':
                raise ValueError('Create a new service for each startup attempt')
            self._phase = 'starting'
            try:
                self._worker = Thread(target=self._run, name='Nuclemu-service', daemon=True)
                self._worker.start()
            except Exception as error:
                self._error, self._phase = error, 'failed'
                self._worker = None
                self._condition.notify_all()
        return self

    def wait_ready(self, timeout=None):
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while self._phase in ('new', 'starting'):
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError('The workbench service is not ready')
                self._condition.wait(.1 if remaining is None else min(.1, remaining))
            if self._phase == 'ready':
                return self._url
            if self._error is not None:
                if isinstance(self._error, (ValueError, OSError, ImportError)):
                    raise self._error
                raise OSError(str(self._error)) from self._error
            raise OSError('Workbench startup was cancelled')

    def cancel_start(self):
        with self._condition:
            if self._phase not in ('new', 'starting'):
                return False
            self._request_stop()
            return True

    def _request_stop(self):
        self._cancel.set()
        if self._worker is None:
            self._phase = 'stopped'
        else:
            self._phase = 'stopping'
        self._condition.notify_all()

    def active_session(self):
        with self._condition:
            server = self._server
        if server is None:
            return None
        with server.app_lock:
            return server.app.lab.id if server.app.lab is not None else None

    def stop_if_idle(self):
        return self.stop()

    def stop(self, *, force=False):
        """Check and gate mutations under the same lock as HTTP requests.

        Call this off the window thread: an in-flight application request may
        still hold the application lock. Startup cancellation needs no such lock.
        """
        if type(force) is not bool:
            raise ValueError('force must be boolean')
        with self._condition:
            if self._phase in ('stopped', 'failed', 'stopping'):
                return True
            server = self._server
            if self._phase in ('new', 'starting') or server is None:
                self._request_stop()
                return True
        # Do not hold the status lock while an application request finishes:
        # the window must remain able to poll status while a closer waits.
        with server.app_lock:
            with self._condition:
                if self._phase != 'ready' or self._server is not server:
                    return True
                if server.app.lab is not None and not force:
                    return False
                server.accepting_requests = False
                self._request_stop()
                return True

    def join(self, timeout=None):
        worker = self._worker
        if worker is None:
            return True
        worker.join(timeout)
        return not worker.is_alive()

    def _probe(self, server):
        connection = HTTPConnection(*server.server_address, timeout=2)
        try:
            if self._cancel.is_set():
                return
            connection.request('GET', '/api/catalog')
            response = connection.getresponse()
            document = json.loads(response.read())
            if response.status != 200 or not isinstance(document.get('experiments'), list):
                raise OSError('The workbench catalog did not become ready')
            with server.app_lock:
                with self._condition:
                    if not self._cancel.is_set():
                        server.accepting_requests = True
                        self._url = f'http://127.0.0.1:{server.server_port}/'
                        self._phase = 'ready'
                        self._condition.notify_all()
        except Exception as error:
            with self._condition:
                if not self._cancel.is_set():
                    self._error = error if isinstance(error, OSError) else OSError(str(error))
                    self._cancel.set()
        finally:
            connection.close()

    def _run(self):
        server, probe, probe_started = None, None, False
        try:
            from .web import make_server
            server = make_server(self.paths, port=self.port, directory=self.directory, clock=self.clock)
            server.timeout = .05
            server.accepting_requests = False
            with self._condition:
                self._server = server
                if self._cancel.is_set():
                    return
            probe = Thread(target=self._probe, args=(server,), name='Nuclemu-ready', daemon=True)
            probe.start()
            probe_started = True
            # handle_request has a bounded wait and no shutdown-before-serve
            # handshake. The owning worker alone closes this listener.
            while not self._cancel.is_set():
                server.handle_request()
        except BaseException as error:
            with self._condition:
                if not self._cancel.is_set():
                    self._error = error if isinstance(error, Exception) else OSError(str(error))
        finally:
            if server is not None:
                try:
                    server.server_close()
                except Exception as error:
                    with self._condition:
                        self._error = self._error or error
            if probe_started:
                probe.join()
            with self._condition:
                self._server = None
                self._phase = 'failed' if self._error is not None else 'stopped'
                self._condition.notify_all()
