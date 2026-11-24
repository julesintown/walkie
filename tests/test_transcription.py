"""Whisper-Aufruf: keine Neuversuche mit höherer Temperatur (gestörte Aufnahmen dauern sonst ewig)."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import transcription  # noqa: E402


class FakeModel:
    def __init__(self, text):
        self.text, self.kw = text, None

    def transcribe(self, audio, **kw):
        self.kw = kw
        return [types.SimpleNamespace(text=self.text)], None


def silent_wav():
    path = Path(tempfile.mkdtemp()) / "x.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 1600)
    return str(path)


class TranscribeTest(unittest.TestCase):
    def test_no_temperature_fallback(self):
        m = FakeModel(" Hallo Welt.")
        self.assertEqual(transcription.transcribe(m, silent_wav()), "Hallo Welt.")
        self.assertEqual(m.kw["temperature"], 0.0)

    def test_hint_still_passed(self):
        m = FakeModel(" Ja.")
        transcription.transcribe(m, silent_wav(), ["Ja", "Nein"])
        self.assertEqual(m.kw["initial_prompt"], "Ja. Nein.")
        self.assertEqual(m.kw["temperature"], 0.0)


    def test_loop_segment_is_dropped(self):
        m = FakeModel("")
        good = types.SimpleNamespace(text=" Wie geht es dir?", compression_ratio=1.1)
        loop = types.SimpleNamespace(text=" 桌上桌上桌上桌上", compression_ratio=9.0)
        m.transcribe = lambda audio, **kw: ([good, loop], None)
        self.assertEqual(transcription.transcribe(m, silent_wav()), "Wie geht es dir?")
        m.transcribe = lambda audio, **kw: ([loop], None)
        self.assertEqual(transcription.transcribe(m, silent_wav()), "")

    def test_token_cap_scales_with_length_and_fits_window(self):
        self.assertLess(transcription.max_tokens(2), transcription.max_tokens(10))
        self.assertLessEqual(transcription.max_tokens(600), 220)
        self.assertGreaterEqual(transcription.max_tokens(10), 100)     # 10 s schnelles Reden passt


if __name__ == "__main__":
    unittest.main()
