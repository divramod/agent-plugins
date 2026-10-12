import type { SessionRow, TableState } from '../types'
import { type Align, type TableProps, line, rule } from './grid'

// One Claude Code session as its `~/.claude/sessions/<pid>.json` says it; undefined when the text is no session.
export const parse = (text: string): Omit<SessionRow, 'plan' | 'here'> | undefined => {
  try {
    const s = JSON.parse(text)
    if (typeof s?.pid !== 'number' || typeof s.cwd !== 'string') return undefined
    return {
      id: typeof s.sessionId === 'string' ? s.sessionId : '',
      pid: s.pid,
      name: typeof s.name === 'string' && s.name ? s.name : s.cwd.split('/').filter(Boolean).at(-1) ?? String(s.pid),
      cwd: s.cwd,
      kind: typeof s.kind === 'string' ? s.kind : '',
      status: typeof s.status === 'string' ? s.status : '',
      startedAt: typeof s.startedAt === 'number' ? s.startedAt : 0,
    }
  } catch {
    return undefined
  }
}

// A plan file's first line: the plan the slot works on (`plans/CURRENT_PLAN`); empty when there is none.
export const planOf = (text: string | undefined) => (text ?? '').split('\n')[0]!.trim()

// `/…/worktree/<repo>/<NN>` reads `<repo> <NN>`; any other folder its last two parts.
export const folder = (cwd: string) => {
  const parts = cwd.split('/').filter(Boolean)
  const at = parts.indexOf('worktree')
  return at >= 0 && parts.length > at + 2 ? `${parts[at + 1]} ${parts.slice(at + 2).join('/')}` : parts.slice(-2).join('/')
}

// How long ago, as `5m`, `3h 12m` or `2d 4h`.
export const ago = (ms: number, now: number) => {
  const m = Math.max(0, Math.floor((now - ms) / 60_000))
  return m < 60 ? `${m}m` : m < 1440 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`
}

// The sessions with a plan, or all of them, by name; this session first.
export const ordered = (rows: readonly SessionRow[], onlyPlans: boolean) =>
  rows.filter(r => !onlyPlans || r.plan).sort((a, b) => Number(b.here) - Number(a.here) || a.name.localeCompare(b.name))

export type Grid = { heads: string[]; aligns: Align[]; cells: string[][]; ids: string[] }

export const agentsGrid = (rows: readonly SessionRow[], now: number): Grid => ({
  heads: ['Agent', 'Folder', 'Status', 'Plan', 'Age'],
  aligns: ['l', 'l', 'c', 'l', 'r'],
  cells: ordered(rows, false).map(r => [`${r.here ? '● ' : ''}${r.name}`, folder(r.cwd), r.status || r.kind, r.plan || '-', ago(r.startedAt, now)]),
  ids: ordered(rows, false).map(r => r.id || String(r.pid)),
})

export const plansGrid = (rows: readonly SessionRow[], now: number): Grid => ({
  heads: ['Plan', 'Agent', 'Folder', 'Status', 'Age'],
  aligns: ['l', 'l', 'l', 'c', 'r'],
  cells: ordered(rows, true).map(r => [r.plan, `${r.here ? '● ' : ''}${r.name}`, folder(r.cwd), r.status || r.kind, ago(r.startedAt, now)]),
  ids: ordered(rows, true).map(r => r.id || String(r.pid)),
})

const MIN = 8

// The column widths for a pane `columns` wide: each as wide as its longest cell, then the widest shrunk one cell at a
// time until the table fits (a cut cell ends in `…`); never below MIN.
export const widths = (g: Grid, columns: number) => {
  const laid = g.heads.map((h, i) => Math.max(h.length, ...g.cells.map(c => c[i]!.length)) + 2)
  const total = () => laid.reduce((sum, w) => sum + w + 1, 1)
  while (columns > 0 && total() > columns) {
    const widest = laid.indexOf(Math.max(...laid))
    if (laid[widest]! <= MIN) break
    laid[widest]!--
  }
  return laid
}

// The grid as box-drawn lines like the subagents' table, fitted to `columns` wide, no rules between rows (so a session
// takes one line); at most `max` rows, the rest counted in a last line. `empty` says so when there is no row.
export const lines = (g: Grid, empty: string, columns = 0, max = Infinity) => {
  const laid = widths(g, columns)
  const shown = g.cells.slice(0, Math.max(1, max))
  const out = [rule(laid, 'top'), line(g.heads, laid, g.aligns), rule(laid, 'mid'), ...shown.map(c => line(c, laid, g.aligns))]
  if (!g.cells.length) out.push(line([empty], [laid.reduce((sum, w) => sum + w + 1, -1)], ['l']))
  out.push(rule(laid, 'bottom'))
  if (g.cells.length > shown.length) out.push(`… ${g.cells.length - shown.length} more: make the pane taller`)
  return out
}

// The grid as the table's props (the `Client` lays it out and follows the pane's size): each column as wide as its
// longest cell (at most CAP), the first column giving way when the pane is narrow.
const CAP = 44
const total = (g: Grid, noun: string) => [`${g.cells.length} ${noun}`, ...g.heads.slice(1).map(() => '')]
export const asTable = (g: Grid, label: string, view: TableState | null, ids: readonly string[], give: number, noun = 'sessions', steps = false): TableProps => ({
  heads: g.heads,
  widths: g.heads.map((h, i) => Math.min(CAP, Math.max(h.length, ...g.cells.map(c => c[i]!.length))) + 2),
  aligns: g.aligns,
  rows: g.cells.map((cells, i) => ({ id: ids[i]!, cells, values: cells, color: null, running: false })),
  sums: { all: total(g, noun), running: total(g, noun), finished: total(g, noun) },
  view,
  plain: label,
  give,
  ...(steps ? { steps } : {}),
})
