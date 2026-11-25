"""Whisper-Aufruf: keine Neuversuche mit höherer Temperatur (gestörte Aufnahmen dauern sonst ewig)."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import tempfile
import types
import os
import unittest
import unittest.mock
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


class LazyWhisperTest(unittest.TestCase):
    """Whisper gibt im Leerlauf seinen Speicher frei und lädt beim nächsten Reden von selbst."""

    def test_unloads_after_idle_and_reloads_on_use(self):
        import time
        from transcription import LazyWhisper
        loads = []

        class Model:
            def transcribe(self, audio, **kw):
                return iter([f"seg:{audio}"]), "info"

        lazy = LazyWhisper(lambda: loads.append(1) or Model(), idle_after=0.2)
        self.assertEqual(lazy.transcribe("a"), (["seg:a"], "info"))
        self.assertFalse(lazy.unload_if_idle())          # gerade benutzt
        time.sleep(0.25)
        self.assertTrue(lazy.unload_if_idle())
        self.assertFalse(lazy.loaded)
        lazy.warm()                                       # beim Beginn einer Aufnahme
        for _ in range(50):
            if lazy.loaded:
                break
            time.sleep(0.02)
        self.assertTrue(lazy.loaded)
        self.assertEqual(lazy.transcribe("b")[0], ["seg:b"])
        self.assertEqual(len(loads), 2)

    def test_zero_means_keep_loaded(self):
        import time
        from transcription import LazyWhisper
        lazy = LazyWhisper(lambda: object(), idle_after=0)
        lazy._get()
        time.sleep(0.05)
        self.assertFalse(lazy.unload_if_idle())
        self.assertTrue(lazy.loaded)

    def test_threads_sleep_and_are_capped(self):
        import transcription
        with unittest.mock.patch.dict(os.environ, {}, clear=False) as env:
            env.pop("KMP_BLOCKTIME", None)
            transcription.quiet_threads()
            self.assertEqual(os.environ["KMP_BLOCKTIME"], "0")
            self.assertEqual(os.environ["OMP_WAIT_POLICY"], "PASSIVE")
        self.assertLessEqual(transcription.MAX_THREADS, 4)
