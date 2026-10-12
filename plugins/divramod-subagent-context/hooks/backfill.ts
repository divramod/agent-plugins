import type { AgentInfo } from 'claude-code'

import type { SubagentRow } from '../types'
import { family } from './rows'
import { fold, modelOf } from './transcript'

// `$.fs.read` rejects a file over 4 MiB; a larger transcript becomes a marked row instead of a read.
export const LIMIT = 4 * 1024 * 1024

type Meta = { description?: string; model?: string; effort?: string }
export type File = { id: string; size: number; mtimeMs: number }

// `agent-<id>.jsonl` → `<id>`; anything else in a `subagents` folder (the `.meta.json` files) is none.
export const idOf = (name: string) => /^agent-(.+)\.jsonl$/.exec(name)?.[1]

export const metaOf = (text: string | undefined): Meta => {
  try {
    return JSON.parse(text ?? '')
  } catch {
    return {}
  }
}

// The row of a transcript that ran before the mod loaded; `text` is absent for one over LIMIT (not read).
export function rowOf(file: File, meta: Meta, text: string | undefined, agent?: AgentInfo): SubagentRow {
  const base = { id: file.id, description: meta.description || agent?.description || '', effort: meta.effort ?? '', mtime: file.mtimeMs, status: agent?.status ?? 'completed' }
  if (text === undefined) return { ...base, model: family(meta.model ?? ''), calls: 0, now: 0, peak: 0, compactions: 0, seconds: 0, started: file.mtimeMs, large: true }
  const f = fold(text)
  const started = f.first || file.mtimeMs
  return { ...base, model: modelOf(f, meta), calls: f.calls, now: f.now, peak: f.peak, compactions: f.compactions, seconds: Math.round((f.last - started) / 1000), started }
}
