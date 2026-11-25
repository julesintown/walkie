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
    # eigener Startwert: ohne Konfigurationsdatei (frische Installation) ist version() None –
    # mit None als Startwert entstanden die Gesten nie, und der Tasten-Thread starb
    state = {"ver": object(), "g": None}

    def gestures():
        if S.version() != state["ver"]:
            state["ver"] = S.version()
            state["g"] = keymap.Gestures(S.get("WALKIE_KEYS"))
        return state["g"]

    learn = {"g": None}
    seen = set()

    def current():
        """Im Anlern-Modus (Einstellungen → Kopfhörer → Taste anlernen) alle Gesten erkennen
        und nur aufschreiben statt ausführen."""
        if learning():
            learn["g"] = learn["g"] or keymap.Gestures(learn=True)
        else:
            learn["g"] = None
        return learn["g"] or gestures()

    def fire(g, fired):
        for k, gesture in fired:
            if g is learn["g"]:
                write_learned(k, gesture)
                continue
            act = g.action(k, gesture)
            log(f"geste {k}/{gesture} -> {act}")
            if act and act != "none":
                emit(act)

    def win_filter(msg, data):
        """Belegte Kopfhörertasten abfangen (sonst pausiert z. B. Spotify mit), außer es ist
        ein Tastendruck, den wir selbst gesendet haben. Beim Anlernen jede Medientaste."""
        key = VK.get(data.vkCode)
        if key is None or data.flags & LLKHF_INJECTED:
            return True
        down = msg not in (0x0101, 0x0105)                    # WM_KEYUP/WM_SYSKEYUP
        if down and key not in seen:
            seen.add(key)
            log(f"taste {key} (Windows-Medientaste)")      # zeigt: die Taste kommt an
        g = current()
        if g is learn["g"] or (S.get("WALKIE_KEYS").get(key) or {}):
            fire(g, g.feed(key, 1 if down else 0, time.time()))
            listener.suppress_event()
        return True

    listener = keyboard.Listener(win32_event_filter=win_filter)
    listener.daemon = True
    listener.start()

    def smtc_key(key):
        """Taste aus der Windows-Mediensteuerung: ein Druck ohne Halten (Windows meldet nur
        „gedrückt“) – dieselbe Gesten-Erkennung, also auch Doppeldruck und Anlernen."""
        now = time.time()
        if key not in seen:
            seen.add(key)
            log(f"taste {key} (Windows-Mediensteuerung)")
        g = current()
        fire(g, g.feed(key, 1, now))
        fire(g, g.feed(key, 0, now))

    global win_remote
    try:
        win_remote = WinRemote(smtc_key, log)
    except Exception as ex:  # noqa: BLE001 – ohne winrt bleibt der Tastatur-Weg
        log(f"tasten: windows-mediensteuerung nicht verfügbar ({ex!r})")

    def poll():
        while True:
            time.sleep(0.05)
            g = current()
            fire(g, g.poll(time.time()))
    threading.Thread(target=poll, daemon=True).start()
    log("tasten: windows-medientasten")
    return True


def learning():
    """Läuft gerade das Anlernen einer Kopfhörertaste? (Die GUI frischt die Datei auf.)"""
    from hook import LEARN_FLAG
    try:
        return time.time() - LEARN_FLAG.stat().st_mtime < 60
    except OSError:
        return False


def write_learned(key, gesture):
    import json

    from hook import LEARN_LOG
    try:
        with open(LEARN_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "gesture": gesture, "ts": time.time()}) + "\n")
    except OSError:
        pass


# Bluetooth-Kopfhörer (AVRCP) schicken ihre Tasten unter Windows meist NICHT als Tastendruck:
# Windows reicht sie über die Mediensteuerung (SMTC) an die gerade aktive Wiedergabe-App weiter,
# der Tastatur-Hook sieht nichts (gemessen mit MOTIF II A.N.C.). Darum meldet sich der Walkie –
# wie auf dem Mac bei „Jetzt läuft“ – als Wiedergabe an, mit stiller Tonspur, und übernimmt die
# Tasten nach denselben Regeln (WALKIE_MAC_KEYS, siehe unten). Ohne Admin-Rechte: winrt ist ein
# normales Paket in der Walkie-Umgebung.
WIN_TERMINALS = {
    "windowsterminal.exe", "openconsole.exe", "conhost.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "wezterm-gui.exe", "alacritty.exe", "mintty.exe", "hyper.exe", "code.exe",
    "cursor.exe", "claude.exe",
    "mstsc.exe", "msrdc.exe",          # WSL über Remotedesktop/xrdp oder WSLg
}
SMTC_KEYS = {"PLAY": "PLAYPAUSE", "PAUSE": "PLAYPAUSE", "NEXT": "NEXTSONG",
             "PREVIOUS": "PREVIOUSSONG"}


