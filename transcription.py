"""WAV-Aufbereitung und lokale Spracherkennung mit Whisper."""
import os
import re
from pathlib import Path

import settings as S

# Whisper erfindet bei Stille gern Floskeln -> verwerfen
HALLUCINATIONS = re.compile(
    r"^(untertitel.*|vielen dank( fürs zuschauen)?|danke( schön)?|tschüss|"
    r"thank you( for watching)?|thanks for watching|you|bye|\.+|…)[.!?]*$", re.I)


def without_pyav():
    """faster-whisper importiert PyAV (`av`) nur, um Audiodateien zu dekodieren. Der Walkie
    übergibt fertige numpy-Arrays (load_wav), die Installation lässt das ~130 MB große Paket
    deshalb weg – hier steht stattdessen ein leerer Platzhalter."""
    import sys
    import types
    try:
        import av  # noqa: F401
    except ImportError:
        stub = types.ModuleType("av")
        stub.__walkie_stub__ = True
        sys.modules.setdefault("av", stub)


def whisper_model(name, **kw):
    """faster_whisper.WhisperModel laden (CPU, int8) – auch ohne PyAV."""
    without_pyav()
    from faster_whisper import WhisperModel
    return WhisperModel(name, device="cpu", compute_type="int8", **kw)


def transcribe(model, wav, hint=None):
    """Whisper-Text einer WAV-Datei: ohne Wiederholungen ("ja, ja, ja") und ohne die
    typischen Stille-Halluzinationen. hint = erwartete Wörter (z. B. Optionen).
    temperature=0.0: keine Neuversuche. Sonst setzt faster-whisper bei unsicherem Ergebnis bis zu
    fünfmal neu an (gestörte Bluetooth-Aufnahme: 16–20 s statt 2–4 s), und heraus kommt trotzdem
    Wortsalat. Saubere Aufnahmen erkennt es beim ersten Versuch, dort ändert sich nichts."""
    kw = {"initial_prompt": ". ".join(hint) + "."} if hint else {}
    audio = load_wav(wav)
    segs, _ = model.transcribe(audio, language=S.get("WALKIE_LANG") or None,
                               vad_filter=True, beam_size=1, condition_on_previous_text=False,
                               temperature=0.0, max_new_tokens=max_tokens(len(audio) / 16000),
                               **kw)
    # Schleife („桌上桌上…“, „halt, halt, …“): Whisper markiert sie selbst mit hoher Kompressionsrate
    text = " ".join(s.text.strip() for s in segs
                    if getattr(s, "compression_ratio", 0) <= LOOP_RATIO).strip()
    text = re.sub(r"\s*[\[(][^\])]{1,30}[\])]\s*", " ", text).strip()   # [Musik], (Stille) – aus VoiceMode
    text = re.sub(r"\s*(\*[^*]{1,30}\*|♪[^♪]*♪?)\s*", " ", text).strip()  # *lacht*, ♪ … ♪ – aus VoiceTerm
    text = re.sub(r"\b((?:\w+\W+){0,2}?\w+)(?:[,.!]?\s+\1\b)+", r"\1", text, flags=re.I)
    if hint and len(hint) > 1 and text.rstrip(".") == kw["initial_prompt"].rstrip("."):
        return ""                                  # Stille: Whisper wiederholt nur den Hinweis
    return "" if HALLUCINATIONS.match(text) else text


LOOP_RATIO = 2.4          # faster-whispers eigene Grenze für „wiederholt sich“


def max_tokens(seconds):
    """Obergrenze neuer Tokens pro 30-s-Stück: schnelles Sprechen ergibt ~5 Tokens/s. Eine
    Schleife läuft sonst bis 448 Tokens (Sekunden Rechenzeit). Höchstens 220, damit Hinweisliste
    (≤ 223 Tokens) plus Antwort in Whispers 448er-Fenster passen."""
    return int(min(220, 30 + 8 * min(seconds, 30)))


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
