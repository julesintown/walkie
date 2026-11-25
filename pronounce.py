"""Aussprache für die Stimme: englische Namen klingen mit deutscher Stimme sonst deutsch
(„Walkie“ -> „Valkie“, „Claude“ -> „Klaude“).

Ersetzt wird nur, was die Stimme bekommt – angezeigter Text und Logs bleiben unverändert. Ein
Eintrag ist eine Schreibweise („Uohki“) oder Lautschrift in [[...]] (Piper spricht sie dann
genau so; Phoneme wie bei espeak-ng). Eigene Einträge in WALKIE_PRONOUNCE:
"Wort=Aussprache; Wort=Aussprache" – sie gehen den eingebauten vor.
"""
import re

# je Sprache der Stimme (erste zwei Buchstaben des Modells, z. B. de_DE-thorsten -> de)
DEFAULTS = {
    "de": {
        "Walkie": "[[wˈɔːki]]",         # wie die englische Stimme: wˈɔːki
        "Claude": "[[klˈɔːd]]",
        "Gemini": "[[dʒˈɛmɪnaɪ]]",
    },
}


def parse(user):
    """'Walkie=Uohki; Claude=[[klˈɔːd]]' -> {"Walkie": "Uohki", "Claude": "[[klˈɔːd]]"}"""
    out = {}
    for part in re.split(r"[;\n]", user or ""):
        word, sep, say = part.partition("=")
        if sep and word.strip() and say.strip():
            out[word.strip()] = say.strip()
    return out


def table(lang, user=""):
    return {**DEFAULTS.get(lang, {}), **parse(user)}


def apply(text, lang, user=""):
    """Wörter (ganze Wörter, Groß-/Kleinschreibung egal) durch ihre Aussprache ersetzen."""
    words = table(lang, user)
    if not words:
        return text

    def say(word, punct):
        v = words[word]
        if v.startswith("[[") and v.endswith("]]"):
            # Satzzeichen direkt danach verschluckt Piper (kein Satzende, kein Frageton) –
            # darum gehört es mit in den Block
            return f"[[ {v[2:-2].strip()}{punct} ]]"
        return v + punct

    for word in sorted(words, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)([.,!?;:]?)",
                      lambda m, w=word: say(w, m.group(1)), text, flags=re.IGNORECASE)
    return re.sub(r"\]\](?=\S)", "]] ", text)     # sonst klebt das nächste Wort am Block
