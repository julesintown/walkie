"""Tasten außerhalb von Linux-evdev: globaler Hotkey (alle Systeme), Kopfhörer-Medientasten
unter Windows (pynput) und macOS („Jetzt läuft“, experimentell).

Jedes Backend ist gekapselt: fehlt eine Bibliothek oder eine Berechtigung, wird es übersprungen
und im Log vermerkt – der Begleiter läuft weiter (der Hotkey bleibt als sicherer Weg).
Aktionen gehen als Text an `emit(action)` (siehe keymap.ACTIONS).
"""
import sys
import threading
import time

import keymap
import settings as S

WIN_KEYS = {"media_play_pause": "PLAYPAUSE", "media_next": "NEXTSONG",
            "media_previous": "PREVIOUSSONG"}
LLKHF_INJECTED = 0x10          # Windows: von einem Programm gesendet (z. B. von uns selbst)
VK = {0xB3: "PLAYPAUSE", 0xB0: "NEXTSONG", 0xB1: "PREVIOUSSONG"}


def start(emit, log=print):
    """Alle passenden Backends starten. Rückgabe: Liste der aktiven Namen (für Diagnose)."""
    active = []
    for name, fn in (("hotkey", start_hotkey), ("windows-medientasten", start_windows_media),
                     ("macos-medientasten", start_mac_media)):
        try:
            if fn(emit, log):
                active.append(name)
        except Exception as ex:  # noqa: BLE001 – ein Backend darf nie den Start verhindern
            log(f"tasten: {name} aus ({ex})")
    return active


# ------------------------------------------------------------------ Hotkey
def start_hotkey(emit, log):
    combo = (S.get("WALKIE_HOTKEY") or "").strip()
    if not combo:
        return False
    if sys.platform == "darwin":
        # pynput stürzt auf macOS ab 14.6 ab (TSM-Aufruf außerhalb des Hauptthreads, SIGTRAP) –
        # dort nativ über NSEvent (wie heard). Braucht die Freigabe „Bedienungshilfen“.
        return start_mac_hotkey(combo, emit, log)
    from pynput import keyboard
    hk = keyboard.GlobalHotKeys({combo: lambda: emit("talk")})
    hk.daemon = True
    hk.start()
    log(f"tasten: hotkey {combo}")
    return True


# ------------------------------------------------------------------ Windows
def start_windows_media(emit, log):
    if sys.platform != "win32":
        return False
    from pynput import keyboard
    state = {"ver": None, "g": None}

    def gestures():
        if S.version() != state["ver"]:
            state["ver"] = S.version()
            state["g"] = keymap.Gestures(S.get("WALKIE_KEYS"))
        return state["g"]

    def handle(key, value):
        for k, gesture in gestures().feed(key, value, time.time()):
            act = gestures().action(k, gesture)
            if act and act != "none":
                emit(act)

    def win_filter(msg, data):
        """Belegte Kopfhörertasten abfangen (sonst pausiert z. B. Spotify mit), außer es ist
        ein Tastendruck, den wir selbst gesendet haben."""
        key = VK.get(data.vkCode)
        if key is None or data.flags & LLKHF_INJECTED:
            return True
        if (S.get("WALKIE_KEYS").get(key) or {}):
            handle(key, 0 if msg in (0x0101, 0x0105) else 1)   # WM_KEYUP/WM_SYSKEYUP
            listener.suppress_event()
        return True

    listener = keyboard.Listener(win32_event_filter=win_filter)
    listener.daemon = True
    listener.start()

    def poll():
        while True:
            time.sleep(0.05)
            for k, gesture in gestures().poll(time.time()):
                act = gestures().action(k, gesture)
                if act and act != "none":
                    emit(act)
    threading.Thread(target=poll, daemon=True).start()
    log("tasten: windows-medientasten")
    return True


# ------------------------------------------------------------------ macOS
MAC_KEYCODES = {"space": 49, "enter": 36, "return": 36, "tab": 48, "esc": 53, "escape": 53,
                **{f"f{i}": c for i, c in enumerate(
                    (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111), start=1)}}


