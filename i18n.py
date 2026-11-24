"""Sprache der Oberfläche (nur Standardbibliothek).

Quelltexte sind Deutsch; Übersetzungen liegen als JSON in locales/<sprache>/*.json
(ein Wörterbuch {deutscher Text: Übersetzung} pro Quelldatei, beim Laden zusammengeführt).

    from i18n import t
    t("Einstellungen …")                       # -> "Settings …" bei Englisch
    t("{n} Session(s), {busy} aktiv", n=3, busy=1)

Platzhalter immer benannt über format() – nie f-Strings in t(), sonst gibt es keinen
festen Schlüssel. Fehlt eine Übersetzung, bleibt der deutsche Text stehen.
Sprache: WALKIE_UI_LANG (auto | de | en); auto = Systemsprache (LC_ALL/LC_MESSAGES/LANG,
unter Windows/macOS über locale), alles außer Deutsch -> Englisch.
"""
import json
import locale
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCALES = HERE / "locales"
LANGS = ("de", "en")

_tables = {}


_windows_lang = []


def wsl_windows_lang():
    """Unter WSL ist die Linux-Sprache oft nur C.UTF-8 – dann zählt die von Windows.
    Einmal abgefragt (mit Zeitlimit) und gemerkt; außerhalb von WSL: None."""
    if _windows_lang:
        return _windows_lang[0]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "walkie" / "windows-lang"
    try:
        cached = cache.read_text(encoding="ascii").strip()
        if cached in LANGS:
            _windows_lang.append(cached)
            return cached
    except OSError:
        pass
    code = None
    try:
        if "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower():
            import shutil
            import subprocess
            ps = shutil.which("powershell.exe") or next(
                (str(c) for c in Path("/mnt").glob("*/Windows/System32/WindowsPowerShell/v1.0/"
                                                  "powershell.exe")), None)
            if ps is None:
                raise OSError("powershell.exe fehlt")
            r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command",
                                "(Get-UICulture).Name"], capture_output=True, text=True,
                               timeout=5)
            name = (r.stdout or "").strip().lower()
            if name:
                code = "de" if name.startswith("de") else "en"
    except (OSError, ValueError, Exception):  # noqa: BLE001 – nur ein Vorschlag
        code = None
    _windows_lang.append(code)
    if code:
        try:                                   # Hooks laden i18n bei jedem Ereignis
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(code, encoding="ascii")
        except OSError:
            pass
    return code


def system_lang():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(var)
        if v and v not in ("C", "POSIX", "C.UTF-8"):
            return "de" if v.lower().startswith("de") else "en"
    if os.name == "posix":
        win = wsl_windows_lang()
        if win:
            return win
    try:
        loc = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        loc = ""
    return "de" if loc.lower().startswith(("de", "german")) else "en"


def lang():
    try:
        import settings as S
        v = S.get("WALKIE_UI_LANG") or "auto"
    except Exception:  # noqa: BLE001 – ohne Einstellungen: Systemsprache
        v = "auto"
    return v if v in LANGS else system_lang()


def table(code):
    if code not in _tables:
        merged = {}
        for f in sorted((LOCALES / code).glob("*.json")):
            try:
                merged.update(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        _tables[code] = merged
    return _tables[code]


def t(text, **kw):
    """Text in der Oberflächensprache; benannte Platzhalter per format()."""
    code = lang()
    if code != "de" and text:
        text = table(code).get(text, text)
    return text.format(**kw) if kw else text


def spoken_prompt(text):
    """Pass the current menu language along even in an already-open agent session."""
    return f"[Walkie · reply language: {lang()}] {text}"


def render(value):
    return value.render() if isinstance(value, Speech) else value


class Speech(str):
    """A queued announcement retains its template and arguments until playback."""
    def __new__(cls, template, **values):
        def resolve():
            return t(template, **{k: render(v) for k, v in values.items()})
        obj = super().__new__(cls, resolve())
        obj.render = resolve
        return obj

    def __add__(self, other):
        return Speech("{left}{right}", left=self, right=other)

    def __radd__(self, other):
        return Speech("{left}{right}", left=other, right=self)
