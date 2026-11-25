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


MAX_THREADS = 4          # mehr Threads machen Whisper kaum schneller, belegen aber Kerne


def quiet_threads():
    """Rechen-Threads von Whisper (Intel OpenMP in CTranslate2) nach getaner Arbeit sofort
    schlafen legen. Ohne das warten sie aktiv auf die nächste Aufgabe und halten je einen Kern
    auf Volllast – gemessen unter Windows: drei Threads, je 100 %, über zehn Minuten. Wirkt
    nur, bevor CTranslate2 geladen ist; eigene Werte des Nutzers bleiben."""
    os.environ.setdefault("KMP_BLOCKTIME", "0")
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")


def whisper_model(name, **kw):
    """faster_whisper.WhisperModel laden (CPU, int8) – auch ohne PyAV."""
    quiet_threads()
    without_pyav()
    from faster_whisper import WhisperModel
    kw.setdefault("cpu_threads", min(MAX_THREADS, os.cpu_count() or MAX_THREADS))
    return WhisperModel(name, device="cpu", compute_type="int8", **kw)


class LazyWhisper:
    """Whisper, das sich nach idle_after Sekunden ohne Nutzung aus dem Speicher nimmt (rund
    0,3–0,8 GB je nach Modell) und bei der nächsten Erkennung von selbst wieder lädt. Nach außen
    wie das Modell: transcribe(); warm() lädt im Voraus (beim Beginn einer Aufnahme – sie dauert
    länger als das Laden). idle_after 0 = nie entladen."""

    def __init__(self, load, idle_after=0.0, log=lambda m: None):
        import threading
        self._load, self.idle_after, self.log = load, idle_after, log
        self._model = None
        self._lock = threading.Lock()
        self._used = 0.0
        self._busy = 0

    @property
    def loaded(self):
        return self._model is not None

    def _get(self):
        import time
        with self._lock:
            if self._model is None:
                started = time.monotonic()
                self._model = self._load()
                self.log(f"whisper geladen ({time.monotonic() - started:.1f} s)")
            self._used = time.monotonic()
            return self._model

    def warm(self):
        """Im Hintergrund laden, falls entladen (kehrt sofort zurück)."""
        import threading
        if self._model is None:
            threading.Thread(target=self._get, daemon=True, name="whisper-warm").start()

    def transcribe(self, *args, **kw):
        import time
        model = self._get()
        self._busy += 1
        try:
            segs, info = model.transcribe(*args, **kw)
            return list(segs), info          # erst hier rechnet Whisper (Generator)
        finally:
            self._busy -= 1
            self._used = time.monotonic()

    def unload_if_idle(self):
        """Regelmäßig aufrufen. -> True, wenn entladen."""
        import gc
        import time
        if not self.idle_after or self._model is None or self._busy:
            return False
        if time.monotonic() - self._used < self.idle_after:
            return False
        with self._lock:
            if self._busy or time.monotonic() - self._used < self.idle_after:
                return False
            self._model = None
        gc.collect()
        self.log("whisper entladen (Leerlauf)")
        return True


def transcribe(model, wav, hint=None):
    """Whisper-Text einer WAV-Datei: ohne Wiederholungen ("ja, ja, ja") und ohne die
    typischen Stille-Halluzinationen. hint = erwartete Wörter (z. B. Optionen).
    temperature=0.0: keine Neuversuche. Sonst setzt faster-whisper bei unsicherem Ergebnis bis zu
    fünfmal neu an (gestörte Bluetooth-Aufnahme: 16–20 s statt 2–4 s), und heraus kommt trotzdem
    Wortsalat. Saubere Aufnahmen erkennt es beim ersten Versuch, dort ändert sich nichts."""
    kw = {"initial_prompt": ". ".join(hint) + "."} if hint else {}
    audio = load_wav(wav)
    segs, _ = model.transcribe(audio, language=S.stt_language(),
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
