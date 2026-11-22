#!/usr/bin/env python3
"""walkie – Walkie im Terminal steuern (nur Standardbibliothek).

  walkie settings                 Menü für alle Einstellungen (Pfeiltasten + Enter)
  walkie settings --window        dasselbe in einem eigenen Terminalfenster
  walkie list [--json] [GRUPPE]   alle Einstellungen mit aktuellem Wert
  walkie get KEY                  einen Wert lesen
  walkie set KEY WERT             einen Wert setzen (KEY auch kurz: announce, voice …)
  walkie reset KEY                auf Standard zurück
  walkie keys [show]              Tastenbelegung des Kopfhörers
  walkie keys set TASTE GESTE AKTION   z. B. walkie keys set PREVIOUSSONG double repeat
  walkie keys learn               Taste am Kopfhörer drücken -> wird erkannt
  walkie keys reset
  walkie voice list | use NAME    Stimmen (lädt fehlende herunter)
  walkie sprite installed | use ORDNER|NAME   Figur wechseln
  walkie setup                    alles installieren (Python-Umgebung, Pakete, Modelle) + starten
  walkie drafts [clear]           ausstehende oder unbestätigte Diktate lesen (clear: löschen)
  walkie sessions                 welche Claude-Sessions der Walkie gerade kennt
  walkie start | stop | restart | status | doctor | gui
  walkie agent-guide              Anleitung für KI-Agents (Claude, Codex, Gemini …)

Gespeichert wird in ~/.config/walkie/config.env; der laufende Begleiter
übernimmt Änderungen sofort (außer bei Einstellungen mit „Neustart“).
"""
import json
import re
import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import keymap  # noqa: E402
import settings as S  # noqa: E402
from hook import LEARN_FLAG, LEARN_LOG, LOCK, RUN, walkie_running  # noqa: E402

INSTALL = RUN / "install"            # vom Begleiter beim Start geschrieben
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else str(text)


def bold(t):
    return c(t, "1")


def dim(t):
    return c(t, "2")


def accent(t):
    return c(t, "38;5;173")          # Claude-Orange


def die(msg, code=1):
    print(c("✗ ", "31") + msg, file=sys.stderr)
    sys.exit(code)


def ok(msg):
    print(c("✓ ", "32") + msg)


def install_dir():
    """Ordner der echten Installation (für Plugin-Kopien im Claude-Cache)."""
    try:
        d = Path(INSTALL.read_text(encoding="utf-8").strip())
        if (d / "walkie.py").exists():
            return d
    except OSError:
        pass
    return HERE


def resolve(key):
    """'announce' / 'WALKIE_ANNOUNCE' / 'answer-window' -> 'WALKIE_ANNOUNCE…'."""
    k = key.strip().upper().replace("-", "_")
    if not k.startswith("WALKIE_"):
        k = "WALKIE_" + k
    if k in S.BY_KEY:
        return k
    hits = [s.key for s in S.SCHEMA if k in s.key]
    if len(hits) == 1:
        return hits[0]
    die(f"Unbekannte Einstellung „{key}“" + (f" – meinst du {', '.join(hits)}?" if hits else
                                             " – siehe `walkie list`"))


def show(s, value):
    if s.type == "bool":
        return c("an", "32") if value else dim("aus")
    if s.type == "choice":
        return dict(s.choices).get(value, value)
    if s.type == "json":
        return json.dumps(value, ensure_ascii=False)
    if value in ("", None):
        return dim("Standard")
    return str(value)


def restart_note(s):
    if s.restart and walkie_running():
        print(dim("  greift nach Neustart: walkie restart"))


# ------------------------------------------------------------------ Einstellungen
def cmd_list(args):
    as_json = "--json" in args
    rest = [a for a in args if a != "--json"]
    group = rest[0].lower() if rest else None
    items = [s for g in S.GROUPS for s in S.SCHEMA if s.group == g
             and (not group or group in (s.group, S.GROUPS[s.group].lower()))]
    if as_json:
        out = {"config_file": str(S.CONFIG), "running": walkie_running(),
               "settings": [s.to_json(S.get(s.key)) for s in items],
               "key_actions": keymap.ACTIONS, "key_gestures": keymap.GESTURES}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    last = None
    for s in items:
        if s.group != last:
            print("\n" + accent(bold(S.GROUPS[s.group])))
            last = s.group
        mark = dim(" ↻") if s.restart else ""
        short = s.key.removeprefix("WALKIE_").lower()
        print(f"  {s.title:<42} {show(s, S.get(s.key))}{mark}  {dim(short)}")
    print(dim(f"\n↻ = greift nach Neustart · Datei: {S.CONFIG}"))


