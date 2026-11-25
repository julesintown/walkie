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
let pollSince = 0                  // Beginn des laufenden Abrufs
let submitting = ''                // Nachricht, deren Zustellung gerade auf die Session wartet
let pollGen = 0
const POLL_STUCK_MS = 20_000       // länger hängt ein Abruf nur, wenn seine Anfrage nie beantwortet wird
let announcing = false
let announced = ''                 // Walkie (Adresse + Token), bei dem diese Session angemeldet ist

async function runDir($: EngineInterface): Promise<string> {
  const own = await $.env.get('WALKIE_RUN')
  if (own) return own
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE')) ?? ''
  const state = (await $.env.get('XDG_STATE_HOME')) || `${home}/.local/state`
  return `${state}/walkie`
}

let windowsRun: Promise<string[]> | undefined

const NOT_PEOPLE = new Set(['all users', 'default', 'default user', 'public', 'desktop.ini'])

/** Nur unter WSL: Statusordner, in denen ein Walkie auf Windows seine server.json ablegt
 *  (C:\Users\<du>\.local\state\walkie, als /mnt/c/Users/<du>/…). WALKIE_WINDOWS_RUN
 *  überschreibt die Suche. Direkt im Dateisystem gesucht, ohne cmd.exe: Claude-Prozessen aus
 *  einem xrdp-Desktop fehlt die WSL-Interop, dort scheiterte cmd.exe still. Einmal pro
 *  Session. Erreichbar ist dieser Walkie aus WSL nur mit networkingMode=mirrored. */
