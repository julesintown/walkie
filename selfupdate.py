"""Selbst-Update einer Installation ohne Git (nur Standardbibliothek).

Der Installer (install.ps1) legt den Walkie als ZIP von GitHub an und schreibt dazu die Datei
UPDATE_FILE: Repository, Zweig, Stand (Commit) und die Liste der Dateien. Nur solche
Installationen aktualisieren sich selbst. Ein Git-Checkout (Entwicklung) bleibt unberührt:
Dort gibt es diese Datei nicht.

Ablauf: GitHub nach dem neuesten Commit des Zweigs fragen, bei neuem Stand dessen ZIP laden,
die Dateien ersetzen und Dateien löschen, die es im neuen Stand nicht mehr gibt (nur solche aus
der alten Liste – nie etwas, das der Nutzer selbst angelegt hat). Die Python-Umgebung liegt
außerhalb (~/.local/share/walkie/venv) und bleibt; geänderte requirements meldet update() zurück.

  python selfupdate.py           # prüfen und aktualisieren
  python selfupdate.py --check   # nur prüfen
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPDATE_FILE = ".walkie-update.json"
AGENT = "walkie-updater"                 # User-Agent: GitHub verlangt einen, nichts Persönliches
PACKAGE_FILES = ("requirements.txt", "requirements-nodeps.txt")


def info(root=HERE):
    """Inhalt von UPDATE_FILE – None bei einem Git-Checkout oder einer alten Installation."""
    try:
        data = json.loads((Path(root) / UPDATE_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("repo") and data.get("sha") else None


def _get(url, timeout, accept=None):
    headers = {"User-Agent": AGENT}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                timeout=timeout) as r:
        return r.read()


def latest(repo, branch, timeout=5):
    """Commit-SHA des neuesten Stands auf GitHub."""
    sha = _get(f"https://api.github.com/repos/{repo}/commits/{branch}", timeout,
               accept="application/vnd.github.sha").decode().strip()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError(f"unerwartete Antwort von GitHub: {sha[:60]!r}")
    return sha


def check(root=HERE, timeout=5):
    """-> neuer Commit-SHA oder None (aktuell, keine ZIP-Installation)."""
    cur = info(root)
    if not cur:
        return None
    sha = latest(cur["repo"], cur.get("branch") or "main", timeout)
    return sha if sha != cur["sha"] else None


def _digest(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def unpack(data):
    """ZIP von GitHub (oberster Ordner <repo>-<sha>/) -> {relativer Pfad: Bytes}."""
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for item in z.infolist():
            if item.is_dir():
                continue
            parts = item.filename.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            rel = parts[1]
            if rel.startswith("/") or ".." in rel.split("/"):
                raise ValueError(f"ungültiger Pfad im Archiv: {rel}")
            files[rel] = z.read(item)
    if "walkie.py" not in files:
        raise ValueError("Archiv enthält keinen Walkie")
    return files


def apply(root, files, repo, branch, sha):
    """Dateien in root ersetzen, verschwundene entfernen, UPDATE_FILE schreiben.
    -> True, wenn sich Paketlisten geändert haben (Pakete nachinstallieren)."""
    root = Path(root)
    old = info(root) or {}
    before = {name: _digest(root / name) for name in PACKAGE_FILES}
    # erst alles in einen Ordner daneben schreiben, dann Datei für Datei tauschen: bricht der
    # Download ab, bleibt die alte Installation ganz
    stage = Path(tempfile.mkdtemp(prefix=".walkie-update-", dir=root.parent))
    try:
        for rel, data in files.items():
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        for rel in files:
            target = root / rel
            if target.exists() and target.read_bytes() == files[rel]:
                continue                       # unverändert: nicht anfassen (laufende .cmd)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / rel, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    for rel in set(old.get("files") or []) - set(files):
        try:
            (root / rel).unlink()
        except OSError:
            pass
    (root / UPDATE_FILE).write_text(json.dumps(
        {"repo": repo, "branch": branch, "sha": sha, "files": sorted(files)}, indent=1) + "\n",
        encoding="utf-8")
    return any(_digest(root / name) != before[name] for name in PACKAGE_FILES)


def update(root=HERE, log=print, timeout=5):
    """Prüfen und bei neuem Stand aktualisieren. -> None (nichts zu tun) oder
    {"sha": …, "packages": bool}. Fehler (offline, GitHub nicht erreichbar) -> None."""
    cur = info(root)
    if not cur:
        return None
    branch = cur.get("branch") or "main"
    try:
        sha = latest(cur["repo"], branch, timeout)
        if sha == cur["sha"]:
            return None
        files = unpack(_get(f"https://codeload.github.com/{cur['repo']}/zip/{sha}", 120))
        packages = apply(root, files, cur["repo"], branch, sha)
    except Exception as ex:  # noqa: BLE001 – Update ist nie wichtiger als der Start
        log(f"update: {ex}")
        return None
    log(f"update: {cur['sha'][:7]} -> {sha[:7]}" + (" (neue Pakete)" if packages else ""))
    return {"sha": sha, "packages": packages}


if __name__ == "__main__":
    if "--check" in sys.argv:
        cur = info()
        print("keine ZIP-Installation (Git-Checkout?)" if not cur else
              f"neuer Stand: {check()}" if check() else f"aktuell ({cur['sha'][:7]})")
    else:
        print(update() or "nichts zu tun")
