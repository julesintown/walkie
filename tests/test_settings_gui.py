"""Einstellungsfenster: geführte Ersteinrichtung und sichtbare Werte.

Läuft in einem eigenen Prozess: settings_gui lädt hook.py, das seine Ordner beim Import
festlegt – im gemeinsamen Testprozess würde das die Ordner späterer Testdateien verbiegen."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import textwrap  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent.parent

PRELUDE = f"""
import sys
sys.path.insert(0, {str(HERE)!r})
from PyQt6.QtWidgets import QApplication, QPushButton, QSpinBox
APP = QApplication([])
import settings as S
import settings_gui as G
def pump():
    for _ in range(5):
        APP.processEvents()
"""


def run(body):
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", WALKIE_RUN=f"{d}/run",
                   WALKIE_CONFIG=f"{d}/config.env", XDG_RUNTIME_DIR=d, XDG_CACHE_HOME=f"{d}/cache")
        env.pop("WALKIE_UI_LANG", None)
        r = subprocess.run([sys.executable, "-c", PRELUDE + textwrap.dedent(body)],
                           capture_output=True, text=True, env=env, timeout=120,
                           encoding="utf-8", errors="replace")
    return r


class SettingsGuiTest(unittest.TestCase):
    def check(self, body):
        r = run(body)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout, r.stderr)

    def test_first_open_is_the_guided_setup_and_ends_in_settings(self):
        self.check("""
            w = G.SettingsWindow(); w.show(); pump()
            assert w.setup_mode, "erstes Öffnen: Assistent"
            for i in range(len(w.STEPS)):
                w.goto_step(i); pump()
                assert w.step == i
            w.goto_step(0); pump()
            de = next(b for b in w.content.findChildren(QPushButton) if b.text().startswith("Deutsch"))
            de.click(); pump()
            assert S.get("WALKIE_UI_LANG") == "de"
            assert S.get("WALKIE_VOICE").startswith("Deutsch"), "Stimme folgt der Sprache"
            w.finish_welcome(); pump()
            assert G.WELCOMED.exists() and not w.setup_mode
            w.refresh_language()                 # Timer nach dem Abschluss: kein Absturz
            assert w.current_page() == "general" and w.nav is not None
            print("OK")
        """)

    def test_number_fields_show_their_value(self):
        """Mit Stylesheet und ohne Pfeiltasten schrumpfte das Textfeld auf 1 px (leere Felder)."""
        self.check("""
            G.WELCOMED.parent.mkdir(parents=True, exist_ok=True); G.WELCOMED.write_text("1")
            w = G.SettingsWindow(); w.show(); pump()
            spins = w.findChildren(QSpinBox)
            assert spins
            for s in spins:
                s.resize(max(s.width(), 80), s.height()); s.show(); pump()
                assert s.lineEdit().width() > 20, (s.text(), s.lineEdit().width())
            print("OK")
        """)


if __name__ == "__main__":
    unittest.main()
