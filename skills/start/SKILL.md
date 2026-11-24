---
name: start
description: Starts the Walkie (a figure on the desktop you talk to through headphones). Installs it on first use. Use when the user wants to start, install or set up the walkie/companion.
---

Prüfe zuerst mit `walkie status`, ob der Begleiter läuft. Verwende den installierten
`walkie`-Befehl für die folgenden Schritte, wenn er im Suchpfad liegt.

Fehlt der Befehl, ermittle den Plugin-Ordner aus dem tatsächlichen Pfad dieser Datei:
Von `<plugin>/skills/start/SKILL.md` aus ist es `../..` relativ zum Ordner `start`.
Rufe unter Linux/macOS `sh "<plugin>/bin/walkie" status` auf, unter Windows
`"<plugin>\bin\walkie.cmd" status`. Ersetze `<plugin>` durch den ermittelten
absoluten Pfad. Verwende denselben Starter für die weiteren Befehle.

1. Läuft Walkie bereits, bestätige den Status kurz.
2. Andernfalls prüfe mit `walkie doctor`, ob die Abhängigkeiten vorhanden sind.
   Bei fehlenden Paketen verwende `walkie setup --lang de` bzw. `--lang en` – passend zur
   Sprache, in der der Nutzer mit dir spricht. Das richtet Walkie ein und startet ihn; beim
   ersten Start führt ein Assistent durch Sprache, Agent, Mikrofon und Kopfhörer.
3. Bei fertiger Installation führe `walkie start` aus und prüfe mit `walkie status`.
4. Einstellungen lassen sich mit `walkie gui` öffnen.
5. Meldet `walkie setup` oder `walkie doctor` fehlende Systembibliotheken (Linux, z. B. unter
   WSL: `libxcb-icccm4`, `libxcb-keysyms1`), zeige dem Nutzer den ausgegebenen
   `sudo apt-get install …`-Befehl und bitte ihn, ihn einmal im Terminal auszuführen
   (Passwort nötig). Führe danach `walkie start` aus.
