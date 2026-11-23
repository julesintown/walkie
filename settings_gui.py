#!/usr/bin/env python3
"""Einstellungen des Walkie – Fenster im Stil der Claude-App.

Rechtsklick auf die Figur → „Einstellungen …“ oder eigenständig: ./start.sh --settings
Alles wird sofort in ~/.config/walkie/config.env gespeichert (settings.py);
der laufende Begleiter übernimmt Änderungen live.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QDoubleSpinBox,
                             QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QProgressBar,
                             QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
                             QVBoxLayout, QWidget)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audio  # noqa: E402
import crashguard  # noqa: E402
import keymap  # noqa: E402
import settings as S  # noqa: E402
from i18n import lang, t  # noqa: E402
from hook import LEARN_FLAG, LEARN_LOG, LOCK, RUN, walkie_running  # noqa: E402

WELCOMED = RUN / "welcomed"          # Ersteinrichtung gesehen -> nicht mehr automatisch öffnen


# ------------------------------------------------------------------ Theme (Claude-Look)
LIGHT = dict(bg="#FAF9F5", side="#F0EEE6", card="#FFFFFF", border="#E5E3DA", text="#141413",
             muted="#73726C", accent="#D97757", accent_hi="#C6613F", hover="#E8E6DD",
             select="#E3DFD3", field="#FFFFFF", track="#D6D3C8")
DARK = dict(bg="#262624", side="#1F1E1D", card="#30302E", border="#3E3D39", text="#F5F4EE",
            muted="#A6A39A", accent="#D97757", accent_hi="#E08A6D", hover="#393835",
            select="#45433E", field="#262624", track="#55534D")


def is_dark():
    try:
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return QApplication.palette().window().color().lightness() < 128


def stylesheet(c):
    return f"""
    QWidget {{ color: {c['text']}; font-size: 13px; }}
    #root {{ background: {c['bg']}; }}
    #side {{ background: {c['side']}; border-right: 1px solid {c['border']}; }}
    #brand {{ font-size: 15px; font-weight: 600; padding: 4px 8px 14px 8px; }}
    #nav {{ background: transparent; border: none; outline: none; }}
    #nav::item {{ padding: 8px 10px; border-radius: 8px; margin: 1px 0; }}
    #nav::item:hover {{ background: {c['hover']}; }}
    #nav::item:selected {{ background: {c['select']}; color: {c['text']}; }}
    #page {{ background: {c['bg']}; }}
    QScrollArea {{ border: none; background: {c['bg']}; }}
    #pageTitle {{ font-family: "Georgia", "Tiempos Headline", serif; font-size: 26px;
                  padding: 6px 0 2px 0; }}
    #pageSub {{ color: {c['muted']}; padding-bottom: 10px; }}
    #card {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 12px; }}
    #cardTitle {{ font-weight: 600; font-size: 14px; }}
    #rowTitle {{ font-weight: 500; }}
    #help, #muted {{ color: {c['muted']}; font-size: 12px; }}
    #sep {{ background: {c['border']}; max-height: 1px; min-height: 1px; }}
    #banner {{ background: {c['accent']}; border-radius: 10px; }}
    #banner QLabel {{ color: white; font-weight: 500; }}
    #banner QPushButton {{ background: white; color: {c['accent_hi']}; border: none;
                          border-radius: 8px; padding: 6px 12px; font-weight: 600; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {c['field']}; border: 1px solid {c['border']}; border-radius: 8px;
        padding: 5px 8px; min-height: 20px; selection-background-color: {c['accent']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {c['card']}; border: 1px solid {c['border']};
        selection-background-color: {c['select']}; selection-color: {c['text']}; outline: none; }}
    QPushButton {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 8px;
                   padding: 6px 14px; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:disabled {{ color: {c['muted']}; }}
    QPushButton#primary {{ background: {c['accent']}; color: white; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {c['accent_hi']}; }}
    QPushButton#primary:disabled {{ background: {c['track']}; }}
    QListWidget#list {{ background: {c['field']}; border: 1px solid {c['border']};
                        border-radius: 8px; outline: none; }}
    QListWidget#list::item {{ padding: 5px 8px; border-radius: 6px; }}
    QListWidget#list::item:selected {{ background: {c['select']}; color: {c['text']}; }}
    QProgressBar {{ background: {c['track']}; border: none; border-radius: 4px; max-height: 8px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['track']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: white; border: 1px solid {c['border']};
                                  width: 16px; margin: -7px 0; border-radius: 8px; }}
    #mono {{ font-family: monospace; font-size: 12px; }}
    #hl {{ border: 2px solid {c['accent']}; }}
    """


class Toggle(QAbstractButton):
    """Schalter im Stil der Claude-App."""

    def __init__(self, checked=False, colors=None):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.c = colors

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        on = self.isChecked()
        col = QColor(self.c["accent"] if on else self.c["track"])
        if not self.isEnabled():
            col.setAlpha(110)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(29 if on else 11, 11), 8, 8)


class Bg(QObject):
    """Arbeit im Hintergrund, Ergebnis zurück in den GUI-Thread."""
    done = pyqtSignal(object)

    def __init__(self, fn, cb, *args):
        super().__init__()

        def deliver(res):
            try:
                cb(res)
            except RuntimeError:              # Seite inzwischen neu aufgebaut (Sprachwechsel)
                pass
        self.done.connect(deliver)
        _keep.add(self)

        def run():
            try:
                res = fn(*args)
            except Exception as ex:  # noqa: BLE001
                res = ex
            try:
                self.done.emit(res)
            except RuntimeError:              # Fenster inzwischen geschlossen – Ergebnis egal
                pass
            _keep.discard(self)
        threading.Thread(target=run, daemon=True).start()


_keep = set()


def label(text, name=None, wrap=True):
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def hbox(*widgets, stretch_at=None, spacing=8):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for i, x in enumerate(widgets):
        if x is None:
            lay.addStretch(1)
        else:
            lay.addWidget(x)
    return w


# ------------------------------------------------------------------ Fenster
class SettingsWindow(QWidget):
    def __init__(self, walkie=None):
        super().__init__()
        self.walkie = walkie
        self.c = DARK if is_dark() else LIGHT
        self.resize(940, 680)
        self.setObjectName("root")
        self.setStyleSheet(stylesheet(self.c))
        self.needs_restart = set()
        self.content = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.build_ui()
        self.lang_timer = QTimer(self, timeout=self.refresh_language)
        self.lang_timer.start(500)

    def refresh_language(self):
        if self.ui_language != lang():
            self.build_ui(self.current_page())

    PAGES = ["welcome", "general", "figure", "headset", "ask", "voice", "info"]

    def build_ui(self, page="welcome"):
        """Inhalt (neu) aufbauen – auch nach einem Wechsel der Oberflächensprache.
        Das Fenster selbst bleibt dasselbe (walkie.settings_win zeigt weiter darauf)."""
        self.ui_language = lang()
        if getattr(self, "learn_timer", None) is not None and self.learn_timer.isActive():
            self.learn_timer.stop()
            LEARN_FLAG.unlink(missing_ok=True)
        if getattr(self, "rec_timer", None) is not None and self.rec_timer.isActive():
            self.rec_timer.stop()                 # laufende Probeaufnahme sauber beenden
            self.rec.stop()
            if self.rec_headset:
                self.walkie.in_thread(self.walkie.headset_audio.release, self)
            try:
                os.unlink(self.rec_wav)
            except OSError:
                pass
        if self.content is not None:
            self.layout().removeWidget(self.content)
            self.content.hide()
            self.content.deleteLater()
        self.setWindowTitle(t("{name} – Einstellungen", name=S.get("WALKIE_NAME")))
        self.rows = {}            # key -> Widget (für Abhängigkeiten)
        self.content = QWidget()
        self.layout().addWidget(self.content)

        lay = QHBoxLayout(self.content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QWidget(objectName="side")
        side.setFixedWidth(210)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 18, 12, 12)
        sl.addWidget(label(f"{S.get('WALKIE_NAME')}", "brand"))
        self.nav = QListWidget(objectName="nav")
        sl.addWidget(self.nav, 1)
        sl.addWidget(label(t("Gespeichert in") + "\n" + str(S.CONFIG).replace(str(Path.home()), "~")
                           if len(str(S.CONFIG)) < 60 else "", "help"))
        lay.addWidget(side)

        right = QWidget(objectName="page")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.banner = self.make_banner()
        self.banner.setVisible(bool(self.needs_restart))
        rl.addWidget(self.banner)
        self.stack = QStackedWidget()
        rl.addWidget(self.stack, 1)
        lay.addWidget(right, 1)

        titles = {"welcome": t("Erste Schritte"), "general": t("Allgemein"), "figure": t("Figur"),
                  "headset": t("Kopfhörer"), "ask": t("Fragen & Freigaben"),
                  "voice": t("Sprache & Modelle"), "info": t("Info")}
        for pid in self.PAGES:
            QListWidgetItem(titles[pid], self.nav)
            self.stack.addWidget(self.scroll(getattr(self, "page_" + pid)()))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.currentRowChanged.connect(self.on_page)
        self.nav.setCurrentRow(self.PAGES.index(page) if page in self.PAGES else 0)
        self.update_deps()

    def current_page(self):
        i = self.nav.currentRow()
        return self.PAGES[i] if 0 <= i < len(self.PAGES) else "welcome"

    # ---------------- Bausteine ----------------
    def scroll(self, inner):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(inner)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return sa

    def page(self, title, sub):
        w = QWidget(objectName="page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(36, 26, 36, 30)
        lay.setSpacing(14)
        lay.addWidget(label(title, "pageTitle"))
        lay.addWidget(label(sub, "pageSub"))
        w.lay = lay
        return w

    def card(self, page, title=None, help_text=None):
        f = QFrame(objectName="card")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)
        if title:
            lay.addWidget(label(title, "cardTitle"))
        if help_text:
            lay.addWidget(label(help_text, "help"))
        page.lay.addWidget(f)
        f.lay = lay
        f.n = 0
        return f

    def add_row(self, card, title, help_text, control):
        if card.n:
            sep = QFrame(objectName="sep")
            card.lay.addWidget(sep)
        card.n += 1
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 2, 0, 2)
        rl.setSpacing(16)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        txt.addWidget(label(title, "rowTitle"))
        if help_text:
            txt.addWidget(label(help_text, "help"))
        rl.addLayout(txt, 1)
        rl.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        card.lay.addWidget(row)
        row.control = control
        return row

    def setting_row(self, card, key, title=None, extra=None):
        """Zeile für eine Einstellung aus dem Schema (Typ bestimmt das Bedienelement)."""
        s = S.BY_KEY[key]
        ctrl = self.control_for(s)
        if extra is not None:
            ctrl = hbox(ctrl, extra)
        help_text = (t(s.help) if s.help else "") + (
            "  ·  " + t("greift nach Neustart") if s.restart else "")
        if S.overridden(key):
            help_text += "  ·  " + t("durch Umgebungsvariable festgelegt")
            ctrl.setEnabled(False)
        row = self.add_row(card, title or t(s.title), help_text, ctrl)
        self.rows[key] = row
        return row

    def control_for(self, s):
        v = S.get(s.key)
        if s.type == "bool":
            w = Toggle(v, self.c)
            w.toggled.connect(lambda val, k=s.key: self.save(k, val))
        elif s.type == "choice":
            w = QComboBox()
            for val, text in s.choices:
                w.addItem(text if text in S.VOICES else t(text), val)
            w.setCurrentIndex(max(0, w.findData(v)))
            w.setMinimumWidth(230)
            w.currentIndexChanged.connect(lambda _i, k=s.key, w=w: self.save(k, w.currentData()))
        elif s.type == "int":
            w = QSpinBox()
            w.setRange(int(s.min or 0), int(s.max or 9999))
            w.setValue(int(v))
            w.setMinimumWidth(80)
            w.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            w.setAlignment(Qt.AlignmentFlag.AlignRight)
            w.editingFinished.connect(lambda k=s.key, w=w: self.save(k, w.value()))
        elif s.type == "float":
            w = QDoubleSpinBox()
            w.setRange(s.min or 0, s.max or 999)
            w.setSingleStep(0.5)
            w.setDecimals(1)
            w.setValue(float(v))
            w.setMinimumWidth(80)
            w.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            w.setAlignment(Qt.AlignmentFlag.AlignRight)
            w.editingFinished.connect(lambda k=s.key, w=w: self.save(k, w.value()))
        elif s.type == "path":
            edit = QLineEdit(str(v))
            edit.setPlaceholderText(t("Standard"))
            edit.setMinimumWidth(260)
            edit.editingFinished.connect(lambda k=s.key, e=edit: self.save(k, e.text().strip()))
            btn = QPushButton(t("Wählen …"))

            def pick(_=False, e=edit, k=s.key):
                d = QFileDialog.getExistingDirectory(self, t("Ordner wählen"), e.text() or str(Path.home()))
                if d:
                    e.setText(d)
                    self.save(k, d)
            btn.clicked.connect(pick)
            w = hbox(edit, btn)
        else:
            w = QLineEdit(str(v))
            w.setMinimumWidth(260)
            w.editingFinished.connect(lambda k=s.key, w=w: self.save(k, w.text().strip()))
        return w

    def save(self, key, value):
        if key == "WALKIE_VOICE" and value in S.VOICES:
            model = S.VOICES[value][0]
            self.wanted_voice = value
            if not (HERE / "voices" / f"{model}.onnx").exists():
                loading = self.__dict__.setdefault("voice_downloads", set())
                if model in loading:
                    return                       # läuft schon; übernommen wird die zuletzt gewählte
                loading.add(model)
                self.toast(t("Stimme „{voice}“ wird geladen …", voice=value))

                def fetch():
                    import fetch_assets
                    fetch_assets.fetch_voice(model)

                def done(r, v=value):
                    loading.discard(model)
                    if isinstance(r, Exception):
                        self.toast(t("Laden fehlgeschlagen: {error}", error=r))
                    elif getattr(self, "wanted_voice", None) == v:
                        self.save(key, v)        # nur, wenn inzwischen keine andere gewählt ist
                Bg(fetch, done)
                return
        try:
            S.set(key, value)
        except (ValueError, KeyError) as ex:
            self.toast(str(ex))
            return
        if key == "WALKIE_UI_LANG":           # sofort in der neuen Sprache zeigen
            QTimer.singleShot(0, self.refresh_language)
            return
        if S.BY_KEY[key].restart and self.walkie is not None:
            self.needs_restart.add(key)
            self.banner.show()
        self.update_deps()

    def update_deps(self):
        """Abhängige Einstellungen ausgrauen."""
        def enable(keys, on):
            for k in keys:
                if k in self.rows:
                    self.rows[k].setEnabled(on)
        enable(["WALKIE_ANNOUNCE_ATTENTION", "WALKIE_ANNOUNCE_ERROR", "WALKIE_ANNOUNCE_DONE",
                "WALKIE_ANNOUNCE_AFTER", "WALKIE_SUMMARY"], S.get("WALKIE_ANNOUNCE"))
        enable(["WALKIE_ANSWER_MODE", "WALKIE_ANSWER_WINDOW", "WALKIE_ANSWER_MAX",
                "WALKIE_ASK_WAIT"], S.get("WALKIE_VOICE_ANSWER"))
        enable(["WALKIE_REPLY_WAIT"], S.get("WALKIE_VOICE_REPLY"))
        enable(["WALKIE_AGENT_CMD"], S.get("WALKIE_AGENT") == "custom")
        enable(["WALKIE_SUMMARY_MODEL"], S.get("WALKIE_SUMMARY") == "claude")

    def make_banner(self):
        f = QFrame(objectName="banner")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(16, 10, 10, 10)
        lay.addWidget(label(t("Einige Änderungen greifen erst nach einem Neustart."), wrap=False), 1)
        b = QPushButton(t("Jetzt neu starten"))
        b.clicked.connect(self.restart_walkie)
        lay.addWidget(b)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(36, 14, 36, 0)
        wl.addWidget(f)
        wrap.hide()
        return wrap

    def unlock_keys(self, button):
        """udev-Regel per pkexec installieren (grafische Passwortabfrage), ohne die GUI
        anzuhalten; danach die Seite neu aufbauen."""
        src = HERE / "extras" / "udev" / keymap.RULE
        cmd = keymap.unlock_command(src)
        if cmd is None:
            QApplication.clipboard().setText(keymap.unlock_hint(src))
            self.toast(t("pkexec fehlt – der Befehl liegt in der Zwischenablage (Terminal, einmalig)."))
            return
        button.setEnabled(False)
        button.setText(t("Warte auf Passwort …"))
        proc = subprocess.Popen(cmd)

        def check():
            if proc.poll() is None:
                return
            timer.stop()
            if keymap.keys_need_unlock():
                button.setEnabled(True)
                button.setText(t("Tasten freischalten"))
                self.toast(t("Nicht freigeschaltet – abgebrochen?"))
            else:
                self.toast(t("Freigeschaltet 🎧 Falls die Tasten nicht sofort gehen: Kopfhörer neu verbinden."))
                button.setText(t("Freigeschaltet ✓"))
        timer = QTimer(button, timeout=check)
        timer.start(400)

    def toast(self, text):
        self.status_text = text
        if self.walkie is not None:
            from walkie import notify
            notify(text)
        else:
            print(text, file=sys.stderr)

    def restart_walkie(self):
        import paths
        subprocess.Popen([paths.python(), str(HERE / "cli.py"), "restart"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=paths.clean_env(),
                         **({"start_new_session": True} if not paths.WIN else
                            {"creationflags": subprocess.CREATE_NO_WINDOW}))
        if self.walkie is None:
            QApplication.quit()

    def on_page(self, i):
        if 0 <= i < len(self.PAGES) and self.PAGES[i] == "info":
            self.refresh_info()

    # ---------------- Seiten ----------------
    def goto(self, page):
        """Zur Seite mit der festen ID (siehe PAGES) – unabhängig von der Sprache."""
        if page in self.PAGES:
            self.nav.setCurrentRow(self.PAGES.index(page))

    def check_row(self, card, state, title, text):
        mark = {True: "✓", False: "✗", None: "•"}[state]
        lb = label(text, "muted")
        self.add_row(card, f"{mark}  {title}", "", lb)

    def page_welcome(self):
        """Ersteinrichtung: was schon klappt, und wo es noch einen Handgriff braucht."""
        pg = self.page(t("Erste Schritte"),
                       t("In drei Schritten zu „mit {name} per Kopfhörer reden“.",
                         name=S.get("WALKIE_NAME")))
        c = self.card(pg, "Sprache / Language")
        self.setting_row(c, "WALKIE_UI_LANG")
        mics = [n for n, _ in audio.sources()]
        outs = audio.outputs()
        heads = keymap.headset_audio(outs)
        keys_ok, keys_text = keymap.key_status()

        c = self.card(pg, t("1 · Mikrofon"),
                      t("Sprich einen Satz zur Probe – du siehst sofort, was verstanden wurde."))
        self.check_row(c, bool(mics), t("Mikrofon"),
                       ", ".join(mics) if mics else t("keins gefunden – Kopfhörer verbinden"))
        b = QPushButton(t("Mikro testen"), objectName="primary")
        b.clicked.connect(lambda: self.goto("voice"))
        c.lay.addWidget(hbox(b, None))

        c = self.card(pg, t("2 · Kopfhörer"),
                      t("Dein Bluetooth-Kopfhörer ist Lautsprecher, Mikro und Fernbedienung zugleich."))
        self.check_row(c, True if heads else None, t("Als Audiogerät"),
                       ", ".join(heads) if heads else t("kein Kopfhörer verbunden"))
        self.check_row(c, keys_ok, t("Tasten"), keys_text)
        self.check_row(c, True, t("Hotkey (geht immer)"), S.get("WALKIE_HOTKEY") or t("aus"))
        b = QPushButton(t("Taste anlernen"))
        b.clicked.connect(lambda: self.goto("headset"))
        if keymap.keys_need_unlock():
            u = QPushButton(t("Tasten freischalten"), objectName="primary")
            u.setToolTip(t("Erlaubt dem Walkie, die Tasten deines Bluetooth-Kopfhörers zu lesen "
                           "(einmalig, fragt nach deinem Passwort)."))
            u.clicked.connect(lambda: self.unlock_keys(u))
            c.lay.addWidget(hbox(u, b, None))
        else:
            c.lay.addWidget(hbox(b, None))

        c = self.card(pg, t("3 · So geht's"),
                      t("Play am Kopfhörer, Klick auf die Figur oder der Hotkey: Pling = sprich. "
                        "Ist eine Frage offen, beantwortest du sie (ja/nein/Option). Sonst geht dein "
                        "Satz an die passende Claude-Session – oder der Walkie antwortet selbst. "
                        "Fallender Ton = fertig zugehört."))
        demo = QPushButton(t("Stimme anhören"))
        demo.clicked.connect(self.voice_demo)
        demo.setEnabled(self.walkie is not None)
        done = QPushButton(t("Fertig – loslegen"), objectName="primary")
        done.clicked.connect(self.finish_welcome)
        c.lay.addWidget(hbox(demo, None, done))
        pg.lay.addStretch(1)
        return pg

    def finish_welcome(self):
        try:
            WELCOMED.parent.mkdir(parents=True, exist_ok=True)
            WELCOMED.write_text("1", encoding="utf-8")
        except OSError:
            pass
        self.close()

    def page_general(self):
        pg = self.page(t("Allgemein"), t("Wer im Terminal arbeitet und wann der Begleiter startet."))
        c = self.card(pg, t("Begleiter"))
        self.setting_row(c, "WALKIE_UI_LANG")
        self.setting_row(c, "WALKIE_NAME")
        self.setting_row(c, "WALKIE_WANDER")
        self.setting_row(c, "WALKIE_NOTIFY")
        c = self.card(pg, t("Agent"))
        self.setting_row(c, "WALKIE_AGENT")
        self.setting_row(c, "WALKIE_AGENT_CMD")
        self.setting_row(c, "WALKIE_AGENT_2")
        self.setting_row(c, "WALKIE_WORKDIR")
        self.setting_row(c, "WALKIE_SESSION_DIR")
        c = self.card(pg, t("Start"))
        self.setting_row(c, "WALKIE_LOGIN_AUTOSTART")
        self.setting_row(c, "WALKIE_AUTOSTART")
        pg.lay.addStretch(1)
        return pg

    # ---- Figur
    def page_figure(self):
        pg = self.page(t("Figur"), t("Mitgelieferte Figuren (frei, CC0) oder eigene Sprites im selben "
                                     "Format – siehe figures/CREDITS.md."))
        c = self.card(pg, t("Deine Figuren"), t("Klick auf eine Figur, um sie zu nehmen. Fuchs, Frosch "
                      "und Schleim sind freie Pixel-Art (CC0) – Credits in figures/CREDITS.md."))
        self.tiles_box = QWidget()
        self.tiles = QGridLayout(self.tiles_box)
        self.tiles.setContentsMargins(0, 4, 0, 4)
        self.tiles.setSpacing(10)
        c.lay.addWidget(self.tiles_box)
        self.fill_installed()
        custom = QPushButton(t("Eigener Ordner …"))
        custom.clicked.connect(self.pick_sprite_folder)
        scale = QSlider(Qt.Orientation.Horizontal)
        scale.setRange(2, 8)
        scale.setValue(S.get("WALKIE_SCALE"))
        scale.setFixedWidth(180)
        scale_lbl = label(f"{S.get('WALKIE_SCALE')}×", "muted", wrap=False)
        scale.valueChanged.connect(lambda v: scale_lbl.setText(f"{v}×"))
        scale.sliderReleased.connect(lambda: self.save("WALKIE_SCALE", scale.value()))
        c.lay.addWidget(hbox(custom, None, label(t("Größe"), "rowTitle", wrap=False), scale, scale_lbl))

        return pg

    def fill_installed(self):
        """Kacheln aller installierten Figuren: mitgelieferte (figures/) zuerst."""
        g = self.tiles
        while g.count():
            w = g.takeAt(0).widget()
            if w:
                w.deleteLater()
        cur = S.sprite_dir().resolve()
        dirs = [d for base in ("figures", "sprites") if (HERE / base).exists()
                for d in sorted((HERE / base).iterdir()) if (d / "AnimData.xml").exists()]
        if cur not in [d.resolve() for d in dirs] and (cur / "AnimData.xml").exists():
            dirs.append(cur)
        for i, d in enumerate(dirs):
            try:
                title = json.loads((d / "figure.json").read_text(encoding="utf-8"))["title"]
            except (OSError, ValueError, KeyError):
                title = d.name.replace("-", " ").title()
            tile = FigureTile(d, title, d.resolve() == cur, self.c)
            tile.chosen.connect(self.use_sprite)
            g.addWidget(tile, i // 5, i % 5)

    def use_sprite(self, folder):
        default = S.DEFAULT_FIGURE.resolve()
        self.save("WALKIE_SPRITE", "" if folder.resolve() == default else str(folder))
        self.fill_installed()

    def pick_sprite_folder(self):
        d = QFileDialog.getExistingDirectory(self, t("Sprite-Ordner wählen"), str(HERE / "figures"))
        if d and (Path(d) / "AnimData.xml").exists():
            self.use_sprite(Path(d))
        elif d:
            self.toast(t("Kein Sprite-Ordner: AnimData.xml fehlt."))

    # ---- Kopfhörer
    def page_headset(self):
        pg = self.page(t("Kopfhörer"), t("Lege fest, was die Tasten deines Bluetooth-Kopfhörers tun."))
        c = self.card(pg, t("Gerät"))
        heads = keymap.headset_audio(audio.outputs())
        keys_ok, keys_text = keymap.key_status()
        self.add_row(c, t("Als Audiogerät"), t("Lautsprecher und Mikro des Kopfhörers."),
                     label(", ".join(heads) if heads else t("kein Kopfhörer verbunden"), "muted"))
        self.add_row(c, t("Tasten"), "", label(keys_text, "muted"))
        self.setting_row(c, "WALKIE_HEADSET", t("Welcher Kopfhörer"))
        self.setting_row(c, "WALKIE_HOTKEY")

        c = self.card(pg, t("Tastenbelegung"),
                      t("Musik-Aktionen steuern deinen Player direkt – so behältst du Play/Pause, "
                        "Vor und Zurück wie gewohnt. „Doppelt“ und „lang“ funktionieren nicht bei "
                        "jedem Kopfhörer: einfach mit „Taste anlernen“ ausprobieren."))
        self.key_grid_box = QWidget()
        self.key_grid = QGridLayout(self.key_grid_box)
        self.key_grid.setContentsMargins(0, 4, 0, 4)
        self.key_grid.setHorizontalSpacing(10)
        self.key_grid.setVerticalSpacing(8)
        c.lay.addWidget(self.key_grid_box)
        self.learn_btn = QPushButton(t("Taste anlernen"), objectName="primary")
        self.learn_btn.clicked.connect(self.start_learning)
        reset = QPushButton(t("Standard wiederherstellen"))
        reset.clicked.connect(self.reset_keys)
        self.learn_lbl = label("", "muted")
        c.lay.addWidget(hbox(self.learn_btn, reset, None))
        c.lay.addWidget(self.learn_lbl)
        self.learn_timer = QTimer(self, timeout=self.poll_learning)
        self.build_key_grid()
        pg.lay.addStretch(1)
        return pg

    def build_key_grid(self, highlight=None):
        g = self.key_grid
        while g.count():
            w = g.takeAt(0).widget()
            if w:
                w.deleteLater()
        mapping = S.get("WALKIE_KEYS")
        g.addWidget(label(t("Taste"), "help"), 0, 0)
        for j, (gest, text) in enumerate(keymap.GESTURES.items(), 1):
            g.addWidget(label(t(text).capitalize(), "help"), 0, j)
        keys = list(S.DEFAULT_KEYS) + [k for k in mapping if k not in S.DEFAULT_KEYS]
        for i, key in enumerate(keys, 1):
            g.addWidget(label(keymap.key_label(key), "rowTitle", wrap=False), i, 0)
            for j, gest in enumerate(keymap.GESTURES, 1):
                box = QComboBox()
                box.addItem("—", "")
                for act, text in keymap.ACTIONS.items():
                    if act != "none":
                        box.addItem(t(text), act)
                box.setCurrentIndex(max(0, box.findData((mapping.get(key) or {}).get(gest, ""))))
                box.setMinimumWidth(150)
                if highlight == (key, gest):
                    box.setObjectName("hl")
                    box.setFocus()
                box.currentIndexChanged.connect(
                    lambda _i, k=key, ge=gest, b=box: self.set_key(k, ge, b.currentData()))
                g.addWidget(box, i, j)
            if key not in S.DEFAULT_KEYS:
                rm = QPushButton(t("Entfernen"))
                rm.clicked.connect(lambda _=False, k=key: self.remove_key(k))
                g.addWidget(rm, i, len(keymap.GESTURES) + 1)

    def set_key(self, key, gesture, action):
        m = S.get("WALKIE_KEYS")
        m = {k: dict(v) for k, v in m.items()}
        m.setdefault(key, {})
        if action:
            m[key][gesture] = action
        else:
            m[key].pop(gesture, None)
        self.save("WALKIE_KEYS", m)

    def remove_key(self, key):
        m = dict(S.get("WALKIE_KEYS"))
        m.pop(key, None)
        self.save("WALKIE_KEYS", m)
        self.build_key_grid()

    def reset_keys(self):
        S.reset("WALKIE_KEYS")
        self.build_key_grid()

    def start_learning(self):
        if not walkie_running():
            self.learn_lbl.setText(t("Der Begleiter muss laufen, damit er die Tasten hört."))
            return
        RUN.mkdir(parents=True, exist_ok=True)
        LEARN_LOG.write_text("", encoding="utf-8")
        LEARN_FLAG.touch()
        self.learn_started = time.time()
        self.learn_btn.setEnabled(False)
        self.learn_lbl.setText(t("Drück jetzt eine Taste am Kopfhörer – einmal, doppelt oder lang …"))
        self.learn_timer.start(200)

    def poll_learning(self):
        if time.time() - self.learn_started > 30:
            self.stop_learning(t("Keine Taste erkannt. Ist der Kopfhörer verbunden?"))
            return
        try:
            lines = LEARN_LOG.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        if not lines:
            LEARN_FLAG.touch()
            return
        try:
            ev = json.loads(lines[-1])
            key, gest = ev["key"], ev["gesture"]
        except (ValueError, KeyError, TypeError):
            return                               # Zeile wird gerade geschrieben
        m = S.get("WALKIE_KEYS")
        if key not in m and key not in S.DEFAULT_KEYS:
            m = {k: dict(v) for k, v in m.items()}
            m[key] = {}
            self.save("WALKIE_KEYS", m)
        self.build_key_grid(highlight=(key, gest))
        self.stop_learning(t("Erkannt: {key} · {gesture}. "
                             "Wähle in der markierten Zelle, was passieren soll.",
                             key=keymap.key_label(key), gesture=t(keymap.GESTURES[gest])))

    def stop_learning(self, text):
        self.learn_timer.stop()
        LEARN_FLAG.unlink(missing_ok=True)
        self.learn_btn.setEnabled(True)
        self.learn_lbl.setText(text)

    # ---- Fragen & Freigaben
    def page_ask(self):
        pg = self.page(t("Fragen & Freigaben"),
                       t("Was die Figur ansagt und wie du per Stimme antwortest – auch ohne Bildschirm."))
        c = self.card(pg, t("Ansagen"))
        for k in ("WALKIE_ANNOUNCE", "WALKIE_ANNOUNCE_ATTENTION", "WALKIE_ANNOUNCE_ERROR",
                  "WALKIE_ANNOUNCE_DONE", "WALKIE_ANNOUNCE_AFTER", "WALKIE_SUMMARY"):
            self.setting_row(c, k)
        c = self.card(pg, t("Antworten per Stimme"),
                      t("Nach der Frage ertönt ein steigender Ton: jetzt sprechen. Ein fallender Ton "
                        "beendet das Zuhören. Erkannt werden ja/nein, Optionen und freie Antworten."))
        for k in ("WALKIE_VOICE_ANSWER", "WALKIE_VOICE_REPLY", "WALKIE_REPLY_WAIT",
                  "WALKIE_ANSWER_MODE", "WALKIE_ANSWER_WINDOW", "WALKIE_ANSWER_MAX",
                  "WALKIE_ASK_WAIT"):
            self.setting_row(c, k)
        pg.lay.addStretch(1)
        return pg

    # ---- Sprache & Modelle
    def page_voice(self):
        pg = self.page(t("Sprache & Modelle"), t("Mikrofon, Spracherkennung, Stimme und KI-Modelle."))
        c = self.card(pg, t("Mikrofon"))
        self.mic_box = QComboBox()
        self.mic_box.setMinimumWidth(280)
        self.fill_mics()
        self.mic_box.currentIndexChanged.connect(
            lambda _i: self.save("WALKIE_MIC", self.mic_box.currentData() or ""))
        refresh = QPushButton(t("Aktualisieren"))
        refresh.clicked.connect(self.fill_mics)
        self.rows["WALKIE_MIC"] = self.add_row(
            c, t("Mikrofon"), t("Ein Bluetooth-Kopfhörer-Mikro erscheint erst, wenn es aktiv ist. "
                                "Mit einem anderen Mikro bleibt der Kopfhörer in guter Klangqualität."),
            hbox(self.mic_box, refresh))
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedWidth(180)
        self.test_btn = QPushButton(t("Probeaufnahme (4 s)"))
        self.test_btn.clicked.connect(self.test_mic)
        self.add_row(c, t("Test"), t("Nimmt kurz auf, zeigt den Pegel und was Whisper versteht."),
                     hbox(self.level, self.test_btn))
        self.test_result = label("", "muted")
        c.lay.addWidget(self.test_result)

        c = self.card(pg, t("Spracherkennung"))
        for k in ("WALKIE_STT", "WALKIE_WHISPER", "WALKIE_LANG", "WALKIE_SILENCE"):
            self.setting_row(c, k)
        c = self.card(pg, t("Stimme"))
        demo = QPushButton(t("Hörprobe"))
        demo.clicked.connect(self.voice_demo)
        demo.setEnabled(self.walkie is not None)
        self.setting_row(c, "WALKIE_VOICE", extra=demo)
        self.setting_row(c, "WALKIE_READ_ANSWERS")
        c = self.card(pg, t("KI-Modelle"))
        self.setting_row(c, "WALKIE_BRAIN")
        self.setting_row(c, "WALKIE_SUMMARY_MODEL")
        self.setting_row(c, "WALKIE_CODEX_MODEL")
        self.setting_row(c, "WALKIE_AGENT_MODEL")
        pg.lay.addStretch(1)
        return pg

    def fill_mics(self):
        box = self.mic_box
        box.blockSignals(True)
        box.clear()
        box.addItem(t("Systemstandard"), "")
        for name, desc in audio.sources():
            box.addItem(desc, name)
        cur = S.get("WALKIE_MIC")
        if cur and box.findData(cur) < 0:
            box.addItem(t("{device} (nicht verbunden)", device=cur), cur)
        box.setCurrentIndex(max(0, box.findData(cur)))
        box.blockSignals(False)

    def test_mic(self):
        cmd_dev = S.get("WALKIE_MIC") or None
        fd, wav = tempfile.mkstemp(suffix=".wav", prefix="walkie-test-")
        os.close(fd)
        headset = self.walkie is not None and sys.platform.startswith("linux")
        if headset:
            cmd_dev = self.walkie.headset_audio.prepare(self, cmd_dev, S.get("WALKIE_HEADSET"))
        self.rec = audio.Recorder()
        if not self.rec.start(wav, cmd_dev):
            if headset:
                self.walkie.in_thread(self.walkie.headset_audio.release, self)
            os.unlink(wav)
            self.test_result.setText(t("Mikrofon lässt sich nicht öffnen: {error}", error=self.rec.error))
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText(t("Sprich jetzt …"))
        self.rec_wav, self.rec_pos, self.rec_t0, self.rec_headset = wav, 44, time.time(), headset
        self.peak = 0.0
        self.rec_timer = QTimer(self, timeout=self.rec_tick)
        self.rec_timer.start(100)

    def rec_tick(self):
        import numpy as np
        try:
            with open(self.rec_wav, "rb") as f:
                f.seek(self.rec_pos)
                data = f.read()
            data = data[: len(data) // 2 * 2]
            self.rec_pos += len(data)
            if data:
                a = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
                rms = float(np.sqrt(np.mean(a * a)))
                self.peak = max(self.peak, rms)
                self.level.setValue(min(100, int(rms * 1000)))
        except OSError:
            pass
        if time.time() - self.rec_t0 < 4:
            return
        self.rec_timer.stop()
        self.rec.stop()
        self.level.setValue(0)
        if self.rec_headset:
            self.walkie.in_thread(self.walkie.headset_audio.release, self)
        self.test_result.setText(t("Pegel max. {peak} – Whisper hört zu …", peak=f"{self.peak:.3f}"))
        Bg(self.transcribe, self.transcribed, self.rec_wav)

    def transcribe(self, wav):
        model = getattr(self.walkie, "whisper", None)
        if model is None:
            global _whisper
            if _whisper is None:
                from transcription import whisper_model
                _whisper = whisper_model(S.get("WALKIE_WHISPER"), cpu_threads=os.cpu_count() or 4)
            model = _whisper
        from walkie import transcribe
        try:
            return transcribe(model, wav)
        finally:
            os.unlink(wav)

    def transcribed(self, text):
        if not crashguard.alive(self.test_btn):
            return                              # Seite inzwischen neu aufgebaut
        self.test_btn.setEnabled(True)
        if isinstance(text, Exception):
            self.test_result.setText(t("Fehler: {error}", error=text))
            return
        hint = ("  " + t("Sehr leise – ein anderes Mikro wählen?") if self.peak < 0.01 else "")
        self.test_result.setText(t("Erkannt: „{text}“  (Pegel {peak}).", text=text or t("…nichts…"),
                                   peak=f"{self.peak:.3f}") + hint)

    def voice_demo(self):
        if self.walkie is not None:
            threading.Thread(target=self.walkie.set_voice, args=(S.get("WALKIE_VOICE"), True),
                             daemon=True).start()

    # ---- Info
    def page_info(self):
        pg = self.page(t("Info"), t("Zustand des Begleiters und Hilfe bei Problemen."))
        c = self.card(pg, t("Diagnose"))
        self.doctor = label("…", "mono")
        self.doctor.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        c.lay.addWidget(self.doctor)
        b1 = QPushButton(t("Einstellungsdatei öffnen"))
        b1.clicked.connect(lambda: self.open_path(S.CONFIG))
        b2 = QPushButton(t("Ordner öffnen"))
        b2.clicked.connect(lambda: self.open_path(HERE))
        b3 = QPushButton(t("Neu starten"), objectName="primary")
        b3.clicked.connect(self.restart_walkie)
        b3.setEnabled(self.walkie is not None)
        c.lay.addWidget(hbox(b1, b2, None, b3))
        c = self.card(pg, t("Im Terminal & in Claude"))
        c.lay.addWidget(label(t("Alle Einstellungen gehen auch ohne Fenster:\n"
                                "  walkie settings          interaktives Menü\n"
                                "  walkie set KEY WERT      einzelnen Wert setzen\n"
                                "  walkie list --json       alles für Skripte und KI-Agents"), "mono"))
        pg.lay.addStretch(1)
        return pg

    def open_path(self, path):
        """Datei/Ordner im Standardprogramm öffnen – plattformneutral (kein xdg-open unter
        Windows/macOS). Die Einstellungsdatei entsteht erst mit der ersten Änderung."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        path = Path(path)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.toast(t("Lässt sich nicht öffnen: {path}", path=path))

    def refresh_info(self):
        def run():
            r = subprocess.run([sys.executable, str(HERE / "doctor.py")], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=30,
                               stdin=subprocess.DEVNULL,
                               **({"creationflags": subprocess.CREATE_NO_WINDOW}
                                  if sys.platform == "win32" else {}))
            return (r.stdout + r.stderr).strip()
        doctor = self.doctor
        Bg(run, lambda out: crashguard.alive(doctor) and doctor.setText(str(out)))

    def closeEvent(self, e):
        LEARN_FLAG.unlink(missing_ok=True)
        super().closeEvent(e)