def cmd_get(args):
    if not args:
        die("walkie get KEY")
    s = S.BY_KEY[resolve(args[0])]
    v = S.get(s.key)
    print(json.dumps(v, ensure_ascii=False) if s.type == "json" else
          ("1" if v is True else "0" if v is False else v))


def cmd_set(args):
    if len(args) < 2:
        die("walkie set KEY WERT")
    s = S.BY_KEY[resolve(args[0])]
    raw = " ".join(args[1:])
    if s.type == "choice":                       # auch Anzeigename/Nummer erlauben
        vals = [v for v, _ in s.choices]
        names = {t.lower(): v for v, t in s.choices}
        if raw not in vals:
            raw = names.get(raw.lower()) or next(
                (v for v, t in s.choices if raw.lower() in t.lower()), raw)
    if s.key == "WALKIE_VOICE":
        ensure_voice(raw)
    try:
        v = S.set(s.key, raw)
    except (ValueError, TypeError) as ex:
        die(str(ex))
    ok(f"{s.title}: {show(s, v)}")
    restart_note(s)


def cmd_reset(args):
    if not args:
        die("walkie reset KEY")
    s = S.BY_KEY[resolve(args[0])]
    v = S.reset(s.key)
    ok(f"{s.title}: {show(s, v)} (Standard)")
    restart_note(s)


# ------------------------------------------------------------------ Terminal-Menü (Pfeiltasten)
class Term:
    """Alternativer Bildschirm + cbreak-Modus; Tasten einzeln lesen."""
    KEYS = {"[A": "up", "[B": "down", "[C": "right", "[D": "left", "OA": "up", "OB": "down",
            "OC": "right", "OD": "left", "[H": "home", "[F": "end", "[5~": "pgup", "[6~": "pgdn",
            "[1~": "home", "[4~": "end"}

    def __enter__(self):
        import termios
        import tty
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        sys.stdout.write("\033[?1049h\033[?25l")
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *_):
        import termios
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()

    def key(self):
        import select
        b = os.read(self.fd, 1)
        if b == b"\x1b":
            if not select.select([self.fd], [], [], 0.05)[0]:
                return "esc"
            seq = os.read(self.fd, 1)
            if seq in (b"[", b"O"):            # CSI/SS3 bis zum Endbyte lesen, nicht mehr
                while len(seq) < 8:
                    ch = os.read(self.fd, 1)
                    seq += ch
                    if 0x40 <= ch[0] <= 0x7E:
                        break
            return self.KEYS.get(seq.decode(errors="ignore"), "?")
        if b in (b"\r", b"\n"):
            return "enter"
        if b in (b"\x7f", b"\x08"):
            return "backspace"
        if b[0] >= 0xC0:                       # UTF-8 (ä, ö, ü …) vollständig lesen
            b += os.read(self.fd, 1 if b[0] < 0xE0 else 2 if b[0] < 0xF0 else 3)
        return b.decode(errors="ignore")

    def ask(self, prompt, value=""):
        """Zeile bearbeiten: ←→ Cursor, Enter übernehmen, Esc abbrechen (None)."""
        buf, pos = list(value), len(value)
        sys.stdout.write("\033[?25h")
        try:
            while True:
                line = "".join(buf)
                sys.stdout.write(f"\r\033[K{prompt}{line}" + (f"\033[{len(buf) - pos}D" if pos < len(buf) else ""))
                sys.stdout.flush()
                k = self.key()
                if k == "enter":
                    return line.strip()
                if k == "esc":
                    return None
                if k == "left":
                    pos = max(0, pos - 1)
                elif k == "right":
                    pos = min(len(buf), pos + 1)
                elif k == "home":
                    pos = 0
                elif k == "end":
                    pos = len(buf)
                elif k == "backspace" and pos:
                    del buf[pos - 1]
                    pos -= 1
                elif k == "\x15":                    # Strg+U: Zeile leeren
                    buf, pos = [], 0
                elif len(k) == 1 and k.isprintable():
                    buf.insert(pos, k)
                    pos += 1
        finally:
            sys.stdout.write("\033[?25l")


HINT = "↑↓ wählen · Enter ok · ←→ ändern · Esc/q zurück"


