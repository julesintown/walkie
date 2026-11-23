"""Kontextvokabular für die Spracherkennung (Idee aus Parley): Whisper kennt Projekt- und
Dateinamen der laufenden Sessions nicht und macht aus „auth middleware“ gern „off middle where“.

  terms(sessions)          -> Liste von Term(spoken, canonical) aus Git-Repos und Verlauf
  hint(base, terms)        -> Wörter für Whispers initial_prompt (begrenzt)
  correct(text, terms)     -> Text mit erkannten Bezeichnern („auth middleware“ -> auth_middleware.py)

Nur Standardbibliothek. Git-Abfragen sind gecacht und haben ein kurzes Zeitlimit; ohne Git
(oder ohne Repo) gibt es einfach weniger Begriffe.
"""
import re
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import NamedTuple

CACHE_S = 300
GIT_TIMEOUT = 2
MAX_FILES = 4000
HINT_WORDS = 60                      # Whispers initial_prompt fasst nur ~220 Tokens
CODE_EXT = {"py", "ts", "tsx", "js", "jsx", "mjs", "go", "rs", "java", "kt", "swift", "rb",
            "php", "c", "h", "cc", "cpp", "hpp", "cs", "sql", "sh", "toml", "yaml", "yml",
            "json", "md", "vue", "svelte", "css", "scss", "html", "dart", "ex", "exs", "lua"}
SKIP_STEMS = {"index", "main", "init", "__init__", "readme", "license", "test", "tests", "utils",
              "util", "setup", "config", "package", "package-lock", "app", "mod", "lib", "types"}
_cache = {}


class Term(NamedTuple):
    spoken: str        # so wird es gesagt: "auth middleware"
    canonical: str     # so steht es im Code: "auth_middleware.py"


def split_words(name):
    """'auth_middleware' / 'authMiddleware' / 'auth-middleware' -> 'auth middleware'."""
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    return " ".join(w for w in re.split(r"[\W_]+", name) if w).lower()


def _letters(text):
    return re.sub(r"[^0-9a-zäöüß]", "", text.lower())


def _git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                           timeout=GIT_TIMEOUT, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    return r.stdout.splitlines() if r.returncode == 0 else []


def repo_terms(cwd):
    """Begriffe eines Repos: zuletzt geänderte Dateien zuerst, dann alle übrigen."""
    if not cwd or not Path(cwd).is_dir():
        return []
    key = str(cwd)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    recent = [f for f in _git(cwd, "log", "-n", "40", "--name-only", "--format=") if f]
    changed = [ln[3:] for ln in _git(cwd, "status", "--porcelain") if len(ln) > 3]
    files = _git(cwd, "ls-files")[:MAX_FILES]
    out, seen = [], set()
    for path in [*changed, *recent, *files]:
        p = Path(path.strip('"'))
        ext = p.suffix.lstrip(".").lower()
        if ext not in CODE_EXT or p.stem.lower() in SKIP_STEMS:
            continue
        spoken = split_words(p.stem)
        if len(_letters(spoken)) < 4 or p.name in seen:
            continue
        seen.add(p.name)
        out.append(Term(spoken, p.name))
    _cache[key] = (time.monotonic(), out)
    return out


IDENT = re.compile(r"`([^`\s]{3,60})`|\b([\w.-]+\.(?:%s))\b|\b([a-z]+(?:_[a-z0-9]+)+|"
                   r"[a-z]+(?:[A-Z][a-z0-9]+)+)\b" % "|".join(sorted(CODE_EXT)))


def text_terms(text):
    """Bezeichner aus dem Verlauf einer Session (Backticks, Dateinamen, snake/camelCase)."""
    out = []
    for m in IDENT.finditer(text or ""):
        word = next(g for g in m.groups() if g)
        name = Path(word).name if "/" in word else word
        spoken = split_words(Path(name).stem if "." in name else name)
        if len(_letters(spoken)) >= 4 and " " in spoken or "." in name:
            out.append(Term(spoken, name))
    return out


def terms(sessions, per_repo=400):
    """Begriffe aller laufenden Sessions: Projektname, Verlauf, Repo-Dateien."""
    out, seen = [], set()

    def add(t):
        if t.canonical not in seen:
            seen.add(t.canonical)
            out.append(t)
    for s in sessions.values():
        project = s.get("project") or ""
        if project:
            add(Term(split_words(project), project))
        for field in ("prompt", "text", "first_prompt"):
            for t in text_terms(s.get(field) or ""):
                add(t)
    for s in sessions.values():
        for t in repo_terms(s.get("cwd"))[:per_repo]:
            add(t)
    return out


