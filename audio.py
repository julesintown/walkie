"""Aufnahme und Wiedergabe – auf Linux, macOS und Windows gleich.

Hauptweg: miniaudio (bringt seine Audio-Engine mit; Linux: PulseAudio/PipeWire/ALSA,
macOS: CoreAudio, Windows: WASAPI – keine Systempakete nötig). Nur wenn miniaudio fehlt:
Kommandozeilen-Programme (pw-record/parecord/arecord/sox bzw. pw-play/pacat/aplay/sox).

Recorder schreibt WAV 16 kHz mono s16 in eine Datei, die während der Aufnahme wächst (der
Begleiter misst daraus den Pegel). `Recorder.alive()` ist False, sobald das Gerät nichts
mehr liefert (Kopfhörer getrennt) – der Begleiter bricht dann sauber ab statt zu hängen.
"""
import os
import queue
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time

RATE = 16000
try:
    import miniaudio
except Exception:  # noqa: BLE001 – nicht installiert oder Bibliothek fehlt
    miniaudio = None


# ------------------------------------------------------------------ Geräte
def _devices():
    if miniaudio is None:
        return [], []
    try:
        d = miniaudio.Devices()
        ins = [c for c in d.get_captures() if not c["name"].startswith("Monitor of")]
        return ins, d.get_playbacks()
    except Exception:  # noqa: BLE001
        return [], []


def sources():
    """Mikrofone als [(Name, Anzeigename)] – der Name ist das, was WALKIE_MIC speichert."""
    ins, _ = _devices()
    if ins:
        return [(c["name"], c["name"]) for c in ins]
    return _pactl_sources()


def outputs():
    return [p["name"] for p in _devices()[1]]


def _device_id(name, captures=True):
    if not name or miniaudio is None:
        return None
    ins, outs = _devices()
    for dev in ins if captures else outs:
        if dev["name"] == name:
            return dev["id"]
    if captures and name.startswith(("bluez_input.", "bluez_source.")):
        # Pulse node names address pw-record directly. Miniaudio often lists their descriptions.
        labels = [label for node, label in _pactl_sources() if node == name]
        matches = [dev for dev in ins if dev["name"] in labels]
        return matches[0]["id"] if len(matches) == 1 else None
    for dev in ins if captures else outs:                      # Teilname (z. B. umbenannt)
        if name.lower() in dev["name"].lower():
            return dev["id"]
    return None


def backend():
    if miniaudio is not None:
        try:
            return f"miniaudio ({miniaudio.Devices().backend})"
        except Exception:  # noqa: BLE001
            return "miniaudio"
    tool = record_cmd("x")
    return tool[0] if tool else None


# ------------------------------------------------------------------ Aufnahme
def truncate_wav(path, nbytes):
    """WAV-Aufnahme auf nbytes Audio-Daten kürzen (z. B. das eigene „Okay“ am Ende weg)."""
    nbytes -= nbytes % 2
    try:
        with open(path, "r+b") as f:
            f.truncate(44 + nbytes)
            f.seek(0)
            f.write(_wav_header(nbytes))
    except OSError:
        pass


def _wav_header(nbytes=0x7FFFFFFF):
    return (b"RIFF" + struct.pack("<I", 36 + nbytes) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16) +
            b"data" + struct.pack("<I", nbytes))


