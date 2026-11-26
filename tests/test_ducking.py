"""Musik leiser beim Zuhören/Vorlesen und danach genau wie vorher (ohne echte Audiogeräte)."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ducking  # noqa: E402


class FakeBackend(ducking.Backend):
    def __init__(self):
        self.calls = []

    def duck(self, factor):
        self.calls.append(("duck", factor))
        return {"spotify": 1}

    def restore(self, saved):
        self.calls.append(("restore", saved))


def settle(d):
    d.q.put("noop")
    deadline = time.time() + 3
    while not d.q.empty() and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.15)


class DuckerTest(unittest.TestCase):
    def test_duck_once_for_overlapping_reasons_and_restore_after_both(self):
        b = FakeBackend()
        d = ducking.Ducker(lambda: 30, backend=b, delay=0.05)
        d.hold("mic")
        d.hold("speak")
        settle(d)
        self.assertEqual(b.calls, [("duck", 0.3)])
        d.release("mic")
        settle(d)
        self.assertEqual(len(b.calls), 1, "noch spricht der Walkie")
        d.release("speak")
        settle(d)
        self.assertEqual(b.calls[-1], ("restore", {"spotify": 1}))
        d.close()

    def test_short_gap_between_sentences_does_not_restore(self):
        b = FakeBackend()
        d = ducking.Ducker(lambda: 30, backend=b, delay=0.3)
        d.hold("speak")
        settle(d)
        d.release("speak")
        time.sleep(0.05)
        d.hold("speak")
        settle(d)
        time.sleep(0.4)
        self.assertEqual([c[0] for c in b.calls], ["duck"])
        d.close()
        self.assertEqual(b.calls[-1][0], "restore", "beim Beenden immer zurück")

    def test_level_100_means_off(self):
        b = FakeBackend()
        d = ducking.Ducker(lambda: 100, backend=b, delay=0.01)
        d.hold("mic")
        settle(d)
        self.assertEqual(b.calls, [])
        d.close()


class PulseTest(unittest.TestCase):
    def test_lowers_other_apps_and_restores_unless_user_changed_it(self):
        streams = [
            {"index": 7, "corked": False, "properties": {"application.process.id": "111"},
             "volume": {"front-left": {"value": 65536}, "front-right": {"value": 65536}}},
            {"index": 8, "corked": False, "properties": {"application.process.id": "999"},
             "volume": {"mono": {"value": 50000}}},
        ]
        calls = []

        def run(argv, **_kw):
            calls.append(argv[1:])
            out = json.dumps(streams) if "list" in argv else ""
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        with patch("subprocess.run", run):
            p = ducking.Pulse(own_pid=999)
            saved = p.duck(0.25)
            self.assertEqual(list(saved), [7], "eigene Wiedergabe bleibt laut")
            self.assertIn(["set-sink-input-volume", "7", "16384", "16384"], calls)
            streams[0]["volume"] = {"front-left": {"value": 16384}, "front-right": {"value": 16384}}
            p.restore(saved)
            self.assertEqual(calls[-1], ["set-sink-input-volume", "7", "65536", "65536"])
            calls.clear()
            streams[0]["volume"] = {"front-left": {"value": 40000}, "front-right": {"value": 40000}}
            p.restore(saved)
            self.assertFalse([c for c in calls if c[0] == "set-sink-input-volume"],
                             "vom Nutzer verstellt: so lassen")

    def test_own_child_player_stays_loud(self):
        """Beim Bluetooth-Kopfhörer spielt pw-play (Kindprozess) die Stimme ab – nicht drosseln."""
        streams = [
            {"index": 7, "corked": False, "properties": {"application.process.id": "111"},
             "volume": {"mono": {"value": 65536}}},
            {"index": 9, "corked": False, "properties": {"application.process.id": "555"},
             "volume": {"mono": {"value": 65536}}},
            # pw-play meldet keine Prozess-ID, nur die Markierung aus audio.py
            {"index": 10, "corked": False, "properties": {"walkie.own": "true"},
             "volume": {"mono": {"value": 65536}}},
        ]

        def run(argv, **_kw):
            out = json.dumps(streams) if "list" in argv else ""
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        parents = {"555": "999", "111": "42", "42": "1"}
        with patch("subprocess.run", run), \
                patch.object(ducking.Pulse, "_parent", staticmethod(parents.get)):
            saved = ducking.Pulse(own_pid=999).duck(0.3)
        self.assertEqual(list(saved), [7])

    def test_own_players_are_marked(self):
        import audio
        self.assertIn("walkie.own = true", audio.OWN_PW)
        self.assertIn("state.restore-props = false", audio.OWN_PW)
        self.assertEqual(audio.OWN_PACAT, "--property=walkie.own=true")

    def test_stream_ending_while_ducked_gets_its_volume_back(self):
        """Liedwechsel beim Leiserdrehen: PipeWire startet den Nachfolger mit der gemerkten,
        gedrosselten Lautstärke. Der wird mit zurückgedreht – sofort oder beim nächsten Mal."""
        spotify = {"application.name": "spotify", "application.process.id": "111"}
        streams = [{"index": 7, "corked": False, "properties": spotify,
                    "volume": {"mono": {"value": 60000}}}]
        sets = []

        def run(argv, **_kw):
            if "set-sink-input-volume" in argv:
                sets.append(argv[2:])
            out = json.dumps(streams) if "list" in argv else ""
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        with patch("subprocess.run", run):
            p = ducking.Pulse(own_pid=999)
            saved = p.duck(0.5)
            streams[:] = [{"index": 8, "corked": False, "properties": spotify,
                           "volume": {"mono": {"value": 30000}}}]       # Nachfolger, gedrosselt
            sets.clear()
            p.restore(saved)
            self.assertEqual(sets, [["8", "60000"]])

            # Nachfolger kommt erst nach dem Zurückdrehen: beim nächsten Mal die echte Höhe
            streams[0]["volume"] = {"mono": {"value": 60000}}                # wie zurückgedreht
            saved = p.duck(0.5)
            streams[:] = []
            p.restore(saved)
            streams[:] = [{"index": 9, "corked": False, "properties": spotify,
                           "volume": {"mono": {"value": 30000}}}]
            sets.clear()
            saved = p.duck(0.5)
            self.assertEqual(sets, [["9", "30000"]])
            streams[0]["volume"] = {"mono": {"value": 30000}}
            sets.clear()
            p.restore(saved)
            self.assertEqual(sets, [["9", "60000"]])


class WindowsSharedVolumeTest(unittest.TestCase):
    """Spotify/Teams: zwei Sitzungen eines Programms teilen sich eine Lautstärke."""
    def make(self, sessions):
        backend = ducking.WindowsSessions.__new__(ducking.WindowsSessions)
        backend.own = 1
        backend.utils = type("U", (), {"GetAllSessions": staticmethod(lambda: sessions)})
        return backend

    def test_comes_back_to_full_volume_every_time(self):
        class Shared:
            level = 1.0

        class Vol:
            def GetMasterVolume(self):
                return Shared.level

            def SetMasterVolume(self, v, _ctx):
                Shared.level = v

        class Session:
            def __init__(self, ident):
                self.ProcessId, self.Process = 4140, None
                self.InstanceIdentifier, self.SimpleAudioVolume = ident, Vol()

        backend = self.make([Session("a"), Session("b")])
        for _ in range(3):
            saved = backend.duck(0.3)
            self.assertAlmostEqual(Shared.level, 0.3)
            backend.restore(saved)
            self.assertAlmostEqual(Shared.level, 1.0)


if __name__ == "__main__":
    unittest.main()
