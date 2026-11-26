"""Musik leiser, solange der Walkie zuhört oder spricht (Idee aus GodTerm, backtalk,
voice-of-claude) – danach wieder genau so laut wie vorher.

  d = Ducker(level=lambda: 30, log=print)
  d.hold("mic")      # ab jetzt leiser (mehrere Gründe zählen getrennt)
  d.release("mic")   # wenn kein Grund mehr übrig ist: nach kurzer Pause wieder laut
  d.close()          # beim Beenden: sofort alles zurück

Alle Systemaufrufe laufen in einem eigenen Thread (Windows-COM braucht das, und kein Aufruf
darf die Oberfläche blockieren). Das Zurückdrehen wartet RESTORE_DELAY Sekunden, damit die
Musik zwischen zwei Sätzen nicht kurz aufheult. Hat der Nutzer die Lautstärke inzwischen
selbst verändert, bleibt seine Einstellung.

Linux: pactl, jede Wiedergabe anderer Programme (sink-input) einzeln.
Windows: pycaw, jede Audio-Sitzung anderer Programme einzeln.
macOS: Spotify und Music per AppleScript (wenn sie laufen).
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

RESTORE_DELAY = 0.8


class Backend:
    def duck(self, factor):
        """-> Zustand zum Zurückdrehen (beliebig)."""
        return None

    def restore(self, saved):
        pass


class Pulse(Backend):
    """PipeWire/PulseAudio über pactl: Lautstärke je Wiedergabe-Stream."""
    def __init__(self, own_pid):
        self.own = str(own_pid)
        self.pending = {}                      # App -> (alt, gedrosselt): Stream endete gedrosselt

    @staticmethod
    def _parent(pid):
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
                return f.read().rsplit(")", 1)[1].split()[1]   # Feld 4 = ppid; Name kann ")" enthalten
        except (OSError, IndexError):
            return None

    def _ours(self, pid):
        """Eigene Wiedergabe – auch über Kindprozesse (z. B. pacat/aplay). Würde die mitgedrosselt,
        merkt sich PipeWire die 30 % und die Stimme wird mit jedem Satz leiser."""
        for _ in range(8):
            if not pid or pid in ("0", "1"):
                return False
            if pid == self.own:
                return True
            pid = self._parent(pid)
        return False

    @staticmethod
    def _pactl(*args):
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=2)

    def streams(self):
        r = self._pactl("-f", "json", "list", "sink-inputs")
        if r.returncode != 0:
            return []
        try:
            return json.loads(r.stdout or "[]")
        except ValueError:
            return []

    @staticmethod
    def _app(props):
        return (props.get("application.name"), props.get("application.process.binary"))

    @staticmethod
    def _vols(s):
        return [int(v.get("value", 0)) for v in (s.get("volume") or {}).values()]

    @staticmethod
    def _close(now, ducked):
        return len(now) == len(ducked) and all(abs(a - b) <= 700 for a, b in zip(now, ducked))

    def duck(self, factor):
        saved = {}
        for s in self.streams():
            props = s.get("properties") or {}
            if (str(props.get("walkie.own", "")).lower() == "true"     # eigene pw-play/pacat
                    or self._ours(str(props.get("application.process.id", "")))
                    or s.get("corked")):
                continue
            vols = self._vols(s)
            if not vols or max(vols) == 0:
                continue
            app = self._app(props)
            if app in self.pending and self._close(vols, self.pending[app][1]):
                vols = self.pending.pop(app)[0]   # startet noch gedrosselt (s. restore): echte Höhe
            new = [max(0, int(v * factor)) for v in vols]
            if self._pactl("set-sink-input-volume", str(s["index"]), *map(str, new)).returncode == 0:
                saved[s["index"]] = (vols, new, app)
        return saved

    def restore(self, saved):
        """Zurückdrehen. Endet ein Stream, solange er gedrosselt ist (Liedwechsel, neues Video),
        merkt sich PipeWire die gedrosselte Lautstärke für diese App und ihr nächster Stream
        startet leise. Den drehen wir mit zurück – sofort, wenn er schon läuft, sonst beim
        nächsten Mal, wenn er auftaucht."""
        streams = self.streams()
        current = {s["index"]: self._vols(s) for s in streams}
        for idx, (old, ducked, app) in (saved or {}).items():
            now = current.get(idx)
            if now is not None:
                if self._close(now, ducked):   # sonst vom Nutzer verstellt: so lassen
                    self._pactl("set-sink-input-volume", str(idx), *map(str, old))
                continue
            successors = [s["index"] for s in streams if s["index"] not in saved
                          and self._app(s.get("properties") or {}) == app
                          and self._close(current[s["index"]], ducked)]
            for i in successors:
                self._pactl("set-sink-input-volume", str(i), *map(str, old))
            if not successors:
                self.pending[app] = (old, ducked)


class WindowsSessions(Backend):
    """Windows-Audiositzungen anderer Programme (pycaw); läuft im Ducker-Thread mit COM."""
    def __init__(self, own_pid):
        self.own = own_pid
        import comtypes
        comtypes.CoInitialize()
        from pycaw.pycaw import AudioUtilities
        self.utils = AudioUtilities

    def _sessions(self):
        """-> (Schlüssel, Lautstärke) je Sitzung. Ein Programm hat oft mehrere Sitzungen (Spotify,
        Teams), die sich eine Lautstärke teilen – darum zählt die Sitzung, nicht die PID."""
        for i, s in enumerate(self.utils.GetAllSessions()):
            pid = getattr(s, "ProcessId", None) or (s.Process.pid if s.Process else None)
            if pid and pid != self.own and not self._child(s):
                try:
                    key = s.InstanceIdentifier or f"{pid}#{i}"
                except Exception:  # noqa: BLE001 – Sitzung schon weg
                    key = f"{pid}#{i}"
                yield key, s.SimpleAudioVolume

    def _child(self, s):
        """Eigener Kindprozess (Player-Programm) zählt als eigene Wiedergabe."""
        try:
            return bool(s.Process) and s.Process.ppid() == self.own
        except Exception:  # noqa: BLE001 – Prozess schon weg / kein Zugriff
            return False

    def duck(self, factor):
        # Erst alle Lautstärken lesen, dann drehen: Sitzungen eines Programms teilen sich oft
        # eine Lautstärke. Läse die zweite schon die gedrosselte, wäre "alt" falsch und die Musik
        # käme nach jedem Satz nur noch auf 30 % zurück.
        found = []
        for key, vol in self._sessions():
            try:
                old = vol.GetMasterVolume()
            except OSError:
                continue
            if old > 0:
                found.append((key, vol, old))
        saved = {}
        for key, vol, old in found:
            try:
                vol.SetMasterVolume(old * factor, None)
                saved[key] = (old, old * factor)
            except OSError:
                continue
        return saved

    def restore(self, saved):
        for key, vol in self._sessions():
            if key not in (saved or {}):
                continue
            old, ducked = saved[key]
            try:
                if abs(vol.GetMasterVolume() - ducked) < 0.02:
                    vol.SetMasterVolume(old, None)
            except OSError:
                continue


class MacApps(Backend):
    APPS = ("Spotify", "Music")

    @staticmethod
    def _osa(script):
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""

    def duck(self, factor):
        saved = {}
        for app in self.APPS:
            vol = self._osa(f'if application "{app}" is running then tell application "{app}" '
                            f'to get sound volume')
            if vol.isdigit() and int(vol) > 0:
                new = int(int(vol) * factor)
                self._osa(f'tell application "{app}" to set sound volume to {new}')
                saved[app] = (int(vol), new)
        return saved

    def restore(self, saved):
        for app, (old, ducked) in (saved or {}).items():
            now = self._osa(f'if application "{app}" is running then tell application "{app}" '
                            f'to get sound volume')
            if now.isdigit() and abs(int(now) - ducked) <= 2:
                self._osa(f'tell application "{app}" to set sound volume to {old}')


def make_backend(own_pid):
    if sys.platform.startswith("linux"):
        return Pulse(own_pid) if shutil.which("pactl") else None
    if sys.platform == "win32":
        return WindowsSessions(own_pid)
    if sys.platform == "darwin":
        return MacApps()
    return None


class Ducker:
    def __init__(self, level, log=lambda m: None, backend=None, delay=RESTORE_DELAY):
        """level() -> Prozent der Lautstärke während des Duckings (100 = aus)."""
        self.level, self.log, self.delay = level, log, delay
        self.holders = set()
        self.lock = threading.Lock()
        self.q = queue.Queue()
        self.backend = backend
        self.saved = None
        self.thread = threading.Thread(target=self._run, name="ducking", daemon=True)
        self.thread.start()

    def hold(self, reason):
        with self.lock:
            self.holders.add(reason)
        self.q.put("change")

    def release(self, reason):
        with self.lock:
            self.holders.discard(reason)
        self.q.put("change")

    def close(self, timeout=2):
        with self.lock:
            self.holders.clear()
        self.q.put("close")
        self.thread.join(timeout)

    def _run(self):
        if self.backend is None:
            try:
                self.backend = make_backend(os.getpid())
            except Exception as ex:  # noqa: BLE001 – z. B. pycaw fehlt: dann eben ohne
                self.log(f"ducking: nicht verfügbar ({ex!r})")
        while True:
            msg = self.q.get()
            with self.lock:
                want = bool(self.holders)
            if msg != "close" and not want and self.saved is not None:
                time.sleep(self.delay)             # Pause zwischen zwei Sätzen abwarten
                with self.lock:
                    want = bool(self.holders)
            try:
                if want and msg != "close" and self.saved is None:
                    pct = max(0, min(100, int(self.level())))
                    if pct < 100 and self.backend is not None:
                        self.saved = self.backend.duck(pct / 100) or {}
                        self.log(f"ducking: leiser ({len(self.saved)} Wiedergaben auf {pct} %)")
                elif not want and self.saved is not None:
                    saved, self.saved = self.saved, None
                    self.backend.restore(saved)
                    self.log("ducking: wieder laut")
            except Exception as ex:  # noqa: BLE001 – Musik darf den Walkie nie stören
                self.log(f"ducking: {ex!r}")
                self.saved = None
            if msg == "close":
                return
