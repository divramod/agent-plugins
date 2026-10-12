// Runs workflows/deep-research.js outside Claude Code with fake agents, so its control flow can be tested.
// node workflow_harness.mjs [--check]   --check: syntax only; else runs with canned agents and prints the result JSON.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(here, '..', 'workflows', 'deep-research.js'), 'utf8')
if (!source.startsWith('export const meta = {')) throw new Error('the script must begin with export const meta')
const body = source.replace('export const meta =', 'const meta =')
const AsyncFunction = (async () => {}).constructor
const run = new AsyncFunction('args', 'agent', 'pipeline', 'parallel', 'phase', 'log', 'budget', body)
if (process.argv.includes('--check')) { console.log('ok: syntax'); process.exit(0) }

const scenario = process.env.SCENARIO || 'normal'
const calls = []
const agent = async (prompt, opts = {}) => {
  calls.push(opts.label)
  const label = opts.label || ''
  if (label === 'planner') return { questions: [
    { question: 'A?', perspective: 'docs', evidence_target: 'vendor docs' },
    { question: 'B?', perspective: 'practice', evidence_target: 'blogs' }], options: ['X', 'Y'], criteria: ['speed'],
    kind: 'decision', non_goals: [] }
  if (label.startsWith('researcher-')) {
    if (scenario === 'research-fails' && label === 'researcher-2') return null
    const n = label.split('-')[1]
    return { claims: [
      { claim: `claim ${n}a`, evidence: 'e', source_title: 't', source_author: 'a', source_date: '2026', source_locator: `https://ex.com/${n}`, source_type: 'primary', confidence: 'high' },
      { claim: `claim ${n}b`, evidence: 'e', source_title: 't', source_author: 'a', source_date: '', source_locator: `https://ex.com/${n}#frag`, source_type: 'primary', confidence: 'low' }],
      uncertainties: [], searched: ['q'], found: 3, read: 2 }
  }
  if (label.startsWith('verifier-')) {
    const ids = [...prompt.matchAll(/"id":"(q\d+c\d+)"/g)].map(m => m[1])
    return { verdicts: ids.map((id, k) => ({ claim_id: id, verdict: k === 1 ? 'unsupported' : 'verified', reason: 'r', checked_locator: 'l' })) }
  }
  if (label === 'premortem') return { leading_answer: 'X', runner_up: 'Y', case_for_runner_up: 'c', failure_story: 'f', assumptions: [], signposts: [] }
  if (label === 'report-writer') return { title: 't', answer_sentence: 'X.', answer: '**X** [S1].', confidence: 'moderate',
    confidence_reason: 'r', key_findings: [{ text: 'k [S1]', confidence: 'high', reason: 'r', claim_ids: ['q1c1'] }],
    recommendation: 'X', findings: [{ heading: 'A', body: 'a [S1]. b [S9].' }], options: [], comparison: '', open_questions: [], next_steps: [] }
  throw new Error(`unexpected agent ${label}`)
}
const pipeline = async (items, ...stages) => Promise.all(items.map(async (item, i) => {
  let value = item
  for (const stage of stages) {
    try { value = await stage(value, item, i) } catch { return null }
  }
  return value
}))
const parallel = async thunks => Promise.all(thunks.map(t => t().catch(() => null)))
const result = await run({ query: 'X or Y?', breadth: 3, today: '2026-09-30' }, agent, pipeline, parallel, () => {}, () => {},
  { total: null, spent: () => 0, remaining: () => Infinity })
console.log(JSON.stringify({ calls, result }))
