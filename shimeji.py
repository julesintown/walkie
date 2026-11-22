"""Shimeji-Pakete (shime1.png … shime46.png) ins Figurenformat des Begleiters umbauen.

Shimejis sind Einzelbilder in Seitenansicht (Blick nach links, 128×128, manche breiter),
deren Bedeutung über die Standardbelegung von Shimeji-ee festliegt: 1 Stehen,
1-2-1-3 Laufen, 11 Sitzen, 18/19 Aufprall, 37/38 Erschrecken („!“) usw.
Daraus wird ein Ordner im PMD-Format (AnimData.xml + <Anim>-Anim.png, 8 Richtungen;
rechte Hälfte gespiegelt) – sprite.py lädt ihn wie jede andere Figur.

    walkie sprite import ~/Downloads/mein-shimeji.zip mein-shimeji

Gelesen werden nur Bilder namens shimeN.png (aus einer ZIP-Datei oder einem Ordner);
nichts wird entpackt oder ausgeführt.
"""
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PyQt6.QtGui import QColor, QImage, QPainter, QTransform

# Bezugspunkt eines Bildes (Füße), wie in Shimeji-ees Standard-actions.xml: (64, 128)
ANCHOR = (64, 128)
# Shimejis sind ~128 px hoch, PMD-Sprites ~40 px: so wirkt WALKIE_SCALE bei beiden ähnlich.
SCALE_FACTOR = 0.2

# Animation -> (Bildnummern, Dauer je Bild in 1/60 s – eine Zahl für alle oder eine Liste).
TRIP = [31, 32, 31, 33]                    # trippelt frontal auf der Stelle
ANIMS = {
    "Idle": ([1], 60),
    "Walk": ([1, 2, 1, 3], 8),
    "Sleep": ([27, 29], 70),               # sitzt, Augen zu
    "DeepBreath": ([11, 26], 40),          # zuhören: sitzt aufmerksam
    # arbeiten: eifrig trippeln, zwischendurch kurz umschauen
    "Charge": (TRIP * 3 + [1, 11, 15, 16, 15],
               [7] * 12 + [12, 20, 22, 22, 18]),
    "Nod": ([11, 16, 11, 15], 10),         # sprechen
    "Hop": ([37, 38], 14),                 # „!“ – du bist dran
    "Hurt": ([18, 19], 12),                # Aufprall
    "Drag": ([5, 6, 5, 7, 8, 7], 9),       # am Nackenfell hochgehoben, zappelt
    # Zufallsbeschäftigungen im Leerlauf (Namen wie bei den PMD-Sprites)
    "TailWhip": ([11, 15, 16, 15, 11], [30, 25, 25, 25, 30]),   # sitzt, schaut sich um
    "Eat": ([11, 17, 29, 17, 11], [25, 30, 45, 30, 20]),        # zufrieden blinzeln
    "Rotate": ([1, 20, 21, 20, 21, 20, 1], [10, 16, 16, 16, 16, 24, 10]),  # strecken/kriechen
    # verdoppelt sich kurz: eine zweite Figur taucht auf und verschwindet wieder
    "Double": ([40, 41, 42, 43, 44, 45, 46, 46, 45, 44, 43, 42, 41, 40],
               [8, 8, 8, 8, 8, 8, 60, 8, 8, 8, 8, 8, 8, 8]),
    # Klettern & Co. (climber.py): Wand links = Original, rechts gespiegelt
    "Fall": ([4], 60),
    "Jump": ([22], 60),                    # Sprung (verwischt) auf ein Fenster
    "Climb": ([12, 13, 14, 13], 10),
    "ClimbRest": ([13], 60),
    "Ceiling": ([23, 24, 25, 24], 10),     # kopfüber an der Bildschirmoberkante
    "SitEdge": ([30], 60),                 # sitzt auf einer Fensterkante, Beine baumeln
}
# Abweichender Bezugspunkt: auf der Kante sitzt das Hinterteil, die Beine hängen darunter
ANCHORS = {"SitEdge": (64, 88)}
COPIES = {"Cringe": "Hurt", "Wake": "Hop", "LookUp": "Hop"}
RIGHT_ROWS = {1, 2, 3}                     # Quelle blickt nach links -> diese spiegeln
NAME = re.compile(r"(?:^|/)shime(\d+)\.png$", re.I)


def read_frames(src):
    """{Nummer: QImage} aus ZIP-Datei oder Ordner."""
    src = Path(src).expanduser()
    out = {}
    if src.is_dir():
        for f in src.rglob("shime*.png"):
            m = NAME.search(f.name)
            if m:
                out[int(m.group(1))] = QImage(str(f))
    else:
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                m = NAME.search(info.filename)
                if m and info.file_size < 5_000_000:
                    img = QImage()
                    img.loadFromData(z.read(info))
                    out[int(m.group(1))] = img
    return {k: v for k, v in out.items() if not v.isNull()}


def build(frames, dest, title):
    missing = sorted({i for ids, _ in ANIMS.values() for i in ids} - frames.keys())
    assert all(isinstance(d, int) or len(d) == len(i) for i, d in ANIMS.values())
    if 1 not in frames:
        raise ValueError("kein shime1.png – ist das ein Shimeji-Paket?")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    mirror = QTransform().scale(-1, 1)
    root = ET.Element("AnimData")
    ET.SubElement(root, "ShadowSize").text = "1"
    anims = ET.SubElement(root, "Anims")
    made = []
    for name, (ids, dur) in ANIMS.items():
        durs_ = dur if isinstance(dur, list) else [dur] * len(ids)
        pairs = [(i, d) for i, d in zip(ids, durs_) if i in frames]
        if not pairs:
            continue
        fr = [frames[i] for i, _ in pairs]
        ax, ay = ANCHORS.get(name, ANCHOR)
        # Zelle so groß, dass jedes Bild (auch gespiegelt) mit dem Bezugspunkt genau in der
        # Mitte liegt – sprite.py stellt die Zellmitte (Höhe der Füße von Idle) auf den Boden.
        half = max(max(ax, f.width() - ax) for f in fr)
        halfh = max(max(ay, f.height() - ay) for f in fr)
        cw, ch = 2 * half, 2 * halfh
        sheet = QImage(cw * len(fr), ch * 8, QImage.Format.Format_ARGB32)
        sheet.fill(QColor(0, 0, 0, 0))
        p = QPainter(sheet)
        for r in range(8):
            for j, f in enumerate(fr):
                top = r * ch + halfh - ay
                if r in RIGHT_ROWS:
                    p.drawImage(j * cw + half - (f.width() - ax), top, f.transformed(mirror))
                else:
                    p.drawImage(j * cw + half - ax, top, f)
        p.end()
        sheet.save(str(dest / f"{name}-Anim.png"))
        a = ET.SubElement(anims, "Anim")
        ET.SubElement(a, "Name").text = name
        ET.SubElement(a, "Index").text = str(len(made))
        ET.SubElement(a, "FrameWidth").text = str(cw)
        ET.SubElement(a, "FrameHeight").text = str(ch)
        durs = ET.SubElement(a, "Durations")
        for _, d in pairs:
            ET.SubElement(durs, "Duration").text = str(d)
        made.append(name)
    for name, src in COPIES.items():
        if src in made:
            a = ET.SubElement(anims, "Anim")
            ET.SubElement(a, "Name").text = name
            ET.SubElement(a, "CopyOf").text = src
    ET.indent(root)
    (dest / "AnimData.xml").write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    (dest / "figure.json").write_text(json.dumps(
        {"title": title, "source": "shimeji", "scale_factor": SCALE_FACTOR},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return made, missing
