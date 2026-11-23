"""Setup must distinguish an optional download failure from a broken installation."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fetch_assets
import paths


class SetupTest(unittest.TestCase):
    def run_setup(self, flags, failures):
        import cli
        calls = []

        def run(command):
            calls.append(command)
            return SimpleNamespace(returncode=next((code for part, code in failures.items()
                                                    if part in command), 0))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            venv = root / "venv"
            python = paths.venv_python(venv)
            python.parent.mkdir(parents=True)
            python.touch()
            output = io.StringIO()
            with (patch.dict(os.environ, WALKIE_VENV=str(venv)),
                  patch.object(cli, "install_dir", return_value=root),
                  patch.object(paths, "HERE", root),
                  patch("uvboot.ensure_uv", return_value="uv"),
                  patch("audio.build_mac_voicemic", return_value=False),
                  patch.object(cli.subprocess, "run", side_effect=run),
                  contextlib.redirect_stdout(output), contextlib.redirect_stderr(output)):
                try:
                    cli.cmd_setup(["--no-start", *flags])
                except SystemExit as ex:
                    status = ex.code
                else:
                    status = 0
        return status, calls, output.getvalue()

    def test_no_assets_still_requires_passing_doctor(self):
        status, calls, _ = self.run_setup(["--no-assets"], {"--allow-missing-agent": 1})
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("install", calls[0])
        self.assertIn("--allow-missing-agent", calls[1])

    def test_failed_downloads_report_both_warnings_and_continue(self):
        status, calls, output = self.run_setup([], {"voices": 1, "-c": 1})
        self.assertEqual(status, 0)
        self.assertIn("--allow-missing-agent", calls[-1])
        self.assertIn("⚠ Stimme", output)
        self.assertIn("⚠ Whisper", output)

    def test_offline_voice_uses_only_local_files(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, HF_HUB_OFFLINE="1"):
            dest = Path(temp) / "voice.onnx"
            with patch("urllib.request.urlopen") as download:
                with self.assertRaisesRegex(OSError, "HF_HUB_OFFLINE"):
                    fetch_assets.fetch("https://example.invalid/model", dest)
                dest.write_bytes(b"cached")
                fetch_assets.fetch("https://example.invalid/model", dest)
                download.assert_not_called()
