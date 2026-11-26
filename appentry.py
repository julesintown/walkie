"""Walkie als App mit Icon starten: Eintrag im Startmenü bzw. Programme-Ordner (nur stdlib).

  Windows  Startmenü\\Programme\\Walkie.lnk (+ Desktop beim Einrichten) → pythonw cli.py
  macOS    ~/Applications/Walkie.app (Launchpad, Spotlight, Dock)      → bin/walkie
  Linux    ~/.local/share/applications/walkie.desktop (App-Menü)        → bin/walkie

Ein Klick tut dasselbe wie `walkie` ohne Argumente: starten oder die Figur nach vorne holen.
Die Einträge zeigen auf die Installation (root) und werden bei `walkie setup` neu geschrieben,
beim Start nur angelegt, falls sie fehlen. Icons: icons/ (tools/make_icons.py).
"""
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "Walkie"
COMMENT = "Mit Claude Code über Kopfhörer reden"


def _home():
    return Path(os.environ.get("HOME") or Path.home())


def entry_path():
    """Wo der App-Eintrag liegt (None: unbekanntes System)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return (Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{NAME}.lnk"
                if base else None)
    if sys.platform == "darwin":
        return _home() / "Applications" / f"{NAME}.app"
    if sys.platform.startswith("linux"):
        data = Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share")
        return data / "applications" / "walkie.desktop"
    return None


# ---------- Linux ----------

def _desktop_quote(arg):
    """Exec-Argument nach der Desktop-Entry-Spezifikation quoten."""
    for ch in ("\\", '"', "`", "$"):
        arg = arg.replace(ch, "\\" + ch)
    return f'"{arg}"'


def desktop_entry(root):
    root = Path(root)
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={NAME}",
        f"Comment={COMMENT}",
        f"Exec={_desktop_quote(str(root / 'bin' / 'walkie'))}",
        f"Path={root}",
        f"Icon={root / 'icons' / 'walkie.png'}",
        "Terminal=false",
        "StartupNotify=false",
        "Categories=Utility;Accessibility;",
        "Keywords=voice;claude;headphones;companion;",
        "",
    ])


def _write_linux(dest, root):
    text = desktop_entry(root)
    if dest.exists() and dest.read_text(encoding="utf-8", errors="replace") == text:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    dest.chmod(0o755)                         # manche Dateimanager starten sonst nicht
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(dest.parent)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


# ---------- macOS ----------

def mac_script(root):
    """Startskript der App. Aus dem Finder gestartet fehlt der PATH der Shell (Homebrew,
    ~/.local/bin, claude) – den holt sich das Skript aus einer Login-Shell."""
    walkie = shlex.quote(str(Path(root) / "bin" / "walkie"))
    return (
        "#!/bin/sh\n"
        "# Walkie.app – startet den Walkie (angelegt von `walkie setup`, appentry.py)\n"
        'p="$("${SHELL:-/bin/zsh}" -lc \'printf %s "$PATH"\' 2>/dev/null </dev/null)"\n'
        '[ -n "$p" ] && PATH="$p"\n'
        'PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
        "export PATH\n"
        f"exec {walkie} >/dev/null 2>&1 </dev/null\n"
    )


def mac_plist():
    return {
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleIdentifier": "io.github.julesintown.walkie",
        "CFBundleExecutable": NAME,
        "CFBundleIconFile": "walkie.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "10.13",
        "LSUIElement": True,                  # nur Starter: kein eigenes Symbol im Dock
        "NSHighResolutionCapable": True,
    }


def _write_mac(dest, root):
    contents = dest / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(parents=True, exist_ok=True)
    exe = contents / "MacOS" / NAME
    exe.write_text(mac_script(root), encoding="utf-8")
    exe.chmod(0o755)
    (contents / "Info.plist").write_bytes(plistlib.dumps(mac_plist()))
    icns = Path(root) / "icons" / "walkie.icns"
    if icns.exists():
        (contents / "Resources" / "walkie.icns").write_bytes(icns.read_bytes())
    os.utime(dest)                            # Finder/Launchpad laden das Icon neu
    lsregister = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
                  "LaunchServices.framework/Support/lsregister")
    if Path(lsregister).exists():
        subprocess.run([lsregister, "-f", str(dest)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)


# ---------- Windows ----------

def windows_target(root):
    """Ziel der Verknüpfung: pythonw (kein Konsolenfenster) mit cli.py, Icon aus icons/."""
    import paths
    pyw = Path(paths.python(gui=True))
    return pyw, f'"{Path(root) / "cli.py"}"', Path(root) / "icons" / "walkie.ico"


def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def _write_windows(dests, root):
    pyw, args, icon = windows_target(root)
    if not pyw.exists():
        raise OSError(f"{pyw} fehlt")
    lines = ["$s = New-Object -ComObject WScript.Shell"]
    for d in dests:
        d.parent.mkdir(parents=True, exist_ok=True)
        lines += [f"$l = $s.CreateShortcut({_ps_quote(d)})",
                  f"$l.TargetPath = {_ps_quote(pyw)}",
                  f"$l.Arguments = {_ps_quote(args)}",
                  f"$l.WorkingDirectory = {_ps_quote(root)}",
                  f"$l.IconLocation = {_ps_quote(str(icon) + ',0')}",
                  f"$l.Description = {_ps_quote(COMMENT)}",
                  "$l.Save()"]
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        "; ".join(lines)], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode or not all(d.exists() for d in dests):
        raise OSError((r.stderr or r.stdout or "PowerShell-Fehler").strip().splitlines()[-1])


def windows_desktop():
    """Desktop des Nutzers (auch umgeleitet, z. B. nach OneDrive)."""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            "[Environment]::GetFolderPath('Desktop')"], capture_output=True,
                           text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.stdout.strip():
            return Path(r.stdout.strip())
    except OSError:
        pass
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"


# ---------- gemeinsam ----------

def install(root, refresh=True, desktop=False):
    """App-Eintrag anlegen. refresh=False: nur, falls er fehlt (schnell, für jeden Start).
    desktop: unter Windows zusätzlich eine Verknüpfung auf dem Desktop. Gibt den Pfad zurück,
    None ohne Änderung; OSError bei Fehlern."""
    if os.environ.get("WALKIE_NO_APP_ENTRY"):
        return None                           # Tests (tests/isolate.py)
    dest = entry_path()
    if dest is None or not (Path(root) / "walkie.py").exists():
        return None
    if not refresh and dest.exists():
        return None
    if sys.platform == "win32":
        dests = [dest] + ([windows_desktop() / f"{NAME}.lnk"] if desktop else [])
        _write_windows(dests, root)
    elif sys.platform == "darwin":
        _write_mac(dest, root)
    else:
        _write_linux(dest, root)
    return dest
