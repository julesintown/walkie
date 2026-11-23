"""Ein Adapter je Agent: Ereignis-Übersetzung und Fähigkeiten an einer Stelle."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("WALKIE_CONFIG", str(Path(tempfile.mkdtemp()) / "config.env"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adapters  # noqa: E402
import agents  # noqa: E402
import hook  # noqa: E402


class AdapterTest(unittest.TestCase):
    def test_every_agent_has_an_adapter(self):
        for name in agents.AGENTS:
            self.assertIsNotNone(adapters.get(name), name)
            self.assertIs(agents.AGENTS[name]("", "whisper").adapter, adapters.get(name))

    def test_event_maps_only_produce_common_events(self):
        for a in set(adapters.ADAPTERS.values()):
            for native, common in a.event_map.items():
                self.assertIn(common, adapters.COMMON, f"{a.name}: {native}")
            self.assertTrue(set(a.caps["events"]) <= set(adapters.COMMON), a.name)

    def test_hook_uses_the_adapter_tables(self):
        self.assertEqual(adapters.get("agy").normalize("PreInvocation"), "prompt")
        self.assertIs(hook.GEMINI_EVENTS, adapters.ADAPTERS["gemini"].event_map)
        self.assertEqual(agents.Gemini.EVENTS, tuple(adapters.ADAPTERS["gemini"].event_map))

    def test_matrix_lists_all_agents(self):
        text = adapters.matrix()
        for label in ("Claude Code", "Codex", "Antigravity", "Gemini CLI"):
            self.assertIn(label, text)


if __name__ == "__main__":
    unittest.main()