def menu(t, title, rows, sel=0, helps=None, status="", hint=HINT, lr=False):
    """Zeilen mit Pfeiltasten auswählen.

    Rückgabe (Index, "enter"|"left"|"right") oder None (zurück). Mit lr=False
    bedeutet → wie Enter und ← wie zurück."""
    import shutil
    sel = max(0, min(sel, len(rows) - 1))
    top = 0
    while True:
        height = shutil.get_terminal_size((80, 24)).lines
        view = max(3, height - 7 - title.count("\n"))
        top = min(max(top, sel - view + 1), sel)
        out = ["\033[H\033[2J" + accent(bold(title)), ""]
        for i in range(top, min(len(rows), top + view)):
            out.append((accent("❯ ") + c(rows[i], "1")) if i == sel else "  " + rows[i])
        if len(rows) > view:
            out.append(dim(f"  … {sel + 1}/{len(rows)}"))
        out.append("")
        h = (helps or [None] * len(rows))[sel]
        out.append(dim(h) if h else "")
        out.append(status or "")
        out.append(dim(hint))
        sys.stdout.write("\n".join(out))
        sys.stdout.flush()
        k = t.key()
        k = k.lower() if len(k) == 1 else k
        if k in ("up", "k"):
            sel = (sel - 1) % len(rows)
        elif k in ("down", "j"):
            sel = (sel + 1) % len(rows)
        elif k == "home":
            sel = 0
        elif k == "end":
            sel = len(rows) - 1
        elif k == "pgup":
            sel = max(0, sel - view)
        elif k == "pgdn":
            sel = min(len(rows) - 1, sel + view)
        elif k == "enter" or (k == "right" and not lr):
            return sel, "enter"
        elif k in ("left", "right") and lr:
            return sel, k
        elif k in ("esc", "q", "backspace") or (k == "left" and not lr):
            return None
        elif k.isdigit() and 1 <= int(k) <= len(rows):
            sel = int(k) - 1


TERMINALS = [  # (Programm, Argumente vor dem Befehl) – das erste vorhandene gewinnt
    ("kitty", ["--title", "Walkie", "-o", "remember_window_size=no",
               "-o", "initial_window_width=86c", "-o", "initial_window_height=30c"]),
    ("konsole", ["-e"]), ("gnome-terminal", ["--"]), ("xfce4-terminal", ["-x"]),
    ("x-terminal-emulator", ["-e"]), ("xterm", ["-e"]),
]


