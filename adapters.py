"""Ein Adapter je Coding-Agent – eine Stelle, die beschreibt, was der Walkie mit ihm kann
(Idee aus Clawd on Desk: ein deklarativer Eintrag pro Agent). Nur Standardbibliothek, weil
hook.py sie bei jedem Ereignis lädt.

Gemeinsame Ereignisse (hook.py -> Begleiter):
  ready · prompt · tool · attention (+ req = wartet auf Freigabe) · stop · error · end

Fähigkeiten:
  events       welche gemeinsamen Ereignisse der Agent liefert
  approvals    Freigaben/Rückfragen per Stimme beantworten (wartender Hook)
  read_answers fertige Antworten vorlesen (stop mit Text)
  voice_reply  endet eine Antwort mit einer Frage: per Stimme antworten und fortsetzen
  route_to     gesprochene Sätze in eine laufende Session schicken
  new_session  neue Session mit Auftrag öffnen (Kommandozeile)
  dictation    eingebautes Diktat (sonst Whisper lokal)
  think        kann als Denkmodell für Routing/Zusammenfassungen dienen (-p / exec)
"""

COMMON = ("ready", "prompt", "tool", "attention", "stop", "error", "end")


class Adapter:
    def __init__(self, name, label, source, event_map=None, binary=None, aliases=(), **caps):
        self.name, self.label, self.source = name, label, source
        self.event_map = dict(event_map or {})
        self.binary = binary or name
        self.aliases = tuple(aliases)
        self.caps = {"events": tuple(caps.pop("events", ())), "approvals": False,
                     "read_answers": False, "voice_reply": False, "route_to": False,
                     "new_session": False, "dictation": False, "think": False}
        self.caps.update(caps)

    def normalize(self, native):
        """Natives Ereignis -> gemeinsames Ereignis (oder None, wenn uninteressant)."""
        if not self.event_map:
            return native if native in COMMON or native == "ask" else None
        return self.event_map.get(native)

    def can(self, cap):
        return bool(self.caps.get(cap))


ADAPTERS = {a.name: a for a in (
    Adapter("claude", "Claude Code", "plugin (hooks/session.tsx) + Hooks im eigenen Terminal",
            events=COMMON, approvals=True, read_answers=True, voice_reply=True, route_to=True,
            new_session=True, dictation=True, think=True),
    Adapter("codex", "Codex", "Plugin-Hooks (.codex-plugin) + notify",
            events=("ready", "prompt", "tool", "attention", "stop"), approvals=True,
            read_answers=True, route_to=False, new_session=True, think=True),
    Adapter("antigravity", "Antigravity", "globale Hooks (~/.gemini/config/hooks.json)",
            event_map={"SessionStart": "ready", "PreInvocation": "prompt",
                       "PostToolUse": "tool", "Stop": "stop"},
            binary="agy", aliases=("agy",),
            events=("ready", "prompt", "tool", "stop"), read_answers=True, new_session=True,
            think=True),
    Adapter("gemini", "Gemini CLI", "globale Hooks (~/.gemini/settings.json)",
            event_map={"SessionStart": "ready", "BeforeAgent": "prompt", "AfterTool": "tool",
                       "Notification": "attention", "AfterAgent": "stop",
                       "SessionEnd": "end"},
            events=("ready", "prompt", "tool", "attention", "stop", "end"), read_answers=True,
            new_session=True, think=True),
    Adapter("custom", "Eigener Befehl", "keine – optional `hook.py stop` mit JSON auf stdin",
            events=("stop",), read_answers=True),
)}
for _a in list(ADAPTERS.values()):
    for _alias in _a.aliases:
        ADAPTERS[_alias] = _a

CAP_LABELS = {"approvals": "Freigaben per Stimme", "read_answers": "Antworten vorlesen",
              "voice_reply": "Rückfragen per Stimme", "route_to": "Sätze in laufende Session",
              "new_session": "Neue Session mit Auftrag", "dictation": "Eigenes Diktat",
              "think": "Denkmodell"}


def get(name):
    return ADAPTERS.get((name or "").strip().lower())


def matrix(names=("claude", "codex", "antigravity", "gemini", "custom")):
    """Textuelle Übersicht für `walkie agents`."""
    rows = [("", *[ADAPTERS[n].label for n in names])]
    for cap, label in CAP_LABELS.items():
        rows.append((label, *["✓" if ADAPTERS[n].can(cap) else "–" for n in names]))
    rows.append(("Ereignisse", *[str(len(ADAPTERS[n].caps["events"])) + f"/{len(COMMON)}"
                                 for n in names]))
    width = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, width)).rstrip() for r in rows)
