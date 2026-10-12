import { expect, test } from 'claude-code/testing'

import { cycle, fit, fits, hit, inner, order, rule } from './grid'
import { BORDER, PANE, PEAK, mounted, steps } from './testkit'
import { clock, short } from './table'

test('on VS Code, which draws no Client, the rows are plain lines in start order', async ($, on) => {
  await steps($, on)
  const ui = await $.ui.mount({ ...PANE, surface: 'vscode' })
  expect(await ui.find({ type: 'Client' })).toBeUndefined()
  const lines = (await ui.findAll({ type: 'Text', text: /^● (alpha|beta|gamma) / })).map(t => t.text.split(' ')[1])
  expect(lines).toEqual(['alpha', 'beta', 'gamma'])
  await ui.unmount()
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`on the ${surface} a click on a header sorts its column ascending, then descending, then not`, async ($, on) => {
    const { ui, header, names, click } = await mounted($, on, surface)
    expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
    await click(PEAK, 4)
    expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
    await click(PEAK)
    expect(await names()).toEqual(['beta', 'gamma', 'alpha'])
    expect(await header()).toMatch(/Peak ▲/)
    await click(PEAK)
    expect(await names()).toEqual(['alpha', 'gamma', 'beta'])
    expect(await header()).toMatch(/Peak ▼/)
    await click(PEAK)
    expect(await names()).toEqual(['alpha', 'beta', 'gamma'])
    expect(await header()).not.toMatch(/[▲▼]/)
    await ui.unmount()
  })
}

// The borders of the header line, by x.
const borders = (line: string) => [...line].flatMap((c, i) => (c === '│' ? [i] : []))

// The border right of Subagent is the header's third `│`; it can be dragged on any line of the table.
test('a drag on a border widens and narrows its column, never below 3 cells, from the header or from a row', async ($, on) => {
  const { ui, header, names, drag } = await mounted($, on)
  expect(borders(await header())[2]).toBe(BORDER)
  await drag(BORDER, BORDER + 4)
  expect(borders(await header())[2]).toBe(43)
  await ui.pointer({ type: 'down', x: 43, y: 4, button: 'left' })
  await ui.pointer({ type: 'move', x: 20, y: 4, button: 'left' })
  await ui.pointer({ type: 'up', x: 20, y: 4, button: 'left' })
  expect(borders(await header())[2]).toBe(20)
  await drag(20, 0)
  expect(borders(await header())[2]).toBe(8)
  expect(await names()).toEqual(['…', '…', '…'])
  expect(await header()).not.toMatch(/[▲▼]/)
  await ui.unmount()
})

test('the table is never wider than the region and never stretched: the Subagent column gives way', async ($, on) => {
  const { ui, header } = await mounted($, on)
  expect(await header()).toHaveLength(115)
  await ui.resize({ columns: 100, rows: 24, in: 'table' })
  expect(await header()).toHaveLength(100)
  await ui.resize({ columns: 130, rows: 24, in: 'table' })
  expect(await header()).toHaveLength(115)
  await ui.unmount()
})

test('the table has a rule over and under it, between its rows and over the sum row', async ($, on) => {
  const { ui, all } = await mounted($, on)
  const texts = await all()
  const rules = texts.filter(t => /^[┌├└]/.test(t))
  // top, under the header, between the three rows (2), over the sum row, bottom
  expect(rules).toHaveLength(6)
  expect(rules[0]).toMatch(/^┌[─┬]+┐$/)
  expect(rules.at(-1)).toMatch(/^└[─┴]+┘$/)
  expect(texts.at(-1)).toBe(rules.at(-1))
  expect(texts.at(-2)).toMatch(/^│ Σ /)
  await ui.unmount()
})

