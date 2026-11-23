"""Kontextvokabular: Bezeichner aus Repo und Verlauf, konservative Nachkorrektur."""
import isolate  # noqa: F401 – zuerst: nie in die echten Walkie-Ordner
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import vocab  # noqa: E402
from vocab import Term  # noqa: E402

TERMS = [Term("auth middleware", "auth_middleware.py"), Term("uvboot", "uvboot.py"),
         Term("router", "router.py"), Term("settings gui", "settings_gui.py")]


class Correct(unittest.TestCase):
    def test_spoken_identifier_becomes_file_name(self):
        self.assertEqual(vocab.correct("Fix den Fehler in auth middleware.", TERMS),
                         "Fix den Fehler in auth_middleware.py.")
        self.assertEqual(vocab.correct("fix the auth.middleware file", TERMS),
                         "fix the auth_middleware.py file")

    def test_words_heard_apart_are_joined(self):
        self.assertEqual(vocab.correct("check the uv boot script", TERMS),
                         "check the uvboot.py script")

    def test_ordinary_words_stay(self):
        for text in ("yes do it", "the router is fine", "the settings are wrong", "ja"):
            self.assertEqual(vocab.correct(text, TERMS), text)

    def test_fuzzy_match_does_not_swallow_filler_words(self):
        self.assertEqual(vocab.correct("open the setings gui now", TERMS),
                         "open the settings_gui.py now")

    def test_split_words(self):
        self.assertEqual(vocab.split_words("authMiddleware"), "auth middleware")
        self.assertEqual(vocab.split_words("HTTPServer_v2"), "http server v2")


class Terms(unittest.TestCase):
    def test_repo_and_history_terms(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            (Path(d) / "auth_middleware.py").write_text("x")
            (Path(d) / "index.ts").write_text("x")
            subprocess.run(["git", "-C", d, "add", "."], check=True)
            found = vocab.terms({"s": {"project": "shop-api", "cwd": d,
                                       "text": "I updated `paymentService` in billing.ts"}})
        names = [t.canonical for t in found]
        self.assertIn("auth_middleware.py", names)
        self.assertIn("paymentService", names)
        self.assertIn("billing.ts", names)
        self.assertIn("shop-api", names)
        self.assertNotIn("index.ts", names, "Allerweltsnamen helfen Whisper nicht")

    def test_hint_respects_word_budget(self):
        many = [Term(f"name {i}", f"name_{i}.py") for i in range(200)]
        words = vocab.hint(["Walkie"], many, limit=20)
        self.assertEqual(words[0], "Walkie")
        self.assertLessEqual(sum(len(w.split()) for w in words), 20)


if __name__ == "__main__":
    unittest.main()
