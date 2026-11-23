"""„Was habe ich verpasst?“ – ein kurzer Überblick über alle Sessions (Idee aus GodTerm:
Ereignis-Log mit „gesehen“-Marke, sortiert nach Dringlichkeit).

  log = Timeline()
  log.add(event)                       # jedes Session-Ereignis (ready/prompt/stop/attention …)
  text = summary(log.since(seen), sessions, waiting, now, lang)

Reihenfolge: wer auf dich wartet (Freigabe, Frage), wer noch arbeitet, wer seitdem fertig
geworden ist („vor 5 Minuten“) und mit welchem Ergebnis. Ohne Modell, sofort und offline –
die letzte Antwort einer Session wird auf ihren ersten Satz gekürzt.
"""
import re
import threading
import time
from collections import deque

MAX_EVENTS = 300
SNIPPET = 140


REQUEST = re.compile(
    r"^\W*(?:hey\W+|okay\W+|ok\W+|und\W+|so\W+|also\W+)?(?:\w+\W+)?(?:"
    r"was\s+(?:habe|hab)\s+ich\s+verpasst|was\s+ist\s+(?:passiert|los|neu)|"
    r"wie\s+ist\s+(?:der|die)\s+(?:stand|lage)|gibt\s+es\s+(?:was\s+)?neues|"
    r"(?:gib\s+mir\s+)?(?:einen?\s+)?(?:überblick|statusbericht|status\s*update|lagebericht)|"
    r"what\s+did\s+i\s+miss|what(?:'s|\s+is)\s+(?:new|going\s+on|the\s+status)|"
    r"catch\s+me\s+up|(?:give\s+me\s+(?:a|an)\s+)?(?:status\s+update|overview|status\s+report)"
    r")(?:\W+(?:bitte|mal|please|now|jetzt))?\W*$", re.I)


def is_request(text):
    """Ist der ganze Satz die Frage nach einem Überblick? (Ein längerer Auftrag, der „Status“
    enthält, geht weiter an die Session.)"""
    return bool(REQUEST.match((text or "").strip()))


class Timeline:
    def __init__(self, maxlen=MAX_EVENTS):
        self.events = deque(maxlen=maxlen)
        self.lock = threading.Lock()

    def add(self, ev, now=None):
        if ev.get("event") not in ("ready", "prompt", "tool", "stop", "attention", "error", "end"):
            return
        e = {k: ev.get(k) for k in ("event", "session", "project", "agent", "text", "reason",
                                     "detail", "tool")}
        e["ts"] = now if now is not None else time.time()
        with self.lock:
            self.events.append(e)

    def since(self, ts):
        with self.lock:
            return [e for e in self.events if e["ts"] > ts]


def first_sentence(text, limit=SNIPPET):
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"[*_#`>|]", "", text)
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + " …"


def ago(seconds, de=True):
    m = int(seconds // 60)
    if m < 1:
        return "gerade eben" if de else "just now"
    if m == 1:
        return "vor einer Minute" if de else "a minute ago"
    if m < 60:
        return f"vor {m} Minuten" if de else f"{m} minutes ago"
    h = m // 60
    return (f"vor {h} Stunde{'n' if h > 1 else ''}" if de
            else f"{h} hour{'s' if h > 1 else ''} ago")


def summary(events, states, waiting, now=None, lang="de", names=None):
    """events: Timeline.since(seen); states: {sid: {"state", "ts"}} des Walkies;
    waiting: {sid: Grund} offener Freigaben/Fragen; names: {sid: gesprochener Name}."""
    now = now if now is not None else time.time()
    de = lang != "en"
    names = dict(names or {})
    per = {}
    for e in events:
        sid = e.get("session") or "?"
        names.setdefault(sid, e.get("project") or e.get("agent") or sid[:8])
        per.setdefault(sid, []).append(e)
    sids = set(per) | set(waiting) | {s for s, v in states.items() if v.get("state") == "thinking"}
    if not sids:
        return ("Nichts Neues. Keine Session hat sich seitdem gemeldet." if de
                else "Nothing new. No session has reported since.")

    def name(sid):
        return names.get(sid) or sid[:8]

    needs, working, done, failed, ended = [], [], [], [], []
    for sid in sids:
        evs = per.get(sid, [])
        last_stop = next((e for e in reversed(evs) if e["event"] == "stop"), None)
        last_err = next((e for e in reversed(evs) if e["event"] == "error"), None)
        state = (states.get(sid) or {}).get("state")
        if sid in waiting:
            needs.append((sid, waiting[sid]))
        elif state == "thinking":
            tool = next((e.get("tool") for e in reversed(evs) if e["event"] == "tool"
                         and e.get("tool")), None)
            working.append((sid, tool))
        elif last_err and (not last_stop or last_err["ts"] > last_stop["ts"]):
            failed.append((sid, last_err.get("reason") or ""))
        elif last_stop:
            done.append((sid, last_stop))
        elif evs and evs[-1]["event"] == "end":
            ended.append(sid)

    parts = []
    n = len(sids)
    if n > 1:
        parts.append(f"{n} Sessions haben sich gemeldet." if de else f"{n} sessions reported.")
    for sid, why in needs:
        why = first_sentence(why, 90)
        parts.append(f"{name(sid)} wartet auf dich" + (f": {why}" if why else ".") if de
                     else f"{name(sid)} is waiting for you" + (f": {why}" if why else "."))
    for sid, tool in working:
        parts.append(f"{name(sid)} arbeitet noch" + (f" ({tool})." if tool else ".") if de
                     else f"{name(sid)} is still working" + (f" ({tool})." if tool else "."))
    for sid, reason in failed:
        parts.append(f"{name(sid)} hatte einen Fehler" + (f": {reason}." if reason else ".") if de
                     else f"{name(sid)} hit an error" + (f": {reason}." if reason else "."))
    for sid, e in sorted(done, key=lambda x: -x[1]["ts"]):
        what = first_sentence(e.get("text") or "")
        when = ago(now - e["ts"], de)
        if de:
            parts.append(f"{name(sid)} ist fertig, {when}" + (f": {what}" if what else "."))
        else:
            parts.append(f"{name(sid)} finished {when}" + (f": {what}" if what else "."))
    for sid in ended:
        parts.append(f"{name(sid)} wurde beendet." if de else f"{name(sid)} was closed.")
    return " ".join(p if p.endswith((".", "…", "!", "?")) else p + "." for p in parts)
