#!/usr/bin/env sh
# Installiert und startet den Walkie (Linux/macOS). Windows: bin\walkie.cmd setup
# Dasselbe wie `walkie setup`: eigene Python-Umgebung, Pakete, Stimme, Spracherkennung.
# Fehlt ein passendes Python, holt bin/walkie es über uv – ohne Adminrechte.
cd "$(dirname "$0")" || exit 1
mkdir -p "$HOME/.local/bin" && ln -sf "$PWD/bin/walkie" "$HOME/.local/bin/walkie"
exec sh bin/walkie setup "$@"
