"""Ein Fehler in einem Knopf darf nicht den ganzen Walkie beenden.

PyQt6 beendet den Prozess mit qFatal(), wenn in einem Slot eine Exception hochkommt – es sei
denn, sys.excepthook ist ersetzt. install() ersetzt ihn (und threading.excepthook) durch
Protokollieren, und schreibt bei echten Abstürzen (Segfault in Qt, Audio, Whisper) die
Thread-Stacks nach <RUN>/crash.log – ebenso, wenn der GUI-Thread hängt (hang_heartbeat).
"""
import faulthandler
import sys
import threading
import traceback

_crash_file = None


def safe_console():
    """Windows-Konsolen (cp1252) und pythonw ohne Konsole: Ausgaben mit ✓, „“ oder Emoji
    dürfen nie eine Exception auslösen – genau das verhinderte unter Windows das Laden der
    Stimme („'charmap' codec can't encode character '\\u2713'“)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def install(log, run_dir=None, notify=None):
    """log(text) protokolliert, notify(text) zeigt dem Nutzer einen kurzen Hinweis (optional)."""
    global _crash_file
    safe_console()
    shown = set()

    def report(kind, exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
        try:
            log(f"{kind}: {text}")
        except Exception:  # noqa: BLE001 – Protokollieren darf selbst nicht scheitern
            pass
        if notify is not None and exc_type is not None:
            key = (exc_type.__name__, str(exc)[:80])
            if key not in shown:               # denselben Fehler nicht immer wieder zeigen
                shown.add(key)
                try:
                    notify(f"{exc_type.__name__}: {str(exc)[:120]}")
                except Exception:  # noqa: BLE001
                    pass

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        report("Unerwarteter Fehler", exc_type, exc, tb)

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        report(f"Fehler im Thread {getattr(args.thread, 'name', '?')}",
               args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook
    if run_dir is not None and _crash_file is None:
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            _crash_file = open(run_dir / "crash.log", "a", encoding="utf-8")  # noqa: SIM115
            faulthandler.enable(_crash_file, all_threads=True)
        except (OSError, ValueError, RuntimeError):
            _crash_file = None


HANG_SECONDS = 15


def hang_heartbeat():
    """Vom GUI-Thread regelmäßig aufrufen (QTimer). Kommt er HANG_SECONDS lang nicht mehr dazu,
    schreibt faulthandler die Stacks aller Threads nach crash.log: Ein Hänger („reagiert
    nicht“, z. B. nach dem Trennen eines Headsets) ist sonst nicht zu finden, weil weder eine
    Exception noch ein Absturz auftritt. Einmal je Hänger; der Prozess läuft weiter."""
    if _crash_file is None:
        return
    try:
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(HANG_SECONDS, repeat=False, file=_crash_file)
    except (OSError, ValueError, RuntimeError):
        pass


def alive(widget):
    """Gibt es das Qt-Objekt hinter dem Python-Wrapper noch? (Nach einem Neuaufbau der
    Seiten, z. B. Sprachwechsel, sind alte Labels gelöscht.)"""
    try:
        from PyQt6 import sip
    except ImportError:
        try:
            import sip
        except ImportError:
            return widget is not None
    return widget is not None and not sip.isdeleted(widget)
