import type { RollUp, RollUpRow, SessionRow } from '../types'
import { type Grid, ago } from './sessions'

// The plans tab's two groups above the sessions: the masterplan this session's folder belongs to (the roll-up of
// `hal2-cli-plans masterplan --json`, plan 0275 D3) and the servants of this field (sessions whose `plans/LEAD` names
// this field, D26). Pure: register.tsx and load.ts do the IO.

const text = (v: unknown) => (typeof v === 'string' ? v : '')
const count = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const strings = (v: unknown) => (Array.isArray(v) ? v.filter((s): s is string => typeof s === 'string') : [])

const rowOf = (r: any): RollUpRow => ({
  row: text(r.row),
  status: text(r.status),
  needs: strings(r.needs),
  slug: text(r.slug),
  done: count(r.done),
  total: count(r.total),
  next: r.next && typeof r.next === 'object' ? { number: text(r.next.number), title: text(r.next.title), status: text(r.next.status) } : null,
  current_in: strings(r.current_in),
})

// The CLI's output as a roll-up; `{}` or `null` (the CLI's word for "no masterplan"), anything unreadable or a JSON of another
// shape gives null, never an error.
export const parseRollUp = (out: string): RollUp | null => {
  try {
    const r = JSON.parse(out)
    if (!r || typeof r !== 'object' || typeof r.slug !== 'string' || !Array.isArray(r.rows)) return null
    const crop = r.crop && typeof r.crop === 'object' ? { name: text(r.crop.name), glyph: text(r.crop.glyph), code: text(r.crop.code) } : null
    return {
      id: count(r.id), slug: r.slug, title: text(r.title), crop, current_in: strings(r.current_in),
      plans_done: count(r.plans_done), plans_total: count(r.plans_total), steps_done: count(r.steps_done), steps_total: count(r.steps_total),
      plus: r.plus === true, rows: r.rows.filter((x: unknown) => x && typeof x === 'object').map(rowOf),
    }
  } catch {
    return null
  }
}

// `/…/worktree/<repo>/<NN>` is repo `<repo>` and field `<NN>`; any other folder has no field (the yard).
export const fieldOf = (cwd: string) => {
  const parts = cwd.split('/').filter(Boolean)
  const at = parts.indexOf('worktree')
  return at >= 0 && parts.length > at + 2 ? { repo: parts[at + 1]!, field: parts.slice(at + 2).join('/') } : { repo: parts.at(-1) ?? '', field: '' }
}

// A `plans/LEAD` line: `<foreman's field> <plan> <step>`; undefined when it has no field and plan.
export const leadOf = (line: string) => {
  const [field, plan, ...step] = line.trim().split(/\s+/)
  return field && plan ? { field, plan, step: step.join(' ') } : undefined
}

// The servants of the field `home` stands in: sessions of the same repository whose marker names this field.
export const servantsOf = (found: readonly SessionRow[], home: string) => {
  const me = fieldOf(home)
  if (!me.field) return []
  return found
    .map(s => ({ s, lead: leadOf(s.lead), at: fieldOf(s.cwd) }))
    .filter(x => x.lead && x.lead.field === me.field && x.at.repo === me.repo && x.at.field !== me.field)
    .map(x => ({ session: x.s, lead: x.lead!, field: x.at.field }))
    .sort((a, b) => a.field.localeCompare(b.field))
}

export type Group = { title: string; grid: Grid }

// `🌾 274 · 2/17 plans · 19/147+ steps`; a masterplan without a crop gets `◆`.
export const lineOf = (m: RollUp) => `${m.crop?.glyph || '◆'} ${m.id} · ${m.plans_done}/${m.plans_total} plans · ${m.steps_done}/${m.steps_total}${m.plus ? '+' : ''} steps`

export const groupsOf = (found: readonly SessionRow[], home: string, mp: RollUp | null, now: number): Group[] => {
  const servants = servantsOf(found, home)
  const groups: Group[] = []
  if (mp && mp.rows.length) {
    const fields = (r: RollUpRow) =>
      [...new Set([...r.current_in, ...servants.filter(x => x.lead.plan === mp.slug && x.lead.step === r.row).map(x => x.field)])].sort().join(' ') || '-'
    groups.push({
      title: lineOf(mp),
      grid: {
        heads: ['Row', 'Plan', 'Field', 'Steps', 'Status', 'Needs'],
        aligns: ['l', 'l', 'l', 'r', 'c', 'l'],
        cells: mp.rows.map(r => [r.row, r.slug || '-', fields(r), `${r.done}/${r.total}`, r.status, r.needs.join(' ') || '-']),
        ids: mp.rows.map(r => r.row),
      },
    })
  }
  if (servants.length) {
    const cells = servants.map(({ session, lead, field }) => {
      const row = mp && lead.plan === mp.slug ? mp.rows.find(r => r.row === lead.step) : undefined
      const [plan, step, status, steps] = row
        ? [row.slug || lead.plan, row.next ? `${row.next.number} ${row.next.title}`.trim() : '-', row.next ? row.next.status || 'open' : 'done', `${row.done}/${row.total}`]
        : [lead.plan, lead.step || '-', '', '']
      return [field, plan, step, status, steps, session.status || session.kind, ago(session.startedAt, now)]
    })
    groups.push({
      title: 'servants of this field',
      grid: { heads: ['Field', 'Plan', 'Step', 'Step status', 'Steps', 'State', 'Age'], aligns: ['l', 'l', 'l', 'c', 'r', 'c', 'r'], cells, ids: servants.map(x => x.session.id || String(x.session.pid)) },
    })
  }
  return groups
}
