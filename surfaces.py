"""Fenster auf dem Bildschirm – damit die Figur auf Fensterkanten sitzen und laufen kann.

  KDE (Wayland/X11): ein KWin-Skript meldet jede Änderung (verschieben, öffnen, schließen,
                     minimieren, Desktopwechsel) per D-Bus an den Begleiter.
  andere X11-Desktops: wmctrl + xprop, alle 0,7 s abgefragt (falls installiert).
  macOS: CGWindowListCopyWindowInfo (Quartz), alle 0,5 s – braucht keine Freigabe, denn
         Position, Größe und Prozess eines Fensters sind ohne Bildschirmaufnahme lesbar.
  Windows: EnumWindows (ctypes), alle 0,5 s – sichtbare, nicht verdeckte Programmfenster.
  WSL (WSLg): dieselbe Abfrage der Windows-Fenster über einen dauerhaft laufenden PowerShell-
         Helfer, denn die Figur steht unter WSLg auf dem Windows-Desktop.
  sonst (GNOME-Wayland): keine Fenster – Boden, Wände und Decke gehen trotzdem.

Fenster: dict(id, x, y, w, h, z, ledge, pid) in Qt-Koordinaten; z = Stapelreihenfolge (größer =
weiter vorne), ledge = darf man draufsitzen (normales Fenster, nicht Vollbild).
ledges() rechnet daraus die sichtbaren Oberkanten aus (verdeckte Stücke fallen weg).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

SERVICE = "org.desktopwalkie.Walkie"
PATH = "/surfaces"
IFACE = "org.desktopwalkie.Surfaces"
SCRIPT_NAME = "walkie-surfaces"

KWIN_SCRIPT = """
function wins() { return workspace.windowList ? workspace.windowList() : workspace.clientList(); }
function onCurrent(w) {
  if (w.onAllDesktops) return true;
  if (w.desktops) return w.desktops.indexOf(workspace.currentDesktop) >= 0;
  return w.desktop === workspace.currentDesktop;
}
var pending = false;
function send() {
  var out = [];
  var list = wins();
  for (var i = 0; i < list.length; i++) {
    var w = list[i];
    if (!(w.normalWindow || w.dialog) || w.minimized || !onCurrent(w)) continue;
    var g = w.frameGeometry;
    out.push([String(w.internalId), Math.round(g.x), Math.round(g.y), Math.round(g.width),
              Math.round(g.height), w.stackingOrder !== undefined ? w.stackingOrder : i,
              !w.fullScreen && w.normalWindow, w.pid || 0]);
  }
  var s = workspace.virtualScreenSize;
  callDBus("%(service)s", "%(path)s", "%(iface)s", "Windows",
           JSON.stringify({screen: [s.width, s.height], wins: out}));
}
function hook(w) {
  w.frameGeometryChanged.connect(send);
  if (w.minimizedChanged) w.minimizedChanged.connect(send);
  if (w.fullScreenChanged) w.fullScreenChanged.connect(send);
}
var all = wins();
for (var i = 0; i < all.length; i++) hook(all[i]);
var added = workspace.windowAdded || workspace.clientAdded;
var removed = workspace.windowRemoved || workspace.clientRemoved;
var activated = workspace.windowActivated || workspace.clientActivated;
added.connect(function (w) { hook(w); send(); });
removed.connect(send);
activated.connect(send);
workspace.currentDesktopChanged.connect(send);
send();
""" % {"service": SERVICE, "path": PATH, "iface": IFACE}


def ledges(wins, screen, min_top=0, min_len=60):
    """Sichtbare Oberkanten: [(id, x1, x2, y)]. screen = (links, oben, rechts, unten).
    Ein Kantenstück ist verdeckt, wenn ein weiter vorne liegendes Fenster darüber liegt."""
    left, top, right, bottom = screen
    out = []
    for w in wins:
        y = w["y"]
        if not w.get("ledge", True) or y < max(top, min_top) or y > bottom - 40:
            continue
        segs = [(max(left, w["x"]), min(right, w["x"] + w["w"]))]
        for o in wins:
            if o["z"] <= w["z"] or o is w:
                continue
            if o["y"] - 2 <= y <= o["y"] + o["h"]:          # deckt die Kantenlinie ab
                a, b = o["x"], o["x"] + o["w"]
                segs = [piece for s1, s2 in segs
                        for piece in ((s1, min(s2, a)), (max(s1, b), s2)) if piece[1] > piece[0]]
        out += [(w["id"], s1, s2, y) for s1, s2 in segs if s2 - s1 >= min_len]
    return out


class Surfaces:
    """Hält die aktuelle Fensterliste aktuell. start() im Qt-Hauptthread aufrufen."""

    def __init__(self, log=lambda m: None):
        self.log = log
        self.wins = []
        self.backend = None
        self.factor = 1.0
        self._adaptor = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ Start/Stop
    def start(self, qt_width=None):
        self.qt_width = qt_width
        try:
            if sys.platform == "darwin" and _mac_windows is not None:
                threading.Thread(target=self._poll_loop, args=(_mac_windows, 0.5),
                                 daemon=True).start()
                self.backend = "mac"
            elif sys.platform == "win32":
                threading.Thread(target=self._poll_loop, args=(self._win_scaled, 0.5),
                                 daemon=True).start()
                self.backend = "windows"
            elif self._start_kwin():
                self.backend = "kwin"
            elif _on_x11() and (_xlib_ok() or (shutil.which("wmctrl") and shutil.which("xprop"))):
                # auch unter WSL mit eigenem X-Desktop (xrdp): dort zählen dessen Fenster
                read = _xlib_windows if _xlib_ok() else _x11_windows
                threading.Thread(target=self._poll_loop, args=(read, 0.7),
                                 daemon=True).start()
                self.backend = "x11"
            elif is_wsl() and _wsl_powershell():
                # WSLg: die Figur steht direkt auf dem Windows-Desktop
                threading.Thread(target=self._wsl_loop, daemon=True).start()
                self.backend = "wsl"
        except Exception as ex:  # noqa: BLE001 – ohne Fenster geht es auch
            self.log(f"fenster: {ex!r}")
        self.log(f"fenster: {self.backend or 'keine Quelle'}")
        return self.backend

    def stop(self):
        self._stop.set()
        proc = getattr(self, "_ps", None)
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
        if self.backend == "kwin":
            _kwin("unloadScript", SCRIPT_NAME)

    # ------------------------------------------------------------ KWin
    def _start_kwin(self):
        from windows import _kwin_available
        if not _kwin_available():
            return False
        from PyQt6.QtCore import QObject, pyqtClassInfo, pyqtSlot
        from PyQt6.QtDBus import QDBusAbstractAdaptor, QDBusConnection

        owner = self

        @pyqtClassInfo("D-Bus Interface", IFACE)
        class Adaptor(QDBusAbstractAdaptor):
            @pyqtSlot(str)
            def Windows(self, data):              # noqa: N802 – D-Bus-Methodenname
                owner._from_kwin(data)

        bus = QDBusConnection.sessionBus()
        self._obj = QObject()
        self._adaptor = Adaptor(self._obj)
        if not (bus.registerService(SERVICE) and bus.registerObject(PATH, self._obj)):
            self.log("fenster: D-Bus-Name belegt")
            return False
        fd, path = tempfile.mkstemp(suffix=".js", prefix="walkie-surfaces-")
        with os.fdopen(fd, "w") as f:
            f.write(KWIN_SCRIPT)
        try:
            _kwin("unloadScript", SCRIPT_NAME)          # Rest eines abgestürzten Laufs
            ok = _kwin("loadScript", path, SCRIPT_NAME)
            _kwin("start")
        finally:
            # KWin liest die Datei beim Laden; danach darf sie weg
            threading.Timer(5, lambda: os.path.exists(path) and os.unlink(path)).start()
        return ok

    def _from_kwin(self, data):
        try:
            d = json.loads(data)
        except ValueError:
            return
        sw = (d.get("screen") or [0])[0]
        self.factor = (self.qt_width / sw) if self.qt_width and sw else 1.0
        f = self.factor
        self.wins = [{"id": i, "x": x * f, "y": y * f, "w": w * f, "h": h * f, "z": z,
                      "ledge": bool(lg), "pid": pid} for i, x, y, w, h, z, lg, pid in
                     (list(r) + [0] * (8 - len(r)) for r in d.get("wins", []))]

    def window_of(self, pid, names=()):
        """Fenster, zu dem ein Prozess gehört (sein eigenes oder das eines Vorfahren –
        das Terminal, in dem die Claude-Session läuft). Unter WSL sind die PIDs Linux-PIDs,
        die Fenster aber Windows-Fenster: dann das vorderste Fenster, dessen Titel einen der
        `names` (Projektname, Sitzungstitel) enthält."""
        if self.backend != "wsl":
            from windows import ancestors
            chain = ancestors(int(pid)) if pid else []
            for p in chain:
                for w in self.wins:
                    if w.get("pid") == p:
                        return w
        names = [n.lower() for n in names if n and len(n) >= 3]
        hits = [w for w in self.wins if names and any(n in w.get("title", "").lower()
                                                       for n in names)]
        return max(hits, key=lambda w: w["z"]) if hits else None

    # ------------------------------------------------------------ Windows / WSL
    def _scale(self, raw, vx, vy, vw):
        """Physische Windows-Pixel -> Qt-Koordinaten (Qt rechnet mit logischen Pixeln)."""
        f = self.factor = (self.qt_width / vw) if self.qt_width and vw else 1.0
        return [dict(w, x=(w["x"] - vx) * f, y=(w["y"] - vy) * f, w=w["w"] * f, h=w["h"] * f)
                for w in raw]

    def _win_scaled(self):
        raw, (vx, vy, vw, vh) = _win_windows()
        return self._scale(_with_ledges(raw, vw, vh), vx, vy, vw)

    def _wsl_loop(self):
        """Der PowerShell-Helfer schreibt alle 0,7 s eine JSON-Zeile mit den Fenstern."""
        own = {"walkie", (os.environ.get("WALKIE_NAME") or "").lower()}
        while not self._stop.is_set():
            try:
                self._ps = proc = subprocess.Popen(
                    [_wsl_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand",
                     ps_encoded(PS_WINDOWS)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace")
                for line in proc.stdout:
                    if self._stop.is_set():
                        break
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    vx, vy, vw, vh = d["screen"]
                    raw = [{"id": str(h), "x": x, "y": y, "w": w, "h": hh, "z": z, "pid": 0,
                            "title": title} for h, x, y, w, hh, z, title in d["wins"]
                           # die Figur und ihre Fenster laufen selbst als WSLg-Fenster
                           if not any(o and title.lower().startswith(o) for o in own)]
                    self.wins = self._scale(_with_ledges(raw, vw, vh), vx, vy, vw)
                err = proc.stderr.read().strip() if proc.poll() is not None else ""
                if err:
                    self.log(f"fenster (wsl): {err[-300:]}")
            except Exception as ex:  # noqa: BLE001
                self.log(f"fenster (wsl): {ex!r}")
            self.wins = []
            if self._stop.wait(10):                      # Helfer beendet: später neu starten
                return

    # ------------------------------------------------------------ X11
    def _poll_loop(self, read, every):
        while not self._stop.is_set():
            try:
                self.wins = read()
            except Exception as ex:  # noqa: BLE001
                self.log(f"fenster: {ex!r}")
                self.wins = []
            time.sleep(every)


def _kwin(method, *args):
    from windows import _qdbus
    r = subprocess.run([_qdbus(), "org.kde.KWin", "/Scripting",
                        f"org.kde.kwin.Scripting.{method}", *map(str, args)],
                       capture_output=True, text=True, timeout=3)
    return r.returncode == 0


class _Xlib:
    """Die paar Xlib-Aufrufe für die Fensterliste, per ctypes (libX11 bringt jeder X-Desktop
    mit, Qt braucht sie ohnehin) – ohne wmctrl und ohne einen Prozess pro Abfrage."""

    def __init__(self):
        import ctypes
        import ctypes.util
        c = ctypes
        self.c = c
        x = self.x = c.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        x.XOpenDisplay.restype = c.c_void_p
        x.XOpenDisplay.argtypes = [c.c_char_p]
        x.XDefaultRootWindow.restype = c.c_ulong
        x.XDefaultRootWindow.argtypes = [c.c_void_p]
        x.XInternAtom.restype = c.c_ulong
        x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]
        x.XGetWindowProperty.argtypes = [
            c.c_void_p, c.c_ulong, c.c_ulong, c.c_long, c.c_long, c.c_int, c.c_ulong,
            c.POINTER(c.c_ulong), c.POINTER(c.c_int), c.POINTER(c.c_ulong),
            c.POINTER(c.c_ulong), c.POINTER(c.c_void_p)]
        x.XFree.argtypes = [c.c_void_p]
        x.XGetGeometry.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong),
                                   c.POINTER(c.c_int), c.POINTER(c.c_int), c.POINTER(c.c_uint),
                                   c.POINTER(c.c_uint), c.POINTER(c.c_uint), c.POINTER(c.c_uint)]
        x.XTranslateCoordinates.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_int, c.c_int,
                                            c.POINTER(c.c_int), c.POINTER(c.c_int),
                                            c.POINTER(c.c_ulong)]
        # ein kaputtes Fenster (gerade geschlossen) darf den Begleiter nicht beenden
        self._handler = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p)(lambda d, e: 0)
        x.XSetErrorHandler(self._handler)
        self.d = x.XOpenDisplay(None)
        if not self.d:
            raise OSError("X-Display nicht erreichbar")
        self.root = x.XDefaultRootWindow(self.d)
        self.atoms = {}

    def atom(self, name):
        if name not in self.atoms:
            self.atoms[name] = self.x.XInternAtom(self.d, name.encode(), 0)
        return self.atoms[name]

    def prop(self, win, name):
        """32-Bit-Werte einer Fenstereigenschaft als Liste (leer, wenn es sie nicht gibt)."""
        c = self.c
        typ, fmt, n, after = c.c_ulong(), c.c_int(), c.c_ulong(), c.c_ulong()
        data = c.c_void_p()
        if self.x.XGetWindowProperty(self.d, win, self.atom(name), 0, 4096, 0, 0,
                                     c.byref(typ), c.byref(fmt), c.byref(n), c.byref(after),
                                     c.byref(data)) != 0 or not data.value:
            return []
        try:
            if fmt.value != 32:
                return []
            return list(c.cast(data, c.POINTER(c.c_ulong))[:n.value])   # 32 Bit = long
        finally:
            self.x.XFree(data)

    def geometry(self, win):
        c = self.c
        r, child = c.c_ulong(), c.c_ulong()
        x, y = c.c_int(), c.c_int()
        w, h, b, depth = c.c_uint(), c.c_uint(), c.c_uint(), c.c_uint()
        if not self.x.XGetGeometry(self.d, win, c.byref(r), c.byref(x), c.byref(y),
                                   c.byref(w), c.byref(h), c.byref(b), c.byref(depth)):
            return None
        ax, ay = c.c_int(), c.c_int()
        self.x.XTranslateCoordinates(self.d, win, self.root, 0, 0, c.byref(ax), c.byref(ay),
                                     c.byref(child))
        return ax.value, ay.value, w.value, h.value


_XLIB = []


def _xlib_ok():
    if not _XLIB:
        try:
            _XLIB.append(_Xlib())
        except Exception:  # noqa: BLE001 – dann eben wmctrl oder gar nichts
            _XLIB.append(None)
    return _XLIB[0] is not None


def _xlib_windows():
    """X11 (EWMH): Fenster des aktuellen Arbeitsbereichs, sichtbarer Rahmen inklusive
    Titelleiste (_NET_FRAME_EXTENTS), z aus _NET_CLIENT_LIST_STACKING."""
    xl = _XLIB[0]
    cur = (xl.prop(xl.root, "_NET_CURRENT_DESKTOP") or [None])[0]
    hidden = {xl.atom("_NET_WM_STATE_HIDDEN")}
    full = xl.atom("_NET_WM_STATE_FULLSCREEN")
    normal = {xl.atom("_NET_WM_WINDOW_TYPE_NORMAL"), xl.atom("_NET_WM_WINDOW_TYPE_DIALOG")}
    out = []
    for z, win in enumerate(xl.prop(xl.root, "_NET_CLIENT_LIST_STACKING")):
        desk = (xl.prop(win, "_NET_WM_DESKTOP") or [cur])[0]
        if cur is not None and desk not in (cur, 0xFFFFFFFF):
            continue
        state = set(xl.prop(win, "_NET_WM_STATE"))
        types = set(xl.prop(win, "_NET_WM_WINDOW_TYPE"))
        if state & hidden or (types and not types & normal):
            continue
        pid = (xl.prop(win, "_NET_WM_PID") or [0])[0]
        g = xl.geometry(win)
        if pid == os.getpid() or not g or g[2] < 80 or g[3] < 60:
            continue                         # die Figur selbst und ihr Einstellungsfenster
        left, right, top, bottom = (xl.prop(win, "_NET_FRAME_EXTENTS") + [0, 0, 0, 0])[:4]
        x, y, w, h = g[0] - left, g[1] - top, g[2] + left + right, g[3] + top + bottom
        out.append({"id": hex(win), "x": x, "y": y, "w": w, "h": h, "z": z,
                    "ledge": full not in state, "pid": pid})
    return out


def _x11_windows():
    cur = next((ln.split()[0] for ln in subprocess.run(
        ["wmctrl", "-d"], capture_output=True, text=True, timeout=2).stdout.splitlines()
        if "*" in ln.split()[1:2]), None)
    stack = subprocess.run(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"], capture_output=True,
                           text=True, timeout=2).stdout
    order = {int(h, 16): i for i, h in enumerate(
        part.strip() for part in stack.split("#", 1)[-1].split(",") if part.strip())}
    out = []
    for ln in subprocess.run(["wmctrl", "-lpG"], capture_output=True, text=True,
                             timeout=2).stdout.splitlines():
        p = ln.split(None, 8)
        if len(p) < 8 or (p[1] != "-1" and p[1] != cur):
            continue
        wid = int(p[0], 16)
        x, y, w, h = map(int, p[3:7])
        out.append({"id": p[0], "x": x, "y": y, "w": w, "h": h, "z": order.get(wid, 0),
                    "ledge": True, "pid": int(p[2])})
    return out


def _mac_window_list():
    """macOS: sichtbare normale Fenster (Ebene 0), vorderstes zuerst – wie term-pet es macht.
    Koordinaten: Punkte, Ursprung oben links – genau wie Qt sie auf dem Mac verwendet."""
    import Quartz
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []
    own = os.getpid()
    out = []
    for i, w in enumerate(infos):
        if w.get("kCGWindowLayer", 1) != 0 or w.get("kCGWindowOwnerPID") == own:
            continue
        b = w.get("kCGWindowBounds") or {}
        if b.get("Width", 0) < 80 or b.get("Height", 0) < 60:
            continue                                   # Mini-Fenster, Tooltips
        out.append({"id": str(w.get("kCGWindowNumber")), "x": b["X"], "y": b["Y"],
                    "w": b["Width"], "h": b["Height"], "z": len(infos) - i, "ledge": True,
                    "pid": int(w.get("kCGWindowOwnerPID") or 0)})
    return out


try:
    if sys.platform == "darwin":
        import Quartz  # noqa: F401 – nur prüfen, ob pyobjc-Quartz da ist
        _mac_windows = _mac_window_list
    else:
        _mac_windows = None
except ImportError:
    _mac_windows = None


def _with_ledges(wins, vw, vh):
    """Vollbild- und Fenster, die den ganzen Bildschirm füllen, sind keine Kanten."""
    for w in wins:
        w["ledge"] = not (w["w"] >= vw - 2 and w["h"] >= vh - 2)
    return wins


def _win_windows():
    """Windows: sichtbare Programmfenster, vorderstes zuerst, in physischen Pixeln.
    Ohne Werkzeug- und versteckte („cloaked“, z. B. auf anderem virtuellen Desktop) Fenster."""
    import ctypes
    from ctypes import wintypes
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    own = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x80:          # WS_EX_TOOLWINDOW
            return True
        cloaked = wintypes.DWORD()
        if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        r = wintypes.RECT()                                 # sichtbarer Rahmen ohne Schatten
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        w, h = r.right - r.left, r.bottom - r.top
        if pid.value != own and w >= 80 and h >= 60:
            found.append({"id": str(hwnd), "x": r.left, "y": r.top, "w": w, "h": h,
                          "pid": pid.value, "title": buf.value})
        return True
    user32.EnumWindows(each, 0)
    for i, w in enumerate(found):
        w["z"] = len(found) - i
    screen = tuple(user32.GetSystemMetrics(m) for m in (76, 77, 78, 79))   # SM_*VIRTUALSCREEN
    return found, screen


# Dieselbe Abfrage für WSL, als PowerShell-Schleife (einmal starten, dann nur lesen).
PS_WINDOWS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System; using System.Text; using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class WalkieWins {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr p);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
  [DllImport("user32.dll")] static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int a, out RECT r, int n);
  [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int a, out int v, int n);
  const char Q = (char)34, BS = (char)92;
  static string Esc(string s) {
    var b = new StringBuilder();
    foreach (char c in s) { if (c == Q || c == BS) b.Append(BS).Append(c);
      else if (c < ' ') b.Append(' '); else b.Append(c); }
    return b.ToString();
  }
  public static string Json() {
    var rows = new List<string>();
    EnumWindows(delegate (IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h) || IsIconic(h) || (GetWindowLong(h, -20) & 0x80) != 0) return true;
      int cl; if (DwmGetWindowAttribute(h, 14, out cl, 4) == 0 && cl != 0) return true;
      int n = GetWindowTextLength(h); if (n == 0) return true;
      var sb = new StringBuilder(n + 1); GetWindowText(h, sb, n + 1);
      RECT r; if (DwmGetWindowAttribute(h, 9, out r, 16) != 0) GetWindowRect(h, out r);
      int w = r.R - r.L, hh = r.B - r.T; if (w < 80 || hh < 60) return true;
      rows.Add(h.ToInt64() + "," + r.L + "," + r.T + "," + w + "," + hh + ",Z," + Q + Esc(sb.ToString()) + Q);
      return true; }, IntPtr.Zero);
    var outp = new List<string>();
    for (int i = 0; i < rows.Count; i++) outp.Add("[" + rows[i].Replace(",Z,", "," + (rows.Count - i) + ",") + "]");
    return "{" + Q + "screen" + Q + ":[" + GetSystemMetrics(76) + "," + GetSystemMetrics(77) + "," +
      GetSystemMetrics(78) + "," + GetSystemMetrics(79) + "]," + Q + "wins" + Q + ":[" + string.Join(",", outp) + "]}";
  }
}
'@
[void][WalkieWins]::SetProcessDPIAware()
$last = ''
while ($true) {
  $j = [WalkieWins]::Json()
  if ($j -ne $last) { [Console]::Out.WriteLine($j); [Console]::Out.Flush(); $last = $j }
  Start-Sleep -Milliseconds 700
}
"""


def _on_x11():
    """Zeichnet Qt über X11? Unter WSL ist WAYLAND_DISPLAY (WSLg) oft auch dann gesetzt, wenn
    die Figur auf einem X-Desktop (z. B. xrdp) läuft – dann zählt, was Qt benutzt."""
    try:
        from PyQt6.QtGui import QGuiApplication
        name = QGuiApplication.platformName()
        if name:
            return name == "xcb"
    except Exception:  # noqa: BLE001
        pass
    return bool(os.environ.get("DISPLAY")) and not os.environ.get("WAYLAND_DISPLAY")


def is_wsl():
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def ps_encoded(script):
    """PowerShell -EncodedCommand: Base64 von UTF-16LE (mehrzeilige Skripte über stdin
    führt PowerShell nur zeilenweise und unvollständig aus)."""
    import base64
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _wsl_powershell():
    import glob
    return shutil.which("powershell.exe") or next(iter(sorted(glob.glob(
        "/mnt/*/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"))), None)
