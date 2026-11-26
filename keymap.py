"""Kopfhörertasten: Gesten erkennen (einmal / doppelt / lang) und Aktionen zuordnen.

Ohne Hardware testbar: `Gestures.feed(taste, wert, t)` mit evdev-Werten
(1 = gedrückt, 2 = gehalten/Wiederholung, 0 = losgelassen) und `poll(t)` für
abgelaufene Einzel-Drücke. Beide geben [(taste, geste), …] zurück.
"""

# Aktion -> Anzeige (GUI, CLI, Skill)
ACTIONS = {
    "talk": "Reden / antworten",
    "repeat": "Wiederholen",
    "allow": "Freigabe erlauben",
    "deny": "Freigabe ablehnen",
    "stop_speaking": "Ruhe (Sprechen beenden)",
    "terminal": "Terminal zeigen",
    "show": "Fenster der Session nach vorne",
    "missed": "Was habe ich verpasst?",
    "media_toggle": "Musik: Play/Pause",
    "media_next": "Musik: Vor",
    "media_prev": "Musik: Zurück",
    "none": "Nichts",
}
GESTURES = {"press": "einmal", "double": "doppelt", "long": "lang halten"}

# Gerätespezifische Namen derselben Taste vereinheitlichen
ALIASES = {"PLAY": "PLAYPAUSE", "PAUSE": "PLAYPAUSE", "PLAYCD": "PLAYPAUSE",
           "PAUSECD": "PLAYPAUSE", "NEXT": "NEXTSONG", "PREVIOUS": "PREVIOUSSONG"}
KEY_NAMES = {"PLAYPAUSE": "Play/Pause", "NEXTSONG": "Vor", "PREVIOUSSONG": "Zurück",
             "STOPCD": "Stopp", "VOLUMEUP": "Lauter", "VOLUMEDOWN": "Leiser",
             "PHONE": "Anruf-Taste"}

DOUBLE_S = 0.42      # zweiter Druck innerhalb -> doppelt
LONG_S = 0.65        # so lange gehalten -> lang
DEDUP_S = 0.15       # manche Kopfhörer senden PLAY+PAUSE für einen Druck


def normalize(code_name):
    """'KEY_PLAYCD' oder ['KEY_PLAYCD', …] (evdev) -> 'PLAYPAUSE'."""
    if isinstance(code_name, (list, tuple)):
        code_name = code_name[0]
    name = str(code_name).removeprefix("KEY_")
    return ALIASES.get(name, name)


def key_label(key):
    """Anzeigename einer Taste in der Oberflächensprache."""
    from i18n import t
    return t(KEY_NAMES[key]) if key in KEY_NAMES else key.title()


def action_label(action):
    """Anzeigename einer Aktion (ACTIONS) in der Oberflächensprache."""
    from i18n import t
    return t(ACTIONS[action]) if action in ACTIONS else action


def gesture_label(gesture):
    """Anzeigename einer Geste (GESTURES) in der Oberflächensprache."""
    from i18n import t
    return t(GESTURES[gesture]) if gesture in GESTURES else gesture


class Gestures:
    def __init__(self, mapping=None, learn=False):
        self.mapping = mapping or {}
        self.learn = learn     # Anlernen: alle Gesten jeder Taste erkennen
        self.down = {}         # Taste -> Zeitpunkt des Drückens
        self.long_fired = set()
        self.pending = {}      # Taste -> Zeitpunkt eines Einzel-Drucks, der evtl. doppelt wird
        self.last_down = {}

    def _needs(self, key, gesture):
        return self.learn or gesture in (self.mapping.get(key) or {})

    def _wait_for_double(self, key):
        return self._needs(key, "double")

    def feed(self, key, value, t):
        out = []
        if value == 1:
            if t - self.last_down.get(key, -9) < DEDUP_S:
                return out                       # Doppelsignal eines Drucks
            self.last_down[key] = t
            self.down[key] = t
            self.long_fired.discard(key)
            if key in self.pending:              # zweiter Druck -> doppelt
                del self.pending[key]
                out.append((key, "double"))
                self.long_fired.add(key)         # Loslassen danach ignorieren
            elif not self._wait_for_double(key) and not self._needs(key, "long"):
                out.append((key, "press"))       # nichts anderes belegt -> sofort
                self.long_fired.add(key)
        elif value == 2:
            t0 = self.down.get(key)
            if t0 is not None and key not in self.long_fired and t - t0 >= LONG_S:
                self.long_fired.add(key)
                out.append((key, "long"))
        elif value == 0:
            t0 = self.down.pop(key, None)
            if t0 is None or key in self.long_fired:
                self.long_fired.discard(key)
                return out
            if t - t0 >= LONG_S and self._needs(key, "long"):
                out.append((key, "long"))
            elif self._wait_for_double(key):
                self.pending[key] = t
            else:
                out.append((key, "press"))
        return out

    def poll(self, t):
        out = []
        for key, t0 in list(self.pending.items()):
            if t - t0 >= DOUBLE_S:
                del self.pending[key]
                out.append((key, "press"))
        # Kopfhörer ohne Loslass-Ereignis: gedrückt + nie losgelassen -> nach kurzer Zeit
        # als Einzel-Druck werten
        for key, t0 in list(self.down.items()):
            if key not in self.long_fired and t - t0 >= 1.5:
                del self.down[key]
                if self._wait_for_double(key):
                    self.pending[key] = t
                else:
                    out.append((key, "press"))
        return out

    def action(self, key, gesture):
        return (self.mapping.get(key) or {}).get(gesture)