class Recorder:
    """Aufnahme in eine wachsende WAV-Datei. start() -> bool, stop(), alive()."""

    def __init__(self):
        self.dev = None
        self.proc = None
        self.file = None
        self.last_data = 0.0
        self.bytes = 0
        self.error = ""

    def start(self, path, device=None):
        self.path = path
        if device is None and self._start_mac_voicemic(path):
            return True
        if miniaudio is not None:
            try:
                device_id = _device_id(device)
                if device and device_id is None:
                    raise ValueError(f"Mikrofon nicht gefunden: {device}")
                self.file = open(path, "wb")
                self.file.write(_wav_header())
                self.file.flush()
                self.dev = miniaudio.CaptureDevice(
                    input_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                    sample_rate=RATE, buffersize_msec=100,
                    device_id=device_id, app_name="Walkie")
                gen = self._sink()
                next(gen)
                self.last_data = time.time()
                self.dev.start(gen)
                return True
            except Exception as ex:  # noqa: BLE001
                self.error = str(ex)
                self._close_file()
                self.dev = None
        cmd = record_cmd(path, device)
        if cmd is None:
            self.error = self.error or "kein Aufnahmeprogramm"
            return False
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.last_data = time.time()
            return True
        except OSError as ex:
            self.error = str(ex)
            return False

    def data_bytes(self):
        """Wie viele Audio-Bytes bisher in der Datei stehen (ohne WAV-Kopf)."""
        if self.dev is not None or getattr(self, "piped", False):
            return self.bytes
        try:
            return max(0, os.path.getsize(self.path) - 44)
        except OSError:
            return 0

    def _start_mac_voicemic(self, path):
        """macOS, experimentell (WALKIE_MAC_VOICE_PROCESSING): Aufnahme über mac/voicemic.swift
        mit Echo- und Rauschunterdrückung. Fehlt es oder scheitert es: der normale Weg."""
        if sys.platform != "darwin":
            return False
        try:
            import settings as S
            if not S.get("WALKIE_MAC_VOICE_PROCESSING"):
                return False
        except Exception:  # noqa: BLE001
            return False
        exe = mac_voicemic_path()
        if not exe.exists():
            return False
        try:
            self.file = open(path, "wb")
            self.file.write(_wav_header())
            self.file.flush()
            self.proc = subprocess.Popen([str(exe)], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)
        except OSError as ex:
            self.error = str(ex)
            self._close_file()
            return False
        self.last_data = time.time()
        self.piped = True
        sink = self._sink()
        next(sink)

        stdout = self.proc.stdout

        def pump():
            with stdout:
                while chunk := stdout.read(3200):
                    sink.send(chunk)
        self.pump = threading.Thread(target=pump, daemon=True)
        self.pump.start()
        return True

    def _sink(self):
        while True:
            data = yield
            if data:
                raw = bytes(data)                  # kommt als array('h') – len() wären Samples
                self.last_data = time.time()
                self.bytes += len(raw)
                try:
                    self.file.write(raw)
                    self.file.flush()
                except (OSError, ValueError):
                    return

    def alive(self, stale=2.5):
        """Kommt noch Audio? (Gerät weg -> False nach `stale` Sekunden ohne Daten)."""
        if self.dev is not None:
            return time.time() - self.last_data < stale
        if self.proc is not None:
            if self.proc.poll() is not None:
                return False
            if getattr(self, "piped", False):
                return time.time() - self.last_data < stale
            try:
                size = os.path.getsize(self.path)
            except OSError:
                return False
            if size > self.bytes:
                self.bytes, self.last_data = size, time.time()
            return time.time() - self.last_data < stale
        return False

    def stop(self):
        if self.dev is not None:
            try:
                self.dev.stop()
                self.dev.close()
            except Exception:  # noqa: BLE001
                pass
            self.dev = None
            self._close_file(fix=True)
        if self.proc is not None:
            try:
                if sys.platform == "win32":
                    self.proc.terminate()
                else:
                    self.proc.send_signal(signal.SIGINT)
                self.proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
                self.proc.wait()
            self.proc = None
            if getattr(self, "piped", False):
                self.pump.join(timeout=1)
                self.piped = False
                self._close_file(fix=True)

    def _close_file(self, fix=False):
        if not self.file:
            return
        try:
            if fix:
                self.file.seek(0)
                self.file.write(_wav_header(self.bytes))
            self.file.close()
        except (OSError, ValueError):
            pass
        self.file = None


# ------------------------------------------------------------------ Wiedergabe
def bluetooth_playback_target():
    """Return a Linux Bluetooth sink, or an empty name while its profile is switching.

    None means there is no Bluetooth audio card and system playback is available.
    """
    if not sys.platform.startswith("linux") or not shutil.which("pactl"):
        return None
    import json
    import headset_audio
    try:
        cards = json.loads(headset_audio.pactl("-f", "json", "list", "cards"))
        addresses = {headset_audio.address(card["name"]) for card in cards}
        addresses.discard("")
        if not addresses:
            return None
        sinks = json.loads(headset_audio.pactl("-f", "json", "list", "sinks"))
        names = [sink["name"] for sink in sinks if headset_audio.address(sink["name"]) in addresses]
        if len(names) == 1:
            return names[0]
        default = headset_audio.pactl("get-default-sink")
        return default if default in names else ""
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return ""


