"""Was der Begleiter als Nächstes sagt – mit Vorrang statt stur der Reihe nach (Idee aus heard).

Stufen: URGENT (Fragen, Freigaben, Antworten auf das, was du gerade gesagt hast, Rückmeldungen)
        NORMAL (Fehler, „braucht dich“), ROUTINE („fertig“-Meldungen).
- Höhere Stufe wird zuerst gesprochen, innerhalb einer Stufe der Reihe nach.
- Gleicher Schlüssel (z. B. ("done", Session)): die neuere Meldung ersetzt die ältere wartende.
- Höchstens MAX Einträge; voll -> die älteste Routine-Meldung fällt weg.

Nach außen wie queue.Queue (put/get/get_nowait/empty), damit bestehender Code weiterläuft.
"""
import itertools
import queue
import threading

URGENT, NORMAL, ROUTINE = 0, 1, 2
MAX = 8


class SpeechQueue:
    def __init__(self):
        self._items = []                       # [(prio, seq, key, item)]
        self._seq = itertools.count()
        self._cv = threading.Condition()

    def put(self, item, prio=None, key=None):
        if prio is None:
            prio = URGENT        # direkte Rückmeldungen und Fragen; Ansagen setzen ihre Stufe selbst
        with self._cv:
            if key is not None:
                self._items = [e for e in self._items if e[2] != key]
            self._items.append((prio, next(self._seq), key, item))
            while len(self._items) > MAX:
                drop = [e for e in self._items if e[0] == ROUTINE] or \
                       [e for e in self._items if e[0] == NORMAL] or self._items
                self._items.remove(min(drop, key=lambda e: e[1]))
            self._items.sort(key=lambda e: (e[0], e[1]))
            self._cv.notify()

    def push_front(self, item):
        """Unterbrochenes wieder ganz nach vorne (z. B. weil du telefonierst)."""
        with self._cv:
            self._items.insert(0, (URGENT, -1, None, item))
            self._cv.notify()

    def get(self, timeout=None):
        with self._cv:
            if not self._cv.wait_for(lambda: self._items, timeout=timeout):
                raise queue.Empty
            return self._items.pop(0)[3]

    def get_nowait(self):
        with self._cv:
            if not self._items:
                raise queue.Empty
            return self._items.pop(0)[3]

    def empty(self):
        with self._cv:
            return not self._items

    def qsize(self):
        with self._cv:
            return len(self._items)