def hint(base, found, limit=HINT_WORDS):
    """Hinweiswörter für Whisper: feste Wörter, dann die wichtigsten Begriffe (gesprochen und
    geschrieben – beides hilft dem Modell), bis das Wortbudget erreicht ist."""
    words, budget = [], limit
    for w in [*base, *[x for t in found for x in (t.spoken, t.canonical)]]:
        n = len(w.split())
        if w and w not in words and n <= budget:
            words.append(w)
            budget -= n
        if budget <= 0:
            break
    return words


FILLER = {"the", "a", "an", "in", "on", "to", "of", "and", "or", "is", "at", "for", "with",
          "der", "die", "das", "den", "dem", "des", "ein", "eine", "im", "in", "und", "oder",
          "mit", "von", "zu", "zum", "zur", "an", "am", "auf", "ist", "bei", "für"}


def _match(chunk, cands, fuzzy, threshold):
    words = [_letters(w) for w in chunk]
    key = "".join(words)
    if len(key) < 6:
        return None
    if key in cands:
        t = cands[key]
        if len(chunk) == 1 and " " not in t.spoken and "." not in chunk[0]:
            return None                   # „router“ bleibt „router“, nicht router.py
        return 1.0, t
    if not fuzzy or words[0] in FILLER or words[-1] in FILLER:
        return None
    best = None
    for ckey, t in cands.items():
        if " " not in t.spoken and len(chunk) == 1:
            continue
        if abs(len(ckey) - len(key)) > max(1, len(ckey) // 10):
            continue
        r = SequenceMatcher(None, key, ckey).ratio()
        if r >= threshold and (best is None or r > best[0]):
            best = (r, t)
    return best


DOT = re.compile(r"\b([\w-]+)\s+(?:dot|punkt|point)\s+([a-z]{1,5})\b", re.I)


def spoken_dots(text, found):
    """„router dot ts“ / „router punkt py“ -> router.ts – nur, wenn es die Datei gibt
    (Idee aus parlar)."""
    names = {t.canonical.lower(): t.canonical for t in found if "." in t.canonical}

    def sub(m):
        name = f"{m.group(1)}.{m.group(2)}".lower()
        return names.get(name, m.group(0))
    return DOT.sub(sub, text)


def correct(text, found, threshold=0.86):
    """Gehörte Wortfolgen durch Bezeichner ersetzen – nur, wenn sie (fast) genau so klingen
    wie ein mehrteiliger Bezeichner. Exakte Treffer zuerst; unscharfe nur, wenn die Wortfolge
    nicht mit einem Füllwort beginnt oder endet. Einzelne Allerweltswörter bleiben stehen."""
    if not text or not found:
        return text
    text = spoken_dots(text, found)
    cands = {}
    for t in found:
        key = _letters(t.spoken)
        # mehrteilige Bezeichner – oder einteilige, die als mehrere Wörter gehört wurden
        # („uv boot“ -> uvboot.py); ein einzelnes, richtig gehörtes Wort bleibt ohnehin stehen
        if len(key) >= 6 and (len(t.spoken.split()) >= 2 or len(key) >= 6):
            cands.setdefault(key, t)
    if not cands:
        return text
    tokens = re.findall(r"\S+", text)
    for fuzzy in (False, True):
        out, i = [], 0
        while i < len(tokens):
            hit = None
            if not tokens[i].startswith("\0"):
                for n in (4, 3, 2, 1):
                    chunk = tokens[i:i + n]
                    if len(chunk) < n or any(c.startswith("\0") for c in chunk):
                        continue
                    m = _match(chunk, cands, fuzzy, threshold)
                    if m and (hit is None or m[0] > hit[0]):
                        hit = (m[0], n, m[1])
                    if hit and hit[0] == 1.0:
                        break
            if hit:
                _, n, t = hit
                tail = re.search(r"[.,!?;:]+$", tokens[i + n - 1])
                out.append("\0" + t.canonical + (tail.group(0) if tail else ""))
                i += n
            else:
                out.append(tokens[i])
                i += 1
        tokens = out
    return " ".join(t.lstrip("\0") for t in tokens)
