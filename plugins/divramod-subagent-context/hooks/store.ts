import type { SubagentRow } from '../types'

// What a session leaves for the next one (a clear starts a new session, so its rows would be gone): at most this
// many rows, none older than this many days.
export const KEEP = 300
export const DAYS = 14

// The file's text: the newest rows by their latest step.
export const serialize = (rows: readonly SubagentRow[]) =>
  JSON.stringify({ version: 1, rows: [...rows].sort((a, b) => b.mtime - a.mtime).slice(0, KEEP).sort((a, b) => a.started - b.started) })

const isRow = (r: unknown): r is SubagentRow => {
  const o = r as Record<string, unknown> | null
  return typeof o === 'object' && o !== null && typeof o.id === 'string' && typeof o.description === 'string' && typeof o.status === 'string' &&
    ['calls', 'now', 'peak', 'compactions', 'seconds', 'started', 'mtime'].every(k => Number.isFinite(o[k]))
}

// The rows a file holds, as an earlier session left them: a bad file gives none, an old row goes, and a row that was
// still running then has ended with its session.
export const parse = (text: string, now: number): SubagentRow[] => {
  try {
    const rows = (JSON.parse(text) as { rows?: unknown }).rows
    if (!Array.isArray(rows)) return []
    return rows
      .filter(isRow)
      .filter(r => now - r.mtime < DAYS * 86_400_000)
      .map(r => (['completed', 'failed', 'killed'].includes(r.status) ? r : { ...r, status: 'completed' }))
  } catch {
    return []
  }
}
