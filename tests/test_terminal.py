"""Terminal: normales Fenster des Standard-Terminals, Gespräch fortsetzen."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import os  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agents  # noqa: E402
import paths  # noqa: E402


def only(*names):
    return lambda name, path=None: f"/usr/bin/{name}" if name in names else None


class DefaultTerminalTest(unittest.TestCase):
    def test_terminal_env_wins(self):
        with patch.dict(os.environ, TERMINAL="alacritty", XDG_CURRENT_DESKTOP="KDE"), \
                patch("shutil.which", only("alacritty", "konsole")):
            self.assertEqual(paths.linux_terminal(["claude"], "/w"),
                             ["alacritty", "--working-directory", "/w", "-e", "claude"])

    def test_desktop_default(self):
        cases = {"KDE": (["konsole"], ["konsole", "--nofork", "--workdir", "/w", "-e", "claude"]),
                 "XFCE": (["xfce4-terminal"], ["xfce4-terminal", "--disable-server",
                                               "--working-directory=/w", "-x", "claude"]),
                 "ubuntu:GNOME": (["gnome-terminal"], ["gnome-terminal", "--wait",
                                                        "--working-directory=/w", "--", "claude"])}
        for desktop, (installed, expected) in cases.items():
            with patch.dict(os.environ, XDG_CURRENT_DESKTOP=desktop, TERMINAL=""), \
                    patch("shutil.which", only(*installed, "kitty", "xterm")):
                self.assertEqual(paths.linux_terminal(["claude"], "/w"), expected, desktop)

    def test_desktop_from_processes_when_env_is_missing(self):
        with patch.dict(os.environ, XDG_CURRENT_DESKTOP="", TERMINAL=""), \
                patch.object(paths, "running_desktop", return_value=["xfce"]), \
                patch("shutil.which", only("xfce4-terminal", "kitty")):
            self.assertEqual(paths.linux_terminal(["agy"], "/w")[0], "xfce4-terminal")

    def test_nothing_found(self):
        with patch.dict(os.environ, XDG_CURRENT_DESKTOP="", TERMINAL=""), \
                patch.object(paths, "running_desktop", return_value=[]), \
                patch("shutil.which", only()):
            self.assertIsNone(paths.linux_terminal(["claude"], "/w"))


class ResumeTest(unittest.TestCase):
    def test_claude_fixed_id_then_resume_once_a_transcript_exists(self):
        a = agents.ClaudeCode("", "whisper")
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, CLAUDE_CONFIG_DIR=d):
            self.assertEqual(a.terminal_command("abc", resume=False)[1:], ["--session-id", "abc"])
            self.assertEqual(a.terminal_command("abc", resume=True)[1:], ["--session-id", "abc"],
                             "noch kein Transcript: --resume würde scheitern")
            (Path(d) / "projects" / "home").mkdir(parents=True)
            (Path(d) / "projects" / "home" / "abc.jsonl").write_text("{}")
            self.assertEqual(a.terminal_command("abc", resume=True)[1:], ["--resume", "abc"])

    def test_codex_and_antigravity(self):
        c = agents.Codex("", "whisper")
        self.assertEqual(c.terminal_command(None, False)[1:], [])
        self.assertEqual(c.terminal_command(None, True)[1:], ["resume", "--last"])
        self.assertEqual(c.terminal_command("t1", True)[1:], ["resume", "t1"])
        g = agents.Antigravity("", "whisper")
        with patch.object(agents.Antigravity, "install_hooks", return_value=True):
            self.assertEqual(g.terminal_command(None, True)[1:], ["--continue"])
            self.assertEqual(g.terminal_command("conv", True)[1:], ["--conversation", "conv"])


if __name__ == "__main__":
    unittest.main()
