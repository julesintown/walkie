// Walkie – Brücke zwischen dieser Claude-Code-Session und der Walkie-App.
// Läuft in jeder Session, ohne Python, auf Linux, macOS und Windows gleich. Spricht mit der
// App über ihren lokalen HTTP-Dienst (127.0.0.1, Port + Token in RUN/server.json):
//  - POST /event   Zustand: bereit, denkt, fertig (+ Antworttext, ob Frage), Fehler, beendet
//  - GET  /inbox   gesprochene Sätze für diese Session -> $.prompt.submit (wartet bis frei)
//  - POST /ask     Freigabe/Rückfrage: wartet auf die gesprochene Antwort, während der normale
//                  Dialog parallel offen ist (wer zuerst antwortet, gewinnt)
// Läuft die App nicht, tut der Mod nichts (keine Fehler, keine Wartezeit).
// RUN = $WALKIE_RUN oder ($XDG_STATE_HOME | ~/.local/state)/walkie – wie in hook.py.
import type { EngineInterface, Register } from 'claude-code'

const VOICE_CONTEXT =
  'The user spoke this message through a headset; the Walkie transcribed it (speech ' +
  'recognition can mishear words: interpret unclear words sensibly). Your answer will be read ' +
  'aloud. Choose the length by what is useful to hear: if the user asks for content (ideas, ' +
  'an explanation, facts, a recommendation), give that content completely but in a form that ' +
  'is pleasant to listen to; for status updates and confirmations, be brief. Answer in the ' +
  "user's language, without markdown unless code is requested."

type Server = { url: string; token: string; windows?: boolean }   // windows: Walkie auf Windows, Session in WSL

let receipt = ''
let delayed = ''
let retryAt = 0                    // nach einer abgelehnten Zustellung kurz warten
let sid = ''
let project = ''
let cwd = ''
let replyLanguage = ''
let voiceTurn = false              // die laufende Runde kam per Sprache -> Antwort vorlesen
let turnStart = 0                  // Beginn der laufenden Runde (0 = keine läuft)
let lastTool = 0
let poller: { cancel: () => void } | undefined
let polling = false

async function runDir($: EngineInterface): Promise<string> {
  const own = await $.env.get('WALKIE_RUN')
  if (own) return own
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE')) ?? ''
  const state = (await $.env.get('XDG_STATE_HOME')) || `${home}/.local/state`
  return `${state}/walkie`
}

let windowsRun: Promise<string | undefined> | undefined

/** Nur unter WSL: Statusordner eines Walkies, der auf Windows läuft
 *  (C:\Users\<du>\.local\state\walkie, als /mnt/c/…). WALKIE_WINDOWS_RUN überschreibt die
 *  Suche. Wird einmal pro Session ermittelt. Erreichbar ist dieser Walkie aus WSL nur mit
 *  networkingMode=mirrored in der .wslconfig (sonst ist 127.0.0.1 nicht der Windows-Rechner). */
async function windowsRunDir($: EngineInterface): Promise<string | undefined> {
  const own = await $.env.get('WALKIE_WINDOWS_RUN')
  if (own) return own
  windowsRun ??= (async () => {
    try {
      // WSL: Variable der WSL-Shell (fehlt z. B. im xrdp-Desktop) oder Kennung des WSL-Kernels.
      // Auf macOS/Windows gibt es die Datei nicht -> kein WSL, nichts weiter.
      const wsl = Boolean(await $.env.get('WSL_DISTRO_NAME')) ||
        /microsoft/i.test(await $.fs.read('/proc/sys/kernel/osrelease').catch(() => ''))
      if (!wsl) return undefined
      // cmd.exe liegt nicht immer im PATH (appendWindowsPath=false)
      const r = await $.process.run(['sh', '-c',
        'p=$( (cmd.exe /c "echo %USERPROFILE%" || /mnt/c/Windows/System32/cmd.exe /c "echo %USERPROFILE%")' +
        ' 2>/dev/null | tr -d "\\r"); [ -n "$p" ] && wslpath -u "$p"'], { timeoutMs: 8000 })
      const home = r.stdout.trim()
      return home ? `${home}/.local/state/walkie` : undefined
    } catch {
      return undefined
    }
  })()
  return windowsRun
}

