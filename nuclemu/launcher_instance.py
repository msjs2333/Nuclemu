"""Per-user desktop ownership and coalesced activation, without a listener.

The caller holds the returned owner until its window and service have closed.
Only desktop entry points participate; HTTP ports and process IDs play no role.
Persistent lock files must not be unlinked: another process may hold their inode.
"""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat
from time import monotonic, sleep


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


class LauncherInstance:
    """Owned OS lock. Consume activation from the Tk event loop, then close."""

    def __init__(self, owner_fd, mailbox_fd):
        self._owner_fd = owner_fd
        self._mailbox_fd = mailbox_fd

    def take_activation(self):
        """Return and clear a pending activation; never wait for another caller."""
        if self._owner_fd is None:
            return False
        with _mailbox_lock(self._mailbox_fd, wait=False) as acquired:
            if not acquired:
                return False
            pending = _signal(self._mailbox_fd)
            if pending:
                _signal(self._mailbox_fd, False)
            return pending

    def close(self):
        """Release ownership. OS process termination releases it as well."""
        if self._owner_fd is None:
            return
        try:
            with _mailbox_lock(self._mailbox_fd, wait=True):
                _signal(self._mailbox_fd, False)
                _unlock(self._owner_fd)
        finally:
            os.close(self._owner_fd)
            os.close(self._mailbox_fd)
            self._owner_fd = self._mailbox_fd = None


def acquire_or_activate(directory=None):
    """Own the user's desktop, or signal its owner and return None.

    directory is the per-user settings root, default ~/.nuclemu. Tests may
    supply a separate root. Errors propagate as OSError; never launch a second
    desktop merely because its ownership files cannot be accessed.
    """
    root = (Path(directory) if directory is not None else Path.home() / '.nuclemu') / 'launcher-instance'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise OSError('启动器实例目录不是普通目录。')
    if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise OSError('启动器实例目录须仅当前用户可访问。')
    owner_fd = mailbox_fd = None
    owned = False
    transferred = False
    try:
        mailbox_fd = _open_file(root / 'activation')
        # This short lock serializes acquire, signal and close. Retest ownership
        # inside it so a closing owner cannot swallow a new launch request.
        with _mailbox_lock(mailbox_fd, wait=True):
            owner_fd = _open_file(root / 'owner')
            owned = _try_lock(owner_fd)
            _signal(mailbox_fd, not owned)
        if owned:
            instance = LauncherInstance(owner_fd, mailbox_fd)
            transferred = True
            return instance
        return None
    finally:
        if not transferred:
            if owner_fd is not None:
                os.close(owner_fd)
            if mailbox_fd is not None:
                os.close(mailbox_fd)
