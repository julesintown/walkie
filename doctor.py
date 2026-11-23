#!/usr/bin/env python3
"""Prüft die Installation: ./start.sh --doctor  (oder python doctor.py)"""
import argparse
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


def headset_check(line):
    """Bluetooth-Kopfhörer-Taste: Gerät da? Lesbar?"""
    import re
    mode = settings.get("WALKIE_HEADSET")
    if mode.lower() == "off":
        line(None, "Kopfhörer-Taste: ausgeschaltet (WALKIE_HEADSET=off)")
        return
    try:
        text = Path("/proc/bus/input/devices").read_text(encoding="utf-8", errors="replace")
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
        line(True if ok else None, f"Kopfhörer-Taste: {name}" + ("" if ok else
             f" – {dev} nicht lesbar – einmalig: walkie keys unlock"))
    if not found:
        line(None, "Kopfhörer-Taste: kein Bluetooth-Kopfhörer verbunden")


def main(argv=None):
    import crashguard
    crashguard.safe_console()             # Windows-Konsole (cp1252): ✓ und ✗ ohne Absturz
    parser = argparse.ArgumentParser(description="Walkie-Installation prüfen")
    parser.add_argument("--allow-missing-agent", action="store_true",
                        help="Eine fehlende Agent-CLI nur als Warnung melden")
    args = parser.parse_args(argv)
    problems = warnings = 0

    def line(state, text):
        nonlocal problems, warnings
        problems += state is False
        warnings += state is None
        mark = OK if state is True else BAD if state is False else WARN
        print(f"  {mark} {text}")

    print(f"Walkie – {sys.platform}, Python {sys.version.split()[0]}")
    line(sys.version_info >= (3, 10), "Python ≥ 3.10")
    for mod, why in (("PyQt6.QtWidgets", "Fenster"), ("numpy", "Pegel"), ("miniaudio", "Audio"),
                     ("piper", "Vorlesen"),
                     ("faster_whisper", "Spracherkennung (Whisper)")):
        try:
            if mod == "faster_whisper":
                from transcription import without_pyav
                without_pyav()
            __import__(mod)
            line(True, f"{mod} ({why})")
        except (ImportError, OSError) as ex:
            line(False, f"{mod} nicht ladbar ({why}): {ex} – walkie setup ausführen")
    if sys.platform.startswith("linux"):
        import sysdeps
        libs = sysdeps.report()
        qt = [m for m in libs["missing"] if m != "libasound.so.2"]
        fix = (" – sudo " + " ".join(libs["command"])) if libs["command"] else ""
        headless = os.environ.get("QT_QPA_PLATFORM") in ("offscreen", "minimal")
        if qt:
            line(None if headless else False,
                 f"Systembibliotheken für Qt fehlen: {', '.join(qt)}{fix}")
        if "libasound.so.2" in libs["missing"]:
            line(None, f"Keine Audio-Bibliothek (ALSA/PulseAudio) gefunden{fix}")
    sprite = settings.sprite_dir()
    line((sprite / "AnimData.xml").exists(), f"Sprite: {sprite}")
    voice = settings.get("WALKIE_VOICE")
    model = settings.VOICES.get(voice, settings.VOICES[settings.DEFAULT_VOICE])[0]
    voice_ready = all((HERE / "voices" / (model + ext)).is_file() for ext in (".onnx", ".onnx.json"))
    line(True if voice_ready else None, f"Stimme: {model}" + ("" if voice_ready else
         " fehlt – zum Vorlesen mit walkie setup nachladen"))
    if settings.talk_terminal():
        line(True if shutil.which("kitty") else None, "kitty (eigenes Terminal über der Figur)")
    be = audio.backend()
    line(True if be else False, f"Audio: {be or 'nichts gefunden – pip install miniaudio'}")
    mics = [n for n, _ in audio.sources()]
    line(True if mics else None, f"Mikrofone: {', '.join(mics) or 'keins gefunden'}")
    if sys.platform.startswith("linux"):
        line(True if shutil.which("notify-send") else None, "notify-send (Desktop-Hinweise)")
        headset_check(line)
    try:
        agent = make_agent("", settings.get("WALKIE_STT"))
        exe = agent.binary()
        if shutil.which(exe):
            line(True, f"Agent '{agent.name}': {exe}")
        else:
            line(None if args.allow_missing_agent else False,
                 f"Agent '{agent.name}': {exe} fehlt – für Gespräche mit diesem Agent installieren")
        for state, text in agent.doctor():
            line(state, text)
        caps = agent.capabilities()
        if caps:
            print(f"      kann: {', '.join(caps)}")
        import router
        brains = router.brains()
        line(True if brains else None, "Denkmodell: " + (", ".join(brains) if brains else
             "keins (claude, codex, agy oder gemini) – Routing nur nach Namen"))
    except RuntimeError as ex:
        line(False, str(ex))
    line(True if RUN.exists() else None, f"Statusordner: {RUN}"
         + ("" if RUN.exists() else " (entsteht beim ersten Ereignis)"))
    print(f"  {'●' if walkie_running() else '○'} Begleiter läuft {'gerade' if walkie_running() else 'nicht'}")
    if problems:
        print(f"\n{problems} Problem(e) – siehe ✗")
    elif warnings:
        print(f"\nInstallation geprüft, {warnings} Hinweis(e) – siehe ⚠")
    else:
        print("\nAlles bereit.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
