"""Wohin mit einem gesprochenen Satz, wenn keine Frage offen ist?

route(text, sessions) -> ("session", sid) oder ("self", None)
  1. Projektname genannt („sag dem Shop …“, „an api: …“) -> diese Session
  2. keine aktive Session -> selbst antworten
  3. sonst entscheidet ein kleines Modell (Haiku) anhand der Sessions (Projekt, letzte Frage/
     Antwort) – bei Fehler/Zeitüberschreitung: zuletzt aktive Session
ask_self(text) -> Antwort des Walkies selbst (eigene, durchgehende Claude-Unterhaltung).
"""
import json
import os
import re
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path

ROUTE_PROMPT = """You are the dispatcher of a voice assistant for programmers. The user said
something through a headset. Speech recognition may mishear words: interpret generously. The user
may speak any language; write "message" in the user's language.

Running Claude Code sessions (JSON):
{sessions}

Project folders WITHOUT a running session: {folders}
Direct mode: {direct}
Agents: primary {primary}; secondary {secondary}
Hint from fast name/folder matching (can be wrong; a name in the sentence does not mean the
sentence is addressed to that session): {hint}

The user said: "{text}"

Targets:
- "<session id>": work for one of the running sessions (code, files, commands, questions about
  what it is working on, answers to its last question).
- "new": ONLY when the user explicitly wants a new, another or separate session or window to be
  opened (any wording, any language, any grammatical person: "open a new session", "I'll open a
  new session and ...", "let's do that in another window"); then set "explicit": true. A new
  topic alone is no reason. Add "agent": "secondary" only when the user explicitly names the
  secondary agent for it; otherwise "agent": "primary". A task the user explicitly gives to the
  secondary agent by name ("ask <secondary agent> to ...") is also "new" with "explicit": true
  and "agent": "secondary", because it has no running session. With secondary "none", never
  use "secondary". If the
  sentence belongs to one of the project folders without a session (speech recognition twists
  names, e.g. "shop front end" for "shop-frontend"), answer "new" with "folder": "<folder name>".
- "self": small talk, short knowledge or research questions (the assistant can search the web),
  questions about the sessions as a whole. NOT feedback, ideas or questions about the voice
  assistant itself, its behaviour or its settings: those belong to the session "in_conversation"
  (the user is probably developing or testing it there).
- "show": the user only wants to SEE a session's window (bring it to the front); nothing is
  sent. "session": its id, or "" for the session of the current conversation.
- "direct": the user wants everything they say from now on to go to one session only.
  "session": its id; "message": a task said in the same breath, otherwise "".
- "direct_end": direct mode is active and the user wants you to decide the target again.
- "ask": several sessions fit similarly well and the conversation does not help either: do NOT
  guess, "options": the 2-3 best session ids, and "labels": for each id a short spoken name of
  2-5 words in the user's language that tells the sessions apart by what they are about (e.g.
  "the gift ideas", "the walkie review"), never the project name alone if they share it.
- "unclear": the speech makes no recognizable sense (speech recognition garbage, only filler
  words, a broken fragment). Nothing is sent.

Rules:
- Mentioning is not addressing. If a project name only occurs ("before I do X", "afterwards I
  test X", "like in X"), the sentence stays with the session that is "in_conversation". It goes
  to another session only if the user addresses it or gives it a task ("ask X ...", "tell X
  ...", "X should ..."). Sentences about the test itself, about the assistant, or feedback ("I
  heard nothing", "that worked") belong to the current conversation.
- Most important: if the sentence has a topic of its own, it belongs to the session whose
  "topic" (what it was started for) fits. That counts more than anything else; "last_prompt"
  can mislead. Only short follow-ups WITHOUT a topic of their own ("read that to me", "do it
  like that") go to the session that is "in_conversation". Otherwise, when in doubt, to the
  session the user addressed last ("self" only for clearly general questions or small talk,
  never for instructions or answers to a session's question).
- In direct mode everything goes to the direct session, unless the user clearly wants "show",
  "direct_end" or "direct" to another session.

"message": what the user wants from the target, as a clear instruction or question in the
user's words and language, without filler, without meta talk about testing, dictation or the
routing itself (drop e.g. "open a new session for this"), with obvious mishearings fixed
(project names, technical terms). Invent nothing and drop nothing of substance; when unsure,
stay close to the wording.

Answer ONLY with JSON, e.g. {{"target": "<session-id>", "message": "..."}},
{{"target": "new", "explicit": true, "message": "..."}},
{{"target": "new", "folder": "<folder>", "message": "..."}}, {{"target": "self", "message": "..."}},
{{"target": "show", "session": "<id>"}}, {{"target": "direct", "session": "<id>", "message": ""}},
{{"target": "direct_end"}},
{{"target": "ask", "options": ["<id>", "<id>"], "labels": {{"<id>": "..."}}, "message": "..."}} or
{{"target": "unclear"}}"""

