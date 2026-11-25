"""Austauschbare Coding-Agents, die im Terminal über dem Begleiter laufen.

Auswahl per WALKIE_AGENT: claude | codex | antigravity (agy) | gemini | custom.
Jeder Agent beschreibt:
  - wie er gestartet wird (Kommandozeile),
  - ob er Ereignisse an hook.py meldet (bereit / Prompt / fertig + Antworttext …),
  - ob er ein eingebautes Diktat hat (sonst transkribiert der Begleiter lokal mit Whisper).

Ohne Rückmeldung ("hooks": False) funktioniert alles außer dem Vorlesen der
Antwort: der Begleiter tippt den gesprochenen Satz ins Terminal, mehr nicht.
Jeder Agent kann sich nachträglich anbinden, indem er beim Antwortende
    python hook.py stop   (JSON {"last_assistant_message": "..."} auf stdin)
aufruft.

  python agents.py plugin-hooks   # hooks/hooks.json fürs Claude-Plugin neu erzeugen
  python agents.py uninstall      # globale Hooks (agy, gemini) und Walkie-Plugins entfernen
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import adapters  # noqa: E402
import settings  # noqa: E402
HOOK = [sys.executable, str(HERE / "hook.py")]
MARK = "walkie"

# Claude-Code-Hook -> Begleiter-Ereignis. Synchron laufen nur UserPromptSubmit (seine
# Ausgabe markiert gesprochene Nachrichten), Stop und PermissionRequest: Letzterer wartet
# auf eine gesprochene Antwort ("ja"/"nein"/Option). Der Dialog im Terminal erscheint
# trotzdem sofort – wer zuerst antwortet, gewinnt.
ASK_TIMEOUT = 150         # Sekunden; hook.py wartet selbst nur WALKIE_ASK_WAIT (120)
CLAUDE_EVENTS = [
    # (Hook, Matcher, Ereignis, async, Timeout)
    ("SessionStart", None, "ready", True, 10),
    ("UserPromptSubmit", None, "prompt", False, 10),
    ("PostToolUse", None, "tool", True, 10),
    ("PermissionRequest", None, "ask", False, ASK_TIMEOUT),   # auch AskUserQuestion
    ("Notification", None, "attention", True, 10),
    ("Stop", None, "stop", False, ASK_TIMEOUT),   # wartet ggf. auf gesprochene Antwort
    ("StopFailure", None, "error", True, 10),
    ("SessionEnd", None, "end", True, 10),
]


def claude_hooks(command, args_prefix):
    """Hook-Konfiguration im Claude-Format (für --settings und hooks/hooks.json)."""
    out = {}
    for hook, matcher, event, is_async, timeout in CLAUDE_EVENTS:
        h = {"type": "command", "command": command, "args": [*args_prefix, event],
             "timeout": timeout}
        if is_async:
            h["async"] = True
        entry = {"hooks": [h]}
        if matcher:
            entry["matcher"] = matcher
        out.setdefault(hook, []).append(entry)
    return out


class Agent:
    name = "custom"
    label = "Der Agent"
    hooks = False          # meldet die fertige Antwort (stop) an hook.py
    ready_hook = False     # meldet "bereit" beim Start (sonst: kurz warten)
    dictation = False      # eingebautes Diktat per Leertaste (Tap-Modus)

    def __init__(self, system_prompt, stt_mode):
        self.system_prompt = system_prompt
        self.stt_mode = stt_mode

    def command(self):
        cmd = settings.get("WALKIE_AGENT_CMD").strip()
        if not cmd:
            raise RuntimeError("WALKIE_AGENT=custom braucht WALKIE_AGENT_CMD, z. B. 'aider'")
        return shlex.split(cmd)

    def binary(self):
        """Programm, das gestartet wird (ohne Nebenwirkungen, für doctor.py)."""
        return self.command()[0]

    def new_session(self, task):
        """Kommandozeile für eine eigene, interaktive Session mit erstem Auftrag – oder None,
        wenn der Agent das nicht kann."""
        return None

    def terminal_command(self, conversation=None, resume=False):
        """Kommandozeile fürs Terminalfenster des Walkies: eine ganz normale, interaktive
        Session (Ereignisse kommen über Plugin bzw. globale Hooks). conversation = bekannte
        Gesprächs-ID; resume = das Fenster war schon einmal offen -> dasselbe Gespräch."""
        return self.command()

    @property
    def adapter(self):
        """Was der Walkie mit diesem Agent kann (adapters.py)."""
        return adapters.get(self.name)

    def capabilities(self):
        a = self.adapter
        return [label for cap, label in adapters.CAP_LABELS.items() if a and a.can(cap)]

    def doctor(self):
        """Liste (ok, Text) für `doctor.py`."""
        return []


class ClaudeCode(Agent):
    name, label = "claude", "Claude"
    hooks = ready_hook = dictation = True

    def terminal_command(self, conversation=None, resume=False):
        """Feste Session-ID: beim ersten Öffnen vergeben, danach fortgesetzt – sofern Claude
        schon ein Transcript dazu hat (sonst gäbe --resume einen Fehler)."""
        binary = os.environ.get("WALKIE_CLAUDE_BIN", "claude")
        if conversation and resume and claude_transcript(conversation):
            return [binary, "--resume", conversation]
        return [binary, "--session-id", conversation] if conversation else [binary]

    def command(self):
        cfg = {"hooks": claude_hooks(HOOK[0], HOOK[1:])}
        if self.stt_mode == "claude":
            cfg["voice"] = {"enabled": True, "mode": "tap"}
        model = settings.get("WALKIE_AGENT_MODEL")
        return [os.environ.get("WALKIE_CLAUDE_BIN", "claude"),
                *(["--model", model] if model else []),
                "--append-system-prompt", self.system_prompt,
                "--settings", json.dumps(cfg)]


class Codex(Agent):
    """OpenAI Codex CLI. 'notify' beim Antwortende (JSON als letztes Argument)
    reicht fürs Vorlesen und braucht kein Feature-Flag."""
    name, label = "codex", "Codex"
    hooks = True

    def new_session(self, task):
        return [os.environ.get("WALKIE_CODEX_BIN", "codex"), task]

    def terminal_command(self, conversation=None, resume=False):
        binary = os.environ.get("WALKIE_CODEX_BIN", "codex")
        if conversation:
            return [binary, "resume", conversation]
        return [binary, "resume", "--last"] if resume else [binary]

    def command(self):
        notify = json.dumps([*HOOK, "codex"])
        binary = os.environ.get("WALKIE_CODEX_BIN", "codex")
        args = [binary, "-c", f"notify={notify}",
                "-c", f"developer_instructions={json.dumps(self.system_prompt)}"]
        if sys.platform.startswith("linux"):
            # The foreground process must own the rollout for terminal reply routing.
            try:
                help_text = subprocess.run([binary, "--help"], capture_output=True,
                                           timeout=3).stdout
                if b"--no-daemon" in help_text:
                    args.append("--no-daemon")
            except (OSError, subprocess.TimeoutExpired):
                pass
        return args


class GlobalHooks(Agent):
    """Agents ohne Hook-Flag: Hooks werden unter dem Namen 'walkie' in deren
    globale Konfiguration eingetragen. Fremde Einträge bleiben unberührt, kaputte
    Dateien werden nicht angefasst, `python agents.py uninstall` räumt wieder auf."""
    hooks = ready_hook = True
    FILE: Path

    def entries(self):
        raise NotImplementedError

    def merge(self, cfg):
        raise NotImplementedError

    def unmerge(self, cfg):
        raise NotImplementedError

    def install_hooks(self):
        f = self.FILE
        try:
            cfg = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except json.JSONDecodeError:
            return False
        new = self.merge(json.loads(json.dumps(cfg)))
        if new != cfg:
            write_json(f, new)
        return True

    def uninstall_hooks(self):
        try:
            cfg = json.loads(self.FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        new = self.unmerge(json.loads(json.dumps(cfg)))
        if new != cfg:
            write_json(self.FILE, new)

    def doctor(self):
        try:
            cfg = json.loads(self.FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [(None, f"{self.FILE} fehlt noch – wird beim ersten Start angelegt")]
        except (OSError, json.JSONDecodeError):
            return [(False, f"{self.FILE} ist kein gültiges JSON – Hooks werden nicht eingetragen")]
        ok = self.merge(json.loads(json.dumps(cfg))) == cfg
        return [(ok if ok else None, f"Hooks in {self.FILE}: "
                 + ("eingetragen" if ok else "werden beim Start eingetragen"))]


class Antigravity(GlobalHooks):
    """Google Antigravity CLI (`agy`): ~/.gemini/config/hooks.json, Gruppen nach Namen."""
    name, label = "antigravity", "Antigravity"
    FILE = Path.home() / ".gemini" / "config" / "hooks.json"

    def entries(self):
        cmd = shell_join(HOOK)
        out = {}
        for ev in ("SessionStart", "PreInvocation", "Stop"):
            out[ev] = [{"type": "command", "command": f"{cmd} agy {ev}", "timeout": 10}]
        out["PostToolUse"] = [{"matcher": "*", "hooks": [
            {"type": "command", "command": f"{cmd} agy PostToolUse", "timeout": 10}]}]
        return out

    def merge(self, cfg):
        cfg[MARK] = self.entries()
        return cfg

    def unmerge(self, cfg):
        cfg.pop(MARK, None)
        return cfg

    def binary(self):
        return os.environ.get("WALKIE_AGY_BIN", "agy")

    def new_session(self, task):
        return [self.binary(), "--prompt-interactive", task]

    def terminal_command(self, conversation=None, resume=False):
        self.install_hooks()
        if conversation:
            return [self.binary(), "--conversation", conversation]
        return [self.binary(), "--continue"] if resume else [self.binary()]

    def command(self):
        self.install_hooks()
        return [self.binary()]


class Gemini(GlobalHooks):
    """Google Gemini CLI: Claude-artige Hooks in ~/.gemini/settings.json (timeout in ms).
    Unsere Einträge erkennt man am Namen 'walkie'."""
    name, label = "gemini", "Gemini"
    FILE = Path.home() / ".gemini" / "settings.json"
    EVENTS = tuple(adapters.ADAPTERS["gemini"].event_map)

    def entries(self):
        cmd = shell_join(HOOK)
        return {ev: {"hooks": [{"type": "command", "name": MARK,
                                "command": f"{cmd} gemini {ev}", "timeout": 5000}]}
                for ev in self.EVENTS}

    @staticmethod
    def _ours(entry):
        return isinstance(entry, dict) and any(
            isinstance(h, dict) and h.get("name") == MARK for h in entry.get("hooks", []))

    def unmerge(self, cfg):
        hooks = cfg.get("hooks")
        if not isinstance(hooks, dict):
            return cfg
        for ev in list(hooks):
            if isinstance(hooks[ev], list):
                hooks[ev] = [e for e in hooks[ev] if not self._ours(e)]
                if not hooks[ev]:
                    del hooks[ev]
        if not hooks:
            del cfg["hooks"]
        return cfg

    def merge(self, cfg):
        cfg = self.unmerge(cfg)
        hooks = cfg.setdefault("hooks", {})
        for ev, entry in self.entries().items():
            hooks.setdefault(ev, []).append(entry)
        return cfg

    def binary(self):
        return os.environ.get("WALKIE_GEMINI_BIN", "gemini")

    def new_session(self, task):
        return [self.binary(), "--prompt-interactive", task]

    def command(self):
        self.install_hooks()
        return [self.binary()]


def shell_join(argv):
    """Befehlszeile für die globalen Hook-Dateien: Antigravity und Gemini führen sie über die
    System-Shell aus – unter Windows cmd.exe, das keine einfachen Anführungszeichen kennt."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return " ".join(shlex.quote(p) for p in argv)