def parse_mac_combo(combo):
    """'<ctrl>+<alt>+<space>' -> (Modifier-Namen, keyCode oder Zeichen)."""
    mods, key = set(), None
    for part in combo.lower().split("+"):
        p = part.strip().strip("<>")
        if p in ("ctrl", "control", "alt", "option", "shift", "cmd", "command", "super"):
            mods.add({"control": "ctrl", "option": "alt", "command": "cmd",
                      "super": "cmd"}.get(p, p))
        elif p:
            key = MAC_KEYCODES.get(p, p if len(p) == 1 else None)
    return mods, key


def start_mac_hotkey(combo, emit, log):
    """Globaler Hotkey über NSEvent (im Qt-Hauptthread aufrufen). Ohne Bedienungshilfen-Freigabe
    sieht der Monitor nichts – darum: Freigabe anfragen und den Monitor neu anlegen, sobald sie
    da ist (ein vorher angelegter bleibt tot, Erfahrung aus heard)."""
    from AppKit import (NSEvent, NSEventMaskKeyDown, NSEventModifierFlagCommand,
                        NSEventModifierFlagControl, NSEventModifierFlagOption,
                        NSEventModifierFlagShift)
    mods, key = parse_mac_combo(combo)
    if key is None:
        log(f"tasten: hotkey {combo} auf macOS nicht unterstützt")
        return False
    flags = {"ctrl": NSEventModifierFlagControl, "alt": NSEventModifierFlagOption,
             "shift": NSEventModifierFlagShift, "cmd": NSEventModifierFlagCommand}
    want = 0
    for m in mods:
        want |= flags[m]
    relevant = 0
    for f in flags.values():
        relevant |= f

    def on_key(event):
        try:
            if (event.modifierFlags() & relevant) != want:
                return
            hit = (event.keyCode() == key if isinstance(key, int)
                   else (event.charactersIgnoringModifiers() or "").lower() == key)
            if hit and not event.isARepeat():
                emit("talk")
        except Exception:  # noqa: BLE001
            pass

    state = {"monitor": None, "trusted": None}

    def ensure():
        trusted = mac_accessibility(prompt=state["trusted"] is None)
        if trusted and not state["trusted"]:
            if state["monitor"] is not None:
                NSEvent.removeMonitor_(state["monitor"])
            state["monitor"] = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown, on_key)
            log(f"tasten: hotkey {combo} (macOS)")
        state["trusted"] = trusted

    ensure()
    try:                                       # alle 10 s schauen, ob die Freigabe inzwischen da ist
        from PyQt6.QtCore import QTimer
        t = QTimer()
        t.timeout.connect(ensure)
        t.start(10_000)
        state["timer"] = t
        _keep.append(state)
    except Exception:  # noqa: BLE001
        pass
    if not state["trusted"]:
        log("tasten: hotkey wartet auf die Freigabe „Bedienungshilfen“ (Systemeinstellungen)")
    return True


_keep = []                                     # Monitor/Timer am Leben halten


