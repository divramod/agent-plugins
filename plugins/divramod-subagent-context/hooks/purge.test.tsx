import { expect, mock, test } from 'claude-code/testing'

import type { SubagentRow } from '../types'
import { PANE } from './testkit'
import { serialize } from './store'

const row = (id: string): SubagentRow => ({ id, description: `Plan 0149 row ${id}: title`, model: 'opus', effort: 'high', calls: 2, now: 50_000, peak: 60_000, compactions: 0, seconds: 40, started: 0, mtime: 0, status: 'completed' })
const entry = (name: string, kind: 'file' | 'dir') => ({ name, kind, size: 10, mtimeMs: 0, isLink: false })

// The rows file of wt 01 holds a row of wt 02 (the bug of 0.3.2); only the row with a transcript in this folder stays.
test("a remembered row without a transcript in this folder's project is dropped", async ($, on) => {
  const clock = mock.clock(on)
  mock.env(on, { HOME: '/h' })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: { context: { window: 1_000_000 } } as never }))
  on('command.register', () => ({ value: undefined as never }))
  on('ui.open', () => ({ value: undefined as never }))
  on('session.id', () => ({ value: 'S9' }))
  on('session.cwd', () => ({ value: '/w/worktree/hal2/01' }))
  on('agent.list', () => ({ value: [] }))
  on('ui.status', () => ({ value: undefined }))
  on('fs.list', (_$, e) => ({
    value: e.path === '/h/.claude/projects/-w-worktree-hal2-01' ? [entry('S1', 'dir')]
      : e.path === '/h/.claude/projects/-w-worktree-hal2-01/S1/subagents' ? [entry('agent-232.jsonl', 'file')]
      : [],
  }))
  const written: Record<string, string> = {}
  on('fs.read', (_$, e) => {
    if (e.path === '/h/.claude/divramod-subagent-context/rows-w-worktree-hal2-01.json') return { value: serialize([row('232'), row('233')]) }
    throw new Error(`ENOENT ${e.path}`)
  })
  on('fs.write', (_$, e) => {
    written[e.path] = e.text
    return { value: undefined as never }
  })
  await $.session.start({ cwd: '/w', surface: 'terminal', isInteractive: true })
  await clock.settle()
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /149-232: title/, in: 'table' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /149-233: title/, in: 'table' })).toBeUndefined()
  expect(written['/h/.claude/divramod-subagent-context/rows-w-worktree-hal2-01.json']).not.toContain('233')
  await ui.unmount()
})
