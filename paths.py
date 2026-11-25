"""Wo liegt was, und wie startet man es – auf Linux, macOS und Windows gleich (nur stdlib).

Python-Umgebung des Walkies (erste vorhandene):
  $WALKIE_VENV · ~/.local/share/walkie/venv (von `walkie setup`) · <Repo>/.venv
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIN = sys.platform == "win32"
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "walkie"
VENV = DATA / "venv"


def venv_python(venv, gui=False):
    venv = Path(venv)
    if WIN:
        return venv / "Scripts" / ("pythonw.exe" if gui else "python.exe")
    return venv / "bin" / "python"


def venvs():
    out = []
    if os.environ.get("WALKIE_VENV"):
        out.append(Path(os.environ["WALKIE_VENV"]))
    return out + [VENV, HERE / ".venv"]


def python(gui=False):
    """Python mit den Abhängigkeiten des Walkies – sonst das laufende."""
    for v in venvs():
        p = venv_python(v, gui)
        if p.exists():
            return str(p)
    return sys.executable


def clean_env():
    """Umgebung ohne Variablen einer umgebenden Claude-Code-Session."""
    return {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}


def no_window():
    """Windows: Hintergrundprogramme (claude.cmd, agy.exe, git …) ohne eigenes Konsolenfenster
    starten. Der Walkie läuft unter pythonw ohne Konsole; sonst öffnet jeder Aufruf ein leeres
    Fenster mit dem Programmpfad als Titel."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if WIN else {}


