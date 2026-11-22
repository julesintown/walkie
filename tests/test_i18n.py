"""Jeder t("…")-Text im Code hat eine englische Übersetzung, und die Platzhalter passen."""
import ast
import json
import os
import string
import sys
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402
import settings as S  # noqa: E402

SOURCES = ["settings_gui.py", "walkie.py", "keymap.py"]


def t_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("Speech", "t") and node.args):
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                yield node.lineno, a.value


def fields(s):
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def schema_texts():
    yield from S.GROUPS.values()
    for s in S.SCHEMA:
        yield s.title
        if s.help:
            yield s.help
        for _v, text in s.choices:
            if text not in S.VOICES:              # Stimmennamen bleiben, wie sie sind
                yield text


class I18nTest(unittest.TestCase):
    def setUp(self):
        i18n._tables.clear()
        self.en = i18n.table("en")

    def test_json_valid(self):
        for f in (ROOT / "locales" / "en").glob("*.json"):
            with self.subTest(f=f.name):
                data = json.loads(f.read_text(encoding="utf-8"))
                self.assertIsInstance(data, dict)
                for k, v in data.items():
                    self.assertTrue(v.strip(), k)
                    self.assertEqual(fields(k), fields(v), f"Platzhalter: {k!r}")

    def test_code_strings_translated(self):
        missing = []
        for name in SOURCES:
            p = ROOT / name
            if p.exists():
                missing += [f"{name}:{ln}: {s!r}" for ln, s in t_literals(p) if s not in self.en]
        self.assertEqual(missing, [], "\n".join(missing))

    def test_schema_translated(self):
        missing = [s for s in schema_texts() if s not in self.en]
        self.assertEqual(missing, [], "\n".join(missing))

    def test_menu_switch_updates_queued_speech_voice_and_recognizer(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(S, "CONFIG", Path(tmp) / "config.env"), patch.dict(os.environ):
            for key in ("WALKIE_UI_LANG", "WALKIE_LANG", "WALKIE_VOICE"):
                os.environ.pop(key, None)
            S.raw_values(force=True)
            S.set("WALKIE_UI_LANG", "de")
            queued = i18n.Speech("Hier ist {session}.", session="Projekt A")
            for code, expected in [("en", "Here is Projekt A."), ("de", "Hier ist Projekt A.")]:
                S.set("WALKIE_UI_LANG", code)
                self.assertEqual(i18n.render(queued), expected)
                self.assertEqual(S.get("WALKIE_LANG"), code)
                self.assertTrue(S.VOICES[S.get("WALKIE_VOICE")][0].startswith(code + "_"))
                self.assertIn("reply language: " + code, i18n.spoken_prompt("Test"))
        S.raw_values(force=True)

    def test_switch(self):
        os.environ["WALKIE_UI_LANG"] = "en"
        try:
            self.assertEqual(i18n.t("Sprache der Oberfläche"), "Interface language")
            os.environ["WALKIE_UI_LANG"] = "de"
            self.assertEqual(i18n.t("Sprache der Oberfläche"), "Sprache der Oberfläche")
        finally:
            del os.environ["WALKIE_UI_LANG"]


if __name__ == "__main__":
    unittest.main()
