import { family } from './rows'

// What one subagent transcript (`agent-<id>.jsonl`) says: its requests' fills, compactions and span.
export type Fold = { calls: number; now: number; peak: number; compactions: number; first: number; last: number; model: string }

type Line = {
  type?: string
  subtype?: string
  timestamp?: string
  message?: { model?: string; usage?: Record<string, number | undefined> }
}

const KEYS = ['input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens']

// A compaction is a `compact_boundary` entry or, as `record` counts it, a fill that drops by more than half.
export const fold = (text: string): Fold => {
  const out: Fold = { calls: 0, now: 0, peak: 0, compactions: 0, first: 0, last: 0, model: '' }
  for (const raw of text.split('\n')) {
    let e: Line
    try {
      e = JSON.parse(raw)
    } catch {
      continue
    }
    const at = Date.parse(e.timestamp ?? '')
    if (at) {
      out.first ||= at
      out.last = at
    }
    if (e.type === 'system' && String(e.subtype ?? '').includes('compact')) out.compactions++
    if (e.type !== 'assistant') continue
    const usage = e.message?.usage ?? {}
    const fill = KEYS.reduce((sum, k) => sum + (usage[k] ?? 0), 0)
    if (!fill) continue
    if (out.now && fill < out.now / 2) out.compactions++
    out.calls++
    out.now = fill
    out.peak = Math.max(out.peak, fill)
    out.model = e.message?.model || out.model
  }
  return out
}

export const modelOf = (f: Fold, meta: { model?: string }) => family(meta.model || f.model)
