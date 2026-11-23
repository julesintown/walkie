"""Hook-Protokoll, Agent-Anbindung, Audio-Fallbacks – nur Standardbibliothek.

    python -m unittest discover -s tests -v
"""
import isolate  # noqa: F401 – zuerst: nie in die echten Walkie-Ordner
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# eigene Einstellungsdatei – nie die echte des Nutzers lesen/schreiben
os.environ["WALKIE_CONFIG"] = str(Path(tempfile.mkdtemp()) / "config.env")


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: v for k, v in os.environ.items()
                    if k != "WALKIE_SESSION" and not k.startswith("CLAUDE")}
        self.env.update(PYTHONIOENCODING="utf-8", WALKIE_UI_LANG="de", WALKIE_RUN=str(self.tmp / "run"),
                        XDG_RUNTIME_DIR=str(self.tmp), WALKIE_CONFIG=str(self.tmp / "config.env"),
                        HOME=str(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hook(self, *args, data=None, own=False):
        env = dict(self.env, **({"WALKIE_SESSION": "1"} if own else {}))
        r = subprocess.run([sys.executable, str(ROOT / "hook.py"), *args],
                           input=json.dumps(data if data is not None else {}),
                           encoding="utf-8", capture_output=True, env=env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def events(self):
        f = self.tmp / "run" / "events.jsonl"
        if not f.exists():
            return []
        return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]

    def test_claude_basic_flow(self):
        for ev in ("ready", "prompt", "tool"):
            self.hook(ev, data={"session_id": "S"})
        self.hook("stop", data={"session_id": "S", "last_assistant_message": "Fertig!"})
        evs = self.events()
        self.assertEqual([e["event"] for e in evs], ["ready", "prompt", "tool", "stop"])
        self.assertEqual(evs[-1]["text"], "Fertig!")
        self.assertTrue(all(e["session"] == "S" and e["agent"] == "claude" for e in evs))

    def test_codex_plugin_hooks_report_as_codex(self):
        for ev in ("ready", "prompt", "tool"):
            self.hook("--plugin-codex", ev, data={"session_id": "C", "turn_id": "t1"})
        self.hook("--plugin-codex", "stop",
                  data={"session_id": "C", "turn_id": "t1", "last_assistant_message": "Done."})
        evs = self.events()
        self.assertEqual([e["event"] for e in evs], ["ready", "prompt", "tool", "stop"])
        self.assertTrue(all(e["agent"] == "codex" and e["session"] == "C" and not e["own"]
                            for e in evs))
        self.assertEqual(evs[-1]["text"], "Done.")

    def test_codex_plugin_silent_in_walkie_own_and_helper_runs(self):
        self.hook("--plugin-codex", "stop", own=True,
                  data={"session_id": "C", "last_assistant_message": "x"})
        self.assertEqual(self.events(), [], "eigenes Terminal meldet über notify, Helfer nie")

    def test_codex_manifest_and_marketplace(self):
        m = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(m["name"], "walkie")
        self.assertEqual(m["hooks"], "./.codex-plugin/hooks.json",
                         "eigene Datei: sonst liest Codex hooks/hooks.json des Claude-Mods")
        hooks_file = json.loads((ROOT / ".codex-plugin" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        for event, hooks in hooks_file.items():
            cmd = hooks[0]["hooks"][0]["command"]
            self.assertIn("bin/walkie-hook", cmd, event)
        launcher = ROOT / "bin" / "walkie-hook"
        self.assertTrue(launcher.is_file())
        if os.name == "posix":
            self.assertTrue(launcher.stat().st_mode & 0o111)
        market = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(market["plugins"][0]["source"], {"source": "local", "path": "./"})
        claude = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(claude["version"], m["version"], "beide Plugins gleiche Version")

    def test_permission_not_doubled(self):
        self.hook("attention", data={"session_id": "S", "tool_name": "Bash"})
        self.hook("attention", data={"session_id": "S", "notification_type": "permission_prompt"})
        self.hook("attention", data={"session_id": "S", "notification_type": "idle_prompt"})
        self.hook("attention", data={"session_id": "S", "notification_type": "agent_needs_input",
                                     "message": "Frage"})
        evs = self.events()
        self.assertEqual([e.get("reason") for e in evs], ["Freigabe nötig: Bash", "Frage"])

    def test_ask_user_question(self):
        self.hook("attention", data={"session_id": "S", "tool_name": "AskUserQuestion"})
        self.assertEqual(self.events()[0]["reason"], "Rückfrage für dich")

    def test_error_and_end_reason(self):
        self.hook("error", data={"session_id": "S", "error_type": "rate_limit"})
        self.hook("end", data={"session_id": "S", "reason": "other"})
        evs = self.events()
        self.assertEqual(evs[0]["reason"], "rate_limit")
        self.assertNotIn("reason", evs[1])

    def test_plugin_silent_in_own_session(self):
        self.hook("--plugin", "prompt", data={"session_id": "S"}, own=True)
        self.assertEqual(self.events(), [])
        self.hook("--plugin", "prompt", data={"session_id": "S"})
        self.assertEqual(self.events()[0]["own"], False)

    def test_voice_flag_only_own_session(self):
        run = self.tmp / "run"
        run.mkdir()
        (run / "voice_pending").touch()
        out = self.hook("--plugin", "prompt", data={"session_id": "other"})
        self.assertEqual(out, "")
        self.assertTrue((run / "voice_pending").exists())
        out = self.hook("prompt", data={"session_id": "S"}, own=True)
        self.assertIn("Mikrofon", out)
        self.assertFalse((run / "voice_pending").exists())
        self.assertTrue(self.events()[-1]["voice"])

    def test_own_stop_reads_transcript(self):
        tr = self.tmp / "t.jsonl"
        tr.write_text("\n".join(json.dumps(x) for x in [
            {"type": "user", "message": {"content": "hi"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Aus dem Transcript"}]}},
        ]), encoding="utf-8")
        self.hook("stop", data={"session_id": "S", "transcript_path": str(tr)}, own=True)
        self.assertEqual(self.events()[0]["text"], "Aus dem Transcript")

    def test_codex_notify(self):
        r = subprocess.run([sys.executable, str(ROOT / "hook.py"), "codex", json.dumps(
            {"type": "agent-turn-complete", "thread-id": "T", "last-assistant-message": "ok"})],
            env=self.env, timeout=20)
        self.assertEqual(r.returncode, 0)
        subprocess.run([sys.executable, str(ROOT / "hook.py"), "codex",
                        json.dumps({"type": "other"})], env=self.env, timeout=20)
        evs = self.events()
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0]["event"], evs[0]["text"], evs[0]["agent"]), ("stop", "ok", "codex"))

    def test_antigravity(self):
        tr = self.tmp / "transcript.jsonl"
        tr.write_text(json.dumps({"role": "user", "content": "x"}) + "\n"
                      + json.dumps({"type": "PLANNER_RESPONSE",
                                    "content": [{"type": "text", "text": "Hallo von agy"}]}) + "\n", encoding="utf-8")
        self.hook("agy", "PreInvocation", data={"conversationId": "C", "invocationNum": 1})
        self.hook("agy", "Stop", data={"conversationId": "C", "fullyIdle": False})
        self.hook("agy", "Stop", data={"conversationId": "C", "fullyIdle": True,
                                       "transcriptPath": str(tr)})
        self.hook("agy", "Unbekannt", data={})
        evs = self.events()
        self.assertEqual([e["event"] for e in evs], ["prompt", "stop"])
        self.assertEqual(evs[1]["text"], "Hallo von agy")
        self.assertEqual(evs[1]["session"], "C")

    def test_gemini(self):
        self.hook("gemini", "BeforeAgent", data={"session_id": "G"})
        self.hook("gemini", "Notification", data={"session_id": "G", "message": "Freigabe?"})
        self.hook("gemini", "AfterAgent", data={"session_id": "G", "prompt_response": "Antwort"})
        evs = self.events()
        self.assertEqual([e["event"] for e in evs], ["prompt", "attention", "stop"])
        self.assertEqual(evs[2]["text"], "Antwort")

    def test_garbage_input(self):
        r = subprocess.run([sys.executable, str(ROOT / "hook.py"), "stop"], input="kein json",
                           encoding="utf-8", env=self.env, timeout=20)
        self.assertEqual(r.returncode, 0)
        r = subprocess.run([sys.executable, str(ROOT / "hook.py"), "codex", "{kaputt"],
                           env=self.env, timeout=20)
        self.assertEqual(r.returncode, 0)


class AgentTest(unittest.TestCase):
    def setUp(self):
        import agents
        self.agents = agents
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = []
        for cls, rel in ((agents.Gemini, ".gemini/settings.json"),
                         (agents.Antigravity, ".gemini/config/hooks.json")):
            self.patches.append((cls, cls.FILE))
            cls.FILE = self.tmp / rel

    def tearDown(self):
        for cls, f in self.patches:
            cls.FILE = f
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_claude_command(self):
        a = self.agents.ClaudeCode("Prompt", "claude")
        cmd = a.command()
        settings = json.loads(cmd[cmd.index("--settings") + 1])
        self.assertIn("PermissionRequest", settings["hooks"])
        self.assertEqual(settings["voice"], {"enabled": True, "mode": "tap"})
        self.assertFalse(settings["hooks"]["UserPromptSubmit"][0]["hooks"][0].get("async"))
        self.assertFalse(settings["hooks"]["Stop"][0]["hooks"][0].get("async"))
        self.assertNotIn("voice", json.loads(
            self.agents.ClaudeCode("P", "whisper").command()[-1]))

    def test_plugin_has_no_python_hooks(self):
        """Das Plugin meldet alles über seinen Mod (plattformneutral) – keine python3-Hooks,
        die unter Windows fehlschlagen würden."""
        cfg = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg, {"modules": ["./main.tsx"]})

    def test_codex_command(self):
        cmd = self.agents.Codex("Sag „hallo“", "claude").command()
        self.assertEqual(cmd[0], "codex")
        self.assertTrue(cmd[2].startswith("notify=["))
        self.assertIn("developer_instructions=", cmd[4])

    def test_gemini_merge_keeps_foreign(self):
        f = self.agents.Gemini.FILE
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"theme": "x", "hooks": {"AfterAgent": [
            {"hooks": [{"type": "command", "command": "mine.sh"}]}]}}), encoding="utf-8")
        g = self.agents.Gemini("", "whisper")
        g.install_hooks()
        g.install_hooks()
        cfg = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(len(cfg["hooks"]["AfterAgent"]), 2)
        self.assertEqual(len(cfg["hooks"]["SessionStart"]), 1)
        self.agents.uninstall()
        self.assertEqual(json.loads(f.read_text(encoding="utf-8")), {"theme": "x", "hooks": {"AfterAgent": [
            {"hooks": [{"type": "command", "command": "mine.sh"}]}]}})

    def test_broken_config_untouched(self):
        f = self.agents.Antigravity.FILE
        f.parent.mkdir(parents=True)
        f.write_text("{kaputt", encoding="utf-8")
        self.assertFalse(self.agents.Antigravity("", "whisper").install_hooks())
        self.assertEqual(f.read_text(encoding="utf-8"), "{kaputt")

    def test_antigravity_merge(self):
        a = self.agents.Antigravity("", "whisper")
        self.assertEqual(a.command(), ["agy"])
        cfg = json.loads(a.FILE.read_text(encoding="utf-8"))
        self.assertEqual(sorted(cfg["walkie"]),
                         ["PostToolUse", "PreInvocation", "SessionStart", "Stop"])
        self.agents.uninstall()
        self.assertEqual(json.loads(a.FILE.read_text(encoding="utf-8")), {})

    def test_custom_and_unknown(self):
        os.environ["WALKIE_AGENT_CMD"] = "aider --model 'x y'"
        try:
            self.assertEqual(self.agents.Agent("", "").command(), ["aider", "--model", "x y"])
        finally:
            del os.environ["WALKIE_AGENT_CMD"]
        os.environ["WALKIE_AGENT"] = "gibtsnicht"
        try:
            with self.assertRaises(RuntimeError):
                self.agents.make_agent("", "")
        finally:
            del os.environ["WALKIE_AGENT"]


