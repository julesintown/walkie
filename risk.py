"""Riskante Befehle erkennen (Idee aus GodTerm): Wer per Stimme oder Taste freigibt, hat den
Befehl nicht gesehen. Bei Unumkehrbarem liest der Begleiter ihn darum vor und will ein
zweites, klares Ja – per Taste allein wird so etwas nicht freigegeben.

risky(tool, detail) -> kurzer, sprechbarer Grund oder None.
"""
import re

RULES = [
    (r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\b|--recursive|--force)", "löscht Dateien"),
    (r"\bgit\s+push\b.*(\s--force\b|\s-f\b|--force-with-lease|\s\+\S)", "überschreibt den Verlauf auf dem Server"),
    (r"\bgit\s+reset\s+--hard\b", "verwirft Änderungen"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "löscht nicht versionierte Dateien"),
    (r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", "verwirft Änderungen"),
    (r"\bgit\s+branch\s+-D\b", "löscht einen Branch"),
    (r"\bsudo\b", "läuft mit Adminrechten"),
    (r"\b(mkfs|fdisk|parted)\b|\bdd\s+.*\bof=", "schreibt direkt auf ein Laufwerk"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|python3?)\b", "führt ein Skript aus dem Netz aus"),
    (r"\b(drop\s+(table|database|schema)|truncate\s+table)\b", "löscht Daten in der Datenbank"),
    (r"\b(kubectl\s+delete|terraform\s+destroy|docker\s+system\s+prune)\b", "löscht Infrastruktur"),
    (r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b", "veröffentlicht ein Paket"),
    (r"\bchmod\s+-R\b|\bchown\s+-R\b", "ändert Rechte rekursiv"),
    (r">\s*/dev/sd|>\s*/etc/", "überschreibt Systemdateien"),
]
_RULES = [(re.compile(p, re.I), why) for p, why in RULES]


def risky(tool, detail):
    if (tool or "") != "Bash" or not detail:
        return None
    for rx, why in _RULES:
        if rx.search(detail):
            return why
    return None
