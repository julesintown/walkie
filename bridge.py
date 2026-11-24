"""Lokaler HTTP-Dienst der Walkie-App – Gegenstelle des Plugin-Mods (hooks/session.tsx).

Nur 127.0.0.1, zufälliger Port, geheimes Token; beides steht in RUN/server.json, das der Mod
liest. Plattformneutral (nur Standardbibliothek), keine Dateien als Nachrichtenkanal.

  POST /event            Ereignis einer Session -> Warteschlange (GUI-Thread holt ab)
  GET  /inbox?session=X  gesprochene Sätze für Session X (werden dabei entnommen)
  POST /ask              Freigabe/Rückfrage: wartet bis zur Antwort (oder Zeitlimit)
  GET  /health
"""
from dictations import Dictations

import json
import os

import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from urllib.parse import parse_qs, urlparse


from i18n import lang, t


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer löst den Namen per Reverse-DNS auf. Auf macOS kann das selbst
        # für 127.0.0.1 den GUI-Start blockieren. Adresse und Port sind hier lokal.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address


class Bridge:
    def __init__(self, run_dir, ask_wait=lambda: 120):
        self.run = run_dir
        self.token = secrets.token_hex(16)
        self.events = queue.Queue()          # dicts, vom GUI-Thread abgeholt
        self.dictations = Dictations(run_dir)
        self.waiting = {}                     # req -> [threading.Event, answer]
        self.sessions = {}                    # session -> {project, cwd, prompt, text, ts}
        self.ask_wait = ask_wait
        self.lock = threading.Lock()
        self.httpd = None
        self.on_quit = None
        self.on_digest = None             # -> Text „Was habe ich verpasst?“ (GET /digest)
        self.on_show = None               # Figur zeigen (POST /show)
        self.on_terminal = None           # Terminalfenster des Agents (POST /terminal)
        self.saved = 0.0
        self._load()                   # vom Begleiter gesetzt: sauber beenden

    # ---------------- Start/Stopp ----------------
    def start(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):       # keine Konsolenausgabe
                pass

            def _reply(self, code, data=None):
                body = json.dumps(data if data is not None else {}).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth(self):
                if self.headers.get("x-walkie-token") != bridge.token:
                    self._reply(403, {"error": "token"})
                    return False
                return True

            def _body(self):
                n = int(self.headers.get("content-length") or 0)
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return {}

            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                if url.path == "/health":
                    return self._reply(200, {"ok": True})
                if not self._auth():
                    return
                if url.path == "/digest" and bridge.on_digest:
                    speak = parse_qs(url.query).get("speak") == ["1"]
                    return self._reply(200, {"text": bridge.on_digest(speak)})
                if url.path == "/sessions":
                    return self._reply(200, {"sessions": bridge.active_sessions()})
                if url.path == "/inbox":
                    q = parse_qs(url.query)
                    sid = (q.get("session") or [""])[0]
                    bridge.touch(sid, (q.get("project") or [""])[0], (q.get("cwd") or [""])[0])
                    if q.get("ack") == ["1"]:
                        return self._reply(200, {"message": bridge.dictations.first(sid),
                                                 "reply_language": lang()})
                    return self._reply(200, {"texts": bridge.take_inbox(sid)})
                self._reply(404)

            def do_POST(self):  # noqa: N802
                if not self._auth():
                    return
                path = urlparse(self.path).path
                data = self._body()
                if path == "/ack":
                    bridge.dictations.ack(data["session"], data["id"])
                    return self._reply(200, {"ok": True})
                if path == "/event":
                    bridge.on_event(data)
                    return self._reply(200, {"ok": True})
                if path == "/ask":
                    return self._reply(200, bridge.ask(data))
                if path == "/terminal" and bridge.on_terminal:
                    bridge.on_terminal()
                    return self._reply(200, {"ok": True})
                if path == "/show" and bridge.on_show:
                    bridge.on_show()
                    return self._reply(200, {"ok": True})
                if path == "/quit" and bridge.on_quit:
                    self._reply(200, {"ok": True})
                    return bridge.on_quit()
                self._reply(404)

        os.makedirs(self.run, exist_ok=True)
        path = os.path.join(self.run, "server.json")
        tmp = path + ".tmp"
        httpd = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        port = httpd.server_address[1]
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"port": port, "token": self.token, "pid": os.getpid()}, f)
            threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                             daemon=True).start()
            self.httpd = httpd
            os.replace(tmp, path)
        except (OSError, RuntimeError):
            if self.httpd:
                httpd.shutdown()
            httpd.server_close()
            self.httpd = None
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass
            raise
        return port

    def stop(self):
        try:
            os.remove(os.path.join(self.run, "server.json"))
        except OSError:
            pass
        for ev, _ in list(self.waiting.values()):
            ev.set()                          # wartende Freigaben freigeben (-> normaler Dialog)
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    # ---------------- Ereignisse ----------------
    def on_event(self, data):
        if not isinstance(data, dict) or not data.get("session"):
            return
        sid = str(data["session"])
        with self.lock:
            s = self.sessions.setdefault(sid, {})
            now = time.time()
            s.update(project=data.get("project") or s.get("project") or "", ts=now)
            if data.get("cwd"):
                s["cwd"] = data["cwd"]
            if data.get("pid"):
                s["pid"] = int(data["pid"])               # zum Fenster-nach-vorne-Holen
            if data.get("event") == "prompt":           # der Nutzer hat sie angesprochen
                s["user_ts"] = now
            if data.get("prompt"):
                s["prompt"] = data["prompt"]
                s.setdefault("first_prompt", data["prompt"])    # Thema der Session
            if data.get("event") == "stop":
                s["text"] = (data.get("text") or "")[-600:]
            if data.get("event") == "end":
                self.sessions.pop(sid, None)
            self._save()
        self.events.put(data)

    # ---------------- Gedächtnis über Neustarts ----------------
    def _store(self):
        return os.path.join(self.run, "sessions.json")

    def _load(self):
        """Thema/letzte Frage bekannter Sessions nach einem Neustart wiederherstellen
        (sie gelten erst als aktiv, wenn sie sich wieder melden)."""
        try:
            with open(self._store(), encoding="utf-8") as f:
                data = json.load(f)
            for sid, s in data.items():
                if time.time() - s.get("ts", 0) < 12 * 3600:
                    s["ts"] = 0                  # noch nicht wieder gemeldet
                    self.sessions[sid] = s
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self):
        if time.time() - self.saved < 2:
            return
        self.saved = time.time()
        try:
            os.makedirs(self.run, exist_ok=True)
            tmp = self._store() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.sessions, f)
            os.replace(tmp, self._store())
        except OSError:
            pass

    def active_sessions(self, max_age=90):
        """Sessions, die sich in den letzten max_age Sekunden gemeldet haben (jede Session
        fragt alle 0,5 s ihr Postfach ab – geschlossene fallen so von selbst heraus)."""
        now = time.time()
        with self.lock:
            return {k: dict(v) for k, v in self.sessions.items() if now - v["ts"] < max_age}

    def touch(self, sid, project="", cwd=""):
        """Lebenszeichen einer Session (Postfach-Abruf) – meldet sie auch nach einem Neustart
        des Walkies sofort wieder an."""
        if not sid:
            return
        with self.lock:
            s = self.sessions.setdefault(sid, {})
            s["ts"] = time.time()
            if project:
                s["project"] = project
            if cwd:
                s["cwd"] = cwd

    # ---------------- Postfach ----------------
    def send(self, sid, text):
        """Gesprochenen Satz an Session sid schicken (der Mod holt ihn binnen ~0,5 s ab)."""
        return self.dictations.add(sid, text, pending=True)

    def take_inbox(self, sid):
        return self.dictations.take_legacy(sid)

    # ---------------- Freigaben ----------------
    def ask(self, data):
        """Wird im HTTP-Thread aufgerufen und blockiert bis zur Antwort oder zum Zeitlimit."""
        req = f"{os.getpid()}-{time.time_ns()}"
        ev = threading.Event()
        with self.lock:
            self.waiting[req] = [ev, None]
        tool = str(data.get("tool") or "")
        self.events.put({
            "event": "attention", "ts": time.time(), "agent": "claude", "own": False,
            "session": str(data.get("session") or ""), "project": data.get("project") or "",
            "reason": t("Rückfrage für dich") if tool == "AskUserQuestion" else t("Freigabe nötig: {tool}", tool=tool),
            "detail": data.get("detail") or "", "req": req, "tool": tool,
            "command": str(data.get("command") or "")[:500],
            "questions": data.get("questions") or [],
            "first": bool(data.get("first")),
        })
        wait = float(self.ask_wait())
        if data.get("first"):                  # Stimme zuerst, Dialog wartet: kurz halten
            wait = min(wait, 60.0)
        ev.wait(timeout=wait)
        with self.lock:
            _, answer = self.waiting.pop(req, (None, None))
        if not isinstance(answer, dict) or answer.get("behavior") not in ("allow", "deny"):
            return {"behavior": "pass"}
        return answer

    def resolve(self, req, answer):
        """Antwort auf eine wartende Anfrage. False, wenn niemand (mehr) wartet."""
        with self.lock:
            slot = self.waiting.get(req)
            if not slot:
                return False
            slot[1] = answer
            slot[0].set()
            return True