class AudioTest(unittest.TestCase):
    def test_fallback_order(self):
        import audio
        backends = [("pw-record", "pw-play"), ("parecord", "pacat"),
                    ("arecord", "aplay"), ("rec", "play")]
        for index, (rec, play) in enumerate([*backends, (None, None)]):
            tools = {cmd: cmd for pair in backends[index:] for cmd in pair}
            with self.subTest(rec=rec, play=play), patch.object(audio.shutil, "which", tools.get):
                r, p = audio.record_cmd("x.wav"), audio.play_cmd(22050)
                self.assertEqual(r[0] if r else None, rec)
                self.assertEqual(p[0] if p else None, play)


class AssetTest(unittest.TestCase):
    def test_voice_tables_match(self):
        import fetch_assets
        import settings
        self.assertIn(settings.DEFAULT_VOICE, settings.VOICES)
        for model, _ in settings.VOICES.values():
            path = fetch_assets.voice_path(model)
            self.assertTrue(path.endswith("/" + model), path)
            self.assertEqual(path.split("/")[1], model.split("-")[0])
        for model in fetch_assets.DEFAULT_VOICES:
            self.assertIn(model, [m for m, _ in settings.VOICES.values()])


class DecisionTest(unittest.TestCase):
    def test_allow_always_sends_updated_input(self):
        import hook
        for tool, inp in [("ExitPlanMode", {"plan": "x"}), ("Bash", {"command": "ls"})]:
            out = hook.decision({"behavior": "allow"}, {"tool_name": tool, "tool_input": inp})
            d = out["hookSpecificOutput"]["decision"]
            self.assertEqual(d, {"behavior": "allow", "updatedInput": inp})
        d = hook.decision({"behavior": "deny", "message": "nö"}, {"tool_input": {}})
        self.assertNotIn("updatedInput", d["hookSpecificOutput"]["decision"])


if __name__ == "__main__":
    unittest.main()
