import type { JobRow } from '../types'
import { type Grid, ago } from './sessions'

// What the engine's Stop hooks list: `background_tasks` (type, status, description and a type-specific field) and `session_crons`.
export type Task = { id: string; type: string; status: string; description: string; command?: string; agent_type?: string; server?: string; tool?: string; name?: string }
export type Cron = { id: string; schedule: string; recurring: boolean; prompt: string }

const ENDED = ['completed', 'failed', 'killed', 'cancelled', 'canceled', 'stopped', 'done', 'error']
const KEEP = 200

const detailOf = (t: Task) => t.command ?? t.agent_type ?? t.name ?? [t.server, t.tool].filter(Boolean).join(' / ')

// The jobs after a snapshot: each listed job added or updated (first seen kept), each earlier one it no longer lists ended.
export const merge = (list: readonly JobRow[], tasks: readonly Task[], crons: readonly Cron[], now: number): JobRow[] => {
  const seen = new Map(list.map(j => [j.id, j]))
  const now_: JobRow[] = [
    ...tasks.map(t => ({ id: t.id, type: t.type, status: t.status, text: t.description, detail: detailOf(t), ended: ENDED.includes(t.status.toLowerCase()) })),
    ...crons.map(c => ({ id: c.id, type: 'cron', status: c.recurring ? 'recurring' : 'once', text: c.prompt, detail: c.schedule, ended: false })),
  ].map(j => ({ ...j, first: seen.get(j.id)?.first ?? now, last: now }))
  const listed = new Set(now_.map(j => j.id))
  const gone = list.filter(j => !listed.has(j.id)).map(j => (j.ended ? j : { ...j, ended: true, status: 'ended', last: now }))
  return [...gone, ...now_].sort((a, b) => a.first - b.first).slice(-KEEP)
}

// The types the list has, `all` first, then by name.
export const typesOf = (list: readonly JobRow[]) => ['all', ...[...new Set(list.map(j => j.type))].sort()]

// The type one step before or after `current` in the list's types (the ends stay); an unknown one starts at `all`.
export const stepType = (list: readonly JobRow[], current: string, dir: 'prev' | 'next') => {
  const types = typesOf(list)
  const at = Math.max(0, types.indexOf(current))
  return types[Math.min(types.length - 1, Math.max(0, at + (dir === 'next' ? 1 : -1)))]!
}

// The jobs' table for the chosen type: running ones first, then the newest.
export const jobsGrid = (list: readonly JobRow[], type: string, now: number): Grid => {
  const rows = list.filter(j => type === 'all' || j.type === type).sort((a, b) => Number(a.ended) - Number(b.ended) || b.first - a.first)
  return {
    heads: ['Type', 'Status', 'Job', 'Detail', 'Age'],
    aligns: ['l', 'c', 'l', 'l', 'r'],
    cells: rows.map(j => [j.type, j.status, j.text, j.detail, ago(j.first, now)]),
    ids: rows.map(j => j.id),
  }
}

// The line above the table: each type with its count, the chosen one in brackets.
export const typesLine = (list: readonly JobRow[], type: string) =>
  typesOf(list).map(t => { const n = t === 'all' ? list.length : list.filter(j => j.type === t).length; return t === type ? `[${t} ${n}]` : `${t} ${n}` }).join('  ')
