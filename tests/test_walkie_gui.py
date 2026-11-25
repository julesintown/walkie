"""Begleiter-Logik offscreen mit synthetischer Mini-Figur (keine geschützten Grafiken nötig).
Übersprungen, wenn PyQt6 fehlt."""
import os as _os, sys as _sys  # noqa: E401 – zuerst: nie in die echten Walkie-Ordner
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import isolate  # noqa: E402,F401
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp())
os.environ.update(QT_QPA_PLATFORM="offscreen", WALKIE_RUN=str(TMP / "run"), WALKIE_SESSION_DIR=str(TMP / "sessions"),
                  WALKIE_CONFIG=str(TMP / "config.env"),
                  XDG_RUNTIME_DIR=str(TMP), WALKIE_SPRITE=str(TMP / "sprite"),
                  WALKIE_HEADSET="off", WALKIE_AGENT="claude", WALKIE_NO_WELCOME="1",
                  WALKIE_HOTKEY="")

try:
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

ANIMS = ["Idle", "Walk", "Sleep", "Charge", "Nod", "Hop", "Hurt", "DeepBreath"]


def make_sprite(folder):
    """Ein 8-Richtungen-Sheet je Animation, 2 Frames à 24x24, mit Fuß-Pixeln."""
    folder.mkdir(parents=True, exist_ok=True)
    xml = ["<AnimData><Anims>"]
    for name in ANIMS:
        img = QImage(48, 24 * 8, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        for r in range(8):
            for f in range(2):
                for x in range(6, 18):
                    for y in range(8, 20):
                        img.setPixelColor(f * 24 + x, r * 24 + y, QColor("#c08040"))
        img.save(str(folder / f"{name}-Anim.png"))
        xml.append(f"<Anim><Name>{name}</Name><FrameWidth>24</FrameWidth><FrameHeight>24"
                   "</FrameHeight><Durations><Duration>8</Duration><Duration>8</Duration>"
                   "</Durations></Anim>")
    xml.append("</Anims></AnimData>")
    (folder / "AnimData.xml").write_text("".join(xml), encoding="utf-8")


@unittest.skipIf(QApplication is None, "PyQt6 fehlt")
class WalkieTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from unittest.mock import patch
        cls.enter_language = patch.dict(os.environ, LC_ALL="de_DE.UTF-8", PYTHONIOENCODING="utf-8")
        cls.enter_language.start()
        cls.addClassCleanup(cls.enter_language.stop)
        import settings
        config = patch.object(settings, "CONFIG", TMP / "config.env")
        config.start()
        cls.addClassCleanup(config.stop)
        settings.raw_values(force=True)
        cls.app = QApplication.instance() or QApplication([])
        make_sprite(TMP / "sprite")
        (TMP / "run").mkdir(parents=True, exist_ok=True)
        (TMP / "run" / "welcomed").write_text("1", encoding="utf-8")   # Ersteinrichtung nicht automatisch öffnen
        import walkie as bmod
        cls.ev = bmod
        cls.load_whisper = staticmethod(bmod.Walkie.load_whisper)
        cls.set_voice = staticmethod(bmod.Walkie.set_voice)
        cls.notes = []
        bmod.notify = cls.notes.append
        bmod.media_tracker = lambda: None
        bmod.beep = lambda *a, **kw: None
        bmod.Walkie.mic_watch = lambda self: None
        bmod.HeadsetAudio.retry = lambda self: None
        cls.reader = staticmethod(bmod.headset_loop)
        bmod.headset_loop = lambda bus, stop: None
        # Tests unabhängig von der Maschine: kein echter Kopfhörer, keine echten Geräte
        bmod.keymap.connected_headsets = lambda: []
        bmod.Walkie.has_terminal = lambda self: False     # kein echtes kitty-Terminal in Tests
        bmod.headset_mic = lambda: None
        # Tests inspect queued announcements before playback and use no real audio devices.
        import keys
        from types import SimpleNamespace
        for target, attr, replacement in (
                (bmod.Walkie, "announcer", lambda self: None),
                (bmod.Walkie, "set_voice", lambda *args, **kwargs: None),
                (bmod.audio, "Player", lambda *args, **kwargs: SimpleNamespace(ok=False)),
                (keys, "start", lambda *args, **kwargs: [])):
            guard = patch.object(target, attr, replacement)
            guard.start()
            cls.addClassCleanup(guard.stop)
        bmod.Walkie.load_whisper = lambda self: None
        bmod.Walkie.refresh_panel = lambda self: None
        bmod.Surfaces.start = lambda self, *a: None      # kein KWin-Skript auf dem echten Desktop
        bmod.Walkie.summarize = lambda self, text, question=False, request="": (
            text if question else f"Zusammenfassung({len(text)})")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        # Tests fragen nie ein echtes Modell an; wer eins braucht, setzt eine feste Antwort.
        router = self.ev.router

        def offline(*a, **k):
            raise OSError("kein Modell im Test")
        self.addCleanup(setattr, router, "ask_model", router.ask_model)
        router.ask_model = offline
        self.b = self.ev.Walkie()
        self.notes.clear()

    def tearDown(self):
        from PyQt6.QtCore import QTimer
        self.b.device_stop.set()
        for timer in self.b.findChildren(QTimer):
            timer.stop()
        self.b.bridge.stop()                 # Brücke + server.json weg (wie beim Beenden)

    def hook(self, *args, own=False, **data):
        env = {k: v for k, v in os.environ.items() if k != "WALKIE_SESSION"}
        if own:
            env["WALKIE_SESSION"] = "1"
        subprocess.run([sys.executable, str(ROOT / "hook.py"), *args], input=json.dumps(data),
                       encoding="utf-8", env=env, check=True, timeout=20, capture_output=True)

    def view(self):
        self.b.poll_events()
        self.b.step()
        self.b.grab()                       # paintEvent einmal durchlaufen
        return self.b.view

    def test_available_desktop_tray_has_sprite_icon_at_startup(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QSystemTrayIcon
        with (patch.object(self.ev, "LINUX", False), patch.object(self.ev, "NOTIFIER"),
              patch.object(self.ev.Bridge, "start"), patch.object(QSystemTrayIcon, "show"),
              patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)):
            desktop = self.ev.Walkie()
            try:
                self.assertFalse(desktop.tray.icon().isNull())
                self.assertIs(desktop.tray.contextMenu(), desktop.tray_menu)
            finally:
                desktop.device_stop.set()
                desktop.deleteLater()

    def test_priority_across_sessions(self):
        self.assertEqual(self.view(), "idle")
        self.hook("--plugin", "prompt", session_id="A")
        self.assertEqual(self.view(), "thinking")
        self.hook("--plugin", "attention", session_id="B", tool_name="Bash")
        self.assertEqual(self.view(), "attention")
        self.assertEqual(self.notes, ["Freigabe nötig: Bash"])
        self.hook("--plugin", "attention", session_id="B", tool_name="Bash")
        self.assertEqual(len(self.notes), 1, "keine Doppel-Benachrichtigung")
        self.hook("--plugin", "tool", session_id="B")
        self.assertEqual(self.view(), "thinking")
        self.hook("--plugin", "stop", session_id="A")
        self.hook("--plugin", "stop", session_id="B")
        self.assertEqual(self.view(), "idle")

    def test_error_decays(self):
        self.hook("--plugin", "error", session_id="A", error_type="rate_limit")
        self.assertEqual(self.view(), "error")
        self.b.sessions["A"]["ts"] -= self.ev.ERROR_SHOW + 1
        self.assertEqual(self.view(), "idle")

    def test_done_notification_only_for_long_tasks(self):
        self.hook("--plugin", "prompt", session_id="A")
        self.view()
        self.hook("--plugin", "stop", session_id="A")
        self.view()
        self.assertEqual(self.notes, [])
        self.hook("--plugin", "prompt", session_id="A")
        self.view()
        self.b.sessions["A"]["since"] -= self.ev.S.get("WALKIE_ANNOUNCE_AFTER") + 1
        self.hook("--plugin", "stop", session_id="A")
        self.view()
        self.assertEqual(len(self.notes), 1)

    def said(self):
        out = []
        while not self.b.say_q.empty():
            out.append(self.b.say_q.get_nowait())
        return out

    def test_announces_attention_with_project_and_detail(self):
        self.b.announce_on = True
        self.b.say_q = __import__("queue").Queue()      # Vorleser-Thread nicht dazwischen
        self.hook("--plugin", "attention", session_id="B", cwd="/home/x/shop",
                  tool_name="Bash", tool_input={"command": "rm -rf build",
                                                "description": "Build-Ordner löschen"})
        self.view()
        self.assertEqual(self.said(), ["shop braucht dich. Freigabe nötig: Bash. "
                                       "Build-Ordner löschen."])
        self.hook("--plugin", "attention", session_id="C", tool_name="AskUserQuestion",
                  tool_input={"questions": [{"question": "Welche Datenbank?"}]})
        self.view()
        self.assertEqual(self.said(), ["Claude braucht dich. Rückfrage für dich. "
                                       "Welche Datenbank?"])

    def test_typed_answers_are_read_when_reading_is_on(self):
        """Walkie an = jede Antwort hören, auch auf getippte Nachrichten (Schalter: Antworten
        vorlesen)."""
        b = self.b
        spoken = []
        b.voice_on = True
        b.in_thread = lambda fn, *a: spoken.append(a) if fn == b.speak_answer else None
        self.hook("--plugin", "prompt", session_id="T", cwd="/p/api")
        self.view()
        self.hook("--plugin", "stop", session_id="T", cwd="/p/api",
                  last_assistant_message="Erledigt, alles grün.")
        self.view()
        self.assertEqual(spoken, [("T", "api", "Erledigt, alles grün.")])

    def test_announces_done_only_after_real_work(self):
        """Antworten vorlesen aus: nur kurze Fertig-Ansagen nach echter Arbeit."""
        self.b.voice_on = False
        self.addCleanup(setattr, self.b, "voice_on", True)
        self.b.announce_on = True
        done = []
        self.b.in_thread = lambda fn, *a: done.append(a) if fn == self.b.announce_done else None
        self.hook("--plugin", "prompt", session_id="A", cwd="/p/api")
        self.view()
        self.hook("--plugin", "stop", session_id="A", last_assistant_message="Kurz.")
        self.view()
        self.assertEqual(done, [], "kurze Runde -> keine Ansage")
        self.hook("--plugin", "prompt", session_id="A", cwd="/p/api")
        self.view()
        self.b.sessions["A"]["since"] -= self.ev.S.get("WALKIE_ANNOUNCE_AFTER") + 1
        self.hook("--plugin", "stop", session_id="A", cwd="/p/api",
                  last_assistant_message="Tests laufen grün.")
        self.view()
        self.assertEqual(done, [("A", "api", "Tests laufen grün.")])
        self.b.say_q = __import__("queue").Queue()
        self.b.bridge.active_sessions = lambda: {"A": {}}
        self.ev.Walkie.announce_done(self.b, *done[0])
        self.assertEqual(self.said(), ["Fertig. Zusammenfassung(18)."], "nur eine Session")
        self.b.bridge.active_sessions = lambda: {"A": {"project": "api"}, "B": {"project": "api"}}
        self.ev.Walkie.announce_done(self.b, *done[0])
        self.assertEqual(self.said(), ["Fertig. Zusammenfassung(18)."], "alle heißen gleich")
        self.b.bridge.active_sessions = lambda: {"A": {"project": "api"}, "B": {"project": "web"}}
        self.b.focus_sid = "B"                                   # Nutzer arbeitet gerade in B
        self.ev.Walkie.announce_done(self.b, *done[0])
        self.assertEqual(self.said(), ["api ist fertig. Zusammenfassung(18)."], "andere Session")
        self.b.focus_sid = "A"                                   # dort zuletzt etwas abgeschickt
        self.ev.Walkie.announce_done(self.b, *done[0])
        self.assertEqual(self.said(), ["Fertig. Zusammenfassung(18)."], "gerade dort gearbeitet")

    def test_risky_command_is_never_allowed_by_key_alone(self):
        b = self.b
        b.say_q = __import__("queue").Queue()
        written = []
        b.write_answer = lambda req, ans: written.append((req, ans))
        b.pending = {"r1": {"session": "S", "who": "api", "tool": "Bash", "detail": "Aufräumen",
                            "command": "rm -rf build", "questions": [], "answers": {}, "ts": 0}}
        b.decide_newest("allow")
        self.assertEqual(written, [], "rm -rf nicht blind per Taste")
        self.assertIn("r1", b.pending)
        self.assertIn("per Stimme bestätigen", b.say_q.get_nowait())
        b.pending["r1"]["command"] = "npm test"
        b.decide_newest("allow")
        self.assertEqual(written, [("r1", {"behavior": "allow"})])

    def test_figure_comes_back_after_resolution_change_or_minimize(self):
        from PyQt6.QtWidgets import QApplication
        b = self.b
        b.show()
        g = QApplication.primaryScreen().geometry()
        b.climb.mode = "wall"
        b.move(g.right() + 600, g.bottom() + 600)          # alter, größerer Bildschirm
        b.keep_on_screen()
        self.assertTrue(g.contains(b.frameGeometry().center()))
        self.assertEqual(b.climb.mode, "floor")
        b.showMinimized()
        self.app.processEvents()
        b.keep_on_screen()
        self.app.processEvents()
        self.assertFalse(b.isMinimized(), "minimiert bliebe sie unerreichbar (nicht in der Taskleiste)")
        self.assertTrue(b.isVisible())

    def test_terminal_window_opens_raises_and_resumes(self):
        import paths
        import windows
        b, ev = self.b, self.ev
        (ev.RUN / b.TERMINAL_STATE).unlink(missing_ok=True)
        opened = []

        class Proc:
            pid = 4321
            alive = True
            def poll(self): return None if self.alive else 0
        proc = Proc()
        with patch.object(ev, "PANEL", False), \
                patch.object(b, "in_thread", lambda fn, *a: fn(*a)), \
                patch.object(paths, "open_terminal",
                             lambda argv, **k: opened.append((argv, k)) or proc), \
                patch.object(windows, "raise_pid", return_value=True) as raised:
            b.show_terminal()                                  # erstes Öffnen
            argv, kw = opened[-1]
            self.assertEqual(kw["env_extra"], {"WALKIE_IN_TERMINAL": "1"})
            self.assertEqual(kw["cwd"], ev.new_session_dir(), "eigener Ordner, nie das Home")
            self.assertNotEqual(kw["cwd"], str(Path.home()))
            conv = b.terminal_state()["id"]
            self.assertIn("--session-id", argv)               # Claude: feste ID
            self.assertEqual(argv[-1], conv)
            b.show_terminal()                                  # noch offen: nach vorne
            if sys.platform.startswith("linux"):
                self.assertEqual(len(opened), 1)
                raised.assert_called_with(4321, log=ev.dbg)
            proc.alive = False                                 # Fenster geschlossen
            b.show_terminal()
            self.assertEqual(opened[-1][0][-1], conv, "dasselbe Gespräch wieder")
        b.remember_terminal_conversation({"terminal": True, "session": "neu-1", "agent": "claude"})
        self.assertEqual(b.terminal_state()["id"], "neu-1")
        b.remember_terminal_conversation({"session": "fremd", "agent": "claude"})
        self.assertEqual(b.terminal_state()["id"], "neu-1", "nur Ereignisse aus dem Walkie-Terminal")

    def test_bluetooth_start_beep_waits_for_signal_and_is_blanked(self):
        """BT-Telefonmodus: Piep erst bei echtem Signal; der Ton wird in der Aufnahme genullt."""
        import struct
        b, ev = self.b, self.ev
        path = TMP / "bt.wav"
        signal = struct.pack("<8h", *[60] * 8)           # Stille vor dem Piep: Grundrauschen
        path.write_bytes(b"\0" * 44 + b"\0\0" * 100 + signal + struct.pack("<50h", *[900] * 50))

        class Rec:
            def data_bytes(self):
                return path.stat().st_size - 44 - 40       # die letzten 20 Samples: nach dem Ton

        rec = Rec()
        b.rec_proc, b.live_wait = rec, True
        beeps = []
        with patch.object(ev, "beep", lambda *a, **k: beeps.append(a)), \
                patch.object(type(b), "BEEP_TAIL", 0), patch.object(type(b), "NOISE_SAMPLES", 8):
            b._beep_when_live(rec, str(path))
        data = path.read_bytes()[44:]
        mark = rec.data_bytes()
        self.assertEqual(beeps, [()])
        self.assertFalse(b.live_wait)
        self.assertEqual(data[:mark], bytes(mark))         # Ton und Anlauf ausgeblendet
        self.assertNotEqual(data[mark:], bytes(len(data) - mark))
        self.assertEqual(b.rec_pos, 44 + mark)
        self.assertAlmostEqual(b.noise, 60 / 32768, places=5)   # vor dem Piep gemessen, nicht danach
        b.rec_proc = None

    def test_bluetooth_noise_floor_ignores_early_speech(self):
        """Wer schon vor dem Piep redet, macht seine Stimme nicht zum „Rauschen“."""
        import struct
        b, ev = self.b, self.ev
        path = TMP / "bt2.wav"
        path.write_bytes(b"\0" * 44 + struct.pack("<60h", *[8000] * 60))

        class Rec:
            def data_bytes(self):
                return 80

        rec = Rec()
        b.rec_proc, b.live_wait = rec, True
        with patch.object(ev, "beep", lambda *a, **k: None), \
                patch.object(type(b), "BEEP_TAIL", 0), patch.object(type(b), "NOISE_SAMPLES", 8):
            b._beep_when_live(rec, str(path))
        self.assertEqual(b.noise, type(b).NOISE_MAX)
        b.rec_proc = None

    def test_talk_pipeline_logs_step_timings(self):
        """Eine Logzeile pro Äußerung: Dauer von Vokabel, Whisper, Router und Zustellen."""
        import queue
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        lines = []
        with patch.object(ev, "transcribe", lambda model, wav, hint=None: "Hallo du."), \
                patch.object(ev.router, "understand",
                             lambda text, sessions, **k: ("unclear", None, text)), \
                patch.object(ev, "dbg", lines.append):
            b.talk_pipeline(str(TMP / "nichts.wav"), laps=ev.Laps())
        timing = [x for x in lines if x.startswith("zeiten: ")]
        self.assertEqual(len(timing), 1)
        for step in ("vokabel", "whisper", "router", "unclear", "gesamt"):
            self.assertIn(f"{step} ", timing[0])

    def test_overview_question_goes_to_the_model_with_facts(self):
        """Ob kurz, eine Session oder Projektstand: das Modell entscheidet anhand der Frage."""
        import queue
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        b.seen_ts = 0
        b.handle_event({"event": "stop", "session": "M1", "project": "dashboard",
                        "text": "Die Tests sind durch."})
        prompts = []
        with patch.object(ev, "transcribe", lambda model, wav, hint=None: "Na, was läuft so?"), \
                patch.object(ev.router, "understand",
                             lambda text, sessions, **k: ("overview", None, "Was läuft so?")), \
                patch.object(ev.router, "brains", return_value=["claude"]), \
                patch.object(ev.router, "ask_model",
                             lambda prompt, *a, **k: prompts.append(prompt) or "Dashboard ist fertig."):
            b.talk_pipeline(str(TMP / "nichts.wav"))
        self.assertIn("Was läuft so?", prompts[0])
        self.assertIn("Die Tests sind durch.", prompts[0])
        said = []
        while not b.say_q.empty():
            said.append(b.say_q.get_nowait())
        self.assertIn("Dashboard ist fertig.", said)
        b.bridge.events.queue.clear()

    def test_overview_without_model_is_a_short_fallback(self):
        b, ev = self.b, self.ev
        b.seen_ts = 0
        b.handle_event({"event": "stop", "session": "M2", "project": "api", "text": "Fertig."})
        with patch.object(ev.router, "brains", return_value=[]):
            self.assertIn("api ist fertig", b.missed())
            self.assertNotIn("api", b.missed(), "danach gilt es als gehört")
        b.bridge.events.queue.clear()

    def test_critical_command_needs_the_code_confirmed_by_the_model(self):
        b = self.b
        p = {"tool": "Bash", "command": "vercel deploy --prod", "code": 42}

        def judge(decision, code_said=False):
            return lambda situation, said: (self.assertEqual(situation["confirmation_code"], 42)
                                            or {"decision": decision, "code_said": code_said})
        allow = {"behavior": "allow"}
        self.assertEqual(b.check_code(p, "zweiundvierzig", judge("allow", True))[0], allow)
        self.assertEqual(b.check_code(p, "Bestätige 42", judge("allow"))[0], allow)
        self.assertIsNone(b.check_code(p, "Ja, mach.", judge("allow"))[0],
                          "ein Ja ohne bestätigten Code gibt nichts frei")
        self.assertEqual(b.check_code(p, "Nein, auf keinen Fall 42", judge("deny"))[0]["behavior"],
                         "deny", "das Modell versteht das Nein trotz Ziffern")
        self.assertEqual(b.check_code(p, "Bestätige 42", lambda s, t: None)[0], allow,
                         "ohne Modell: Ziffern genügen")
        self.assertIsNone(b.check_code(p, "zweiundvierzig", lambda s, t: None)[0],
                          "ohne Modell: nur Ziffern, keine Zahlwortlisten")

    def test_interpret_permission(self):
        p = {"questions": [], "answers": {}, "tool": "Bash", "detail": "rm -rf build"}
        f = self.ev.Walkie.interpret
        seen = []

        def judge(decision, **extra):
            return lambda situation, said: seen.append((situation, said)) or dict(
                decision=decision, **extra)
        self.assertEqual(f(p, "Yes, go ahead.", judge("allow"))[0], {"behavior": "allow"})
        self.assertEqual(seen[0][0]["kind"], "permission")
        self.assertEqual(seen[0][1], "Yes, go ahead.")
        deny = f(p, "Nein, nimm lieber yarn.", judge("deny", message="nimm lieber yarn"))[0]
        self.assertEqual(deny["behavior"], "deny")
        self.assertIn("yarn", deny["message"])
        self.assertIsNone(f(p, "Äh, Moment.", judge("unclear"))[0])
        self.assertIsNone(f(p, "Ja.", lambda *a: None)[0], "ohne Modell: am Rechner entscheiden")
        self.assertIsNone(f(p, "   ", judge("allow"))[0], "Stille ist keine Zustimmung")
        self.assertEqual(f(p, "Was genau?", judge("repeat"))[0], "repeat")

    def test_interpret_question(self):
        f = self.ev.Walkie.interpret
        q = lambda multi=False: {"questions": [{"question": "Welche Farbe?",  # noqa: E731
                                                "options": ["Rot", "Blau"], "multi": multi}],
                                 "answers": {}}
        pick = lambda *v, other="": lambda s, t: {"decision": "answer",  # noqa: E731
                                                   "values": list(v), "other": other}
        self.assertEqual(f(q(), "Rot bitte.", pick("Rot"))[0],
                         {"behavior": "allow", "answers": {"Welche Farbe?": "Rot"}})
        self.assertEqual(f(q(True), "red and blue", pick("Rot", "Blau"))[0]["answers"],
                         {"Welche Farbe?": "Rot, Blau"})
        self.assertEqual(f(q(), "both", pick("Rot", "Blau"))[0]["answers"],
                         {"Welche Farbe?": "Rot"}, "Einfachauswahl: höchstens eine Option")
        self.assertEqual(f(q(), "Lieber grün.", pick(other="Grün"))[0]["answers"],
                         {"Welche Farbe?": "Grün"})
        self.assertEqual(f(q(), "Lila", pick("Lila"))[0]["answers"], {"Welche Farbe?": "Lila"},
                         "erfundene Option -> Wortlaut")
        self.assertEqual(f(q(), "forget it", lambda s, t: {"decision": "cancel"})[0]["behavior"],
                         "deny")
        self.assertIsNone(f(q(), "hm", lambda s, t: {"decision": "unclear"})[0])
        self.assertEqual(f(q(), "Blau", lambda *a: None)[0]["answers"], {"Welche Farbe?": "Blau"},
                         "ohne Modell: exakt genannte Option")
        two = q()
        two["questions"].append({"question": "Wie groß?", "options": ["S", "M"], "multi": False})
        self.assertEqual(f(two, "Blau", pick("Blau"))[0], "next")
        self.assertEqual(f(two, "the first", pick("S"))[0]["answers"],
                         {"Welche Farbe?": "Blau", "Wie groß?": "S"})

    def test_interpret_reply(self):
        f = self.ev.Walkie.interpret
        p = {"kind": "reply", "questions": [], "answers": {}, "prompt": "Soll ich weitermachen?"}
        self.assertEqual(f(p, "Ja, aber vorsichtig.", lambda s, t: {"decision": "reply"})[0],
                         {"behavior": "reply", "text": "Ja, aber vorsichtig."})
        self.assertEqual(f(p, "later", lambda s, t: {"decision": "pass"})[0], {"behavior": "pass"})
        self.assertEqual(f(p, "Weiter so.", lambda *a: None)[0]["behavior"], "reply",
                         "ohne Modell: Wortlaut weitergeben")
        self.assertEqual(f(p, "Welches Modell denn?", lambda s, t: {"decision": "repeat"})[0],
                         {"behavior": "reply", "text": "Welches Modell denn?"},
                         "offene Frage: Rückfrage geht an die Session, nicht nochmal vorlesen")

    def start_voice_hook(self, event, data, env):
        # The hook must see EOF before the test can answer its request. Use a file
        # for stdin so communicate() never tries to flush a closed pipe.
        with tempfile.TemporaryFile() as payload:
            payload.write(json.dumps(data).encode("utf-8"))
            payload.seek(0)
            proc = subprocess.Popen([sys.executable, str(ROOT / "hook.py"), "--plugin", event],
                                    stdin=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    encoding="utf-8", env=env)

        def cleanup():
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
            proc.stdout.close()
            proc.stderr.close()

        self.addCleanup(cleanup)
        return proc

    def voice_hook_output(self, proc):
        stdout, stderr = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, stderr)
        return stdout

    def test_voice_permission_end_to_end(self):
        """hook.py wartet, der Begleiter legt die Antwort ab, hook.py gibt die Entscheidung aus."""
        from hook import acquire_lock
        lock = acquire_lock()
        self.assertIsNotNone(lock)
        try:
            self.b.announce_on = True
            env = {k: v for k, v in os.environ.items() if k != "WALKIE_SESSION"}
            data = {"session_id": "Q", "cwd": "/p/shop", "tool_name": "AskUserQuestion",
                    "tool_input": {"questions": [{"question": "Welche Farbe?", "options": [
                        {"label": "Rot", "description": ""}, {"label": "Blau",
                                                              "description": ""}]}]}}
            proc = self.start_voice_hook("ask", data, env)
            import time
            for _ in range(100):
                self.view()
                if self.b.pending:
                    break
                time.sleep(0.05)
            (req, p), = self.b.pending.items()
            self.assertEqual(p["who"], "shop")
            self.assertEqual(self.b.prompt_text(p),
                             "Welche Farbe? Optionen: Rot oder Blau.")   # nur eine Session
            result, _ = self.ev.Walkie.interpret(
                p, "Blau.", lambda s, t: {"decision": "answer", "values": ["Blau"]})
            self.b.write_answer(req, result)
            out = json.loads(self.voice_hook_output(proc))
            d = out["hookSpecificOutput"]["decision"]
            self.assertEqual(d["behavior"], "allow")
            self.assertEqual(d["updatedInput"]["answers"], {"Welche Farbe?": "Blau"})
            self.assertEqual(d["updatedInput"]["questions"][0]["question"], "Welche Farbe?")
            # Session macht weiter (im Terminal beantwortet) -> Anfrage verfällt
            self.b.pending[req] = p
            self.hook("--plugin", "tool", session_id="Q")
            self.view()
            self.assertEqual(self.b.pending, {})
        finally:
            lock.close()

    def test_voice_reply_to_session_question(self):
        """Session endet mit Frage -> Stop-Hook wartet, Antwort setzt die Session fort."""
        from hook import acquire_lock
        import time
        lock = acquire_lock()
        self.assertIsNotNone(lock)
        try:
            self.b.announce_on = True
            env = {k: v for k, v in os.environ.items() if k != "WALKIE_SESSION"}
            msg = "Ich habe das Widget gefunden.\n\nSoll ich es aus dem Repo entfernen?"

            def stop_hook():
                proc = self.start_voice_hook("stop", {"session_id": "R", "cwd": "/p/walkie",
                                                      "last_assistant_message": msg}, env)
                for _ in range(100):
                    self.view()
                    if any("fragt:" in x["prompt"] for x in self.b.pending.values()):
                        break
                    time.sleep(0.05)
                return proc

            proc = stop_hook()
            (req, p), = self.b.pending.items()
            self.assertEqual(p["kind"], "reply")
            self.assertIn("Soll ich es aus dem Repo entfernen?", self.b.prompt_text(p))
            result, _ = self.ev.Walkie.interpret(p, "Ja, aber sichere es vorher.",
                                                lambda s, t: {"decision": "reply"})
            self.b.write_answer(req, result)
            out = json.loads(self.voice_hook_output(proc))
            self.assertEqual(out["decision"], "block")
            self.assertIn("Ja, aber sichere es vorher.", out["reason"])

            # Stille / "abbrechen" -> Session endet sofort normal (keine Ausgabe)
            self.b.pending.clear()
            proc = stop_hook()
            (req, p), = self.b.pending.items()
            result, _ = self.ev.Walkie.interpret(p, "Abbrechen.", lambda s, t: {"decision": "pass"})
            self.b.write_answer(req, result)
            self.assertEqual(self.voice_hook_output(proc), "")
        finally:
            lock.close()

    def test_expired_question_is_announced_not_misrouted(self):
        """Wartet die Session nicht mehr, darf Play die Antwort nicht ins Leere schicken."""
        import queue
        self.b.say_q = queue.Queue()
        self.b.pending["r1"] = {"session": "S", "who": "shop", "kind": "reply", "tool": "",
                                "detail": "", "reason": "", "questions": [], "answers": {},
                                "prompt": "shop fragt: Weiter?", "ts": 0}
        started = []
        self.b.start_listening = lambda *a, **k: started.append(k)
        self.b.headset_toggle()
        self.assertEqual(self.b.pending, {})
        self.assertIn("shop ist schon abgelaufen", self.b.say_q.get_nowait().replace(
            "Die Frage von ", ""))
        self.assertEqual(started, [], "nicht stillschweigend ans eigene Terminal")
        self.b.headset_toggle()                  # zweiter Druck: normal reden
        self.assertEqual(len(started), 1)

    def test_no_listen_tone_before_terminal_ready(self):
        """Claude-Diktat: erst zuhören (Pling + Aufnahme), wenn das Terminal bereit ist."""
        if self.ev.STT_MODE != "claude":
            self.skipTest("nur im Claude-Diktat-Modus")
        prepared, tones = [], []
        self.b.cc_prepare = lambda pos, silence: prepared.append(silence)
        self.b.term.running = lambda: False
        orig_beep = self.ev.beep
        self.ev.beep = lambda *a, **k: tones.append(a)
        try:
            self.b.start_listening(silence=60)
            import time
            time.sleep(0.1)
        finally:
            self.ev.beep = orig_beep
        self.assertEqual(self.b.state, "thinking")
        self.assertEqual(prepared, [60])
        self.assertNotIn((True,), tones, "kein 'ich höre zu', solange das Terminal startet")
        self.assertIsNone(self.b.rec_proc)

    def test_mic_prepared_off_gui_thread_then_records(self):
        """Mikro umschalten + Ton im Hintergrund, Aufnahme erst danach (GUI hängt nicht)."""
        import time
        ev, b = self.ev, self.b
        calls = []
        old = (b.headset_audio.prepare, ev.beep, b.headset_audio.release, ev.audio.Recorder)
        b.headset_audio.prepare = lambda *args: time.sleep(0.3) or calls.append("bt")
        ev.beep = lambda *a, **k: calls.append(("beep", k.get("up", a[0] if a else None)))
        b.headset_audio.release = lambda *args: None
        class FakeRec:
            error = ""
            def start(self, path, device=None): return True
            def alive(self): return True
            def stop(self): pass
        ev.audio.Recorder = FakeRec
        try:
            b.whisper = object()
            b.pending["q"] = {"session": "S", "who": "x", "kind": "reply", "tool": "",
                              "detail": "", "reason": "", "questions": [], "answers": {},
                              "prompt": "x fragt: ?", "ts": time.time()}
            t0 = time.time()
            b.start_listening(silence=6, answer="q")
            self.assertLess(time.time() - t0, 0.2, "start_listening blockiert den GUI-Thread")
            self.assertEqual(b.state, "thinking")
            for _ in range(100):
                self.app.processEvents()
                if b.state == "listening":
                    break
                time.sleep(0.02)
            self.assertEqual(b.state, "listening")
            self.assertEqual(calls, (["bt"] if ev.LINUX else []) + [("beep", True)])
            self.assertIsNotNone(b.rec_proc)
        finally:
            b.rec_proc = None
            b.level_timer.stop()
            b.rec_limit.stop()
            b.headset_audio.prepare, ev.beep, b.headset_audio.release, ev.audio.Recorder = old

    def test_question_via_mod_answer_goes_to_inbox(self):
        """Frage am Ende (vom Mod gemeldet): vorlesen, Antwort als nächster Prompt ins Postfach."""
        b = self.b
        b.announce_on = True
        b.bridge.on_event({"event": "stop", "session": "M1", "project": "shop",
                           "text": "Fertig.\n\nSoll ich committen?", "question": True})
        import time
        for _ in range(100):
            self.view()
            if any("fragt:" in x["prompt"] for x in b.pending.values()):
                break
            time.sleep(0.02)
        (req, p), = b.pending.items()
        self.assertEqual((p["kind"], p["via"], p["session"]), ("reply", "mod", "M1"))
        old = self.ev.transcribe
        self.ev.transcribe = lambda model, wav, hint=None: "Ja, mach das."
        try:
            b.whisper = object()
            wav = TMP / "antwort.wav"
            wav.write_bytes(b"")
            b.answer_pipeline(str(wav), req)          # echter Weg: erkennen -> zustellen
        finally:
            self.ev.transcribe = old
        self.assertEqual(b.bridge.take_inbox("M1"), ["Ja, mach das."])
        self.assertNotIn(req, b.pending)
        b.prune_pending()                     # Mod-Fragen verfallen nicht
        b.bridge.events.queue.clear()

    def test_direct_mode_binds_the_mic_to_one_session(self):
        import queue
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        b.raise_session = lambda *a, **k: True
        b.bridge.on_event({"event": "ready", "session": "R1", "project": "api"})
        b.bridge.on_event({"event": "ready", "session": "R2", "project": "shop"})
        said = iter(["Talk only to the shop", "Mach die Tests grün", "back to normal"])
        seen = []

        def understand(text, sessions, direct=None, **k):
            seen.append(direct)
            return {"Talk only to the shop": ("direct", "R2", ""),
                    "Mach die Tests grün": ("session", direct, text),
                    "back to normal": ("direct_end", None, "")}[text]
        old = (ev.transcribe, ev.router.understand)
        try:
            ev.transcribe = lambda model, wav, hint=None: next(said)
            ev.router.understand = understand
            b.talk_pipeline(str(TMP / "nichts.wav"))
            self.assertEqual(b.direct, "R2")
            self.assertIn("direkt an shop", b.say_q.get_nowait())
            b.talk_pipeline(str(TMP / "nichts.wav"))
            self.assertEqual(b.bridge.take_inbox("R2"), ["Mach die Tests grün"])
            b.talk_pipeline(str(TMP / "nichts.wav"))
            self.assertIsNone(b.direct)
            self.assertEqual(b.say_q.get_nowait(), "Okay, wieder alle.")
            self.assertEqual(seen, [None, "R2", "R2"], "Router kennt den Direktmodus")
        finally:
            ev.transcribe, ev.router.understand = old

    def test_talk_routes_to_session_or_self(self):
        import queue
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        b.bridge.on_event({"event": "ready", "session": "R1", "project": "api"})
        old = (ev.transcribe, ev.router.understand, ev.router.ask_self)
        try:
            ev.transcribe = lambda model, wav, hint=None: "Deploy bitte die API"
            ev.router.understand = lambda text, sessions, **k: ("session", "R1", text)
            b.talk_pipeline(str(TMP / "nichts.wav"))
            self.assertEqual(b.bridge.take_inbox("R1"), ["Deploy bitte die API"])
            self.assertTrue(b.say_q.empty(), "kein Routing-Geplauder (Okay kommt schon beim Aufnahme-Ende)")
            b.talk_pipeline(str(TMP / "nichts.wav"), cut=True)   # Zeitlimit: wird angesagt
            cut_msg = b.say_q.get_nowait()
            self.assertIn("Zeitlimit", cut_msg)
            self.assertIn("„API“", cut_msg)                     # bis wohin mitgeschrieben
            b.bridge.take_inbox("R1")
            ev.router.understand = lambda text, sessions, **k: ("self", None, text)
            ev.router.ask_self = lambda text, *a, **k: "Es ist drei Uhr."
            with patch.object(ev.router, "brains", return_value=["claude"]):
                b.talk_pipeline(str(TMP / "nichts.wav"))
            self.assertEqual(b.say_q.get_nowait(), "Moment, ich schaue nach.")
            self.assertEqual(b.say_q.get_nowait(), "Es ist drei Uhr.")
        finally:
            ev.transcribe, ev.router.understand, ev.router.ask_self = old
            b.bridge.events.queue.clear()

    def test_without_any_brain_a_session_opens_instead_of_silence(self):
        """Weder claude, codex, agy noch gemini: der Satz geht als Auftrag an eine neue Session."""
        b, ev = self.b, self.ev
        opened = []
        with patch.object(ev, "transcribe", lambda model, wav, hint=None: "Wie spät ist es?"), \
                patch.object(ev.router, "understand", lambda text, sessions, **k: ("self", None, text)), \
                patch.object(ev.router, "brains", return_value=[]), \
                patch.object(ev.Walkie, "has_terminal", lambda self: False), \
                patch.object(b, "open_new_session", lambda text, **k: opened.append((text, k))):
            b.talk_pipeline(str(TMP / "nichts.wav"))
        self.assertEqual(opened, [("Wie spät ist es?", {"agent": ev.S.get("WALKIE_AGENT")})])

    def test_mic_lost_during_recording_recovers(self):
        """Kopfhörer weg mitten in der Aufnahme: Abbruch, Ansage, wieder bereit – kein Hänger."""
        import queue
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        old = (ev.beep, b.headset_audio.release)
        ev.beep = b.headset_audio.release = lambda *a, **k: None

        class DeadRec:
            def alive(self): return False
            def stop(self): pass
        try:
            b.rec_proc, b.rec_file = DeadRec(), str(TMP / "weg.wav")
            b.answer_req = "q1"
            b.set_state("listening")
            b.check_silence()
            self.assertEqual(b.state, "idle")
            self.assertIsNone(b.rec_proc)
            self.assertIsNone(b.answer_req)
            self.assertIn("Mikrofon ist weg", b.say_q.get_nowait())
        finally:
            ev.beep, b.headset_audio.release = old

    def test_watchdog_resets_stuck_state(self):
        b, ev = self.b, self.ev
        old = ev.beep
        ev.beep = lambda *a, **k: None
        try:
            b.set_state("thinking")
            b.watchdog()
            self.assertEqual(b.state, "thinking", "frisch -> nicht eingreifen")
            b.state_since -= b.STUCK["thinking"] + 1
            b.watchdog()
            self.assertEqual(b.state, "idle")
        finally:
            ev.beep = old

    def test_soak_200_cycles(self):
        """Dauertest: 200 Runden reden/antworten, mit Mikro-Ausfällen und Fragen dazwischen.
        Danach muss alles auf 'bereit' stehen – nichts hängt, nichts bleibt liegen."""
        import queue
        import time
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        b.whisper = object()
        b.announce_on = True
        old_quiet, ev.QUIET_PEAK = ev.QUIET_PEAK, 0.0   # Ersatz-Aufnahmen sind stumm
        self.addCleanup(setattr, ev, "QUIET_PEAK", old_quiet)
        dead = {"n": 0}

        class FlakyRec:
            def __init__(self):
                dead["n"] += 1
                self.dead = dead["n"] % 7 == 0          # jede 7. Aufnahme: Gerät weg
                self.error = ""
            def start(self, path, device=None):
                Path(path).write_bytes(b"\0" * 44)
                return True
            def alive(self): return not self.dead
            def stop(self): pass

        old = (ev.audio.Recorder, b.headset_audio.prepare, b.headset_audio.release, ev.beep, ev.transcribe,
               ev.router.understand)
        ev.audio.Recorder = FlakyRec
        b.headset_audio.prepare = b.headset_audio.release = ev.beep = lambda *a, **k: None
        ev.transcribe = lambda model, wav, hint=None: "Ja, mach weiter"
        ev.router.understand = lambda text, sessions, **k: ("session", "S", text)
        # Fenster nach vorne holen fragt sonst die echte Fensterliste ab (X11/xrdp: bis zu 4 s,
        # hält dabei die anderen Threads auf) – der Test brach dann je nach Last zufällig ab
        b.raise_session = lambda *a, **k: None
        b.bridge.on_event({"event": "ready", "session": "S", "project": "soak"})

        def pump(cond, limit=3.0):
            end = time.time() + limit
            while time.time() < end:
                self.app.processEvents()
                if cond():
                    return True
                time.sleep(0.005)
            return False
        try:
            for i in range(200):
                if i % 10 == 5:                          # Session fragt -> per Stimme antworten
                    b.bridge.on_event({"event": "stop", "session": "S", "project": "soak",
                                       "text": "Weiter?", "question": True})
                    self.assertTrue(pump(lambda: b.pending), f"Runde {i}: Frage nicht offen")
                    b.answer_done.wait(0.01)
                b.headset_toggle()                       # Druck: reden oder Frage beantworten
                pump(lambda: b.state == "listening" or b.state == "idle", 2)
                if b.state == "listening":
                    b.check_silence()                    # erkennt ggf. das tote Gerät
                if b.state == "listening":
                    b.stop_listening()                   # zweiter Druck
                self.assertTrue(pump(lambda: b.state == "idle", 3),
                                f"Runde {i}: hängt in {b.state} DIAG rec={b.rec_proc!r} "
                                f"owner={b.mic_owner!r} answer={b.answer_req!r} "
                                f"pending={list(b.pending)} timer={b.level_timer.isActive()}")
            self.assertEqual(b.state, "idle")
            self.assertIsNone(b.rec_proc)
            self.assertEqual(b.pending, {}, "Anfragen liegen geblieben")
            self.assertGreater(len(b.bridge.take_inbox("S")), 100, "Sätze kamen nicht an")
        finally:
            (ev.audio.Recorder, b.headset_audio.prepare, b.headset_audio.release, ev.beep, ev.transcribe,
             ev.router.understand) = old
            b.bridge.events.queue.clear()

    def test_stop_releases_exclusive_reader(self):
        import threading
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        stop, grabbed = threading.Event(), threading.Event()
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        dev = Mock(fd=read_fd)
        dev.name = "Test (AVRCP)"
        dev.grab.side_effect = grabbed.set
        fake = SimpleNamespace(list_devices=lambda: ["/fake"], InputDevice=lambda _: dev,
                               ecodes=SimpleNamespace())
        with patch.dict(sys.modules, {"evdev": fake}), patch.object(self.ev, "HEADSET_NAME", "auto"):
            worker = threading.Thread(target=self.reader, args=(self.b.bus, stop), daemon=True)
            worker.start()
            try:
                self.assertTrue(grabbed.wait(1))
            finally:
                stop.set()
                worker.join(1)
        self.assertFalse(worker.is_alive())
        dev.close.assert_called_once()

    def test_quiet_speech_acknowledged_and_transcribed(self):
        import time
        from unittest.mock import Mock, patch
        b, ev = self.b, self.ev
        b.rec_start = time.time()
        b.answer_voice = b.rec_start
        b.max_rms = 0.003
        b.rec_file = str(TMP / "leise.wav")
        Path(b.rec_file).write_bytes(ev.audio._wav_header(64) + bytes(64))
        b.rec_proc = Mock()
        b.rec_proc.data_bytes.return_value = 64
        b.piper, b.whisper, b.answer_req = object(), object(), ev.TALK
        b.in_thread = lambda f, *a: f(*a)
        b.speak = Mock()
        with patch.object(ev, "transcribe", return_value="Leiser Auftrag") as stt, \
                patch.object(ev.S, "talk_terminal", return_value=True), \
                patch.object(b, "deliver_terminal") as send:
            b.stop_listening()
        self.assertEqual(b.speak.call_args.args, ("Okay.",))
        stt.assert_called_once()
        self.assertEqual(send.call_args.args[0], "Leiser Auftrag")

    def test_native_start_failure_keeps_wav_and_skips_stop_key(self):
        import queue
        from concurrent.futures import Future
        from unittest.mock import Mock
        b = self.b
        wav = TMP / "native.wav"
        wav.write_bytes(b"local recording")
        started = Future()
        started.set_exception(OSError("kein Terminal"))
        b.term, b.say_q = Mock(), queue.Queue()
        b.cc_stop(str(wav), started, None)
        b.term.kitty.assert_not_called()
        saved = self.ev.RUN / wav.name
        self.assertEqual(saved.read_bytes(), b"local recording")
        drafts = [row["text"] for row in b.bridge.dictations.drafts()]
        self.assertIn(f"WAV: {saved}", drafts)
        messages = self.said()
        self.assertEqual(len(messages), 1, f"Ansagen nach cc_stop: {messages!r}, Drafts: {drafts!r}")
        self.assertIn("walkie drafts", messages[0])

    def test_silent_native_dictation_is_not_archived(self):
        import queue
        from concurrent.futures import Future
        from unittest.mock import Mock
        b = self.b
        wav = TMP / "silent.wav"
        wav.write_bytes(b"silence")
        started = Future()
        started.set_exception(OSError("kein Terminal"))
        b.term, b.say_q = Mock(), queue.Queue()
        before = len(b.bridge.dictations.drafts())
        b.cc_stop(str(wav), started, None, heard=False)
        self.assertFalse(wav.exists())
        self.assertFalse((self.ev.RUN / wav.name).exists())
        self.assertTrue(b.say_q.empty())
        self.assertEqual(len(b.bridge.dictations.drafts()), before)

    def test_external_codex_question_once_then_listen_after_playback(self):
        import time
        from unittest.mock import Mock, patch
        b = self.b
        b.term.codex_binding = lambda sid: 7 if sid == "main" else None
        b.whisper = object()
        b.in_thread = lambda fn, *a: fn(*a)
        b.bus.ask.disconnect()
        asked = []
        b.bus.ask.connect(asked.append)
        b._speak = Mock(side_effect=lambda *a, **kw: not asked)
        ev = dict(event="stop", own=True, agent="codex", text="Welche Farbe?", ts=time.time(),
                  turn_id="one", session="main")
        with patch.object(self.ev.AGENT, "name", "codex"), patch.object(self.ev, "LINUX", True):
            b.handle_event(ev)
            b.handle_event(ev)
            b.handle_event(dict(ev, session="title", text='{"title":"Farbe"}'))
        b._speak.assert_called_once()
        self.assertEqual(len(asked), 1)
        self.assertEqual(b.pending[asked[0]]["session"], "main")

    def test_codex_followup_bound_to_original_session(self):
        from unittest.mock import Mock
        b = self.b
        b.term = Mock()
        b.term.codex_binding.return_value = (7, "rollout")
        b.deliver_terminal("Blau", None, session="main")
        b.term.send_codex.assert_called_once_with("🎤 " + self.ev.spoken_prompt("Blau"), (7, "rollout"))
        b.term.ready.wait.assert_not_called()
        b.term.codex_binding.return_value = None
        b.deliver_terminal("Grün", None, session="gone")
        b.term.send_codex.assert_called_once()
        b.term.open.assert_not_called()

    def test_new_claude_session_ignores_unrelated_ready(self):
        from unittest.mock import Mock, patch
        b = self.b
        b.in_thread = Mock()
        with patch("paths.open_terminal", return_value=True) as launch:
            b.open_new_session("Testauftrag", folder=str(TMP))
        command = launch.call_args.args[0]
        self.assertEqual(command[-2], "--session-id")
        sid = command[-1]
        b.deliver_to_new_session("andere-session")
        self.assertIsNone(b.bridge.dictations.first("andere-session"))
        b.deliver_to_new_session(sid)
        self.assertEqual(b.bridge.dictations.first(sid)["text"], "Testauftrag")

    def test_codex_receipt_requires_new_matching_user_input(self):
        from unittest.mock import Mock, patch
        text = "🎤 Testfixture"
        rollout = TMP / "receipt.jsonl"

        def entry(role, content):
            return json.dumps({"type": "response_item", "payload": {
                "role": role, "content": [{"type": "input_text", "text": content}]}}) + "\n"

        rollout.write_text(entry("user", text), encoding="utf-8")
        term = self.ev.Terminal()
        def append(role, content):
            with rollout.open("a", encoding="utf-8") as stream:
                stream.write(entry(role, content))

        term.send = Mock(side_effect=lambda *a, **kw: append("assistant", text))
        with patch.object(self.ev.time, "monotonic", side_effect=[0, 0, 0, 31]):
            with self.assertRaises(TimeoutError):
                term.send_codex(text, (7, rollout))
        term.send = Mock(side_effect=lambda *a, **kw: append("user", text))
        term.send_codex(text, (7, rollout))
        term.send.assert_called_once_with(text, window=7)

    def test_codex_receipt_after_slow_first_submission(self):
        from datetime import datetime, timezone
        from unittest.mock import Mock, patch
        term = self.ev.Terminal()
        text = "🎤 Hello"
        rollout = TMP / "first-receipt.jsonl"
        def submit(*args, **kwargs):
            entry = {"type": "response_item", "timestamp": datetime.now(timezone.utc).isoformat(),
                     "payload": {"role": "user", "content": [{"type": "input_text", "text": text}]}}
            rollout.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        term.send = Mock(side_effect=submit)
        term.codex_binding = Mock(return_value=(7, rollout))
        with patch.object(self.ev.time, "monotonic", side_effect=[0, 0, 9, 10, 10]):
            term.send_codex(text, (7, None))
        term.send.assert_called_once_with(text, window=7)

    def test_codex_reply_stops_after_speech_but_waits_for_silent_user(self):
        import time
        from unittest.mock import Mock
        b = self.b
        now = time.time()
        b.rec_start = now - 3
        b.answer_req = "req"
        b.pending["req"] = {"via": "terminal"}
        b.rec_proc = Mock()
        b.rec_file = str(TMP / "silence-window.wav")
        Path(b.rec_file).touch()
        b.rec_pos = 0
        b.stop_listening = Mock()
        b.answer_voice = 0
        b.check_silence()
        b.stop_listening.assert_not_called()
        b.answer_voice = now - 1.5
        b.check_silence()
        b.stop_listening.assert_called_once()

    def test_question_waits_for_a_busy_mic_instead_of_staying_silent(self):
        """Frage kommt, während das Mikro noch belegt ist: warten und dann zuhören – vorher
        gab Walkie still auf, und nach manchen Fragen kam keine Aufforderung."""
        import time
        from unittest.mock import patch
        b = self.b
        b.pending["busy-q"] = {"session": "S", "who": "x", "kind": "reply", "via": "hook",
                               "tool": "", "questions": [], "answers": {}, "ts": time.time(),
                               "prompt": "x fragt: weiter?"}
        started = []
        b.answer_done.clear()
        with patch.object(b, "start_listening", lambda **k: started.append(k["answer"])):
            b.mic_owner = object()                       # dein letzter Satz läuft noch
            b.listen_answer("busy-q")
            self.assertEqual(started, [])
            self.assertFalse(b.answer_done.is_set())     # nicht aufgegeben
            b.mic_owner = None
            end = time.time() + 2
            while not started and time.time() < end:
                self.app.processEvents()
                time.sleep(0.02)
        self.assertEqual(started, ["busy-q"])
        b.pending.pop("busy-q", None)

    def test_session_question_asks_once_and_closes_quietly(self):
        """Frage einer Session, von selbst zugehört, keine klare Antwort: kein zweites Zuhören,
        kein „nicht verstanden“; die Session wartet nicht. Selbst gedrückt: einmal nachfragen."""
        import queue
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        spoken, asked, written = [], [], []
        b.speak = spoken.append
        b.bus.ask.disconnect()
        b.bus.ask.connect(asked.append)
        b.whisper = object()
        old = (ev.transcribe, b.write_answer, ev.router.ask_model)
        ev.transcribe = lambda model, wav, hint=None: "äh"
        ev.router.ask_model = lambda *a, **k: '{"decision": "unclear"}'
        b.write_answer = lambda req, ans: written.append((req, ans))
        try:
            for manual in (False, True):
                req = f"q-{manual}"
                b.pending[req] = {"session": "S", "who": "shop", "kind": "reply", "via": "hook",
                                  "tool": "", "detail": "", "reason": "", "questions": [],
                                  "answers": {}, "ts": __import__("time").time(),
                                  "prompt": "shop fragt: weiter?", **({"manual": True} if manual else {})}
                wav = TMP / "q.wav"
                wav.write_bytes(b"")
                b.answer_pipeline(str(wav), req)
                if not manual:
                    self.assertEqual((spoken, asked), ([], []))      # still
                    self.assertNotIn(req, b.pending)
                    self.assertEqual(written[-1], (req, {"behavior": "pass"}))
                else:
                    self.assertEqual(len(asked), 1)                  # einmal nachfragen
                    self.assertTrue(spoken)
                b.pending.pop(req, None)
        finally:
            ev.transcribe, b.write_answer, ev.router.ask_model = old
            b.bus.ask.disconnect()
            b.bus.ask.connect(b.listen_answer)

    def test_limit_offers_second_agent_and_opens_it_on_yes(self):
        """Claude-Session im Limit: einmal fragen; „ja“ öffnet den Zweitagenten im Ordner der
        Session mit dem bisherigen Stand, „nein“ öffnet nichts."""
        import queue
        from unittest.mock import patch
        import transcripts
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        b.handover_offered = {}
        b.bridge.on_event({"event": "ready", "session": "L1", "project": "shop", "cwd": "/w/shop"})
        ctx = {"limited": True, "topic": "Report bauen", "last_user": "weiter",
               "last_answer": "Halb fertig"}
        settings = dict(WALKIE_AGENT_2="antigravity")
        real_get = ev.S.get
        with patch.object(transcripts, "context", return_value=ctx), \
                patch.object(ev.time, "sleep"), \
                patch("shutil.which", return_value="/bin/agy"), \
                patch.object(ev.S, "get", side_effect=lambda k, *a: settings.get(k, real_get(k, *a))):
            b.offer_handover("L1", "shop")
            b.offer_handover("L1", "shop")                     # nicht doppelt fragen
        reqs = [r for r, p in b.pending.items() if p.get("kind") == "handover"]
        self.assertEqual(len(reqs), 1)
        p = b.pending[reqs[0]]
        self.assertEqual((p["agent"], p["folder"]), ("antigravity", "/w/shop"))
        self.assertIn("Halb fertig", p["text"])
        with patch.object(b, "open_new_session") as opened, patch.object(b, "speak"):
            with patch.object(type(b), "interpret", staticmethod(
                    lambda p, text, judge=None: ({"behavior": "allow"}, "Okay"))), \
                    patch.object(ev, "transcribe", return_value="ja"):
                b.answer_pipeline(str(TMP / "ja.wav"), reqs[0])
        opened.assert_called_once()
        self.assertEqual(opened.call_args.kwargs["agent"], "antigravity")
        self.assertEqual(opened.call_args.kwargs["folder"], "/w/shop")
        self.assertNotIn(reqs[0], b.pending)

    def test_missing_chosen_mic_falls_back_to_default(self):
        """Gewähltes Mikro weg (Kopfhörer getrennt): Standardmikro statt Fehlermeldung, Hinweis
        nur einmal je Gerät."""
        from unittest.mock import patch
        b, ev = self.b, self.ev
        tried = []

        class Rec:
            error = ""
            def start(self, path, device=None):
                tried.append(device)
                if device:
                    self.error = f"Mikrofon nicht gefunden: {device}"
                    return False
                return True
            def alive(self): return True
            def stop(self): pass
        notes = []
        with patch.object(ev.audio, "Recorder", Rec), patch.object(ev, "notify", notes.append):
            b.mic_device = "Headset (Test)"
            b.whisper = object()
            b.start_listening(answer=ev.TALK, prepared=True)
            self.assertEqual(tried, ["Headset (Test)", None])
            self.assertEqual(b.state, "listening")
            b.stop_listening()
            b.rec_proc = None
            b.set_state("idle")
            b.start_listening(answer=ev.TALK, prepared=True)
        self.assertEqual(len(notes), 1)
        b.rec_proc = None
        b.set_state("idle")

    def test_read_aloud_answer_is_router_context_not_a_rule(self):
        """Was vorgelesen wurde, bekommt der Router als Kontext; wen der Nutzer zuletzt
        angesprochen hat, bleibt unverändert (entscheiden soll das Modell)."""
        import time
        from unittest.mock import patch
        b = self.b
        b.voice_target = ("andere", time.time() - 30)
        with patch.object(b, "summarize", return_value="Fix gebaut, alle Tests grün."), \
                patch.object(type(b), "voice_on", True, create=True):
            b.speak_answer("S", "walkie", "Ich habe den Fix gebaut.")
        self.assertEqual(b.voice_target[0], "andere")
        self.assertEqual(b.read_aloud["S"][1], "Fix gebaut, alle Tests grün.")

    def test_reply_to_session_question_is_not_cut_at_answer_max(self):
        """Frei formulierte Antwort auf eine Frage: läuft, solange gesprochen wird. Freigaben
        bleiben bei WALKIE_ANSWER_MAX (20 s brachen lange Antworten mitten im Satz ab)."""
        import time
        from unittest.mock import Mock
        b = self.b
        now = time.time()
        b.rec_proc = Mock()
        b.rec_file = str(TMP / "long-reply.wav")
        Path(b.rec_file).touch()
        for kind, cut in (("reply", False), (None, True)):
            b.pending["q"] = {"session": "S", "who": "x", "tool": "Bash",
                              **({"kind": kind} if kind else {})}
            b.answer_req = "q"
            b.rec_start, b.rec_pos, b.noise = now - 25, 0, 0.001
            b.answer_voice = now - 0.5                # spricht noch
            b.stop_listening = Mock()
            b.check_silence()
            self.assertEqual(b.stop_listening.called, cut, kind)
        self.assertTrue(b.free_speech(self.ev.TALK))
        self.assertFalse(b.free_speech(None))

    def test_silent_codex_reply_closes_without_another_prompt(self):
        import time
        from unittest.mock import Mock
        b = self.b
        b.rec_start = time.time()
        b.rec_proc = Mock()
        b.rec_file = str(TMP / "silent-codex.wav")
        Path(b.rec_file).touch()
        b.answer_req = "codex-q"
        b.pending[b.answer_req] = {"via": "terminal"}
        b.in_thread = Mock()
        b.stop_listening()
        self.assertFalse(b.pending)
        self.assertEqual(b.state, "idle")
        self.assertFalse(Path(b.rec_file).exists())
        self.assertFalse(any(c.args[0] == b.answer_pipeline for c in b.in_thread.call_args_list))

    def test_terminal_failure_retains_text_and_speaks(self):
        import queue
        from unittest.mock import Mock
        b = self.b
        b.term = Mock()
        b.term.send.side_effect = OSError("terminal closed")
        b.say_q = queue.Queue()
        b.deliver_terminal("Text behalten", (0, 0))
        self.assertIn("walkie drafts", b.say_q.get_nowait())
        self.assertIn("Text behalten", [r["text"] for r in b.bridge.dictations.drafts()])
        self.assertFalse(b.expect_voice)

    def test_headset_mic_picked_by_name(self):
        """Ohne fest gewähltes Mikro nimmt der Walkie das des verbundenen Kopfhörers."""
        import importlib
        real = importlib.import_module("walkie")
        src = Path(real.__file__).read_text(encoding="utf-8")
        ns = {}
        exec(src[src.index("def headset_mic():"):src.index("def uses_headset_mic():")],
             {"audio": type("A", (), {"sources": staticmethod(
                 lambda: [("Built-in Audio Analog Stereo", ""), ("WH-1000XM5", "")])}),
              "keymap": type("K", (), {"connected_headsets": staticmethod(lambda: ["WH-1000XM5"]),
                                       "SPEAKER_WORDS": ()}),
              "LINUX": True}, ns)
        self.assertEqual(ns["headset_mic"](), "WH-1000XM5")

    def test_new_session_gets_the_task(self):
        """„Öffne eine neue Session …“: Terminal auf, die neue Session bekommt den Auftrag."""
        import queue

        import paths
        import router
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        old_claude = router.ask_model
        router.ask_model = lambda *a, **k: ('{"target": "new", "explicit": true, '
                                          '"message": "Recherchiere die Tech-Aktien"}')
        self.addCleanup(setattr, router, "ask_model", old_claude)
        b.bridge.on_event({"event": "ready", "session": "ALT", "project": "shop",
                           "cwd": "/home/x/shop"})
        opened = []
        old = (paths.open_terminal, ev.transcribe)
        paths.open_terminal = lambda argv, **k: opened.append((argv, k.get("cwd"))) or True
        ev.transcribe = lambda model, wav, hint=None: "Recherchiere in einer neuen Session die Tech-Aktien"
        try:
            b.talk_pipeline(str(TMP / "x.wav"))
            self.assertEqual(len(opened), 1)
            self.assertEqual(opened[0][1], self.ev.new_session_dir(),
                             "neues Thema: eigener Ordner, nicht der einer anderen Session")
            self.assertNotEqual(opened[0][1], str(Path.home()), "Home verlangt jedes Mal Freigabe")
            self.assertIn("neue Session", b.say_q.get_nowait())
            b.handle_event({"event": "ready", "session": "ALT", "project": "shop"})
            self.assertEqual(b.bridge.take_inbox("ALT"), [], "nicht an die alte Session")
            new_sid = opened[0][0][-1]
            b.handle_event({"event": "ready", "session": new_sid, "project": "Home"})
            self.assertEqual(b.bridge.take_inbox(new_sid), ["Recherchiere die Tech-Aktien"])
        finally:
            paths.open_terminal, ev.transcribe = old
            b.bridge.events.queue.clear()

    def test_new_session_uses_the_configured_agent(self):
        import queue

        import paths
        b = self.b
        b.say_q = queue.Queue()
        opened = []
        old = paths.open_terminal
        paths.open_terminal = lambda argv, **k: opened.append(argv) or True
        try:
            b.open_new_session("Such ein Rezept", agent="codex")
            self.assertEqual(opened[-1][-1], self.ev.spoken_prompt("Such ein Rezept"))
            self.assertIn("Codex-Session", b.say_q.get_nowait())
            b.open_new_session("Such ein Rezept", agent="antigravity")
            self.assertEqual(opened[-1][-2:], ["--prompt-interactive",
                                               self.ev.spoken_prompt("Such ein Rezept")])
            self.assertIn("Antigravity", b.say_q.get_nowait())
            b.open_new_session("Such ein Rezept", agent="custom")
            self.assertEqual(len(opened), 2, "eigener Befehl kann keine Session mit Auftrag starten")
            self.assertIn("walkie drafts", b.say_q.get_nowait())
            b.open_new_session("Such ein Rezept", agent="claude")
            self.assertIn("--session-id", opened[-1])
        finally:
            paths.open_terminal = old

    def test_route_question_is_understandable_repeatable_and_ends_cleanly(self):
        import queue
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        b.bridge.on_event({"event": "ready", "session": "A", "project": "claude-walkie"})
        b.bridge.on_event({"event": "ready", "session": "B", "project": "claude-walkie"})
        b.ask_which_session("Muss ich neu laden?", {"options": ["A", "B"], "labels": {
            "A": "das Walkie-Review", "B": ""}}, b.bridge.active_sessions())
        kind, req = b.say_q.get_nowait()
        p = b.pending[req]
        self.assertTrue(p["prompt"].startswith("Meinst du das Walkie-Review oder claude-walkie"))
        spoken, asked = [], []
        b.speak = spoken.append
        b.bus.ask.disconnect()
        b.bus.ask.connect(asked.append)
        b.whisper = object()
        answers = iter(['{"decision": "repeat"}', '{"decision": "unclear"}',
                        '{"decision": "unclear"}'])
        ev.router.ask_model = lambda *a, **k: next(answers)
        old = ev.transcribe
        ev.transcribe = lambda model, wav, hint=None: "Welche Optionen?"
        try:
            for _ in range(3):
                wav = TMP / "a.wav"
                wav.write_bytes(b"")
                b.answer_pipeline(str(wav), req)
        finally:
            ev.transcribe = old
        self.assertEqual(spoken[0], p["prompt"], "Wiederholen: Frage samt Optionen")
        self.assertIn(p["prompt"], spoken[1], "unklar: Optionen nochmal nennen")
        self.assertIn("walkie drafts", spoken[2])
        self.assertNotIn(req, b.pending, "keine hängende Frage")
        self.assertIn("Muss ich neu laden?", [r["text"] for r in b.bridge.dictations.drafts()])
        self.assertEqual(len(asked), 2)

    def test_five_sessions_ask_back_which_one(self):
        """Fünf Sessions, der Router ist unsicher: „Meinst du …?“ – die Antwort wählt."""
        import queue
        import time
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        topics = ["Energieeinstellungen prüfen", "Tech-Aktien recherchieren", "Tests reparieren",
                  "README übersetzen", "Docker aufräumen"]
        for i, t in enumerate(topics):
            b.bridge.on_event({"event": "prompt", "session": f"S{i}", "project": "Home",
                               "prompt": t})
        old = (ev.transcribe, ev.router.understand)
        ev.router.understand = lambda text, sessions, **k: ("ask", ["S0", "S1"], text)
        ev.transcribe = lambda model, wav, hint=None: "Lies mir die Werte vor"
        try:
            b.talk_pipeline(str(TMP / "x.wav"))
            item = b.say_q.get_nowait()
            self.assertEqual(item[0], "ask")
            p = b.pending[item[1]]
            self.assertEqual(b.prompt_text(p),
                             "Meinst du Home, Energieeinstellungen prüfen oder Home, Tech-Aktien recherchieren?")
            b.whisper = object()
            ev.transcribe = lambda model, wav, hint=None: "Die Energie"
            ev.router.ask_model = lambda *a, **k: (
                '{"decision": "answer", "values": ["Home, Energieeinstellungen prüfen"]}')
            wav = TMP / "a.wav"
            wav.write_bytes(b"")
            b.answer_pipeline(str(wav), item[1])
            self.assertEqual(b.bridge.take_inbox("S0"), ["Lies mir die Werte vor"])
            self.assertEqual(b.bridge.take_inbox("S1"), [])
            self.assertEqual(b.voice_target[0], "S0", "Nachfragen gehen jetzt dorthin")
        finally:
            ev.transcribe, ev.router.understand = old
            b.bridge.events.queue.clear()

    def test_show_me_raises_the_session_window(self):
        """„Zeig mir die Energie-Session“: Fenster holen, nichts senden."""
        import queue

        import windows
        b, ev = self.b, self.ev
        b.say_q = queue.Queue()
        b.bridge.on_event({"event": "ready", "session": "E", "project": "energie", "pid": 4242})
        raised = []
        old = (windows.raise_pid, ev.transcribe)
        windows.raise_pid = lambda pid, log=None: raised.append(pid) or True
        ev.transcribe = lambda model, wav, hint=None: "Zeig mir die Energie"
        ev.router.ask_model = lambda *a, **k: '{"target": "show", "session": "E"}'
        try:
            b.talk_pipeline(str(TMP / "x.wav"))
            self.assertEqual(raised, [4242])
            self.assertEqual(b.bridge.take_inbox("E"), [], "nichts gesendet")
            self.assertIn("Hier ist energie", b.say_q.get_nowait())
            b.voice_target = ("E", __import__("time").time())
            b.run_action("show")                       # Kopfhörertaste „Zeigen“
            import time
            for _ in range(100):
                if len(raised) == 2:
                    break
                time.sleep(0.01)
            self.assertEqual(raised, [4242, 4242])
        finally:
            windows.raise_pid, ev.transcribe = old
            b.bridge.events.queue.clear()

    def test_self_answer_goes_to_own_terminal(self):
        """Mit kitty: der Walkie antwortet selbst in seiner Session über der Figur (sichtbar)."""
        import threading
        b, ev = self.b, self.ev
        sent = []

        class FakeTerm:
            visible = False
            ready = threading.Event()
            def running(self): return True
            def send(self, text): sent.append(text)
        FakeTerm.ready.set()
        old = (ev.Walkie.has_terminal, b.term, ev.transcribe, ev.router.understand)
        ev.Walkie.has_terminal = lambda self: True
        b.term = FakeTerm()
        ev.transcribe = lambda model, wav, hint=None: "Wie spät ist es?"
        ev.router.understand = lambda text, sessions, **k: ("self", None, text)
        try:
            b.talk_pipeline(str(TMP / "x.wav"))
            self.assertEqual(sent, [f"{ev.VOICE_MARK} " + ev.spoken_prompt("Wie spät ist es?")])
            self.assertTrue(b.expect_voice, "Antwort wird vorgelesen")
        finally:
            ev.Walkie.has_terminal, b.term, ev.transcribe, ev.router.understand = old
            b.expect_voice = False

    def test_no_reply_wait_without_question(self):
        import hook
        self.assertTrue(hook.ends_with_question("Fertig.\n\nSoll ich committen?"))
        self.assertTrue(hook.ends_with_question("Welche Option – A oder B? Sag Bescheid."))
        self.assertFalse(hook.ends_with_question("Ist das gut? Ja.\n\nAlles erledigt."))
        self.assertFalse(hook.ends_with_question("```py\nx = a ? b : c\n```"))

    def test_hook_without_walkie_returns_immediately(self):
        self.b.bridge.stop()                 # kein laufender Begleiter
        r = subprocess.run([sys.executable, str(ROOT / "hook.py"), "--plugin", "ask"],
                           input=json.dumps({"session_id": "Z", "tool_name": "Bash"}),
                           encoding="utf-8", capture_output=True, timeout=5,
                           env={k: v for k, v in os.environ.items() if k != "WALKIE_SESSION"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")

    def test_bundled_figures_load(self):
        """Mitgelieferte CC0-Figuren: laden, haben Idle/Walk, links = gespiegelt rechts."""
        from sprite import LEFT, RIGHT, SpriteSet
        figs = sorted(d for d in (ROOT / "figures").iterdir() if (d / "AnimData.xml").exists())
        self.assertGreaterEqual(len(figs), 3)
        self.assertIn(self.ev.S.DEFAULT_FIGURE, figs)
        for d in figs:
            s = SpriteSet(d, scale=1)
            self.assertTrue(s.has("Idle") and s.has("Walk"), d)
            # In Originalauflösung vergleichen: weiches Herunterskalieren um krumme
            # Faktoren (Shimejis) rundet links und rechts minimal unterschiedlich.
            s = SpriteSet(d, scale=1 / s.scale)
            r = s.anims["Walk"].frame(RIGHT, 0).toImage()
            left = s.anims["Walk"].frame(LEFT, 0).toImage()
            self.assertEqual(r.mirrored(True, False), left, d)

    def test_turns_around_before_walking_back(self):
        """Mit Turn-Animation dreht sich die Figur erst sichtbar um und läuft dann los."""
        from sprite import LEFT, RIGHT, Animator, SpriteSet
        b = self.b
        b.anim = Animator(SpriteSet(self.ev.S.DEFAULT_FIGURE, scale=1))
        b.wander, b.dir = True, 1
        x0 = b.x()
        b.target_x = x0 - 100
        b.step()
        self.assertEqual((b.anim.name, b.anim.row, b.x()), ("Turn", RIGHT, x0))
        for _ in range(300):
            b.step()
            if b.x() != x0:
                break
        self.assertEqual((b.dir, b.anim.name, b.anim.row), (-1, "Walk", LEFT))

    def test_drag_faces_drag_direction(self):
        """Beim Tragen schaut die Figur in die Richtung, in die sie gezogen wird."""
        from types import SimpleNamespace
        from PyQt6.QtCore import QPoint, QPointF
        b = self.b
        b.drag_off, b.dir = QPoint(0, 0), -1

        def to(x):
            return SimpleNamespace(globalPosition=lambda: QPointF(x, b.y()))
        b.mouseMoveEvent(to(b.x() + 20))
        self.assertEqual((b.dir, b.turn_from), (1, 0))      # sofort, ohne Dreh-Animation
        b.mouseMoveEvent(to(b.x() + 1))                     # Zittern ändert nichts
        self.assertEqual(b.dir, 1)
        b.mouseMoveEvent(to(b.x() - 20))
        self.assertEqual(b.dir, -1)

    def test_agent_model_reaches_command(self):
        import agents
        os.environ["WALKIE_AGENT_MODEL"] = "opus"
        try:
            cmd = agents.ClaudeCode("", "claude").command()
        finally:
            del os.environ["WALKIE_AGENT_MODEL"]
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")

    def test_first_sentences(self):
        t = "Erster Satz. " + "Zweiter Satz ist länger. " * 20
        out = self.ev.Walkie.first_sentences(t, limit=60)
        self.assertTrue(out.startswith("Erster Satz. Zweiter"))
        self.assertLessEqual(len(out), 140)

    def test_click_acknowledges_attention(self):
        self.hook("--plugin", "attention", session_id="B", tool_name="Bash")
        self.assertEqual(self.view(), "attention")
        self.b.term.visible = True          # Terminal "offen" -> Klick blendet nichts aus
        self.b.toggle_terminal()
        self.assertEqual(self.view(), "thinking")

    def test_own_session_reads_answer(self):
        spoken = []
        self.b.speak_then_idle = spoken.append
        self.b.expect_voice = True
        self.hook("stop", own=True, session_id="X", last_assistant_message="Hallo!")
        self.assertEqual(self.view(), "speaking")
        self.assertEqual(spoken, ["Hallo!"])

    def test_listening_beats_agent_state(self):
        self.hook("--plugin", "prompt", session_id="A")
        self.b.state = "listening"
        self.assertEqual(self.view(), "listening")
        self.assertEqual(self.b.anim.name, "DeepBreath")

    def test_walkie_faces_forward_to_listen(self):
        from sprite import DOWN, Animator, SpriteSet
        b = self.b
        b.anim = Animator(SpriteSet(self.ev.S.DEFAULT_FIGURE, scale=4))
        b.fx_kind = "spin"
        b.set_state("listening")
        b.step()
        self.assertEqual((b.anim.name, b.anim.row, b.fx_kind), ("Listen", DOWN, None))
        for _ in range(8):
            b.step()
        self.assertGreater(b.anim.i, 0)
        b.set_state("speaking")
        b.step()
        self.assertEqual(b.anim.name, "Nod")

    def test_session_end_and_ttl(self):
        self.hook("--plugin", "prompt", session_id="A")
        self.hook("--plugin", "prompt", session_id="B")
        self.view()
        self.hook("--plugin", "end", session_id="A")
        self.view()
        self.assertEqual(sorted(self.b.sessions), ["B"])
        self.b.sessions["B"]["ts"] -= self.ev.SESSION_TTL + 1
        self.assertEqual(self.view(), "idle")
        self.assertEqual(self.b.sessions, {})

    def test_hallucination_filter(self):
        h = self.ev.HALLUCINATIONS
        for t in ("Vielen Dank.", "Untertitel im Auftrag des ZDF", "Thank you.", "..."):
            self.assertTrue(h.match(t), t)
        for t in ("Danke, mach weiter mit Tests", "Mach das Fenster zu"):
            self.assertFalse(h.match(t), t)

    def test_missing_models_do_not_retry_each_tick_or_announcement(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        b = self.b
        name = self.ev.S.get("WALKIE_VOICE")
        b.need_whisper = lambda: True
        b.requested_voice = name
        b.in_thread = Mock()
        whisper = Mock(side_effect=OSError("offline"))
        fetch = Mock(side_effect=OSError("offline"))
        modules = {"faster_whisper": SimpleNamespace(WhisperModel=whisper),
                   "piper": SimpleNamespace(PiperVoice=Mock())}
        with (patch.dict(sys.modules, modules), patch.object(self.ev, "VOICE_DIR", TMP),
              patch("fetch_assets.fetch_voice", fetch), patch.object(self.ev.time, "monotonic") as now):
            now.return_value = 1
            self.load_whisper(b)
            self.set_voice(b, name)
            now.return_value = 2
            b.apply_settings()
            self.set_voice(b, name)
            b.in_thread.assert_not_called()
            whisper.assert_called_once()
            fetch.assert_called_once()
            now.return_value += self.ev.MODEL_RETRY_SECONDS
            b.apply_settings()
            b.in_thread.assert_called_once_with(b.load_whisper)
            self.set_voice(b, name)
            self.assertEqual(fetch.call_count, 2)

    def test_headset_detection(self):
        ev = self.ev
        old = ev.HEADSET_NAME
        try:
            ev.HEADSET_NAME = "auto"
            self.assertTrue(ev.is_headset("Sony WH-1000XM5 (AVRCP)"))
            self.assertFalse(ev.is_headset("Designer Keyboard"))
            ev.HEADSET_NAME = "off"
            self.assertFalse(ev.is_headset("Sony WH-1000XM5 (AVRCP)"))
            ev.HEADSET_NAME = "Mein Headset"
            self.assertTrue(ev.is_headset("Mein Headset"))
            self.assertTrue(ev.is_headset("Mein Headset (AVRCP)"), "Anzeigename ohne Zusatz passt")
            self.assertFalse(ev.is_headset("Anderes Headset (AVRCP)"))
        finally:
            ev.HEADSET_NAME = old


if __name__ == "__main__":
    unittest.main()