def avrcp_devices():
    """Volle Gerätenamen aller Bluetooth-Medientasten ('<Name> (AVRCP)'), ohne Leserechte."""
    import re
    from pathlib import Path
    try:
        text = Path("/proc/bus/input/devices").read_text()
    except OSError:
        return []
    return [n for n in re.findall(r'^N: Name="(.*)"$', text, re.M) if n.endswith("(AVRCP)")]


def matches(mode, devname):
    """Passt ein Gerät zur Einstellung WALKIE_HEADSET? auto = jeder Kopfhörer, off = keiner,
    sonst der Name – mit oder ohne ' (AVRCP)'."""
    mode = (mode or "auto").strip()
    if mode.lower() == "off":
        return False
    if mode.lower() == "auto":
        return devname.endswith("(AVRCP)")
    # fester Name: auch Geräte ohne AVRCP (z. B. USB-Fernbedienung)
    return mode.removesuffix(" (AVRCP)") == devname.removesuffix(" (AVRCP)")


def connected_headsets():
    """Anzeigenamen verbundener Kopfhörer (ohne ' (AVRCP)')."""
    return [n.removesuffix(" (AVRCP)") for n in avrcp_devices()]


SPEAKER_WORDS = ("built-in", "eingebaut", "speaker", "lautsprecher", "hdmi", "displayport",
                 "monitor", "analog", "realtek", "intel", "dummy", "null", "macbook", "internal")


def headset_audio(outputs):
    """Welche Audioausgänge sind (vermutlich) Kopfhörer? Bluetooth-Namen bevorzugt."""
    named = [n.lower() for n in connected_headsets()]
    out = [o for o in outputs if any(h in o.lower() or o.lower() in h for h in named)]
    return out or [o for o in outputs if not any(w in o.lower() for w in SPEAKER_WORDS)]


RULE = "70-walkie-avrcp.rules"
RULE_DEST = "/etc/udev/rules.d/" + RULE


def keys_need_unlock():
    """Linux: Ist die udev-Regel (Leserechte für die Kopfhörertasten) noch nicht installiert?"""
    import os
    import sys
    return sys.platform.startswith("linux") and not os.path.exists(RULE_DEST)


def unlock_command(src):
    """Befehl, der die Regel installiert – mit grafischer Passwortabfrage (pkexec), sonst None."""
    import shlex
    import shutil
    if not shutil.which("pkexec"):
        return None
    script = (f"install -m 0644 {shlex.quote(str(src))} {RULE_DEST} && "
              "udevadm control --reload && "
              "udevadm trigger --subsystem-match=input --action=change")
    return ["pkexec", "sh", "-c", script]


def unlock_hint(src):
    return (f"sudo install -m 0644 {src} {RULE_DEST} && sudo udevadm control --reload "
            "&& sudo udevadm trigger --subsystem-match=input --action=change")


def key_status():
    """(ok, Text) – ob Kopfhörertasten auf diesem System ankommen können."""
    import os
    import sys

    from i18n import t
    if sys.platform.startswith("linux"):
        import re
        from pathlib import Path
        try:
            text = Path("/proc/bus/input/devices").read_text()
        except OSError:
            return None, t("Tastengeräte nicht lesbar")
        for block in text.split("\n\n"):
            m = re.search(r'^N: Name="(.*\(AVRCP\))"$', block, re.M)
            h = re.search(r"^H: Handlers=.*?(event\d+)", block, re.M)
            if m and h:
                if os.access(f"/dev/input/{h.group(1)}", os.R_OK):
                    return True, t("Tasten von {device} werden erkannt", device=m.group(1)[:-8])
                if keys_need_unlock():
                    return False, t("Tasten brauchen einmalig eine Freigabe – „Tasten "
                                  "freischalten“ (fragt nach deinem Passwort). Bis dahin: "
                                  "Klick auf die Figur oder der Hotkey")
                return False, t("Freigabe ist da – Kopfhörer einmal neu verbinden")
        return None, t("Kein Bluetooth-Kopfhörer mit Medientasten verbunden")
    if sys.platform == "win32":
        return True, t("Medientasten kommen über Windows an (Play/Pause, Vor, Zurück)")
    if sys.platform == "darwin":
        return None, t("macOS: Medientasten über „Jetzt läuft“ (experimentell) – "
                       "der Hotkey funktioniert immer")
    return None, t("Medientasten auf diesem System nicht unterstützt – Hotkey nutzen")
