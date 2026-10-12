import { expect, test } from 'claude-code/testing'

import type { SubagentRow } from '../types'
import { color, limits } from './table'
import { mounted } from './testkit'

const stop = (agent_id: string) => ({ agent_id, agent_type: 'general-purpose', agent_transcript_path: '', stop_hook_active: false })

// The tabs as drawn: ` All 3 ` at x 0-6, ` Running n ` from x 8, ` Finished n ` after it.
test('each filter shows the right rows, chosen by a click on its tab or by the arrow keys', async ($, on) => {
  const { ui, all, texts, names, click, status } = await mounted($, on)
  Object.assign(status, { beta: 'completed', gamma: 'failed' })
  await $.classic.SubagentStop(stop('beta'))
  await $.classic.SubagentStop(stop('gamma'))
  expect((await all()).slice(0, 3)).toEqual([' All 3 ', ' Running 1 ', ' Finished 2 '])
  expect((await texts()).map(t => t.split('│')[1]!.trim())).toEqual(['●', '✓', '✗'])
  await click(10, 0)
  expect(await names()).toEqual(['alpha'])
  expect((await ui.find({ type: 'Text', text: ' Running 1 ', in: 'table' }))?.props.inverse).toBe(true)
  await ui.key({ key: 'right', in: 'table' })
  expect(await names()).toEqual(['beta', 'gamma'])
  await click(2, 0)
  expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
  await ui.key({ key: 'right', in: 'table' })
  expect(await names()).toEqual(['alpha'])
  await ui.key({ key: 'left', in: 'table' })
  expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
  await ui.unmount()
})

test('a running row is cyan unless warn or alert; a finished one has the default color', async ($, on) => {
  const { ui, status } = await mounted($, on)
  const tone = async (name: string) => (await ui.find({ type: 'Text', text: new RegExp(`^│ . │ ${name} `), in: 'table' }))?.props.color
  expect([await tone('alpha'), await tone('beta'), await tone('gamma')]).toEqual(['yellow', 'cyan', 'cyan'])
  status.beta = 'completed'
  await $.classic.SubagentStop(stop('beta'))
  expect(await tone('beta')).toBeUndefined()
  const row = { id: 'x', description: 'x', model: 'opus', effort: 'high', calls: 1, now: 360_000, peak: 360_000, compactions: 0, seconds: 60, started: 0, mtime: 0, status: 'running' } satisfies SubagentRow
  expect(color(row, limits({}, 1_000_000))).toBe('red')
  expect(color({ ...row, peak: 1_000, status: 'idle' }, limits({}, 1_000_000))).toBe('cyan')
  await ui.unmount()
})

test('a subagent has its row from its start, before its first step; a stop it was killed by shows ✗', async ($, on) => {
  const { ui, texts, names, status } = await mounted($, on)
  await $.classic.SubagentStart({ agent_id: 'delta', agent_type: 'Explore' })
  expect(await names()).toEqual(['alpha', 'beta', 'gamma', 'Explore'])
  expect((await texts()).at(-1)).toMatch(/^│ ● │ Explore\s+│\s+-\s+│\s+-\s+│\s+0\s/)
  status.alpha = 'killed'
  await $.classic.SubagentStop(stop('alpha'))
  expect((await texts())[0]).toMatch(/^│ ✗ │ alpha/)
  await ui.unmount()
})

test('r and f no longer choose a filter (a is the Agents tab); the pane has no running or finished button, next and prev do', async ($, on) => {
  const { ui, names, status } = await mounted($, on)
  Object.assign(status, { beta: 'completed' })
  await $.classic.SubagentStop(stop('beta'))
  for (const key of ['r', 'f']) await ui.key({ key, in: 'table' })
  expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
  expect(await ui.find({ type: 'Button', key: 'running' })).toBeUndefined()
  expect(await ui.find({ type: 'Button', key: 'finished' })).toBeUndefined()
  await ui.press({ key: 'next' })
  expect(await names()).toEqual(['alpha', 'gamma'])
  await ui.press({ key: 'prev' })
  expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
  await ui.unmount()
})

test('the arrow keys move between the tabs and stop at the ends', async ($, on) => {
  const { ui, names, status } = await mounted($, on)
  Object.assign(status, { beta: 'completed' })
  await $.classic.SubagentStop(stop('beta'))
  await ui.key({ key: 'left', in: 'table' })
  expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
  await ui.key({ key: 'right', in: 'table' })
  expect(await names()).toEqual(['alpha', 'gamma'])
  await ui.key({ key: 'right', in: 'table' })
  expect(await names()).toEqual(['beta'])
  await ui.key({ key: 'right', in: 'table' })
  expect(await names()).toEqual(['beta'])
  await ui.key({ key: 'left', in: 'table' })
  expect(await names()).toEqual(['alpha', 'gamma'])
  await ui.unmount()
})

test('h and l move between the tabs, j and k move the row, the cursor row is inverse and a new filter drops it', async ($, on) => {
  const { ui, names, status } = await mounted($, on)
  Object.assign(status, { beta: 'completed' })
  await $.classic.SubagentStop(stop('beta'))
  const on_ = async () => (await ui.findAll({ type: 'Text', in: 'table' })).filter(t => t.props.inverse && t.text.startsWith('│')).map(t => t.text.split('│')[2]!.trim())
  await ui.key({ key: 'j', in: 'table' })
  expect(await on_()).toEqual(['alpha'])
  await ui.key({ key: 'j', in: 'table' })
  await ui.key({ key: 'down', in: 'table' })
  await ui.key({ key: 'j', in: 'table' })
  expect(await on_()).toEqual(['gamma'])
  await ui.key({ key: 'k', in: 'table' })
  expect(await on_()).toEqual(['beta'])
  await ui.key({ key: 'l', in: 'table' })
  expect(await names()).toEqual(['alpha', 'gamma'])
  expect(await on_()).toEqual([])
  await ui.key({ key: 'h', in: 'table' })
  expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
  await ui.unmount()
})

test("the pane's own buttons h, l, j and k work without a click into the table", async ($, on) => {
  const { ui, names } = await mounted($, on)
  for (const [label, hotkey] of [['prev', 'h'], ['next', 'l'], ['down', 'j'], ['up', 'k']] as const) expect((await ui.find({ type: 'Button', key: label }))?.props.hotkey).toBe(hotkey)
  await ui.press({ key: 'next' })
  expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
  await ui.press({ key: 'down' })
  await ui.press({ key: 'down' })
  const lit = async () => (await ui.findAll({ type: 'Text', in: 'table' })).filter(t => t.props.inverse && t.text.startsWith('│')).map(t => t.text.split('│')[2]!.trim())
  expect(await lit()).toEqual(['beta'])
  await ui.press({ key: 'up' })
  expect(await lit()).toEqual(['alpha'])
  await ui.unmount()
})
