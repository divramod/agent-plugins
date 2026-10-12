import { expect, mock, test } from 'claude-code/testing'

import { wanted } from './keyboard'
import { PANE, mounted, steps } from './testkit'

test('the pane asks for a row per subagent, between 9 and 20', () => {
  expect([0, 5, 9, 30].map(wanted)).toEqual([9, 9, 13, 20])
})

test('rows that do not fit are counted, not dropped silently', async ($, on) => {
  const { ui, all, texts } = await mounted($, on)
  await ui.resize({ columns: 120, rows: 9, in: 'table' })
  // Nine lines: the frame takes six, one row fits, the last line counts the other two.
  expect(await texts()).toHaveLength(1)
  expect((await all()).some(t => t.startsWith('… 2 more'))).toBe(true)
  await ui.resize({ columns: 120, rows: 24, in: 'table' })
  expect((await all()).some(t => t.startsWith('…'))).toBe(false)
})

test('a subagent that starts asks the open pane for room, a closed pane stays closed', async ($, on) => {
  const asked: (number | undefined)[] = []
  let up = true
  on('ui.panes', () => ({ value: up ? [{ id: 'subagent-context', title: 'Subagents: context', isShown: true, isFocused: false, isPlaced: true }] : [] }))
  on('ui.open', (_$, e) => {
    asked.push(e.rows)
    return { value: undefined as never }
  })
  await mounted($, on)
  await $.classic.SubagentStart({ agent_id: 'delta', agent_type: 'general-purpose' } as never)
  expect(asked).toEqual([9])
  up = false
  await $.classic.SubagentStart({ agent_id: 'eps', agent_type: 'general-purpose' } as never)
  expect(asked).toEqual([9])
})

test("the pane's top right shows the version of plugin.json", async ($, on) => {
  on('fs.read', (_$, e) => {
    if (!e.path.endsWith('/.claude-plugin/plugin.json')) throw new Error(`ENOENT ${e.path}`)
    return { value: JSON.stringify({ version: '9.8.7' }) }
  })
  const { ui } = await mounted($, on)
  expect(await ui.find({ type: 'Text', text: 'v9.8.7' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'divramod subagents context' })).toBeDefined()
})

test('a button above the prompt opens the pane, and closes it when it is open', async ($, on) => {
  const calls: string[] = []
  let up = false
  on('ui.panes', () => ({ value: up ? [{ id: 'subagent-context', title: 't', isShown: true, isFocused: false, isPlaced: true }] : [] }))
  on('ui.open', (_$, e) => {
    calls.push(`open ${e.rows} ${e.focus}`)
    return { value: undefined as never }
  })
  on('ui.close', (_$, e) => {
    calls.push(`close ${e.id}`)
    return { value: undefined }
  })
  await mounted($, on)
  const band = await $.ui.mount({ plugin: 'divramod-subagent-context', surface: 'terminal', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 5, columns: 100 }, requestId: 'band', viewport: { columns: 100, rows: 12 } } as never)
  expect((await band.find({ type: 'Button', key: 'subagents' }))?.props.hotkey).toBe('s')
  await band.press({ key: 'subagents' })
  up = true
  await band.press({ key: 'subagents' })
  expect(calls).toEqual(['open 9 true', 'close subagent-context'])
})

test('the command opens the pane focused, the start of a session opens nothing', async ($, on) => {
  const asked: (true | undefined)[] = []
  on('ui.open', (_$, e) => {
    asked.push(e.focus)
    return { value: undefined as never }
  })
  mock.env(on, { HOME: '/h' })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({ value: { context: { window: 1_000_000 } } as never }))
  on('command.register', () => ({ value: undefined as never }))
  on('session.id', () => ({ value: 'S1' }))
  on('fs.list', () => ({ value: [] }))
  await mounted($, on)
  await $.session.start({ cwd: '/w' } as never)
  await $.command.run({ command: 'divramod-subagent-context' } as never)
  expect(asked).toEqual([true])
})

// The test engine lays no heights out, so this checks what the engine is asked for: a body as tall as the pane's.
test('the body is as tall as the pane the surface gave it, and follows it', async ($, on) => {
  await steps($, on)
  for (const bodyRows of [10, 30]) {
    const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, scroll: { offset: 0, bodyRows } } })
    expect((await ui.findAll({ type: 'Box' })).some(b => b.props.height === bodyRows)).toBe(true)
    await ui.unmount()
  }
})

test("the pane's title in the window's first row is divramod subagents context", async ($, on) => {
  const titles: unknown[] = []
  on('command.register', () => ({ value: undefined as never }))
  on('ui.open', (_$, e) => { titles.push(e.title); return { value: undefined as never } })
  await mounted($, on)
  await $.command.run({ command: 'divramod-subagent-context' } as never)
  expect(titles).toContain('divramod subagents context')
})

const entry = (name: string, size: number) => ({ name, kind: 'file' as const, size, mtimeMs: 0, isLink: false })

// The sessions of this machine: two live ones (one with a plan) and one whose process is gone.
const session = (pid: number, name: string, cwd: string) => JSON.stringify({ pid, sessionId: `S${pid}`, cwd, name, kind: 'interactive', status: 'idle', startedAt: 0 })

