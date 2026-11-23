"""Sprechwarteschlange mit Vorrang (Idee aus heard)."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import speechq  # noqa: E402
from speechq import NORMAL, ROUTINE, URGENT, SpeechQueue  # noqa: E402


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


class SpeechQueueTest(unittest.TestCase):
    def test_priority_then_order(self):
        q = SpeechQueue()
        q.put("api fertig", ROUTINE)
        q.put("shop braucht dich", NORMAL)
        q.put(("ask", "r1"))
        q.put("web fertig", ROUTINE)
        q.put("Hab nichts verstanden.")
        self.assertEqual(drain(q), [("ask", "r1"), "Hab nichts verstanden.", "shop braucht dich",
                                    "api fertig", "web fertig"])

    def test_newer_done_replaces_older_of_same_session(self):
        q = SpeechQueue()
        q.put("api fertig: Tests rot", ROUTINE, key=("done", "A"))
        q.put("web fertig", ROUTINE, key=("done", "B"))
        q.put("api fertig: Tests grün", ROUTINE, key=("done", "A"))
        self.assertEqual(drain(q), ["web fertig", "api fertig: Tests grün"])

    def test_full_queue_drops_oldest_routine_first(self):
        q = SpeechQueue()
        for i in range(speechq.MAX):
            q.put(f"r{i}", ROUTINE)
        q.put("wichtig", NORMAL)
        got = drain(q)
        self.assertEqual(got[0], "wichtig")
        self.assertNotIn("r0", got)
        self.assertEqual(len(got), speechq.MAX)

    def test_interrupted_goes_back_to_the_front(self):
        q = SpeechQueue()
        q.put(("ask", "r2"))
        q.push_front("abgebrochener Satz")
        self.assertEqual(q.get(timeout=1), "abgebrochener Satz")
