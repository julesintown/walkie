#!/usr/bin/env python3
"""Agent-Hook: meldet Ereignisse von Agent-Sessions an den Begleiter (nur Standardbibliothek).

Aufruf:
  hook.py <ready|prompt|tool|attention|ask|error|stop|end>   Claude-Code-Format (JSON auf stdin)
      ask  = PermissionRequest: wartet auf gesprochenes ja/nein/Option (Ausgabe: decision)
      stop = endet die Antwort mit einer Frage, wartet er auf eine gesprochene Antwort
             und setzt die Session damit fort (Ausgabe: {"decision": "block", …})
  hook.py --plugin <…>        dasselbe aus dem Claude-Plugin (feuert in jeder Session)
  hook.py --plugin-codex <…>  dasselbe aus dem Codex-Plugin (Hook-Format wie bei Claude)
  hook.py codex '<json>'      Codex-'notify' (JSON als Argument)
  hook.py agy <Event>         Antigravity CLI (SessionStart|PreInvocation|PostToolUse|Stop)
  hook.py gemini <Event>      Gemini CLI (SessionStart|BeforeAgent|AfterTool|Notification|AfterAgent|SessionEnd)
Eigene Agents: `hook.py stop` mit {"last_assistant_message": "..."} auf stdin.

Jedes Ereignis wird als eine JSON-Zeile an <RUN>/events.jsonl angehängt:
  {"event", "ts", "session", "own", "agent", ["project"], ["reason"], ["detail"],
   ["text"], ["voice"], ["req", "tool", "questions"]}
"req" = Anfrage, auf die der Hook wartet; der Begleiter legt die Antwort als
<RUN>/answers/<req>.json ab.
"own" = Session, die der Begleiter selbst im Terminal gestartet hat (nur deren
Antworten werden vorgelesen).
"""
import json
import os