def launch(script, *args):
    """Skript des Walkies losgelöst starten (kein Konsolenfenster unter Windows)."""
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
          "stderr": subprocess.DEVNULL, "env": clean_env(), "cwd": str(HERE)}
    if WIN:
        kw["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.CREATE_NO_WINDOW)
    else:
        kw["start_new_session"] = True
    return subprocess.Popen([python(gui=True), str(HERE / script), *args], **kw)


# Linux: wie ein Terminal ein Programm startet (Arbeitsordner, Befehl). Programme, die sonst in
# einen schon laufenden Server übergeben und sofort enden, laufen hier bis zum Fensterschluss –
# so weiß der Walkie, ob das Fenster noch offen ist.
LINUX_TERMINALS = {
    "konsole": lambda cwd, argv: ["--nofork", "--workdir", cwd, "-e", *argv],
    "gnome-terminal": lambda cwd, argv: ["--wait", f"--working-directory={cwd}", "--", *argv],
    "kgx": lambda cwd, argv: [f"--working-directory={cwd}", "--", *argv],
    "ptyxis": lambda cwd, argv: ["--new-window", "--working-directory", cwd, "--", *argv],
    "xfce4-terminal": lambda cwd, argv: ["--disable-server", f"--working-directory={cwd}",
                                         "-x", *argv],
    "mate-terminal": lambda cwd, argv: ["--disable-factory", f"--working-directory={cwd}",
                                        "-x", *argv],
    "tilix": lambda cwd, argv: ["-w", cwd, "-e", *argv],
    "qterminal": lambda cwd, argv: ["-w", cwd, "-e", *argv],
    "lxterminal": lambda cwd, argv: [f"--working-directory={cwd}", "-e", *argv],
    "kitty": lambda cwd, argv: ["--directory", cwd, *argv],
    "alacritty": lambda cwd, argv: ["--working-directory", cwd, "-e", *argv],
    "wezterm": lambda cwd, argv: ["start", "--cwd", cwd, "--", *argv],
    "foot": lambda cwd, argv: ["-D", cwd, *argv],
    "ghostty": lambda cwd, argv: [f"--working-directory={cwd}", "-e", *argv],
    "xterm": lambda cwd, argv: ["-e", *argv],
}
DESKTOP_TERMINALS = {"kde": ["konsole"], "gnome": ["ptyxis", "kgx", "gnome-terminal"],
                     "xfce": ["xfce4-terminal"], "mate": ["mate-terminal"],
                     "x-cinnamon": ["gnome-terminal"], "cinnamon": ["gnome-terminal"],
                     "lxqt": ["qterminal"], "lxde": ["lxterminal"]}


DESKTOP_PROCESSES = {"plasmashell": "kde", "gnome-shell": "gnome", "xfce4-session": "xfce",
                     "xfwm4": "xfce", "mate-session": "mate", "cinnamon": "cinnamon",
                     "lxqt-session": "lxqt", "lxsession": "lxde"}


def running_desktop():
    """Ohne XDG_CURRENT_DESKTOP (z. B. aus einer Shell ohne Desktop-Umgebung gestartet): die
    Arbeitsumgebung an ihren laufenden Prozessen erkennen."""
    names = set()
    try:
        for d in Path("/proc").iterdir():
            if d.name.isdigit():
                try:
                    names.add((d / "comm").read_text(encoding="utf-8").strip())
                except OSError:
                    continue                    # Prozess gerade beendet
    except OSError:
        return []
    return list(dict.fromkeys(v for k, v in DESKTOP_PROCESSES.items() if k in names))


def linux_terminal(argv, cwd):
    """Befehlszeile für das Standard-Terminal: $TERMINAL, xdg-terminal-exec, das Terminal der
    Arbeitsumgebung (XDG_CURRENT_DESKTOP), x-terminal-emulator, dann bekannte Terminals."""
    import shlex
    import shutil
    term = os.environ.get("TERMINAL", "").strip()
    if term:
        parts = shlex.split(term)
        name = Path(parts[0]).name
        if shutil.which(parts[0]):
            how = LINUX_TERMINALS.get(name, lambda c, a: ["-e", *a])
            return [*parts, *how(cwd, argv)]
    if shutil.which("xdg-terminal-exec"):
        return ["xdg-terminal-exec", *argv]
    desktops = [d.strip().lower() for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
                if d.strip()] or running_desktop()
    candidates = [t for d in desktops for t in DESKTOP_TERMINALS.get(d, [])]
    for name in candidates:
        if shutil.which(name):
            return [name, *LINUX_TERMINALS[name](cwd, argv)]
    if shutil.which("x-terminal-emulator"):
        target = Path(os.path.realpath(shutil.which("x-terminal-emulator"))).name
        target = target.removesuffix(".wrapper")
        how = LINUX_TERMINALS.get(target, lambda c, a: ["-e", *a])
        return ["x-terminal-emulator", *how(cwd, argv)]
    for name, how in LINUX_TERMINALS.items():
        if shutil.which(name):
            return [name, *how(cwd, argv)]
    return None


def wt_escape(argv):
    """Argumente für Windows Terminal: „;“ ist dort der Trenner zwischen Tabs, „\\;“ ein echtes."""
    return [a.replace(";", "\\;") for a in argv]


def open_terminal(argv, cwd=None, title="Claude", env_extra=None):
    """Programm in einem neuen, sichtbaren Fenster des Standard-Terminals starten.
    Linux: siehe linux_terminal(), macOS: Terminal.app, Windows: Windows Terminal, sonst cmd.
    Rückgabe: der gestartete Prozess (wahr) oder None, wenn kein Terminal gefunden wurde.
    Unter Linux endet der Prozess erst mit dem Fenster; Windows Terminal und Terminal.app
    übergeben an ein laufendes Programm – dort sagt der Prozess nichts über das Fenster."""
    import shlex
    import shutil
    cwd = str(cwd or Path.home())
    env = clean_env()
    env.pop("WALKIE_SESSION", None)           # eine ganz normale, interaktive Session
    env.update(env_extra or {})
    kw = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL,
          "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if WIN:
        # npm-Shims (claude.cmd, codex.cmd, gemini.cmd) findet CreateProcess nicht ohne Endung
        argv = [shutil.which(argv[0]) or argv[0], *argv[1:]]
        if shutil.which("wt"):
            # wt trennt seine Kommandozeile an „;“ in mehrere Tabs – ein „;“ im Befehl (etwa im
            # bash -lc-Skript für WSL-Sessions) muss als „\;“ hinein, sonst startet wt den Rest
            # als eigenes Programm („Die angegebene Datei wurde nicht gefunden“)
            cmd = ["wt", "--title", title, "-d", cwd, *wt_escape(argv)]
        else:
            cmd = ["cmd", "/c", "start", title, "cmd", "/k", *argv]
        return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, **kw)
    if sys.platform == "darwin":
        exports = "".join(f"export {k}={shlex.quote(v)}; " for k, v in (env_extra or {}).items())
        script = f"cd {shlex.quote(cwd)} && {exports}{' '.join(shlex.quote(a) for a in argv)}"
        return subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to activate',
                                 "-e", f'tell application "Terminal" to do script {json_str(script)}'],
                                start_new_session=True, **kw)
    cmd = linux_terminal(argv, cwd)
    if cmd is None:
        return None
    return subprocess.Popen(cmd, start_new_session=True, **kw)


def json_str(text):
    import json
    return json.dumps(text)
