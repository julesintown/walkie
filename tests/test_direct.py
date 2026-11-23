"""Direct mode, show and new sessions: the router model decides, the code only follows it."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import router  # noqa: E402

S = {"A": {"project": "claude-walkie", "cwd": "/x/claude-walkie", "user_ts": 2},
     "B": {"project": "shop", "cwd": "/x/shop", "user_ts": 1}}


def model(answer):
    return mock.patch.object(router, "ask_model", lambda *a, **k: answer)


class DirectTest(unittest.TestCase):
    def test_enter_with_task(self):
        with model('{"target": "direct", "session": "B", "message": "Run the tests"}'):
            self.assertEqual(router.understand("Talk only to the shop now, run the tests", S),
                             ("direct", "B", "Run the tests"))

    def test_enter_unknown_session_is_not_guessed(self):
        with model('{"target": "direct", "session": "ZZ"}'):
            kind, target, _ = router.understand("Nur noch mit Foo reden", S)
        self.assertEqual((kind, target), ("session", "A"))

    def test_end_only_when_active(self):
        with model('{"target": "direct_end"}'):
            self.assertEqual(router.understand("back to normal", S, direct="B")[:2],
                             ("direct_end", None))
            self.assertEqual(router.understand("back to normal", S)[0], "session")

    def test_direct_session_wins_without_model(self):
        with mock.patch.object(router, "ask_model", side_effect=OSError("offline")):
            self.assertEqual(router.understand("Mach weiter", S, direct="B")[:2], ("session", "B"))

    def test_show(self):
        with model('{"target": "show", "session": "B"}'):
            self.assertEqual(router.understand("Zeig mir den Shop", S), ("show", "B", ""))
        with model('{"target": "show", "session": ""}'):
            self.assertEqual(router.understand("show me that", S), ("show", None, ""))


class NewSessionGuardTest(unittest.TestCase):
    def test_model_new_without_wish_or_folder_is_rejected(self):
        s = {"A": {"project": "claude-walkie", "cwd": "/x/a", "user_ts": 1}}
        out = '{"target": "new", "folder": "music-widget"}'
        with model(out), \
                mock.patch.object(router, "project_dirs", lambda: [Path("/home/x/music-widget")]):
            self.assertEqual(router.route("Okay, wir werden das Set anroben.", s),
                             ("session", "A"), "verhörter Satz öffnet keine neue Session")
            self.assertEqual(router.route("Mach im music widget weiter mit dem Player", s)[0],
                             "new", "genannter Ordner: ja")

    def test_no_new_session_without_model(self):
        with mock.patch.object(router, "ask_model", side_effect=OSError("offline")):
            self.assertEqual(router.route("Open a new session", S)[0], "session")


class AgentChoiceTest(unittest.TestCase):
    def test_secondary_only_when_configured(self):
        out = '{"target": "new", "explicit": true, "agent": "secondary", "message": "Fix it"}'
        with model(out):
            self.assertEqual(router.understand("Ask Codex to fix it", S,
                                               agents=("Claude Code", "Codex")),
                             ("new_secondary", None, "Fix it"))
            self.assertEqual(router.understand("Ask Codex to fix it", S,
                                               agents=("Claude Code", None))[0], "new")

    def test_primary_by_default(self):
        with model('{"target": "new", "explicit": true, "message": "Rezept"}'):
            self.assertEqual(router.understand("Neue Session: Rezept", S,
                                               agents=("Claude Code", "Codex"))[0], "new")


class BrainTest(unittest.TestCase):
    def setUp(self):
        import settings
        self.settings = settings
        self.env = {"PATH": str(Path(__file__).parent)}           # no real CLIs needed

    def brains(self, brain, agent, installed):
        with mock.patch.object(self.settings, "get", lambda k, d=None: {
                "WALKIE_BRAIN": brain, "WALKIE_AGENT": agent}.get(k, d)), \
                mock.patch("shutil.which", lambda name, path=None: name if name in installed
                           else None):
            return router.brains(self.env)

    def test_primary_agent_first_then_the_other(self):
        self.assertEqual(self.brains("auto", "codex", {"codex", "claude"}), ["codex", "claude"])
        self.assertEqual(self.brains("auto", "claude", {"codex", "claude"}), ["claude", "codex"])
        self.assertEqual(self.brains("auto", "gemini", {"codex"}), ["codex"])
        self.assertEqual(self.brains("codex", "claude", {"codex", "claude"}), ["codex"])
        self.assertEqual(self.brains("auto", "claude", set()), [])

    def test_falls_back_when_the_first_brain_fails(self):
        calls = []
        with mock.patch.object(router, "brains", lambda env=None: ["codex", "claude"]), \
                mock.patch.object(router, "_codex", side_effect=RuntimeError("usage limit")), \
                mock.patch.object(router, "_claude",
                                  lambda args, *a, **k: calls.append(args) or '{"ok": 1}'):
            self.assertEqual(router.ask_model("p", None, None, 5), '{"ok": 1}')
            self.assertEqual(router.ask_model("p", None, None, 5), '{"ok": 1}')
            self.assertEqual(router._codex.call_count, 1, "ausgefallenes Modell erst später wieder")
        self.assertEqual(len(calls), 2)
        router._brain_down.clear()
        with mock.patch.object(router, "brains", lambda env=None: []):
            with self.assertRaises(RuntimeError):
                router.ask_model("p", None, None, 5)
