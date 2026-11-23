"""Vorlesbar machen: Pfade, Kürzel, Einleitungen (Ideen aus Moonstone und term-pet)."""
import isolate  # noqa: F401 – zuerst: nie in die echten Walkie-Ordner
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class SpeakableTest(unittest.TestCase):
    # Import erst beim Testlauf: discover lädt vorher alle Testdateien, und test_walkie_gui
    # lenkt dabei Einstellungen und Laufzeitordner in ein Testverzeichnis um. Ein Import hier
    # oben würde walkie mit den echten Ordnern des Nutzers laden (und dort schreiben).
    @classmethod
    def setUpClass(cls):
        global walkie
        import walkie
    def test_paths_become_file_names(self):
        f = walkie.speakable
        self.assertEqual(f("Fix in /home/x/shop/src/app.py:42 und ~/proj/README.md."),
                         "Fix in app.py und README.md.")
        self.assertEqual(f("Die Datei liegt unter src/tools/x.py"), "Die Datei liegt unter x.py")
        self.assertEqual(f("und/oder bleibt"), "und/oder bleibt")

    def test_hashes_go_numbers_stay(self):
        self.assertEqual(walkie.speakable("Commit 9dbfd30c ist drin, Port 8080 ok."),
                         "Commit ist drin, Port 8080 ok.")

    def test_clean_spoken_drops_preamble_and_quotes(self):
        self.assertEqual(walkie.clean_spoken('**Zusammenfassung:** „Tests sind grün, committen?“\n'),
                         "Tests sind grün, committen?")
        self.assertEqual(walkie.clean_spoken("Fertig.\n\nZweite Zeile.\nDritte.\nVierte."),
                         "Fertig. Zweite Zeile. Dritte.")


if __name__ == "__main__":
    unittest.main()
