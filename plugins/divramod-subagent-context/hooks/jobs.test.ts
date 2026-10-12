import { expect, test } from 'claude-code/testing'

import { jobsGrid, merge, stepType, typesLine, typesOf } from './jobs'

const shell = { id: 'b1', type: 'shell', status: 'running', description: 'build', command: 'cargo build' }
const sub = { id: 'a1', type: 'subagent', status: 'running', description: 'Plan 0222 row 1: x', agent_type: 'general-purpose' }
const cron = { id: 'c1', schedule: '*/5 * * * *', recurring: true, prompt: 'check CI' }

test('a snapshot adds its jobs and crons; a job it no longer lists is ended, the first-seen time kept', () => {
  const one = merge([], [shell, sub], [cron], 10)
  expect(one.map(j => [j.id, j.type, j.ended])).toEqual([['b1', 'shell', false], ['a1', 'subagent', false], ['c1', 'cron', false]])
  const two = merge(one, [{ ...shell, status: 'completed' }], [], 50)
  expect(two.find(j => j.id === 'b1')).toMatchObject({ first: 10, last: 50, ended: true, status: 'completed' })
  expect(two.find(j => j.id === 'a1')).toMatchObject({ ended: true, status: 'ended', last: 50 })
  expect(two.find(j => j.id === 'c1')?.ended).toBe(true)
})

test('the types are all first, then by name; stepping stops at the ends and an unknown one starts at all', () => {
  const list = merge([], [shell, sub], [cron], 0)
  expect(typesOf(list)).toEqual(['all', 'cron', 'shell', 'subagent'])
  expect(stepType(list, 'all', 'next')).toBe('cron')
  expect(stepType(list, 'subagent', 'next')).toBe('subagent')
  expect(stepType(list, 'all', 'prev')).toBe('all')
  expect(stepType(list, 'gone', 'next')).toBe('cron')
})

test('the grid filters by type and lists running jobs before ended ones; the line counts each type', () => {
  const list = merge(merge([], [shell], [], 0), [sub], [cron], 60_000)
  expect(jobsGrid(list, 'all', 120_000).cells.map(c => c[0])).toEqual(['subagent', 'cron', 'shell'])
  expect(jobsGrid(list, 'shell', 120_000).cells.map(c => c[2])).toEqual(['build'])
  expect(typesLine(list, 'cron')).toBe('all 3  [cron 1]  shell 1  subagent 1')
})