test('numbers are right-aligned, model and effort centered, the state and the title as they are', async ($, on) => {
  const { ui, texts, sum } = await mounted($, on)
  const cells = (await texts())[0]!.split('│').slice(1, -1)
  // alpha: 1 call, now 300k, peak 300k, 30.0 %, no compaction, 0:00
  expect(cells[0]).toBe(' ● ')
  expect(cells[1]!.startsWith(' alpha ')).toBe(true)
  expect(cells[2]).toMatch(/^ +opus +$/)
  const [left, right] = [cells[2]!.indexOf('opus'), cells[2]!.length - 4 - cells[2]!.indexOf('opus')]
  expect(Math.abs(left - right)).toBeLessThanOrEqual(1)
  for (const i of [4, 5, 6, 7, 8, 9]) expect(cells[i]).toMatch(/^ +\S+ $/)
  expect((await sum()).split('│').slice(1, -1)[1]).toMatch(/^ 3 subagents /)
  await ui.unmount()
})

test('the sum row adds the calls, the context, the peaks, their share and the time of the shown rows', async ($, on) => {
  const { ui, sum, click } = await mounted($, on)
  // 3 agents with 1 call each; now and peak 300k + 100k + 200k; 60.0 % of 1M
  const cells = async () => (await sum()).split('│').slice(1, -1).map(c => c.trim())
  expect(await cells()).toEqual(['Σ', '3 subagents', '', '', '3', '600k', '600k', '60.0', '0', '00:00'])
  await click(10, 0)
  expect((await cells())[1]).toBe('3 subagents')
  await ui.unmount()
})

test('an agent title shortens to plan-row, a duration reads mm:ss, and the rows that fit are counted', () => {
  expect(short('Plan 0149 row 232: Automations plugin')).toBe('149-232: Automations plugin')
  expect(short('Plan 0149 row 163 part 2: e2e')).toBe('149-163 part 2: e2e')
  expect(short('Explore the hooks')).toBe('Explore the hooks')
  expect([0, 40, 61, 3599, 7530].map(clock)).toEqual(['00:00', '00:40', '01:01', '59:59', '125:30'])
  expect(inner('ab', 8, 'r')).toBe('     ab ')
  expect(inner('ab', 8, 'c')).toBe('   ab   ')
  expect(inner('abcdefgh', 5)).toBe(' ab… ')
  expect(rule([2, 3], 'mid')).toBe('├──┼───┤')
  // lines: 6 for the frame, 2 per row less one; a last line when rows are left out
  expect([fits(3, 12), fits(3, 11), fits(5, 12), fits(5, 0), fits(0, 3)]).toEqual([3, 2, 2, 5, 1])
})

test('rows without counts sort last both ways; a header cell is a label, a border or nothing', async () => {
  const rows = [
    { id: 'a', cells: [], values: [null], color: null, running: false },
    { id: 'b', cells: [], values: [2], color: null, running: false },
    { id: 'c', cells: [], values: [1], color: null, running: false },
  ]
  expect(order(rows, { col: 0, dir: 'asc' }).map(r => r.id)).toEqual(['c', 'b', 'a'])
  expect(order(rows, { col: 0, dir: 'desc' }).map(r => r.id)).toEqual(['b', 'c', 'a'])
  expect(cycle({ col: 1, dir: 'desc' }, 2)).toEqual({ col: 2, dir: 'asc' })
  expect(hit([5, 5], 0)).toBeUndefined()
  expect(hit([5, 5], 6)).toEqual({ col: 0, border: true })
  expect(hit([5, 5], 8)).toEqual({ col: 1, border: false })
  expect(hit([5, 5], 12)).toEqual({ col: 1, border: true })
  expect(hit([5, 5], 13)).toBeUndefined()
  expect(fit([5, 5, 5], 0)).toEqual([5, 5, 5])
  expect(fit([5, 9, 5], 20)).toEqual([5, 6, 5])
  expect(fit([5, 9, 5], 16)).toEqual([4, 3, 5])
  expect(fit([20, 9, 5], 30, 0)).toEqual([12, 9, 5])
  expect(fit([5, 9, 5], 60)).toEqual([5, 9, 5])
})
