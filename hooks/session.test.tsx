import { expect, test } from 'claude-code/testing'
import { confirmDelivery, submitVoice } from './session'

type Fetch = { url: string; init?: { method?: string; body?: string } }

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function engine(on: (...args: any[]) => unknown, answers: Record<string, unknown>) {
  const fetched: Fetch[] = []
  on('command.register', () => ({ value: { command: 'walkie' } }))
  on('session.start', (_: unknown, e: { cwd: string }) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'S1' }) as never)
  on('session.cwd', () => ({ value: '/home/x/shop' }) as never)
  on('env.get', () => ({ value: undefined }) as never)
  on('clock.every', () => ({ value: { cancel: () => undefined } }) as never)
  on('classic.PermissionRequest', () => ({}) as never)   // Engine: kein Hook entscheidet
  on('fs.read', () => ({ value: JSON.stringify({ port: 4711, token: 't0k' }) }) as never)
  on('http.fetch', (_: unknown, e: unknown) => {
    const f = e as unknown as Fetch
    fetched.push(f)
    const path = new URL(f.url).pathname
    return { value: { ok: true, status: 200, headers: {}, text: JSON.stringify(answers[path] ?? {}) } } as never
  })
  return fetched
}

const bodies = (fetched: Fetch[], path: string) =>
  fetched.filter(f => f.url.endsWith(path)).map(f => JSON.parse(f.init?.body ?? '{}'))

test('meldet den Start der Session an die App', async ($, on) => {
  const fetched = engine(on, {})
  await $.session.start({ cwd: '/home/x/shop', surface: 'terminal', isInteractive: true })
  const ready = bodies(fetched, '/event')[0]
  expect(ready).toMatchObject({ event: 'ready', session: 'S1', project: 'shop' })
  expect(fetched[0]?.url).toBe('http://127.0.0.1:4711/event')

  // turn.complete kann die Test-Umgebung nicht auslösen – live geprüft
})

test('Freigabe per Stimme: allow mit updatedInput, sonst normaler Dialog', async ($, on) => {
  const answers: Record<string, unknown> = { '/ask': { behavior: 'allow' } }
  const fetched = engine(on, answers)
  await $.session.start({ cwd: '/home/x/shop', surface: 'terminal', isInteractive: true })

  const input = { command: 'npm test', description: 'Tests ausführen' }
  const r = await $.classic.PermissionRequest({ tool_name: 'Bash', tool_input: input } as never)
  expect(r).toMatchObject({ decision: { behavior: 'allow', updatedInput: input } })
  expect(bodies(fetched, '/ask')[0]).toMatchObject({ tool: 'Bash', detail: 'Tests ausführen', project: 'shop' })

  answers['/ask'] = { behavior: 'deny', message: 'Per Sprache abgelehnt: „nein“' }
  const d = await $.classic.PermissionRequest({ tool_name: 'Bash', tool_input: input } as never)
  expect(d).toMatchObject({ decision: { behavior: 'deny' } })

  answers['/ask'] = { behavior: 'pass' }
  const p = await $.classic.PermissionRequest({ tool_name: 'Bash', tool_input: input } as never)
  expect((p as { decision?: unknown } | undefined)?.decision).toBeUndefined()
})

test('Rückfrage zuerst per Stimme: Antwort ersetzt den Dialog, sonst geht er normal auf', async ($, on) => {
  let dialogs = 0
  on('tool.call', () => { dialogs++; return { result: { questions: [], answers: {} } } as never })
  on('ui.toast', () => ({ value: undefined }) as never)
  const fetched = engine(on, { '/ask': { behavior: 'allow', answers: { 'Welche Farbe?': 'Blau' } } })
  await $.session.start({ cwd: '/home/x/shop', surface: 'terminal', isInteractive: true })
  const questions = [{ question: 'Welche Farbe?', header: 'Farbe', multiSelect: false,
    options: [{ label: 'Rot', description: '' }, { label: 'Blau', description: '' }] }]
  const r = await $.tool.call({ tool: 'AskUserQuestion', questions } as never)
  expect(r).toMatchObject({ result: { answers: { 'Welche Farbe?': 'Blau' } } })
  expect(dialogs).toBe(0)
  const sent = bodies(fetched, '/ask')[0]
  expect(sent.first).toBe(true)
  expect(sent.questions).toEqual([{ question: 'Welche Farbe?', options: ['Rot', 'Blau'], multi: false }])
  // Freigabe-Weg fragt Rückfragen nicht ein zweites Mal
  const p = await $.classic.PermissionRequest({ tool_name: 'AskUserQuestion', tool_input: {} } as never)
  expect(p).toEqual({})
})

