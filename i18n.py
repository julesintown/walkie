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


def system_lang():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(var)
        if v and v not in ("C", "POSIX", "C.UTF-8"):
            return "de" if v.lower().startswith("de") else "en"
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