def mac_accessibility(prompt=False):
    """Hat der Walkie die Freigabe „Bedienungshilfen“? prompt=True: macOS fragt einmal nach."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: bool(prompt)}))
    except Exception:  # noqa: BLE001
        return False


# Kopfhörertasten (AirPods & Co.) stellt macOS nur der App zu, die gerade „Jetzt läuft“ ist –
# und das wird nur, wer wirklich Ton ausgibt. Darum spielt der Begleiter dann eine stille
# Tonspur (Idee aus earshot). Damit Musik-Tasten sonst wie gewohnt bei Spotify & Co. landen,
# übernimmt er sie nur, wenn es passt (WALKIE_MAC_KEYS = smart):
#   - er spricht, hört zu oder eine Frage ist offen (busy), oder
#   - ein Terminal / Claude ist vorne (man arbeitet gerade mit Claude).
# „always“: immer beim Begleiter (Musik dann über die Musik-Aktionen der Tastenbelegung).
TERMINAL_APPS = {
    "com.apple.Terminal", "com.googlecode.iterm2", "net.kovidgoyal.kitty", "com.mitchellh.ghostty",
    "dev.warp.Warp-Stable", "com.github.wez.wezterm", "org.alacritty", "io.alacritty",
    "co.zeit.hyper", "com.microsoft.VSCode", "com.todesktop.230313mzl4w4u92",   # Cursor
    "com.anthropic.claudefordesktop",
}


class MacRemote:
    def __init__(self, log):
        self.log = log
        self.owned = False
        self.dev = None
        self.hold_until = 0.0          # so lange nicht übernehmen (nach einer Musik-Taste)

    def frontmost(self):
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return str(app.bundleIdentifier() or "") if app else ""
        except Exception:  # noqa: BLE001
            return ""

    def _silence(self):
        need = yield b""
        while True:
            need = yield b"\x00" * (need * 2)          # s16 mono: 2 Byte je Frame

    def own(self, on):
        if on == self.owned:
            return
        from MediaPlayer import (MPNowPlayingInfoCenter, MPNowPlayingPlaybackStatePlaying,
                                 MPNowPlayingPlaybackStateStopped)
        center = MPNowPlayingInfoCenter.defaultCenter()
        if on:
            try:
                import miniaudio
                self.dev = miniaudio.PlaybackDevice(
                    output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                    sample_rate=22050, buffersize_msec=200, app_name="Walkie")
                gen = self._silence()
                next(gen)
                self.dev.start(gen)
            except Exception as ex:  # noqa: BLE001
                self.log(f"tasten: stille tonspur geht nicht ({ex})")
            center.setNowPlayingInfo_({"title": S.get("WALKIE_NAME")})
            center.setPlaybackState_(MPNowPlayingPlaybackStatePlaying)
        else:
            if self.dev is not None:
                try:
                    self.dev.stop()
                    self.dev.close()
                except Exception:  # noqa: BLE001
                    pass
                self.dev = None
            center.setPlaybackState_(MPNowPlayingPlaybackStateStopped)
        self.owned = on
        self.log(f"tasten: macos-medientasten {'übernommen' if on else 'freigegeben'}")

    def tick(self, busy):
        """Jede Sekunde aus dem Begleiter: Tasten übernehmen oder freigeben."""
        if time.time() < self.hold_until and not busy:
            want = False
        elif S.get("WALKIE_MAC_KEYS") == "always" or busy:
            want = True
        else:
            want = self.frontmost() in TERMINAL_APPS
        self.own(want)

    def release(self, seconds=4.0):
        """Vor einer Musik-Taste: kurz loslassen, damit sie beim echten Player ankommt."""
        self.hold_until = time.time() + seconds
        self.own(False)


mac_remote = None


def start_mac_media(emit, log):
    """macOS: Kopfhörertasten über „Jetzt läuft“ (MPRemoteCommandCenter). Ohne Erfolg bleibt
    der Hotkey. AirPods: Doppelklick kommt als „nächster Titel“, Dreifachklick als „vorheriger“;
    ein Einzelklick ist auch das, was beim Herausnehmen eines Stöpsels gesendet wird."""
    global mac_remote
    if sys.platform != "darwin":
        return False
    from MediaPlayer import MPRemoteCommandCenter, MPRemoteCommandHandlerStatusSuccess

    def handler(action):
        def run(_event):
            emit(action)
            return MPRemoteCommandHandlerStatusSuccess
        return run

    mapping = S.get("WALKIE_KEYS")
    cc = MPRemoteCommandCenter.sharedCommandCenter()
    for cmd, key, name in ((cc.togglePlayPauseCommand(), "PLAYPAUSE", "toggle"),
                           (cc.playCommand(), "PLAYPAUSE", "play"),
                           (cc.pauseCommand(), "PLAYPAUSE", "pause"),
                           (cc.nextTrackCommand(), "NEXTSONG", "next"),
                           (cc.previousTrackCommand(), "PREVIOUSSONG", "prev")):
        act = mac_action((mapping.get(key) or {}).get("press"), name)
        if act and act != "none":
            cmd.setEnabled_(True)
            cmd.addTargetWithHandler_(handler(act))
    mac_remote = MacRemote(log)
    log("tasten: macos-medientasten")
    return True


def mac_action(act, command):
    """„Pause“ schickt macOS auch, wenn man einen AirPod herausnimmt – darum darf Pause das
    Mikro nur schließen, nie öffnen (Regel aus GodTerm): aus „talk“ wird dort „talk_off“."""
    if command == "pause" and act == "talk":
        return "talk_off"
    return act


def mac_tick(busy):
    if mac_remote is not None:
        try:
            mac_remote.tick(busy)
        except Exception as ex:  # noqa: BLE001
            mac_remote.log(f"tasten: {ex!r}")


def mac_release(seconds=4.0):
    if mac_remote is not None:
        mac_remote.release(seconds)
