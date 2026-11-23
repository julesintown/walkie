"""Klettern, Fallen, Fensterkanten (climber.py) und sichtbare Kanten (surfaces.ledges)."""
import isolate  # noqa: F401 – zuerst: nie in die echten Walkie-Ordner
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import climber  # noqa: E402
from surfaces import ledges  # noqa: E402

SCREEN = (0, 0, 1919, 1079)


def env(ledges_=(), win_x=None, idle=True, can=("Climb", "Ceiling", "SitEdge")):
    return {"screen": SCREEN, "floor": 1073, "ledges": list(ledges_), "win_x": win_x or {},
            "idle": idle, "can": set(can), "size": (100, 150)}


def never():
    return 0.99                                   # Zufall: nie spontan etwas tun


class LedgeTest(unittest.TestCase):
    def test_covered_parts_drop_out(self):
        wins = [{"id": "a", "x": 100, "y": 500, "w": 600, "h": 300, "z": 1, "ledge": True},
                {"id": "b", "x": 300, "y": 400, "w": 200, "h": 300, "z": 2, "ledge": True}]
        got = ledges(wins, SCREEN)
        self.assertIn(("a", 100, 300, 500), got)
        self.assertIn(("a", 500, 700, 500), got)
        self.assertIn(("b", 300, 500, 400), got)
        self.assertEqual(len(got), 3)

    def test_fullscreen_and_too_high_are_no_ledges(self):
        wins = [{"id": "f", "x": 0, "y": 0, "w": 1920, "h": 1080, "z": 1, "ledge": False},
                {"id": "t", "x": 0, "y": 50, "w": 800, "h": 300, "z": 2, "ledge": True}]
        self.assertEqual(ledges(wins, SCREEN, min_top=150), [])


class ClimberTest(unittest.TestCase):
    def setUp(self):
        self.c = climber.Climber(rnd=never)

    def run_until(self, e, cond, n=500):
        for _ in range(n):
            self.c.step(e)
            if cond():
                return
        self.fail(f"nicht erreicht, Modus {self.c.mode}")

    def test_falls_onto_window_and_rides_along(self):
        e = env([("w", 400, 900, 600)], {"w": 400})
        self.c.drop(500, 100)
        self.run_until(e, lambda: self.c.mode != "fall")
        self.assertEqual((self.c.mode, self.c.fy), ("ledge", 600))
        self.assertGreater(self.c.landed, climber.BIG_FALL)
        e = env([("w", 450, 950, 620)], {"w": 450})     # Fenster verschoben
        self.c.step(e)
        self.assertEqual((self.c.fx, self.c.fy), (550, 620))

    def test_window_gone_means_falling_to_floor(self):
        self.c.drop(500, 100)
        self.run_until(env([("w", 400, 900, 600)], {"w": 400}), lambda: self.c.mode == "ledge")
        self.run_until(env(), lambda: self.c.mode == "floor")
        self.assertEqual(self.c.fy, 1073)

    def test_misses_window_beside_it(self):
        self.c.drop(100, 100)
        self.run_until(env([("w", 400, 900, 600)], {"w": 400}), lambda: self.c.mode == "floor")

    def test_wall_to_ceiling(self):
        self.c.climb("left", 50, 1000)
        self.c.moving = True
        self.run_until(env(), lambda: self.c.mode == "ceiling", n=2000)
        self.assertEqual((self.c.fy, self.c.dir), (0, 1))

    def test_without_ceiling_lets_go_at_top(self):
        self.c.climb("right", 1870, 1000)
        self.run_until(env(can=("Climb",)), lambda: self.c.mode == "fall", n=2000)
        self.assertIsNone(self.c.fell_from)              # walkie.py setzt die Position neu

    def test_busy_lets_go_of_wall(self):
        self.c.climb("left", 50, 600)
        self.c.step(env(idle=False))
        self.assertEqual(self.c.mode, "fall")

    def test_sits_on_edge_and_gets_up_when_busy(self):
        self.c.drop(500, 599)
        e = env([("w", 400, 900, 600)], {"w": 400})
        self.run_until(e, lambda: self.c.mode == "ledge")
        self.c.rnd = lambda: 0.001
        self.c.step(e)
        self.assertEqual(self.c.mode, "edge")
        self.c.step(env([("w", 400, 900, 600)], {"w": 400}, idle=False))
        self.assertEqual(self.c.mode, "ledge")


if __name__ == "__main__":
    unittest.main()


class JumpTest(unittest.TestCase):
    def test_jumps_in_an_arc_onto_window_and_follows_it(self):
        c = climber.Climber(rnd=never)
        c.jump(100, 1073, 600, 500, "t", 400)
        e = env([("t", 400, 900, 500)], {"t": 400}, idle=False)
        ys = []
        while c.mode == "jump":
            c.step(e)
            ys.append(c.fy)
        self.assertEqual((c.mode, c.win, c.fx, c.fy), ("ledge", "t", 600, 500))
        self.assertLess(min(ys), 500, "Bogen geht über die Kante hinaus")
        self.assertEqual(c.landed, 0)

    def test_target_window_gone_mid_jump_falls(self):
        c = climber.Climber(rnd=never)
        c.jump(100, 1073, 600, 500, "t", 400)
        c.step(env([("t", 400, 900, 500)], {"t": 400}))
        c.step(env())
        self.assertEqual(c.mode, "fall")


class MacWindowsTest(unittest.TestCase):
    def test_quartz_window_list_becomes_ledges(self):
        import os
        import types
        from unittest import mock
        import surfaces
        fake = types.SimpleNamespace(
            kCGWindowListOptionOnScreenOnly=1, kCGWindowListExcludeDesktopElements=16,
            kCGNullWindowID=0,
            CGWindowListCopyWindowInfo=lambda opt, wid: [
                {"kCGWindowLayer": 0, "kCGWindowOwnerPID": 4711, "kCGWindowNumber": 7,
                 "kCGWindowBounds": {"X": 100, "Y": 300, "Width": 800, "Height": 500}},
                {"kCGWindowLayer": 25, "kCGWindowOwnerPID": 1, "kCGWindowNumber": 8,   # Menüleiste
                 "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1920, "Height": 25}},
                {"kCGWindowLayer": 0, "kCGWindowOwnerPID": os.getpid(), "kCGWindowNumber": 9,
                 "kCGWindowBounds": {"X": 0, "Y": 900, "Width": 170, "Height": 170}},   # wir selbst
                {"kCGWindowLayer": 0, "kCGWindowOwnerPID": 42, "kCGWindowNumber": 10,
                 "kCGWindowBounds": {"X": 0, "Y": 200, "Width": 1500, "Height": 700}}])
        with mock.patch.dict("sys.modules", {"Quartz": fake}):
            wins = surfaces._mac_window_list()
        self.assertEqual([w["pid"] for w in wins], [4711, 42])
        self.assertGreater(wins[0]["z"], wins[1]["z"], "vorderstes zuerst")
        got = ledges(wins, SCREEN)
        self.assertIn(("7", 100, 900, 300), got)
        self.assertIn(("10", 0, 1500, 200), got, "Oberkante liegt über dem vorderen Fenster")
