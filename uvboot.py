"""uv holen – damit die Einrichtung kein passendes Python, kein python3-venv und keine
Adminrechte braucht. uv bringt bei Bedarf selbst ein Python mit (nur für den Walkie).

Nur Standardbibliothek, läuft auch mit altem Python (macOS-System-Python 3.9).

  find_uv()   -> Pfad zu uv oder None (eigenes im Datenordner, sonst eines im PATH)
  ensure_uv() -> wie find_uv, lädt es sonst herunter (feste Version, SHA-256 geprüft)
"""
import hashlib
import io
import os
import platform
import shutil
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.9.0"
BASE = "https://github.com/astral-sh/uv/releases/download/" + VERSION + "/"
# Prüfsummen der offiziellen Release-Dateien (…/<datei>.sha256), fest eingetragen
SHA256 = {
    "uv-x86_64-unknown-linux-gnu.tar.gz":
        "4dadaa5ff5009ccd6a0a43f6ccfa32bf36ed2eff18df7011275a9b1d81950e7b",
    "uv-aarch64-unknown-linux-gnu.tar.gz":
        "ca410766024d2d726c937bda2e9441823e2848894ac5a2f8b608902384fc391f",
    "uv-x86_64-apple-darwin.tar.gz":
        "8fce2fe15b227ca38c706acda7cf0ebc43d5ec4be537f1badd58d5e938c7ed89",
    "uv-aarch64-apple-darwin.tar.gz":
        "136e70984e3fd359f4119ef445bfd67d6e0d50f15400226ef8db7b738ebef6d0",
    "uv-x86_64-pc-windows-msvc.zip":
        "4bad2c47dafb52ad774072fb7a260e5c9f3dbf73441658db1128eb2aec5818eb",
    "uv-aarch64-pc-windows-msvc.zip":
        "a816625eae0117c8ca0cd618716ddc11c68522d1ecfa7d2738f1c670099fef10",
}
WIN = sys.platform == "win32"
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "walkie"
UV = DATA / "uv" / ("uv.exe" if WIN else "uv")


def asset():
    """Name der passenden Release-Datei – oder None (System ohne fertiges uv)."""
    m = platform.machine().lower()
    arch = "aarch64" if m in ("arm64", "aarch64") else "x86_64" if m in ("x86_64", "amd64") else None
    if arch is None:
        return None
    if WIN:
        return "uv-%s-pc-windows-msvc.zip" % arch
    if sys.platform == "darwin":
        return "uv-%s-apple-darwin.tar.gz" % arch
    if sys.platform.startswith("linux"):
        return "uv-%s-unknown-linux-gnu.tar.gz" % arch
    return None


def find_uv():
    if UV.exists():
        return str(UV)
    return shutil.which("uv")


def ensure_uv(log=print):
    have = find_uv()
    if have:
        return have
    name = asset()
    if not name:
        return None
    log("  uv %s laden (bringt ein passendes Python mit) …" % VERSION)
    try:
        req = urllib.request.Request(BASE + name, headers={"User-Agent": "walkie"})
        data = urllib.request.urlopen(req, timeout=120).read()
    except OSError as ex:
        log("  ⚠ uv nicht ladbar: %s" % ex)
        return None
    if hashlib.sha256(data).hexdigest() != SHA256[name]:
        log("  ✗ uv: Prüfsumme stimmt nicht – Download verworfen")
        return None
    exe = "uv.exe" if WIN else "uv"
    blob = None
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next((n for n in z.namelist() if n.split("/")[-1] == exe), None)
            blob = z.read(member) if member else None
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            member = next((m for m in t.getmembers()
                           if m.isfile() and m.name.split("/")[-1] == exe), None)
            blob = t.extractfile(member).read() if member else None
    if not blob:
        log("  ✗ uv: Programm nicht im Archiv gefunden")
        return None
    UV.parent.mkdir(parents=True, exist_ok=True)
    tmp = UV.with_suffix(".part")
    tmp.write_bytes(blob)                      # nur die eine Datei, nichts wird entpackt
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(str(tmp), str(UV))
    return str(UV)


if __name__ == "__main__":                     # von bin/walkie aufgerufen: Pfad ausgeben
    p = ensure_uv(log=lambda m: print(m, file=sys.stderr))
    if not p:
        sys.exit(1)
    print(p)
