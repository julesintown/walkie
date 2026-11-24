"""Zentrale Einstellungen des Walkie (nur Standardbibliothek).

Eine Datei für alle: ~/.config/walkie/config.env (KEY=Wert, shell-quotiert).
Begleiter, Hooks (auch aus dem Plugin-Cache), GUI, `walkie`-CLI und der Claude-Skill
lesen und schreiben dieselbe Datei. Umgebungsvariablen haben Vorrang (zum Testen).

    import settings as S
    S.get("WALKIE_ANNOUNCE")          # -> True (typisiert, Datei wird bei Änderung neu gelesen)
    S.set("WALKIE_SCALE", 5)
    S.SCHEMA                          # alle Einstellungen mit Titel, Hilfe, Gruppe, Auswahl
"""
import json
import os
import shlex
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FIGURE = HERE / "figures" / "walkie"
CONFIG = Path(os.environ.get("WALKIE_CONFIG") or Path(
    os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "walkie" / "config.env")

GROUPS = {
    "general": "Allgemein",
    "figure": "Figur",
    "headset": "Kopfhörer",
    "ask": "Fragen & Freigaben",
    "voice": "Sprache & Modelle",
}

# Tasten (evdev-Namen ohne KEY_) -> Geste -> Aktion; siehe keymap.py
DEFAULT_KEYS = {
    "PLAYPAUSE": {"press": "talk"},
    "NEXTSONG": {"press": "media_toggle"},
    "PREVIOUSSONG": {"press": "media_toggle", "double": "repeat", "long": "missed"},
}


@dataclass
class Setting:
    key: str
    type: str                  # bool | int | float | str | choice | path | json
    default: object
    group: str
    title: str
    help: str = ""
    choices: list = field(default_factory=list)   # für choice: [(Wert, Anzeige), …]
    restart: bool = False      # greift erst nach Neustart des Begleiters
    min: float = None
    max: float = None
    advanced: bool = False

    def to_json(self, value):
        return {"key": self.key, "type": self.type, "default": self.default,
                "value": value, "group": GROUPS[self.group], "title": self.title,
                "help": self.help, "choices": [c[0] for c in self.choices],
                "restart": self.restart, "min": self.min, "max": self.max}


# Name im Menü -> (Piper-Modell, Aussprache). None = native Aussprache der Stimme.
VOICES = {
    "Deutsch · Thorsten (männlich)": ("de_DE-thorsten-medium", None),
    "Deutsch · Thorsten, beste Qualität (männlich)": ("de_DE-thorsten-high", None),
    "Deutsch · Kerstin (weiblich)": ("de_DE-kerstin-medium", None),
    "Deutsch · Ramona (weiblich)": ("de_DE-ramona-low", None),
    "English (US) · Lessac (female)": ("en_US-lessac-medium", None),
    "English (US) · Ryan (male)": ("en_US-ryan-medium", None),
    "English (UK) · Jenny (female)": ("en_GB-jenny_dioco-medium", None),
    "English (UK) · Alan (male)": ("en_GB-alan-medium", None),
    "Français · Siwis (féminin)": ("fr_FR-siwis-medium", None),
    "Français · Tom (masculin)": ("fr_FR-tom-medium", None),
    "Español (España) · Davefx": ("es_ES-davefx-medium", None),
    "Español (México) · Claude": ("es_MX-claude-high", None),
    "Italiano · Paola (femminile)": ("it_IT-paola-medium", None),
    "Português (Brasil) · Faber": ("pt_BR-faber-medium", None),
    "Nederlands · Nathalie (België)": ("nl_BE-nathalie-medium", None),
    "Nederlands · MLS": ("nl_NL-mls-medium", None),
    "Polski · Gosia (kobieta)": ("pl_PL-gosia-medium", None),
    "Polski · Darkman (mężczyzna)": ("pl_PL-darkman-medium", None),
    "Türkçe · DFKI": ("tr_TR-dfki-medium", None),
    "Русский · Ирина": ("ru_RU-irina-medium", None),
    "Русский · Дмитрий": ("ru_RU-dmitri-medium", None),
    "Українська": ("uk_UA-ukrainian_tts-medium", None),
    "Svenska · NST": ("sv_SE-nst-medium", None),
    "中文 · Huayan": ("zh_CN-huayan-medium", None),
}
DEFAULT_VOICE = "Deutsch · Thorsten (männlich)"

AGENTS = [("claude", "Claude Code"), ("codex", "Codex"), ("gemini", "Gemini CLI"),
          ("antigravity", "Antigravity CLI"), ("custom", "Eigener Befehl")]
ANSWER_MODES = [("auto", "Nach der Frage automatisch zuhören"),
                ("key", "Nur auf Tastendruck zuhören")]

SCHEMA = [
    # ---- Allgemein
    Setting("WALKIE_UI_LANG", "choice", "auto", "general", "Sprache der Oberfläche",
            "Beim Wechsel folgen Menüs, Ansagen, Spracherkennung und Stimme. Automatisch verwendet die Systemsprache.",
            [("auto", "Automatisch"), ("de", "Deutsch"), ("en", "English")]),
    Setting("WALKIE_NAME", "str", "Walkie", "general", "Name",
            "So heißt die Figur in Hinweisen und im Agent-Prompt.", restart=True),
    Setting("WALKIE_AGENT", "choice", "claude", "general", "Hauptagent",
            "Läuft im Terminal über der Figur, beantwortet Fragen an den Begleiter und öffnet "
            "neue Sessions.", AGENTS, restart=True),
    Setting("WALKIE_AGENT_2", "choice", "none", "general", "Zweitagent",
            "Kommt nur zum Zug, wenn du ihn ausdrücklich ansprichst (z. B. „frag Codex …“): "
            "öffnet dafür eine neue Session. Nur Claude-Sessions kann der Begleiter danach "
            "vorlesen und weiter ansprechen.",
            [("none", "Keiner")] + [a for a in AGENTS if a[0] != "custom"]),
    Setting("WALKIE_AGENT_CMD", "str", "", "general", "Eigener Agent-Befehl",
            "Nur für „Eigener Befehl“, z. B. aider oder opencode.", restart=True),
    Setting("WALKIE_AGENT_MODEL", "str", "", "voice", "Modell des Terminal-Agents",
            "Leer = Standard des Agents. Bei Claude z. B. sonnet, opus oder haiku.",
            restart=True),
    Setting("WALKIE_WORKDIR", "path", "", "general", "Arbeitsordner des Agents",
            "Leer = Ordner des Walkie.", restart=True),
    Setting("WALKIE_SESSION_DIR", "path", "", "general", "Ordner für neue Sessions",
            "Hier starten neue Sessions ohne genanntes Projekt. Leer = eigener Walkie-Ordner "
            "(Claude fragt dort nur einmal nach der Freigabe)."),
    Setting("WALKIE_LOGIN_AUTOSTART", "bool", False, "general", "Beim Anmelden starten",
            "Legt einen Autostart-Eintrag an."),
    Setting("WALKIE_AUTOSTART", "bool", False, "general", "Mit der ersten Claude-Session starten",
            "Nur mit dem Claude-Plugin."),
    Setting("WALKIE_WANDER", "bool", True, "general", "Herumlaufen"),
    Setting("WALKIE_CLIMB", "bool", True, "general", "Klettern & Fensterkanten",
            "Fällt nach dem Loslassen auf Fenster oder Boden, sitzt auf Fensterkanten, "
            "klettert an Bildschirmrändern hoch (wenn die Figur das kann, z. B. Shimejis)."),
    Setting("WALKIE_NOTIFY", "bool", True, "general", "Desktop-Benachrichtigungen"),

    # ---- Figur
    Setting("WALKIE_SPRITE", "path", "", "figure", "Figur (Sprite-Ordner)",
            "Leer = Walkie. Ordner mit AnimData.xml + *-Anim.png (siehe figures/CREDITS.md)."),
    Setting("WALKIE_SCALE", "int", 4, "figure", "Größe", "Pixel-Vergrößerung.", min=2, max=8),

    # ---- Kopfhörer
    Setting("WALKIE_HEADSET", "str", "auto", "headset", "Kopfhörer",
            "auto = jeder Bluetooth-Kopfhörer, off = aus, sonst genauer Gerätename.",
            restart=True),
    Setting("WALKIE_BARGE_IN", "bool", True, "voice", "Unterbrechen durch Reden",
            "„Stopp“, „warte“ oder einfach Losreden beendet das Vorlesen. Nur mit Kopfhörern und "
            "einem eigenen Mikro (Laptop, USB) – das Bluetooth-Mikro würde den Kopfhörer sonst "
            "in den Telefonmodus schalten; dort unterbricht ein Tastendruck."),
    Setting("WALKIE_MAC_VOICE_PROCESSING", "bool", False, "voice",
            "Mikro mit Echounterdrückung (macOS, experimentell)",
            "Nimmt über die Sprachverarbeitung von macOS auf (filtert die eigene Stimme und "
            "Hintergrundgeräusche). Fällt automatisch auf die normale Aufnahme zurück.",
            advanced=True),
    Setting("WALKIE_QUIET_WHEN_MIC", "bool", True, "voice", "Nicht reinreden",
            "Nimmt eine andere App vom Mikrofon auf (Telefonat, Diktat), hält der Walkie seine "
            "Ansagen zurück und holt sie danach nach."),
    Setting("WALKIE_HOTKEY", "str", "<ctrl>+<alt>+<space>", "headset", "Hotkey zum Reden",
            "Funktioniert immer, auch ohne Kopfhörertasten. Leer = aus. Schreibweise wie "
            "<ctrl>+<alt>+<space> oder <ctrl>+<shift>+b.", restart=True),
    Setting("WALKIE_MAC_KEYS", "choice", "smart", "headset", "Kopfhörertasten (macOS)",
            "smart = beim Walkie, wenn er spricht, zuhört oder fragt oder ein Terminal/Claude vorne "
            "ist – sonst steuern sie wie gewohnt die Musik. always = immer beim Walkie.",
            [("smart", "Smart"), ("always", "Immer beim Walkie")], advanced=True),
    Setting("WALKIE_KEYS", "json", DEFAULT_KEYS, "headset", "Tastenbelegung",
            "Taste → Geste (press/double/long) → Aktion."),

    # ---- Fragen & Freigaben
    Setting("WALKIE_ANNOUNCE", "bool", True, "ask", "Ansagen",
            "Die Figur sagt laut, was in deinen Sessions passiert."),
    Setting("WALKIE_ANNOUNCE_ATTENTION", "bool", True, "ask", "… wenn eine Session dich braucht"),
    Setting("WALKIE_ANNOUNCE_ERROR", "bool", True, "ask", "… bei Fehlern"),
    Setting("WALKIE_ANNOUNCE_DONE", "bool", True, "ask", "… wenn eine Session fertig ist"),
    Setting("WALKIE_DUCK", "int", 30, "ask", "Musik leiser beim Zuhören und Vorlesen (%)",
            "Andere Programme spielen so lange mit diesem Anteil ihrer Lautstärke weiter und "
            "danach wieder wie vorher. 100 = nicht leiser.", min=0, max=100),
    Setting("WALKIE_ANNOUNCE_AFTER", "int", 20, "ask", "„Fertig“ erst nach … Sekunden Arbeit",
            "Kurze Hin-und-her-Runden werden nicht angesagt.", min=0, max=600),
    Setting("WALKIE_SUMMARY", "choice", "claude", "ask", "Antworten zusammenfassen",
            "Lange Antworten in einem Satz (kostet ein paar hundert Tokens).",
            [("claude", "Mit KI zusammenfassen"), ("off", "Anfang vorlesen")]),
    Setting("WALKIE_PANEL", "bool", False, "general", "Terminal als Panel über der Figur",
            "Nur Linux mit kitty: ein randloses Terminal direkt über der Figur statt eines "
            "normalen Terminalfensters.", restart=True, advanced=True),
    Setting("WALKIE_TALK", "choice", "auto", "ask", "Reden ohne offene Frage",
            "Wohin dein Satz geht, wenn gerade keine Frage offen ist.",
            [("auto", "Claude-Sessions oder das Terminal des gewählten Agents"),
             ("route", "An die passende Session – oder der Walkie antwortet selbst"),
             ("terminal", "Ins Panel-Terminal über der Figur (braucht kitty und das Panel)")]),
    Setting("WALKIE_RAISE", "bool", False, "ask", "Fenster nach vorne holen, wenn eine Session fragt",
            "Holt das Terminal der fragenden Session in den Vordergrund. „Zeig mir das“ geht immer."),
    Setting("WALKIE_VOICE_REPLY", "bool", True, "ask", "Fragen am Ende einer Antwort per Stimme",
            "Endet eine Session mit einer Frage, liest die Figur sie vor und hört zu. Deine "
            "Antwort geht an genau diese Session."),
    Setting("WALKIE_REPLY_WAIT", "int", 60, "ask", "Auf Antwort warten (Sekunden)",
            "So lange wartet die Session auf deine gesprochene Antwort, bevor sie normal "
            "endet. Tippen am Rechner geht erst danach.", min=15, max=140),
    Setting("WALKIE_VOICE_ANSWER", "bool", True, "ask", "Freigaben & Rückfragen per Stimme",
            "„Ja“, „nein“ oder eine Option sagen. Der Dialog im Terminal geht parallel."),
    Setting("WALKIE_ANSWER_MODE", "choice", "auto", "ask", "Zuhören", "", ANSWER_MODES),
    Setting("WALKIE_ANSWER_WINDOW", "float", 6.0, "ask", "Antwortfenster (Sekunden)",
            "So lange hört die Figur mindestens zu.", min=2, max=30),
    Setting("WALKIE_ANSWER_MAX", "float", 20.0, "ask", "Höchstens (Sekunden)",
            "Solange du sprichst, verlängert sich das Fenster bis hierhin.", min=4, max=60),
    Setting("WALKIE_ASK_WAIT", "int", 120, "ask", "Auf Antwort warten (Sekunden)",
            "Danach entscheidest du nur noch am Rechner.", min=10, max=140),

    # ---- Sprache & Modelle
    Setting("WALKIE_MIC", "str", "", "voice", "Mikrofon",
            "Leer = Systemstandard (bei Kopfhörer: dessen Mikro)."),
    Setting("WALKIE_STT", "choice", "claude", "voice", "Spracherkennung (Gespräch)",
            "Für Freigaben/Rückfragen wird immer Whisper genutzt.",
            [("claude", "Claude-Code-Diktat"), ("whisper", "Whisper (lokal)")], restart=True),
    Setting("WALKIE_WHISPER", "choice", "base", "voice", "Whisper-Modell",
            "Größer = genauer, aber langsamer. Wird beim ersten Start geladen.",
            [("tiny", "tiny – sehr schnell"), ("base", "base – Standard"),
             ("small", "small – genauer"), ("medium", "medium – am genauesten, langsam")],
            restart=True),
    Setting("WALKIE_LANG", "str", "de", "voice", "Sprache der Erkennung", "z. B. de, en."),
    Setting("WALKIE_VOICE", "choice", DEFAULT_VOICE, "voice", "Stimme",
            "Piper-Stimme fürs Vorlesen, wird bei Auswahl geladen (~60 MB).",
            [(n, n) for n in VOICES]),
    Setting("WALKIE_READ_ANSWERS", "bool", True, "voice", "Antworten vorlesen",
            "Jede Antwort deiner Sessions vorlesen – auch auf getippte Nachrichten. Aus: nur "
            "kurze Ansagen, wenn etwas fertig ist."),
    Setting("WALKIE_SILENCE", "float", 7.0, "voice", "Stille bis Absenden (Sekunden)",
            "Beim Gespräch per Doppelklick.", min=2, max=30),
    Setting("WALKIE_SELF_MODEL", "choice", "sonnet", "voice", "Modell, wenn der Walkie selbst antwortet",
            "Für Fragen und Recherche ohne passende Session (mit Websuche).",
            [("haiku", "Haiku – schnell"), ("sonnet", "Sonnet – gründlicher"), ("opus", "Opus")]),
    Setting("WALKIE_BRAIN", "choice", "auto", "voice", "Denkmodell des Begleiters",
            "Entscheidet, wohin Gesagtes geht, versteht Antworten und bereitet Vorlesetexte auf. "
            "Automatisch: das Modell des Hauptagenten; fällt es aus (z. B. Nutzungslimit), ein "
            "anderer installierter Agent.",
            [("auto", "Automatisch"), ("claude", "Claude"), ("codex", "Codex"),
             ("antigravity", "Antigravity"), ("gemini", "Gemini")]),
    Setting("WALKIE_SUMMARY_MODEL", "choice", "haiku", "voice", "Claude-Modell fürs Denken",
            "", [("haiku", "Haiku – schnell, günstig"), ("sonnet", "Sonnet"),
                 ("opus", "Opus")]),
    Setting("WALKIE_CODEX_MODEL", "str", "gpt-6-luna", "voice", "Codex-Modell fürs Denken",
            "Ein schnelles Codex-Modell, z. B. gpt-6-luna."),
]
BY_KEY = {s.key: s for s in SCHEMA}

# --------------------------------------------------------------------------- Datei
_cache = {"mtime": -1, "values": {}, "checked": 0.0}   # -1 = noch nie gelesen


def _parse(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        try:
            parts = shlex.split(v, comments=True)
        except ValueError:
            parts = [v.strip()]
        out[k.strip()] = parts[0] if parts else ""
    return out


def _read():
    try:
        return _parse(CONFIG.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _migrate():
    """Einmalig: alte config.env im Repo und voice.json übernehmen."""
    if CONFIG.exists():
        return
    old = HERE / "config.env"
    values = _parse(old.read_text(encoding="utf-8")) if old.exists() else {}
    values = {k: v for k, v in values.items() if k in BY_KEY}
    try:
        from hook import RUN
        name = json.loads((RUN / "voice.json").read_text(encoding="utf-8"))["voice"]
        values.setdefault("WALKIE_VOICE", name)
    except Exception:  # noqa: BLE001
        pass
    if not os.environ.get("WALKIE_CONFIG") and autostart_entries():
        values["WALKIE_LOGIN_AUTOSTART"] = "1"
    if values:
        _write(values)


def _write(values):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Walkie – Einstellungen. Bearbeiten per GUI, `walkie settings` oder hier.",
             "# Nur Abweichungen vom Standard stehen hier."]
    for s in SCHEMA:
        if s.key in values:
            lines.append(f"{s.key}={shlex.quote(str(values[s.key]))}")
    for k, v in values.items():
        if k not in BY_KEY:
            lines.append(f"{k}={shlex.quote(str(v))}")
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=CONFIG.parent, prefix=".config-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:     # eigene Temp-Datei je Schreiber
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, CONFIG)


def raw_values(force=False):
    """Werte aus der Datei (Strings), bei Änderung neu gelesen (höchstens 1x pro 0,5 s)."""
    now = time.time()
    if force or now - _cache["checked"] > 0.5:
        _cache["checked"] = now
        try:
            m = CONFIG.stat().st_mtime_ns
        except OSError:
            m = None
        if force or m != _cache["mtime"]:
            if m is None:
                _migrate()
            _cache["mtime"], _cache["values"] = m, _read()
    return _cache["values"]


def version():
    raw_values()
    return _cache["mtime"]


# --------------------------------------------------------------------------- Typen
def convert(s, raw):
    if s.type == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "ja", "on", "an")
    if s.type == "int":
        return int(float(raw))
    if s.type == "float":
        return float(raw)
    if s.type == "json":
        v = json.loads(raw) if isinstance(raw, str) else raw
        if s.key == "WALKIE_KEYS" and not (isinstance(v, dict) and all(
                isinstance(g, dict) for g in v.values())):
            raise ValueError("Tastenbelegung: {TASTE: {press|double|long: AKTION}}")
        return v
    if s.type == "choice" and s.choices and str(raw) not in [c[0] for c in s.choices]:
        raise ValueError(f"{raw!r} – erlaubt: {', '.join(c[0] for c in s.choices)}")
    return str(raw)


