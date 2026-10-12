import type { ClientPointerEvent } from 'claude-code'

import type { TableState } from '../types'

// What the hooks module hands the table: the header labels, the start widths and per row its cells, sort values,
// color (`null`: the surface's default) and whether it still runs.
export type TableRow = { id: string; cells: string[]; values: (string | number | null)[]; color: string | null; running: boolean }
export type Align = 'l' | 'c' | 'r'
// `sums` is the sum row for each filter; `aligns` the alignment of each column; `epoch` changes when the pane chose the view; `plain` (the tabs row's text) says there are no filters; `steps` says `h` `l` and the arrows step something outside the table (the jobs' type); `give` is the column that gives way first when the pane is narrow (1: the Subagent column).
export type TableProps = { heads: string[]; widths: number[]; aligns: Align[]; rows: TableRow[]; sums: Record<Filter, string[]>; view: TableState | null; epoch?: number; plain?: string; give?: number; steps?: boolean }

export type Sort = { col: number; dir: 'asc' | 'desc' }

export const FILTERS = ['all', 'running', 'finished'] as const
export type Filter = (typeof FILTERS)[number]

// The table's own state: the sort, the widths, the filter, a border being dragged and what a button went down on.
export type View = { sort?: Sort; widths: number[]; filter?: Filter; cursor?: string; drag?: { col: number; from: number; width: number }; press?: string }

// What a new instance starts from: the kept state, its widths only while the columns are the same.
export const restore = (props: TableProps): View => {
  const kept = props.view
  if (!kept) return { widths: props.widths }
  const widths = kept.widths.length === props.widths.length ? kept.widths : props.widths
  return { widths, filter: kept.filter, ...(kept.sort ? { sort: kept.sort } : {}), ...(kept.cursor ? { cursor: kept.cursor } : {}) }
}

// What is kept of a view: not a drag or a press under way.
export const saved = (view: View): TableState => ({ sort: view.sort ?? null, widths: view.widths, filter: view.filter ?? 'all', cursor: view.cursor ?? null })

// A post's data is the Client's own, but crosses as `unknown`: only a whole TableState is kept.
// What the Client posts when `q` is pressed.
export const isClose = (data: unknown) => typeof data === 'object' && data !== null && (data as { close?: unknown }).close === true

// What the Client posts when `s` `p` or `a` is pressed: the tab the pane should show.
export const tabOf = (data: unknown) => {
  const t = (data as { tab?: unknown } | null)?.tab
  return t === 'subagents' || t === 'plans' || t === 'agents' || t === 'jobs' ? t : undefined
}

// What the Client posts when `h` `l` or an arrow should step the jobs' type: which way.
export const stepOf = (data: unknown) => {
  const s = (data as { step?: unknown } | null)?.step
  return s === 'prev' || s === 'next' ? s : undefined
}

export const isState = (data: unknown): data is TableState => {
  const d = data as TableState | null
  return (
    typeof d === 'object' && d !== null &&
    Array.isArray(d.widths) && d.widths.every(w => Number.isInteger(w) && w > 0) &&
    (FILTERS as readonly string[]).includes(d.filter) &&
    (d.cursor === undefined || d.cursor === null || typeof d.cursor === 'string') &&
    (d.sort === null || (typeof d.sort === 'object' && Number.isInteger(d.sort.col) && (d.sort.dir === 'asc' || d.sort.dir === 'desc')))
  )
}

// The Client's lines from the top: the filter's tabs, the table's top rule, its header, then a rule and the rows.
export const TABS_Y = 0
export const TOP_Y = 1
export const HEAD_Y = 2

export const MIN = 3

export const pad = (s: string, n: number) => (s.length > n ? s.slice(0, Math.max(0, n - 1)) + '…' : s.padEnd(n))