def claude_transcript(session_id):
    """Gibt es ein Claude-Code-Transcript zu dieser Session (also etwas zum Fortsetzen)?"""
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    try:
        return any(base.glob(f"*/{session_id}.jsonl"))
    except OSError:
        return False


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


AGENTS = {a.name: a for a in (ClaudeCode, Codex, Antigravity, Gemini, Agent)}
AGENTS["agy"] = Antigravity


def uninstall():
    """Alles entfernen, was außerhalb des Repos eingetragen wurde."""
    for cls in (Antigravity, Gemini):
        cls("", "whisper").uninstall_hooks()
    import plugins
    plugins.uninstall()


def make_agent(system_prompt, stt_mode):
    key = (os.environ.get("WALKIE_AGENT") or settings.get("WALKIE_AGENT")).strip().lower()
    cls = AGENTS.get(key)
    if cls is None:
        raise RuntimeError(f"Unbekannter Agent '{key}' – möglich: {', '.join(AGENTS)}")
    return cls(system_prompt, stt_mode)


if __name__ == "__main__":
    if sys.argv[1:] == ["uninstall"]:
        uninstall()
        print("Hooks entfernt.")
    elif sys.argv[1:] == ["plugin-hooks"]:
        # Das Plugin braucht keine Python-Hooks mehr: hooks/session.tsx (Mod) meldet alles
        # plattformneutral an die App; hook.py dient nur noch dem eigenen Terminal.
        write_json(HERE / "hooks" / "hooks.json", {"modules": ["./main.tsx"]})
        print("hooks/hooks.json aktualisiert.")
    else:
        print(__doc__)
