"""Ein Fehler in einem Slot protokolliert statt den Walkie zu beenden."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


class CrashGuard(unittest.TestCase):
    def test_exception_in_slot_does_not_abort(self):
        code = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(HERE)!r})
            import crashguard
            logged = []
            crashguard.install(logged.append)
            from PyQt6.QtCore import QTimer
            from PyQt6.QtWidgets import QApplication, QPushButton
            app = QApplication([])
            b = QPushButton()
            b.clicked.connect(lambda: 1 / 0)
            b.click()
            QTimer.singleShot(50, app.quit)
            app.exec()
            assert any("ZeroDivisionError" in m for m in logged), logged
            print("survived")
        """)
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=d)
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("survived", r.stdout)

    def test_alive(self):
        sys.path.insert(0, str(HERE))
        import crashguard
        self.assertFalse(crashguard.alive(None))


if __name__ == "__main__":
    unittest.main()