// A cell of `w` cells: a space each side, the text left, centered or right in between, cut with `…` when too long.
export const inner = (text: string, w: number, align: Align = 'l') => {
  const room = Math.max(0, w - 2)
  const t = text.length > room ? text.slice(0, Math.max(0, room - 1)) + '…' : text
  const gap = room - t.length
  const [left, right] = align === 'r' ? [gap, 0] : align === 'c' ? [Math.floor(gap / 2), gap - Math.floor(gap / 2)] : [0, gap]
  return ` ${' '.repeat(left)}${t}${' '.repeat(right)} `.slice(0, w)
}

// One line of the table: the cells between `│`.
export const line = (cells: readonly string[], laid: readonly number[], aligns: readonly Align[]) =>
  '│' + cells.map((c, i) => inner(c, laid[i] ?? c.length + 2, aligns[i])).join('│') + '│'

// A rule across the table: the top, between rows, or the bottom.
export const rule = (laid: readonly number[], kind: 'top' | 'mid' | 'bottom') => {
  const [l, m, r] = kind === 'top' ? ['┌', '┬', '┐'] : kind === 'mid' ? ['├', '┼', '┤'] : ['└', '┴', '┘']
  return l + laid.map(w => '─'.repeat(w)).join(m) + r
}

// The header: each label with the sort's mark on the sorted one, in its column's alignment.
export const header = (heads: readonly string[], laid: readonly number[], aligns: readonly Align[], sort: Sort | undefined) =>
  line(heads.map((label, i) => (sort?.col === i ? `${label} ${sort.dir === 'asc' ? '▲' : '▼'}` : label)), laid, aligns)

// One click on a column's label: asc, then desc, then off; another column starts at asc.
export const cycle = (sort: Sort | undefined, col: number): Sort | undefined =>
  sort?.col !== col ? { col, dir: 'asc' } : sort.dir === 'asc' ? { col, dir: 'desc' } : undefined

const compare = (a: string | number | null, b: string | number | null) =>
  a === b ? 0 : a === null ? 1 : b === null ? -1 : a < b ? -1 : 1

// The rows in the sort's order; off keeps their own order (when each started). `null` sorts last either way.
export const order = (rows: readonly TableRow[], sort: Sort | undefined) => {
  if (!sort) return [...rows]
  const sign = sort.dir === 'asc' ? 1 : -1
  return rows
    .map((row, i) => ({ row, i }))
    .sort((a, b) => {
      const [x, y] = [a.row.values[sort.col] ?? null, b.row.values[sort.col] ?? null]
      return (x === null || y === null ? compare(x, y) : sign * compare(x, y)) || a.i - b.i
    })
    .map(r => r.row)
}

export const shown = (rows: readonly TableRow[], filter: Filter = 'all') =>
  filter === 'all' ? [...rows] : rows.filter(r => r.running === (filter === 'running'))

// The tabs' labels with their counts, as drawn one cell apart from x 0.
export const tabs = (rows: readonly TableRow[]) =>
  FILTERS.map(f => ` ${f[0]!.toUpperCase()}${f.slice(1)} ${shown(rows, f).length} `)

const tabAt = (labels: readonly string[], x: number) => {
  let start = 0
  for (const [i, label] of labels.entries()) {
    if (x >= start && x < start + label.length) return FILTERS[i]
    start += label.length + 1
  }
  return undefined
}

// The table's width: a border before each column and one after the last.
export const widthOf = (widths: readonly number[]) => widths.reduce((sum, w) => sum + w + 1, 1)

// The widths laid out in `columns` cells: too wide, the `give` column gives way down to MIN, then the widest others;
// never stretched.
export const fit = (widths: readonly number[], columns: number, give = 1) => {
  const laid = [...widths]
  if (!columns) return laid
  while (widthOf(laid) > columns) {
    const col = laid[give]! > MIN ? give : laid.indexOf(Math.max(...laid))
    if (laid[col]! <= MIN) break
    laid[col]!--
  }
  return laid
}

// What cell `x` of a line is: a column's cell, or the border right of it (`border`); the left edge is nobody's.
export const hit = (widths: readonly number[], x: number) => {
  let edge = 0
  for (const [col, w] of widths.entries()) {
    if (x > edge && x < edge + w + 1) return { col, border: false }
    if (x === edge + w + 1) return { col, border: true }
    edge += w + 1
  }
  return undefined
}