def open_menu_window():
    """Pfeiltasten-Menü in einem eigenen Terminalfenster (für /walkie in Claude Code)."""
    import shutil
    cmd = [sys.executable, str(install_dir() / "cli.py"), "settings"]
    for prog, pre in TERMINALS:
        if shutil.which(prog):
            subprocess.Popen([prog, *pre, *cmd], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            ok("Einstellungsmenü geöffnet (eigenes Terminalfenster)")
            return
    die("Kein Terminal gefunden (kitty, konsole, gnome-terminal …) – walkie settings direkt starten")


def cmd_settings(args):
    """Interaktives Menü: Gruppe -> Einstellung -> Wert (Pfeiltasten + Enter)."""
    if "--window" in args:
        open_menu_window()
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        die("Interaktives Menü braucht ein Terminal – sonst: walkie list / walkie set")
    try:
        import termios  # noqa: F401
    except ImportError:
        die("Pfeiltasten-Menü gibt es nur unter Linux/macOS – sonst: walkie list / walkie set")
    groups = list(S.GROUPS.items())
    rows = [g[1] for g in groups] + ["Tastenbelegung Kopfhörer", "Ende"]
    sel = 0
    try:
        with Term() as t:
            while True:
                r = menu(t, f"{S.get('WALKIE_NAME')} – Einstellungen", rows, sel,
                         hint="↑↓ wählen · Enter öffnen · Esc/q Ende")
                if r is None or r[0] == len(rows) - 1:
                    return
                sel = r[0]
                if sel == len(groups):
                    keys_menu(t)
                else:
                    group_menu(t, groups[sel][0])
    except KeyboardInterrupt:
        pass


def group_menu(t, group):
    items = [s for s in S.SCHEMA if s.group == group and s.type != "json"]
    width = max(len(s.title) for s in items) + 2
    sel, status = 0, ""
    while True:
        rows = [f"{s.title:<{width}} {show(s, S.get(s.key))}" + (dim(" ↻") if s.restart else "")
                for s in items]
        helps = [(s.help or "") + ("  (↻ greift nach Neustart)" if s.restart else "") for s in items]
        r = menu(t, S.GROUPS[group], rows, sel, helps, status, lr=True)
        if r is None:
            return
        sel, how = r
        status = edit(t, items[sel], how)


def _msg(text):
    return c("✓ ", "32") + text


def _restart(s):
    return dim("  · greift nach Neustart: walkie restart") if s.restart and walkie_running() else ""


def edit(t, s, how="enter"):
    """Wert ändern (Enter, ← oder →); liefert eine Statuszeile fürs Menü."""
    cur = S.get(s.key)
    try:
        if s.type == "bool":
            S.set(s.key, not cur)
            return _msg(f"{s.title}: {show(s, not cur)}") + _restart(s)
        if s.type == "choice":
            vals = [v for v, _ in s.choices]
            i = vals.index(cur) if cur in vals else 0
            if how == "enter":
                rows = [txt + (accent("  ●") if v == cur else "") for v, txt in s.choices]
                r = menu(t, s.title, rows, i, [s.help] * len(rows),
                         hint="↑↓ wählen · Enter übernehmen · Esc zurück")
                if r is None:
                    return ""
                v = vals[r[0]]
            else:
                v = vals[(i + (1 if how == "right" else -1)) % len(vals)]
            if s.key == "WALKIE_VOICE":
                sys.stdout.write("\033[H\033[2J")
                ensure_voice(v)
            S.set(s.key, v)
            return _msg(f"{s.title}: {show(s, v)}") + _restart(s)
        if how != "enter":
            if s.type in ("int", "float") and s.min is not None and s.max is not None:
                step = 1 if s.type == "int" else (round((s.max - s.min) / 20, 3) or 0.1)
                base = cur if isinstance(cur, (int, float)) else s.min
                v = min(s.max, max(s.min, base + (step if how == "right" else -step)))
                v = S.set(s.key, round(v, 3) if s.type == "float" else int(v))
                return _msg(f"{s.title}: {show(s, v)}") + _restart(s)
            return dim("Enter zum Bearbeiten")
        rng = f" ({s.min:g}–{s.max:g})" if s.min is not None else ""
        sys.stdout.write("\033[1A\r\033[K" + dim("Enter übernehmen · Esc abbrechen · leer = Standard") + "\n")
        a = t.ask(f"{s.title}{rng}: ", "" if cur is None else str(cur))
        if a is None or a == str(cur):
            return ""
        if a in ("", "-"):
            S.reset(s.key)
            return _msg(f"{s.title}: Standard") + _restart(s)
        return _msg(f"{s.title}: {show(s, S.set(s.key, a))}") + _restart(s)
    except (ValueError, TypeError) as ex:
        return c("✗ " + str(ex), "31")


# ------------------------------------------------------------------ Tasten
def keys_lines():
    m = S.get("WALKIE_KEYS")
    out = []
    for key in list(S.DEFAULT_KEYS) + [k for k in m if k not in S.DEFAULT_KEYS]:
        acts = m.get(key) or {}
        parts = [f"{keymap.GESTURES[g]}: {keymap.ACTIONS.get(acts[g], acts[g])}"
                 for g in keymap.GESTURES if g in acts]
        out.append(f"  {keymap.key_label(key):<12} {dim(key):<24} " + (" · ".join(parts) or dim("—")))
    return out


def keys_show():
    print(accent(bold("Tastenbelegung")) + dim("  (Taste · Geste → Aktion)"))
    print("\n".join(keys_lines()))
    print(dim("\nGesten: " + ", ".join(keymap.GESTURES) +
              "\nAktionen: " + ", ".join(keymap.ACTIONS)))


def keys_set(key, gesture, action):
    key = keymap.normalize(key.upper())
    if gesture not in keymap.GESTURES:
        die(f"Geste: {', '.join(keymap.GESTURES)}")
    if action not in keymap.ACTIONS:
        die(f"Aktion: {', '.join(keymap.ACTIONS)}")
    m = {k: dict(v) for k, v in S.get("WALKIE_KEYS").items()}
    m.setdefault(key, {})
    if action == "none":
        m[key].pop(gesture, None)
    else:
        m[key][gesture] = action
    S.set("WALKIE_KEYS", m)
    return f"{keymap.key_label(key)} {keymap.GESTURES[gesture]} → {keymap.ACTIONS[action]}"


def keys_learn(timeout=30):
    """Wartet auf eine Kopfhörertaste; None, wenn nichts kam."""
    if not walkie_running():
        die("Der Begleiter muss laufen, damit er die Tasten hört: walkie start")
    flag, log = LEARN_FLAG, LEARN_LOG
    log.write_text("", encoding="utf-8")
    flag.touch()
    print("Drück jetzt eine Taste am Kopfhörer – einmal, doppelt oder lang …")
    sys.stdout.flush()
    try:
        end = time.time() + timeout
        while time.time() < end:
            flag.touch()
            lines = log.read_text(encoding="utf-8").splitlines()
            if lines:
                ev = json.loads(lines[-1])
                print(f"Erkannt: {bold(keymap.key_label(ev['key']))} ({ev['key']}) · "
                      f"{bold(keymap.GESTURES[ev['gesture']])} ({ev['gesture']})")
                return ev
            time.sleep(0.2)
        return None
    finally:
        flag.unlink(missing_ok=True)


def keys_menu(t):
    sel, status = 0, ""
    while True:
        title = "Tastenbelegung\n\n" + "\n".join(keys_lines())
        r = menu(t, title, ["Taste anlernen …", "Auf Standard zurücksetzen", "Zurück"], sel,
                 status=status, hint="↑↓ wählen · Enter ok · Esc/q zurück")
        if r is None or r[0] == 2:
            return
        sel = r[0]
        if sel == 1:
            S.reset("WALKIE_KEYS")
            status = _msg("Tastenbelegung zurückgesetzt")
            continue
        if not walkie_running():
            status = c("✗ Der Begleiter muss laufen, damit er die Tasten hört: walkie start", "31")
            continue
        sys.stdout.write("\033[H\033[2J")
        ev = keys_learn()
        if ev is None:
            status = c("✗ Keine Taste erkannt. Ist der Kopfhörer verbunden?", "31")
            continue
        cur = (S.get("WALKIE_KEYS").get(keymap.normalize(ev["key"])) or {}).get(ev["gesture"], "none")
        acts = list(keymap.ACTIONS.items())
        i = next((n for n, (a, _) in enumerate(acts) if a == cur), 0)
        head = f"{keymap.key_label(ev['key'])} · {keymap.GESTURES[ev['gesture']]} – was soll passieren?"
        r = menu(t, head, [txt + (accent("  ●") if a == cur else "") for a, txt in acts], i,
                 hint="↑↓ wählen · Enter übernehmen · Esc abbrechen")
        status = _msg(keys_set(ev["key"], ev["gesture"], acts[r[0]][0])) if r else ""


def cmd_keys(args):
    sub = args[0] if args else "show"
    if sub == "show":
        keys_show()
    elif sub == "set" and len(args) == 4:
        ok(keys_set(*args[1:]))
    elif sub == "learn":
        if keys_learn() is None:
            die("Keine Taste erkannt. Ist der Kopfhörer verbunden?")
    elif sub == "reset":
        S.reset("WALKIE_KEYS")
        ok("Tastenbelegung zurückgesetzt")
    elif sub == "unlock":
        keys_unlock()
    else:
        die("walkie keys [show | set TASTE GESTE AKTION | learn | reset | unlock]")


def keys_unlock():
    """Linux: Kopfhörertasten für den angemeldeten Benutzer lesbar machen (udev-Regel)."""
    if not keymap.keys_need_unlock():
        ok("Kopfhörertasten sind schon freigeschaltet (oder hier nicht nötig)")
        return
    src = install_dir() / "extras" / "udev" / keymap.RULE
    cmd = keymap.unlock_command(src)
    if cmd is None:
        die("pkexec fehlt – einmalig von Hand:\n  " + keymap.unlock_hint(src))
    print(dim("Dein System fragt gleich nach deinem Passwort (einmalig, für die Kopfhörertasten) …"))
    if subprocess.run(cmd).returncode != 0 or keymap.keys_need_unlock():
        die("Nicht freigeschaltet (abgebrochen?). Von Hand:\n  " + keymap.unlock_hint(src))
    ok("Kopfhörertasten freigeschaltet – Kopfhörer einmal neu verbinden, falls sie nicht sofort gehen")


# ------------------------------------------------------------------ Stimmen & Figuren
def ensure_voice(name):
    if name not in S.VOICES:
        return
    model = S.VOICES[name][0]
    if not (install_dir() / "voices" / f"{model}.onnx").exists():
        print(dim(f"Stimme {model} wird geladen (~60 MB) …"))
        import fetch_assets
        fetch_assets.HERE = install_dir()
        fetch_assets.voices([model])


def cmd_voice(args):
    sub = args[0] if args else "list"
    if sub == "list":
        cur = S.get("WALKIE_VOICE")
        for name, (model, _) in S.VOICES.items():
            have = (install_dir() / "voices" / f"{model}.onnx").exists()
            print(("● " if name == cur else "  ") + name + ("" if have else dim("  (wird geladen)")))
    elif sub == "use" and len(args) > 1:
        cmd_set(["WALKIE_VOICE", " ".join(args[1:])])
    else:
        die("walkie voice [list | use NAME]")


def sprites_installed():
    out = []
    for base in ("figures", "sprites"):
        root = install_dir() / base
        if root.exists():
            out += sorted(d for d in root.iterdir() if (d / "AnimData.xml").exists())
    return out


def cmd_sprite(args):
    sub = args[0] if args else "installed"
    if sub == "installed":
        cur = S.sprite_dir().resolve()
        for d in sprites_installed():
            print(("● " if d.resolve() == cur else "  ") + d.name + dim(f"  {d}"))
    elif sub == "use" and len(args) > 1:
        p = Path(args[1]).expanduser()
        for base in ("figures", "sprites"):
            if not (p / "AnimData.xml").exists():
                p = install_dir() / base / args[1]
        if not (p / "AnimData.xml").exists():
            die(f"Kein Sprite-Ordner: {args[1]} (siehe walkie sprite installed)")
        S.set("WALKIE_SPRITE", "" if p.resolve() == (install_dir() / "figures" / "fox").resolve()
              else str(p.resolve()))
        ok(f"Figur: {p.name}")
    elif sub == "import" and len(args) > 1:
        cmd_sprite_import(args[1], args[2] if len(args) > 2 else None)
    else:
        die("walkie sprite [installed | use ORDNER|NAME | import SHIMEJI.zip|ORDNER [NAME]]")


def cmd_sprite_import(src, name=None):
    """Shimeji-Paket umbauen nach sprites/NAME und gleich als Figur nehmen."""
    src = Path(src).expanduser()
    if not src.exists():
        die(f"Nicht gefunden: {src}")
    name = re.sub(r"[^\w-]+", "-", name or src.stem).strip("-").lower() or "shimeji"
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 – QImage braucht sie
    import shimeji
    try:
        frames = shimeji.read_frames(src)
        made, missing = shimeji.build(frames, install_dir() / "sprites" / name,
                                      name.replace("-", " ").title())
    except (ValueError, OSError, zipfile.BadZipFile) as ex:
        die(f"Kein Shimeji-Paket: {ex}")
    ok(f"{len(frames)} Bilder -> sprites/{name} ({', '.join(made)})")
    if missing:
        print(dim(f"  fehlende Bilder: {', '.join(map(str, missing))}"))
    cmd_sprite(["use", name])


# ------------------------------------------------------------------ Begleiter
def pid():
    from hook import server_info
    info = server_info() or {}
    return info.get("pid")


def bridge_post(path):
    """POST an den lokalen Dienst der laufenden App (z. B. /quit). True bei Erfolg."""
    import urllib.request

    from hook import server_info
    info = server_info()
    if not info:
        return False
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}{path}", data=b"{}",
                                 headers={"x-walkie-token": info["token"]}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:  # noqa: BLE001
        return False


