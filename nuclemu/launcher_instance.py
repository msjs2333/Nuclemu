"""Private, process-owned service registrations and explicit desktop start plans."""

from contextlib import contextmanager
from dataclasses import dataclass
import errno
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import stat
from time import monotonic, sleep, time_ns
from urllib.parse import urlsplit
from uuid import uuid4


def _try_lock(fd):
    try:
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return False
        raise


def _unlock(fd):
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _mailbox_lock(fd, *, wait):
    deadline = monotonic() + 2
    acquired = _try_lock(fd)
    while not acquired and wait:
        if monotonic() >= deadline:
            raise OSError('启动器实例文件繁忙，请稍后重试。')
        sleep(.01)
        acquired = _try_lock(fd)
    try:
        yield acquired
    finally:
        if acquired:
            _unlock(fd)


def _open_file(path):
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError('启动器实例文件不是普通文件。')
        if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise OSError('启动器实例文件须仅当前用户可读写。')
        if info.st_size == 0:
            os.write(fd, b'\0')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _signal(fd, value=None):
    # Byte zero is the Windows lock; data lives outside that locked range.
    os.lseek(fd, 1, os.SEEK_SET)
    if value is None:
        return os.read(fd, 1) == b'1'
    os.write(fd, b'1' if value else b'0')


def _registry_root(directory):
    root = (Path.home() / '.nuclemu' if directory is None else Path(directory)) / 'services'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or (os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077)):
        raise OSError('服务登记目录须仅当前用户可访问。')
    return root


@contextmanager
def _registry_lock(root, *, wait=True):
    fd = _open_file(root / '.registry')
    try:
        with _mailbox_lock(fd, wait=wait) as acquired:
            yield acquired
    finally:
        os.close(fd)


@dataclass(frozen=True)
class ServiceConfiguration:
    paths: tuple[str, ...]
    port: int
    workbench_directory: str


def _configuration(paths, port, workbench_directory):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('端口须为 0 或 1–65535 的整数。')
    canonical = lambda path: os.path.normcase(str(Path(path).resolve()))
    store = workbench_directory if workbench_directory is not None else Path.home() / '.nuclemu/workbench'
    return ServiceConfiguration(tuple(sorted(set(map(canonical, paths)))), port, canonical(store))


@dataclass(frozen=True)
class RegisteredService:
    registration_id: str
    configuration: ServiceConfiguration
    gui: bool
    url: str | None
    instance_id: str | None
    preferred: bool
    created_ns: int
    state: str

    @property
    def paths(self):
        return self.configuration.paths

    @property
    def port(self):
        return self.configuration.port


def _read_record(fd, identity):
    os.lseek(fd, 2, os.SEEK_SET)
    try:
        value = json.loads(os.read(fd, 65537))
        configuration = value['configuration']
        if (value['registration_id'] != identity or value['state'] not in ('choice', 'starting', 'ready')
                or type(value['gui']) is not bool
                or type(value['preferred']) is not bool or type(value['created_ns']) is not int
                or not isinstance(configuration['paths'], list)
                or any(not isinstance(p, str) for p in configuration['paths'])
                or type(configuration['port']) is not int or not 0 <= configuration['port'] <= 65535
                or not isinstance(configuration['workbench_directory'], str)):
            return None
        checked = ServiceConfiguration(tuple(configuration['paths']), configuration['port'], configuration['workbench_directory'])
        url, instance = value['url'], value['instance_id']
        if url is not None:
            parsed = urlsplit(url)
            if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
                    or parsed.username or parsed.password or parsed.path != '/' or parsed.query or parsed.fragment
                    or not isinstance(instance, str) or not instance):
                return None
        elif instance is not None:
            return None
        return RegisteredService(identity, checked, value['gui'], url, instance, value['preferred'], value['created_ns'], value['state'])
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        return None


def _locked_records(root):
    records = []
    for path in sorted(root.glob('*.instance')):
        if len(path.stem) != 32 or any(c not in '0123456789abcdef' for c in path.stem):
            continue
        fd = _open_file(path)
        stale = False
        try:
            if _try_lock(fd):
                _unlock(fd)
                stale = True
            else:
                record = _read_record(fd, path.stem)
                if record is not None:
                    records.append(record)
        finally:
            os.close(fd)
        if stale:
            # Callers hold the registry lock, including while a new owner is
            # created. Close first because Windows cannot unlink an open file.
            path.unlink(missing_ok=True)
    return sorted(records, key=lambda r: (not r.preferred, r.created_ns, r.registration_id))


def service_is_ready(record):
    """Verify only the exact loopback URL of a live registration, never scan."""
    if record.url is None:
        return False
    connection = HTTPConnection('127.0.0.1', urlsplit(record.url).port, timeout=.5)
    try:
        connection.request('GET', '/api/identity')
        response = connection.getresponse()
        identity = json.loads(response.read(4096))
        return (response.status == 200 and identity.get('product') == 'Nuclemu'
                and identity.get('instance_id') == record.instance_id and identity.get('ready') is True)
    except (OSError, HTTPException, ValueError, AttributeError):
        return False
    finally:
        connection.close()


def discover_services(directory=None):
    root = _registry_root(directory)
    with _registry_lock(root):
        records = _locked_records(root)
    return [record for record in records if record.url is not None and service_is_ready(record)]


