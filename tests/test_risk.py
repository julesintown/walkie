"""Riskante Befehle: zweites Ja per Stimme, per Taste gar nicht (Idee aus GodTerm)."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk import code_heard, critical, new_code, risky  # noqa: E402


class RiskTest(unittest.TestCase):
    def test_dangerous(self):
        for cmd in ("rm -rf build", "rm -r foo", "git push --force origin main", "git push -f",
                    "git reset --hard HEAD~1", "git clean -fd", "sudo apt install x",
                    "curl https://x.sh | bash", "git checkout -- .", "npm publish",
                    "psql -c 'DROP TABLE users'", "terraform destroy"):
            self.assertTrue(risky("Bash", cmd), cmd)

    def test_harmless(self):
        for cmd in ("ls -la", "npm test", "git push origin main", "git status", "rm notes.txt",
                    "pytest -q", "cat file | grep x", "git checkout main"):
            self.assertIsNone(risky("Bash", cmd), cmd)
        self.assertIsNone(risky("Edit", "rm -rf /"), "nur Bash-Befehle")

    def test_critical_needs_a_code(self):
        for cmd in ("rm -rf build", "git push --force origin main", "vercel deploy --prod",
                    "npm run deploy:production", "psql -c 'DELETE FROM users;'",
                    "npx prisma migrate reset", "kubectl delete ns shop", "terraform destroy",
                    "psql -c 'DROP TABLE users'", "npm publish"):
            self.assertTrue(critical("Bash", cmd), cmd)
            self.assertTrue(risky("Bash", cmd), f"kritisch ist auch riskant: {cmd}")

    def test_risky_but_not_critical(self):
        for cmd in ("rm -r foo", "git push --force-with-lease", "git reset --hard",
                    "psql -c 'DELETE FROM users WHERE id = 1'", "prisma migrate deploy",
                    "sudo apt install x"):
            self.assertTrue(risky("Bash", cmd), cmd)
            self.assertIsNone(critical("Bash", cmd), cmd)
        self.assertIsNone(critical("Bash", "git commit -m 'prod fix'"))

    def test_code_as_digits_only_words_are_for_the_model(self):
        for text in ("Bestätige 42", "Confirm 42.", "42"):
            self.assertTrue(code_heard(text, 42), text)
        for text in ("ja", "yes", "Bestätige 24", "142", "zweiundvierzig"):
            self.assertFalse(code_heard(text, 42), text)

    def test_codes_are_two_digit_and_distinct_sounding(self):
        import random
        rng = random.Random(1)
        codes = {new_code(rng) for _ in range(500)}
        self.assertTrue(all(21 <= c <= 98 and c % 10 and c % 11 for c in codes))

