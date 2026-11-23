"""WAV-Aufbereitung und lokale Spracherkennung mit Whisper."""
import os
import re
from pathlib import Path

import settings as S

# Whisper erfindet bei Stille gern Floskeln -> verwerfen
HALLUCINATIONS = re.compile(
    r"^(untertitel.*|vielen dank( fürs zuschauen)?|danke( schön)?|tschüss|"
    r"thank you( for watching)?|thanks for watching|you|bye|\.+|…)[.!?]*$", re.I)


def transcribe(model, wav, hint=None):
    """Whisper-Text einer WAV-Datei: ohne Wiederholungen ("ja, ja, ja") und ohne die
    typischen Stille-Halluzinationen. hint = erwartete Wörter (z. B. Optionen)."""
    kw = {"initial_prompt": ". ".join(hint) + "."} if hint else {}
    segs, _ = model.transcribe(load_wav(wav), language=S.get("WALKIE_LANG") or None,
                               vad_filter=True, beam_size=1, condition_on_previous_text=False,
                               **kw)
    text = " ".join(s.text.strip() for s in segs).strip()
    text = re.sub(r"\s*[\[(][^\])]{1,30}[\])]\s*", " ", text).strip()   # [Musik], (Stille) – aus VoiceMode
    text = re.sub(r"\b((?:\w+\W+){0,2}?\w+)(?:[,.!]?\s+\1\b)+", r"\1", text, flags=re.I)
    if hint and len(hint) > 1 and text.rstrip(".") == kw["initial_prompt"].rstrip("."):
        return ""                                  # Stille: Whisper wiederholt nur den Hinweis
    return "" if HALLUCINATIONS.match(text) else text


def load_wav(path):
    """WAV -> float32 mono 16 kHz (ohne PyAV)."""
    import wave
    import numpy as np
    with wave.open(path, "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if not raw and os.path.getsize(path) > 44:  # Header evtl. nicht finalisiert
        raw = Path(path).read_bytes()[44:]
    dtype = {2: np.int16, 4: np.int32}[width]
    a = np.frombuffer(raw[: len(raw) // (width * ch) * width * ch], dtype=dtype)
    a = a.astype(np.float32) / float(np.iinfo(dtype).max)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != 16000 and len(a):
        n = int(len(a) * 16000 / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a
