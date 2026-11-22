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


def open_terminal(argv, cwd=None, title="Claude"):
    """Programm in einem neuen, sichtbaren Terminalfenster starten (z. B. eine neue
    Claude-Session). Linux: kitty/konsole/gnome-terminal/…, macOS: Terminal.app,
    Windows: Windows Terminal, sonst cmd. Rückgabe: True, wenn ein Terminal gestartet wurde."""
    import shlex
    import shutil
    cwd = str(cwd or Path.home())
    env = clean_env()
    env.pop("WALKIE_SESSION", None)           # eine ganz normale, interaktive Session
    kw = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL,
          "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if WIN:
        if shutil.which("wt"):
            cmd = ["wt", "-d", cwd, *argv]
        else:
            cmd = ["cmd", "/c", "start", title, "cmd", "/k", *argv]
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, **kw)
        return True
    if sys.platform == "darwin":
        script = f"cd {shlex.quote(cwd)} && {' '.join(shlex.quote(a) for a in argv)}"
        subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to activate',
                          "-e", f'tell application "Terminal" to do script {json_str(script)}'],
                         start_new_session=True, **kw)
        return True
    for prog, pre in (("kitty", ["--title", title, "--directory", cwd]),
                      ("konsole", ["--workdir", cwd, "-e"]),
                      ("gnome-terminal", [f"--working-directory={cwd}", "--"]),
                      ("xfce4-terminal", [f"--working-directory={cwd}", "-x"]),
                      ("x-terminal-emulator", ["-e"]), ("xterm", ["-e"])):
        if shutil.which(prog):
            subprocess.Popen([prog, *pre, *argv], start_new_session=True, **kw)
            return True
    return False


def json_str(text):
    import json
    return json.dumps(text)
