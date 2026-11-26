#!/usr/bin/env python3
"""App-Icons des Walkies aus einer quadratischen Vorlage bauen (braucht Pillow und numpy).

  python tools/make_icons.py VORLAGE.png

Die Vorlage ist das Russpelz-Icon auf weißem Grund. Das Weiß außerhalb der abgerundeten Fläche
wird durchsichtig (weiche Kante), dann entstehen:
  icons/walkie.png    1024 px, Linux-Startmenü und Vorlage für alles andere
  icons/walkie.ico    16–256 px, Windows (Walkie.exe, Startmenü-Verknüpfung)
  icons/walkie.icns   16–1024 px, macOS (Walkie.app)
"""
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "icons"


def cut_background(img):
    """Weißen Rand, der von den Ecken aus erreichbar ist, durchsichtig machen. Weiß im Inneren
    (Ohren, Augenglanz) bleibt, weil es nicht mit dem Rand verbunden ist."""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w, _ = rgb.shape
    low = rgb.min(axis=2)
    bg = low > 200                                   # Hintergrund und helle Hälfte der Kante
    outside = np.zeros((h, w), bool)
    todo = deque((y, x) for y, x in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)) if bg[y, x])
    for y, x in todo:
        outside[y, x] = True
    while todo:
        y, x = todo.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and bg[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                todo.append((ny, nx))
    # Kante: zwei Pixel um den Hintergrund herum bekommen Deckkraft nach ihrer Helligkeit
    edge = outside.copy()
    for _ in range(3):
        grown = edge.copy()
        grown[1:] |= edge[:-1]
        grown[:-1] |= edge[1:]
        grown[:, 1:] |= edge[:, :-1]
        grown[:, :-1] |= edge[:, 1:]
        edge = grown
    white = 253.0                                    # Helligkeit des Hintergrunds
    alpha = np.full((h, w), 255.0)
    soft = edge
    alpha[soft] = np.clip((white - low[soft]) / max(white - 86.0, 1) * 255, 0, 255)
    alpha[outside & (low > 245)] = 0
    # halb durchsichtige Kantenpixel in der Farbe der Fläche, sonst bleibt ein heller Saum
    border = soft & (alpha > 0) & (alpha < 255)
    ys, xs = np.nonzero(border)
    out = rgb.copy()
    for y, x in zip(ys, xs):
        y0, y1, x0, x1 = max(y - 4, 0), min(y + 5, h), max(x - 4, 0), min(x + 5, w)
        solid = ~edge[y0:y1, x0:x1]
        if solid.any():
            out[y, x] = rgb[y0:y1, x0:x1][solid].mean(axis=0)
    rgba = np.dstack([out, alpha]).round().astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def main(src):
    img = Image.open(src)
    if img.size[0] != img.size[1]:
        sys.exit("Die Vorlage muss quadratisch sein.")
    icon = cut_background(img).resize((1024, 1024), Image.LANCZOS)
    OUT.mkdir(exist_ok=True)
    icon.save(OUT / "walkie.png", optimize=True)
    icon.save(OUT / "walkie.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    icon.save(OUT / "walkie.icns")
    for name in ("walkie.png", "walkie.ico", "walkie.icns"):
        print(f"{OUT / name}  {(OUT / name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip())
    main(sys.argv[1])
