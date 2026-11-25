"""plugins.py: Walkie-Plugin in Claude Code und Codex einmalig eintragen und wieder entfernen."""
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
import plugins  # noqa: E402


class Fake:
    """Simuliert claude/codex: merkt sich Aufrufe, Plugin-Zustand pro Agent."""

    def __init__(self, have=None, fail=()):
        self.calls, self.have, self.fail = [], dict(have or {}), set(fail)

    def run(self, argv):
        self.calls.append(argv)
        agent, verb = argv[0], argv[2:4]
        if tuple(argv[2:]) in self.fail:
            return False, "boom"
        if verb in (["install", plugins.PLUGIN], ["add", plugins.PLUGIN]):
            self.have[agent] = True
        if verb in (["uninstall", plugins.PLUGIN], ["remove", plugins.PLUGIN]):
            self.have[agent] = False
        return True, ""


class PluginsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake = Fake()
        installed = {"claude": lambda: self.fake.have.get("claude", False),
                     "codex": lambda: self.fake.have.get("codex", False)}
        agents = {k: {**v, "installed": installed[k]} for k, v in plugins.AGENTS.items()}
        for p in (patch.object(plugins, "STATE", self.tmp / "plugins.json"),
                  patch.object(plugins, "AGENTS", agents),
                  patch.object(plugins, "_run", side_effect=lambda a: self.fake.run(a)),
                  patch.object(plugins.shutil, "which", side_effect=lambda b: f"/bin/{b}")):
            p.start()
            self.addCleanup(p.stop)

    def test_installs_missing_plugins_once(self):
        self.assertEqual(plugins.ensure(log=lambda m: None), ["Claude Code", "Codex"])
        self.assertIn(["claude", "plugin", "install", plugins.PLUGIN], self.fake.calls)
        self.assertIn(["codex", "plugin", "add", plugins.PLUGIN], self.fake.calls)
        # vom Nutzer wieder entfernt: nicht ungefragt neu eintragen
        self.fake.have.clear()
        self.fake.calls.clear()
        self.assertEqual(plugins.ensure(log=lambda m: None), [])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(plugins.ensure(log=lambda m: None, force=True), ["Claude Code", "Codex"])

    def test_existing_plugin_is_left_alone_and_not_removed(self):
        self.fake.have["claude"] = True
        self.assertEqual(plugins.ensure(log=lambda m: None), ["Codex"])
        self.assertFalse(any(a[0] == "claude" for a in self.fake.calls))
        self.fake.calls.clear()
        plugins.uninstall(log=lambda m: None)
        self.assertEqual({a[0] for a in self.fake.calls}, {"codex"})
        self.assertTrue(self.fake.have["claude"])
        self.assertFalse(self.fake.have["codex"])
        self.assertEqual(json.loads((self.tmp / "plugins.json").read_text()),
                         {"claude": {"by": "user"}})

    def test_failed_install_is_retried_next_start(self):
        self.fake.fail = {("install", plugins.PLUGIN)}
        self.assertEqual(plugins.ensure(log=lambda m: None), ["Codex"])
        self.fake.fail = set()
        self.assertEqual(plugins.ensure(log=lambda m: None), ["Claude Code"])

    def test_missing_agent_is_skipped(self):
        with patch.object(plugins.shutil, "which",
                          side_effect=lambda b: None if b == "codex" else f"/bin/{b}"):
            self.assertEqual(plugins.ensure(log=lambda m: None), ["Claude Code"])
        self.assertNotIn("codex", json.loads((self.tmp / "plugins.json").read_text()))

    def test_unknown_state_changes_nothing(self):
        plugins.AGENTS["claude"]["installed"] = lambda: None
        self.assertEqual(plugins.ensure(log=lambda m: None), ["Codex"])
        self.assertFalse(any(a[0] == "claude" for a in self.fake.calls))


class SourceTest(unittest.TestCase):
    def test_repo_checkout_is_its_own_source(self):
        here = Path("/home/x/walkie")
        with patch.object(plugins, "HERE", here):
            self.assertEqual(plugins.source(), str(here))      # Windows: \\home\\x\\walkie

    def test_plugin_cache_uses_github(self):
        cache = Path.home() / ".claude" / "plugins" / "cache" / "walkie" / "walkie" / "0.3.0"
        with patch.object(plugins, "HERE", cache):
            self.assertEqual(plugins.source(), plugins.GITHUB)

    def test_codex_config_is_read_directly(self):
        home = Path(tempfile.mkdtemp())
        with patch.dict(_os.environ, {"CODEX_HOME": str(home)}):
            self.assertFalse(plugins.codex_installed())
            (home / "config.toml").write_text('[plugins."walkie@walkie"]\nenabled = true\n')
            self.assertTrue(plugins.codex_installed())
            (home / "config.toml").write_text('[plugins."browser@openai"]\nenabled = true\n')
            self.assertFalse(plugins.codex_installed())

    def test_desktop_claude_newest_verified(self):
        appdata = Path(tempfile.mkdtemp())
        root = appdata / "Claude" / "claude-code"
        for ver, verified in (("2.1.9", True), ("2.1.330", True), ("2.1.331", False)):
            d = root / ver / "abc123"
            d.mkdir(parents=True)
            (d / "claude.exe").write_text("")
            if verified:
                (d / ".verified").write_text("")
        (root / "tmp").mkdir()
        with patch.object(plugins.sys, "platform", "win32"), \
                patch.dict(_os.environ, {"APPDATA": str(appdata)}):
            self.assertEqual(plugins.desktop_claude(),
                             str(root / "2.1.330" / "abc123" / "claude.exe"))
            with patch.object(plugins.shutil, "which", return_value=None), \
                    patch.dict(_os.environ, {}, clear=False) as env:
                env.pop("WALKIE_CLAUDE_BIN", None)
                self.assertEqual(plugins._bin("claude"), plugins.desktop_claude())
                self.assertEqual(plugins._bin("codex"), "codex")
        with patch.object(plugins.sys, "platform", "linux"):
            self.assertIsNone(plugins.desktop_claude())


if __name__ == "__main__":
    unittest.main()
