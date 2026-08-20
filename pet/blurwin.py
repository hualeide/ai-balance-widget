"""Windows 真毛玻璃。做法对齐 zhiyiYo/PyQt-Frameless-Window 的 AcrylicWindow。"""
from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, Structure, byref, c_bool, c_int, pointer, sizeof
from ctypes.wintypes import BOOL, DWORD, HRGN, ULONG


class ACCENT_POLICY(Structure):
    _fields_ = [
        ("AccentState", DWORD),
        ("AccentFlags", DWORD),
        ("GradientColor", DWORD),
        ("AnimationId", DWORD),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(Structure):
    _fields_ = [
        ("Attribute", DWORD),
        ("Data", POINTER(ACCENT_POLICY)),
        ("SizeOfData", ULONG),
    ]


class DWM_BLURBEHIND(Structure):
    _fields_ = [
        ("dwFlags", DWORD),
        ("fEnable", BOOL),
        ("hRgnBlur", HRGN),
        ("fTransitionOnMaximized", BOOL),
    ]


class MARGINS(Structure):
    _fields_ = [
        ("cxLeftWidth", c_int),
        ("cxRightWidth", c_int),
        ("cyTopHeight", c_int),
        ("cyBottomHeight", c_int),
    ]


ACCENT_DISABLED = 0
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19
DWM_BB_ENABLE = 1
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_ROUND = 2
DWMSBT_NONE = 1


def _rgba_to_abgr(rgba: str) -> int:
    h = rgba.strip().lstrip("#")
    if len(h) != 8:
        h = "1C1E26A6"
    return int("".join(h[i : i + 2] for i in range(6, -1, -2)), 16)


def apply_frosted(hwnd: int, tint: str = "1C1E26A6") -> bool:
    """tint 为 RRGGBBAA。Qt 窗口背景必须透明，不能再盖一层实色。"""
    if not hwnd:
        return False
    hwnd = int(hwnd)
    user32 = ctypes.WinDLL("user32")
    dwm = ctypes.WinDLL("dwmapi")
    try:
        blur = DWM_BLURBEHIND(DWM_BB_ENABLE, True, 0, False)
        dwm.DwmEnableBlurBehindWindow(hwnd, byref(blur))
    except Exception:
        pass
    accent = ACCENT_POLICY()
    accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
    accent.AccentFlags = 0x20 | 0x40 | 0x80 | 0x100
    accent.GradientColor = _rgba_to_abgr(tint)
    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.Data = pointer(accent)
    data.SizeOfData = sizeof(accent)
    fn = user32.SetWindowCompositionAttribute
    fn.restype = c_bool
    ok = bool(fn(hwnd, pointer(data)))
    try:
        dark = c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(dark), sizeof(dark))
        if sys.getwindowsversion().build >= 22000:
            round_c = c_int(DWMWCP_ROUND)
            dwm.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, byref(round_c), sizeof(round_c)
            )
            m = MARGINS(-1, -1, -1, -1)
            dwm.DwmExtendFrameIntoClientArea(hwnd, byref(m))
    except Exception:
        pass
    return ok


def apply_card_glass(hwnd: int, tint: str = "FFFFFF4D") -> None:
    """只给卡片上浅色磨砂，不铺整窗深色框、不 ExtendFrame。"""
    if not hwnd:
        return
    hwnd = int(hwnd)
    user32 = ctypes.WinDLL("user32")
    dwm = ctypes.WinDLL("dwmapi")
    try:
        none = c_int(DWMSBT_NONE)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, byref(none), sizeof(none))
        m = MARGINS(0, 0, 0, 0)
        dwm.DwmExtendFrameIntoClientArea(hwnd, byref(m))
    except Exception:
        pass
    try:
        blur = DWM_BLURBEHIND(DWM_BB_ENABLE, True, 0, False)
        dwm.DwmEnableBlurBehindWindow(hwnd, byref(blur))
    except Exception:
        pass
    accent = ACCENT_POLICY()
    accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
    accent.AccentFlags = 0x20
    accent.GradientColor = _rgba_to_abgr(tint)
    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.Data = pointer(accent)
    data.SizeOfData = sizeof(accent)
    fn = user32.SetWindowCompositionAttribute
    fn.restype = c_bool
    try:
        fn(hwnd, pointer(data))
    except Exception:
        pass
    try:
        if sys.getwindowsversion().build >= 22000:
            round_c = c_int(DWMWCP_ROUND)
            dwm.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, byref(round_c), sizeof(round_c)
            )
    except Exception:
        pass


def clear_frosted(hwnd: int) -> None:
    """关掉 Acrylic / Mica，窗口只留真正透明，不再铺一层深色底。"""
    if not hwnd:
        return
    hwnd = int(hwnd)
    user32 = ctypes.WinDLL("user32")
    dwm = ctypes.WinDLL("dwmapi")
    try:
        blur = DWM_BLURBEHIND(DWM_BB_ENABLE, False, 0, False)
        dwm.DwmEnableBlurBehindWindow(hwnd, byref(blur))
    except Exception:
        pass
    accent = ACCENT_POLICY()
    accent.AccentState = ACCENT_DISABLED
    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.Data = pointer(accent)
    data.SizeOfData = sizeof(accent)
    fn = user32.SetWindowCompositionAttribute
    fn.restype = c_bool
    try:
        fn(hwnd, pointer(data))
    except Exception:
        pass
    try:
        none = c_int(DWMSBT_NONE)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, byref(none), sizeof(none))
        m = MARGINS(0, 0, 0, 0)
        dwm.DwmExtendFrameIntoClientArea(hwnd, byref(m))
    except Exception:
        pass
