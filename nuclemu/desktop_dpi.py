"""DPI setup before Tk creation, with window-local measurements afterward."""

import sys


def enable_windows_dpi_awareness():
    """Keep a manifest-owned context; otherwise prefer per-monitor V2."""
    if sys.platform != 'win32':
        return 'platform'
    import ctypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    setter = getattr(user32, 'SetProcessDpiAwarenessContext', None)
    if setter is not None:
        setter.argtypes, setter.restype = [ctypes.c_void_p], ctypes.c_int
        for context, name in ((-4, 'per-monitor-v2'), (-3, 'per-monitor')):
            if setter(ctypes.c_void_p(context)):
                return name
            if ctypes.get_last_error() == 5:
                return 'host'
    try:
        setter = ctypes.WinDLL('shcore').SetProcessDpiAwareness
        setter.argtypes, setter.restype = [ctypes.c_int], ctypes.c_long
        result = setter(2)
        if result == 0:
            return 'per-monitor'
        if result == -2147024891:
            return 'host'
    except (OSError, AttributeError):
        pass
    return 'system' if user32.SetProcessDPIAware() else 'host'


def window_dpi(root):
    if sys.platform == 'win32':
        import ctypes
        user32 = ctypes.WinDLL('user32')
        getter = getattr(user32, 'GetDpiForWindow', None)
        if getter is not None:
            getter.argtypes, getter.restype = [ctypes.c_void_p], ctypes.c_uint
            dpi = getter(root.winfo_id())
            if dpi:
                return dpi
    return root.winfo_fpixels('1i')


def work_area(root):
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
        user32 = ctypes.WinDLL('user32')
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MonitorInfo)]
        monitor = user32.MonitorFromWindow(root.winfo_id(), 2)
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return info.work.right - info.work.left, info.work.bottom - info.work.top
    return root.winfo_screenwidth(), root.winfo_screenheight()
