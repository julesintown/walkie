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

    def test_hung_gui_thread_writes_all_stacks(self):
        """Hängt der GUI-Thread (kein Herzschlag mehr), landen die Stacks in crash.log –
        in einem eigenen Prozess, weil faulthandler prozessweit ist."""
        code = textwrap.dedent(f"""
            import sys, time
            from pathlib import Path
            sys.path.insert(0, {str(HERE)!r})
            import crashguard
            crashguard.HANG_SECONDS = 0.3
            run = Path(sys.argv[1])
            crashguard.install(lambda m: None, run)
            crashguard.hang_heartbeat()
            def stuck_in_device_call():
                time.sleep(1.0)               # GUI-Thread blockiert, kein Herzschlag
            stuck_in_device_call()
            print("weiter")
        """)
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-c", code, d], capture_output=True, text=True,
                               timeout=60)
            log = (Path(d) / "crash.log").read_text(encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("weiter", r.stdout)             # Prozess läuft weiter
        self.assertIn("Timeout", log)
        self.assertIn("stuck_in_device_call", log)

    def test_watchdog_restarts_only_a_hung_gui_thread(self):
        """Figur eingefroren (GUI-Thread blockiert): Der Wächter startet neu – solange der
        Herzschlag kommt, nie. Vor dem ersten Herzschlag (Start) auch nicht."""
        import threading
        import time
        sys.path.insert(0, str(HERE))
        import crashguard
        crashguard._beat = None
        fired, logs = threading.Event(), []
        crashguard.watchdog(fired.set, logs.append, limit=0.3, poll=0.05)
        time.sleep(0.5)
        self.assertFalse(fired.is_set())                # noch kein Herzschlag
        for _ in range(10):                             # GUI lebt
            crashguard.hang_heartbeat()
            time.sleep(0.05)
        self.assertFalse(fired.is_set())
        self.assertTrue(fired.wait(2))                  # Herzschlag bleibt aus
        self.assertIn("hänger", logs[0])
        crashguard._beat = None

    def test_alive(self):
        sys.path.insert(0, str(HERE))
        import crashguard
        self.assertFalse(crashguard.alive(None))


if __name__ == "__main__":
    unittest.main()
