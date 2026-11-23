"""macOS-Aufnahme über ein Hilfsprogramm (stdout -> WAV), mit Ersatzprogramm statt Swift."""
import isolate  # noqa: F401 – zuerst: nie in die echten Walkie-Ordner
import os
import stat
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import audio  # noqa: E402


@unittest.skipIf(sys.platform == "win32", "Shell-Ersatzprogramm")
class VoicemicTest(unittest.TestCase):
    def test_piped_helper_becomes_a_valid_wav(self):
        tmp = Path(tempfile.mkdtemp())
        exe = tmp / "voicemic"
        exe.write_text("#!/bin/sh\nexec head -c 32000 /dev/zero\n", encoding="utf-8")   # 1 s Stille, 16 kHz s16
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        wav = tmp / "rec.wav"
        with mock.patch.object(audio.sys, "platform", "darwin"), \
                mock.patch.object(audio, "mac_voicemic_path", lambda: exe), \
                mock.patch("settings.get", lambda k: True if k == "WALKIE_MAC_VOICE_PROCESSING" else None):
            rec = audio.Recorder()
            self.assertTrue(rec._start_mac_voicemic(str(wav)))
            time.sleep(0.6)
            rec.stop()
        with wave.open(str(wav)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels()), (16000, 1))
            self.assertEqual(w.getnframes(), 16000)

    def test_off_or_missing_means_normal_path(self):
        rec = audio.Recorder()
        with mock.patch.object(audio.sys, "platform", "darwin"), \
                mock.patch("settings.get", lambda k: False):
            self.assertFalse(rec._start_mac_voicemic(os.devnull))


class TruncateTest(unittest.TestCase):
    def test_own_okay_is_cut_off(self):
        tmp = Path(tempfile.mkdtemp()) / "rec.wav"
        tmp.write_bytes(audio._wav_header(64000) + b"\x01\x00" * 32000)   # 2 s
        audio.truncate_wav(str(tmp), 32000)                                 # auf 1 s
        with wave.open(str(tmp)) as w:
            self.assertEqual(w.getnframes(), 16000)