SELF_SYSTEM = (
    "Du bist {name}, ein kleiner Begleiter auf dem Desktop, mit dem man per Kopfhörer spricht. "
    "Deine Antworten werden vorgelesen: kurz (höchstens 4 Sätze), natürlich, in der Sprache des Nutzers, ohne "
    "Markdown, ohne Links. Für aktuelle Fragen suchst du im Web (WebSearch/WebFetch) und fasst "
    "das Wichtigste zusammen. Nur die Antwort selbst – keine Bemerkungen über Quellen-Formate, "
    "Werkzeuge oder deine Arbeitsweise. "
    "Die Spracherkennung kann sich verhört haben – deute unklare Wörter sinnvoll. "
    "Laufende Claude-Sessions des Nutzers: {sessions}"
)


def _words(text):
    return re.findall(r"[\wäöüß-]+", text.lower())


def by_name(text, sessions):
    """Session, deren Projektname (oder ein Teil davon) im Satz vorkommt."""
    words = _words(text)
    best, score = None, 0.0
    for sid, s in sessions.items():
        name = (s.get("project") or "").lower()
        if len(name) < 3:
            continue
        parts = [p for p in re.split(r"[-_. ]+", name) if len(p) >= 3] + [name]
        for w in words:
            for p in parts:
                r = SequenceMatcher(None, w, p).ratio()
                if r > score:
                    best, score = sid, r
    return best if score >= 0.85 else None


def label(sid, sessions):
    """Sprechbarer Name einer Session: Projekt, bei Gleichnamigen plus Thema
    („Home, Energieeinstellungen“)."""
    s = sessions.get(sid, {})
    name = s.get("project") or "Claude"
    same = [k for k, v in sessions.items() if (v.get("project") or "Claude") == name]
    topic = (s.get("first_prompt") or s.get("prompt") or "").strip()
    if len(same) > 1 and topic:
        words = re.findall(r"[\wäöüÄÖÜß-]+", topic)[:5]
        return f"{name}, {' '.join(words)}"
    return name


def _standard_dirs(home):
    """Names of the user's standard folders (Desktop, Downloads ...) in any locale: the OS
    defaults plus the localized XDG user dirs (~/.config/user-dirs.dirs)."""
    names = {"Desktop", "Documents", "Downloads", "Music", "Pictures", "Public", "Templates",
             "Videos", "Movies", "Library", "Applications", "OneDrive"}
    try:
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
        for line in cfg.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*XDG_\w+_DIR="?\$HOME/([^"/]+)', line)
            if m:
                names.add(m.group(1))
    except OSError:
        pass
    return names


def project_dirs():
    """Projektordner, die der Nutzer nennen könnte: Ordner im Home (nicht versteckt) und
    alles, worin schon einmal eine Claude-Session lief."""
    home = Path.home()
    standard = {n.lower() for n in _standard_dirs(home)}
    dirs = {d for d in home.iterdir() if d.is_dir() and not d.name.startswith(".")
            and d.name.lower() not in standard} if home.is_dir() else set()
    projects = home / ".claude" / "projects"
    if projects.is_dir():
        for p in projects.iterdir():                 # "-home-anna-shop" -> Pfad
            guess = Path("/" + p.name.lstrip("-").replace("-", "/"))
            for cand in (guess, home / p.name.split(home.name + "-", 1)[-1]):
                if cand.is_dir() and cand != home:
                    dirs.add(cand)
    return sorted(dirs)