class Player:
    """Spielt s16-mono-PCM, das stückweise kommt (Vorlesen Satz für Satz).
    write(bytes) · finish() wartet, bis alles gespielt ist · abort() bricht sofort ab."""

    def __init__(self, rate, device=None):
        self.rate = rate
        self.q = queue.Queue()
        self.buf = b""
        self.done = threading.Event()
        self.first_audio = None
        self.aborted = False
        self.dev = None
        self.proc = None
        target = bluetooth_playback_target() if device is None else None
        if target is not None:
            # An unbound stream could move to the speakers during a profile change.
            if target and shutil.which("pw-play"):
                cmd = ["pw-play", "--target", target, "--properties",
                       '{ node.dont-fallback = true node.dont-reconnect = true }',
                       "--raw", "--rate", str(rate), "--channels", "1", "--format", "s16", "-"]
            elif target and shutil.which("pacat"):
                cmd = ["pacat", "--playback", "--device", target,
                       f"--rate={rate}", "--channels=1", "--format=s16le"]
            else:
                return
            self._start_process(cmd)
            return
        if miniaudio is not None:
            try:
                self.dev = miniaudio.PlaybackDevice(
                    output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                    sample_rate=rate, buffersize_msec=120,
                    device_id=_device_id(device, captures=False), app_name="Walkie")
                gen = self._source()
                next(gen)
                self.dev.start(gen)
                return
            except Exception:  # noqa: BLE001
                self.dev = None
        cmd = play_cmd(rate)
        if cmd:
            self._start_process(cmd)

    def _start_process(self, cmd):
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.proc = None

    @property
    def ok(self):
        return self.dev is not None or self.proc is not None

    def _source(self):
        need = yield b""
        ended = False
        while True:
            want = need * 2
            while len(self.buf) < want and not ended:
                try:
                    chunk = self.q.get(timeout=0.02)
                except queue.Empty:
                    break
                if chunk is None:
                    ended = True
                else:
                    self.buf += chunk
            out, self.buf = self.buf[:want], self.buf[want:]
            if ended and not out:
                self.done.set()
            if self.aborted:
                out = b""
                self.done.set()
            if self.first_audio and any(out):
                self.first_audio()
                self.first_audio = None
            need = yield out + b"\0" * (want - len(out))   # Lücken mit Stille füllen

    def write(self, data):
        if self.aborted:
            return
        if self.dev is not None:
            self.q.put(bytes(data))
        elif self.proc is not None:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
                if self.first_audio and any(data):
                    self.first_audio()
                    self.first_audio = None
            except (BrokenPipeError, OSError):
                self.aborted = True

    def finish(self, timeout=120):
        if self.dev is not None:
            self.q.put(None)
            self.done.wait(timeout)
            time.sleep(0.15)                       # Rest im Gerätepuffer ausspielen
            self._close()
        elif self.proc is not None:
            self._close_pipe()
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None

    def abort(self):
        self.aborted = True
        if self.proc is not None:
            try:
                self.proc.terminate()
            except OSError:
                pass
            self._close_pipe()
        self.done.set()

    def _close_pipe(self):
        """stdin zum Abspieler schließen. Ist der schon weg, schlägt das Leeren des Puffers
        fehl – ohne zweites close() meldet Python das später beim Aufräumen
        („Exception ignored … BrokenPipeError“)."""
        for _ in range(2):
            try:
                self.proc.stdin.close()
                return
            except OSError:
                continue

    def _close(self):
        try:
            self.dev.stop()
            self.dev.close()
        except Exception:  # noqa: BLE001
            pass
        self.dev = None


def play_pcm(data, rate, wait=False):
    """Kurzes PCM (z. B. Signalton) abspielen."""
    def run():
        p = Player(rate)
        if p.ok:
            p.write(data)
            p.finish(timeout=5)
    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()


# ------------------------------------------------------------------ Rückfall: Programme
def record_cmd(path, device=None):
    """device: Name einer PipeWire/Pulse-Quelle, None = Standard."""
    if shutil.which("pw-record"):
        dev = ["--target", device] if device else []
        return ["pw-record", *dev, "--rate", "16000", "--channels", "1", "--format", "s16", path]
    if shutil.which("parecord"):
        dev = [f"--device={device}"] if device else []
        return ["parecord", *dev, "--rate=16000", "--channels=1", "--format=s16le",
                "--file-format=wav", path]
    if device:
        return None
    if shutil.which("arecord"):
        return ["arecord", "-q", "-r", "16000", "-c", "1", "-f", "S16_LE", "-t", "wav", path]
    if shutil.which("rec"):
        return ["rec", "-q", "-r", "16000", "-c", "1", "-b", "16", "-e", "signed-integer", path]
    return None


def play_cmd(rate):
    """Spielt rohes s16-mono-Audio von stdin."""
    if shutil.which("pw-play"):
        return ["pw-play", "--raw", "--rate", str(rate), "--channels", "1", "--format", "s16", "-"]
    if shutil.which("pacat"):
        return ["pacat", "--playback", f"--rate={rate}", "--channels=1", "--format=s16le"]
    if shutil.which("aplay"):
        return ["aplay", "-q", "-r", str(rate), "-c", "1", "-f", "S16_LE", "-t", "raw", "-"]
    if shutil.which("play"):
        return ["play", "-q", "-t", "raw", "-r", str(rate), "-c", "1", "-b", "16",
                "-e", "signed-integer", "-"]
    return None


