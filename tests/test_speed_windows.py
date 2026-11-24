"""Faster answers, hidden helper windows on Windows, window sources and the language menu."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import audio  # noqa: E402
import paths  # noqa: E402
import router  # noqa: E402
import settings as S  # noqa: E402
import surfaces  # noqa: E402

SESS = {"A": {"project": "walkie", "cwd": "/x/walkie", "user_ts": 2}}


class RouterAnswersSmallTalk(unittest.TestCase):
    def test_self_with_reply_returns_it(self):
        with mock.patch.object(router, "ask_model", lambda *a, **k:
                               '{"target": "self", "message": "Hörst du mich?", '
                               '"reply": "Ja, ich höre dich gut."}'):
            self.assertEqual(router.understand("Hörst du mich?", SESS),
                             ("self", "Ja, ich höre dich gut.", "Hörst du mich?"))

    def test_self_without_reply_needs_a_second_call(self):
        with mock.patch.object(router, "ask_model", lambda *a, **k:
                               '{"target": "self", "message": "Wetter morgen", "reply": ""}'):
            self.assertEqual(router.understand("Wie wird das Wetter?", SESS)[:2], ("self", None))


class LeanModelCalls(unittest.TestCase):
    def test_claude_skips_mcp_servers_and_skills(self):
        seen = {}

        def run(argv, **kw):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, "ok", "")
        with mock.patch.object(router, "_run", run):
            router._claude(["--model", "haiku"], "hi", None, None, 5)
        self.assertIn("--strict-mcp-config", seen["argv"])
        self.assertIn("--disable-slash-commands", seen["argv"])

    def test_old_claude_without_the_flags_still_works(self):
        self.assertEqual(router._without_newer_flags(["--model", "haiku", *router.LEAN]),
                         ["--model", "haiku"])

    def test_windows_runs_helpers_without_console(self):
        with mock.patch.object(paths, "WIN", True), \
                mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            self.assertEqual(paths.no_window(), {"creationflags": 0x08000000})
        with mock.patch.object(paths, "WIN", False):
            self.assertEqual(paths.no_window(), {})
        seen = {}
        with mock.patch.object(paths, "no_window", lambda: {"creationflags": 8}), \
                mock.patch.object(subprocess, "run", lambda argv, **kw: seen.update(kw)):
            router._run(["true"])
        self.assertEqual(seen.get("creationflags"), 8)


class EarlyTranscription(unittest.TestCase):
    def test_copy_wav_keeps_only_the_part_before_okay(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "a.wav", Path(tmp) / "b.wav"
            src.write_bytes(audio._wav_header() + bytes(range(100)) * 10)
            audio.copy_wav(src, dst, 301)
            data = dst.read_bytes()
            self.assertEqual(len(data), 44 + 300)
            self.assertEqual(data[44:], (bytes(range(100)) * 10)[:300])


class WindowSources(unittest.TestCase):
    def test_full_screen_windows_are_no_ledges(self):
        wins = surfaces._with_ledges([{"w": 1920, "h": 1080}, {"w": 800, "h": 600}], 1920, 1080)
        self.assertEqual([w["ledge"] for w in wins], [False, True])

    def test_scale_from_physical_pixels(self):
        s = surfaces.Surfaces()
        s.qt_width = 2560
        got = s._scale([{"x": -2560, "y": 0, "w": 1280, "h": 800}], -2560, 0, 5120)
        self.assertEqual((got[0]["x"], got[0]["w"], got[0]["h"]), (0, 640, 400))

    def test_wsl_finds_the_terminal_by_title(self):
        s = surfaces.Surfaces()
        s.backend = "wsl"
        s.wins = [{"id": "1", "z": 1, "title": "julian@pc: ~/walkie"},
                  {"id": "2", "z": 3, "title": "walkie – Claude Code"},
                  {"id": "3", "z": 5, "title": "Teams"}]
        self.assertEqual(s.window_of(4711, names=("walkie",))["id"], "2")
        self.assertIsNone(s.window_of(4711, names=("shop",)))

    def test_powershell_script_is_encoded_as_utf16(self):
        import base64
        self.assertEqual(base64.b64decode(surfaces.ps_encoded("Ä")).decode("utf-16-le"), "Ä")


class LanguageMenu(unittest.TestCase):
    def test_language_is_a_choice_with_automatic(self):
        s = S.BY_KEY["WALKIE_LANG"]
        self.assertEqual(s.type, "choice")
        self.assertIn("auto", [c[0] for c in s.choices])
        with mock.patch.dict(os.environ, WALKIE_LANG="auto"):
            self.assertIsNone(S.stt_language())
        with mock.patch.dict(os.environ, WALKIE_LANG="fr"):
            self.assertEqual(S.stt_language(), "fr")


if __name__ == "__main__":
    unittest.main()