test('s, p and a switch between the subagents, the plans of the live sessions and all their names', async ($, on) => {
  mock.env(on, { HOME: '/h' })
  const files: Record<string, string> = {
    '/h/.claude/sessions/11.json': session(11, 'hal2-03', '/w/worktree/hal2/03'),
    '/h/.claude/sessions/12.json': session(12, 'hal2-04', '/w/worktree/hal2/04'),
    '/h/.claude/sessions/13.json': session(13, 'gone', '/w/worktree/hal2/05'),
    '/w/worktree/hal2/03/plans/CURRENT_PLAN': '0222-publish\n',
  }
  on('session.id', () => ({ value: 'S11' }))
  on('fs.list', (_$, e) => ({ value: e.path === '/h/.claude/sessions' ? Object.keys(files).filter(f => f.startsWith(e.path)).map(f => entry(f.split('/').at(-1)!, 10)) : [] }))
  on('fs.read', (_$, e) => {
    if (!(e.path in files)) throw new Error(`ENOENT ${e.path}`)
    return { value: files[e.path]! }
  })
  on('process.run', () => ({ value: { exitCode: 0, stdout: '11\n12\n', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } as never }))
  await steps($, on)
  const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, scroll: { offset: 0, bodyRows: 30 } } })
  expect((await ui.find({ type: 'Button', key: 'plans' }))?.props.hotkey).toBe('p')
  await ui.press({ key: 'plans' })
  const texts = async () => (await ui.findAll({ type: 'Text', in: current })).map(t => t.text)
  let current = 'plans-table'
  expect((await texts()).some(t => t.includes('0222-publish') && t.includes('● hal2-03'))).toBe(true)
  expect((await texts()).some(t => t.includes('hal2-04'))).toBe(false)
  await ui.resize({ columns: 50, rows: 20, in: 'plans-table' })
  const widths = (await texts()).filter(t => /^[│┌├└]/.test(t)).map(t => t.length)
  expect(widths.length).toBeGreaterThan(3)
  expect(Math.max(...widths)).toBeLessThanOrEqual(50)
  await ui.resize({ columns: 120, rows: 20, in: 'plans-table' })
  expect(await ui.find({ type: 'Button', key: 'agents' })).toBeDefined()
  expect(await ui.find({ type: 'Button', key: 'subagents' })).toBeDefined()
  await ui.press({ key: 'down' })
  const lit = async () => (await ui.findAll({ type: 'Text', in: 'plans-table' })).filter(t => t.props.inverse && t.text.startsWith('│')).map(t => t.text)
  expect(await lit()).toHaveLength(1)
  await ui.press({ key: 'up' })
  expect((await lit())[0]).toContain('hal2-03')
  await ui.press({ key: 'agents' })
  current = 'agents-table'
  expect((await texts()).some(t => t.includes('hal2-04'))).toBe(true)
  expect((await texts()).some(t => t.includes('gone'))).toBe(false)
  await ui.press({ key: 'subagents' })
  expect(await ui.find({ type: 'Text', text: /alpha/, in: 'table' })).toBeDefined()
  await ui.unmount()
})

const stop = (over: object) => ({ stop_hook_active: false, ...over })

test('b shows the session\'s background jobs by type; h and l step the type, a snapshot without a job ends it', async ($, on) => {
  on('classic.Stop', () => ({}))
  await steps($, on)
  const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, scroll: { offset: 0, bodyRows: 30 } } })
  await $.classic.Stop(stop({
    background_tasks: [{ id: 'b1', type: 'shell', status: 'running', description: 'watch logs', command: 'tail -f x' }, { id: 'a1', type: 'subagent', status: 'running', description: 'Plan 0222 row 1: x' }],
    session_crons: [{ id: 'c1', schedule: '*/5 * * * *', recurring: true, prompt: 'check CI' }],
  }))
  expect((await ui.find({ type: 'Button', key: 'jobs' }))?.props.hotkey).toBe('b')
  await ui.press({ key: 'jobs' })
  const texts = async () => (await ui.findAll({ type: 'Text', in: 'jobs-table' })).map(t => t.text)
  expect((await texts())[0]).toBe('[all 3]  cron 1  shell 1  subagent 1')
  await ui.key({ key: 'l', in: 'jobs-table' })
  expect((await texts())[0]).toBe('all 3  [cron 1]  shell 1  subagent 1')
  expect((await texts()).filter(t => t.startsWith('│')).slice(1, -1).map(t => t.split('│')[1]!.trim())).toEqual(['cron'])
  await ui.key({ key: 'h', in: 'jobs-table' })
  await $.classic.Stop(stop({ background_tasks: [{ id: 'b1', type: 'shell', status: 'running', description: 'watch logs', command: 'tail -f x' }], session_crons: [] }))
  const lines = (await texts()).filter(t => t.startsWith('│')).slice(1, -1)
  expect(lines).toHaveLength(3)
  expect(lines[0]).toMatch(/shell\s+│\s+running/)
  expect(lines.filter(t => /ended/.test(t))).toHaveLength(2)
  await ui.unmount()
})
