import { expect, test } from 'claude-code/testing'

import type { RollUp, SessionRow } from '../types'
import { type World, sessionCheck } from './live'
import { type Io, afterRefresh } from './load'
import { ROLLUP } from './testkit'

const CLI = ['hal2-cli-plans', 'masterplan', '--repo', '/w/worktree/hal2/09', '--json']

// What follows a refresh, from fakes: the pane's state, the atoms and every process started, with its timeout; with
// `hold` the masterplan's process waits until `free()` lets it go.
const fake = (over: { shown?: boolean; hold?: boolean; stdout?: string } = {}) => {
  const state = { shown: over.shown ?? true, home: '', plan: null as RollUp | null, sets: 0, runs: [] as [readonly string[], number | undefined][], waiting: [] as (() => void)[] }
  const io: Io = {
    cwd: async () => '/w/worktree/hal2/09',
    run: async (argv, init) => {
      state.runs.push([argv, init?.timeoutMs])
      if (over.hold) await new Promise<void>(done => state.waiting.push(done))
      return { exitCode: 0, stdout: over.stdout ?? JSON.stringify(ROLLUP) }
    },
    shown: async () => state.shown,
    home: async () => state.home,
    setHome: async cwd => void (state.home = cwd),
    get: async () => state.plan,
    set: async plan => void ((state.plan = plan), state.sets++),
  }
  return { state, io }
}

// One live session (pid 12, a servant of field 09) and the session check's world around `io`.
const world = (io: Io, open: () => boolean) => {
  const state = { rows: [] as SessionRow[], lists: 0, checks: 0 }
  const files: Record<string, string> = {
    '/h/.claude/sessions/12.json': JSON.stringify({ pid: 12, sessionId: 'S12', cwd: '/w/worktree/hal2/31', name: 's12', kind: 'interactive', status: 'idle', startedAt: 0 }),
    '/w/worktree/hal2/31/plans/CURRENT_PLAN': '0012-view\n',
    '/w/worktree/hal2/31/plans/LEAD': '09 0010-masterplan-farm 2\n',
  }
  const w: World = {
    config: async () => '/h/.claude',
    session: async () => 'S11',
    list: async () => (state.lists++, [{ name: '12.json', kind: 'file' }]),
    read: async path => {
      if (!(path in files)) throw new Error(`ENOENT ${path}`)
      return files[path]
    },
    run: async () => (state.checks++, { exitCode: 0 }),
    open: async () => open(),
    tab: async () => 'plans',
    get: async () => state.rows,
    set: async rows => void (state.rows = rows),
    after: () => afterRefresh(io),
  }
  return { state, w }
}

// Lets the microtasks of a started refresh run until it waits for its process.
const settle = () => new Promise<void>(done => setTimeout(done, 0))

test('a hidden plans tab or a closed pane keeps the folder and starts no process', async () => {
  const { state, io } = fake({ shown: false })
  await afterRefresh(io)
  expect([state.home, state.runs, state.sets]).toEqual(['/w/worktree/hal2/09', [], 0])
})

test('an open plans tab asks the masterplan with one process and a 3 s timeout, and writes it only when it changed', async () => {
  const { state, io } = fake()
  await afterRefresh(io)
  await afterRefresh(io)
  expect(state.runs).toEqual([[CLI, 3000], [CLI, 3000]])
  expect([state.plan?.slug, state.sets]).toEqual(['0010-masterplan-farm', 1])
})

test('while the masterplan\'s process still runs no second one starts and no session is checked: not by a refresh, not by a tick', async () => {
  const { state, io } = fake({ hold: true })
  const { state: sessions, w } = world(io, () => true)
  const check = sessionCheck()
  const first = check.refresh(w)
  await settle()
  expect([state.runs.length, sessions.lists, sessions.checks]).toEqual([1, 1, 1])
  await check.refresh(w)
  await check.tick(w)
  expect([state.runs.length, sessions.lists, sessions.checks]).toEqual([1, 1, 1])
  state.waiting.shift()!()
  await first
  // The row carries its folder's `plans/LEAD`, and the masterplan arrived with that refresh.
  expect(sessions.rows.map(r => [r.plan, r.lead])).toEqual([['0012-view', '09 0010-masterplan-farm 2']])
  expect(state.plan?.slug).toBe('0010-masterplan-farm')
  // Once it has ended, the next one runs again.
  const next = check.tick(w)
  await settle()
  expect([state.runs.length, sessions.lists, sessions.checks]).toEqual([2, 2, 2])
  state.waiting.shift()!()
  await next
})

test('a tick with the pane closed asks no masterplan', async () => {
  const { state, io } = fake()
  const { state: sessions, w } = world(io, () => false)
  await sessionCheck().tick(w)
  expect([state.runs, state.home, sessions.lists]).toEqual([[], '', 0])
})
