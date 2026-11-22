"""Unterbrechen durch Reden: Stopp-Wörter, Echo, Füllwörter."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from barge import decide, looks_like_headphones  # noqa: E402

SAID = "Die Tests sind grün und ich habe den Build-Ordner aufgeräumt, soll ich committen?"


class BargeTest(unittest.TestCase):
    def test_stop_words_cut(self):
        self.assertEqual(decide("Stopp!", SAID), "stop")
        self.assertEqual(decide("warte mal kurz", SAID), "stop")

    def test_own_voice_is_echo(self):
        self.assertIsNone(decide("die Tests sind grün und ich habe", SAID))
        self.assertIsNone(decide("Halt", "Halt, bevor ich weitermache: der Server läuft."),
                          "Stopp-Wort, das er selbst sagt, ist Echo")

    def test_backchannel_is_ignored(self):
        self.assertIsNone(decide("ja okay mhm", SAID))

    def test_real_talk_cuts(self):
        self.assertEqual(decide("nein mach lieber erst den Server neu", SAID), "stop")

    def test_headphone_names(self):
        self.assertTrue(looks_like_headphones("bluez_output.2C_4D.1"))
        self.assertTrue(looks_like_headphones("AirPods Pro"))
        self.assertFalse(looks_like_headphones("alsa_output.pci-0000_00_1b.0.analog-stereo"))
