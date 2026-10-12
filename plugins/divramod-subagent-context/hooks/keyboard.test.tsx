import type { On } from 'claude-code'
import { type Engine, expect, mock, test } from 'claude-code/testing'

import { MARKER, appended, idle, logLine, unfocused } from './keyboard'
import { PANE, steps } from './testkit'

// The pane and the keyboard (plan 0233 D3, D6): it never opens by itself, only the person's opens ask for the
// keyboard, a plugin's focus move is refused, every move is logged, a marker shows the hold, an idle hold ends.

const ID = 'subagent-context'
const pane = (isFocused: boolean) => [{ id: ID, title: 't', isShown: true, isFocused, isPlaced: true }]

// A session that starts: the engine's answers the start needs, the opens, closes and the files it writes.
const session = ($: Engine, on: On, up: () => readonly ReturnType<typeof pane>[number][] = () => []) => {
  const opens: { rows?: number; focus?: true }[] = []
  const closes: string[] = []
  const files: Record<string, string> = {}
  const clock = mock.clock(on)
  mock.env(on, { HOME: '/h' })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: { context: { window: 1_000_000 } } as never }))
  on('command.register', () => ({ value: undefined as never }))
  on('session.id', () => ({ value: 'S1' }))
  on('ui.status', () => ({ value: undefined }))
  on('agent.list', () => ({ value: [] }))
  on('fs.list', () => ({ value: [] }))
  on('fs.read', (_$, e) => {
    if (!(e.path in files)) throw new Error(`ENOENT ${e.path}`)
    return { value: files[e.path]! }
  })
  on('fs.write', (_$, e) => {
    files[e.path] = e.text
    return { value: undefined }
  })
  on('ui.panes', () => ({ value: up() }))
  on('ui.open', (_$, e) => {
    opens.push({ rows: e.rows, ...(e.focus ? { focus: e.focus } : {}) })
    return { value: { isPlaced: true } }
  })
  on('ui.close', (_$, e) => {
    closes.push(e.id)
    return { value: undefined }
  })
  const start = () => $.session.start({ cwd: '/w', surface: 'terminal', isInteractive: true })
  const log = () => (files['/h/.claude/divramod-subagent-context/focus.log'] ?? '').split('\n').filter(Boolean)
  return { opens, closes, files, clock, start, log }
}

test('a session start, a reload and a subagent start open nothing', async ($, on) => {
  const { opens, clock, start } = session($, on)
  on('classic.SubagentStart', () => ({}))
  await start()
  // A reload (`/reload-plugins`) raises the start of the reloaded module again.
  await start()
  await clock.settle()
  await $.classic.SubagentStart({ agent_id: 'delta', agent_type: 'general-purpose' } as never)
  await clock.advance(30_000)
  expect(opens).toEqual([])
})

test('a subagent start with the pane open asks for its rows only, never for the keyboard', async ($, on) => {
  const { opens, start } = session($, on, () => pane(false))
  on('classic.SubagentStart', () => ({}))
  await start()
  await $.classic.SubagentStart({ agent_id: 'delta', agent_type: 'general-purpose' } as never)
  expect(opens).toEqual([{ rows: 9 }])
})

test('the typed command and the button above the prompt open the pane with the keyboard', async ($, on) => {
  const { opens, log, start } = session($, on)
  await start()
  await $.command.run({ command: 'divramod-subagent-context' } as never)
  const band = await $.ui.mount({ plugin: 'divramod-subagent-context', surface: 'terminal', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 5, columns: 100 }, requestId: 'band', viewport: { columns: 100, rows: 12 } } as never)
  await band.press({ key: 'subagents' })
  expect(opens).toEqual([{ rows: 9, focus: true }, { rows: 9, focus: true }])
  expect(log().map(l => l.split(' ').slice(1).join(' '))).toEqual(['ui.open command granted asked', 'ui.open button granted asked'])
})

// The `ui.open` hook strips `focus` from an open neither the command nor the button made. The test kit cannot raise
// such an open (a test's hook may not call `$.ui.open`, and the mod makes none), so the rewrite is tested here and the
// mod's own unasked opens (a subagent's start, the idle release) are checked above and below to carry no `focus`.
test('an open nobody asked for loses its focus and keeps the rest', () => {
  expect(unfocused({ id: ID, title: 'x', rows: 9, focus: true as const })).toEqual({ id: ID, title: 'x', rows: 9 })
  expect('focus' in unfocused({ id: ID, focus: true as const })).toBe(false)
})

test("a plugin's focus move in the pane is refused and logged, the person's is granted and logged", async ($, on) => {
  const { log, start } = session($, on)
  on('ui.focus', () => ({}))
  await start()
  const move = (origin: { kind: 'person' } | { kind: 'plugin'; name: string }) =>
    $.ui.focus({ component: 'Pane', requestId: ID, plugin: 'divramod-subagent-context', element: 'close', origin } as never)
  expect((await move({ kind: 'plugin', name: 'intruder' })).deny).toMatch(/only the person/)
  expect((await move({ kind: 'person' })).deny).toBeUndefined()
  const moves = log().filter(l => l.includes(' ui.focus '))
  expect(moves).toHaveLength(2)
  expect(moves[0]).toMatch(/ ui\.focus plugin:intruder refused close$/)
  expect(moves[1]).toMatch(/ ui\.focus person granted close$/)
})

test('the focus log keeps the last 200 lines, each with its time, origin and grant', () => {
  let text = ''
  for (let i = 0; i < 205; i++) text = appended(text, logLine(i * 1000, 'ui.focus', 'person', i % 2 === 0, `k${i}`))
  const lines = text.trim().split('\n')
  expect(lines).toHaveLength(200)
  expect(lines[0]).toBe('1970-01-01T00:00:05.000Z ui.focus person refused k5')
  expect(lines.at(-1)).toBe('1970-01-01T00:03:24.000Z ui.focus person granted k204')
})

test('the title line carries the marker only while the pane holds the keyboard', async ($, on) => {
  await steps($, on)
  for (const isFocused of [true, false]) {
    const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, isFocused } })
    const marker = await ui.find({ type: 'Text', text: /^\[pane has the keyboard/ })
    expect(marker?.text.trim()).toBe(isFocused ? MARKER : undefined)
    expect(await ui.find({ type: 'Text', text: 'divramod subagents context' })).toBeDefined()
    await ui.unmount()
  }
})

test('a pane that holds the keyboard a minute without a key gives it back; a press holds that off', async ($, on) => {
  let focused = true
  const { opens, closes, log, clock, start } = session($, on, () => pane(focused))
  await start()
  await clock.advance(10_000)
  await clock.advance(50_000)
  expect(closes).toEqual([])
  const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, scroll: { offset: 0, bodyRows: 20 } } })
  await ui.press({ key: 'down' })
  await clock.advance(50_000)
  expect(closes).toEqual([])
  await clock.advance(20_000)
  expect(closes).toEqual([ID])
  expect(opens).toEqual([{ rows: 9 }])
  expect(log().some(l => / idle release granted closed and reopened without focus$/.test(l))).toBe(true)
  focused = false
  await clock.advance(120_000)
  expect(closes).toEqual([ID])
  await ui.unmount()
})

test('idle counts from the later of the hold and the last key', () => {
  expect(idle(70_000, 10_000, 0)).toBe(true)
  expect(idle(69_999, 10_000, 0)).toBe(false)
  expect(idle(100_000, 10_000, 50_000)).toBe(false)
  expect(idle(100_000, 0, 0)).toBe(false)
})