def serialize(s, value):
    if s.type == "bool":
        return "1" if value else "0"
    if s.type == "json":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def get(key, default=None):
    """Typisierter Wert: Umgebung > Datei > Standard."""
    s = BY_KEY.get(key)
    raw = os.environ.get(key)
    if raw is None:
        raw = raw_values().get(key)
    if s is None:
        return raw if raw is not None else default
    if raw is None or raw == "" and s.type not in ("str", "path"):
        if key in ("WALKIE_LANG", "WALKIE_VOICE"):
            from i18n import lang
            return lang() if key == "WALKIE_LANG" else voice_for_language(lang())
        return s.default
    try:
        return convert(s, raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        return s.default


def voice_for_language(code, preferred=None):
    """Prefer the user's choice, then an installed model for the same language."""
    candidates = [name for name, (model, _) in VOICES.items()
                  if model.split("_", 1)[0] == code]
    if preferred in candidates:
        return preferred
    return next((name for name in candidates
                 if (HERE / "voices" / (VOICES[name][0] + ".onnx")).is_file()), candidates[0])


def has_kitty():
    import shutil
    return sys.platform.startswith("linux") and shutil.which("kitty") is not None


def panel():
    """Terminal als kitty-Panel über der Figur? Nur auf ausdrücklichen Wunsch (WALKIE_PANEL)
    und nur, wo es geht. Standard: ein normales Fenster des System-Terminals."""
    return bool(get("WALKIE_PANEL")) and has_kitty()


def talk_terminal():
    """Geht Gesagtes ins eigene Panel-Terminal statt an die passende Session? Nur mit Panel –
    ohne würde jedes Diktat unzustellbar in den Entwürfen landen."""
    mode = get("WALKIE_TALK")
    return panel() and (mode == "terminal" or (mode == "auto" and get("WALKIE_AGENT") != "claude"))


def stt_in_use():
    """Was beim freien Reden wirklich erkennt -> ("claude" | "whisper", Grund oder "").
    Das Claude-Diktat tippt in ein Terminal: es braucht Claude Code als Agent, das Panel und
    WALKIE_TALK, das ins eigene Panel-Terminal geht. Sonst erkennt still Whisper (walkie.py)."""
    if get("WALKIE_STT") != "claude":
        return "whisper", ""
    if get("WALKIE_AGENT") != "claude":
        return "whisper", "Das Claude-Diktat gibt es nur mit Claude Code als Agent."
    if not panel():
        return "whisper", "Das Claude-Diktat braucht das Terminal-Panel über der Figur."
    if not talk_terminal():
        return "whisper", "Das Claude-Diktat tippt nur ins eigene Panel-Terminal, nicht beim Weiterleiten an Sessions."
    return "claude", ""


def overridden(key):
    return key in os.environ


def set(key, value):  # noqa: A001 – bewusst wie dict-API
    """Wert prüfen, typisieren und speichern. Standardwerte werden aus der Datei entfernt."""
    s = BY_KEY.get(key)
    if s is None:
        raise KeyError(f"Unbekannte Einstellung: {key}")
    v = convert(s, value) if (isinstance(value, str) and s.type != "str") or s.type == "json" \
        else value
    if s.type in ("int", "float") and v is not None:
        if s.min is not None and v < s.min or s.max is not None and v > s.max:
            raise ValueError(f"{key}: erlaubt {s.min:g}–{s.max:g}")
    values = dict(raw_values(force=True))
    if key == "WALKIE_UI_LANG":
        from i18n import system_lang
        code = system_lang() if v == "auto" else v
        previous = get("WALKIE_VOICE")
        previous_code = VOICES[previous][0].split("_", 1)[0]
        values["WALKIE_PREFERRED_VOICE_" + previous_code.upper()] = previous
        preferred = values.get("WALKIE_PREFERRED_VOICE_" + code.upper())
        values["WALKIE_VOICE"] = voice_for_language(code, preferred)
        values["WALKIE_LANG"] = code
    if v == s.default and key not in ("WALKIE_LANG", "WALKIE_VOICE"):
        values.pop(key, None)
    else:
        values[key] = serialize(s, v)
    _write(values)
    raw_values(force=True)
    side_effects(key, v)
    return v


def reset(key):
    return set(key, BY_KEY[key].default)


# --------------------------------------------------------------------------- Nebenwirkungen
import sys as _sys

AUTOSTART_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart"
MAC_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.desktopwalkie.plist"
WIN_STARTUP = Path(os.environ.get("APPDATA") or Path.home()) / "Microsoft" / "Windows" / \
    "Start Menu" / "Programs" / "Startup" / "Walkie.cmd"


def _start_cmd():
    """Startbefehl des Walkies: Python der Walkie-Umgebung + walkie.py."""
    import paths
    return [paths.python(gui=True), str(HERE / "walkie.py")]


def autostart_entries():
    """Autostart-Einträge, die diesen Walkie starten (auch selbst angelegte)."""
    if _sys.platform == "darwin":
        return [MAC_AGENT] if MAC_AGENT.exists() else []
    if _sys.platform == "win32":
        return [WIN_STARTUP] if WIN_STARTUP.exists() else []
    marks = (f"Exec={HERE / 'start.sh'}", f"{HERE / 'walkie.py'}")
    return [f for f in AUTOSTART_DIR.glob("*.desktop")
            if any(m in f.read_text(encoding="utf-8", errors="ignore") for m in marks)]


def _write_autostart():
    py, script = _start_cmd()
    if _sys.platform == "darwin":
        MAC_AGENT.parent.mkdir(parents=True, exist_ok=True)
        MAC_AGENT.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.desktopwalkie</string>
  <key>ProgramArguments</key><array><string>{py}</string><string>{script}</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
""", encoding="utf-8")
    elif _sys.platform == "win32":
        WIN_STARTUP.parent.mkdir(parents=True, exist_ok=True)
        WIN_STARTUP.write_text(f'@start "" "{py}" "{script}"\r\n', encoding="utf-8")
    else:
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        (AUTOSTART_DIR / "walkie.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Walkie\n"
            f"Exec={py} {script}\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")


def side_effects(key, value):
    if key == "WALKIE_LOGIN_AUTOSTART" and not os.environ.get("WALKIE_CONFIG"):
        if value and not autostart_entries():
            _write_autostart()
        elif not value:
            for f in autostart_entries():
                f.unlink(missing_ok=True)


def sprite_dir():
    p = get("WALKIE_SPRITE")
    if not p:
        return DEFAULT_FIGURE
    path = Path(p).expanduser()
    # Die Standardfigur hieß früher figures/russpelz; alte Configs landen jetzt auf figures/walkie.
    if path.name == "russpelz" and not path.exists():
        return DEFAULT_FIGURE
    return path