async function windowsRunDirs($: EngineInterface): Promise<string[]> {
  const own = await $.env.get('WALKIE_WINDOWS_RUN')
  if (own) return [own]
  windowsRun ??= (async () => {
    try {
      // WSL: Variable der WSL-Shell (fehlt z. B. im xrdp-Desktop) oder Kennung des WSL-Kernels.
      // Auf macOS/Windows gibt es die Datei nicht -> kein WSL, nichts weiter.
      const wsl = Boolean(await $.env.get('WSL_DISTRO_NAME')) ||
        /microsoft/i.test(await $.fs.read('/proc/sys/kernel/osrelease').catch(() => ''))
      if (!wsl) return []
      const entries = (await $.fs.list('/mnt/c/Users')) as unknown[]
      return entries
        .map(e => (typeof e === 'string' ? e : String((e as { name?: unknown })?.name ?? '')))
        .map(name => name.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? '')
        .filter(name => name && !NOT_PEOPLE.has(name.toLowerCase()))
        .map(name => `/mnt/c/Users/${name}/.local/state/walkie`)
    } catch {
      return []
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
  } catch (error) {
    lastReadError = `${dir}: ${String((error as Error)?.message ?? error).slice(0, 120)}`
    return undefined
  }
}

/** Adresse der laufenden App – undefined, wenn sie nicht läuft. Unter WSL ohne eigenen Walkie
 *  auch der Walkie auf Windows; überall sonst nur der eigene Statusordner. */
async function server($: EngineInterface): Promise<Server | undefined> {
  const own = await readServer($, await runDir($))
  if (own) return own
  for (const dir of await windowsRunDirs($)) {
    const s = await readServer($, dir, true)
    if (s) return s
  }
  return undefined
}

const CALL_TIMEOUT_MS = 5000

/** Wartet ms, dann TIMEOUT. Lehnt die Engine die Uhr ab (Tests), wartet es nie. */
const TIMEOUT = Symbol('timeout')
function after($: EngineInterface, ms: number): Promise<typeof TIMEOUT> {
  try {
    return $.clock.sleep(ms).then(() => TIMEOUT, () => new Promise<never>(() => undefined))
  } catch {
    return new Promise<never>(() => undefined)
  }
}

async function call($: EngineInterface, path: string, body?: unknown) {
  const s = await server($)
  if (!s) return undefined
  try {
    const request = $.http.fetch(`${s.url}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'x-walkie-token': s.token, 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    // /ask wartet absichtlich lange auf die gesprochene Antwort. Alles andere ist kurz: Ohne
    // Grenze hing eine Anfrage an einen gerade beendeten Walkie für immer – und mit ihr der
    // Sessionstart oder das Postfach.
    const r = path.startsWith('/ask') ? await request
      : await Promise.race([request, after($, CALL_TIMEOUT_MS)])
    if (r === TIMEOUT) return undefined
    return r.ok ? (JSON.parse(r.text || 'null') as unknown) : undefined
  } catch {
    return undefined                          // App gerade nicht erreichbar -> egal
  }
}

async function emit($: EngineInterface, event: string, extra: Record<string, unknown> = {}) {
  if (!sid) return
  if (!announcing) await ensureAnnounced($)
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

/** Session beim laufenden Walkie anmelden. Auch nachträglich: Startet der Walkie erst nach der
 *  Session (oder neu), kennt er sie sonst erst bei ihrer nächsten Aktion. */
async function announce($: EngineInterface, s: Server) {
  announcing = true
  try {
    // Walkie auf Windows: Linux-PIDs sagen ihm nichts (er sucht das Fenster dann über den Titel)
    const pid = s.windows ? undefined : await ownPid($)
    if (await emit($, 'ready', { cwd, pid }) === undefined) return
    announced = `${s.url} ${s.token}`
    if (turnStart) await emit($, 'tool')      // mitten in einer Runde: „denkt“, nicht „bereit“
  } finally {
    announcing = false
  }
}

/** Vor jeder Meldung und jedem Abruf: Kennt der laufende Walkie diese Session schon? */
async function ensureAnnounced($: EngineInterface) {
  const s = await server($)
  if (s && `${s.url} ${s.token}` !== announced) await announce($, s)
}

async function pollInbox($: EngineInterface) {
  // Eine Zustellung wartet absichtlich, bis die Session frei ist (Minuten, wenn sie arbeitet).
  // Solange nichts abholen: Der Hänger-Schutz unten hielt das für hängend und stellte dieselbe
  // Nachricht alle 20 s erneut zu (13-mal in einer langen Runde).
  if (!sid || Date.now() < retryAt || submitting) return
  // Eine Anfrage, die nie beantwortet wird (Walkie mitten im Beenden), hielt `polling` für immer
  // fest: Die Session holte danach nichts mehr ab, gesprochene Sätze blieben im Walkie liegen.
  if (polling && Date.now() - pollSince < POLL_STUCK_MS) return
  polling = true
  pollSince = Date.now()
  const gen = ++pollGen
  try {
    // angemeldet, aber im Takt kein Walkie zu finden: sichtbar machen statt still nichts abholen
    if (announced && !(await server($))) reportPollError($, new Error(`kein Walkie gefunden (${lastReadError})`))
    await ensureAnnounced($)
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
        submitting = item.id
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
        } finally {
          submitting = ''
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
    if (gen === pollGen) polling = false   // ein spät endender, hängender Abruf gibt nichts frei
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

let pollErrorShown = false
let lastReadError = ''

/** Scheitert der Postfach-Abruf, kommen gesprochene Sätze nie an – und das merkte bisher
 *  niemand. Den ersten Fehler einmal zeigen, damit er sich finden lässt. */
function reportPollError($: EngineInterface, error: unknown) {
  if (pollErrorShown) return
  pollErrorShown = true
  try {
    $.ui.toast(`🎧 Walkie: Postfach-Abruf gescheitert – ${String((error as Error)?.message ?? error).slice(0, 160)}`,
      { timeoutMs: 30_000 })
  } catch {
    // Hinweis nicht möglich -> nichts weiter
  }
}

/** Beim Sessionstart (aus main.tsx): Session anmelden und das Postfach abfragen. */
export async function sessionStart($: EngineInterface, interactive: boolean) {
  // Nur echte, interaktive Sessions anmelden – nicht `claude -p` und nicht die Hilfsabfragen,
  // die der Walkie selbst startet (dort ist WALKIE_SESSION gesetzt). Sonst kennt er „Sessions“,
  // die nach Sekunden wieder weg sind.
  sid = ''
  windowsRun = undefined
  lateStart = true                   // Start gesehen: nichts nachholen (auch nicht bei claude -p)
  if (await $.env.get('WALKIE_SESSION')) return
  const own = await $.session.id()
  if (!interactive && !(await desktopSession($, own))) return
  await setupHint($).catch(() => undefined)
  sid = own
  cwd = await $.session.cwd()
  const home = (await $.env.get('HOME')) ?? (await $.env.get('USERPROFILE')) ?? ''
  const trimmed = cwd.replace(/[\\/]+$/, '')
  project = trimmed === home.replace(/[\\/]+$/, '')
    ? 'Home'
    : trimmed.split(/[\\/]/).pop() || cwd
  announced = ''
  // Erst den Takt, dann anmelden: Der Takt meldet die Session auch später noch an (Walkie startet
  // erst danach), die Anmeldung selbst darf ihn nie aufhalten.
  poller?.cancel()
  poller = $.clock.every(500, () => void pollInbox($).catch(error => reportPollError($, error)))
  await ensureAnnounced($)
}

let lateStart = false

/** Session im Code-Tab der Claude-Desktop-App? Die App startet Claude Code über das SDK, die
 *  Engine meldet sie darum als nicht interaktiv – obwohl jemand davorsitzt. Ein `claude -p`,
 *  das so eine Session selbst startet, erbt ihre Variablen, trägt aber die Session-ID der
 *  Elternsession: Nur die Session selbst zählt. */
async function desktopSession($: EngineInterface, own: string): Promise<boolean> {
  if ((await $.env.get('CLAUDE_CODE_ENTRYPOINT')) !== 'claude-desktop') return false
  const parent = await $.env.get('CLAUDE_CODE_SESSION_ID')
  return !parent || parent === own
}

/** Nach /reload-plugins läuft das Plugin als neue Instanz, ohne dass die Engine noch einmal
 *  session.start meldet: Es kannte seine Session nicht und blieb ganz stumm (keine Ereignisse,
 *  kein Postfach). Dann beim ersten Hook einmal nachholen. Nur, wenn die Session schon einen
 *  Prompt hatte (interaktiv) – Hilfsabfragen des Walkies schließt sessionStart selbst aus. */
async function ensureStarted($: EngineInterface) {
  if (sid || lateStart) return
  await sessionStart($, true)
  if (sid) $.ui.toast('🎧 Walkie: Session nach dem Neuladen wieder angemeldet', { timeoutMs: 8000 })
}

export const register: Register = on => {

  on('prompt.submit', async ($, e, next) => {
    await ensureStarted($).catch(() => undefined)
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
    await ensureStarted($).catch(() => undefined)
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
