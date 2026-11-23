"""Riskante Befehle erkennen (Idee aus GodTerm und Voice Channel): Wer per Stimme oder Taste
freigibt, hat den Befehl nicht gesehen.

Zwei Stufen:
  risky(tool, detail)    -> Grund oder None. Riskant: der Begleiter liest den Befehl vor und
                            will ein zweites, klares Ja. Per Taste allein gibt es keine Freigabe.
  critical(tool, detail) -> Grund oder None. Kritisch (rm -rf, Force-Push, Produktion,
                            Datenbank, Infrastruktur): zusätzlich ein gesprochener Zahlencode
                            („Bestätige 42“) – ein versehentliches „ja“ reicht nicht.
  new_code() / code_heard(text, code) -> Zahlencode erzeugen und in Gesprochenem finden.
"""
import random
import re

CRITICAL = [
    (r"\brm\s+(-[a-zA-Z]*([rR][a-zA-Z]*f|f[a-zA-Z]*[rR])[a-zA-Z]*\b|(-[a-zA-Z]*[rR]\S*\s+)?"
     r"--recursive\s+--force|--force\s+--recursive)", "löscht Dateien rekursiv und ohne Rückfrage"),
    (r"\bgit\s+push\b.*(\s--force(?![\w-])|\s-f\b|\s\+\S)", "überschreibt den Verlauf auf dem Server"),
    (r"\b(mkfs|fdisk|parted)\b|\bdd\s+.*\bof=/dev/", "schreibt direkt auf ein Laufwerk"),
    (r"\b(drop\s+(table|database|schema)|truncate\s+(table\s+)?\w)", "löscht Daten in der Datenbank"),
    (r"\bdelete\s+from\s+[\w.\"`]+\s*(;|$|['\"])", "löscht alle Zeilen einer Tabelle"),
    (r"\balter\s+table\b.*\bdrop\b", "entfernt Spalten oder Tabellenteile"),
    (r"\b(prisma\s+migrate\s+reset|rails\s+db:(drop|reset)|rake\s+db:(drop|reset)|"
     r"manage\.py\s+flush|alembic\s+downgrade|dropdb)\b", "setzt die Datenbank zurück"),
    (r"\b(kubectl\s+delete|terraform\s+(destroy|apply\b.*-auto-approve)|pulumi\s+destroy|"
     r"helm\s+(uninstall|delete))\b", "löscht oder ändert Infrastruktur"),
    (r"(\b(deploy|release|promote|rollout)\b.*\b(prod|production|live)\b|"
     r"\b(prod|production)\b.*\b(deploy|release|migrate|apply)\b|"
     r"\bvercel\b.*--prod\b|\bnetlify\s+deploy\b.*--prod\b|\bfirebase\s+deploy\b|"
     r"\bfly(ctl)?\s+deploy\b|\bheroku\s+(releases:rollback|pg:reset)\b|"
     r"\bgcloud\s+.*\bdeploy\b|\beb\s+deploy\b|\bserverless\s+deploy\b.*\bprod)",
     "geht in die Produktion"),
    (r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|\bgem\s+push\b",
     "veröffentlicht ein Paket"),
]

RULES = CRITICAL + [
    (r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\b|--recursive|--force)", "löscht Dateien"),
    (r"\bgit\s+push\b.*--force-with-lease", "überschreibt den Verlauf auf dem Server"),
    (r"\bgit\s+reset\s+--hard\b", "verwirft Änderungen"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "löscht nicht versionierte Dateien"),
    (r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", "verwirft Änderungen"),
    (r"\bgit\s+branch\s+-D\b", "löscht einen Branch"),
    (r"\bsudo\b", "läuft mit Adminrechten"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|python3?)\b", "führt ein Skript aus dem Netz aus"),
    (r"\b(update\s+[\w.\"`]+\s+set|delete\s+from)\b", "ändert Daten in der Datenbank"),
    (r"\b(migrate|migration)\b.*\b(deploy|up|apply|run)\b|\bdb:migrate\b",
     "ändert das Datenbankschema"),
    (r"\bdocker\s+system\s+prune\b|\bdocker\s+volume\s+(rm|prune)\b", "löscht Docker-Daten"),
    (r"\bchmod\s+-R\b|\bchown\s+-R\b", "ändert Rechte rekursiv"),
    (r">\s*/dev/sd|>\s*/etc/", "überschreibt Systemdateien"),
]
_RULES = [(re.compile(p, re.I), why) for p, why in RULES]
_CRITICAL = [(re.compile(p, re.I), why) for p, why in CRITICAL]


def _check(rules, tool, detail):
    if (tool or "") != "Bash" or not detail:
        return None
    for rx, why in rules:
        if rx.search(detail):
            return why
    return None


def risky(tool, detail):
    return _check(_RULES, tool, detail)


def critical(tool, detail):
    return _check(_CRITICAL, tool, detail)


def new_code(rng=random):
    """Zweistellig, ohne leicht verwechselbare Zahlen (13/30, 14/40 … klingen ähnlich)."""
    choices = [n for n in range(21, 99) if n % 10 and n % 11]
    return rng.choice(choices)


_UNITS_DE = {"ein": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
             "sechs": 6, "sieben": 7, "acht": 8, "neun": 9}
_TENS_DE = {"zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50,
            "fuenfzig": 50, "sechzig": 60, "siebzig": 70, "achtzig": 80, "neunzig": 90}
_UNITS_EN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9}
_TENS_EN = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
            "seventy": 70, "eighty": 80, "ninety": 90}


def numbers(text):
    """Alle Zahlen 1–99 in gesprochenem Text: Ziffern, „zweiundvierzig“, „forty two“,
    „vier zwei“ (Ziffer für Ziffer)."""
    t = (text or "").lower()
    out = [int(n) for n in re.findall(r"\d+", t)]
    for m in re.finditer(r"(%s)und(%s)" % ("|".join(_UNITS_DE), "|".join(_TENS_DE)), t):
        out.append(_TENS_DE[m.group(2)] + _UNITS_DE[m.group(1)])
    words = re.findall(r"[a-zäöüß]+", t)
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if w in _TENS_EN:
            out.append(_TENS_EN[w] + _UNITS_EN.get(nxt, 0))
        elif w in _TENS_DE:
            out.append(_TENS_DE[w])
        single = {**_UNITS_DE, **_UNITS_EN}
        if w in single and nxt in single:          # Ziffer für Ziffer: „vier zwei“
            out.append(single[w] * 10 + single[nxt])
    return out


def code_heard(text, code):
    return int(code) in numbers(text)
