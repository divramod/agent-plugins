import { expect, mock, test } from 'claude-code/testing'

import type { SubagentRow } from '../types'
import { limits, line, tone } from './table'

const row = (peak: number, compactions = 0): SubagentRow => ({
  id: 'a1', description: 'Plan 0214 step 30', model: 'opus', effort: 'xhigh', calls: 40, now: peak, peak, compactions, seconds: 300, started: 0, mtime: 1, status: 'running',
})

const DEFAULTS = limits({}, 1_000_000)
const PANE = { plugin: 'divramod-subagent-context', surface: 'terminal', component: 'Pane', props: { title: 'Subagents: context', isFocused: true, bodyColumns: 120, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} }, requestId: 'subagent-context', viewport: { columns: 120, rows: 24 } } as const

test('a row names the step, model, effort, peak and its share of the window', async () => {
  expect(line(row(310_000), DEFAULTS)).toMatch(/step 30\s+opus\s+xhigh\s+40\s+310k\s+310k\s+31\.0\s+0\s+05:00/)
})

test('a row is plain below 30%, yellow from 30%, red from 35% or after a compaction', async () => {
  expect(tone(row(68_000), DEFAULTS)).toBeUndefined()
  expect(tone(row(310_000), DEFAULTS)).toBe('yellow')
  expect(tone(row(360_000), DEFAULTS)).toBe('red')
  expect(tone(row(68_000, 1), DEFAULTS)).toBe('red')
})

test('window auto takes the session window, 200k and 1m fix it', async () => {
  expect(limits({ window: 'auto' }, 200_000).window).toBe(200_000)
  expect(limits({ window: '200k' }, 1_000_000).window).toBe(200_000)
  expect(limits({ window: '1m' }, 200_000).window).toBe(1_000_000)
})

test('the thresholds come from the options', async () => {
  const l = limits({ window: '200k', warn_percent: 10, alert_percent: 50 }, 1_000_000)
  expect(tone(row(19_000), l)).toBeUndefined()
  expect(tone(row(20_000), l)).toBe('yellow')
  expect(tone(row(100_000), l)).toBe('red')
})

test('the pane counts against the window and thresholds the options set', { options: { window: '200k', warn_percent: 10, alert_percent: 50 } }, async $ => {
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /warn 10% · stop 50% of 200k/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /%200k/, in: 'table' })).toBeDefined()
  await ui.unmount()
})

test('without options the pane uses the defaults', async $ => {
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /warn 30% · stop 35% of 1M/ })).toBeDefined()
  await ui.unmount()
})

const AGENTS = [
  { id: 'a1', description: 'Plan 0214 step 30', type: 'general-purpose', status: 'running' },
  { id: 'a2', description: 'Explore the hooks', type: 'Explore', status: 'running' },
] as const
const usage = (tokens: number) => ({ input_tokens: 0, output_tokens: 100, cache_read_input_tokens: tokens, cache_creation_input_tokens: 0, model: 'claude-opus-5-5' })

// The stub answers each step with as many cached tokens as the request's `messageCount` says.
test('a stubbed step stream fills the rows and colors them by their share', async ($, on) => {
  mock.clock(on)
  on('agent.list', () => ({ value: [...AGENTS] }))
  on('ui.status', () => ({ value: undefined }))
  on('turn.step', async function* (_$, e) {
    const u = usage(e.messageCount)
    yield { kind: 'stop', stopReason: 'end_turn', usage: u }
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: 'end_turn', usage: u }
  })
  const ui = await $.ui.mount(PANE)
  const run = async (tokens: number, agentId?: string) => {
    const s = $.turn.step({ turnId: 't', index: 0, model: 'opus', effort: 'high', messageCount: tokens, ...(agentId ? { agentId } : {}) })
    for (;;) {
      const r = await s.next()
      if (r.done) return r.value
    }
  }
  for (const [tokens, id] of [[40_000, 'a1'], [360_000, 'a2'], [500_000, 'fork'], [310_000, 'a1']] as const) await run(tokens, id)
  expect((await run(700_000)).stopReason).toBe('end_turn')
  const step30 = await ui.find({ type: 'Text', text: /^│ . │ Plan 0214 step 30\s+│\s+opus\s+│\s+high\s+│\s+2 │\s+310k │\s+310k │\s+31\.0 /, in: 'table' })
  expect(step30?.props.color).toBe('yellow')
  expect((await ui.find({ type: 'Text', text: /^│ . │ Explore the hooks/, in: 'table' }))?.props.color).toBe('red')
  expect(await ui.find({ type: 'Text', text: /500k|700k/, in: 'table' })).toBeUndefined()
  await ui.unmount()
})

const NAME = (id: string) => `agent-${id}.jsonl`
const entry = (name: string, size: number, mtimeMs = 1_000) => ({ name, kind: 'file' as const, size, mtimeMs, isLink: false })
const dir = (name: string) => ({ name, kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false })
const assistant = (at: string, cache: number) => JSON.stringify({ type: 'assistant', timestamp: at, message: { model: 'claude-sonnet-5-5', usage: { input_tokens: 0, cache_read_input_tokens: cache, cache_creation_input_tokens: 0 } } })

// Two earlier subagents (one small, one over 4 MiB) and a live one the step stream made.
test('at the start the pane lists the subagents that ran before the mod loaded', async ($, on) => {
  const clock = mock.clock(on)
  mock.env(on, { HOME: '/h' })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: { context: { window: 1_000_000 } } as never }))
  on('command.register', () => ({ value: undefined as never }))
  on('ui.open', () => ({ value: undefined as never }))
  const statuses: unknown[] = []
  on('ui.status', (_$, e) => { statuses.push(e.text); return { value: undefined } })
  on('session.id', () => ({ value: 'S1' }))
  on('agent.list', () => ({ value: [{ id: 'live', description: 'Live one', type: 'general-purpose', status: 'running' }] }))
  const files: Record<string, string> = {
    '/h/.claude/projects/p1/S1/subagents/agent-old.meta.json': JSON.stringify({ description: 'Old one', model: 'sonnet', effort: 'high' }),
    '/h/.claude/projects/p1/S1/subagents/agent-old.jsonl': [assistant('2026-10-09T10:00:00Z', 100_000), assistant('2026-10-09T10:02:00Z', 120_000)].join('\n'),
  }
  on('fs.list', (_$, e) =>
    ({ value: e.path === '/h/.claude/projects' ? [dir('p1')]
      : e.path === '/h/.claude/projects/p1/S1/subagents' ? [entry(NAME('old'), 900), entry(NAME('big'), 5 * 1024 * 1024), entry('agent-old.meta.json', 20), entry(NAME('big').replace('.jsonl', '.meta.json'), 20)]
      : [] }))
  on('fs.read', (_$, e) => {
    if (!(e.path in files)) throw new Error(`ENOENT ${e.path}`)
    return { value: files[e.path]! }
  })
  await $.session.start({ cwd: '/w', surface: 'terminal', isInteractive: true })
  await clock.settle()
  expect(statuses).toEqual([undefined])
  const ui = await $.ui.mount(PANE)
  const old = await ui.find({ type: 'Text', text: /Old one\s+│\s+sonnet\s+│\s+high\s+│\s+2 │\s+120k │\s+120k /, in: 'table' })
  expect(old).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /agent-big|big\s+│\s+-\s+│\s+-\s+│\s+-/, in: 'table' })).toBeDefined()
  await ui.unmount()
})