_whisper = None


class FigureTile(QFrame):
    """Anklickbare Kachel mit animierter Figur."""
    chosen = pyqtSignal(object)

    def __init__(self, folder, title, active, colors):
        super().__init__()
        self.folder = folder
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(124, 132)
        border = colors["accent"] if active else colors["border"]
        bg = colors["select"] if active else colors["card"]
        self.setStyleSheet(f"FigureTile {{ border: 2px solid {border}; border-radius: 12px; "
                           f"background: {bg}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 6)
        lay.setSpacing(0)
        self.preview = SpritePreview(scale=2, size=100)
        self.preview.load(folder)
        lay.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        name = label(title, "rowTitle", wrap=False)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(name)

    def mousePressEvent(self, _e):
        self.chosen.emit(self.folder)


class SpritePreview(QLabel):
    """Animierte Vorschau (Idle, frontal) eines Sprite-Ordners."""

    def __init__(self, scale=3, size=150):
        super().__init__()
        self.scale = scale
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.anim = None
        self.timer = QTimer(self, timeout=self.tick)

    def load(self, folder):
        from sprite import DOWN, Animator, SpriteSet
        try:
            self.anim = Animator(SpriteSet(folder, scale=self.scale))
            self.anim.play("Idle", DOWN)
            self.timer.start(33)
        except Exception:  # noqa: BLE001
            self.anim = None
            self.timer.stop()
            self.setText(t("keine Vorschau"))
        self.tick()

    def tick(self):
        if self.anim is None:
            return
        self.anim.advance(1.2)
        pm = QPixmap(self.size())
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        ground = self.height() - max(12, self.height() // 8)
        p.drawEllipse(QPointF(self.width() / 2, ground), 8 * self.scale, 5)
        self.anim.draw(p, self.width() / 2, ground)
        p.end()
        self.setPixmap(pm)


def main():
    import crashguard
    crashguard.install(lambda m: print(m, file=sys.stderr), RUN)
    app = QApplication(sys.argv)
    app.setApplicationName("Walkie")
    app.setDesktopFileName("walkie")
    f = QFont(app.font())
    f.setPointSizeF(max(f.pointSizeF(), 10))
    app.setFont(f)
    w = SettingsWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
