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

    def duck(self, factor):
        saved = {}
        for s in self.streams():
            props = s.get("properties") or {}
            if str(props.get("application.process.id", "")) == self.own or s.get("corked"):
                continue
            vols = [int(v.get("value", 0)) for v in (s.get("volume") or {}).values()]
            if not vols or max(vols) == 0:
                continue
            new = [max(0, int(v * factor)) for v in vols]
            if self._pactl("set-sink-input-volume", str(s["index"]), *map(str, new)).returncode == 0:
                saved[s["index"]] = (vols, new)
        return saved

    def restore(self, saved):
        current = {s["index"]: [int(v.get("value", 0)) for v in (s.get("volume") or {}).values()]
                   for s in self.streams()}
        for idx, (old, ducked) in (saved or {}).items():
            now = current.get(idx)
            if now is None or any(abs(a - b) > 700 for a, b in zip(now, ducked)):
                continue                       # Stream weg oder vom Nutzer verstellt
            self._pactl("set-sink-input-volume", str(idx), *map(str, old))


class WindowsSessions(Backend):
    """Windows-Audiositzungen anderer Programme (pycaw); läuft im Ducker-Thread mit COM."""
    def __init__(self, own_pid):
        self.own = own_pid
        import comtypes
        comtypes.CoInitialize()
        from pycaw.pycaw import AudioUtilities
        self.utils = AudioUtilities

    def _sessions(self):
        for s in self.utils.GetAllSessions():
            pid = getattr(s, "ProcessId", None) or (s.Process.pid if s.Process else None)
            if pid and pid != self.own:
                yield pid, s.SimpleAudioVolume

    def duck(self, factor):
        saved = {}
        for pid, vol in self._sessions():
            try:
                old = vol.GetMasterVolume()
                if old <= 0:
                    continue
                vol.SetMasterVolume(old * factor, None)
                saved[pid] = (old, old * factor)
            except OSError:
                continue
        return saved

    def restore(self, saved):
        for pid, vol in self._sessions():
            if pid not in (saved or {}):
                continue
            old, ducked = saved[pid]
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
