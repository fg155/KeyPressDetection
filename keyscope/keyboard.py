"""Windows scan-code input. Instantiation sends no keyboard events."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import os

SCAN = dict(zip('QWERTYUASDFGHJZXCVBNM', [0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x1e,0x1f,0x20,0x21,0x22,0x23,0x24,0x2c,0x2d,0x2e,0x2f,0x30,0x31,0x32]))
ULONG_PTR = ctypes.c_size_t

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

class INPUTUNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('type', wintypes.DWORD), ('value', INPUTUNION)]

class Keyboard:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user.SendInput.restype = wintypes.UINT
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    def send(self, down, up):
        if self.dry_run:
            return
        batch = []
        for keys, flags in ((up, 0x0008|0x0002), (down, 0x0008)):
            for key in keys:
                item = INPUT(type=1)
                item.ki = KEYBDINPUT(0, SCAN[key], flags, 0, 0)
                batch.append(item)
        if batch:
            sent = self.user.SendInput(len(batch), (INPUT*len(batch))(*batch), ctypes.sizeof(INPUT))
            if sent != len(batch):
                raise OSError('SendInput failed. Check window permissions and input compatibility.')

    def pressed(self, key):
        return bool(self.user.GetAsyncKeyState(key) & 0x8000)

    def target(self):
        window = self.user.GetForegroundWindow()
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if not self.dry_run and (not window or pid.value == os.getpid()):
            raise ValueError('Focus the game window during the countdown.')
        return window

    def pause_reason(self,target):
        if self.dry_run: return None
        if self.user.GetForegroundWindow() != target:
            return 'Paused: foreground window changed.'
        if any(self.pressed(vk) for vk in (0x10,0x11,0x12,0x5b,0x5c)):
            return 'Paused: a modifier key is held.'
        return None

@contextmanager
def playback_lock():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, 'Local\\FasterRCNNKeyboardPlayback')
    if not handle:
        raise OSError('Cannot acquire playback lock. Another simulator may be running.')
    acquired = False
    try:
        acquired = kernel.WaitForSingleObject(handle, 0) in (0, 0x80)
        if not acquired:
            raise ValueError('Another simulator is already playing.')
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)
