// /walkie: Einstellungsmenü des Walkie als Dialog direkt im Chat – Claude Codes
// eigene Oberfläche, darum in jedem Terminal gleich: ↑↓ wählen, Enter öffnen/ändern,
// „‹ Zurück“ eine Ebene hoch, Esc schließt. Bedient sich wie `walkie settings`.
// Gelesen und geschrieben wird nur über die CLI (cli.py list --json / set).
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Setting } from '../types'

const PANE = 'walkie-menu'
const HOME = 'home'                  // Ansicht: Bereiche; sonst Gruppe, "choice:KEY", "input:KEY"
const WIDTH = 40                     // Spalte, an der der Wert steht

const view = atom({ plugin: 'walkie', key: 'view' }, HOME)
const note = atom({ plugin: 'walkie', key: 'note' }, '')
const settings = atom({ plugin: 'walkie', key: 'settings' }, [] as Setting[], {
  shape: 'settings-1',
})

/** `walkie …` über den Starter des Plugins: findet die Python-Umgebung auf jedem System
 *  (bin/walkie unter Linux/macOS, bin/walkie.cmd unter Windows – dort gibt es kein python3). */
async function walkie($: EngineInterface, args: string[]) {
  const win = (await $.env.get('OS')) === 'Windows_NT'
  const argv = win
    ? ['cmd', '/c', `${$.plugin.root}\\bin\\walkie.cmd`, ...args]
    : ['sh', `${$.plugin.root}/bin/walkie`, ...args]
  return $.process.run(argv, { timeoutMs: 60_000 })
}

async function load($: EngineInterface) {
  const ran = await walkie($, ['list', '--json'])
  if (ran.exitCode !== 0) {
    await update($, note, () => `✗ Einstellungen nicht lesbar: ${(ran.stderr || ran.stdout).trim()}`)
    return
  }
  const data = JSON.parse(ran.stdout) as { settings: Setting[] }
  await update($, settings, () => data.settings.filter(s => s.type !== 'json'))
}

/** Ansicht wechseln und den Fokus auf deren erstes Element setzen. */
async function go($: EngineInterface, to: string, focus: string) {
  await update($, view, () => to)
  await $.ui.focus({ requestId: PANE, key: focus }).catch(() => undefined)
}

async function setValue($: EngineInterface, s: Setting, value: string) {
  const ran = await walkie($, ['set', s.key, value])
  if (ran.exitCode !== 0) {
    await update($, note, () => `✗ ${(ran.stderr || ran.stdout).replace(/^✗\s*/, '').trim()}`)
    return
  }
  await load($)
  await update($, note, () =>
    `✓ ${s.title}: ${shown({ ...s, value: s.type === 'bool' ? value === '1' : value })}` +
    (s.restart ? '  ·  wirkt nach „Walkie neu starten“' : ''),
  )
}

function shown(s: Setting): string {
  if (s.type === 'bool') return s.value ? 'an' : 'aus'
  if (s.value === '' || s.value === null || s.value === undefined) return 'Standard'
  return String(s.value)
}

const pad = (t: string) => (t.length >= WIDTH ? t.slice(0, WIDTH - 1) + '…' : t.padEnd(WIDTH, ' '))

/** Beim Sessionstart (aus main.tsx): Befehl /walkie anmelden. */
export async function menuStart($: EngineInterface) {
  await $.command.register({
    name: 'walkie',
    description: 'Einstellungen des Walkie (Menü: Pfeiltasten, Enter, Esc)',
  })
}

