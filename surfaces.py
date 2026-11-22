"""Fenster auf dem Bildschirm – damit die Figur auf Fensterkanten sitzen und laufen kann.

  KDE (Wayland/X11): ein KWin-Skript meldet jede Änderung (verschieben, öffnen, schließen,
                     minimieren, Desktopwechsel) per D-Bus an den Begleiter.
  andere X11-Desktops: wmctrl + xprop, alle 0,7 s abgefragt (falls installiert).
  macOS: CGWindowListCopyWindowInfo (Quartz), alle 0,5 s – braucht keine Freigabe, denn
         Position, Größe und Prozess eines Fensters sind ohne Bildschirmaufnahme lesbar.
  sonst (GNOME-Wayland, Windows): keine Fenster – Boden, Wände und Decke gehen trotzdem.

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
            elif self._start_kwin():
                self.backend = "kwin"
            elif (os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
                  and shutil.which("wmctrl") and shutil.which("xprop")):
                threading.Thread(target=self._poll_loop, args=(_x11_windows, 0.7),
                                 daemon=True).start()
                self.backend = "x11"
        except Exception as ex:  # noqa: BLE001 – ohne Fenster geht es auch
            self.log(f"fenster: {ex!r}")
        self.log(f"fenster: {self.backend or 'keine Quelle'}")
        return self.backend

    def stop(self):
        self._stop.set()
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

    def window_of(self, pid):
        """Fenster, zu dem ein Prozess gehört (sein eigenes oder das eines Vorfahren –
        das Terminal, in dem die Claude-Session läuft)."""
        from windows import ancestors
        chain = ancestors(int(pid)) if pid else []
        for p in chain:
            for w in self.wins:
                if w.get("pid") == p:
                    return w
        return None

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
