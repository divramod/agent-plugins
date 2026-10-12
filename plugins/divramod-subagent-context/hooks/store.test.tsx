import { expect, mock, test } from 'claude-code/testing'

import type { SubagentRow } from '../types'
import { PANE } from './testkit'
import { DAYS, KEEP, parse, serialize } from './store'

const row = (id: string, over: Partial<SubagentRow> = {}): SubagentRow => ({ id, description: `Plan 0149 row ${id}: title`, model: 'opus', effort: 'high', calls: 2, now: 50_000, peak: 60_000, compactions: 0, seconds: 40, started: 1_000, mtime: 2_000, status: 'completed', ...over })

test('what a session leaves is the newest rows; a bad file, an old row and a row still running are read safely', () => {
  const day = 86_400_000
  const kept = parse(serialize([row('a', { status: 'running' }), row('old', { mtime: 0 }), row('b', { status: 'failed' })]), DAYS * day + 1)
  expect(kept.map(r => [r.id, r.status])).toEqual([['a', 'completed'], ['b', 'failed']])
  expect(parse('not json', 0)).toEqual([])
  expect(parse(JSON.stringify({ rows: [{ id: 'x' }, 5, null] }), 0)).toEqual([])
  const many = Array.from({ length: KEEP + 20 }, (_, i) => row(`r${i}`, { mtime: i, started: i }))
  const back = parse(serialize(many), 1000)
  expect(back).toHaveLength(KEEP)
  expect(back.some(r => r.id === 'r0')).toBe(false)
})

test('a new session starts with the rows an earlier one left, and writes its own as the subagents stop', async ($, on) => {
  const clock = mock.clock(on)
  mock.env(on, { HOME: '/h' })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: { context: { window: 1_000_000 } } as never }))
  on('command.register', () => ({ value: undefined as never }))
  on('ui.open', () => ({ value: undefined as never }))
  on('session.id', () => ({ value: 'S2' }))
  on('session.cwd', () => ({ value: '/w/worktree/hal2/02' }))
  on('agent.list', () => ({ value: [{ id: 'live', description: 'Plan 0149 row 300: now', type: 'general-purpose', status: 'running' }] }))
  on('fs.list', () => ({ value: [] }))
  on('classic.SubagentStart', () => ({}))
  on('classic.SubagentStop', () => ({}))
  const file = '/h/.claude/divramod-subagent-context/rows-w-worktree-hal2-02.json'
  const written: Record<string, string> = {}
  on('fs.read', (_$, e) => {
    if (e.path === file) return { value: serialize([row('232', { mtime: 0, started: 0 })]) }
    throw new Error(`ENOENT ${e.path}`)
  })
  on('fs.write', (_$, e) => {
    written[e.path] = e.text
    return { value: undefined as never }
  })
  await $.session.start({ cwd: '/w', surface: 'terminal', isInteractive: true })
  await clock.settle()
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /^│ ✓ │ 149-232: title/, in: 'table' })).toBeDefined()
  await ui.unmount()
  await $.classic.SubagentStart({ agent_id: 'live', agent_type: 'general-purpose' })
  await $.classic.SubagentStop({ agent_id: 'live', agent_type: 'general-purpose', agent_transcript_path: '', stop_hook_active: false })
  const saved = parse(written[file]!, 0).map(r => r.id)
  expect(saved).toEqual(expect.arrayContaining(['232', 'live']))
})

test("another folder's session neither reads nor overwrites a folder's rows", async ($, on) => {
  const clock = mock.clock(on)
  mock.env(on, { HOME: '/h' })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: { context: { window: 1_000_000 } } as never }))
  on('command.register', () => ({ value: undefined as never }))
  on('ui.open', () => ({ value: undefined as never }))
  on('session.id', () => ({ value: 'S3' }))
  on('session.cwd', () => ({ value: '/w/worktree/hal2/03' }))
  on('agent.list', () => ({ value: [] }))
  on('fs.list', () => ({ value: [] }))
  const read: string[] = []
  const written: string[] = []
  on('fs.read', (_$, e) => {
    read.push(e.path)
    throw new Error(`ENOENT ${e.path}`)
  })
  on('fs.write', (_$, e) => {
    written.push(e.path)
    return { value: undefined as never }
  })
  await $.session.start({ cwd: '/w', surface: 'terminal', isInteractive: true })
  await clock.settle()
  expect(read).toContain('/h/.claude/divramod-subagent-context/rows-w-worktree-hal2-03.json')
  expect(read.filter(p => p.includes('rows-w-worktree-hal2-02'))).toEqual([])
  expect(written).toEqual(['/h/.claude/divramod-subagent-context/rows-w-worktree-hal2-03.json'])
})
