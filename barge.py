"""Unterbrechen durch Reden (Ideen aus VoiceMode und GodTerm).

Während der Begleiter vorliest, hört er mit – aber nur, wenn das sicher geht:
Ausgabe über Kopfhörer (sonst hört das Mikro die eigene Stimme) und ein anderes Mikro als das
des Bluetooth-Kopfhörers (das würde den Kopfhörer mitten im Vorlesen in den schlechten
Telefonmodus schalten).

decide(gehört, gerade_gesagt) -> "stop" | None
- Stopp-Wörter („stopp“, „warte“, „halt“ …) brechen sofort ab – außer der Begleiter hat sie
  gerade selbst gesagt (Echo).
- Sonst: Überwiegen Wörter, die er gerade selbst sagt (≥ 70 %), ist es Echo.
- Sonst: ab drei neuen Inhaltswörtern redet der Nutzer -> abbrechen.
- Füllwörter und Rückmeldungen („ja“, „okay“, „mhm“) zählen nicht.
"""
import re

STOP_WORDS = {"stopp", "stop", "warte", "wart", "halt", "ruhe", "moment", "pause", "still",
              "leise", "aufhören", "hör", "schluss", "wait", "shush", "quiet", "enough"}
FILLERS = {"ja", "jo", "okay", "ok", "mhm", "hm", "hmm", "äh", "ähm", "genau", "gut", "super",
           "danke", "ah", "aha", "oh", "na", "nee", "nein", "und", "die", "der", "das", "ein",
           "eine", "ich", "du", "es", "ist", "so", "mal", "yeah", "yes", "no", "uh", "um"}
ECHO_SHARE = 0.7
NOVEL_WORDS = 3


def words(text):
    return re.findall(r"[a-zäöüß]+", (text or "").lower())


def decide(heard, spoken):
    got = words(heard)
    if not got:
        return None
    said = set(words(spoken))
    if any(w in STOP_WORDS and w not in said for w in got):
        return "stop"
    if sum(w in said for w in got) / len(got) >= ECHO_SHARE:
        return None                                  # eigene Stimme durchs Mikro
    novel = [w for w in got if w not in said and w not in FILLERS and len(w) > 2]
    return "stop" if len(novel) >= NOVEL_WORDS else None


def looks_like_headphones(name):
    n = (name or "").lower()
    return any(k in n for k in ("bluez", "headphone", "headset", "kopfhörer", "airpods", "buds",
                                "beats", "earphone", "in-ear"))