test('nicht-interaktive Sessions (claude -p, Hilfsabfragen) werden nicht gemeldet', async ($, on) => {
  const fetched = engine(on, {})
  await $.session.start({ cwd: '/home/x/shop', surface: 'terminal', isInteractive: false })
  expect(bodies(fetched, '/event')).toEqual([])
})

test('Plugin da, App nie eingerichtet: Hinweis auf /walkie:start, höchstens dreimal', async ($, on) => {
  on('command.register', () => ({ value: { command: 'walkie' } }))
  on('session.start', (_: unknown, e: { cwd: string }) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'S1' }) as never)
  on('session.cwd', () => ({ value: '/home/x/shop' }) as never)
  on('env.get', () => ({ value: undefined }) as never)
  on('clock.every', () => ({ value: { cancel: () => undefined } }) as never)
  const toasts: string[] = []
  const store: Record<string, unknown> = {}
  on('fs.read', () => { throw new Error('ENOENT') })
  on('store.get', (_: unknown, e: { key: string }) => ({ value: store[e.key] }) as never)
  on('store.set', (_: unknown, e: { key: string; value: unknown }) => {
    store[e.key] = e.value
    return { value: undefined } as never
  })
  on('ui.toast', (_: unknown, e: { text: string }) => {
    toasts.push(e.text)
    return { value: undefined } as never
  })
  for (let i = 0; i < 4; i++) {
    await $.session.start({ cwd: '/home/x/shop', surface: 'terminal', isInteractive: true })
  }
  expect(toasts.length).toBe(3)
  expect(toasts[0]).toContain('/walkie:start')
})

test('Fertig-Meldung bringt die Dauer der Runde mit (übersteht Neustarts des Walkies)', async ($, on) => {
  const fetched = engine(on, {})
  on('prompt.submit', (_: unknown, e: { text: string }) => ({ text: e.text }) as never)
  on('turn.complete', () => ({ text: '' }) as never)
  await $.session.start({ cwd: '/home/x/shop', surface: 'terminal', isInteractive: true })
  await $.prompt.submit({ text: 'Mach die Tests grün', origin: { kind: 'user' } } as never)
  await $.prompt.submit({ text: 'nachgetippt', origin: { kind: 'user' } } as never)
  await $.turn.complete({ answer: 'Fertig.', reason: 'end_turn' } as never)
  const stop = bodies(fetched, '/event').find(b => b.event === 'stop')
  expect(typeof stop.worked).toBe('number')
  expect(bodies(fetched, '/event').filter(b => b.event === 'prompt').length).toBe(2)
})

test('ein fehlgeschlagener Submit bleibt offen, ein verlorenes Ack wiederholt nur das Ack', async () => {
  let attempts = 0
  let acks = 0
  let saved = ''
  const id = 'retry-1'
  const poll = () => confirmDelivery(id, saved, async () => {
    attempts++
    if (attempts === 1) throw new Error('Terminal belegt')
  }, async () => { saved = id }, async () => {
    acks++
    if (acks === 1) throw new Error('Verbindung unterbrochen')
  })
  await poll().catch(() => undefined)
  expect(saved).toBe('')
  expect(acks).toBe(0)
  await poll().catch(() => undefined)
  await poll()
  expect(attempts).toBe(2)
  expect(acks).toBe(2)
})

test('ein von der Engine abgelehnter Prompt gilt nicht als zugestellt', async ($, on) => {
  let answer: unknown = { drop: 'Stop hook' }
  on('prompt.submit', () => answer as never)
  let failed = false
  try {
    await submitVoice($, 'Hallo')
  } catch {
    failed = true
  }
  expect(failed).toBe(true)
  answer = { text: 'Hallo' }
  await submitVoice($, 'Hallo')
})
