#!/usr/bin/env python3
"""Baut die mitgelieferten Figuren (figures/) aus frei lizenzierten (CC0) Pixel-Sprites.

Die Quellen sind Seitenansichten. Für das 8-Richtungen-Format des Begleiters
(PMD-SpriteCollab-Layout: AnimData.xml + <Anim>-Anim.png, Zeilen
unten, unten-rechts, rechts, oben-rechts, oben, oben-links, links, unten-links)
werden sie gespiegelt: rechte Hälfte = Blick nach rechts, linke = nach links.

    .venv/bin/python tools/make_figures.py      # lädt Quellen, schreibt figures/*

Lizenzen und Autoren: figures/CREDITS.md
"""
import io
import sys
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QTransform

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "figures"
CACHE = Path.home() / ".cache" / "walkie" / "figure-sources"

SOURCES = {
    "sunny-land": "https://opengameart.org/sites/default/files/sunny-land-files.zip",
    "slime": "https://opengameart.org/sites/default/files/Slime_0.zip",
}
SUNNY = "Sunny-land-assets-files/PNG/spritesheets/"

# Figur -> Blickrichtung der Quelle, Zellgröße, Animationen.
# Animation: (Quelle, Bildgröße (w, h), Bildindizes, Dauer je Bild in 1/60 s)
# Quelle "zip:pfad" = Streifen; ("zip:pfad", Reihe) = Reihe eines Rasters.
FIGURES = {
    "fox": {
        "title": "Fuchs", "faces": "right", "cell": (34, 32),
        "anims": {
            "Idle": (f"sunny-land:{SUNNY}player-idle.png", (33, 32), [0, 1, 2, 3], 12),
            "Walk": (f"sunny-land:{SUNNY}payer-run.png", (33, 32), [0, 1, 2, 3, 4, 5], 6),
            "Hop": (f"sunny-land:{SUNNY}player-jump.png", (33, 32), [0, 1], 12),
            "Sleep": (f"sunny-land:{SUNNY}player-crouch.png", (33, 32), [0, 1], 45),
            "Hurt": (f"sunny-land:{SUNNY}player-hurt.png", (33, 32), [0, 1], 8),
        },
        "copies": {"Cringe": "Hurt", "Charge": "Hop", "Wake": "Hop", "Nod": "Hop"},
    },
    "frog": {
        "title": "Frosch", "faces": "left", "cell": (36, 32),
        "anims": {
            "Idle": (f"sunny-land:{SUNNY}frog-idle.png", (35, 32), [0, 0, 0, 1, 2, 3], 12),
            "Walk": (f"sunny-land:{SUNNY}frog-jump.png", (35, 32), [0, 1, 2], 8),
            "Hop": (f"sunny-land:{SUNNY}frog-jump.png", (35, 32), [1, 2, 0], 10),
            "Sleep": (f"sunny-land:{SUNNY}frog-idle.png", (35, 32), [0], 60),
        },
        "copies": {"Charge": "Hop", "Wake": "Hop", "Nod": "Hop"},
    },
    "slime": {
        "title": "Schleim", "faces": "left", "cell": (32, 26),
        "anims": {
            "Idle": (("slime:slime-Sheet.png", 0), (32, 25), [0, 1, 2, 3], 12),
            "Walk": (("slime:slime-Sheet.png", 1), (32, 25), [0, 1, 2, 3], 8),
            "Hop": (("slime:slime-Sheet.png", 2), (32, 25), [0, 1, 2, 3], 8),
            "Hurt": (("slime:slime-Sheet.png", 3), (32, 25), [0, 1, 2, 3], 8),
            "Sleep": (("slime:slime-Sheet.png", 0), (32, 25), [0], 60),
        },
        "copies": {"Cringe": "Hurt", "Charge": "Hop", "Wake": "Hop"},
    },
}
RIGHT_ROWS = {1, 2, 3}            # unten-rechts, rechts, oben-rechts
LEFT_ROWS = {5, 6, 7}             # oben-links, links, unten-links


def zip_of(name):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.zip"
    if not path.exists():
        print(f"  lade {SOURCES[name]} …")
        req = urllib.request.Request(SOURCES[name], headers={"User-Agent": "walkie"})
        with urllib.request.urlopen(req, timeout=300) as r:
            path.write_bytes(r.read())
    return zipfile.ZipFile(path)


def load(src):
    ref, row = (src, 0) if isinstance(src, str) else src
    name, inner = ref.split(":", 1)
    z = zip_of(name)
    member = next(m for m in z.namelist() if m.endswith(inner))
    img = QImage()
    img.loadFromData(z.read(member))
    return img, row


def frames(src, size, idx):
    img, row = load(src)
    w, h = size
    return [img.copy(i * w, row * h, w, h) for i in idx]


def build(key, spec):
    dest = OUT / key
    dest.mkdir(parents=True, exist_ok=True)
    cw, ch = spec["cell"]
    root = ET.Element("AnimData")
    ET.SubElement(root, "ShadowSize").text = "1"
    anims = ET.SubElement(root, "Anims")
    mirror = QTransform().scale(-1, 1)
    for i, (name, (src, size, idx, dur)) in enumerate(spec["anims"].items()):
        fr = frames(src, size, idx)
        sheet = QImage(cw * len(fr), ch * 8, QImage.Format.Format_ARGB32)
        sheet.fill(QColor(0, 0, 0, 0))
        p = QPainter(sheet)
        for r in range(8):
            flip = (r in LEFT_ROWS) if spec["faces"] == "right" else (r in RIGHT_ROWS)
            for j, f in enumerate(fr):
                g = f.transformed(mirror) if flip else f
                # unten bündig, waagrecht zentriert in der (geraden) Zelle
                off = (cw - g.width()) // 2
                if flip:                      # gespiegelt auch in der Zelle: exakt symmetrisch
                    off = cw - g.width() - off
                p.drawImage(j * cw + off, r * ch + (ch - g.height()), g)
        p.end()
        sheet.save(str(dest / f"{name}-Anim.png"))
        a = ET.SubElement(anims, "Anim")
        ET.SubElement(a, "Name").text = name
        ET.SubElement(a, "Index").text = str(i)
        ET.SubElement(a, "FrameWidth").text = str(cw)
        ET.SubElement(a, "FrameHeight").text = str(ch)
        durs = ET.SubElement(a, "Durations")
        for _ in fr:
            ET.SubElement(durs, "Duration").text = str(dur)
    for name, src in spec.get("copies", {}).items():
        a = ET.SubElement(anims, "Anim")
        ET.SubElement(a, "Name").text = name
        ET.SubElement(a, "CopyOf").text = src
    import json
    (dest / "figure.json").write_text(json.dumps(
        {"title": spec["title"], "license": "CC0-1.0", "credits": "figures/CREDITS.md"},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ET.indent(root)
    (dest / "AnimData.xml").write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    print(f"✓ {dest.relative_to(ROOT)} ({len(spec['anims'])} Animationen)")


def main():
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)
    app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])  # noqa: F841
    for key, spec in FIGURES.items():
        build(key, spec)


if __name__ == "__main__":
    main()
