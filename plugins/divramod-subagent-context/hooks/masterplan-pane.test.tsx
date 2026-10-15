import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { PANE, ROLLUP, steps } from './testkit'

// The plans tab's two groups in the pane (plan 0275 D18, D21, D26): field 09 with a fake `hal2-cli-plans`.
const entry = (name: string) => ({ name, kind: 'file' as const, size: 10, mtimeMs: 0, isLink: false })
const session = (pid: number, cwd: string) => JSON.stringify({ pid, sessionId: `S${pid}`, cwd, name: `s${pid}`, kind: 'interactive', status: pid === 12 ? 'busy' : 'idle', startedAt: 0 })
const CLI = 'hal2-cli-plans'
const ok = (stdout: string) => ({ exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false })

// Field 09 (this session, pid 11), servants in 31 and 32 of its marker's masterplan rows, and the sessions that are none:
// a marker naming field 10, one naming this field in another repository.
const ALL: Record<string, string> = {
  '/h/.claude/sessions/11.json': session(11, '/w/worktree/hal2/09'),
  '/h/.claude/sessions/12.json': session(12, '/w/worktree/hal2/31'),
  '/h/.claude/sessions/13.json': session(13, '/w/worktree/hal2/32'),
  '/h/.claude/sessions/14.json': session(14, '/w/worktree/hal2/33'),
  '/h/.claude/sessions/15.json': session(15, '/w/worktree/other/31'),
  '/w/worktree/hal2/09/plans/CURRENT_PLAN': '0275-masterplan-tools\n',
  '/w/worktree/hal2/31/plans/LEAD': '09 0010-masterplan-farm 2\n',
  '/w/worktree/hal2/32/plans/LEAD': '09 0010-masterplan-farm 3\n',
  '/w/worktree/hal2/33/plans/LEAD': '10 0010-masterplan-farm 3\n',
  '/w/worktree/other/31/plans/LEAD': '09 0010-masterplan-farm 3\n',
}

// `cli`: what the fake binary answers (a string, or null for a missing binary); returns the calls it got.
const setup = async ($: Parameters<Parameters<typeof test>[1]>[0], on: On, cli: string | null, FILES = ALL, how: { exit?: number; open?: boolean } = {}) => {
  const calls: string[][] = []
  mock.env(on, { HOME: '/h' })
  on('session.id', () => ({ value: 'S11' }))
  on('session.cwd', () => ({ value: '/w/worktree/hal2/09' }))
  on('ui.panes', () => ({ value: how.open === false ? [] : [{ id: 'subagent-context', title: 't', isShown: true, isFocused: false, isPlaced: true }] }))
  on('fs.list', (_$, e) => ({ value: e.path === '/h/.claude/sessions' ? Object.keys(FILES).filter(f => f.startsWith(e.path)).map(f => entry(f.split('/').at(-1)!)) : [] }))
  on('fs.read', (_$, e) => {
    if (!(e.path in FILES)) throw new Error(`ENOENT ${e.path}`)
    return { value: FILES[e.path]! }
  })
  on('process.run', (_$, e) => {
    if (e.argv[0] === 'kill') return { value: ok('') as never }
    calls.push([...e.argv])
    if (cli === null) throw new Error('ENOENT hal2-cli-plans')
    return { value: { ...ok(cli), exitCode: how.exit ?? 0 } as never }
  })
  await steps($, on)
  const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, bodyColumns: 140, scroll: { offset: 0, bodyRows: 40 } } })
  // The rows of a group: its box-drawn lines split into trimmed cells, by the number of columns (6: masterplan, 7: servants).
  const rows = async (columns: number) =>
    (await ui.findAll({ type: 'Text' })).map(t => t.text).filter(t => t.startsWith('│')).map(t => t.split('│').slice(1, -1).map(c => c.trim())).filter(c => c.length === columns).slice(1)
  const titles = async () => (await ui.findAll({ type: 'Text' })).map(t => t.text)
  return { ui, calls, masterplan: () => rows(6), servants: () => rows(7), titles }
}

const FAKE = JSON.stringify({ ...ROLLUP, rows: ROLLUP.rows })