def by_folder(text, dirs=None):
    """Projektordner, der im Satz genannt wird („am Musik-Widget weiterarbeiten“)."""
    words = _words(text)
    grams = words + [" ".join(words[i:i + 2]) for i in range(len(words) - 1)]
    best, score = None, 0.0
    for d in dirs if dirs is not None else project_dirs():
        name = d.name.lower().replace("_", "-")
        if len(name) < 4:
            continue
        spoken = name.replace("-", " ")
        for g in grams:
            r = SequenceMatcher(None, g.replace("-", " "), spoken).ratio()
            if r > score:
                best, score = d, r
    return best if score >= (0.72 if best and "-" in best.name else 0.85) else None


def latest(sessions):
    """Die Session, die der Nutzer zuletzt angesprochen hat (nicht: zuletzt gearbeitet)."""
    if not sessions:
        return None
    return max(sessions, key=lambda k: (sessions[k].get("user_ts", 0), sessions[k].get("ts", 0)))


ANSWER_PROMPT = """You interpret a spoken answer the user gave to a voice assistant. The user
may speak any language. Speech recognition can mishear words: interpret generously, by meaning.

Situation (JSON): {situation}
The user said: "{text}"

Rules by "kind":
- "permission": a coding agent asks to run a tool. "allow" only for clear consent. "deny" when
  the user refuses, objects, or consents only with a reservation or condition ("yes, but not
  now" is deny); put any instruction or alternative the user gave into "message", in the user's
  words. "unclear" for anything else (hesitation, filler, unrelated speech).
- "question": the user picks from "options". "values": the chosen options, copied exactly from
  "options", recognised by name, misheard name, position ("the second one") or meaning; with
  "multi": false at most one. If the user answers with something that is not an option, use
  "values": [] and put the answer in the user's words into "other". "cancel" when the user wants
  to drop the question altogether. "unclear" for empty or meaningless speech.
- "reply": the agent asked the user an open question. "pass" when the user wants to skip it or
  answer later at the computer; "reply" otherwise; "unclear" for empty or meaningless speech.
- "permission" and "question": "repeat" only when the user asks to hear the question or its
  options again ("which options?", "say that again"). A question about the content itself is
  not "repeat".
- "reply": a question back or confusion about the content is a "reply" (the agent explains it).

Allowed decisions: "permission" -> allow, deny, unclear, repeat; "question" -> answer, cancel,
unclear, repeat; "reply" -> reply, pass, unclear.

Answer ONLY with JSON:
{{"decision": "...", "values": [], "other": "", "message": ""}}"""


def judge_answer(situation, text, env=None, cwd=None, model="haiku", log=lambda m: None):
    """Ask the model what a spoken answer means. Returns the parsed JSON dict, None on failure."""
    try:
        out = ask_model(ANSWER_PROMPT.format(situation=json.dumps(situation, ensure_ascii=False),
                                             text=text.replace('"', "'")),
                        env, cwd, 20, claude_model=model, log=log)
        got = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        log(f"answer model: {got}")
        return got
    except Exception as ex:  # noqa: BLE001
        log(f"answer model: {ex}")
        return None


def brains(env=None):
    """Which CLIs think for the Walkie, in order: with WALKIE_BRAIN=auto the primary agent's
    (Claude or Codex) first, then the other one if installed."""
    import shutil

    import settings
    pref = settings.get("WALKIE_BRAIN")
    if pref in ("claude", "codex"):
        order = [pref]
    else:
        order = ["codex", "claude"] if settings.get("WALKIE_AGENT") == "codex" else ["claude", "codex"]
    path = (env or os.environ).get("PATH")
    return [b for b in order if shutil.which(_codex_bin() if b == "codex" else "claude", path=path)]


BRAIN_PAUSE = 300                 # s: a failed brain (e.g. usage limit) is skipped this long
_brain_down = {}


def ask_model(prompt, env, cwd, timeout, claude_model=None, log=lambda m: None):
    """One prompt, one text answer, no tools – from the first brain that answers. A brain that
    just failed is tried last for BRAIN_PAUSE seconds, so every call does not wait for it."""
    import settings
    errors = []
    order = brains(env)
    order.sort(key=lambda b: _brain_down.get(b, 0) > time.time())    # stable: healthy first
    for brain in order:
        try:
            if brain == "codex":
                out = _codex(prompt, env, cwd, timeout, settings.get("WALKIE_CODEX_MODEL"))
            else:
                out = _claude(["--model", claude_model or settings.get("WALKIE_SUMMARY_MODEL"),
                               "--tools", "", "--no-session-persistence"], prompt, env, cwd,
                              timeout)
            _brain_down.pop(brain, None)
            return out
        except Exception as ex:  # noqa: BLE001 – next brain
            log(f"{brain}: {ex}")
            errors.append(f"{brain}: {ex}")
            _brain_down[brain] = time.time() + BRAIN_PAUSE
    raise RuntimeError("; ".join(errors) or "no model: neither claude nor codex is installed")


