"""Shimeji-Import mit Platzhalter-Bildern (keine echten Grafiken im Repo)."""
import isolate  # noqa: F401 – zuerst: nie in die echten Walkie-Ordner
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import QBuffer, QIODevice  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])   # wie die GUI-Tests: nur eine App je Prozess

import shimeji  # noqa: E402
import sprite  # noqa: E402


def png(w=128, h=128, left=40):
    """Platzhalter: Figur als Block links (Blick nach links), Füße auf y=127."""
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    for y in range(30, h):
        for x in range(left, left + 30):
            img.setPixelColor(x, y, QColor("brown"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class ShimejiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.zip = self.tmp / "pack.zip"
        with zipfile.ZipFile(self.zip, "w") as z:
            for i in range(1, 47):
                z.writestr(f"img/shime{i}.png", png(216 if i in (18, 19, 37, 38) else 128))
            z.writestr("../böse.png", png())            # wird ignoriert, nie entpackt
            z.writestr("Shimeji.exe", b"MZ")

    def test_build_and_load(self):
        frames = shimeji.read_frames(self.zip)
        self.assertEqual(sorted(frames), list(range(1, 47)))
        made, missing = shimeji.build(frames, self.tmp / "out", "Test")
        self.assertEqual(missing, [])
        self.assertIn("Walk", made)
        self.assertFalse((self.tmp / "böse.png").exists())
        s = sprite.SpriteSet(self.tmp / "out", scale=5)
        self.assertAlmostEqual(s.scale, 5 * shimeji.SCALE_FACTOR)
        for name in ("Idle", "Walk", "Sleep", "Hop", "Hurt", "Cringe", "Nod", "Charge"):
            self.assertTrue(s.has(name), name)
        # links unverändert, rechts gespiegelt: Figur liegt jeweils auf der anderen Seite
        def xs(row):
            im = s.anims["Idle"].frame(row, 0).toImage()
            return [x for x in range(im.width()) if im.pixelColor(x, im.height() // 2 - 2).alpha()]   # Füße: Zellmitte
        left, right = xs(sprite.LEFT), xs(sprite.RIGHT)
        w = s.anims["Idle"].frame(0, 0).width()
        self.assertAlmostEqual(sum(left) / len(left), w - 1 - sum(right) / len(right), delta=1)
        self.assertLess(sum(left) / len(left), sum(right) / len(right))

    def test_not_a_shimeji(self):
        with self.assertRaises(ValueError):
            shimeji.build({}, self.tmp / "x", "x")


if __name__ == "__main__":
    unittest.main()
