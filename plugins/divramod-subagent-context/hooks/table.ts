import type { PluginOptions } from 'claude-code'

import type { SubagentRow, TableState } from '../types'
import { FILTERS, type TableProps, type TableRow } from './grid'

// The window a share is counted against and the two thresholds, from the mod's options.
export type Limits = { window: number; warn: number; alert: number }

const WINDOWS: Record<string, number> = { '200k': 200_000, '1m': 1_000_000 }

// `auto` takes the session's own window: no API gives a subagent's (research 0063, E9).
export const limits = (options: PluginOptions, sessionWindow: number): Limits => ({
  window: WINDOWS[String(options.window)] ?? sessionWindow,
  warn: Number(options.warn_percent ?? 30) / 100,
  alert: Number(options.alert_percent ?? 35) / 100,
})

const k = (n: number) => `${Math.round(n / 1000)}k`
const pad = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + '…' : s.padEnd(n))
const label = (window: number) => (window >= 1_000_000 ? `${window / 1_000_000}M` : k(window))

export const share = (row: SubagentRow, l: Limits) => row.peak / l.window

export const tone = (row: SubagentRow, l: Limits): 'red' | 'yellow' | undefined =>
  share(row, l) >= l.alert || row.compactions > 0 ? 'red' : share(row, l) >= l.warn ? 'yellow' : undefined

// An idle agent can still be woken: only completed, failed and killed ones are finished (D16).
export const running = (row: SubagentRow) => !['completed', 'failed', 'killed'].includes(row.status)

const glyph = (row: SubagentRow) => (running(row) ? '●' : row.status === 'completed' ? '✓' : '✗')

// The context tone wins; a running row is cyan otherwise, the state column keeps it recognisable (D14).
export const color = (row: SubagentRow, l: Limits) => tone(row, l) ?? (running(row) ? 'cyan' : undefined)

// `Plan 0149 row 232: Automations plugin` → `149-232: Automations plugin`; a part stays (`149-163 part 2: e2e`).
export const short = (description: string) => {
  const m = /^Plan 0*(\d+) row (\d+)( part \d+)?: (.*)$/.exec(description)
  return m ? `${m[1]}-${m[2]}${m[3] ?? ''}: ${m[4]}` : description
}

// A duration as `mm:ss` (`125:30` past two hours).
export const clock = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`

// The table's columns, their start widths (a cell is padded by a space each side) and how each is aligned.
export const WIDTHS = [3, 34, 9, 10, 9, 7, 8, 9, 7, 8]
export type Align = 'l' | 'c' | 'r'
export const ALIGNS: Align[] = ['c', 'l', 'c', 'c', 'r', 'r', 'r', 'r', 'r', 'r']

export const heads = (l: Limits) => [' ', 'Subagent', 'Model', 'Effort', 'Calls', 'Now', 'Peak', `%${label(l.window)}`, 'Cmp', 'Time']

// A row whose transcript was too large to read shows `-` where it has no counts.
export const cells = (row: SubagentRow, l: Limits) => {
  const [calls, now, peak, pct, cmp, time] = row.large
    ? ['-', '-', '-', '-', '-', '-']
    : [String(row.calls), k(row.now), k(row.peak), (share(row, l) * 100).toFixed(1), String(row.compactions), clock(row.seconds)]
  return [glyph(row), short(row.description || row.id), row.model || '-', row.effort || '-', calls, now, peak, pct, cmp, time]
}

// The sum row of some rows: how many, and the totals of the counts (a row without counts adds nothing).
export const sums = (list: readonly SubagentRow[], l: Limits) => {
  const add = (pick: (r: SubagentRow) => number) => list.reduce((sum, r) => sum + (r.large ? 0 : pick(r)), 0)
  return ['Σ', `${list.length} subagent${list.length === 1 ? '' : 's'}`, '', '', String(add(r => r.calls)), k(add(r => r.now)), k(add(r => r.peak)), (add(r => share(r, l)) * 100).toFixed(1), String(add(r => r.compactions)), clock(add(r => r.seconds))]
}

// What a column sorts by: text, or a number; `null` (a large row's counts) sorts last either way. The state column
// sorts running, completed, then failed and killed.
export const values = (row: SubagentRow, l: Limits): (string | number | null)[] => {
  const n = (v: number) => (row.large ? null : v)
  return [running(row) ? 0 : row.status === 'completed' ? 1 : 2, short(row.description || row.id), row.model, row.effort, n(row.calls), n(row.now), n(row.peak), n(share(row, l)), n(row.compactions), n(row.seconds)]
}

// The plain lines of a surface that draws no table (VS Code, mobile).
const PLAIN = [1, 36, 7, 7, 5, 6, 6, 5, 3, 6]
const join = (texts: string[]) => texts.map((t, i) => (i === texts.length - 1 ? t : pad(t, PLAIN[i]!))).join(' ')

export const head = (l: Limits) => join(heads(l))

export const line = (row: SubagentRow, l: Limits) => join(cells(row, l))

export const foot = (l: Limits) => `warn ${Math.round(l.warn * 100)}% · stop ${Math.round(l.alert * 100)}% of ${label(l.window)}`

// The table's rows as it draws them, so a pane-level key moves over what is shown.
export const tableRows = (list: readonly SubagentRow[], l: Limits): TableRow[] =>
  list.map(row => ({ id: row.id, cells: cells(row, l), values: values(row, l), color: color(row, l) ?? null, running: running(row) }))

// The subagents table's props for its `Client`: the rows, a sum row per filter, and the kept view.
export const tableProps = (list: readonly SubagentRow[], l: Limits, view: TableState | null, epoch: number): TableProps => ({
  heads: heads(l),
  widths: WIDTHS,
  aligns: ALIGNS,
  rows: tableRows(list, l),
  sums: Object.fromEntries(FILTERS.map(f => [f, sums(list.filter(r => f === 'all' || running(r) === (f === 'running')), l)])) as TableProps['sums'],
  view,
  epoch,
})
