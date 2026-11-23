"""Überblick: der Code sammelt Fakten, das Modell formuliert."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import digest  # noqa: E402

import json  # noqa: E402

NOW = 10_000.0


def ev(event, sid, **kw):
    return {"event": event, "session": sid, **kw}


def timeline(*items):
    log = digest.Timeline()
    for e, ts in items:
        log.add(e, now=ts)
    return log.all()


class CollectTest(unittest.TestCase):
    def test_facts_urgent_and_new_first(self):
        events = timeline(
            (ev("prompt", "a", project="dashboard", prompt="Fix the charts"), NOW - 900),
            (ev("stop", "a", project="dashboard", text="All tests pass. Commit?"), NOW - 300),
            (ev("tool", "c", project="codex-bug", tool="Bash"), NOW - 30),
            (ev("attention", "b", project="backend"), NOW - 60))
        facts = digest.collect(events, 0, {"c": {"state": "thinking"}},
                               {"b": "Freigabe nötig: Bash"}, now=NOW)
        self.assertEqual([f["status"] for f in facts], ["waiting_for_user", "finished", "working"])
        self.assertEqual(facts[0]["waiting_for"], "Freigabe nötig: Bash")
        self.assertEqual(facts[1]["task"], "Fix the charts")
        self.assertEqual(facts[1]["finished_seconds_ago"], 300)
        self.assertEqual(facts[2]["current_tool"], "Bash")

    def test_old_sessions_stay_in_the_facts_but_not_as_news(self):
        events = timeline((ev("stop", "a", project="alt", text="Fertig."), NOW - 100),
                          (ev("stop", "b", project="neu", text="Auch fertig."), NOW - 10))
        facts = digest.collect(events, NOW - 50, {}, {}, now=NOW)
        news = {f["session"]: f["news_since_last_overview"] for f in facts}
        self.assertEqual(news, {"neu": True, "alt": False}, "Projektstand braucht auch Altes")
        self.assertEqual(facts[0]["session"], "neu")

    def test_known_sessions_contribute_task_and_answer(self):
        facts = digest.collect([], NOW, {}, {}, known={"k": {
            "project": "shop", "first_prompt": "Checkout redesign", "text": "CSS done."}}, now=NOW)
        self.assertEqual(facts[0]["task"], "Checkout redesign")
        self.assertEqual(facts[0]["last_answer"], "CSS done.")

    def test_error_after_last_answer(self):
        events = timeline((ev("stop", "a", project="api", text="Ok."), NOW - 100),
                          (ev("error", "a", project="api", reason="rate_limit"), NOW - 50))
        f = digest.collect(events, 0, {}, {}, now=NOW)[0]
        self.assertEqual((f["status"], f["error"]), ("error", "rate_limit"))


class OverviewTest(unittest.TestCase):
    def test_model_gets_the_request_and_all_facts(self):
        seen = []
        facts = [{"session": "shop", "status": "finished", "news_since_last_overview": False,
                  "last_answer": "CSS done."}]
        out = digest.overview("Wie ist der Projektstand im Shop?", facts, "de",
                              ask=lambda prompt: seen.append(prompt) or "Der Shop ist fertig.")
        self.assertEqual(out, "Der Shop ist fertig.")
        self.assertIn("Wie ist der Projektstand im Shop?", seen[0])
        self.assertIn(json.dumps(facts, ensure_ascii=False), seen[0])
        self.assertIn("Playback language: de", seen[0])

    def test_without_model_a_short_fixed_summary(self):
        facts = [{"session": "api", "status": "waiting_for_user", "news_since_last_overview": True,
                  "waiting_for": "Freigabe nötig: Bash"}]
        self.assertEqual(digest.overview("", facts, "de"), "api wartet auf dich: Freigabe nötig: Bash.")

        def broken(_prompt):
            raise RuntimeError("usage limit")
        self.assertIn("api", digest.overview("", facts, "en", ask=broken))
        self.assertEqual(digest.overview("", [], "en"), "Nothing new.")

    def test_no_phrase_lists_in_code(self):
        """Ob jemand einen Überblick will, erkennt der Router (Modell) – kein Regex hier."""
        self.assertFalse(hasattr(digest, "is_request"))


if __name__ == "__main__":
    unittest.main()