test('the plans tab lists a masterplan of three rows, asked once with the session\'s folder', async ($, on) => {
  const { ui, calls, masterplan, titles } = await setup($, on, FAKE)
  await ui.press({ key: 'plans' })
  expect(calls).toEqual([[CLI, 'masterplan', '--repo', '/w/worktree/hal2/09', '--json']])
  expect(await titles()).toContain('🌾 10 · 1/3 plans · 5/12+ steps')
  expect((await masterplan()).map(c => c[1])).toEqual(['0011-tools', '0012-view', '0013-map'])
  expect((await masterplan()).map(c => c.slice(3))).toEqual([['3/3', 'done', '-'], ['2/4', 'running', '1'], ['0/5', 'draft', '1 2']])
  await ui.unmount()
})

test('two servants show their field, plan, step, step status and the plan\'s done/total, from the one process', async ($, on) => {
  const { ui, calls, masterplan, servants, titles } = await setup($, on, FAKE)
  await ui.press({ key: 'plans' })
  // 31 does row 2 (step 3 running, 2/4), 32 does row 3 (step 1 open, 0/5); the sessions of field 10 and of another repository are not listed.
  expect(await servants()).toEqual([
    ['31', '0012-view', '3 step 3', 'running', '2/4', 'busy', '0m'],
    ['32', '0013-map', '1 step 1', 'open', '0/5', 'idle', '0m'],
  ].map(r => r.map((c, i) => (i === 6 ? expect.stringMatching(/^\d+[mhd]/) : c))))
  expect(await titles()).toContain('servants of this field')
  expect((await masterplan()).map(c => c[2])).toEqual(['-', '01 31', '32'])
  expect(calls).toHaveLength(1)
  await ui.unmount()
})

test('without the binary the servants\' two status cells are empty and their rows stay; the group masterplan is absent', async ($, on) => {
  const { ui, calls, masterplan, servants, titles } = await setup($, on, null)
  await ui.press({ key: 'plans' })
  expect(calls).toHaveLength(1)
  expect(await masterplan()).toEqual([])
  expect((await servants()).map(c => c.slice(0, 5))).toEqual([['31', '0010-masterplan-farm', '2', '', ''], ['32', '0010-masterplan-farm', '3', '', '']])
  expect((await titles()).some(t => t.includes('plans ·'))).toBe(false)
  await ui.unmount()
})

for (const [name, cli] of [['null', 'null'], ['a text that is no roll-up', 'garbage']] as const) {
  test(`${name} gives no masterplan group`, async ($, on) => {
    const { ui, masterplan, titles } = await setup($, on, cli)
    await ui.press({ key: 'plans' })
    expect(await masterplan()).toEqual([])
    expect((await titles()).some(t => t.includes(' plans · '))).toBe(false)
    await ui.unmount()
  })
}

test('a failing CLI (exit 2, as the barn\'s CLI without the subcommand) gives no masterplan group', async ($, on) => {
  const { ui, masterplan } = await setup($, on, FAKE, ALL, { exit: 2 })
  await ui.press({ key: 'plans' })
  expect(await masterplan()).toEqual([])
  await ui.unmount()
})

test('a marker that names another plan gives a row with the marker\'s plan and step and empty status cells', async ($, on) => {
  const files = { ...ALL, '/w/worktree/hal2/32/plans/LEAD': '09 0099-other 4\n' }
  const { ui, masterplan, servants } = await setup($, on, FAKE, files)
  await ui.press({ key: 'plans' })
  expect((await servants()).map(c => c.slice(0, 5))).toEqual([['31', '0012-view', '3 step 3', 'running', '2/4'], ['32', '0099-other', '4', '', '']])
  expect((await masterplan()).map(c => c[2])).toEqual(['-', '01 31', '-'])
  await ui.unmount()
})

test('no process runs while another tab shows, and the masterplan is asked at the switch to the plans tab', async ($, on) => {
  const { ui, calls } = await setup($, on, FAKE)
  await ui.press({ key: 'agents' })
  await ui.press({ key: 'jobs' })
  await ui.press({ key: 'subagents' })
  expect(calls).toEqual([])
  await ui.press({ key: 'plans' })
  expect(calls).toHaveLength(1)
  await ui.unmount()
})

test('a closed pane starts no process', async ($, on) => {
  const { ui, calls } = await setup($, on, FAKE, ALL, { open: false })
  await ui.press({ key: 'plans' })
  expect(calls).toEqual([])
  await ui.unmount()
})

test('neither group shows without rows', async ($, on) => {
  const files = Object.fromEntries(Object.entries(ALL).filter(([k]) => !k.endsWith('/LEAD')))
  const { ui, servants, titles } = await setup($, on, 'null', files)
  await ui.press({ key: 'plans' })
  expect(await servants()).toEqual([])
  expect((await titles()).includes('servants of this field')).toBe(false)
  await ui.unmount()
})