def cmd_sessions(_args):
    """Welche Claude-Sessions kennt der laufende Walkie gerade?"""
    import urllib.request

    from hook import server_info
    info = server_info()
    if not info or not walkie_running():
        die("Der Walkie läuft nicht: walkie start")
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/sessions",
                                 headers={"x-walkie-token": info["token"]})
    with urllib.request.urlopen(req, timeout=3) as r:
        sessions = json.loads(r.read())["sessions"]
    if not sessions:
        print("Keine Session angemeldet. Läuft Claude Code mit dem Plugin? (/reload-plugins)")
    for sid, s in sorted(sessions.items(), key=lambda kv: -kv[1].get("ts", 0)):
        age = int(time.time() - s.get("ts", 0))
        print(f"  {bold(s.get('project') or '?'):<20} {dim(sid[:8])}  vor {age}s  "
              f"{dim((s.get('prompt') or '')[:60])}")


def cmd_setup(args):
    """Alles in einem Schritt: Python-Umgebung, Pakete, Stimme, Whisper-Modell, starten.
    Läuft auf Linux, macOS und Windows; braucht keine Adminrechte."""
    import paths
    root = install_dir()
    paths.HERE = root
    import uvboot
    if sys.version_info < (3, 10):
        # zu altes Python (z. B. macOS 3.9): uv holt ein passendes, nur für den Walkie
        uv = uvboot.ensure_uv()
        if uv and not os.environ.get("WALKIE_UV_REEXEC"):
            os.environ["WALKIE_UV_REEXEC"] = "1"
            r = subprocess.run([uv, "run", "--no-project", "--python", "3.12",
                                str(Path(__file__).resolve()), "setup", *args])
            sys.exit(r.returncode)
        die(f"Python 3.10 oder neuer nötig (gefunden: {sys.version.split()[0]}).\n"
            "  Windows: winget install Python.Python.3.12\n"
            "  macOS:   brew install python@3.12  (oder python.org)\n"
            "  Linux:   über die Paketverwaltung, z. B. sudo apt install python3 python3-venv")
    venv = Path(os.environ.get("WALKIE_VENV") or paths.VENV)
    py = paths.venv_python(venv)
    step = lambda n, t: print(f"\n{accent(bold(f'[{n}/5]'))} {bold(t)}", flush=True)  # noqa: E731

    step(1, f"Python-Umgebung ({venv})")
    # uv: schneller, braucht kein python3-venv (Debian/Ubuntu) und keine Adminrechte.
    # Ohne uv (offline, GitHub gesperrt): der klassische Weg mit venv + pip.
    uv = uvboot.ensure_uv()
    if not py.exists():
        if uv:
            r = subprocess.run([uv, "venv", "--seed", "--python", sys.executable, str(venv)])
        else:
            r = subprocess.run([sys.executable, "-m", "venv", str(venv)])
        if r.returncode != 0 or not py.exists():
            die("Python-Umgebung lässt sich nicht anlegen. Linux: sudo apt install python3-venv")
    ok("bereit")

    step(2, "Pakete installieren (PyQt6, Whisper, Piper, miniaudio …) – dauert 1–3 Minuten")
    if uv:
        cmd = [uv, "pip", "install", "--python", str(py), "-r", str(root / "requirements.txt")]
    else:
        pip = [str(py), "-m", "pip", "--disable-pip-version-check"]
        subprocess.run([*pip, "install", "-q", "--upgrade", "pip"])
        cmd = [*pip, "install", "-r", str(root / "requirements.txt"), "--progress-bar", "on"]
    if subprocess.run(cmd).returncode != 0:
        die("Pakete konnten nicht installiert werden (siehe oben). Internet da?")
    ok("installiert")

    step(3, "Stimme laden")
    voice = S.get("WALKIE_VOICE")
    model = S.VOICES.get(voice, S.VOICES[S.DEFAULT_VOICE])[0]
    subprocess.run([str(py), str(root / "fetch_assets.py"), "voices", model])

    step(4, f"Spracherkennung laden (Whisper „{S.get('WALKIE_WHISPER')}“)")
    code = ("from faster_whisper import WhisperModel; import sys; "
            "WhisperModel(sys.argv[1], device='cpu', compute_type='int8'); print('ok')")
    if subprocess.run([str(py), "-c", code, S.get("WALKIE_WHISPER")]).returncode != 0:
        print(c("  ⚠ Modell lädt beim ersten Start nach", "33"))

    if sys.platform == "darwin":                  # optional: Mikro mit Echounterdrückung
        import audio
        if audio.build_mac_voicemic(root, log=print):
            ok("Mac-Mikrofon mit Echounterdrückung bereit (Einstellungen → experimentell)")

    step(5, "Prüfen und starten")
    subprocess.run([str(py), str(root / "doctor.py")])
    if "--no-start" not in args:
        if walkie_running():
            cmd_restart([])
        else:
            cmd_start([])
        print("\n" + bold("Fertig!") + " Der Walkie führt dich jetzt durch Mikro und Kopfhörer.\n"
              "Reden: Kopfhörer-Play, Klick auf die Figur oder Strg+Alt+Leertaste.")


