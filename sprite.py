"""Figuren im PMD-Sprite-Format (AnimData.xml + <Animation>-Anim.png, 8 Richtungen)."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QImage, QPixmap

# Zeilen-Reihenfolge der Sheets
DOWN, DOWN_RIGHT, RIGHT, UP_RIGHT, UP, UP_LEFT, LEFT, DOWN_LEFT = range(8)


class Anim:
    def __init__(self, frames, durations, rows):
        self.frames = frames          # frames[row][i] -> QPixmap (unskaliert)
        self.durations = durations    # in 1/60 s
        self.rows = rows

    def frame(self, row, i):
        return self.frames[row if row < self.rows else 0][i]


class SpriteSet:
    def __init__(self, folder, scale=3):
        folder = Path(folder)
        # Große Vorlagen (z. B. Shimejis, 128 px) bringen einen Faktor mit, damit
        # WALKIE_SCALE für alle Figuren ungefähr gleich groß wirkt; die werden weich skaliert.
        try:
            self.meta = json.loads((folder / "figure.json").read_text(encoding="utf-8"))
            factor = float(self.meta.get("scale_factor", 1))
        except (OSError, ValueError, AttributeError):
            self.meta, factor = {}, 1.0
        scale = scale * factor
        mode = (Qt.TransformationMode.FastTransformation if factor == 1
                else Qt.TransformationMode.SmoothTransformation)
        self.scale = scale
        root = ET.parse(folder / "AnimData.xml").getroot()
        raw, copies = {}, {}
        for a in root.iter("Anim"):
            name = a.findtext("Name")
            if a.findtext("CopyOf"):
                copies[name] = a.findtext("CopyOf")
                continue
            png = folder / f"{name}-Anim.png"
            if not png.exists():
                continue
            w, h = int(a.findtext("FrameWidth")), int(a.findtext("FrameHeight"))
            durs = [int(d.text) for d in a.find("Durations")]
            img = QImage(str(png))
            rows = img.height() // h
            frames = [[QPixmap.fromImage(img.copy(i * w, r * h, w, h)
                                         .scaled(round(w * scale), round(h * scale),
                                                 transformMode=mode))
                       for i in range(len(durs))] for r in range(rows)]
            raw[name] = Anim(frames, durs, rows)
        for name, src in copies.items():
            if src in raw:
                raw[name] = raw[src]
        self.anims = raw
        # Bodenlinie: unterster sichtbarer Pixel von Idle (frontal) relativ zur Zellmitte.
        idle = self.anims["Idle"].frame(DOWN, 0).toImage()
        bottom = max((y for y in range(idle.height()) for x in range(idle.width())
                      if idle.pixelColor(x, y).alpha() > 0), default=idle.height())
        self.foot = bottom - idle.height() / 2   # in skalierten Pixeln
        # Kopf: bei großen Vorlagen oberster sichtbarer Pixel, sonst die alte Schätzung
        self.head = None
        if factor != 1:
            top = min((y for y in range(idle.height()) for x in range(0, idle.width(), 2)
                       if idle.pixelColor(x, y).alpha() > 0), default=0)
            self.head = top - idle.height() / 2

    def has(self, name):
        return name in self.anims

    def bbox(self, name, row=DOWN):
        """Sichtbarer Umriss aller Bilder einer Animation (l, t, r, b) relativ zu dem Punkt,
        an den Animator.draw zeichnet (cx, ground) – zum Anlegen an Wand oder Decke."""
        key = (name, row)
        cache = self.__dict__.setdefault("_bbox", {})
        if key not in cache:
            a = self.anims[name]
            l = t = float("inf")
            r = b = float("-inf")
            for i in range(len(a.durations)):
                im = a.frame(row, i).toImage()
                w, h = im.width(), im.height()
                for y in range(0, h, 2):
                    for x in range(0, w, 2):
                        if im.pixelColor(x, y).alpha() > 40:
                            l, r, t, b = min(l, x), max(r, x), min(t, y), max(b, y)
                ox, oy = -w / 2, -self.foot - h / 2
            cache[key] = ((l + ox, t + oy, r + ox, b + oy) if l != float("inf")
                          else (-8.0, -16.0, 8.0, 0.0))
        return cache[key]


class Animator:
    """Spielt eine Animation ab; Einmal-Animationen fallen danach zurück."""

    def __init__(self, sprites):
        self.s = sprites
        self.name, self.row, self.i, self.t = "Idle", DOWN, 0, 0.0
        self.once = False
        self.done = False

    def play(self, name, row=DOWN, once=False):
        if not self.s.has(name):
            name = "Idle"
        if (name, row, once) == (self.name, self.row, self.once) and not self.done:
            return
        if name != self.name or once or self.done:
            self.i, self.t = 0, 0.0
        self.name, self.row, self.once, self.done = name, row, once, False

    def advance(self, units):
        a = self.s.anims[self.name]
        if self.done:
            return
        self.t += units
        while self.t >= a.durations[self.i]:
            self.t -= a.durations[self.i]
            if self.i + 1 < len(a.durations):
                self.i += 1
            elif self.once:
                self.done = True
                return
            else:
                self.i = 0

    def draw(self, painter, cx, ground):
        pm = self.s.anims[self.name].frame(self.row, self.i)
        x = cx - pm.width() / 2
        y = ground - self.s.foot - pm.height() / 2
        painter.drawPixmap(QPointF(x, y), pm)
        if self.s.head is not None:
            return y + pm.height() / 2 + self.s.head
        return y + (pm.height() / 2 - 16 * self.s.scale)   # grobe Kopfhöhe
