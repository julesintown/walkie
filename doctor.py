#!/usr/bin/env python3
"""Prüft die Installation: ./start.sh --doctor  (oder python doctor.py)"""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audio  # noqa: E402
import keymap  # noqa: E402
import settings  # noqa: E402
from agents import make_agent  # noqa: E402
from hook import RUN, walkie_running  # noqa: E402

OK, WARN, BAD = "✓", "⚠", "✗"
problems = 0


def line(state, text):
    global problems
    mark = OK if state is True else BAD if state is False else WARN
    problems += state is False
    print(f"  {mark} {text}")


def headset_check():
    """Bluetooth-Kopfhörer-Taste: Gerät da? Lesbar?"""
    import re
    mode = settings.get("WALKIE_HEADSET")
    if mode.lower() == "off":
        line(None, "Kopfhörer-Taste: ausgeschaltet (WALKIE_HEADSET=off)")
        return
    try:
        text = Path("/proc/bus/input/devices").read_text()
    except OSError:
        return
    blocks = text.split("\n\n")
    found = False
    for b in blocks:
        m = re.search(r'^N: Name="(.*)"$', b, re.M)
        h = re.search(r"^H: Handlers=.*?(event\d+)", b, re.M)
        if not m or not h:
            continue
        name = m.group(1)
        if not keymap.matches(mode, name):
            continue
        found = True
        dev = f"/dev/input/{h.group(1)}"
        ok = os.access(dev, os.R_OK)
        line(ok, f"Kopfhörer-Taste: {name}" + ("" if ok else
             f" – {dev} nicht lesbar – einmalig: walkie keys unlock"))
    if not found:
        line(None, "Kopfhörer-Taste: kein Bluetooth-Kopfhörer verbunden")


def main():
    print(f"Walkie – {sys.platform}, Python {sys.version.split()[0]}")
    line(sys.version_info >= (3, 10), "Python ≥ 3.10")
    for mod, why in (("PyQt6", "Fenster"), ("numpy", "Pegel"), ("miniaudio", "Audio"),
                     ("piper", "Vorlesen"),
                     ("faster_whisper", "Spracherkennung (Whisper)")):
        try:
            __import__(mod)
            line(True, f"{mod} ({why})")
        except ImportError:
            line(False, f"{mod} fehlt ({why}) – walkie setup ausführen")
    sprite = settings.sprite_dir()
    line((sprite / "AnimData.xml").exists(), f"Sprite: {sprite}")
    voices = sorted(p.stem for p in (HERE / "voices").glob("*.onnx"))
    line(bool(voices), f"Stimmen: {', '.join(voices) or 'keine – fetch_assets.py voices'}")
    if settings.talk_terminal():
        line(bool(shutil.which("kitty")), "kitty (eigenes Terminal über der Figur)")
    be = audio.backend()
    line(True if be else False, f"Audio: {be or 'nichts gefunden – pip install miniaudio'}")
    mics = [n for n, _ in audio.sources()]
    line(True if mics else None, f"Mikrofone: {', '.join(mics) or 'keins gefunden'}")
    if sys.platform.startswith("linux"):
        line(True if shutil.which("notify-send") else None, "notify-send (Desktop-Hinweise)")
        headset_check()
    try:
        agent = make_agent("", settings.get("WALKIE_STT"))
        exe = agent.binary()
        line(bool(shutil.which(exe)), f"Agent '{agent.name}': {exe}")
        for state, text in agent.doctor():
            line(state, text)
    except RuntimeError as ex:
        line(False, str(ex))
    line(True if RUN.exists() else None, f"Statusordner: {RUN}"
         + ("" if RUN.exists() else " (entsteht beim ersten Ereignis)"))
    print(f"  {'●' if walkie_running() else '○'} Begleiter läuft {'gerade' if walkie_running() else 'nicht'}")
    print("\nAlles bereit." if not problems else f"\n{problems} Problem(e) – siehe ✗")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
