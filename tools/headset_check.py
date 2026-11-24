#!/usr/bin/env python3
"""Kopfhörer-Check: Mikrofon und „Okay“ im Telefonmodus, je Bluetooth-Codec (mSBC / CVSD).

Für Fälle, in denen der Walkie Gesprochenes nur bruchstückhaft erkennt oder das „Okay“ nach
dem Loslassen nicht zu hören ist. Nimmt je Codec 6 s auf, spielt dabei „Okay“ ab, erkennt den
Text und sagt, was ankam. Stellt am Ende den Musikmodus wieder her. Ändert keine Einstellungen.

    .venv/bin/python tools/headset_check.py          (bzw. die Walkie-venv)
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import audio  # noqa: E402
import settings as S  # noqa: E402
import transcription  # noqa: E402


def pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5)


def bt_card():
    cards = json.loads(pactl("-f", "json", "list", "cards").stdout or "[]")
    for c in cards:
        if c["name"].startswith("bluez_card."):
            return c
    return None


def source_of(card):
    addr = card["name"].split(".", 1)[1]
    for s in json.loads(pactl("-f", "json", "list", "sources").stdout or "[]"):
        if s["name"].startswith(f"bluez_input.{addr}"):
            return s["name"]
    return None


def say(voice, text):
    p = audio.Player(voice.config.sample_rate)
    for chunk in voice.synthesize(text):
        p.write(chunk.audio_int16_bytes)
    p.finish()


def main():
    card = bt_card()
    if not card:
        sys.exit("Kein Bluetooth-Kopfhörer verbunden.")
    before = card["active_profile"]
    profiles = [p for p in ("headset-head-unit", "headset-head-unit-cvsd") if p in card["profiles"]]
    from piper import PiperVoice
    model, _ = S.VOICES[S.get("WALKIE_VOICE")]
    voice = PiperVoice.load(str(ROOT / "voices" / f"{model}.onnx"))
    print("Lade Spracherkennung …")
    wm = transcription.whisper_model(S.get("WALKIE_WHISPER"), cpu_threads=os.cpu_count() or 4)
    results = []
    try:
        for prof in profiles:
            pactl("set-card-profile", card["name"], prof)
            time.sleep(2.5)
            src = source_of(card)
            input(f"\n[{prof}] Enter drücken und dann 5 Sekunden lang deutlich sprechen, "
                  "z. B. „Eins, zwei, drei, vier, fünf, sechs, sieben“ …")
            path = tempfile.mktemp(suffix=".wav", prefix="walkie-check-")
            rec = audio.Recorder()
            if not rec.start(path, src):
                print("  Mikro ließ sich nicht öffnen:", rec.error)
                continue
            time.sleep(5.5)
            mark = rec.data_bytes()
            say(voice, "Okay.")                     # wie im Walkie: bei offenem Mikro
            time.sleep(1.5)
            rec.stop()
            audio.truncate_wav(path, mark)
            text = transcription.transcribe(wm, path)
            heard = input("  Hast du gerade „Okay“ gehört? (j/n) ").strip().lower().startswith("j")
            print(f"  erkannt: {text!r}")
            results.append((prof, text, heard))
            os.unlink(path)
    finally:
        pactl("set-card-profile", card["name"], before)
    print("\nErgebnis (bitte Claude zeigen):")
    for prof, text, heard in results:
        print(f"  {prof:24} Okay gehört: {'ja ' if heard else 'nein'}  erkannt: {text!r}")


if __name__ == "__main__":
    main()
