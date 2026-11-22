"""Gesten-Erkennung der Kopfhörertasten (ohne Hardware)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keymap import Gestures, normalize  # noqa: E402


class GestureTest(unittest.TestCase):
    def test_single_fires_immediately_when_nothing_else_mapped(self):
        g = Gestures({"PLAYPAUSE": {"press": "talk"}})
        self.assertEqual(g.feed("PLAYPAUSE", 1, 0.0), [("PLAYPAUSE", "press")])
        self.assertEqual(g.feed("PLAYPAUSE", 0, 0.1), [])

    def test_double_press(self):
        g = Gestures({"PREVIOUSSONG": {"press": "media_toggle", "double": "repeat"}})
        self.assertEqual(g.feed("PREVIOUSSONG", 1, 0.0), [])
        self.assertEqual(g.feed("PREVIOUSSONG", 0, 0.08), [])
        self.assertEqual(g.feed("PREVIOUSSONG", 1, 0.25), [("PREVIOUSSONG", "double")])
        self.assertEqual(g.feed("PREVIOUSSONG", 0, 0.3), [])
        self.assertEqual(g.poll(1.0), [])

    def test_single_waits_for_double_window(self):
        g = Gestures({"PREVIOUSSONG": {"press": "media_toggle", "double": "repeat"}})
        g.feed("PREVIOUSSONG", 1, 0.0)
        g.feed("PREVIOUSSONG", 0, 0.08)
        self.assertEqual(g.poll(0.3), [])
        self.assertEqual(g.poll(0.6), [("PREVIOUSSONG", "press")])

    def test_long_press_via_hold_events(self):
        g = Gestures({"PLAYPAUSE": {"press": "talk", "long": "repeat"}})
        self.assertEqual(g.feed("PLAYPAUSE", 1, 0.0), [])
        self.assertEqual(g.feed("PLAYPAUSE", 2, 0.3), [])
        self.assertEqual(g.feed("PLAYPAUSE", 2, 0.7), [("PLAYPAUSE", "long")])
        self.assertEqual(g.feed("PLAYPAUSE", 0, 1.0), [])

    def test_long_press_via_release_time(self):
        g = Gestures({"PLAYPAUSE": {"press": "talk", "long": "repeat"}})
        g.feed("PLAYPAUSE", 1, 0.0)
        self.assertEqual(g.feed("PLAYPAUSE", 0, 0.9), [("PLAYPAUSE", "long")])
        g.feed("PLAYPAUSE", 1, 2.0)
        self.assertEqual(g.feed("PLAYPAUSE", 0, 2.1), [("PLAYPAUSE", "press")])

    def test_dedup_play_pause_double_signal(self):
        g = Gestures({"PLAYPAUSE": {"press": "talk", "double": "repeat"}})
        g.feed(normalize("KEY_PLAYCD"), 1, 0.0)
        g.feed(normalize("KEY_PAUSECD"), 1, 0.02)       # gleicher Druck, anderes Signal
        g.feed("PLAYPAUSE", 0, 0.1)
        self.assertEqual(g.poll(0.6), [("PLAYPAUSE", "press")])

    def test_press_without_release(self):
        g = Gestures({"NEXTSONG": {"press": "media_next", "long": "repeat"}})
        g.feed("NEXTSONG", 1, 0.0)
        self.assertEqual(g.poll(1.6), [("NEXTSONG", "press")])

    def test_normalize(self):
        self.assertEqual(normalize("KEY_PAUSECD"), "PLAYPAUSE")
        self.assertEqual(normalize(["KEY_NEXTSONG", "KEY_NEXT"]), "NEXTSONG")
        self.assertEqual(normalize("KEY_VOLUMEUP"), "VOLUMEUP")


class BackendTest(unittest.TestCase):
    def test_failing_backends_never_break_start(self):
        import keys
        logs = []
        orig = (keys.start_hotkey, keys.start_windows_media, keys.start_mac_media)

        def boom(emit, log):
            raise RuntimeError("keine Rechte")
        keys.start_hotkey = keys.start_windows_media = keys.start_mac_media = boom
        try:
            self.assertEqual(keys.start(lambda a: None, log=logs.append), [])
            self.assertEqual(len(logs), 3)
        finally:
            keys.start_hotkey, keys.start_windows_media, keys.start_mac_media = orig

    def test_other_platform_backends_stay_off(self):
        import sys

        import keys
        if sys.platform != "win32":
            self.assertFalse(keys.start_windows_media(lambda a: None, print))
        if sys.platform != "darwin":
            self.assertFalse(keys.start_mac_media(lambda a: None, print))


import keymap  # noqa: E402

class UnlockTest(unittest.TestCase):
    def test_unlock_command_quotes_path_and_installs_only_the_rule(self):
        import shlex
        from unittest import mock
        with mock.patch("shutil.which", return_value="/usr/bin/pkexec"):
            cmd = keymap.unlock_command("/home/a b/x; rm -rf ~/70.rules")
        self.assertEqual(cmd[:3], ["pkexec", "sh", "-c"])
        parts = shlex.split(cmd[3].split(" && ")[0])
        self.assertEqual(parts, ["install", "-m", "0644", "/home/a b/x; rm -rf ~/70.rules",
                                 keymap.RULE_DEST])

    def test_without_pkexec_there_is_a_manual_hint(self):
        from unittest import mock
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(keymap.unlock_command("/r"))
        self.assertIn(keymap.RULE_DEST, keymap.unlock_hint("/r"))


class MacRemoteTest(unittest.TestCase):
    """macOS: Tasten übernehmen nur, wenn es passt (ohne echten Mac: MediaPlayer nachgebaut)."""
    def setUp(self):
        import types
        from unittest import mock
        self.center = types.SimpleNamespace(state=None, info=None)
        self.center.setPlaybackState_ = lambda s: setattr(self.center, "state", s)
        self.center.setNowPlayingInfo_ = lambda i: setattr(self.center, "info", i)
        mp = types.SimpleNamespace(
            MPNowPlayingPlaybackStatePlaying=1, MPNowPlayingPlaybackStateStopped=2,
            MPNowPlayingInfoCenter=types.SimpleNamespace(defaultCenter=lambda: self.center))
        self.patch = mock.patch.dict("sys.modules", {"MediaPlayer": mp, "miniaudio": None})
        self.patch.start()
        import keys
        self.keys = keys
        self.r = keys.MacRemote(log=lambda m: None)
        self.front = ""
        self.r.frontmost = lambda: self.front

    def tearDown(self):
        self.patch.stop()

    def test_smart_owns_only_when_busy_or_terminal_in_front(self):
        from unittest import mock
        with mock.patch.object(self.keys.S, "get", lambda k: "smart"):
            self.front = "com.spotify.client"
            self.r.tick(busy=False)
            self.assertFalse(self.r.owned, "Musik-App vorne: Tasten bleiben bei der Musik")
            self.r.tick(busy=True)
            self.assertTrue(self.r.owned, "Walkie spricht/fragt: Tasten zu ihm")
            self.assertEqual(self.center.state, 1)
            self.r.tick(busy=False)
            self.assertFalse(self.r.owned)
            self.assertEqual(self.center.state, 2)
            self.front = "com.googlecode.iterm2"
            self.r.tick(busy=False)
            self.assertTrue(self.r.owned, "Terminal vorne: Tasten zum Walkie")

    def test_release_lets_a_music_key_through(self):
        from unittest import mock
        with mock.patch.object(self.keys.S, "get", lambda k: "always"):
            self.r.tick(busy=False)
            self.assertTrue(self.r.owned)
            self.r.release(seconds=60)
            self.r.tick(busy=False)
            self.assertFalse(self.r.owned, "kurz frei für die Musik-Taste")
            self.r.tick(busy=True)
            self.assertTrue(self.r.owned, "fragt er etwas, holt er sie sofort zurück")


class MacComboTest(unittest.TestCase):
    def test_parse_mac_combo(self):
        import keys
        self.assertEqual(keys.parse_mac_combo("<ctrl>+<alt>+<space>"), ({"ctrl", "alt"}, 49))
        self.assertEqual(keys.parse_mac_combo("<cmd>+<shift>+b"), ({"cmd", "shift"}, "b"))
        self.assertEqual(keys.parse_mac_combo("<ctrl>+<f5>"), ({"ctrl"}, 96))
        self.assertIsNone(keys.parse_mac_combo("<ctrl>+<weird>")[1])


class MacPauseTest(unittest.TestCase):
    def test_pause_never_opens_the_mic(self):
        import keys
        self.assertEqual(keys.mac_action("talk", "pause"), "talk_off")
        self.assertEqual(keys.mac_action("talk", "toggle"), "talk")
        self.assertEqual(keys.mac_action("media_toggle", "pause"), "media_toggle")


if __name__ == "__main__":
    unittest.main()
