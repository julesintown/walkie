# Walkie

**Mit Claude Code über Kopfhörer reden.**

Du stößt ein Refactoring an, holst dir einen Kaffee, und auf halbem Weg sagt dein Kopfhörer:
*„Braucht dich: Migrationen ausführen?“* Du sagst *„ja“*. Erledigt. Zurück am Schreibtisch sitzt
ein kleiner Fuchs oben auf dem Terminal, das gerade arbeitet – und rüttelt sich vor Eifer.

Walkie ist ein kleiner Begleiter auf deinem Desktop, mit dem du Claude Code **freihändig**
nutzt. Er sagt an, was deine Sessions machen, liest ihre Fragen und Freigaben vor, nimmt deine
Antworten per Stimme entgegen – und macht die Tasten deines Bluetooth-Kopfhörers zu seiner
Fernbedienung.

*[English version](README.md)*

## Was er kann

### 🎧 Der Kopfhörer ist die Fernbedienung
Play/Pause, Vor, Zurück – einmal, doppelt oder lang gedrückt, jeweils mit eigener Aktion: reden,
wiederholen, erlauben, ablehnen, Musik pausieren. Funktioniert mit ganz normalen
Bluetooth-Kopfhörern. Welche Gesten ankommen, hängt vom Modell ab. Das Mikro öffnet sich
per Tastendruck oder nach einer Rückfrage, wenn automatisches Zuhören aktiviert ist.
Mit „Unterbrechen durch Reden“ kann Walkie auch während der Wiedergabe kurz mithören.

### 🗣️ Per Stimme antworten
Freigaben und Rückfragen: *„ja“*, *„nein, nimm lieber yarn“* oder einfach der Name einer Option.
Der normale Dialog im Terminal bleibt offen – wer zuerst antwortet, gewinnt.

### 🧭 Einfach reden – er findet die richtige Session
Play drücken und sagen, was du willst. Der Walkie schickt es an die passende Claude-Code-Session –
nach Projektname, nach Thema oder an die, mit der du gerade gesprochen hast –, öffnet eine neue
Session für ein Projekt, das noch nicht läuft, oder beantwortet kleine Fragen selbst.
*„Zeig mir das“* holt das Fenster der Session nach vorne.

### 🔔 Hören, was los ist
*„Die Tests sind grün. Soll ich committen?“* Walkie kann lange Antworten fürs Vorlesen kürzen.
Arbeitsberichte bleiben knapp, bei Erklärungen und Vorschlägen soll der Inhalt erhalten bleiben.
Den Session-Namen hörst du, wenn mehrere Gespräche auseinanderzuhalten sind.

### 🦊 Er wohnt auf deinem Desktop
Loslassen, und er fällt aufs Fenster darunter. Er läuft auf Fensterkanten und fährt mit, wenn du
Fenster verschiebst, klettert an den Bildschirmrändern hoch, krabbelt oben entlang – und fängt
eine Session an zu arbeiten, hüpft er auf deren Terminal und arbeitet sichtbar mit. Lieber ein
anderes Aussehen? Jedes Shimeji-Paket lässt sich mit einem Befehl übernehmen.

### ⚙️ Einstellungen, die man findet
Rechtsklick auf die Figur → *Einstellungen …*. Mit **Sprache / Language** wechselst du zwischen
Deutsch und Englisch. Menüs, Ansagen, Erkennung und Vorlesestimme wechseln gemeinsam.
Das Fenster lässt sich auch mit `walkie gui` öffnen.

### 🔒 Lokal zuerst
Spracherkennung (Whisper) und Stimme (Piper) laufen auf deinem Rechner. Details unten.

## Installation

Walkie wird in erster Linie für **Claude Code** entwickelt und dort getestet. Öffne eine Claude-Code-Sitzung und gib die folgenden Befehle nacheinander ein.

```
/plugin marketplace add julesintown/walkie
/plugin install walkie@walkie
/walkie:start
```

`/walkie:start` richtet beim ersten Mal alles ein (1–3 Minuten, keine Adminrechte):
eigene Python-Umgebung, Pakete, eine Stimme und die Spracherkennung. Danach öffnet sich
**„Erste Schritte“**: Mikro testen, Kopfhörer prüfen, Taste anlernen.

**Kopfhörertasten unter Linux:** Falls Walkie die Medientasten noch nicht lesen kann, öffne
*Erste Schritte → Tasten freischalten* oder führe `walkie keys unlock` im Terminal aus.
Dein System fragt einmalig nach Administratorrechten, um die udev-Regel zu installieren.
Verbinde den Kopfhörer danach bei Bedarf neu. Walkie selbst läuft als normaler Benutzer.

**Aus dem Terminal installieren** (Linux/macOS):

```sh
git clone https://github.com/julesintown/walkie.git
cd walkie
./install.sh
```