def cmd_start(_args):
    if walkie_running():
        ok("läuft schon")
        return
    import paths
    paths.HERE = install_dir()
    paths.launch("walkie.py")
    for _ in range(100):
        if walkie_running():
            ok("gestartet")
            return
        time.sleep(0.2)
    die("Start fehlgeschlagen – walkie doctor")


def cmd_stop(_args):
    p = pid()
    if not walkie_running():
        ok("läuft nicht")
        return
    if not bridge_post("/quit") and p:           # sauber beenden, sonst hart
        os.kill(p, signal.SIGTERM)
    for _ in range(100):
        if not walkie_running():
            ok("beendet")
            return
        time.sleep(0.2)
    die("reagiert nicht")


def cmd_restart(args):
    cmd_stop(args)
    cmd_start(args)


def cmd_status(_args):
    print(f"Begleiter: {c('läuft', '32') if walkie_running() else dim('läuft nicht')}")
    print(f"Installation: {install_dir()}")
    print(f"Einstellungen: {S.CONFIG}")


def cmd_doctor(_args):
    import paths
    paths.HERE = install_dir()
    sys.exit(subprocess.call([paths.python(), str(install_dir() / "doctor.py")]))


def cmd_gui(_args):
    import paths
    paths.HERE = install_dir()
    paths.launch("settings_gui.py")
    ok("Einstellungsfenster geöffnet")


