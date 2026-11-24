#!/usr/bin/env python3
"""Mikro-Zeitleiste: Ab wann liefert das Kopfhörer-Mikro nach dem Umschalten in den Telefonmodus Ton?

Schaltet den Bluetooth-Kopfhörer je Codec (mSBC, CVSD) in den Telefonmodus, nimmt sofort 15 s auf und
zeigt die Lautstärke je halbe Sekunde. Man zählt dabei laut von 1 bis 15. Stellt am Ende das alte Profil
wieder her.     python3 tools/mic_timeline.py
"""
import array
import json
import math
import subprocess
import sys
import time


def pactl(*a):
    return subprocess.run(["pactl", *a], capture_output=True, text=True, timeout=5)


def card():
    for c in json.loads(pactl("-f", "json", "list", "cards").stdout or "[]"):
        if c["name"].startswith("bluez_card."):
            return c
    sys.exit("Kein Bluetooth-Kopfhörer verbunden.")


def run(c, prof):
    addr = c["name"].split(".", 1)[1]
    t0 = time.time()
    pactl("set-card-profile", c["name"], prof)
    src = None
    while time.time() - t0 < 5 and not src:
        for s in json.loads(pactl("-f", "json", "list", "sources").stdout or "[]"):
            if s["name"].startswith(f"bluez_input.{addr}"):
                src = s["name"]
        time.sleep(0.05)
    if not src:
        print(f"[{prof}] kein Mikro erschienen")
        return
    print(f"\n[{prof}] Mikro nach {time.time() - t0:.1f} s da. JETZT laut von 1 bis 15 zählen (1 pro Sekunde) …")
    p = subprocess.Popen(["parec", "-d", src, "--raw", "--format=s16le", "--rate=16000", "--channels=1"],
                         stdout=subprocess.PIPE)
    data = b""
    end = time.time() + 15
    while time.time() < end:
        data += p.stdout.read(1600)
    p.kill()
    s = array.array("h", data)
    step = 8000                                   # 0,5 s
    for i in range(0, len(s), step):
        part = s[i:i + step]
        rms = math.sqrt(sum(x * x for x in part) / max(len(part), 1)) / 32768
        print(f"  {i / 16000:5.1f} s  {rms:.4f}  {'#' * min(60, int(rms * 600))}")


def main():
    c = card()
    before = c["active_profile"]
    try:
        for prof in ("headset-head-unit", "headset-head-unit-cvsd"):
            if prof in c["profiles"]:
                pactl("set-card-profile", c["name"], before)
                time.sleep(2)
                input(f"\nEnter drücken für {prof} …")
                run(c, prof)
    finally:
        pactl("set-card-profile", c["name"], before)
    print("\nFertig. Bitte Claude die Ausgabe zeigen.")


if __name__ == "__main__":
    main()
