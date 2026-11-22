"""Fenster einer Claude-Session nach vorne holen („Zeig mir das“).

Ausgangspunkt ist die PID des Claude-Code-Prozesses (meldet der Plugin-Mod). Gesucht wird das
Fenster, dessen Prozess ein Vorfahre davon ist (das Terminal, in dem die Session läuft).

  KDE (Wayland/X11): KWin-Skript über D-Bus
  andere X11-Desktops: wmctrl bzw. xdotool, falls installiert
  macOS: die Terminal-App aktivieren (genaues Fenster: nicht ohne Weiteres möglich)
  Windows: EnumWindows + SetForegroundWindow

raise_pid(pid) -> True, wenn ein Weg da war (ob das Fenster wirklich vorne ist, meldet kein
System zuverlässig zurück). GNOME unter Wayland erlaubt es Programmen nicht – dann False.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def ancestors(pid, limit=12):
    """PID und ihre Elternprozesse (Linux/macOS über ps, Windows über WMI/ctypes)."""
    out = []
    while pid and pid > 1 and len(out) < limit:
        out.append(pid)
        pid = _parent(pid)
    return out


def _parent(pid):
    try:
        if sys.platform.startswith("linux"):
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("PPid:"):
                    return int(line.split()[1])
        elif sys.platform == "win32":
            return _win_parent(pid)
        else:
            r = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True,
                               text=True, timeout=3)
            return int(r.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


def raise_pid(pid, log=lambda m: None):
    if not pid:
        return False
    chain = ancestors(int(pid))
    try:
        if sys.platform == "win32":
            return _raise_windows(chain)
        if sys.platform == "darwin":
            return _raise_mac(chain)
        if _kwin_available():
            return _raise_kwin(chain)
        if os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return _raise_x11(chain)
    except Exception as ex:  # noqa: BLE001
        log(f"fenster: {ex}")
    return False


# ------------------------------------------------------------------ KDE
def _qdbus():
    return shutil.which("qdbus6") or shutil.which("qdbus")


def _kwin_available():
    q = _qdbus()
    if not q:
        return False
    r = subprocess.run([q, "org.kde.KWin", "/Scripting"], capture_output=True, text=True, timeout=3)
    return r.returncode == 0 and "loadScript" in r.stdout


def _raise_kwin(chain):
    q = _qdbus()
    script = (
        "const pids = [%s];\n"
        "const wins = workspace.windowList ? workspace.windowList() : workspace.clientList();\n"
        "for (const p of pids) {\n"
        "  const w = wins.find(x => x.pid === p);\n"
        "  if (w) { if (w.minimized) w.minimized = false; workspace.activeWindow = w; break; }\n"
        "}\n" % ", ".join(str(p) for p in chain))
    fd, path = tempfile.mkstemp(suffix=".js", prefix="walkie-raise-")
    with os.fdopen(fd, "w") as f:
        f.write(script)
    name = f"walkie-raise-{os.getpid()}"
    try:
        subprocess.run([q, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", name],
                       capture_output=True, timeout=3)
        subprocess.run([q, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript",
                        path, name], capture_output=True, timeout=3, check=True)
        subprocess.run([q, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start"],
                       capture_output=True, timeout=3)
        subprocess.run([q, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", name],
                       capture_output=True, timeout=3)
        return True
    finally:
        os.unlink(path)


# ------------------------------------------------------------------ X11
def _raise_x11(chain):
    if shutil.which("wmctrl"):
        r = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 3 and parts[2].isdigit() and int(parts[2]) in chain:
                subprocess.run(["wmctrl", "-ia", parts[0]], timeout=3)
                return True
    if shutil.which("xdotool"):
        for p in chain:
            r = subprocess.run(["xdotool", "search", "--pid", str(p)], capture_output=True,
                               text=True, timeout=3)
            ids = r.stdout.split()
            if ids:
                subprocess.run(["xdotool", "windowactivate", ids[-1]], timeout=3)
                return True
    return False


# ------------------------------------------------------------------ macOS
def _raise_mac(chain):
    """Erst nativ (NSRunningApplication: keine Rückfrage), sonst über System Events
    (fragt beim ersten Mal nach der Erlaubnis, System Events zu steuern)."""
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication
        for p in chain:
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(p)
            if app is not None and app.activationPolicy() == 0:   # 0 = normale App mit Fenster
                if app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps):
                    return True
    except Exception:  # noqa: BLE001 – ohne pyobjc: der alte Weg
        pass
    for p in chain:
        r = subprocess.run(["osascript", "-e",
                            'tell application "System Events" to set frontmost of (first process '
                            f'whose unix id is {p}) to true'], capture_output=True, timeout=5)
        if r.returncode == 0:
            return True
    return False


# ------------------------------------------------------------------ Windows
def _win_parent(pid):
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]
    k = ctypes.windll.kernel32
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    e = PROCESSENTRY32()
    e.dwSize = ctypes.sizeof(e)
    try:
        ok = k.Process32First(snap, ctypes.byref(e))
        while ok:
            if e.th32ProcessID == pid:
                return e.th32ParentProcessID
            ok = k.Process32Next(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return 0


def _raise_windows(chain):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in chain:
                found.append((chain.index(pid.value), hwnd))
        return True
    user32.EnumWindows(each, 0)
    if not found:
        return False
    hwnd = sorted(found)[0][1]
    user32.ShowWindow(hwnd, 9)                  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True
