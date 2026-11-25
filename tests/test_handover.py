"""Nutzungslimit einer Claude-Session: erkennen und im Zweitagenten weitermachen (mit Nachfrage)."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import transcripts  # noqa: E402

LIMIT = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit",
         "message": {"content": [{"type": "text", "text": "You've hit your limit"}]}}
ANSWER = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Fertig."}]}}
ASK = {"type": "user", "message": {"content": "Bau den Report"}}


class LimitInTranscript(unittest.TestCase):
    def check(self, *entries):
        root = Path(tempfile.mkdtemp())
        (root / "proj").mkdir()
        (root / "proj" / "S1.jsonl").write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        transcripts._cache.clear()
        with patch.object(transcripts, "PROJECTS", root):
            return transcripts.context("S1")

    def test_session_that_ended_at_its_limit(self):
        c = self.check(ASK, ANSWER, ASK, LIMIT)
        self.assertTrue(c.get("limited"))
        self.assertEqual(c["last_answer"], "Fertig.")          # Fehlermeldung ist kein Stand

    def test_session_that_went_on_after_the_limit(self):
        self.assertFalse(self.check(ASK, LIMIT, ASK, ANSWER).get("limited"))

    def test_other_api_errors_are_no_limit(self):
        other = dict(LIMIT, error="overloaded")
        self.assertFalse(self.check(ASK, other).get("limited"))


if __name__ == "__main__":
    unittest.main()
