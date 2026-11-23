"""Systembibliotheken, die pip nicht mitbringt (nur Linux, nur Standardbibliothek).

PyQt6 bringt Qt selbst mit, aber nicht die xcb-Hilfsbibliotheken des X11-Plugins. Auf einem
frischen Ubuntu unter WSL fehlen z. B. libxcb-icccm4 und libxcb-keysyms1 – dann startet die
Figur gar nicht („could not load the Qt platform plugin xcb“). Dieses Modul findet die
fehlenden Bibliotheken per ldd und nennt die Pakete dafür.

  python sysdeps.py            # fehlende Bibliotheken und den Installationsbefehl zeigen
  python sysdeps.py --json     # {"missing": [...], "packages": [...], "command": [...]}
"""
import ctypes.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# soname -> (Debian/Ubuntu, Fedora/RHEL, Arch)
PACKAGES = {
    "libxcb-icccm.so.4": ("libxcb-icccm4", "xcb-util-wm", "xcb-util-wm"),
    "libxcb-keysyms.so.1": ("libxcb-keysyms1", "xcb-util-keysyms", "xcb-util-keysyms"),
    "libxcb-cursor.so.0": ("libxcb-cursor0", "xcb-util-cursor", "xcb-util-cursor"),
    "libxcb-image.so.0": ("libxcb-image0", "xcb-util-image", "xcb-util-image"),
    "libxcb-render-util.so.0": ("libxcb-render-util0", "xcb-util-renderutil",
                                "xcb-util-renderutil"),
    "libxcb-util.so.1": ("libxcb-util1", "xcb-util", "xcb-util"),
    "libxcb-randr.so.0": ("libxcb-randr0", "libxcb", "libxcb"),
    "libxcb-shape.so.0": ("libxcb-shape0", "libxcb", "libxcb"),
    "libxcb-xkb.so.1": ("libxcb-xkb1", "libxcb", "libxcb"),
    "libxcb-xfixes.so.0": ("libxcb-xfixes0", "libxcb", "libxcb"),
    "libxcb-sync.so.1": ("libxcb-sync1", "libxcb", "libxcb"),
    "libxcb-shm.so.0": ("libxcb-shm0", "libxcb", "libxcb"),
    "libxcb-render.so.0": ("libxcb-render0", "libxcb", "libxcb"),
    "libxcb.so.1": ("libxcb1", "libxcb", "libxcb"),
    "libX11-xcb.so.1": ("libx11-xcb1", "libX11-xcb", "libx11"),
    "libX11.so.6": ("libx11-6", "libX11", "libx11"),
    "libxkbcommon-x11.so.0": ("libxkbcommon-x11-0", "libxkbcommon-x11", "libxkbcommon-x11"),
    "libxkbcommon.so.0": ("libxkbcommon0", "libxkbcommon", "libxkbcommon"),
    "libEGL.so.1": ("libegl1", "libglvnd-egl", "libglvnd"),
    "libGL.so.1": ("libgl1", "libglvnd-glx", "libglvnd"),
    "libGLX.so.0": ("libglx0", "libglvnd-glx", "libglvnd"),
    "libOpenGL.so.0": ("libopengl0", "libglvnd-opengl", "libglvnd"),
    "libfontconfig.so.1": ("libfontconfig1", "fontconfig", "fontconfig"),
    "libfreetype.so.6": ("libfreetype6", "freetype", "freetype2"),
    "libdbus-1.so.3": ("libdbus-1-3", "dbus-libs", "dbus"),
    "libwayland-client.so.0": ("libwayland-client0", "libwayland-client", "wayland"),
    "libwayland-cursor.so.0": ("libwayland-cursor0", "libwayland-cursor", "wayland"),
    "libwayland-egl.so.1": ("libwayland-egl1", "libwayland-egl", "wayland"),
    # miniaudio lädt eins von beiden zur Laufzeit (WSLg: PulseAudio-Server)
    "libasound.so.2": ("libasound2t64", "alsa-lib", "alsa-lib"),
}
MANAGERS = (("apt-get", 0, ["apt-get", "install", "-y"]),
            ("dnf", 1, ["dnf", "install", "-y"]),
            ("pacman", 2, ["pacman", "-S", "--needed", "--noconfirm"]))


def qt_libraries():
    """Die nativen Qt-Teile, die beim Start der Figur geladen werden."""
    try:
        import PyQt6
    except ImportError:
        return []
    qt = Path(PyQt6.__file__).resolve().parent / "Qt6"
    found = [qt / "plugins" / "platforms" / "libqxcb.so",
             qt / "plugins" / "platforms" / "libqwayland.so",
             *sorted((qt / "lib").glob("libQt6XcbQpa.so*"))[:1],
             *sorted((qt / "lib").glob("libQt6Gui.so*"))[:1]]
    return [p for p in found if p.exists()]


def missing(libs=None):
    """Sonames, die der dynamische Linker für Qt nicht findet (+ Audio, falls ganz ohne)."""
    if not sys.platform.startswith("linux") or not shutil.which("ldd"):
        return []
    out = []
    for lib in libs if libs is not None else qt_libraries():
        try:
            r = subprocess.run(["ldd", str(lib)], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for name in re.findall(r"^\s*(\S+)\s+=>\s+not found", r.stdout, re.M):
            if name not in out:
                out.append(name)
    if libs is None and not (ctypes.util.find_library("asound")
                             or ctypes.util.find_library("pulse")):
        out.append("libasound.so.2")
    return out


def _apt_name(pkg):
    """Ubuntu vor 24.04 heißt libasound2 noch ohne t64."""
    if pkg == "libasound2t64" and shutil.which("apt-cache"):
        r = subprocess.run(["apt-cache", "show", pkg], capture_output=True, text=True)
        if r.returncode != 0:
            return "libasound2"
    return pkg


def install_command(names):
    """(Pakete, Befehl ohne sudo) für den Paketmanager dieses Systems – oder ([], None)."""
    for prog, col, cmd in MANAGERS:
        if shutil.which(prog):
            pkgs = []
            for n in names:
                pkg = PACKAGES.get(n, (None,) * 3)[col]
                if pkg and col == 0:
                    pkg = _apt_name(pkg)
                if pkg and pkg not in pkgs:
                    pkgs.append(pkg)
            return pkgs, ([*cmd, *pkgs] if pkgs else None)
    return [], None


def report():
    names = missing()
    pkgs, cmd = install_command(names)
    return {"missing": names, "packages": pkgs, "command": cmd}


if __name__ == "__main__":
    info = report()
    if "--json" in sys.argv:
        print(json.dumps(info))
    elif not info["missing"]:
        print("✓ Alle Systembibliotheken für Qt und Audio vorhanden")
    else:
        print("Es fehlen Systembibliotheken: " + ", ".join(info["missing"]))
        if info["command"]:
            print("  sudo " + " ".join(info["command"]))
        sys.exit(1)
