"""uv-Download: Prüfsummen und Plattformzuordnung, gleich in uvboot.py und den Startern."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvboot  # noqa: E402


class UvbootTest(unittest.TestCase):
    def test_every_platform_has_a_checksum(self):
        for name, sha in uvboot.SHA256.items():
            self.assertRegex(sha, r"^[0-9a-f]{64}$", name)
        here = uvboot.asset()
        if here:
            self.assertIn(here, uvboot.SHA256)

    @unittest.skipIf(sys.platform == "win32", "sh-Starter")
    def test_sh_starter_reads_the_same_checksums(self):
        for name, sha in uvboot.SHA256.items():
            if name.endswith(".zip"):
                continue
            got = subprocess.run(
                ["sh", "-c", f'grep -A1 "\\"{name}\\":" "{ROOT}/uvboot.py" | tail -n 1 | tr -dc 0-9a-f'],
                capture_output=True, text=True).stdout
            self.assertEqual(got, sha, name)

    def test_powershell_starter_regex_matches(self):
        src = (ROOT / "uvboot.py").read_text(encoding="utf-8")
        for name, sha in uvboot.SHA256.items():
            m = re.search(re.escape(name) + r'":\s*"([0-9a-f]{64})"', src)
            self.assertEqual(m and m.group(1), sha, name)
        self.assertEqual(re.search(r'VERSION = "([^"]+)"', src).group(1), uvboot.VERSION)


if __name__ == "__main__":
    unittest.main()
