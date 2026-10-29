"""Start a separate, elevated GUI process through the Windows shell."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
from .config import ROOT, resolve_path
from .score import read_score

def is_admin():
    return os.name == 'nt' and bool(ctypes.windll.shell32.IsUserAnAdmin())

def launch_simulator(directory='runs', score=None, language='zh'):
    if os.name != 'nt':
        raise OSError('The keyboard simulator requires Windows.')
    directory = resolve_path(directory)
    if score:
        score = resolve_path(score)
        read_score(score)
    python = Path(sys.executable).with_name('pythonw.exe')
    if not python.is_file():
        python = Path(sys.executable)
    args = [str(ROOT/'simulator.py'), '--directory', str(directory), '--language', 'en' if language == 'en' else 'zh']
    if score:
        args.extend(('--score', str(score)))
    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    # NOCLOSEPROCESS | NOASYNC. No console inheritance or parent job attachment.
    info.fMask = 0x40 | 0x100
    info.lpVerb = 'runas'
    info.lpFile = str(python)
    info.lpParameters = subprocess.list2cmdline(args)
    info.lpDirectory = str(ROOT)
    info.nShow = 1
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:
            raise OSError('Administrator request was cancelled.')
        raise ctypes.WinError(error)
    pid = kernel.GetProcessId(info.hProcess) if info.hProcess else None
    if info.hProcess:
        kernel.CloseHandle(info.hProcess)
    return {'ok': True, 'pid': pid}


from .score_library import list_scores
