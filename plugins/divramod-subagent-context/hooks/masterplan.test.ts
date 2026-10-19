import { expect, test } from 'claude-code/testing'

import type { SessionRow } from '../types'
import { ROLLUP } from './testkit'
import { fieldOf, groupsOf, leadOf, lineOf, parseRollUp, servantsOf } from './masterplan'

const session = (over: Partial<SessionRow>): SessionRow => ({ id: 'x', pid: 1, name: 'n', cwd: '/w/worktree/hal2/31', kind: 'interactive', status: 'idle', startedAt: 0, plan: '', lead: '', here: false, ...over })
const HOME = '/w/worktree/hal2/09'

test('the CLI\'s JSON is a roll-up; null, an error text or another shape is none', () => {
  expect(parseRollUp(JSON.stringify(ROLLUP))).toEqual(ROLLUP)
  expect(parseRollUp('null')).toBeNull()
  expect(parseRollUp('{}')).toBeNull() // the CLI's "no masterplan" since plan 0318
  expect(parseRollUp('error: unknown subcommand')).toBeNull()
  expect(parseRollUp('{"slug":1}')).toBeNull()
  expect(parseRollUp(JSON.stringify({ ...ROLLUP, crop: null }))?.crop).toBeNull()
})

test('the header line, with and without a crop', () => {
  expect(lineOf(ROLLUP)).toBe('🌾 10 · 1/3 plans · 5/12+ steps')
  expect(lineOf({ ...ROLLUP, crop: null, plus: false })).toBe('◆ 10 · 1/3 plans · 5/12 steps')
})

test('a folder reads repo and field, a marker field plan and step', () => {
  expect(fieldOf(HOME)).toEqual({ repo: 'hal2', field: '09' })
  expect(fieldOf('/Users/m/a/hal2')).toEqual({ repo: 'hal2', field: '' })
  expect(leadOf('09 0010-masterplan-farm 2\n')).toEqual({ field: '09', plan: '0010-masterplan-farm', step: '2' })
  expect(leadOf('09')).toBeUndefined()
})

test('the masterplan group has a row per plan with its field, steps, status and needs', () => {
  const [g] = groupsOf([], HOME, ROLLUP, 0)
  expect(g!.title).toBe('🌾 10 · 1/3 plans · 5/12+ steps')
  expect(g!.grid.cells).toEqual([
    ['1', '0011-tools', '-', '3/3', 'done', '-'],
    ['2', '0012-view', '01', '2/4', 'running', '1'],
    ['3', '0013-map', '-', '0/5', 'draft', '1 2'],
  ])
})

test('only sessions of this repository whose marker names this field are servants', () => {
  const found = [
    session({ id: 'a', cwd: '/w/worktree/hal2/31', lead: '09 0010-masterplan-farm 2' }),
    session({ id: 'b', cwd: '/w/worktree/hal2/32', lead: '10 0010-masterplan-farm 3' }),
    session({ id: 'c', cwd: '/w/worktree/other/33', lead: '09 0010-masterplan-farm 3' }),
    session({ id: 'd', cwd: '/w/worktree/hal2/34', lead: '' }),
  ]
  expect(servantsOf(found, HOME).map(s => s.session.id)).toEqual(['a'])
  expect(groupsOf(found.slice(1), HOME, null, 0)).toEqual([])
  expect(groupsOf([], HOME, { ...ROLLUP, rows: [] }, 0)).toEqual([])
})

test('a servant of a row of the roll-up shows that row\'s plan, step, step status and steps, and its field is in the row', () => {
  const found = [
    session({ id: 'a', cwd: '/w/worktree/hal2/31', status: 'busy', lead: '09 0010-masterplan-farm 2' }),
    session({ id: 'b', cwd: '/w/worktree/hal2/32', lead: '09 0010-masterplan-farm 3', startedAt: 0 }),
  ]
  const [mp, sv] = groupsOf(found, HOME, ROLLUP, 5 * 60_000)
  expect(sv!.title).toBe('servants of this field')
  expect(sv!.grid.cells).toEqual([
    ['31', '0012-view', '3 step 3', 'running', '2/4', 'busy', '5m'],
    ['32', '0013-map', '1 step 1', 'open', '0/5', 'idle', '5m'],
  ])
  expect(mp!.grid.cells.map(c => c[2])).toEqual(['-', '01 31', '32'])
})

test('without the roll-up, or with a marker that names another plan, the status cells are empty and the rows stay', () => {
  const found = [
    session({ id: 'a', cwd: '/w/worktree/hal2/31', lead: '09 0010-masterplan-farm 2' }),
    session({ id: 'b', cwd: '/w/worktree/hal2/32', lead: '09 0099-other 4' }),
  ]
  for (const mp of [null, ROLLUP]) {
    const cells = groupsOf(found, HOME, mp, 0).at(-1)!.grid.cells
    expect(cells[1]).toEqual(['32', '0099-other', '4', '', '', 'idle', '0m'])
  }
  expect(groupsOf(found, HOME, null, 0)[0]!.grid.cells[0]).toEqual(['31', '0010-masterplan-farm', '2', '', '', 'idle', '0m'])
})
