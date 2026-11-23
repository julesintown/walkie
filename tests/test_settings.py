"""Zentrale Einstellungen (settings.py) und das `walkie`-Kommando (cli.py)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["WALKIE_CONFIG"] = str(TMP / "config.env")
os.environ["WALKIE_RUN"] = str(TMP / "run")
sys.path.insert(0, str(ROOT))
import settings as S  # noqa: E402


def env():
    e = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    e.update(WALKIE_CONFIG=str(TMP / "config.env"), WALKIE_RUN=str(TMP / "run"),
             XDG_RUNTIME_DIR=str(TMP), NO_COLOR="1", PYTHONIOENCODING="utf-8")
    return e


def walkie(*args):
    return subprocess.run([sys.executable, str(ROOT / "cli.py"), *args], capture_output=True,
                          encoding="utf-8", env=env(), timeout=20)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        config = patch.object(S, "CONFIG", TMP / "config.env")
        config.start()
        self.addCleanup(config.stop)
        (TMP / "config.env").unlink(missing_ok=True)
        S.raw_values(force=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_defaults_and_types(self):
        self.assertIs(S.get("WALKIE_ANNOUNCE"), True)
        self.assertEqual(S.get("WALKIE_SCALE"), 4)
        self.assertEqual(S.get("WALKIE_KEYS"), S.DEFAULT_KEYS)
        for s in S.SCHEMA:                      # jeder Standard passt zu seinem Typ
            if s.type == "choice":
                self.assertIn(s.default, [c[0] for c in s.choices], s.key)
            self.assertIn(s.group, S.GROUPS)

    def test_roundtrip_and_defaults_not_stored(self):
        S.set("WALKIE_SCALE", 6)
        S.set("WALKIE_KEYS", {"PLAYPAUSE": {"long": "repeat"}})
        S.set("WALKIE_VOICE", "Français · Siwis (féminin)")
        text = (TMP / "config.env").read_text(encoding="utf-8")
        self.assertIn("WALKIE_SCALE=6", text)
        S.raw_values(force=True)
        self.assertEqual(S.get("WALKIE_SCALE"), 6)
        self.assertEqual(S.get("WALKIE_KEYS"), {"PLAYPAUSE": {"long": "repeat"}})
        self.assertEqual(S.get("WALKIE_VOICE"), "Français · Siwis (féminin)")
        S.reset("WALKIE_SCALE")
        self.assertNotIn("WALKIE_SCALE", (TMP / "config.env").read_text(encoding="utf-8"))

    def test_auto_talk_uses_selected_cli_and_honours_explicit_route(self):
        from unittest.mock import patch
        for agent in ("claude", "codex", "gemini", "antigravity", "custom"):
            with patch.dict(os.environ, WALKIE_AGENT=agent, WALKIE_TALK="auto"), \
                    patch.object(S, "has_kitty", return_value=True):
                self.assertEqual(S.talk_terminal(), agent != "claude")
            # Ohne kitty (Windows, WSL) gibt es kein eigenes Terminal: routen statt verlieren
            with patch.dict(os.environ, WALKIE_AGENT=agent, WALKIE_TALK="auto"), \
                    patch.object(S, "has_kitty", return_value=False):
                self.assertFalse(S.talk_terminal())
            with patch.dict(os.environ, WALKIE_AGENT=agent, WALKIE_TALK="route"):
                self.assertFalse(S.talk_terminal())

    def test_validation(self):
        with self.assertRaises(ValueError):
            S.set("WALKIE_SCALE", 99)
        with self.assertRaises(ValueError):
            S.set("WALKIE_SUMMARY_MODEL", "gpt")
        with self.assertRaises(KeyError):
            S.set("WALKIE_GIBTSNICHT", 1)

    def test_env_wins_and_bad_values_fall_back(self):
        os.environ["WALKIE_SCALE"] = "7"
        try:
            self.assertEqual(S.get("WALKIE_SCALE"), 7)
            self.assertTrue(S.overridden("WALKIE_SCALE"))
        finally:
            del os.environ["WALKIE_SCALE"]
        (TMP / "config.env").write_text("WALKIE_SCALE=kaputt\nWALKIE_VOICE='gibt es nicht'\n", encoding="utf-8")
        S.raw_values(force=True)
        self.assertEqual(S.get("WALKIE_SCALE"), 4)
        self.assertEqual(S.get("WALKIE_VOICE"), S.DEFAULT_VOICE)

    def test_live_reload(self):
        S.set("WALKIE_ANSWER_WINDOW", 8)
        (TMP / "config.env").write_text("WALKIE_ANSWER_WINDOW=9\n", encoding="utf-8")
        os.utime(TMP / "config.env", ns=(1, 2))      # andere mtime erzwingen
        S._cache["checked"] = 0
        self.assertEqual(S.get("WALKIE_ANSWER_WINDOW"), 9.0)


class CliTest(unittest.TestCase):
    def setUp(self):
        (TMP / "config.env").unlink(missing_ok=True)

    def test_set_get_reset_short_names(self):
        r = walkie("set", "announce", "aus")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(walkie("get", "WALKIE_ANNOUNCE").stdout.strip(), "0")
        walkie("set", "summary-model", "Sonnet")          # Anzeigename geht auch
        self.assertEqual(walkie("get", "summary_model").stdout.strip(), "sonnet")
        walkie("reset", "announce")
        self.assertEqual(walkie("get", "announce").stdout.strip(), "1")

    def test_errors(self):
        r = walkie("set", "scale", "99")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("2–8", r.stderr)
        r = walkie("set", "gibtsnicht", "1")
        self.assertIn("Unbekannte Einstellung", r.stderr)

    def test_list_json_for_agents(self):
        result = walkie("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        keys = {s["key"] for s in data["settings"]}
        self.assertEqual(keys, set(S.BY_KEY))
        self.assertIn("talk", data["key_actions"])
        voice = next(s for s in data["settings"] if s["key"] == "WALKIE_VOICE")
        self.assertIn(S.DEFAULT_VOICE, voice["choices"])

    def test_keys(self):
        r = walkie("keys", "set", "KEY_PREVIOUSSONG", "long", "deny")
        self.assertEqual(r.returncode, 0, r.stderr)
        keys = json.loads(walkie("get", "keys").stdout)
        self.assertEqual(keys["PREVIOUSSONG"]["long"], "deny")
        self.assertNotEqual(walkie("keys", "set", "PLAYPAUSE", "triple", "talk").returncode, 0)
        walkie("keys", "reset")
        self.assertEqual(json.loads(walkie("get", "keys").stdout), S.DEFAULT_KEYS)

    def test_agent_guide_and_help(self):
        self.assertIn("walkie list --json", walkie("agent-guide").stdout)
        self.assertIn("walkie settings", walkie("help").stdout)


if __name__ == "__main__":
    unittest.main()
