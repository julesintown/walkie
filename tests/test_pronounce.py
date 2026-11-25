"""Aussprache für die Stimme: englische Namen mit deutscher Stimme."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pronounce  # noqa: E402


class Pronounce(unittest.TestCase):
    def test_german_voice_says_walkie_in_english(self):
        self.assertEqual(pronounce.apply("Hallo, ich bin Walkie.", "de"),
                         "Hallo, ich bin [[ wˈɔːki. ]]")

    def test_punctuation_goes_into_the_block_and_words_do_not_stick(self):
        self.assertEqual(pronounce.apply("Bist du das, Walkie? Ja.", "de"),
                         "Bist du das, [[ wˈɔːki? ]] Ja.")
        self.assertEqual(pronounce.apply("(Walkie) ok", "de"), "([[ wˈɔːki ]] ) ok")

    def test_whole_words_only_and_any_case(self):
        self.assertEqual(pronounce.apply("Walkies walkie", "de"), "Walkies [[ wˈɔːki ]]")

    def test_other_languages_unchanged_unless_user_adds_words(self):
        self.assertEqual(pronounce.apply("Hi Walkie.", "en"), "Hi Walkie.")
        self.assertEqual(pronounce.apply("Hi Walkie.", "en", "Walkie=Wockie"), "Hi Wockie.")

    def test_user_entries_override_builtin(self):
        self.assertEqual(pronounce.apply("Hallo Walkie", "de", "Walkie=Uohki; Foo = [[fuː]]"),
                         "Hallo Uohki")
        self.assertEqual(pronounce.parse("a=b;;broken; c = [[x]]"), {"a": "b", "c": "[[x]]"})


if __name__ == "__main__":
    unittest.main()
