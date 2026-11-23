#!/bin/sh
# Walkie starten (Linux/macOS). Windows: bin\walkie.cmd start
# Einstellungen: /walkie in Claude Code, Rechtsklick auf die Figur oder `walkie settings`.
here="$(cd "$(dirname "$0")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}/walkie/venv"
py=python3
for p in "$WALKIE_VENV/bin/python" "$data/bin/python" "$here/.venv/bin/python"; do
  [ -x "$p" ] && { py="$p"; break; }
done
# keine Variablen einer evtl. umgebenden Claude-Code-Session erben
for v in $(env | grep -oE '^CLAUDE[A-Z_]*'); do unset "$v"; done
case "${1:-}" in
  --doctor)   shift; exec "$py" "$here/doctor.py" "$@" ;;
  --settings) exec "$py" "$here/settings_gui.py" ;;
esac
exec "$py" "$here/walkie.py" "$@"