// What a cell is: a tab (`f:<filter>`), a column's label in the header (`h:<col>`), or a border right of a column on
// any line of the table (`b:<col>`).
const target = (e: ClientPointerEvent, laid: readonly number[], labels: readonly string[]) => {
  if (e.y === TABS_Y) return tabAt(labels, e.x) && `f:${tabAt(labels, e.x)}`
  const at = e.y >= TOP_Y ? hit(laid, e.x) : undefined
  if (!at) return undefined
  return at.border ? `b:${at.col}` : e.y === HEAD_Y ? `h:${at.col}` : undefined
}

// The view after one pointer event: a press on a border drags it, a press and release on one label sorts by it,
// on one tab filters by it.
export const point = (view: View, e: ClientPointerEvent, laid: readonly number[], labels: readonly string[]): View => {
  const at = target(e, laid, labels)
  if (e.type === 'down' && e.button === 'left') {
    const col = Number(at?.slice(2))
    if (at?.startsWith('b:')) return { ...view, press: undefined, drag: { col, from: e.x, width: laid[col]! } }
    return { ...view, press: at, drag: undefined }
  }
  if (e.type === 'move' && view.drag) {
    const { col, from, width } = view.drag
    return { ...view, widths: view.widths.map((w, i) => (i === col ? Math.max(MIN, width + e.x - from) : w)) }
  }
  if (e.type === 'up' && (view.drag || view.press)) {
    const done = { ...view, drag: undefined, press: undefined }
    if (!view.press || at !== view.press) return done
    if (at.startsWith('f:')) return { ...done, filter: at.slice(2) as Filter }
    return { ...done, sort: cycle(view.sort, Number(at.slice(2))) }
  }
  return view
}

// What a key does to the filter and the cursor: `left` `right` `h` `l` the tab before or
// after (the ends stay), `up` `down` `k` `j` the row before or after in `ids` (the shown rows' ids, in order); a new
// filter drops the cursor. Anything else, and a move that changes nothing, returns the same state.
export const step = <S extends { filter?: Filter; cursor?: string | undefined }>(state: S, k: string, ids: readonly string[]): S => {
  const at = FILTERS.indexOf(state.filter ?? 'all')
  const tab = k === 'left' || k === 'h' ? FILTERS[Math.max(0, at - 1)] : k === 'right' || k === 'l' ? FILTERS[Math.min(FILTERS.length - 1, at + 1)] : undefined
  if (tab) return tab === (state.filter ?? 'all') ? state : { ...state, filter: tab, cursor: undefined }
  const dir = k === 'down' || k === 'j' ? 1 : k === 'up' || k === 'k' ? -1 : 0
  if (!dir || !ids.length) return state
  const now = state.cursor === undefined ? -1 : ids.indexOf(state.cursor)
  const to = now < 0 ? (dir > 0 ? 0 : ids.length - 1) : Math.min(ids.length - 1, Math.max(0, now + dir))
  return ids[to] === state.cursor ? state : { ...state, cursor: ids[to] }
}

// The first row shown of `rows` with room for `room`: the newest unsorted, the first ones sorted, moved to keep the cursor in.
export const first = (rows: readonly TableRow[], room: number, sorted: boolean, cursor: string | undefined) => {
  const start = sorted ? 0 : rows.length - room
  const at = rows.findIndex(r => r.id === cursor)
  return at < 0 ? start : at < start ? at : at >= start + room ? at - room + 1 : start
}

// How many rows fit in `lines` lines: the tabs, the top rule, the header, a rule, the rows with a rule between each,
// a rule, the sum row and the bottom rule; a last line counts those left out.
export const fits = (rows: number, lines: number) => {
  if (!lines) return rows
  const all = Math.floor((lines - 6) / 2)
  return rows <= all ? rows : Math.max(1, Math.floor((lines - 7) / 2))
}