def _pactl_sources():
    import json
    if not shutil.which("pactl"):
        return []
    try:
        out = subprocess.run(["pactl", "-f", "json", "list", "sources"], capture_output=True,
                             text=True, timeout=5).stdout
        items = json.loads(out or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [(i["name"], i.get("description") or i["name"]) for i in items
            if not i["name"].endswith(".monitor")]


# ------------------------------------------------------------------ Mikro anderweitig belegt?
# Telefoniert der Nutzer oder diktiert woanders, soll der Begleiter nicht dazwischenreden
# (Idee aus heard). Eigene Aufnahmen, Pegelanzeigen und Mitschnitte des Desktop-Tons zählen nicht.
METER_APPS = ("pavucontrol", "plasma-pa", "kmix", "gnome-control-center", "easyeffects",
              "pipewire", "wireplumber", "desktop walkie")


def other_app_using_mic(own_pids=None):
    """True, wenn gerade eine andere App von einem echten Mikrofon aufnimmt."""
    own = set(own_pids or ()) | {os.getpid()}
    try:
        if sys.platform.startswith("linux"):
            return _linux_mic_busy(own)
        if sys.platform == "darwin":
            return _mac_mic_busy()
    except Exception:  # noqa: BLE001 – im Zweifel: nicht belegt
        pass
    return False


def _linux_mic_busy(own):
    import json
    run = lambda *a: subprocess.run(["pactl", "-f", "json", *a], capture_output=True,  # noqa: E731
                                    text=True, timeout=3).stdout or "[]"
    sources = {s.get("index"): s.get("name", "") for s in json.loads(run("list", "sources"))}
    for o in json.loads(run("list", "source-outputs")):
        props = o.get("properties") or {}
        name = sources.get(o.get("source"), "")
        if not name or name.endswith(".monitor") or o.get("corked"):
            continue
        try:
            pid = int(props.get("application.process.id") or 0)
        except ValueError:
            pid = 0
        app = " ".join(str(props.get(k, "")) for k in
                       ("application.name", "application.id", "media.name")).lower()
        if pid in own or any(m in app for m in METER_APPS) or "peak detect" in app:
            continue
        return True
    return False


def _mac_mic_busy():
    """CoreAudio: läuft das Standard-Eingabegerät irgendwo? (wie heard, per ctypes)."""
    import ctypes
    import struct
    ca = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")

    def fourcc(s):
        return struct.unpack(">I", s.encode())[0]

    class Addr(ctypes.Structure):
        _fields_ = [("sel", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("elem", ctypes.c_uint32)]

    glob, main = fourcc("glob"), 0
    dev = ctypes.c_uint32(0)
    size = ctypes.c_uint32(4)
    a = Addr(fourcc("dIn "), glob, main)                 # kAudioHardwarePropertyDefaultInputDevice
    if ca.AudioObjectGetPropertyData(1, ctypes.byref(a), 0, None, ctypes.byref(size),
                                     ctypes.byref(dev)) or not dev.value:
        return False
    running = ctypes.c_uint32(0)
    size = ctypes.c_uint32(4)
    a = Addr(fourcc("gone"), glob, main)                 # kAudioDevicePropertyDeviceIsRunningSomewhere
    if ca.AudioObjectGetPropertyData(dev.value, ctypes.byref(a), 0, None, ctypes.byref(size),
                                     ctypes.byref(running)):
        return False
    return bool(running.value)


def default_output_name():
    """Name des Standard-Ausgabegeräts (für „ist das ein Kopfhörer?“) – oder ""."""
    try:
        if sys.platform.startswith("linux") and shutil.which("pactl"):
            return subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True,
                                  timeout=3).stdout.strip()
        if miniaudio is not None:
            for d in miniaudio.Devices().get_playbacks():
                if d.get("is_default"):
                    return d.get("name", "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def mac_voicemic_path():
    """Wohin `walkie setup` das Swift-Hilfsprogramm mac/voicemic.swift übersetzt."""
    from pathlib import Path
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data / "walkie" / "voicemic"


def build_mac_voicemic(src_dir, log=print):
    """macOS: voicemic übersetzen (braucht die Xcode-Kommandozeilenwerkzeuge). True bei Erfolg."""
    if sys.platform != "darwin" or not shutil.which("swiftc"):
        return False
    from pathlib import Path
    src, plist = Path(src_dir) / "mac" / "voicemic.swift", Path(src_dir) / "mac" / "voicemic.plist"
    exe = mac_voicemic_path()
    exe.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["swiftc", "-O", str(src), "-o", str(exe), "-Xlinker", "-sectcreate",
                        "-Xlinker", "__TEXT", "-Xlinker", "__info_plist", "-Xlinker", str(plist)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        log("  ⚠ Mac-Mikrofon mit Echounterdrückung nicht übersetzt: " + r.stderr.strip()[-300:])
        return False
    return True
