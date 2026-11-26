import isolate  # noqa: F401  (immer zuerst: Tests schreiben nie in die echten Walkie-Ordner)

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from PyQt6.QtGui import QImage
except ImportError:                     # pragma: no cover – ohne Qt nichts zu prüfen
    QImage = None

FIGURES = Path(__file__).resolve().parent.parent / "figures"


@unittest.skipIf(QImage is None, "PyQt6 fehlt")
class FrameEdgeTest(unittest.TestCase):
    """Kein Bild der großen, weich gezeichneten Figuren darf seinen Zellenrand berühren. Sonst
    ist dort etwas abgeschnitten, und das Stück ragt ins Nachbarbild – z. B. eine Schwanzspitze,
    die beim Fallen lose unter der Figur hängt. (Die kleinen Pixel-Figuren füllen ihre Zelle
    absichtlich genau aus.)"""
    SMOOTH = ("walkie",)

    def test_no_frame_touches_its_cell_edge(self):
        bad = []
        for xml in (FIGURES / f / "AnimData.xml" for f in self.SMOOTH):
            for a in ET.parse(xml).getroot().iter("Anim"):
                name = a.findtext("Name")
                png = xml.parent / f"{name}-Anim.png"
                if a.findtext("CopyOf") or not png.exists():
                    continue
                w, h = int(a.findtext("FrameWidth")), int(a.findtext("FrameHeight"))
                img = QImage(str(png))
                for r in range(img.height() // h):
                    for i in range(len(a.find("Durations"))):
                        x0, y0 = i * w, r * h
                        edge = [(x0 + x, y0) for x in range(w)] + \
                               [(x0 + x, y0 + h - 1) for x in range(w)] + \
                               [(x0, y0 + y) for y in range(h)] + \
                               [(x0 + w - 1, y0 + y) for y in range(h)]
                        if any(img.pixelColor(x, y).alpha() > 40 for x, y in edge):
                            bad.append(f"{xml.parent.name}/{name} Reihe {r} Bild {i}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
