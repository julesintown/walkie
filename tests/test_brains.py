"""Denkmodelle des Walkies: auch ohne Claude Code (z. B. nur agy unter Windows)."""
import isolate  # noqa: F401 – zuerst: nie in die echten Walkie-Ordner
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("WALKIE_CONFIG", str(TMP / "config.env"))   # nie die echte Konfiguration
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agents  # noqa: E402
import router  # noqa: E402


def which_only(*names):
    return lambda name, path=None: f"/bin/{name}" if name in names else None


class BrainOrder(unittest.TestCase):
    def test_only_antigravity_installed(self):
        with patch.dict(os.environ, WALKIE_AGENT="antigravity", WALKIE_BRAIN="auto"), \
                patch("shutil.which", which_only("agy")):
            self.assertEqual(router.brains(), ["antigravity"])

    def test_primary_agent_first_then_others(self):
        with patch.dict(os.environ, WALKIE_AGENT="gemini", WALKIE_BRAIN="auto"), \
                patch("shutil.which", which_only("claude", "gemini", "codex")):
            self.assertEqual(router.brains(), ["gemini", "claude", "codex"])

    def test_explicit_brain_only(self):
        with patch.dict(os.environ, WALKIE_AGENT="claude", WALKIE_BRAIN="codex"), \
                patch("shutil.which", which_only("claude", "codex")):
            self.assertEqual(router.brains(), ["codex"])

    def test_print_mode_passes_prompt_as_argument_and_silences_hooks(self):
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"], seen["env"] = argv, kw["env"]
            return subprocess.CompletedProcess(argv, 0, stdout="pong\n", stderr="")
        with patch("subprocess.run", fake_run), patch("shutil.which", which_only("agy")):
            self.assertEqual(router._print_mode("antigravity", "ping", {"PATH": "/bin"}, None, 5),
                             "pong")
        self.assertEqual(seen["argv"], ["/bin/agy", "-p", "ping"])
        self.assertEqual(seen["env"]["WALKIE_HOOK_QUIET"], "1")

    def test_no_brain_raises_readable_error(self):
        with patch("shutil.which", which_only()):
            with self.assertRaisesRegex(RuntimeError, "agy"):
                router.ask_model("x", {"PATH": ""}, None, 5)


class AgentCommands(unittest.TestCase):
    def test_antigravity_can_open_a_session_with_a_task(self):
        argv = agents.Antigravity("", "whisper").new_session("fix the tests")
        self.assertEqual(argv[1:], ["--prompt-interactive", "fix the tests"])

    def test_windows_hook_command_uses_double_quotes(self):
        with patch.object(agents.sys, "platform", "win32"):
            cmd = agents.shell_join([r"C:\Program Files\Python\python.exe", r"C:\walkie\hook.py"])
        self.assertEqual(cmd, r'"C:\Program Files\Python\python.exe" C:\walkie\hook.py')
        self.assertNotIn("'", cmd)


if __name__ == "__main__":
    unittest.main()
