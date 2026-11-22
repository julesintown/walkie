#!/usr/bin/env python3
"""Lädt Sprites und Stimmen lokal herunter – sie liegen bewusst NICHT im Repo.

  python fetch_assets.py voices                 # Standard-Stimme (Thorsten)
  python fetch_assets.py voices all             # alle Stimmen aus settings.VOICES

Figuren liegen im Repo (figures/, CC0) – eigene über „Eigener Ordner …“.
Stimmen: https://huggingface.co/rhasspy/piper-voices
"""
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

DEFAULT_VOICES = ["de_DE-thorsten-medium"]


def voice_path(name):
    """'de_DE-thorsten-medium' -> 'de/de_DE/thorsten/medium/de_DE-thorsten-medium'."""
    locale, speaker, quality = name.split("-")
    return f"{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{name}"


def fetch(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(quote(url, safe=":/"), headers={"User-Agent": "walkie"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    tmp.replace(dest)


def voices(which):
    import settings
    names = ([m for m, _ in settings.VOICES.values()] if which == ["all"]
             else (which or DEFAULT_VOICES))
    out = HERE / "voices"
    out.mkdir(exist_ok=True)
    for n in names:
        try:
            path = voice_path(n)
        except ValueError:
            print(f"? unbekannte Stimme {n}")
            continue
        print(f"  Stimme {n} …", flush=True)
        fetch(f"{VOICE_BASE}/{path}.onnx.json", out / f"{n}.onnx.json")
        fetch(f"{VOICE_BASE}/{path}.onnx", out / f"{n}.onnx")
    print(f"✓ Stimmen in {out}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["voices"]:
        voices(args[1:])
    else:
        print(__doc__)
        sys.exit(1)
