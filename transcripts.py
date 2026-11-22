"""Worum geht es in einer laufenden Claude-Code-Session? Direkt aus ihrem Transcript gelesen.

Claude Code speichert jede Session unter ~/.claude/projects/<ordner>/<session-id>.jsonl.
Daraus holt sich der Router Thema (erste Nutzer-Nachricht), letzte Nutzer-Nachricht und letzte
Antwort – unabhängig davon, was der Walkie selbst mitbekommen hat (Neustarts, Plugin-Versionen).
Nur Anfang und Ende der Datei werden gelesen; Ergebnisse werden nach Größe/Zeit zwischengespeichert.
"""
import json
import os
from pathlib import Path

PROJECTS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
HEAD = 256 * 1024
TAIL = 512 * 1024
_cache = {}


def find(sid):
    if not sid or not PROJECTS.is_dir():
        return None
    for p in PROJECTS.glob(f"*/{sid}.jsonl"):
        return p
    return None


def _user_text(e):
    """Text einer echten Nutzer-Nachricht (keine Werkzeug-Ergebnisse, keine Meta-Einträge)."""
    if e.get("type") != "user" or e.get("isMeta"):
        return ""
    content = (e.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
            return ""
        text = " ".join(c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text")
    else:
        return ""
    text = text.strip()
    if text.startswith("<") or not text:          # Befehle, Hinweise, System-Einschübe
        return ""
    for prefix in ("The walkie plugin sent a message:",):   # per Stimme gekommen
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def _assistant_text(e):
    if e.get("type") != "assistant":
        return ""
    for c in reversed((e.get("message") or {}).get("content") or []):
        if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
            return c["text"].strip()
    return ""


def _lines(data):
    for line in data.splitlines():
        try:
            yield json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue


def context(sid):
    """{"topic", "last_user", "last_answer"} einer Session – leer, wenn nichts gefunden."""
    path = find(sid)
    if path is None:
        return {}
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (sid, st.st_size, st.st_mtime_ns)
    if _cache.get(sid, (None,))[0] == key:
        return _cache[sid][1]
    out = {}
    try:
        with open(path, "rb") as f:
            head = f.read(HEAD)
            f.seek(max(0, st.st_size - TAIL))
            tail = f.read()
    except OSError:
        return {}
    for e in _lines(head.decode("utf-8", "ignore")):
        t = _user_text(e)
        if t:
            out["topic"] = t[:300]
            break
    last_user = last_answer = ""
    for e in _lines(tail.decode("utf-8", "ignore")):
        t = _user_text(e)
        if t:
            last_user = t
        a = _assistant_text(e)
        if a:
            last_answer = a
    if last_user:
        out["last_user"] = last_user[:300]
    if last_answer:
        out["last_answer"] = last_answer[-400:]
    _cache[sid] = (key, out)
    return out
