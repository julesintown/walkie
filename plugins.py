"""Das Walkie-Plugin in Claude Code und Codex eintragen, damit sich auch selbst gestartete
Sessions beim Walkie melden (nur Standardbibliothek).

Ohne Plugin kennt der Walkie nur die Sessions, die er selbst im Terminal öffnet: Die bekommen
ihre Hooks per Kommandozeile. Bei Antigravity und Gemini trägt agents.py die Hooks in deren
globale Datei ein; Claude Code und Codex haben dafür ihr Plugin-System.

Jeder Agent wird höchstens einmal eingerichtet (RUN/plugins.json). Wer das Plugin danach selbst
entfernt, bekommt es nicht ungefragt wieder. `python plugins.py uninstall` (und
`python agents.py uninstall`) entfernt nur, was der Walkie selbst eingetragen hat.

  python plugins.py            # Stand anzeigen
  python plugins.py install    # jetzt einrichten
  python plugins.py uninstall  # wieder entfernen
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from paths import clean_env, no_window  # noqa: E402

STATE = None             # RUN/plugins.json – erst beim Aufruf, hook legt RUN beim Import fest
PLUGIN = "walkie@walkie"
MARKETPLACE = "walkie"
GITHUB = "julesintown/walkie"
TIMEOUT = 120


def _bin(agent):
    return os.environ.get(f"WALKIE_{agent.upper()}_BIN", agent)


def source():
    """Woher das Plugin kommt: dieses Repo – außer der Walkie läuft selbst aus dem Cache eines
    Plugins. Der Ordner wechselt bei jedem Update, dann lieber GitHub."""
    caches = [Path.home() / ".claude" / "plugins", Path.home() / ".codex" / "plugins"]
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        caches.append(Path(os.environ["CLAUDE_CONFIG_DIR"]) / "plugins")
    if any(HERE.is_relative_to(c) for c in caches):
        return GITHUB
    return str(HERE)


def _run(argv):
    """-> (ok, Ausgabe). Ohne Konsolenfenster (Windows) und ohne Variablen einer umgebenden
    Claude-Session."""
    exe = shutil.which(argv[0])
    if not exe:
        return False, f"{argv[0]} nicht gefunden"
    try:
        r = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=TIMEOUT,
                           stdin=subprocess.DEVNULL, env=clean_env(), **no_window())
    except (OSError, subprocess.TimeoutExpired) as ex:
        return False, repr(ex)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def claude_installed():
    """Ist irgendein walkie-Plugin in Claude Code installiert? None = unbekannt."""
    ok, out = _run([_bin("claude"), "plugin", "list", "--json"])
    if not ok:
        return None
    try:
        return any(str(p.get("id", "")).startswith("walkie@") for p in json.loads(out))
    except (ValueError, AttributeError):
        return None


def codex_installed():
    """`codex plugin list` fragt entfernte Marketplaces ab und braucht oft über eine Minute –
    die Config sagt dasselbe sofort."""
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        text = (home / "config.toml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError:
        return None
    try:
        import tomllib
    except ImportError:                       # Python 3.10: Tabellenköpfe reichen dafür
        import re
        return bool(re.search(r'^\s*\[plugins\.["\']?walkie@', text, re.M))
    try:
        cfg = tomllib.loads(text)
    except Exception:  # noqa: BLE001 – kaputte Datei
        return None
    return any(k.startswith("walkie@") for k in cfg.get("plugins", {}))


AGENTS = {
    "claude": {
        "label": "Claude Code",
        "installed": claude_installed,
        "add": lambda b, src: [[b, "plugin", "marketplace", "add", src],
                               [b, "plugin", "install", PLUGIN]],
        "remove": lambda b: [[b, "plugin", "uninstall", PLUGIN],
                             [b, "plugin", "marketplace", "remove", MARKETPLACE]],
    },
    "codex": {
        "label": "Codex",
        "installed": codex_installed,
        "add": lambda b, src: [[b, "plugin", "marketplace", "add", src],
                               [b, "plugin", "add", PLUGIN]],
        "remove": lambda b: [[b, "plugin", "remove", PLUGIN],
                             [b, "plugin", "marketplace", "remove", MARKETPLACE]],
    },
}


def state_file():
    if STATE is not None:
        return STATE
    from hook import RUN
    return RUN / "plugins.json"


def load_state():
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        f = state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    except OSError:
        pass


def ensure(log=print, force=False):
    """Fehlende Plugins einmalig einrichten (force: auch nochmal, wenn schon einmal erledigt). -> Liste der Agents (Label), die es neu haben.
    Dauert einige Sekunden: im Hintergrund aufrufen."""
    state = load_state()
    added = []
    for name, a in AGENTS.items():
        b = _bin(name)
        if (name in state and not force) or not shutil.which(b):
            continue                     # schon einmal erledigt, oder Agent nicht installiert
        have = a["installed"]()
        if have is None:
            log(f"plugin {name}: Stand unbekannt – nichts geändert")
            continue
        if have:
            state[name] = {"by": "user"}
            continue
        src = source()
        add_market, install = a["add"](b, src)
        ok, out = _run(add_market)
        if not ok and "already" not in out.lower() and "exist" not in out.lower():
            log(f"plugin {name}: marketplace {src}: {out[-300:]}")
        ok, out = _run(install)
        if not ok:
            log(f"plugin {name}: installieren fehlgeschlagen: {out[-300:]}")
            continue                     # beim nächsten Start nochmal versuchen
        log(f"plugin {name}: {PLUGIN} eingerichtet (aus {src})")
        state[name] = {"by": "walkie", "source": src}
        added.append(a["label"])
    save_state(state)
    return added


def uninstall(log=print):
    """Nur entfernen, was der Walkie selbst eingetragen hat."""
    state = load_state()
    for name, a in AGENTS.items():
        if state.get(name, {}).get("by") != "walkie":
            continue
        for argv in a["remove"](_bin(name)):
            ok, out = _run(argv)
            if not ok:
                log(f"plugin {name}: {' '.join(argv[1:])}: {out[-300:]}")
        state.pop(name)
    save_state(state)


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["install"]:
        print("Neu eingerichtet: " + (", ".join(ensure(force=True)) or "nichts"))
    elif cmd == ["uninstall"]:
        uninstall()
        print("Walkie-Plugins entfernt.")
    else:
        print(__doc__)
        for name, a in AGENTS.items():
            if shutil.which(_bin(name)):
                have = a["installed"]()
                print(f"  {a['label']}: " + {True: "Plugin installiert", False: "kein Plugin",
                                             None: "unbekannt"}[have])