def win_foreground_exe():
    """Programmdatei des Fensters im Vordergrund (klein geschrieben), sonst ''."""
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)       # QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        pass
    return ""


class WinRemote:
    """Walkie als Wiedergabe in der Windows-Mediensteuerung (nur solange er die Tasten will)."""

    def __init__(self, on_key, log):
        import winrt.windows.media as wm
        import winrt.windows.media.playback as wp
        self.wm, self.log, self.on_key = wm, log, on_key
        self.player = wp.MediaPlayer()
        self.player.command_manager.is_enabled = False     # Tasten nicht selbst abspielen lassen
        smtc = self.smtc = self.player.system_media_transport_controls
        for attr in ("is_play_enabled", "is_pause_enabled", "is_next_enabled",
                     "is_previous_enabled"):
            setattr(smtc, attr, True)
        upd = smtc.display_updater
        upd.type = wm.MediaPlaybackType.MUSIC
        upd.music_properties.title = S.get("WALKIE_NAME")
        upd.update()
        smtc.add_button_pressed(self._pressed)
        smtc.is_enabled = False
        self.owned = False
        self.dev = None
        self.hold_until = 0.0          # so lange nicht übernehmen (nach einer Musik-Taste)
        log("tasten: windows-mediensteuerung")

    def _pressed(self, _sender, args):
        try:
            name = self.wm.SystemMediaTransportControlsButton(args.button).name
        except Exception:  # noqa: BLE001
            return
        key = SMTC_KEYS.get(name)
        if key:
            self.on_key(key)

    def own(self, on):
        if on == self.owned:
            return
        if on:
            self.dev = silent_track(self.log)        # Windows wertet nur echte Wiedergabe als aktiv
            self.smtc.is_enabled = True
            self.smtc.playback_status = self.wm.MediaPlaybackStatus.PLAYING
        else:
            self.smtc.playback_status = self.wm.MediaPlaybackStatus.STOPPED
            self.smtc.is_enabled = False
            stop_track(self.dev)
            self.dev = None
        self.owned = on
        self.log(f"tasten: windows-medientasten {'übernommen' if on else 'freigegeben'}")

    def tick(self, busy):
        """Jede Sekunde aus dem Begleiter: Tasten übernehmen oder freigeben."""
        if time.time() < self.hold_until and not busy:
            want = False
        elif S.get("WALKIE_MAC_KEYS") == "always" or busy or learning():
            want = True
        else:
            want = win_foreground_exe() in WIN_TERMINALS
        self.own(want)

    def release(self, seconds=4.0):
        """Vor einer Musik-Taste: kurz loslassen, damit sie beim echten Player ankommt."""
        self.hold_until = time.time() + seconds
        self.own(False)


win_remote = None


def silent_track(log):
    """Stille Tonspur (s16 mono): wer keinen Ton ausgibt, ist für macOS und Windows keine
    laufende Wiedergabe und bekommt keine Kopfhörertasten."""
    try:
        import miniaudio

        def silence():
            need = yield b""
            while True:
                need = yield b"\x00" * (need * 2)
        dev = miniaudio.PlaybackDevice(output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                                       sample_rate=22050, buffersize_msec=200, app_name="Walkie")
        gen = silence()
        next(gen)
        dev.start(gen)
        return dev
    except Exception as ex:  # noqa: BLE001
        log(f"tasten: stille tonspur geht nicht ({ex})")
        return None


def stop_track(dev):
    if dev is not None:
        try:
            dev.stop()
            dev.close()
        except Exception:  # noqa: BLE001
            pass


def media_tick(busy):
    """Jede Sekunde aus dem Begleiter (macOS und Windows): Kopfhörertasten übernehmen oder
    freigeben."""
    for remote in (mac_remote, win_remote):
        if remote is not None:
            try:
                remote.tick(busy)
            except Exception as ex:  # noqa: BLE001
                remote.log(f"tasten: {ex!r}")


def media_release(seconds=4.0):
    for remote in (mac_remote, win_remote):
        if remote is not None:
            remote.release(seconds)


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