class ServiceRegistration:
    """One process owns one locked record and an optional GUI activation bit."""

    def __init__(self, paths=(), *, port=0, gui=False, directory=None,
                 workbench_directory=None, _defer=False, preferred=True):
        self.root = _registry_root(directory)
        self.configuration = _configuration(paths, port, workbench_directory)
        self.registration_id = uuid4().hex
        self.gui = bool(gui)
        self.preferred, self.created_ns = preferred, time_ns()
        self._starting = True
        self.path = self.root / (self.registration_id + '.instance')
        self._fd = None
        if not _defer:
            with _registry_lock(self.root):
                self._create()

    def _create(self):
        fd = _open_file(self.path)
        try:
            if not _try_lock(fd):
                raise OSError('服务登记已被其他进程占用。')
            self._fd = fd
            _signal(fd, False)
            self._publish(None, None)
        except BaseException:
            os.close(fd)
            self._fd = None
            raise

    def _publish(self, url, instance_id):
        from dataclasses import asdict
        value = dict(registration_id=self.registration_id, configuration=asdict(self.configuration),
                     gui=self.gui, url=url, instance_id=instance_id,
                     preferred=self.preferred, created_ns=self.created_ns,
                     state='ready' if url else 'starting' if self._starting else 'choice')
        os.lseek(self._fd, 2, os.SEEK_SET)
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        if len(data) > 65536:
            raise ValueError('服务登记配置过长。')
        if os.write(self._fd, data) != len(data):
            raise OSError('无法完整写入服务登记。')
        os.ftruncate(self._fd, len(data) + 2)

    def publish(self, url, instance_id):
        with _registry_lock(self.root):
            if self._fd is None:
                raise OSError('服务登记已关闭。')
            self._publish(url, instance_id)

    def take_activation(self):
        if self._fd is None:
            return False
        with _registry_lock(self.root, wait=False) as acquired:
            if not acquired or self._fd is None:
                return False
            pending = _signal(self._fd)
            if pending:
                _signal(self._fd, False)
            return pending

    def close(self):
        if self._fd is None:
            return
        try:
            with _registry_lock(self.root):
                if self._fd is None:
                    return
                _unlock(self._fd)
                os.close(self._fd)
                self._fd = None
                self.path.unlink(missing_ok=True)
        finally:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None


def _port_occupied(port):
    if not port:
        return False
    import socket
    with socket.socket() as listener:
        if os.name == 'nt':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(('127.0.0.1', port))
            return False
        except OSError as error:
            if error.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
            return True


def _activate(root, record):
    with _registry_lock(root):
        fd = _open_file(root / (record.registration_id + '.instance'))
        try:
            if _try_lock(fd):
                _unlock(fd)
                raise ValueError('已有工作台已退出，请重新启动。')
            current = _read_record(fd, record.registration_id)
            if current != record:
                raise ValueError('已有工作台状态已改变，请重新查看。')
            if record.gui:
                _signal(fd, True)
        finally:
            os.close(fd)


@dataclass
class LaunchPlan:
    kind: str
    owner: ServiceRegistration | None
    existing: list[RegisteredService]
    port: int
    root: Path

    def use_existing(self, record):
        if record not in self.existing or not service_is_ready(record):
            raise ValueError('已有工作台已退出或尚未就绪，请重新查看。')
        _activate(self.root, record)
        return record.url

    def start_new(self):
        selected = self.port
        if self.port and _port_occupied(self.port):
            if any(service_is_ready(r) and urlsplit(r.url).port == self.port for r in self.existing if r.url):
                selected = 0
            else:
                raise OSError(f'端口 {self.port} 已由其他程序占用，请在设置中更换端口。')
        if self.owner is None:
            raise ValueError('此启动计划已唤回已有工作台。')
        with _registry_lock(self.root):
            self.owner._starting = True
            self.owner._publish(None, None)
        return selected

    def close(self):
        if self.owner is not None:
            self.owner.close()

def plan_start(paths=(), *, port=0, directory=None, registry_directory=None,
               new_instance=False):
    """Plan on a worker after the first GUI frame; never open or stop a service."""
    owner = ServiceRegistration(paths, port=port, gui=True, directory=registry_directory,
                                workbench_directory=directory, preferred=not new_instance, _defer=True)
    root, configuration = owner.root, owner.configuration
    with _registry_lock(root):
        records = _locked_records(root)
    ready = [r for r in records if r.url is not None and service_is_ready(r)]
    occupied = _port_occupied(port)
    with _registry_lock(root):
        # Recheck pending owners under the short registry lock so concurrent
        # first launches cannot both establish the default desktop.
        records = _locked_records(root)
        # Activation only signals a live GUI's mailbox, never reuses its URL.
        # It also coalesces a GUI that finished startup during HTTP discovery.
        matching = next((r for r in records if r.gui and r.configuration == configuration
                         and r.state != 'choice'), None)
        # A surviving parallel GUI may use an automatic port while retaining
        # this requested fixed port. Verify its current occupant before activation.
        if occupied and not any(r in records and urlsplit(r.url).port == port for r in ready):
            if matching is not None and matching.state == 'starting':
                raise OSError('已有工作台正在启动，请稍后重试。')
            raise OSError(f'端口 {port} 已由其他程序占用，请在设置中更换端口。')
        if matching is not None and not new_instance:
            fd = _open_file(root / (matching.registration_id + '.instance'))
            try:
                _signal(fd, True)
            finally:
                os.close(fd)
            return LaunchPlan('activated', None, [], port, root)
        if any(r.gui and r.state == 'starting' for r in records):
            raise OSError('已有工作台正在启动，请稍后重试。')
        owner._starting = not bool(ready)
        owner._create()
    return LaunchPlan('choose' if ready else 'start', owner, ready, port, root)
