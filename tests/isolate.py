"""Als erster Import jeder Testdatei: Tests schreiben nie in die echten Walkie-Ordner.

hook.py und settings.py legen Statusordner und Konfiguration beim Import fest. Ohne diese
Isolation konnte eine Testdatei, die sie früher importiert als eine andere ihre Umgebung
setzt, in ~/.local/state/walkie schreiben – und dabei die server.json eines laufenden
Walkies löschen.
"""
import os
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="walkie-tests-"))
for key, sub in (("WALKIE_RUN", "run"), ("WALKIE_CONFIG", "config.env"),
                 ("XDG_RUNTIME_DIR", "xdg"), ("WALKIE_SESSION_DIR", "sessions")):
    os.environ.setdefault(key, str(ROOT / sub))
(ROOT / "xdg").mkdir(exist_ok=True)
# Tests verändern nie die echte Lautstärke anderer Programme (ducking.py)
os.environ.setdefault("WALKIE_DUCK", "100")
