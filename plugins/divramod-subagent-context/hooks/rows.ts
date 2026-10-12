import type { ModelUsage } from 'claude-code'

import type { SubagentRow } from '../types'

// One model response of a subagent's loop, as the `turn.step` hook saw it.
export type Step = { id: string; description: string; status: string; model: string; effort: string; fill: number; at: number }

// A request's context is its input, cache read and cache write tokens; output is not in the window yet.
export const fill = (u: ModelUsage) =>
  u.input_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens

// `claude-opus-5-5` → `opus`: the family is what fits the column; an unknown id stays whole.
export const family = (model: string) => /opus|sonnet|haiku|fable/.exec(model)?.[0] ?? model

// The rows after one step: a new agent gets a row, a known one its counts; a fill that drops by more than half
// counts as a compaction until an event for them is known (D4).
export const record = (rows: readonly SubagentRow[], s: Step): SubagentRow[] => {
  const was = rows.find(r => r.id === s.id)
  const row: SubagentRow = {
    id: s.id,
    description: s.description,
    model: family(s.model),
    effort: s.effort,
    calls: (was?.calls ?? 0) + 1,
    now: s.fill,
    peak: Math.max(was?.peak ?? 0, s.fill),
    compactions: (was?.compactions ?? 0) + (was && s.fill < was.now / 2 ? 1 : 0),
    seconds: Math.round((s.at - (was?.started ?? s.at)) / 1000),
    started: was?.started ?? s.at,
    mtime: s.at,
    status: s.status,
  }
  return was ? rows.map(r => (r === was ? row : r)) : [...rows, row]
}

// Rows read from transcripts join the live ones: a row `turn.step` already made wins (D4); all keep the order of `started`.
export const adopt = (rows: readonly SubagentRow[], found: readonly SubagentRow[]): SubagentRow[] =>
  [...rows, ...found.filter(f => !rows.some(r => r.id === f.id))].sort((a, b) => a.started - b.started)

// A subagent's status changed (it started, a step ran, it stopped): a new one gets a row without counts yet.
export const mark = (rows: readonly SubagentRow[], m: { id: string; description: string; status: string; at: number }): SubagentRow[] =>
  rows.some(r => r.id === m.id)
    ? rows.map(r => (r.id === m.id ? { ...r, status: m.status, description: r.description || m.description } : r))
    : [...rows, { id: m.id, description: m.description, model: '', effort: '', calls: 0, now: 0, peak: 0, compactions: 0, seconds: 0, started: m.at, mtime: m.at, status: m.status }]
