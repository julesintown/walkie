"""„Was habe ich verpasst?“ – Überblick nach Dringlichkeit."""
import isolate  # noqa: F401 – zuerst: nie in die echten Walkie-Ordner
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import digest  # noqa: E402

NOW = 10_000.0


def ev(event, sid, ts, **kw):
    return {"event": event, "session": sid, "ts": ts, **kw}


class DigestTest(unittest.TestCase):
    def test_needs_you_first_then_working_then_done(self):
        log = digest.Timeline()
        log.add(ev("stop", "a", 0, project="dashboard",
                   text="Alle Tests sind grün. Soll ich committen?"), now=NOW - 300)
        log.add(ev("tool", "c", 0, project="codex-bug", tool="Bash"), now=NOW - 30)
        log.add(ev("attention", "b", 0, project="backend"), now=NOW - 60)
        text = digest.summary(log.since(0), {"c": {"state": "thinking"}, "a": {"state": "idle"}},
                              {"b": "Freigabe nötig: Bash"}, now=NOW)
        self.assertTrue(text.startswith("3 Sessions haben sich gemeldet."), text)
        self.assertLess(text.index("backend wartet auf dich"), text.index("codex-bug arbeitet"))
        self.assertLess(text.index("codex-bug arbeitet noch (Bash)"), text.index("dashboard"))
        self.assertIn("dashboard ist fertig, vor 5 Minuten: Alle Tests sind grün.", text)

    def test_watermark_only_new_events(self):
        log = digest.Timeline()
        log.add(ev("stop", "a", 0, project="alt", text="Fertig."), now=NOW - 100)
        log.add(ev("stop", "b", 0, project="neu", text="Auch fertig."), now=NOW - 10)
        text = digest.summary(log.since(NOW - 50), {}, {}, now=NOW)
        self.assertIn("neu", text)
        self.assertNotIn("alt", text)

    def test_nothing_new(self):
        self.assertIn("Nichts Neues", digest.summary([], {}, {}, now=NOW))
        self.assertIn("Nothing new", digest.summary([], {}, {}, now=NOW, lang="en"))

    def test_error_after_last_answer(self):
        log = digest.Timeline()
        log.add(ev("stop", "a", 0, project="api", text="Ok."), now=NOW - 100)
        log.add(ev("error", "a", 0, project="api", reason="rate_limit"), now=NOW - 50)
        self.assertIn("api hatte einen Fehler: rate_limit.", digest.summary(log.since(0), {}, {}, now=NOW))

    def test_first_sentence_strips_markdown_and_code(self):
        self.assertEqual(digest.first_sentence("**Done.** ```x = 1``` More text."), "Done.")

    def test_is_request(self):
        for s in ("Was habe ich verpasst?", "Okay, was hab ich verpasst", "what did I miss",
                  "Walkie, gib mir einen Überblick", "Status update please", "Wie ist der Stand?"):
            self.assertTrue(digest.is_request(s), s)
        for s in ("Fix den Status der Bestellung im Shop", "Was ist in der auth middleware los "
                  "und warum schlagen die Tests fehl", "ja"):
            self.assertFalse(digest.is_request(s), s)


if __name__ == "__main__":
    unittest.main()