AGENT_GUIDE = """\
# Walkie per Terminal einstellen (für KI-Agents)

Der Walkie ist eine Figur auf dem Desktop, die Coding-Sessions ansagt, Freigaben
und Rückfragen per Stimme entgegennimmt und per Bluetooth-Kopfhörer bedient wird.
Alle Einstellungen gehen über das Kommando `walkie` (bzw. `python3 <repo>/cli.py`).

1. Zustand lesen:   walkie list --json
   -> "settings": [{key, title, help, type, value, default, choices, min, max, restart}]
   -> "key_actions"/"key_gestures": erlaubte Werte für die Tastenbelegung
2. Wert setzen:     walkie set KEY WERT        (KEY ohne WALKIE_ geht auch, z. B. announce)
   bool: 1/0, an/aus · choice: einer der "choices" · int/float: innerhalb min..max
3. Tasten:          walkie keys set TASTE GESTE AKTION
   TASTE z. B. PLAYPAUSE, NEXTSONG, PREVIOUSSONG · GESTE press|double|long
   Unbekannte Taste? `walkie keys learn` (blockiert bis zu 30 s, Nutzer drückt die Taste).
4. "restart": true -> danach `walkie restart` anbieten. Alles andere greift sofort.
5. Stimme:          walkie voice list / walkie voice use NAME (lädt fehlende Stimme)
   Figur:           walkie sprite installed / walkie sprite use NAME

Regeln: Frag nach, wenn der Wunsch mehrdeutig ist, biete die "choices" als Auswahl an,
ändere nur, was der Nutzer will, und bestätige danach kurz mit dem neuen Wert.
"""


