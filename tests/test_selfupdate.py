"""selfupdate.py: Installation ohne Git aktualisiert sich von GitHub (ohne Netz getestet)."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import selfupdate  # noqa: E402

OLD, NEW = "a" * 40, "b" * 40


def archive(files, sha=NEW):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(f"walkie-{sha}/{name}", text)
    return buf.getvalue()


class SelfUpdateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "app"
        self.root.mkdir()
        for name, text in {"walkie.py": "alt", "weg.py": "alt", "requirements.txt": "PyQt6",
                           "bin/walkie.cmd": "@echo off"}.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text)
        (self.root / "eigene-notiz.txt").write_text("vom Nutzer")
        (self.root / selfupdate.UPDATE_FILE).write_text(json.dumps(
            {"repo": "x/walkie", "branch": "main", "sha": OLD,
             "files": ["walkie.py", "weg.py", "requirements.txt", "bin/walkie.cmd"]}))

    def fake_get(self, files):
        def get(url, timeout, accept=None):
            if "api.github.com" in url:
                self.assertIn("/repos/x/walkie/commits/main", url)
                return NEW.encode()
            self.assertIn(f"codeload.github.com/x/walkie/zip/{NEW}", url)
            return archive(files)
        return patch.object(selfupdate, "_get", get)

    def test_git_checkout_is_never_touched(self):
        (self.root / selfupdate.UPDATE_FILE).unlink()
        with patch.object(selfupdate, "_get", side_effect=AssertionError("kein Netz")):
            self.assertIsNone(selfupdate.update(self.root, log=lambda m: None))

    def test_update_replaces_files_and_removes_only_old_ones(self):
        new = {"walkie.py": "neu", "requirements.txt": "PyQt6", "bin/walkie.cmd": "@echo off",
               "selfupdate.py": "x"}
        with self.fake_get(new):
            res = selfupdate.update(self.root, log=lambda m: None)
        self.assertEqual(res, {"sha": NEW, "packages": False})
        self.assertEqual((self.root / "walkie.py").read_text(), "neu")
        self.assertFalse((self.root / "weg.py").exists())
        self.assertEqual((self.root / "eigene-notiz.txt").read_text(), "vom Nutzer")
        state = selfupdate.info(self.root)
        self.assertEqual(state["sha"], NEW)
        self.assertIn("selfupdate.py", state["files"])
        self.assertEqual(list(self.root.parent.glob(".walkie-update-*")), [])   # nichts liegen gelassen

    def test_changed_requirements_ask_for_packages(self):
        new = {"walkie.py": "alt", "requirements.txt": "PyQt6\nneu-paket"}
        with self.fake_get(new):
            self.assertTrue(selfupdate.update(self.root, log=lambda m: None)["packages"])

    def test_current_version_downloads_nothing(self):
        state = json.loads((self.root / selfupdate.UPDATE_FILE).read_text())
        state["sha"] = NEW
        (self.root / selfupdate.UPDATE_FILE).write_text(json.dumps(state))
        with self.fake_get({}):
            self.assertIsNone(selfupdate.update(self.root, log=lambda m: None))

    def test_offline_keeps_installation(self):
        logs = []
        with patch.object(selfupdate, "_get", side_effect=OSError("offline")):
            self.assertIsNone(selfupdate.update(self.root, log=logs.append))
        self.assertEqual((self.root / "walkie.py").read_text(), "alt")
        self.assertIn("offline", logs[0])

    def test_broken_archive_keeps_installation(self):
        with self.fake_get({"README.md": "kein walkie.py"}):
            self.assertIsNone(selfupdate.update(self.root, log=lambda m: None))
        self.assertEqual((self.root / "walkie.py").read_text(), "alt")

    def test_paths_leaving_the_folder_are_refused(self):
        with self.assertRaises(ValueError):
            selfupdate.unpack(archive({"walkie.py": "x", "../../böse.py": "x"}))


if __name__ == "__main__":
    unittest.main()