from i18n import spoken_prompt, t
import tempfile
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Gemeinsamer Statusordner von Hook und Begleiter – unabhängig davon, wo hook.py liegt
# (Repo, Claude-Plugin-Cache, …).
RUN = Path(os.environ.get("WALKIE_RUN") or Path(
    os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "walkie")
EVENTS = RUN / "events.jsonl"
ANSWERS = RUN / "answers"            # gesprochene Antworten auf Anfragen (<req>.json)
LEARN_FLAG = RUN / "learn"           # GUI/CLI: Kopfhörertasten anlernen statt ausführen
LEARN_LOG = RUN / "learn.jsonl"
LOCK = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "walkie.lock"
SERVER = RUN / "server.json"         # Port/Token/PID der laufenden App (bridge.py)
VOICE_NOTE = ("(Diese Nachricht wurde per Mikrofon gesprochen – als gesprochen markiert. "
              "Deine Antwort wird vorgelesen: kurz, natürlich, ohne Markdown.)")

# Claude Code: Notification-Typen, bei denen "Du bist dran!" angezeigt wird.
# permission_prompt fehlt absichtlich – das meldet schon PermissionRequest (sonst doppelt).
ATTENTION_TYPES = {"agent_needs_input", "elicitation_dialog", "elicitation_url_dialog"}
import adapters  # noqa: E402 – Ereignis-Übersetzung je Agent an einer Stelle
AGY_EVENTS = adapters.ADAPTERS["antigravity"].event_map
GEMINI_EVENTS = adapters.ADAPTERS["gemini"].event_map


# ------------------------------------------------------------------ Transcripts
def last_assistant_text(transcript):
    """Claude Code: letzter Text-Block der letzten Assistant-Antwort."""
    try:
        lines = Path(transcript).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = e.get("message") or {}
        if e.get("type") == "user":
            content = msg.get("content")
            is_tool_result = isinstance(content, list) and any(
                isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
            if not is_tool_result:
                return ""  # echte Nutzer-Eingabe erreicht -> keine Antwort danach
        if e.get("type") == "assistant":
            for c in reversed(msg.get("content") or []):
                if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                    return c["text"].strip()
    return ""


def _texts(node, out):
    """Alle Text-Stücke einer Assistant-/Modell-Nachricht einsammeln (formattolerant)."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for n in node:
            _texts(n, out)
    elif isinstance(node, dict):
        if node.get("type") in ("thinking", "tool_use", "tool_call", "function_call"):
            return
        for k in ("text", "content", "parts", "message", "response"):
            if k in node:
                _texts(node[k], out)


def last_model_text(transcript):
    """Andere Agents: letzte Modell-Antwort aus einem JSONL-Transcript (Format nicht
    dokumentiert -> tolerant: letzte Zeile mit Rolle/Typ assistant|model|agent)."""
    try:
        lines = Path(transcript).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict):
            continue
        role = str(e.get("role") or e.get("type") or e.get("source")
                   or (e.get("message") or {}).get("role") or "").lower()
        if role in ("user", "human"):
            return ""
        if any(r in role for r in ("assistant", "model", "agent", "planner")):
            out = []
            _texts(e, out)
            text = "\n".join(t for t in out if t.strip()).strip()
            if text:
                return text
    return ""


def retry(fn, *args):
    """Transcript wird evtl. gerade noch geschrieben -> kurz nachfassen."""
    for _ in range(6):
        text = fn(*args)
        if text:
            return text
        time.sleep(0.25)
    return ""


# ------------------------------------------------------------------ Hilfen
def read_stdin():
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def setting(key):
    """Zentrale Einstellung (settings.py, ~/.config/walkie/config.env) – dieselbe
    Datei, egal ob hook.py im Repo oder im Plugin-Cache liegt."""
    sys.path.insert(0, str(HERE))
    import settings
    return settings.get(key)


def server_info():
    try:
        return json.loads(SERVER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def acquire_lock():
    """Einzige Instanz sicherstellen: offenes Lock-Handle oder None (schon belegt)."""
    f = open(LOCK, "a+", encoding="ascii")
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def bridge_ready():
    info = server_info()
    if info:
        from http.client import HTTPException
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/health", timeout=1.5) as r:
                return json.load(r).get("ok") is True
        except (OSError, ValueError, KeyError, TypeError, AttributeError, HTTPException):
            pass                              # z. B. veraltete server.json
    return False


def walkie_running():
    """Der Dienst antwortet oder eine Instanz hält das Lock beim Start/Herunterfahren."""
    if bridge_ready():
        return True
    try:
        lock = acquire_lock()
    except OSError:
        return False
    if lock is None:
        return True
    lock.close()
    return False


def autostart():
    """Plugin: mit der ersten Claude-Session den Begleiter starten (WALKIE_AUTOSTART=1)."""
    if not setting("WALKIE_AUTOSTART"):
        return
    if not (HERE / ".venv").exists() or walkie_running():
        return
    subprocess.Popen([str(HERE / "start.sh")], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def emit(out):
    RUN.mkdir(parents=True, exist_ok=True)
    try:
        if EVENTS.stat().st_size > 512_000:      # klein halten; der Begleiter liest nur neu
            EVENTS.write_text("", encoding="utf-8")
    except OSError:
        pass
    line = (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(EVENTS, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)                       # eine Zeile, ein write -> atomar angehängt
    finally:
        os.close(fd)


def detail(data):
    """Kurzbeschreibung einer Freigabe/Rückfrage zum Vorlesen, z. B. die Frage selbst
    oder was ein Befehl tut."""
    inp = data.get("tool_input")
    if not isinstance(inp, dict):
        return ""
    if data.get("tool_name") == "AskUserQuestion":
        qs = inp.get("questions") or []
        text = " ".join(str(q.get("question", "")) for q in qs if isinstance(q, dict))
    else:
        text = (inp.get("description") or inp.get("command") or inp.get("file_path")
                or inp.get("url") or "")
        if inp.get("file_path") and not inp.get("description"):
            text = Path(str(text)).name
    return str(text).strip()[:200]


# ------------------------------------------------------------------ Sprach-Freigaben


def questions(data):
    """AskUserQuestion -> [{"question", "options": [Labels], "multi"}] zum Vorlesen."""
    inp = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    out = []
    for q in inp.get("questions") or []:
        if isinstance(q, dict) and q.get("question"):
            opts = [str(o.get("label")) for o in q.get("options") or []
                    if isinstance(o, dict) and o.get("label")]
            out.append({"question": str(q["question"]), "options": opts,
                        "multi": bool(q.get("multiSelect"))})
    return out


def ends_with_question(text):
    """Endet die Antwort mit einer Frage an den Nutzer? (letzter Absatz enthält ein '?')"""
    import re
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S).strip()
    if not text:
        return False
    last = re.split(r"\n\s*\n", text)[-1]
    return "?" in last[-400:]


def wait_answer(req, limit=None):
    """Wartet auf die gesprochene Antwort, die der Begleiter als <req>.json ablegt.
    Der Dialog im Terminal läuft parallel; ohne Antwort -> None (Claude fragt normal)."""
    limit = float(limit or setting("WALKIE_ASK_WAIT"))
    path = ANSWERS / f"{req}.json"
    end = time.time() + limit
    n = 0
    while time.time() < end:
        if path.exists():
            try:
                answer = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
                continue
            path.unlink(missing_ok=True)
            return answer if answer.get("behavior") in ("allow", "deny", "reply") else None
        n += 1
        if n % 25 == 0 and not walkie_running():
            return None
        time.sleep(0.2)
    return None


def decision(answer, data):
    """Antwort des Begleiters -> PermissionRequest-Ausgabe für Claude Code."""
    d = {"behavior": answer["behavior"]}
    if d["behavior"] == "deny":
        d["message"] = str(answer.get("message") or "Per Sprache abgelehnt.")
    else:
        # Claude Code wertet "allow" ohne updatedInput bei manchen Tools (ExitPlanMode,
        # AskUserQuestion) als Ablehnung -> Eingabe immer unverändert mitschicken.
        inp = dict(data.get("tool_input") or {})
        if answer.get("answers") is not None:          # AskUserQuestion beantwortet
            inp["answers"] = answer["answers"]
        d["updatedInput"] = inp
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": d}}


# ------------------------------------------------------------------ main
def parse(argv):
    """-> (event, data, agent) im einheitlichen Format oder None."""
    kind = argv[0] if argv else "?"
    if kind == "codex":
        try:
            note = json.loads(argv[1])
        except (IndexError, json.JSONDecodeError):
            return None
        if note.get("type") != "agent-turn-complete":
            return None
        return "stop", {"turn_id": note.get("turn-id"),
                        "session_id": note.get("thread-id") or note.get("turn-id"),
                        "last_assistant_message": note.get("last-assistant-message") or ""}, "codex"
    if kind in ("agy", "gemini"):
        table = AGY_EVENTS if kind == "agy" else GEMINI_EVENTS
        event = table.get(argv[1] if len(argv) > 1 else "")
        if not event:
            return None
        data = read_stdin()
        data["session_id"] = data.get("session_id") or data.get("conversationId")
        if event == "stop":
            if kind == "agy" and not data.get("fullyIdle", True):
                return None                      # Agent arbeitet noch weiter
            text = data.get("prompt_response") or ""
            if not isinstance(text, str):
                out = []
                _texts(text, out)
                text = "\n".join(out)
            data["last_assistant_message"] = text or retry(
                last_model_text, data.get("transcriptPath") or data.get("transcript_path") or "")
        return event, data, ("antigravity" if kind == "agy" else "gemini")
    return kind, read_stdin(), "claude"


def main():
    if os.environ.get("WALKIE_HOOK_QUIET"):
        return                          # Denk-Aufruf des Walkies selbst (router.py), keine Session
    argv = sys.argv[1:]
    codex_plugin = argv[:1] == ["--plugin-codex"]     # Codex plugin: Claude-style hook input
    plugin = argv[:1] in (["--plugin"], ["--plugin-codex"])
    if plugin:
        # Plugin-Hooks feuern in jeder Claude-Session. In der Session, die der Begleiter
        # selbst gestartet hat, melden schon dessen eigene Hooks -> nicht doppelt.
        if os.environ.get("WALKIE_SESSION"):
            return
        argv = argv[1:]
    parsed = parse(argv)
    if not parsed:
        return
    event, data, agent = parsed
    if codex_plugin:
        agent = "codex"
    own = bool(os.environ.get("WALKIE_SESSION"))
    ask = event == "ask"                   # PermissionRequest: Freigabe oder Rückfrage
    if ask:
        event = "attention"

    if event == "attention":
        kind = data.get("notification_type")
        if kind and kind not in ATTENTION_TYPES and agent == "claude":
            return
        tool = data.get("tool_name")
        data["reason"] = data.get("message") or (
            t("Rückfrage für dich") if tool == "AskUserQuestion"
            else t("Freigabe nötig: {tool}", tool=tool) if tool else "")
    elif event == "error":
        data["reason"] = data.get("error_type") or data.get("error") or t("Fehler")
    else:
        data.pop("reason", None)                 # z. B. SessionEnd hat ein eigenes "reason"

    out = {"event": event, "ts": time.time(), "agent": agent, "own": own,
           "session": str(data.get("session_id") or ("own" if own else agent))}
    if os.environ.get("WALKIE_IN_TERMINAL"):
        out["terminal"] = True            # Terminalfenster des Walkies: Gespräch merken
    if agent == "codex" and data.get("turn_id"):
        out["turn_id"] = data["turn_id"]
    if data.get("reason"):
        out["reason"] = str(data["reason"])[:200]
    if data.get("cwd"):
        out["project"] = Path(str(data["cwd"])).name
    if event == "attention":
        out["detail"] = detail(data)
        inp = data.get("tool_input")
        if data.get("tool_name") == "Bash" and isinstance(inp, dict) and inp.get("command"):
            out["command"] = str(inp["command"])[:500]     # für die Risiko-Prüfung (risk.py)

    flag = RUN / "voice_pending"
    if event == "prompt" and own and flag.exists():
        flag.unlink(missing_ok=True)
        out["voice"] = True
        if agent == "claude":
            print(spoken_prompt(VOICE_NOTE))          # stdout eines UserPromptSubmit-Hooks -> Kontext für Claude
    if event == "stop":
        text = data.get("last_assistant_message") or ""
        if not text and agent == "claude" and data.get("transcript_path"):
            text = retry(last_assistant_text, data["transcript_path"])
        out["text"] = text
    req = None
    # Antwort endet mit einer Frage -> auf gesprochene Antwort warten und die Session damit
    # fortsetzen (Stop-Hook "decision: block"). Nicht in der eigenen Terminal-Session, die
    # hat ihren eigenen Sprachfluss.
    reply = (event == "stop" and agent == "claude" and not own and ends_with_question(out["text"])
             and walkie_running()
             and setting("WALKIE_VOICE_REPLY") and setting("WALKIE_ANNOUNCE"))
    if reply:
        req = f"{os.getpid()}-{time.time_ns()}"
        out["req"] = req
    if ask and walkie_running():
        req = f"{os.getpid()}-{time.time_ns()}"
        out["req"] = req
        out["tool"] = str(data.get("tool_name") or "")
        if out["tool"] == "AskUserQuestion":
            out["questions"] = questions(data)
    emit(out)
    if req and reply:
        answer = wait_answer(req, setting("WALKIE_REPLY_WAIT"))
        if answer and answer.get("behavior") == "reply" and answer.get("text"):
            print(json.dumps({"decision": "block", "reason": (
                "Antwort des Nutzers auf deine Frage, per Sprache über den Walkie "
                "(Spracherkennung, kann sich verhört haben): " + spoken_prompt(str(answer["text"])))},
                ensure_ascii=False))
        return
    if req:
        answer = wait_answer(req)
        if answer:
            print(json.dumps(decision(answer, data), ensure_ascii=False))
    if event == "ready" and plugin:
        autostart()


if __name__ == "__main__":
    main()
