"""Fehlende Qt-Systembibliotheken (WSL: libxcb-icccm4, libxcb-keysyms1) erkennen."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sysdeps  # noqa: E402

LDD = """\tlinux-vdso.so.1 (0x00007ffd)
\tlibxcb-icccm.so.4 => not found
\tlibxcb-keysyms.so.1 => not found
\tlibxcb.so.1 => /lib/x86_64-linux-gnu/libxcb.so.1 (0x00007f)
"""


@unittest.skipUnless(sys.platform.startswith("linux"), "nur Linux")
class SysDeps(unittest.TestCase):
    def test_missing_libraries_from_ldd(self):
        done = subprocess.CompletedProcess([], 0, stdout=LDD, stderr="")
        with patch("subprocess.run", return_value=done), patch("shutil.which", return_value="/usr/bin/ldd"):
            self.assertEqual(sysdeps.missing([Path("libqxcb.so")]),
                             ["libxcb-icccm.so.4", "libxcb-keysyms.so.1"])

    def test_apt_command_for_wsl_ubuntu(self):
        def which(name):
            return "/usr/bin/apt-get" if name == "apt-get" else None
        with patch("shutil.which", which):
            pkgs, cmd = sysdeps.install_command(["libxcb-icccm.so.4", "libxcb-keysyms.so.1"])
        self.assertEqual(pkgs, ["libxcb-icccm4", "libxcb-keysyms1"])
        self.assertEqual(cmd, ["apt-get", "install", "-y", "libxcb-icccm4", "libxcb-keysyms1"])

    def test_dnf_names(self):
        with patch("shutil.which", lambda n: "/usr/bin/dnf" if n == "dnf" else None):
            pkgs, _ = sysdeps.install_command(["libxcb-icccm.so.4", "libxcb-cursor.so.0"])
        self.assertEqual(pkgs, ["xcb-util-wm", "xcb-util-cursor"])


if __name__ == "__main__":
    unittest.main()
