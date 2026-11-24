"""Recorder.stop() darf nie hängen, auch wenn miniaudios close() blockiert (BT-Mikro weg)."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import audio  # noqa: E402


class FakeDev:
    def __init__(self, hang):
        self.hang = hang
        self.release = threading.Event()
        self.closed = False

    def stop(self):
        pass

    def close(self):
        if self.hang:
            self.release.wait(30)
        self.closed = True


def recorder(tmp, dev):
    rec = audio.Recorder()
    rec.path = str(tmp / "rec.wav")
    rec.file = open(rec.path, "wb")
    rec.file.write(audio._wav_header())
    rec.file.write(b"\0\0" * 1600)
    rec.bytes = 3200
    rec.dev = dev
    return rec


class RecorderStopTest(unittest.TestCase):
    def test_normal_close_is_synchronous(self):
        tmp = Path(tempfile.mkdtemp())
        dev = FakeDev(hang=False)
        rec = recorder(tmp, dev)
        rec.stop()
        self.assertTrue(dev.closed)
        self.assertIsNone(rec.dev)
        with wave.open(rec.path) as w:
            self.assertEqual(w.getnframes(), 1600)

    def test_hanging_close_does_not_block_caller(self):
        tmp = Path(tempfile.mkdtemp())
        dev = FakeDev(hang=True)
        rec = recorder(tmp, dev)
        rec.CLOSE_TIMEOUT = 0.2
        t = time.monotonic()
        rec.stop()
        self.assertLess(time.monotonic() - t, 2)
        self.assertIsNone(rec.dev)
        self.assertTrue(rec.error)
        with wave.open(rec.path) as w:               # Datei trotzdem gültig abgeschlossen
            self.assertEqual(w.getnframes(), 1600)
        dev.release.set()


if __name__ == "__main__":
    unittest.main()


class KeepRecordingTest(unittest.TestCase):
    def test_keeps_only_the_last_five(self):
        import walkie as ev
        tmp = Path(tempfile.mkdtemp())
        old = ev.RECENT
        ev.RECENT = tmp / "recent"
        try:
            for i in range(7):
                ev.RECENT.mkdir(exist_ok=True)
                (ev.RECENT / f"2026010{i}-000000.wav").write_bytes(b"x")
            wav = tmp / "neu.wav"
            wav.write_bytes(b"y")
            ev.keep_recording(str(wav))
            kept = sorted(p.name for p in ev.RECENT.glob("*.wav"))
            self.assertEqual(len(kept), 5)
            self.assertFalse(wav.exists())
            self.assertNotIn("20260100-000000.wav", kept)
        finally:
            ev.RECENT = old