def _codex_bin():
    return os.environ.get("WALKIE_CODEX_BIN", "codex")


def _codex(prompt, env, cwd, timeout, model):
    """codex exec, read-only, without hooks or saved session; the answer comes from -o."""
    import tempfile
    fd, out = tempfile.mkstemp(suffix=".txt", prefix="walkie-codex-")
    os.close(fd)
    try:
        r = subprocess.run([_codex_bin(), "exec", "-m", model, "-s", "read-only",
                            "--skip-git-repo-check", "--ephemeral", "--color", "never",
                            "-c", "notify=[]", "-c", 'model_reasoning_effort="low"',
                            "-o", out, "-"],
                           input=prompt, capture_output=True, text=True, timeout=timeout,
                           env=env, cwd=cwd)
        answer = Path(out).read_text(encoding="utf-8").strip()
        if r.returncode != 0 or not answer:
            lines = [ln for ln in (r.stderr or r.stdout).splitlines() if ln.strip()]
            raise RuntimeError((lines[-1] if lines else f"exit {r.returncode}")[:200])
        return answer
    finally:
        Path(out).unlink(missing_ok=True)


def _claude(args, prompt, env, cwd, timeout):
    r = subprocess.run(["claude", "-p", *args], input=prompt, capture_output=True, text=True,
                       timeout=timeout, env=env, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return r.stdout


FOLLOW_UP_S = 180          # so lange gilt „wir reden gerade mit Session X“


def route(text, sessions, env=None, cwd=None, model="haiku", log=lambda m: None, last=None):
    """-> ("session", sid) · ("new", None|ordner) · ("self", None) · ("ask", [sid, …])
    · ("unclear", None). Wie understand(), nur ohne aufgeräumten Auftrag."""
    kind, target, _msg = understand(text, sessions, env, cwd, model, log, last)
    if kind == "ask" and isinstance(target, dict):
        target = target["options"]
    return kind, target


def understand(text, sessions, env=None, cwd=None, model="haiku", log=lambda m: None, last=None,
               direct=None, agents=("Claude Code", None)):
    """Understand speech instead of forwarding it blindly: -> (kind, target, task).
    kind: session · new · self · show · direct · direct_end · ask · unclear. One model call
    decides by the rules in ROUTE_PROMPT, in any language. Names and folders are only hints; if
    the model fails, the fast name/folder matching decides. last = (sid, ts) of the session the
    user addressed last; direct = session id of an active direct mode; agents = (primary label,
    secondary label or None). kind "new_secondary": a new session for the secondary agent."""
    if not sessions:
        return "self", None, text
    direct = direct if direct in sessions else None
    by_n = by_name(text, sessions)
    folder = by_folder(text)
    running = [k for k, v in sessions.items() if folder is not None and v.get("cwd") == str(folder)]
    thread = last[0] if last and last[0] in sessions and time.time() - last[1] < FOLLOW_UP_S \
        else None

    def fast():                                       # without model: names and folders only
        if direct:
            return "session", direct
        if by_n:
            return "session", by_n
        if folder is not None:
            return ("session", running[0]) if running else ("new", str(folder))
        return "session", thread or latest(sessions)

    hint = (f"session {by_n}" if by_n else
            f"project folder {folder.name}" + (f" (session {running[0]})" if running else
                                               " (no session)")
            if folder is not None else "none")
    brief = {k: {"project": v.get("project"), "window_title": v.get("title") or "",
                 "topic": (v.get("first_prompt") or "")[:160],
                 "last_prompt": (v.get("prompt") or "")[:160],
                 "last_answer": (v.get("text") or "")[-200:],
                 "addressed_by_user_s_ago": int(time.time() - v.get("user_ts", v.get("ts", 0))),
                 "in_conversation": k == thread}
             for k, v in sessions.items()}
    try:
        busy = {v.get("cwd") for v in sessions.values()}
        free = {d.name: str(d) for d in project_dirs() if str(d) not in busy}
        out = ask_model(ROUTE_PROMPT.format(sessions=json.dumps(brief, ensure_ascii=False),
                                          folders=", ".join(free) or "none",
                                          direct=f"active, session {direct}" if direct else "off",
                                          primary=agents[0], secondary=agents[1] or "none",
                                          text=text.replace('"', "'"), hint=hint),
                        env, cwd, 20, claude_model=model, log=log)
        got = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        target = got.get("target")
        msg = str(got.get("message") or "").strip() or text
        log(f"router: {target} – auftrag: {msg[:120]!r}")
        if target == "unclear":
            return "unclear", None, text
        if target == "show":
            sid = got.get("session")
            return "show", sid if sid in sessions else None, ""
        if target == "direct":
            sid = got.get("session")
            if sid in sessions:
                return "direct", sid, str(got.get("message") or "").strip()
            target = "ask"                            # unknown session: ask instead of guessing
        if target == "direct_end":
            return ("direct_end", None, "") if direct else ("session", thread or latest(sessions), msg)
        if target == "new":
            fold = free.get(str(got.get("folder") or ""))
            new = "new_secondary" if got.get("agent") == "secondary" and agents[1] else "new"
            # a new session only on explicit request or for a named folder – never because the
            # model could not place a (often misheard) sentence
            if fold and by_folder(text, [Path(fold)]) is not None:
                return new, fold, msg
            if got.get("explicit") is True:
                return new, None, msg
            log(f"router: „new“ ohne Wunsch/Ordner verworfen ({got.get('folder')!r})")
            return "session", direct or thread or latest(sessions), msg
        if target == "self":
            return "self", None, msg
        if target == "ask":
            opts = [o for o in got.get("options") or [] if o in sessions][:3]
            if len(opts) >= 2:
                names = got.get("labels") if isinstance(got.get("labels"), dict) else {}
                return "ask", {"options": opts, "labels": {o: str(names.get(o) or "").strip()
                                                           for o in opts}}, msg
            if opts:
                return "session", opts[0], msg
            return "session", direct or thread or latest(sessions), msg
        if target in sessions:
            return "session", target, msg
        log(f"router: unbekanntes Ziel {target!r}")
    except Exception as ex:  # noqa: BLE001
        log(f"router: {ex}")
    kind, target = fast()
    return kind, target, text


def with_wording(message, spoken):
    """Aufgeräumten Auftrag senden; weicht er deutlich ab, den Wortlaut zur Kontrolle anhängen."""
    a, b = " ".join(_words(message)), " ".join(_words(spoken))
    if not b or a == b or SequenceMatcher(None, a, b).ratio() > 0.9:
        return message
    return f"{message}\n\n(Spoken, per speech recognition: \"{spoken.strip()}\")"


def ask_self(text, run_dir, name, sessions, env=None, cwd=None, model="haiku"):
    """Antwort des Walkies selbst, mit Gedächtnis über eine fortgesetzte Unterhaltung."""
    store = Path(run_dir) / "self-session"
    try:
        sid = store.read_text(encoding="utf-8").strip()
    except OSError:
        sid = ""
    system = SELF_SYSTEM.format(name=name, sessions=", ".join(
        s.get("project") or k[:8] for k, s in sessions.items()) or "keine")
    order = brains(env)
    if order and order[0] == "codex":
        try:
            return ask_model(f"{system}\n\n{text}", env, cwd, 120)
        except Exception:  # noqa: BLE001
            return ""
    args = ["--model", model, "--output-format", "json",
            "--allowedTools", "WebSearch", "WebFetch",       # darf recherchieren, sonst nichts
            "--append-system-prompt", system]
    for attempt in ([*args, "--resume", sid] if sid else None, args):
        if attempt is None:
            continue
        try:
            data = json.loads(_claude(attempt, text, env, cwd, timeout=180))
            if data.get("session_id"):
                Path(run_dir).mkdir(parents=True, exist_ok=True)
                store.write_text(data["session_id"], encoding="utf-8")
            return (data.get("result") or "").strip()
        except Exception:  # noqa: BLE001 – z. B. alte Unterhaltung weg -> neu anfangen
            continue
    return ""


def home_dir():
    return os.environ.get("WALKIE_WORKDIR") or str(Path.home())
