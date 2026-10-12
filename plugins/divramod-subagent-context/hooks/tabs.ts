import type { JobRow, SessionRow, TableState, Tab } from '../types'
import type { TableProps } from './grid'
import { jobsGrid, typesLine } from './jobs'
import { agentsGrid, asTable, ordered, plansGrid } from './sessions'

export const TABS = [['subagents', 's'], ['plans', 'p'], ['agents', 'a'], ['jobs', 'b']] as const

// What the body of a tab other than the subagents shows: its table's props, its plain-line grid and the empty text.
export type Views = { plans: TableState | null; agents: TableState | null; jobs: TableState | null }
export const bodyOf = (current: Exclude<Tab, 'subagents'>, found: readonly SessionRow[], jobs: readonly JobRow[], type: string, views: Views, epoch: number, now: number) => {
  if (current === 'jobs') {
    const grid = jobsGrid(jobs, type, now)
    return { grid, empty: 'No background jobs in this view.', foot: `${jobs.filter(j => !j.ended).length} running · ${jobs.length} seen this session`, table: { ...asTable(grid, typesLine(jobs, type), views.jobs, grid.ids, 2, 'jobs', true), epoch } as TableProps }
  }
  const grid = current === 'plans' ? plansGrid(found, now) : agentsGrid(found, now)
  const foot = `${ordered(found, current === 'plans').length} sessions · reloaded every 10 s · ● this session`
  return { grid, empty: current === 'plans' ? 'No session has a current plan.' : 'No Claude sessions found.', foot, table: { ...asTable(grid, `${grid.cells.length} sessions · reloaded every 10 s · ● this session`, views[current], grid.ids, current === 'plans' ? 0 : 3), epoch } as TableProps }
}

// The count in a tab's label: the subagents, the running jobs, or the sessions the tab lists.
export const count = (t: Tab, subagents: number, found: readonly SessionRow[], jobs: readonly JobRow[]) =>
  t === 'subagents' ? subagents : t === 'jobs' ? jobs.filter(j => !j.ended).length : ordered(found, t === 'plans').length
