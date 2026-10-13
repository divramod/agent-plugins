import type { On } from 'claude-code'
import { type Engine, expect, mock, test } from 'claude-code/testing'

import { PACE, alive, argvOf } from './live'
import { PANE } from './testkit'

const entry = (name: string) => ({ name, kind: 'file' as const, size: 10, mtimeMs: 0, isLink: false })
const file = (pid: number, name: string, cwd: string) => JSON.stringify({ pid, sessionId: `S${pid}`, cwd, name, kind: 'interactive', status: 'idle', startedAt: 0 })
const DIR = '/h/.claude/sessions'

// Three session files (pid 13's process is gone), the pane open or closed, and every process the mod starts recorded;
// with `hold` a process waits until `free()` lets it go.
const world = ($: Engine, on: On, hold = false) => {
  const clock = mock.clock(on)
  mock.env(on, { HOME: '/h' })
  const files: Record<string, string> = {
    [`${DIR}/11.json`]: file(11, 'hal2-03', '/w/worktree/hal2/03'),
    [`${DIR}/12.json`]: file(12, 'hal2-04', '/w/worktree/hal2/04'),
    [`${DIR}/13.json`]: file(13, 'gone', '/w/worktree/hal2/05'),
    '/w/worktree/hal2/03/plans/CURRENT_PLAN': '0222-publish\n',
  }
  const state = { up: false, runs: [] as (readonly string[])[], lists: 0, waiting: [] as (() => void)[] }
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: { context: { window: 1_000_000 } } as never }))
  on('session.id', () => ({ value: 'S11' }))
  on('command.register', () => ({ value: undefined as never }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('agent.list', () => ({ value: [] }))
  on('ui.panes', () => ({ value: state.up ? [{ id: 'subagent-context', title: 't', isShown: true, isFocused: false, isPlaced: true }] : [] }))
  on('fs.write', () => ({ value: undefined }))
  on('fs.list', (_$, e) => {
    if (e.path !== DIR) return { value: [] }
    state.lists++
    return { value: Object.keys(files).filter(f => f.startsWith(DIR)).map(f => entry(f.split('/').at(-1)!)) }
  })
  on('fs.read', (_$, e) => {
    if (!(e.path in files)) throw new Error(`ENOENT ${e.path}`)
    return { value: files[e.path]! }
  })
  on('process.run', async (_$, e) => {
    state.runs.push(e.argv)
    if (hold) await new Promise<void>(done => state.waiting.push(done))
    return { value: { exitCode: e.argv.at(-1) === '13' ? 1 : 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  const start = async () => {
    await $.session.start({ cwd: '/w', surface: 'terminal', isInteractive: true })
    await clock.settle()
  }
  // Lets every waiting process go, and the ones started after them, until none waits.
  const free = async () => {
    hold = false
    while (state.waiting.length) {
      state.waiting.shift()!()
      await clock.settle()
    }
  }
  const mount = () => $.ui.mount({ ...PANE, props: { ...PANE.props, isFocused: false, scroll: { offset: 0, bodyRows: 30 } } })
  return { state, clock, start, free, mount }
}

// The pids a started process names: every argument that is a number or a list of numbers.
const pids = (argv: readonly string[]) => argv.filter(a => /^\d+(,\d+)*$/.test(a)).flatMap(a => a.split(','))

test('with several session files every started process names exactly one pid', async ($, on) => {
  const { state, start } = world($, on)
  await start()
  expect(state.runs).toHaveLength(3)
  for (const argv of state.runs) {
    expect(argv.some(a => a.includes(','))).toBe(false)
    expect(pids(argv)).toHaveLength(1)
  }
  expect(state.runs.map(argv => pids(argv)[0]).sort()).toEqual(['11', '12', '13'])
})

test('a refresh that still waits for its process starts no second one: not by a tick, not by a tab switch', async ($, on) => {
  const { state, clock, start, free, mount } = world($, on, true)
  await start()
  expect(state.runs).toHaveLength(1)
  state.up = true
  const ui = await mount()
  await ui.press({ key: 'plans' })
  await clock.advance(PACE)
  await clock.advance(PACE)
  expect(state.runs).toHaveLength(1)
  expect(state.lists).toBe(1)
  await free()
  expect(state.runs).toHaveLength(3)
  // Once it has ended, the next tick refreshes again.
  await clock.advance(PACE)
  expect(state.runs).toHaveLength(6)
  await ui.unmount()
})

test('a tick with the pane closed, or on the subagents or jobs tab, starts no process and reads no session file', async ($, on) => {
  const { state, clock, start, mount } = world($, on)
  await start()
  expect([state.runs.length, state.lists]).toEqual([3, 1])
  await clock.advance(2 * PACE)
  expect([state.runs.length, state.lists]).toEqual([3, 1])
  state.up = true
  const ui = await mount()
  await clock.advance(2 * PACE)
  await ui.press({ key: 'jobs' })
  await clock.advance(2 * PACE)
  expect([state.runs.length, state.lists]).toEqual([3, 1])
  // The switch to the agents tab refreshes at once, and from then on every 30 s.
  await ui.press({ key: 'agents' })
  expect([state.runs.length, state.lists]).toEqual([6, 2])
  await clock.advance(PACE - 1)
  expect(state.runs).toHaveLength(6)
  await clock.advance(1)
  expect([state.runs.length, state.lists]).toEqual([9, 3])
  // The pane closed on the agents tab: nothing again.
  state.up = false
  await clock.advance(2 * PACE)
  expect([state.runs.length, state.lists]).toEqual([9, 3])
  await ui.unmount()
})

test("a dead pid's session is left out, a live one keeps its plan", async ($, on) => {
  const { state, start, mount } = world($, on)
  await start()
  state.up = true
  const ui = await mount()
  await ui.press({ key: 'plans' })
  const texts = async (table: string) => (await ui.findAll({ type: 'Text', in: table })).map(t => t.text)
  expect((await texts('plans-table')).some(t => t.includes('0222-publish') && t.includes('● hal2-03'))).toBe(true)
  await ui.press({ key: 'agents' })
  const agents = await texts('agents-table')
  expect(agents.some(t => t.includes('hal2-04'))).toBe(true)
  expect(agents.some(t => t.includes('gone'))).toBe(false)
  expect(agents.some(t => t.includes('reloaded every 30 s'))).toBe(true)
  await ui.unmount()
})

test('one pid is checked by one cheap command; a failing run, another exit code or no pid is not alive', async () => {
  expect(argvOf(42)).toEqual(['kill', '-0', '42'])
  const run = (exitCode: number) => async () => ({ exitCode })
  expect(await alive({ run: run(0) }, 42)).toBe(true)
  expect(await alive({ run: run(1) }, 42)).toBe(false)
  expect(await alive({ run: async () => { throw new Error('ENOENT kill') } }, 42)).toBe(false)
  const runs: (readonly string[])[] = []
  for (const pid of [0, -1, 1.5, Number.NaN]) expect(await alive({ run: async argv => { runs.push(argv); return { exitCode: 0 } } }, pid)).toBe(false)
  expect(runs).toEqual([])
})