export const register: Register = on => {

  on('command.run', { command: 'walkie' }, async $ => {
    await update($, view, () => HOME)
    await update($, note, () => '')
    await load($)
    await $.ui.open({
      id: PANE, title: 'Walkie', focus: true, closeOnEscape: true, holdToasts: true,
      rows: 24,
    })
    return { text: 'Walkie-Einstellungen geöffnet.', isTextDisplayOnly: true }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Input } = $.ui.resolve(e)
    const cur = await read($, view)
    const msg = await read($, note)
    const all = await read($, settings)
    const groups = [...new Set(all.map(s => s.group))]

    const footer = (
      <Box flexDirection="column" marginTop={1}>
        {msg !== '' ? <Text>{msg}</Text> : null}
        <Text dimColor>↑↓ wählen · Enter öffnen/ändern · Esc schließen</Text>
      </Box>
    )
    const back = (to: string, focus: string) => (
      <Button key="back" plain dimColor onPress={() => go($, to, focus)}>
        ‹ Zurück
      </Button>
    )

    // ---- Startseite: Bereiche
    if (cur === HOME) {
      return (
        <Box flexDirection="column">
          {groups.length === 0 ? <Text dimColor>Lade Einstellungen …</Text> : null}
          {groups.map((g, i) => (
            <Button key={`g-${g}`} plain autoFocus={i === 0 ? true : undefined}
              onPress={() => go($, g, 'back')}>
              {pad(g)}<Text dimColor>›</Text>
            </Button>
          ))}
          <Box marginTop={1} flexDirection="column">
            <Button key="keys" plain dimColor onPress={async () => {
              await walkie($, ['gui'])
              await update($, note, () => '✓ Einstellungsfenster geöffnet (Kopfhörertasten, Figuren)')
            }}>
              Kopfhörertasten & Figuren (Fenster) …
            </Button>
            <Button key="restart" plain dimColor onPress={async () => {
              const ran = await walkie($, ['restart'])
              await update($, note, () =>
                ran.exitCode === 0 ? '✓ Walkie neu gestartet' : `✗ ${(ran.stderr || ran.stdout).trim()}`)
            }}>
              Walkie neu starten
            </Button>
          </Box>
          {footer}
        </Box>
      )
    }

    // ---- Auswahlliste für einen Wert
    if (cur.startsWith('choice:')) {
      const s = all.find(x => x.key === cur.slice(7))
      if (!s) return <Box>{back(HOME, `g-${groups[0] ?? ''}`)}</Box>
      return (
        <Box flexDirection="column">
          {back(s.group, `s-${s.key}`)}
          <Text bold>{s.title}</Text>
          {s.help ? <Text dimColor>{s.help}</Text> : null}
          {s.choices.map(c => (
            <Button key={`c-${c}`} plain autoFocus={c === String(s.value) ? true : undefined}
              onPress={async () => {
                await setValue($, s, c)
                await go($, s.group, `s-${s.key}`)
              }}>
              {c === String(s.value) ? '● ' : '  '}{c}
            </Button>
          ))}
          {footer}
        </Box>
      )
    }

    // ---- Eingabe für Zahl/Text
    if (cur.startsWith('input:')) {
      const s = all.find(x => x.key === cur.slice(6))
      if (!s) return <Box>{back(HOME, `g-${groups[0] ?? ''}`)}</Box>
      const range = s.min !== null && s.max !== null ? ` (${s.min}–${s.max})` : ''
      return (
        <Box flexDirection="column">
          {back(s.group, `s-${s.key}`)}
          <Text bold>{s.title}{range}</Text>
          {s.help ? <Text dimColor>{s.help}</Text> : null}
          <Input key={`i-${s.key}`} autoFocus
            value={s.value === null || s.value === undefined ? '' : String(s.value)}
            placeholder="leer = Standard" submitLabel="speichern"
            onSubmit={async v => {
              await setValue($, s, v.trim())
              await go($, s.group, `s-${s.key}`)
            }} />
          {footer}
        </Box>
      )
    }

    // ---- Einstellungen eines Bereichs
    const rows = all.filter(s => s.group === cur)
    return (
      <Box flexDirection="column">
        {back(HOME, `g-${cur}`)}
        <Text bold>{cur}</Text>
        {rows.map(s => (
          <Button key={`s-${s.key}`} plain onPress={async () => {
            if (s.type === 'bool') return setValue($, s, s.value ? '0' : '1')
            return go($, `${s.type === 'choice' ? 'choice' : 'input'}:${s.key}`,
              s.type === 'choice' ? `c-${String(s.value)}` : `i-${s.key}`)
          }}>
            {pad(s.title)}
            <Text color={s.type === 'bool' && s.value ? 'green' : undefined}
              dimColor={s.type === 'bool' && !s.value ? true : undefined}>{shown(s)}</Text>
            {s.restart ? <Text dimColor> ↻</Text> : null}
            {s.type !== 'bool' ? <Text dimColor> ›</Text> : null}
          </Button>
        ))}
        {footer}
      </Box>
    )
  })
}
