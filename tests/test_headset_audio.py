import json
import time
import unittest
from unittest.mock import Mock, patch

import headset_audio as audio


class PlaybackTest(unittest.TestCase):
    def test_connected_headset_never_opens_default_during_profile_switch(self):
        import audio as playback
        target = "bluez_output.AA_BB.1"
        cards = json.dumps([{"name": "bluez_card.AA_BB"}])
        for sinks in ([{"name": "speakers"}, {"name": target}], [{"name": "speakers"}]):
            with patch.object(playback.sys, "platform", "linux"), patch.object(
                    playback.shutil, "which", side_effect=lambda name: name), patch.object(
                    audio, "pactl", side_effect=[cards, json.dumps(sinks), "speakers"]), patch.object(
                    playback, "miniaudio") as mini, patch.object(playback.subprocess, "Popen") as spawn:
                player = playback.Player(22050)
                mini.PlaybackDevice.assert_not_called()
                if len(sinks) == 2:
                    self.assertIn(target, spawn.call_args.args[0])
                else:
                    spawn.assert_not_called()
                    self.assertFalse(player.ok)


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.card = {"name": "bluez_card.AA_BB", "active_profile": "a2dp-sink-sbc",
                     "profiles": {"headset-head-unit": {"available": "yes"}},
                     "properties": {"device.description": "Headset"}}
        self.other = dict(self.card, name="bluez_card.CC_DD", active_profile="headset-head-unit")
        self.streams = []
        self.sink = "bluez_output.AA:BB.1"
        self.writes = []
        self.manager = audio.HeadsetAudio(Mock(), Mock())
        self.mock = patch.object(audio, "pactl", self.pactl)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def pactl(self, *args):
        if args == ("get-default-sink",):
            return self.sink
        if args[:3] == ("-f", "json", "list"):
            return json.dumps({"cards": [self.other, self.card], "source-outputs": self.streams,
                               "sources": [{"name": "bluez_input.AA:BB.0", "index": 7}]}[args[3]])
        self.assertEqual(args[:2], ("set-card-profile", self.card["name"]))
        self.writes.append(args[2])
        self.card["active_profile"] = args[2]

    def test_scoped_profile_and_overlapping_recordings(self):
        for owner in ("dictation", "settings"):
            self.assertEqual(self.manager.prepare(owner, None), "bluez_input.AA:BB.0")
        self.manager.release("dictation")
        self.assertEqual(self.writes, ["headset-head-unit"])
        self.streams = [{"source": 7, "corked": False}]
        self.manager.release("settings")
        self.assertEqual(self.writes, ["headset-head-unit"])
        self.streams.clear()
        self.manager._restore()
        self.assertEqual(self.writes, ["headset-head-unit", "a2dp-sink-sbc"])

    def test_leftover_headset_profile_returns_to_a2dp(self):
        self.card["active_profile"] = "headset-head-unit"
        self.card["profiles"] = {"headset-head-unit": {"available": "yes"},
                                 "a2dp-sink": {"available": "yes"}}
        self.assertEqual(self.manager.prepare("talk", None), "bluez_input.AA:BB.0")
        self.assertEqual(self.writes, [])
        self.manager.release("talk")
        self.assertEqual(self.writes, ["a2dp-sink"])

    def test_usb_default_and_ambiguous_name_leave_cards_alone(self):
        self.sink = "alsa_output.speaker"
        for mic in (None, "USB Mic", "Headset"):
            self.assertEqual(self.manager.prepare(object(), mic), mic)
        self.manager._restore()
        self.assertEqual(self.writes, [])

    def test_user_profile_change_wins(self):
        self.manager.prepare(1, None)
        self.card["active_profile"] = "off"
        self.manager.release(1)
        self.assertEqual(self.writes, ["headset-head-unit"])

    def test_shutdown_waits_for_profile_restore(self):
        self.manager.prepare("dictation", None)
        original = self.manager._restore

        def slow_restore():
            time.sleep(0.3)
            original()

        self.manager._restore = slow_restore
        self.manager.close()
        self.assertEqual(self.writes, ["headset-head-unit", "a2dp-sink-sbc"])
        self.assertIsNone(self.manager.prepare("late", None))