async function readServer($: EngineInterface, dir: string | undefined,
  windows = false): Promise<Server | undefined> {
  if (!dir) return undefined
  try {
    const s = JSON.parse(await $.fs.read(`${dir}/server.json`)) as { port: number; token: string }
    return { url: `http://127.0.0.1:${s.port}`, token: s.token, windows }
  } catch {
    return undefined
  }
}

/** Adresse der laufenden App – undefined, wenn sie nicht läuft. Unter WSL ohne eigenen Walkie
 *  auch der Walkie auf Windows; überall sonst nur der eigene Statusordner. */
async function server($: EngineInterface): Promise<Server | undefined> {
  return (await readServer($, await runDir($))) ?? (await readServer($, await windowsRunDir($), true))
}

async function call($: EngineInterface, path: string, body?: unknown) {
  const s = await server($)
  if (!s) return undefined
  try {
    const r = await $.http.fetch(`${s.url}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'x-walkie-token': s.token, 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    return r.ok ? (JSON.parse(r.text || 'null') as unknown) : undefined
  } catch {
    return undefined                          // App gerade nicht erreichbar -> egal
  }
}

async function emit($: EngineInterface, event: string, extra: Record<string, unknown> = {}) {
  if (!sid) return
  return call($, '/event', { event, ts: Date.now() / 1000, agent: 'claude', own: false,
    session: sid, project, ...extra })
}

// Keep the in-process receipt even if writing the persistent receipt or the HTTP ack fails.
export async function confirmDelivery(id: string, saved: unknown, submit: () => Promise<void>,
  remember: () => Promise<void>, acknowledge: () => Promise<void>) {
  if (receipt !== id && saved !== id) {
    await submit()
    receipt = id
  }
  await remember()
  await acknowledge()
}

// submit() resolves with { drop } when the engine refuses the prompt. That is no delivery:
// the caller keeps the dictation in the Walkie and tries again on a later poll.
export function checkVoiceSubmission(res: Awaited<ReturnType<EngineInterface['prompt']['submit']>>) {
  if (res?.drop !== undefined) throw new Error(`prompt dropped: ${res.drop}`)
}

async function pollInbox($: EngineInterface) {
  if (!sid || polling || Date.now() < retryAt) return
  polling = true
  try {
    const q = `session=${encodeURIComponent(sid)}&project=${encodeURIComponent(project)}` +
      `&cwd=${encodeURIComponent(cwd)}`
    const session = sid
    const got = (await call($, `/inbox?${q}&ack=1`)) as
      | { message?: { id: string; text: string }; texts?: string[]; reply_language?: string }
      | undefined
    if (session !== sid) return
    replyLanguage = got?.reply_language ?? ''
    const item = got?.message
    if (item) {
      const key = `last-delivery-${session}`
      await confirmDelivery(item.id, await $.store.get(key), async () => {
        const previous = voiceTurn
        voiceTurn = true
        try {
          checkVoiceSubmission(await $.prompt.submit({ text: item.text }))
        } catch (error) {
          voiceTurn = previous
          retryAt = Date.now() + 3000
          if (delayed !== item.id) {
            const sent = await emit($, 'delivery_delayed')
            if (sent) delayed = item.id
          }
          throw error
        }
      }, async () => { await $.store.set(key, item.id) },
      async () => { await call($, '/ack', { session, id: item.id }) })
    }
    // Older desktop installations return plain texts.
    for (const text of got?.texts ?? []) {
      voiceTurn = true
      await $.prompt.submit({ text })
    }
  } finally {
    polling = false
  }
}

/** Kurzbeschreibung einer Freigabe zum Vorlesen (wie hook.detail). */
function detail(tool: string, input: unknown): string {
  if (!input || typeof input !== 'object') return ''
  const inp = input as Record<string, unknown>
  if (tool === 'AskUserQuestion') {
    const qs = (inp.questions as { question?: string }[] | undefined) ?? []
    return qs.map(q => q.question ?? '').join(' ').trim().slice(0, 200)
  }
  const fp = typeof inp.file_path === 'string' ? inp.file_path.split(/[\\/]/).pop() : undefined
  const text = inp.description ?? inp.command ?? fp ?? inp.url ?? ''
  return String(text).trim().slice(0, 200)
}

function questions(input: unknown) {
  const qs = ((input as { questions?: unknown[] } | undefined)?.questions ?? []) as {
    question?: string
    options?: { label?: string }[]
    multiSelect?: boolean
  }[]
  return qs
    .filter(q => q.question)
    .map(q => ({
      question: String(q.question),
      options: (q.options ?? []).map(o => String(o.label ?? '')).filter(Boolean),
      multi: Boolean(q.multiSelect),
    }))
}

/** PID des Claude-Code-Prozesses dieser Session (Elternprozess der kleinen Shell), damit der
 *  Walkie ihr Fenster findet und nach vorne holen kann. */
async function ownPid($: EngineInterface): Promise<number | undefined> {
  try {
    const win = (await $.env.get('OS')) === 'Windows_NT'
    const r = win
      ? await $.process.run(['powershell', '-NoProfile', '-Command',
        '(Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId'], { timeoutMs: 8000 })
      : await $.process.run(['sh', '-c', 'echo $PPID'], { timeoutMs: 3000 })
    const pid = Number(r.stdout.trim())
    return Number.isFinite(pid) && pid > 1 ? pid : undefined
  } catch {
    return undefined
  }
}

const SETUP_HINTS = 3                // so oft höchstens erinnern, solange nichts eingerichtet ist

/** Plugin installiert, Desktop-App aber nie gestartet (kein RUN/install): kurz zeigen, wie es
 *  weitergeht – höchstens SETUP_HINTS Mal, damit niemand genervt wird. */
async function setupHint($: EngineInterface) {
  if (await server($)) return
  try {
    await $.fs.read(`${await runDir($)}/install`)
    return                                    // war schon einmal eingerichtet
  } catch {
    // noch nie gestartet
  }
  const shown = Number((await $.store.get('setupHints')) ?? 0)
  if (shown >= SETUP_HINTS) return
  await $.store.set('setupHints', shown + 1)
  $.ui.toast('🎧 Walkie ist installiert – /walkie:start richtet ihn ein (1–3 Min.)',
    { timeoutMs: 12_000 })
}

/** Beim Sessionstart (aus main.tsx): Session anmelden und das Postfach abfragen. */
export async function sessionStart($: EngineInterface, interactive: boolean) {
  // Nur echte, interaktive Sessions anmelden – nicht `claude -p` und nicht die Hilfsabfragen,
  // die der Walkie selbst startet (dort ist WALKIE_SESSION gesetzt). Sonst kennt er „Sessions“,
  // die nach Sekunden wieder weg sind.
  sid = ''
  windowsRun = undefined
  if (!interactive || (await $.env.get('WALKIE_SESSION'))) return
  await setupHint($).catch(() => undefined)
  sid = await $.session.id()
  cwd = await $.session.cwd()
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE')) ?? ''
  const trimmed = cwd.replace(/[\\/]+$/, '')
  project = trimmed === home.replace(/[\\/]+$/, '')
    ? 'Home'
    : trimmed.split(/[\\/]/).pop() || cwd
  // Walkie auf Windows: Linux-PIDs sagen ihm nichts (er sucht das Fenster dann über den Titel)
  const pid = (await server($))?.windows ? undefined : await ownPid($)
  await emit($, 'ready', { cwd, pid })
  poller?.cancel()
  poller = $.clock.every(500, () => void pollInbox($).catch(() => undefined))
}

export const register: Register = on => {

  on('prompt.submit', async ($, e, next) => {
    const ours = e.origin?.kind === 'plugin' && voiceTurn
    // gesprochene Sätze bekommen den Hinweis für Claude (nur das Modell liest ihn)
    const res = await next(ours ? { ...e, context: [...(e.context ?? []), VOICE_CONTEXT + (replyLanguage ? ` Reply language: ${replyLanguage}.` : '')] } : e)
    const running = turnStart > 0
    if (!running) turnStart = Date.now()
    if (ours) {
      await emit($, 'prompt', { voice: true, prompt: e.text.slice(0, 300) })
    } else {
      // getippt -> Antwort nicht vorlesen; eine getippte Nachricht MITTEN in einer gesprochenen
      // Runde ändert das nicht (man tippt etwas nach, hört die Antwort aber trotzdem)
      if (!running) voiceTurn = false
      await emit($, 'prompt', { prompt: e.text.slice(0, 300) })
    }
    return res
  })

  on('tool.call', async ($, e, next) => {
    const now = Date.now()
    if (now - lastTool > 5000) {             // „denkt noch“ – höchstens alle 5 s melden
      lastTool = now
      void emit($, 'tool')
    }
    // Rückfragen zuerst per Stimme: der Walkie liest sie vor und hört zu; antwortest du, ist die
    // Frage erledigt, sonst geht der Dialog ganz normal auf. Dieser Weg liegt vor jeder
    // Freigabe-Prüfung – er funktioniert auch, wenn ein anderes Plugin Freigaben selbst entscheidet.
    if (e.tool === 'AskUserQuestion' && sid && (await server($))) {
      const input = e as unknown as { questions?: unknown[] }   // Felder liegen direkt im Ereignis
      $.ui.toast('🎧 Walkie liest die Frage vor – antworte laut oder warte auf den Dialog')
      const answer = (await call($, '/ask', {
        session: sid, project, tool: 'AskUserQuestion', first: true,
        detail: detail('AskUserQuestion', input),
        questions: questions(input),
      })) as { behavior?: string; answers?: Record<string, string> } | undefined
      if (answer?.behavior === 'allow' && answer.answers && Object.keys(answer.answers).length) {
        return { result: { questions: input.questions ?? [], answers: answer.answers } } as never
      }
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const res = await next(e)
    if (e.agentId) return res                 // Subagent – nicht die Hauptantwort
    if (e.reason === 'error') {
      await emit($, 'error', { reason: 'Fehler' })
    } else if (!e.isAborted) {
      const text = e.answer ?? ''
      // Dauer mitschicken: so weiß der Walkie auch nach einem Neustart, ob „fertig“ sich lohnt
      const worked = turnStart ? (Date.now() - turnStart) / 1000 : 0
      await emit($, 'stop', { text, voice: voiceTurn, question: endsWithQuestion(text), worked })
    }
    voiceTurn = false
    turnStart = 0
    return res
  })

  // Freigaben und Rückfragen (AskUserQuestion): parallel zum Dialog per Stimme beantworten.
  on('classic.PermissionRequest', async ($, e, next) => {
    if (!sid || !(await server($))) return next(e)
    const tool = e.tool_name
    if (tool === 'AskUserQuestion') return next(e)   // schon vorher per Stimme gefragt (tool.call)
    const answer = (await call($, '/ask', {
      session: sid, project, tool,
      detail: detail(tool, e.tool_input),
      // der Befehl selbst (detail ist oft nur Claudes Beschreibung) – für die Risiko-Prüfung
      command: tool === 'Bash' ? String((e.tool_input as { command?: unknown })?.command ?? '').slice(0, 500) : '',
      questions: tool === 'AskUserQuestion' ? questions(e.tool_input) : [],
    })) as { behavior?: string; message?: string; answers?: Record<string, string> } | undefined
    if (answer?.behavior === 'allow') {
      // updatedInput immer mitschicken – ohne wertet Claude Code manche Tools als Ablehnung
      const input = { ...((e.tool_input as Record<string, unknown>) ?? {}) }
      if (answer.answers) input.answers = answer.answers
      return { decision: { behavior: 'allow', updatedInput: input } }
    }
    if (answer?.behavior === 'deny') {
      return { decision: { behavior: 'deny', message: answer.message ?? 'Per Sprache abgelehnt.' } }
    }
    return next(e)                            // keine Antwort -> Claude fragt ganz normal
  })

  on('session.end', async ($, e, next) => {
    poller?.cancel()
    await emit($, 'end')
    return next(e)
  })
}

/** Endet die Antwort mit einer Frage an den Nutzer? (letzter Absatz mit '?') */
export function endsWithQuestion(text: string): boolean {
  const plain = text.replace(/```[\s\S]*?```/g, ' ').trim()
  if (!plain) return false
  const last = plain.split(/\n\s*\n/).pop() ?? ''
  return last.slice(-400).includes('?')
}