def cmd_agent_guide(_args):
    print(AGENT_GUIDE)


def cmd_drafts(args):
    from dictations import Dictations
    store = Dictations(RUN)
    if args[:1] == ["clear"]:
        rows = store.clear()
        for row in rows:
            wav = row["text"].removeprefix("WAV: ")
            if wav != row["text"] and Path(wav).parent == Path(RUN):
                Path(wav).unlink(missing_ok=True)
        print(f"{len(rows)} Diktat(e) gelöscht.")
        return
    for row in store.drafts():
        print(f"[{row['session']}] {row['text']}")


COMMANDS = {
    "drafts": cmd_drafts,
    "settings": cmd_settings, "list": cmd_list, "get": cmd_get, "set": cmd_set,
    "reset": cmd_reset, "keys": cmd_keys, "voice": cmd_voice, "sprite": cmd_sprite,
    "sessions": cmd_sessions, "setup": cmd_setup, "start": cmd_start, "stop": cmd_stop, "restart": cmd_restart, "status": cmd_status,
    "doctor": cmd_doctor, "gui": cmd_gui, "agent-guide": cmd_agent_guide,
}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Plugin-Kopie im Claude-Cache -> an die echte Installation weiterreichen
    real = install_dir()
    if real != HERE and (real / "cli.py").exists() and not os.environ.get("WALKIE_CLI_FORWARDED"):
        os.environ["WALKIE_CLI_FORWARDED"] = "1"
        os.execv(sys.executable, [sys.executable, str(real / "cli.py"), *argv])
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return
    fn = COMMANDS.get(argv[0])
    if fn is None:
        die(f"Unbekannter Befehl „{argv[0]}“ – walkie help")
    fn(argv[1:])


if __name__ == "__main__":
    main()
