"""Brücke (lokaler HTTP-Dienst) und Router – ohne GUI, ohne Netz."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import router  # noqa: E402
from bridge import Bridge  # noqa: E402


class DictationsClearTest(unittest.TestCase):
    def test_clear_removes_everything(self):
        from dictations import Dictations
        with tempfile.TemporaryDirectory() as tmp:
            store = Dictations(tmp)
            self.assertEqual(store.clear(), [])
            store.add("a", "eins", pending=True)
            store.add("b", "zwei")
            self.assertEqual([r["text"] for r in store.clear()], ["eins", "zwei"])
            self.assertEqual(store.drafts(), [])
            self.assertIsNone(store.first("a"))


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.b = Bridge(str(self.tmp), ask_wait=lambda: 2)
        self.port = self.b.start()
        info = json.loads((self.tmp / "server.json").read_text())
        self.assertEqual(info["port"], self.port)
        self.token = info["token"]

    def tearDown(self):
        self.b.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, path, body=None, token=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                   data=None if body is None else json.dumps(body).encode(),
                                   headers={"x-walkie-token": token or self.token,
                                            "content-type": "application/json"},
                                   method="GET" if body is None else "POST")
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read() or b"null")

    def test_token_required(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.req("/inbox?session=a", token="falsch")
        self.assertEqual(cm.exception.code, 403)

    def test_events_and_sessions(self):
        self.req("/event", {"event": "ready", "session": "S1", "project": "shop", "cwd": "/p/shop"})
        self.req("/event", {"event": "stop", "session": "S1", "project": "shop", "text": "fertig"})
        self.assertEqual(self.b.events.get_nowait()["event"], "ready")
        self.assertEqual(self.b.events.get_nowait()["text"], "fertig")
        self.assertEqual(self.b.active_sessions()["S1"]["project"], "shop")
        self.req("/event", {"event": "end", "session": "S1"})
        self.assertNotIn("S1", self.b.active_sessions())

    def test_inbox(self):
        self.b.send("S1", "Mach die Tests grün")
        self.b.send("S1", "und committe")
        self.assertEqual(self.req("/inbox?session=S1")["texts"], ["Mach die Tests grün", "und committe"])
        self.assertEqual(self.req("/inbox?session=S1")["texts"], [])

    def test_only_ack_removes_prompt_and_queue_survives_restart(self):
        self.b.send("A", "Erster")
        self.b.send("A", "Zweiter")
        path = "/inbox?session=A&ack=1"
        item = self.req(path)["message"]
        self.assertEqual(item["text"], "Erster")
        self.req("/ack", {"session": "B", "id": item["id"]})
        self.req("/event", {"event": "end", "session": "A"})
        self.assertEqual(Bridge(self.tmp).dictations.first("A"), item)
        self.assertEqual(self.req(path)["message"], item)
        for _ in range(2):
            self.req("/ack", {"session": "A", "id": item["id"]})
        self.assertEqual(self.req(path)["message"]["text"], "Zweiter")

    def test_ask_waits_for_answer(self):
        def answer():
            ev = self.b.events.get(timeout=5)
            self.assertEqual(ev["tool"], "Bash")
            self.b.resolve(ev["req"], {"behavior": "allow"})
        threading.Thread(target=answer, daemon=True).start()
        t0 = time.time()
        out = self.req("/ask", {"session": "S1", "tool": "Bash", "detail": "Tests"})
        self.assertEqual(out, {"behavior": "allow"})
        self.assertLess(time.time() - t0, 2)

    def test_ask_times_out_to_pass(self):
        self.assertEqual(self.req("/ask", {"session": "S1", "tool": "Bash"}), {"behavior": "pass"})
        self.assertFalse(self.b.resolve("gibts-nicht", {"behavior": "allow"}))

    def test_stop_releases_waiting(self):
        out = {}
        t = threading.Thread(target=lambda: out.update(r=self.req("/ask", {"tool": "X"})))
        t.start()
        time.sleep(0.3)
        self.b.stop()
        t.join(5)
        self.assertEqual(out.get("r"), {"behavior": "pass"})


class RouterTest(unittest.TestCase):
    S = {"a1": {"project": "shop-frontend", "ts": 100, "user_ts": 100},
         "b2": {"project": "api", "ts": 200, "user_ts": 200}}

    def setUp(self):
        # nie das echte Modell: ohne Ersatz gilt die schnelle Erkennung (wie bei einem Ausfall)
        def offline(*a, **k):
            raise OSError("kein Modell im Test")
        self._old_claude, router.ask_model = router.ask_model, offline
        self.addCleanup(setattr, router, "ask_model", self._old_claude)

    def test_by_name(self):
        self.assertEqual(router.by_name("Sag dem Shop, er soll die Tests laufen lassen", self.S), "a1")
        self.assertEqual(router.by_name("an api: deploy bitte", self.S), "b2")
        self.assertIsNone(router.by_name("Wie spät ist es?", self.S))

    def test_no_sessions_means_self_without_model(self):
        self.assertEqual(router.route("Mach die Tests grün", {})[0], "self")

    def test_model_judges_explicit_new_session_in_any_language(self):
        answers = []
        router.ask_model = lambda *a, **k: answers.pop(0)
        answers.append('{"target": "new", "explicit": true, "message": "Find gift ideas"}')
        self.assertEqual(router.understand("Could you open another Claude window for gift ideas",
                                           self.S), ("new", None, "Find gift ideas"))
        answers.append('{"target": "new", "explicit": false, "message": "Geschenkideen"}')
        kind, _target, _msg = router.understand("Geschenkideen für Weihnachten", self.S)
        self.assertEqual(kind, "session")

    def test_follow_up_goes_to_current_conversation(self):
        import time as _t
        S = {"a1": {"project": "claude-walkie", "ts": _t.time(), "user_ts": _t.time()},
             "n2": {"project": "Home", "ts": _t.time(), "user_ts": _t.time() - 120}}
        env = {**os.environ, "PATH": str(Path(tempfile.mkdtemp()))}   # Haiku nicht erreichbar
        self.assertEqual(router.route("Lies mir die Werte vor", S, env=env,
                                      last=("n2", _t.time() - 30)), ("session", "n2"))
        self.assertEqual(router.route("Lies mir die Werte vor", S, env=env,
                                      last=("n2", _t.time() - 999)), ("session", "a1"))

    def test_topics_survive_restart(self):
        d = Path(tempfile.mkdtemp())
        b = Bridge(str(d))
        b.on_event({"event": "prompt", "session": "E", "project": "Home",
                    "prompt": "Energieeinstellungen prüfen"})
        b2 = Bridge(str(d))
        self.assertNotIn("E", b2.active_sessions(), "erst wenn sie sich wieder meldet")
        b2.touch("E")
        self.assertEqual(b2.active_sessions()["E"]["first_prompt"], "Energieeinstellungen prüfen")

    def test_touch_registers_after_restart(self):
        b = Bridge(str(Path(tempfile.mkdtemp())))
        b.touch("X", "Home", "/home/x")
        self.assertEqual(b.active_sessions()["X"]["project"], "Home")

    def test_router_may_ask_back(self):
        old = router.ask_model
        router.ask_model = lambda *a, **k: '{"target": "ask", "options": ["a1", "b2", "zz"]}'
        try:
            self.assertEqual(router.route("Mach weiter", self.S), ("ask", ["a1", "b2"]))
        finally:
            router.ask_model = old

    def test_labels_tell_same_folder_apart(self):
        S = {"x": {"project": "Home", "first_prompt": "Energieeinstellungen prüfen bitte"},
             "y": {"project": "Home", "first_prompt": "Tech-Aktien recherchieren"},
             "z": {"project": "api"}}
        self.assertEqual(router.label("x", S), "Home, Energieeinstellungen prüfen bitte")
        self.assertEqual(router.label("z", S), "api")

    def test_named_project_without_session_opens_new_one_there(self):
        root = Path(tempfile.mkdtemp())
        (root / "video-player").mkdir()
        (root / "Downloads").mkdir()
        dirs = [root / "video-player"]
        self.assertEqual(router.by_folder("am Video-Plejer weiterarbeiten", dirs), root / "video-player")
        self.assertIsNone(router.by_folder("Wie spät ist es?", dirs))
        old = router.project_dirs
        router.project_dirs = lambda: dirs
        try:
            self.assertEqual(router.route("Lass uns am Video Player weitermachen", self.S),
                             ("new", str(root / "video-player")))
            S = {**self.S, "m": {"project": "video-player", "cwd": str(root / "video-player")}}
            self.assertEqual(router.route("Lass uns am Video Player weitermachen", S),
                             ("session", "m"), "läuft schon -> dorthin")
        finally:
            router.project_dirs = old

    def test_no_sessions_means_self(self):
        self.assertEqual(router.route("Hallo", {}), ("self", None))

    def test_llm_failure_falls_back_to_latest(self):
        env = {**os.environ, "PATH": str(Path(tempfile.mkdtemp()))}   # kein claude im PATH
        self.assertEqual(router.route("Wie läuft's?", self.S, env=env), ("session", "b2"))


class WindowTest(unittest.TestCase):
    def test_ancestor_chain_reaches_parent(self):
        import windows
        chain = windows.ancestors(os.getpid())
        self.assertEqual(chain[0], os.getpid())
        if sys.platform != "win32":
            self.assertIn(os.getppid(), chain)

    def test_no_pid_no_raise(self):
        import windows
        self.assertFalse(windows.raise_pid(None))


class TranscriptTest(unittest.TestCase):
    def test_topic_last_question_and_answer(self):
        import json as _j

        import transcripts
        root = Path(tempfile.mkdtemp())
        (root / "-home-x").mkdir()
        lines = [
            {"type": "user", "message": {"content": "<command-name>/clear</command-name>"}},
            {"type": "user", "message": {"content": "Schau dir die Energieverwaltung an"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Mache ich."}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            {"type": "user", "message": {"content": "The walkie plugin sent a message:\nLies vor"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Bildschirm: 10 Min."}]}},
        ]
        (root / "-home-x" / "S1.jsonl").write_text("\n".join(_j.dumps(x) for x in lines))
        old = transcripts.PROJECTS
        transcripts.PROJECTS = root
        try:
            c = transcripts.context("S1")
        finally:
            transcripts.PROJECTS = old
        self.assertEqual(c, {"topic": "Schau dir die Energieverwaltung an",
                             "last_user": "Lies vor", "last_answer": "Bildschirm: 10 Min."})
        self.assertEqual(transcripts.context("gibts-nicht"), {})


if __name__ == "__main__":
    unittest.main()
