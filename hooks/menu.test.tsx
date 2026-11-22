import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'walkie',
  component: 'Pane',
  requestId: 'walkie-menu',
  props: {
    title: 'Walkie',
    isFocused: true,
    bodyColumns: 80,
    placement: 'inline',
    scroll: { offset: 0, bodyRows: 24 },
    view: {},
  },
} as const

const S = (key: string, type: string, value: unknown, group: string, title: string,
  extra: object = {}) => ({ key, type, value, default: value, group, title, help: '',
  choices: [], restart: false, min: null, max: null, ...extra })

test('Menü: Bereich öffnen, umschalten, auswählen, Zahl eingeben', async ($, on) => {
  let list = [
    S('WALKIE_ANNOUNCE', 'bool', true, 'Fragen & Freigaben', 'Ansagen'),
    S('WALKIE_SUMMARY_MODEL', 'choice', 'haiku', 'Sprache & Modelle', 'Modell',
      { choices: ['haiku', 'sonnet'] }),
    S('WALKIE_SCALE', 'int', 4, 'Figur', 'Größe', { min: 2, max: 8 }),
  ]
  const sets: string[][] = []
  const opened: object[] = []
  on('command.register', () => ({ value: { command: 'walkie' } }))
  on('ui.open', (_, e) => { opened.push(e); return { value: { isPlaced: true } } })
  on('ui.focus', () => ({}) as never)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'S1' }) as never)
  on('session.cwd', () => ({ value: '/p' }) as never)
  on('env.get', () => ({ value: undefined }) as never)
  on('fs.read', () => { throw new Error('keine App') })   // Brücke: App läuft nicht
  on('clock.every', () => ({ value: { cancel: () => undefined } }) as never)
  on('process.run', (_, e) => {
    const args = e.argv.slice(2)   // sh <root>/bin/walkie <args…>
    if (args[0] === 'list') {
      return { value: { exitCode: 0, stdout: JSON.stringify({ settings: list }), stderr: '' } as never }
    }
    sets.push(args)
    list = list.map(s => (s.key === args[1] ? { ...s, value:
      s.type === 'bool' ? args[2] === '1' : s.type === 'int' ? Number(args[2]) : args[2] } : s))
    return { value: { exitCode: 0, stdout: '✓\n', stderr: '' } as never }
  })

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'walkie', args: '' } as never)
  expect(opened[0]).toMatchObject({ focus: true, closeOnEscape: true, rows: 24 })

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const p = (key: string) => ui.press({ plugin: 'walkie', key })

  await p('g-Fragen & Freigaben')
  await p('s-WALKIE_ANNOUNCE')
  expect(sets).toContainEqual(['set', 'WALKIE_ANNOUNCE', '0'])
  expect((await ui.find({ type: 'Text', text: /✓ Ansagen/ }))?.text).toContain('aus')

  await p('back')
  await p('g-Sprache & Modelle')
  await p('s-WALKIE_SUMMARY_MODEL')
  await p('c-sonnet')
  expect(sets).toContainEqual(['set', 'WALKIE_SUMMARY_MODEL', 'sonnet'])

  await p('back')
  await p('g-Figur')
  await p('s-WALKIE_SCALE')
  await ui.input({ plugin: 'walkie', key: 'i-WALKIE_SCALE', text: '6' })
  expect(sets).toContainEqual(['set', 'WALKIE_SCALE', '6'])
  await ui.unmount()
})
