"""Opens Sakuya when Path of Exile 2 starts, if the player turned that on in the settings.

A small watcher with no window, started with Windows from the user's Run key ("Sakuya.exe --watch-game"). Every few seconds it looks at
the names and paths of the running programs, the list Task Manager shows. It reads nothing of the game: no files, no memory, no log.
When the game appears and Sakuya is not open, it opens Sakuya once; when the setting is turned off, it removes itself and ends.
It loads no more than the standard library, so it costs a few megabytes while it waits.
"""
import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

WATCH_ARGUMENT = "--watch-game"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Sakuya"
POLL_SECONDS = 5
GAME_NAME_START = "pathofexile"  # PathOfExile.exe, PathOfExileSteam.exe, PathOfExile_x64*.exe; Path of Exile 1 has the same names
GAME_FOLDER = "path of exile 2"  # so the path tells the two games apart
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class ProcessEntry(ctypes.Structure):
    _fields_ = [("size", ctypes.wintypes.DWORD), ("usage", ctypes.wintypes.DWORD), ("pid", ctypes.wintypes.DWORD), ("heap", ctypes.c_size_t), ("module", ctypes.wintypes.DWORD),
                ("threads", ctypes.wintypes.DWORD), ("parent", ctypes.wintypes.DWORD), ("priority", ctypes.c_long), ("flags", ctypes.wintypes.DWORD), ("name", ctypes.c_wchar * 260)]


def running_processes() -> list[tuple[int, int, str]]:
    """(pid, parent, file name) of every running program."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    for function in (kernel32.Process32FirstW, kernel32.Process32NextW):
        function.argtypes = (ctypes.c_void_p, ctypes.POINTER(ProcessEntry))
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = ProcessEntry(size=ctypes.sizeof(ProcessEntry))
    found, processes = kernel32.Process32FirstW(snapshot, ctypes.byref(entry)), []
    while found:
        processes.append((entry.pid, entry.parent, entry.name))
        found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    kernel32.CloseHandle(snapshot)
    return processes


def process_path(pid: int) -> str | None:
    """The file a program runs from, as Task Manager shows it. None when Windows does not say."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = (ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.c_wchar_p, ctypes.POINTER(ctypes.wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = ctypes.wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        return buffer.value if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else None
    finally:
        kernel32.CloseHandle(handle)


def game_is_running(processes: list[tuple[int, int, str]], path_of=None) -> bool:
    """Path of Exile 2 by its file name and, where Windows tells it, by its folder: the first game's programs have the same names."""
    path_of = path_of or process_path  # looked up when called, so a test's stand-in is the one asked
    for pid, _, name in processes:
        if name.casefold().startswith(GAME_NAME_START) and name.casefold().endswith(".exe"):
            path = path_of(pid)
            if path is None or GAME_FOLDER in path.casefold():
                return True
    return False


def app_is_running(processes: list[tuple[int, int, str]], exe_name: str, watcher_pids: set[int]) -> bool:
    """Sakuya itself is open: a program of this name that is not the watcher."""
    return any(name.casefold() == exe_name.casefold() and pid not in watcher_pids for pid, _, name in processes)


def run_command(exe: Path) -> str:
    return f'"{exe}" {WATCH_ARGUMENT}'


def registered_command() -> str | None:
    """What the Run key starts with Windows for Sakuya, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value = winreg.QueryValueEx(key, RUN_VALUE)[0]
    except OSError:
        return None
    return value if isinstance(value, str) else None


def is_registered(exe: Path) -> bool:
    return registered_command() == run_command(exe)


def register(exe: Path) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, run_command(exe))


def unregister() -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except OSError:
        pass


def pid_file(exe: Path) -> Path:
    return exe.with_name("game_watch.json")


def watcher_pids(exe: Path, processes: list[tuple[int, int, str]] | None = None) -> set[int]:
    """The watcher's programs that are still running, from the file it leaves beside the exe. The main program does not close them."""
    try:
        stored = json.loads(pid_file(exe).read_text(encoding="utf-8"))
        pids = {int(pid) for pid in stored.get("pids", [])}
    except (OSError, ValueError, TypeError, AttributeError):
        return set()
    alive = {pid for pid, _, name in (processes if processes is not None else running_processes()) if name.casefold() == exe.name.casefold()}
    return pids & alive


def start_watcher(exe: Path) -> None:
    """Starts the watcher now, as Windows will at the next sign-in, unless one is already watching."""
    if watcher_pids(exe):
        return
    subprocess.Popen([str(exe), WATCH_ARGUMENT], cwd=str(exe.parent), env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def open_app(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent), env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def watch(exe: Path, own: set[int], sleep=time.sleep, processes_now=running_processes, still_wanted=None, start=open_app, rounds: int | None = None) -> None:
    """Opens the program when the game starts. Once per start of the game: a player who closes Sakuya while playing is not argued with."""
    still_wanted = still_wanted or (lambda: is_registered(exe))
    game_was_running = True  # a game already running when the watcher starts does not count as a start: Windows has just signed in, or the player turned this on mid-game
    done = 0
    while still_wanted() and (rounds is None or done < rounds):
        processes = processes_now()
        game_now = game_is_running(processes)
        if game_now and not game_was_running and not app_is_running(processes, exe.name, own):
            start(exe)
        game_was_running = game_now
        done += 1
        sleep(POLL_SECONDS)


def run(arguments: list[str]) -> int:
    """The watcher's whole life: one at a time, gone when the setting is off or the exe it was started for has moved (an update)."""
    exe = Path(sys.executable)
    own = {os.getpid(), os.getppid()}  # a packed exe is a starter and the program it runs
    if not getattr(sys, "frozen", False) or not is_registered(exe) or watcher_pids(exe) - own:
        return 0
    try:
        pid_file(exe).write_text(json.dumps({"pids": sorted(own)}), encoding="utf-8")
    except OSError:
        return 0
    try:
        watch(exe, own)
    finally:
        try:
            if watcher_pids(exe) <= own:
                pid_file(exe).unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def stop_watcher(exe: Path) -> None:
    """Ends a running watcher, before an update moves the exe it runs from; the new version starts it again."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.wintypes.UINT)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    for pid in watcher_pids(exe):
        handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.CloseHandle(handle)
    try:
        pid_file(exe).unlink(missing_ok=True)
    except OSError:
        pass
