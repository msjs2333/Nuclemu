"""Blend Windows non-client chrome into the light launcher surface."""

import sys


def blend_windows_caption(root):
    if sys.platform != 'win32':
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32')
    user32.GetAncestor.argtypes, user32.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
    hwnd = user32.GetAncestor(root.winfo_id(), 2)
    class Options(ctypes.Structure):
        _fields_ = [('flags', wintypes.DWORD), ('mask', wintypes.DWORD)]
    theme = ctypes.WinDLL('uxtheme').SetWindowThemeAttribute
    theme.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    theme.restype = ctypes.c_long
    options = Options(3, 3)  # Hide the drawn caption/icon, keeping system commands.
    result = theme(hwnd, 1, ctypes.byref(options), ctypes.sizeof(options))
    dwm = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
    dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    for attribute, value in ((20, 0), (34, 0xfffffffe), (35, 0xffffff)):
        color = wintypes.DWORD(value)
        dwm(hwnd, attribute, ctypes.byref(color), ctypes.sizeof(color))
    # Windows 11 can still draw the small icon despite WTNCA_NODRAWICON.
    # Replace only ICON_SMALL; leave the real ICON_BIG and executable resource
    # available to the shell. A transparent monochrome icon scales at any DPI.
    user32.CreateIcon.argtypes = [wintypes.HINSTANCE, ctypes.c_int, ctypes.c_int,
                                 wintypes.BYTE, wintypes.BYTE, ctypes.c_void_p, ctypes.c_void_p]
    user32.CreateIcon.restype = wintypes.HICON
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.IsWindow.argtypes = [wintypes.HWND]
    mask = (wintypes.BYTE * 32)(*([255] * 32))
    pixels = (wintypes.BYTE * 32)()
    icon = user32.CreateIcon(None, 16, 16, 1, 1, mask, pixels)
    if not icon:
        raise ctypes.WinError()
    previous = user32.SendMessageW(hwnd, 0x80, 0, icon)  # WM_SETICON / ICON_SMALL

    def release(event):
        nonlocal icon
        if event.widget == root and icon:
            if user32.IsWindow(hwnd):
                user32.SendMessageW(hwnd, 0x80, 0, previous)
            user32.DestroyIcon(icon)
            icon = None

    root.bind('<Destroy>', release, add='+')
    return result == 0
