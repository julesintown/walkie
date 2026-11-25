"""Windows: Kopfhörertasten über die Mediensteuerung – wann der Walkie sie übernimmt."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import keys  # noqa: E402


def remote():
    """WinRemote ohne winrt: nur die Steuerlogik, die Mediensteuerung nachgebaut."""
    r = keys.WinRemote.__new__(keys.WinRemote)
    r.wm = SimpleNamespace(MediaPlaybackStatus=SimpleNamespace(PLAYING="playing", STOPPED="stopped"))
    r.smtc = SimpleNamespace(is_enabled=False, playback_status=None)
    r.log, r.owned, r.hold_until, r.unwanted_since = (lambda m: None), False, 0.0, 0.0
    r.track = SimpleNamespace(set=lambda on: None)
    return r


class WinMediaKeys(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(keys, "learning", return_value=False),
                  patch.object(keys.S, "get", side_effect=lambda k: "smart")):
            p.start()
            self.addCleanup(p.stop)

    def test_takes_keys_when_busy_or_terminal_in_front(self):
        r = remote()
        with patch.object(keys, "win_foreground_exe", return_value="spotify.exe"):
            r.tick(busy=False)
            self.assertFalse(r.owned)                      # Musik-App vorne: Tasten bleiben dort
            r.tick(busy=True)
            self.assertTrue(r.owned)                       # spricht/hört zu: Tasten beim Walkie
            self.assertEqual(r.smtc.playback_status, "playing")
        with patch.object(keys, "win_foreground_exe", return_value="windowsterminal.exe"):
            r.tick(busy=False)
            self.assertTrue(r.owned)

    def test_learning_takes_keys_and_music_key_releases_them(self):
        r = remote()
        with patch.object(keys, "win_foreground_exe", return_value="spotify.exe"), \
                patch.object(keys, "learning", return_value=True):
            r.tick(busy=False)
            self.assertTrue(r.owned)                       # Anlernen braucht die Tasten
        with patch.object(keys, "win_foreground_exe", return_value="windowsterminal.exe"):
            r.release(4.0)                                  # Musik-Taste weiterreichen
            self.assertFalse(r.owned)
            self.assertFalse(r.smtc.is_enabled)
            r.tick(busy=False)
            self.assertFalse(r.owned)                       # bleibt kurz frei
            r.hold_until = time.time() - 1
            r.tick(busy=False)
            self.assertTrue(r.owned)

    def test_short_glance_elsewhere_keeps_the_keys(self):
        """Kurz ein anderes Fenster vorne: erst nach RELEASE_AFTER abgeben (sonst ging die
        Tonspur ständig auf und zu)."""
        r = remote()
        with patch.object(keys, "win_foreground_exe", return_value="windowsterminal.exe"):
            r.tick(busy=False)
        self.assertTrue(r.owned)
        with patch.object(keys, "win_foreground_exe", return_value="pythonw.exe"):
            r.tick(busy=False)
            self.assertTrue(r.owned)
            r.unwanted_since = time.time() - r.RELEASE_AFTER - 1
            r.tick(busy=False)
            self.assertFalse(r.owned)

    def test_silent_track_never_blocks_the_caller(self):
        """Kopfhörer gewechselt: miniaudios close() hängt für immer – der Aufrufer (GUI-Thread)
        darf davon nichts merken."""
        import threading
        stuck = threading.Event()

        class Dev:
            def stop(self): pass
            def close(self): stuck.wait(5)          # hängt (im Test: 5 s)
        t = keys.SilentTrack(lambda m: None)
        t.dev = Dev()
        started = time.time()
        t.set(False)
        self.assertLess(time.time() - started, 0.5)
        stuck.set()

    def test_smtc_buttons_map_to_headset_keys(self):
        self.assertEqual(keys.SMTC_KEYS["PAUSE"], "PLAYPAUSE")
        self.assertEqual(keys.SMTC_KEYS["PLAY"], "PLAYPAUSE")
        self.assertEqual(keys.SMTC_KEYS["NEXT"], "NEXTSONG")


if __name__ == "__main__":
    unittest.main()