Unter Windows im geklonten Ordner `bin\walkie.cmd setup` ausführen. Die Einrichtung lädt bei Bedarf
Python über [uv](https://github.com/astral-sh/uv). Später startet `walkie start` die Figur erneut.
Unter Linux/macOS funktioniert im Repo auch `./bin/walkie start`, unter Windows `bin\walkie.cmd start`.

**Optionales Codex-CLI-Plugin** für Session-Ereignisse:

```sh
codex plugin marketplace add julesintown/walkie
codex plugin add walkie@walkie
```

Für Sprachgespräche mit Codex in den Walkie-Einstellungen *Hauptagent → Codex* wählen und
Walkie neu starten. Falls die CLI nach der Freigabe für Plugin-Hooks fragt, diese bestätigen.

Beim freien Diktieren bestätigt ein Klick den Tastendruck. Sprich nach dem ansteigenden Ton.
Ein gesprochenes „Okay“ bestätigt das Aufnahmeende bei erkanntem Sprachpegel. Ohne geladene
Stimme übernimmt ein fallender Ton. Mit `WALKIE_TALK=auto` nutzt Claude das Session-Routing.
Codex, Gemini, Antigravity und eigene Befehle erhalten den lokal transkribierten Text im
Walkie-Terminal (benötigt kitty mit Panel-Unterstützung).

Mit `walkie drafts` liest du ausstehende und unbestätigte Diktate. Das aktuelle Claude-Plugin
bestätigt die Annahme jedes Satzes. Bei älteren Plugins bleibt eine lokale Kopie erhalten.
Bei einer unbestätigten Übergabe im nativen Claude-Diktat zeigt der Befehl den Pfad zur Aufnahme.

## Plattformen

| | Stand |
|---|---|
| **Linux – KDE Plasma** (Wayland/X11, PipeWire) | entwickelt und täglich im Einsatz |
| **Linux – GNOME und andere** | sollte laufen; Fensterkanten nur unter X11 mit `wmctrl`, kein „Zeig mir das“ unter GNOME-Wayland |
| **Windows 10/11** | experimentell – noch nicht auf echter Hardware getestet; Kopfhörertasten über Medientasten |
| **macOS** | experimentell – noch nicht auf echter Hardware getestet; braucht Freigaben für Mikrofon und Bedienungshilfen |

Linux: Die Kopfhörertasten zu lesen braucht einmalig eine Freigabe – ein Klick auf *Tasten
freischalten* in „Erste Schritte“ (das System fragt nach deinem Passwort; oder `walkie keys
unlock`). Sie macht nur das Tasten-Gerät des Kopfhörers für dich lesbar
(`extras/udev/70-walkie-avrcp.rules`). Bis dahin: Klick auf die Figur oder der Hotkey. Unter Wayland greift der globale Hotkey nur, solange ein X11-Fenster den Fokus hat –
dort sind die Kopfhörertasten der bessere Weg.

## So funktioniert es

```
Claude-Code-Session ── Plugin-Modul (hooks/session.tsx) ──► lokaler Dienst der Walkie-App
   Status, Fragen, Freigaben; Gesprochenes kommt als nächster Prompt zurück   (127.0.0.1 + Token)
Walkie-App (Python/Qt): Figur · Mikro & Lautsprecher (miniaudio) · Whisper · Piper · Tasten · Router
```

Das Plugin braucht in Claude Code kein Python. Läuft die Walkie-App nicht, tut das Plugin
nichts – keine Fehler, keine Wartezeit.

## Datenschutz – was lokal bleibt, was nicht

- **Auf deinem Rechner** laufen Piper und die lokale Whisper-Erkennung. Einstellungen und ausstehende Diktate werden lokal gespeichert. Der Zugriff auf Session-Daten der lokalen Brücke erfordert ein Token.
- **An den gewählten Agenten** geht der Text, den du an eine Session sendest. Für Routing und Zusammenfassungen kann Walkie zusätzlich Gesprächsausschnitte über die konfigurierte Modell-CLI verarbeiten. Das native Claude-Diktat nutzt die Sprachfunktion von Claude Code.

- **Downloads bei der Einrichtung:** Python-Pakete (PyPI), die Stimme (Hugging Face / rhasspy),
  das Whisper-Modell (Hugging Face).

## Einstellungen

`/walkie` (in Claude Code), Rechtsklick auf die Figur → *Einstellungen …* oder im Terminal:

```
walkie settings             Menü (Pfeiltasten)
walkie set announce aus     einzelne Werte
walkie keys learn           Kopfhörertaste anlernen
walkie list --json          alles, für Skripte und KI-Agents (walkie agent-guide)
walkie start | stop | restart | status | doctor
```

## Figuren

Fuchs (Standard), Frosch und Schleim – freie Pixel-Art (CC0, siehe `figures/CREDITS.md`), mit
`tools/make_figures.py` umgebaut. Eigene Figuren: jeder Ordner mit `AnimData.xml` und
`<Animation>-Anim.png` (8 Richtungen) über *Einstellungen → Figur → Eigener Ordner*.

**Shimeji-Pakete** (`shime1.png` … `shime46.png`, Shimeji-ee-Belegung) lassen sich direkt
übernehmen – mit eigenen Posen fürs Klettern, für die Decke und fürs Sitzen auf der Kante:

    walkie sprite import ~/Downloads/irgendein-shimeji.zip mein-shimeji

Figuren ohne Kletterbilder klettern gedreht. Fensterkanten gibt es unter KDE (Wayland oder X11),
macOS (Fensterliste des Systems, ohne zusätzliche Freigabe) und auf X11-Desktops mit `wmctrl`;
anderswo nutzt die Figur Boden, Bildschirmränder und Decke.

## Entwicklung

```
python -m unittest discover -s tests      # App, Brücke, Router, Einstellungen, Dauertest (200 Runden)
claude plugin validate . && claude plugin test .   # das Plugin-Modul
```

Der CI-Workflow (`.github/workflows/tests.yml`) führt die Tests und den echten Erstnutzer-Weg
`walkie setup` auf Ubuntu, macOS und Windows aus.

Lizenz: [MIT](LICENSE). Figuren: CC0 (siehe `figures/CREDITS.md`). Stimmen: [Piper](https://github.com/rhasspy/piper); Spracherkennung: [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
