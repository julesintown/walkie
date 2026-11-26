import isolate  # noqa: F401  (immer zuerst: Tests schreiben nie in die echten Walkie-Ordner)

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import appentry  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def fake_root(base):
    # Leerzeichen und Sonderzeichen im Pfad ("" ist unter Windows in Dateinamen nicht erlaubt)
    name = "Walkie's app $HOME" if sys.platform == "win32" else "Walkie's \"app\" $HOME"
    root = Path(base) / name
    (root / "bin").mkdir(parents=True)
    (root / "icons").mkdir()
    (root / "walkie.py").write_text("")
    (root / "icons" / "walkie.icns").write_bytes(b"icns")
    return root


class IconsTest(unittest.TestCase):
    def test_icons_exist(self):
        for name in ("walkie.png", "walkie.ico", "walkie.icns"):
            self.assertGreater((REPO / "icons" / name).stat().st_size, 1000, name)
        self.assertEqual((REPO / "icons" / "walkie.ico").read_bytes()[:4], b"\0\0\1\0")
        self.assertEqual((REPO / "icons" / "walkie.icns").read_bytes()[:4], b"icns")


class LinuxEntryTest(unittest.TestCase):
    def test_desktop_entry_quotes_exec_and_points_to_icon(self):
        with tempfile.TemporaryDirectory() as temp:
            root = fake_root(temp)
            text = appentry.desktop_entry(root)
        exec_line = next(line for line in text.splitlines() if line.startswith("Exec="))
        self.assertEqual(exec_line, 'Exec="' + str(root / "bin" / "walkie")
                         .replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"')
        self.assertIn(f"Icon={root / 'icons' / 'walkie.png'}", text)
        self.assertIn("Terminal=false", text)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux")
    def test_install_writes_entry_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = fake_root(temp)
            env = {"XDG_DATA_HOME": str(Path(temp) / "share")}
            with patch.dict(os.environ, env), patch.dict(os.environ, {"WALKIE_NO_APP_ENTRY": ""}), \
                    patch.object(appentry, "in_wsl", return_value=False):
                dest = appentry.install(root)
                self.assertEqual(dest, Path(temp) / "share" / "applications" / "walkie.desktop")
                self.assertEqual(dest.read_text(), appentry.desktop_entry(root))
                dest.write_text("vom Nutzer geändert")
                self.assertIsNone(appentry.install(root, refresh=False), "beim Start: vorhanden")
                self.assertEqual(dest.read_text(), "vom Nutzer geändert")
                appentry.install(root)
                self.assertEqual(dest.read_text(), appentry.desktop_entry(root), "setup: neu")

    def test_nothing_under_wsl(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {"XDG_DATA_HOME": str(Path(temp) / "share"), "WALKIE_NO_APP_ENTRY": ""}
            with patch.dict(os.environ, env), patch.object(appentry, "in_wsl", return_value=True):
                self.assertIsNone(appentry.install(fake_root(temp)))
            self.assertFalse((Path(temp) / "share" / "applications").exists())

    def test_disabled_in_tests(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(appentry.install(fake_root(temp)))


class MacAppTest(unittest.TestCase):
    def test_bundle_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = fake_root(temp)
            app = Path(temp) / "Applications" / "Walkie.app"
            appentry._write_mac(app, root)
            contents = app / "Contents"
            info = plistlib.loads((contents / "Info.plist").read_bytes())
            self.assertEqual(info["CFBundleExecutable"], "Walkie")
            self.assertEqual(info["CFBundleIconFile"], "walkie.icns")
            self.assertTrue(info["LSUIElement"])
            self.assertEqual((contents / "Resources" / "walkie.icns").read_bytes(), b"icns")
            exe = contents / "MacOS" / "Walkie"
            if sys.platform != "win32":
                self.assertTrue(os.access(exe, os.X_OK))
            if shutil.which("sh"):
                self.assertEqual(subprocess.run(["sh", "-n", str(exe)]).returncode, 0)

    @unittest.skipIf(sys.platform == "win32" or not shutil.which("sh"), "braucht sh")
    def test_script_starts_walkie_with_shell_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = fake_root(temp)
            marker = Path(temp) / "called"
            walkie = root / "bin" / "walkie"
            walkie.write_text(f'#!/bin/sh\necho "$PATH" > "{marker}"\n')
            walkie.chmod(0o755)
            exe = Path(temp) / "Walkie"
            exe.write_text(appentry.mac_script(root))
            env = {"HOME": temp, "SHELL": "/bin/sh", "PATH": "/usr/bin:/bin"}
            subprocess.run(["sh", str(exe)], env=env, timeout=20, check=True)
            path = marker.read_text()
            self.assertIn(f"{temp}/.local/bin", path)
            self.assertIn("/opt/homebrew/bin", path)


class WindowsShortcutTest(unittest.TestCase):
    def test_powershell_gets_quoted_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = fake_root(temp)
            pyw = Path(temp) / "pythonw.exe"
            pyw.write_text("")
            lnk = Path(temp) / "Start" / "Walkie.lnk"
            seen = []

            def run(cmd, **_kw):
                seen.append(cmd)
                lnk.write_text("")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with patch.object(appentry, "windows_target",
                              return_value=(pyw, f'"{root / "cli.py"}"', root / "icons" / "x.ico")), \
                    patch.object(appentry.subprocess, "run", side_effect=run):
                appentry._write_windows([lnk], root)
        script = seen[0][-1]
        self.assertIn("WScript.Shell", script)
        self.assertIn("Walkie''s", script, "einfache Anführungszeichen verdoppelt")
        self.assertIn(f"$l.TargetPath = '{pyw}'", script)


if __name__ == "__main__":
    unittest.main()
