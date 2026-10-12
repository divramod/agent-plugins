import { atom, read, update } from 'claude-code'
import type { AgentInfo, EngineInterface, Register, TurnStepInput, TurnUsage } from 'claude-code'

import type { JobRow, SessionRow, SubagentRow, TableState, Tab } from '../types'
import { LIMIT, type File, idOf, metaOf, rowOf } from './backfill'
import { adopt, fill, mark, record } from './rows'
import { DAYS, parse, serialize } from './store'
import { agentsGrid, asTable, parse as parseSession, plansGrid, planOf } from './sessions'
import { jobsGrid, merge, stepType } from './jobs'
import { bodyOf } from './tabs'
import { type Filter, isClose, isState, order, stepOf, tabOf, shown, step } from './grid'
import { type Limits, WIDTHS, limits, tableProps, tableRows } from './table'
import { TITLE, appended, idle, logLine, unfocused, versionIn, wanted } from './keyboard'
import { type PaneData, paneView } from './pane-view'

// The pane's id, a literal here so the scan names the hooks' matchers.
const PANE = 'subagent-context'
const rows = atom({ plugin: 'divramod-subagent-context', key: 'rows' } as const, [] as SubagentRow[])
// The table's sort, widths and filter, so a redraw or a reopened pane shows them as they were (view-state rule).
const view = atom({ plugin: 'divramod-subagent-context', key: 'view' } as const, null as TableState | null)
// Bumped when a pane-level key changes the filter: the table is keyed by it, so it starts again from the kept view.
const epoch = atom({ plugin: 'divramod-subagent-context', key: 'epoch' } as const, 0)

// The pane's own keys `h` `l` `j` `k`, like `q`: they work while the pane holds the keyboard, without a click into the table.
async function press($: EngineInterface, l: Limits, key: string) {
  const kept = (await read($, view)) ?? { sort: null, widths: WIDTHS, filter: 'all' as Filter, cursor: null }
  const state = { ...kept, cursor: kept.cursor ?? undefined }
  const ids = order(shown(tableRows(await read($, rows), l), state.filter), state.sort ?? undefined).map(r => r.id)
  const next = step(state, key, ids)
  if (next === state) return
  await update($, view, () => ({ sort: next.sort, widths: next.widths, filter: next.filter, cursor: next.cursor ?? null }))
  await update($, epoch, n => n + 1)
}
// `j` `k` on the plans, agents or jobs tab: the row cursor of that table, so the keys never fall through to the prompt.
async function pressSessions($: EngineInterface, key: string, which: 'plans' | 'agents' | 'jobs') {
  const found = await read($, sessions)
  const grid = which === 'plans' ? plansGrid(found, 0) : which === 'agents' ? agentsGrid(found, 0) : jobsGrid(await read($, jobs), await read($, jobType), 0)
  const kept = which === 'plans' ? await read($, plansView) : which === 'agents' ? await read($, agentsView) : await read($, jobsView)
  const rows = grid.cells.map((cells, i) => ({ id: grid.ids[i]!, cells, values: cells, color: null, running: false }))
  const state = { sort: kept?.sort ?? null, widths: kept?.widths ?? asTable(grid, '', null, grid.ids, 0).widths, filter: 'all' as Filter, cursor: kept?.cursor ?? undefined }
  const next = step(state, key, order(rows, state.sort ?? undefined).map(r => r.id))
  if (next.cursor === state.cursor) return
  const kept_ = () => ({ sort: state.sort, widths: state.widths, filter: 'all' as Filter, cursor: next.cursor ?? null })
  await (which === 'plans' ? update($, plansView, kept_) : which === 'agents' ? update($, agentsView, kept_) : update($, jobsView, kept_))
  await update($, epoch, n => n + 1)
}
// `h` `l` on the jobs tab: the type before or after; the cursor starts again.
async function stepJobs($: EngineInterface, dir: 'prev' | 'next') {
  const to = stepType(await read($, jobs), await read($, jobType), dir)
  if (to === (await read($, jobType))) return
  await update($, jobType, () => to)
  await update($, jobsView, v => (v ? { ...v, cursor: null } : v))
  await update($, epoch, n => n + 1)
}

// The pane's top-level tab and the sessions of this machine the Plans and Agents tabs list (reloaded every 10 seconds).
const tab = atom({ plugin: 'divramod-subagent-context', key: 'tab' } as const, 'subagents' as Tab)
const sessions = atom({ plugin: 'divramod-subagent-context', key: 'sessions' } as const, [] as SessionRow[])
// The plans and agents tables' own sort, widths and cursor (the subagents' is `view`).
const plansView = atom({ plugin: 'divramod-subagent-context', key: 'plansView' } as const, null as TableState | null)
const agentsView = atom({ plugin: 'divramod-subagent-context', key: 'agentsView' } as const, null as TableState | null)
// This session's background jobs (the engine's `background_tasks` and `session_crons`), the type the Jobs tab shows and its table's view.
const jobs = atom({ plugin: 'divramod-subagent-context', key: 'jobs' } as const, [] as JobRow[])
const jobType = atom({ plugin: 'divramod-subagent-context', key: 'jobType' } as const, 'all')
const jobsView = atom({ plugin: 'divramod-subagent-context', key: 'jobsView' } as const, null as TableState | null)

// A Stop hook's snapshot of the session's in-flight work, merged into the jobs.
async function snapshot($: EngineInterface, e: { background_tasks?: Parameters<typeof merge>[1]; session_crons?: Parameters<typeof merge>[2] }) {
  if (!e.background_tasks && !e.session_crons) return
  const at = await $.clock.now()
  await update($, jobs, list => merge(list, e.background_tasks ?? [], e.session_crons ?? [], at))
}

const configDir = async ($: EngineInterface) => (await $.env.get('CLAUDE_CONFIG_DIR')) || `${await $.env.get('HOME')}/.claude`

// The live sessions of this machine: each `<config>/sessions/<pid>.json` whose process still runs (`ps`), with the plan its
// folder names. A file or a plan that cannot be read is left out, never an error.
async function loadSessions($: EngineInterface, config: string, session: string) {
  const dir = `${config}/sessions`
  const found: NonNullable<ReturnType<typeof parseSession>>[] = []
  for (const f of await $.fs.list(dir).catch(() => [])) {
    if (f.kind !== 'file' || !/^\d+\.json$/.test(f.name)) continue
    const s = parseSession(String(await $.fs.read(`${dir}/${f.name}`).catch(() => '')))
    if (s) found.push(s)
  }
  if (!found.length) return []
  const ps = await $.process.run(['ps', '-o', 'pid=', '-p', found.map(s => s.pid).join(',')]).catch(() => undefined)
  const alive = new Set(String(ps?.stdout ?? '').split('\n').map(l => l.trim()).filter(Boolean))
  const out: SessionRow[] = []
  for (const s of found.filter(s => alive.has(String(s.pid)))) {
    out.push({ ...s, plan: planOf(String(await $.fs.read(`${s.cwd}/plans/CURRENT_PLAN`).catch(() => ''))), here: s.id === session })
  }
  return out
}

// Reloads the sessions; the atom is written only when they changed, so a quiet round redraws nothing.
async function refresh($: EngineInterface) {
  try {
    const next = await loadSessions($, await configDir($), await $.session.id())
    if (JSON.stringify(next) !== JSON.stringify(await read($, sessions))) await update($, sessions, () => next)
  } catch {}
}

async function show($: EngineInterface, to: Tab) {
  await update($, tab, () => to)
  if (to !== 'subagents') await refresh($)
}

// The agents `$.agent.list()` named, and the loop ids it does not (the engine's compaction and memory forks).
type Known = { agents: Map<string, AgentInfo>; unlisted: Set<string> }

async function agent($: EngineInterface, known: Known, id: string) {
  if (!known.agents.has(id) && !known.unlisted.has(id)) {
    for (const a of await $.agent.list()) known.agents.set(a.id, a)
    if (!known.agents.has(id)) known.unlisted.add(id)
  }
  return known.agents.get(id)
}

async function seen($: EngineInterface, known: Known, l: Limits, e: TurnStepInput, usage: TurnUsage) {
  const a = await agent($, known, e.agentId!)
  if (!a) return
  live.add(a.id)
  const step = { id: a.id, description: a.description, status: 'running', model: usage.model || e.model, effort: e.effort === undefined ? '' : String(e.effort), fill: fill(usage), at: await $.clock.now() }
  await keep($, await update($, rows, list => record(list, step)))
}

// Asks an open pane for the room its rows need, never the keyboard; a closed pane stays closed (D6: it never opens by itself).
async function room($: EngineInterface, n: number) {
  const up = (await $.ui.panes()).some(p => p.id === PANE)
  if (up) await $.ui.open({ id: PANE, title: TITLE, rows: wanted(n) })
}

// The person's own opens (the typed command, the button), logged: the only ones whose `focus` the `ui.open` hook lets through.
let asking = 0
async function asked($: EngineInterface, by: 'command' | 'button') {
  const n = (await read($, rows)).length
  await logFocus($, 'ui.open', by, true, 'asked')
  asking++
  await $.ui.open({ id: PANE, title: TITLE, rows: wanted(n), focus: true }).finally(() => asking--)
}

// When the module last saw a key in the pane, and since when the pane holds the keyboard (0: it does not).
let lastKey = 0
let focusedAt = 0

// Appends a line to the focus log (`<config>/divramod-subagent-context/focus.log`, the last 200): the proof of who took
// the keyboard, for the next incident. Writes run one after the other; a failed one is dropped.
let logging = Promise.resolve()
async function logFocus($: EngineInterface, what: string, origin: string, granted: boolean, detail = '') {
  logging = logging.then(async () => {
    const [at, path] = [await $.clock.now(), `${await configDir($)}/divramod-subagent-context/focus.log`]
    await $.fs.write(path, appended(String(await $.fs.read(path).catch(() => '')), logLine(at, what, origin, granted, detail)))
  }).catch(() => {})
  await logging
}

// The pane's focus as a drawing or the timer saw it: a change is logged, a new hold starts the idle clock.
async function focusSeen($: EngineInterface, focused: boolean) {
  if (focused === focusedAt > 0) return
  focusedAt = focused ? await $.clock.now() : 0
  await logFocus($, 'pane', focused ? 'holds the keyboard' : 'gave the keyboard back', true)
}

// Focused and no key seen for a minute, the pane gives the keyboard back: closed and opened again without `focus`.
async function release($: EngineInterface) {
  const pane = (await $.ui.panes()).find(p => p.id === PANE)
  await focusSeen($, pane?.isFocused ?? false)
  if (!idle(await $.clock.now(), focusedAt, lastKey)) return
  await logFocus($, 'idle', 'release', true, 'closed and reopened without focus')
  focusedAt = 0
  await $.ui.close({ id: PANE })
  await $.ui.open({ id: PANE, title: TITLE, rows: wanted((await read($, rows)).length) })
}

// The version in the plugin's own plugin.json, shown at the pane's top right; empty when it cannot be read.
async function versionOf($: EngineInterface) {
  return versionIn(String(await $.fs.read(`${$.plugin.root}/.claude-plugin/plugin.json`).catch(() => '')))
}

// Where the rows are kept between sessions, and the last time they were written.
// One file per working folder: a `/clear` keeps the folder, and sessions of other folders never overwrite it.
const storeFile = async ($: EngineInterface) => {
  const slug = (await $.session.cwd().catch(() => '')).replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'default'
  return `${await configDir($)}/divramod-subagent-context/rows-${slug}.json`
}
let saved = 0

// Writes the rows now, or at most every 5 seconds; a failed write loses nothing the next one will not carry.
async function keep($: EngineInterface, list: readonly SubagentRow[], force = false) {
  const now = await $.clock.now()
  if (!force && now - saved < 5000) return
  saved = now
  await $.fs.write(await storeFile($), serialize(list)).catch(() => {})
}

const list = ($: EngineInterface, dir: string) => $.fs.list(dir).catch(() => [])

// The rows this module instance made from events (its own session's subagents), which a purge never drops.
const live = new Set<string>()
let purged = false

// Once per load: drops the remembered rows whose subagent has no transcript in this folder's project (rows another
// folder's session left in a shared file or in the state `/reload-plugins` keeps). With no transcript to judge by it keeps all.
async function purge($: EngineInterface) {
  if (purged) return
  purged = true
  try {
    const dir = `${await configDir($)}/projects/${(await $.session.cwd()).replace(/[^A-Za-z0-9]/g, '-')}`
    const now = await $.clock.now()
    const mine = new Set<string>()
    for (const s of await list($, dir)) {
      if (s.kind !== 'dir' || now - s.mtimeMs > DAYS * 86_400_000) continue
      for (const f of await list($, `${dir}/${s.name}/subagents`)) if (idOf(f.name)) mine.add(idOf(f.name)!)
    }
    if (!mine.size) return
    await keep($, await update($, rows, all => all.filter(r => mine.has(r.id) || live.has(r.id))), true)
  } catch {}
}

// The transcripts of this session's subagents: `<config>/projects/*/<session>/subagents/agent-*.jsonl`, with their dirs.
async function transcripts($: EngineInterface, config: string, session: string) {
  const found: (File & { dir: string })[] = []
  for (const project of await list($, `${config}/projects`)) {
    const dir = `${config}/projects/${project.name}/${session}/subagents`
    if (project.kind === 'dir') for (const f of await list($, dir)) if (f.kind === 'file' && idOf(f.name)) found.push({ id: idOf(f.name)!, size: f.size, mtimeMs: f.mtimeMs, dir })
  }
  return found
}

// The subagents that ran before the mod loaded, from their transcripts; a row `turn.step` made already wins.
async function earlier($: EngineInterface) {
  // Rows an earlier session left, first: a live row or a transcript of this session wins over them.
  const left = parse(String(await $.fs.read(await storeFile($)).catch(() => '')), await $.clock.now())
  if (left.length) await update($, rows, list => adopt(list, left))
  const agents = new Map((await $.agent.list()).map(a => [a.id, a]))
  const found: SubagentRow[] = []
  for (const f of await transcripts($, await configDir($), await $.session.id())) {
    const path = `${f.dir}/agent-${f.id}`
    const meta = metaOf(await $.fs.read(`${path}.meta.json`).catch(() => undefined))
    const text = f.size > LIMIT ? undefined : await $.fs.read(`${path}.jsonl`).catch(() => null)
    if (text !== null) found.push(rowOf(f, meta, text, agents.get(f.id)))
  }
  await keep($, await update($, rows, list => adopt(list, found)), true)
}

export const register: Register = (on, options) => {
  let l: Limits = limits(options, 1_000_000)
  const known: Known = { agents: new Map(), unlisted: new Set() }

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.command.register({ name: 'divramod-subagent-context', description: 'Show the context use of this session\'s subagents' })
    l = limits(options, (await $.session.usage()).context.window)
    // A module older than 0.1.7 pinned a summary line under the prompt; clearing it is harmless when none is set.
    void $.ui.status(undefined)
    // The pane never opens by itself (D6): not here, not at a reload (which runs this again), not on a subagent's start.
    await update($, jobs, () => [])
    void earlier($).then(() => purge($)).catch(() => {})
    void refresh($)
    void $.clock.every(10_000, () => void refresh($).then(() => release($)).catch(() => {}))
    return started
  })

  // Every response of a subagent's loop updates its row as it ends: no poll, no transcript read.
  on('turn.step', async function* ($, e, next) {
    const result = yield* next(e)
    if (e.agentId && result.usage) await seen($, known, l, e, result.usage)
    return result
  })

  // Every subagent of the session has a row from its start; its stop gives it its final status (D15's refresh).
  on('classic.SubagentStart', async ($, e, next) => {
    const result = await next(e)
    const a = await agent($, known, e.agent_id)
    live.add(e.agent_id)
    const at = await $.clock.now()
    const list = await update($, rows, list => mark(list, { id: e.agent_id, description: a?.description ?? e.agent_type, status: 'running', at }))
    await keep($, list)
    await room($, list.length).catch(() => {})
    return result
  })

  on('classic.Stop', async ($, e, next) => {
    const result = await next(e)
    await snapshot($, e)
    return result
  })

  on('classic.SubagentStop', async ($, e, next) => {
    const result = await next(e)
    await snapshot($, e)
    const listed = (await $.agent.list()).find(a => a.id === e.agent_id)?.status
    const status = listed === 'failed' || listed === 'killed' ? listed : 'completed'
    const at = await $.clock.now()
    await keep($, await update($, rows, list => (list.some(r => r.id === e.agent_id) ? mark(list, { id: e.agent_id, description: e.agent_type, status, at }) : list)), true)
    return result
  })

  on('command.run', { command: 'divramod-subagent-context' }, async $ => {
    await asked($, 'command')
    return { text: 'Subagents pane opened.' }
  })

  // A button above the prompt opens the pane, or closes it when it is open; a click presses it, `s` once the band has the keys.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const { Box, Button } = $.ui.resolve(e)
    const toggle = async () => {
      const up = (await $.ui.panes()).some(p => p.id === PANE)
      if (up) await $.ui.close({ id: PANE })
      else await asked($, 'button')
    }
    return (
      <Box>
        <Button label="subagents" hotkey="s" plain onPress={toggle} />
      </Box>
    )
  })

  on('ui.message', async ($, e, next) => {
    const result = await next(e)
    if (e.requestId !== PANE) return result
    lastKey = await $.clock.now()
    if (isClose(e.data)) await $.ui.close({ id: PANE })
    else if (tabOf(e.data)) await show($, tabOf(e.data)!)
    else if (stepOf(e.data)) await stepJobs($, stepOf(e.data)!)
    else if (isState(e.data)) {
      const state = () => e.data as TableState
      if (e.element === 'table') await update($, view, state)
      else if (e.element === 'plans-table') await update($, plansView, state)
      else if (e.element === 'agents-table') await update($, agentsView, state)
      else if (e.element === 'jobs-table') await update($, jobsView, state)
    }
    return result
  })

  // The table is a `Client` where the surface draws one (terminal, desktop); elsewhere its rows as plain lines.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const el = $.ui.resolve(e)
    // VS Code's table names a Client it does not draw yet: the surface decides.
    const Client = 'Client' in el && (e.surface === 'terminal' || e.surface === 'desktop') ? el.Client : undefined
    void purge($)
    await focusSeen($, e.props.isFocused).catch(() => {})
    const list = await read($, rows)
    const current = await read($, tab)
    const found = await read($, sessions)
    const tabJobs = await read($, jobs)
    const now = current === 'subagents' ? 0 : await $.clock.now()
    const other = current === 'subagents' ? undefined : bodyOf(current, found, tabJobs, await read($, jobType), { plans: await read($, plansView), agents: await read($, agentsView), jobs: await read($, jobsView) }, await read($, epoch), now)
    const table = tableProps(list, l, await read($, view), await read($, epoch))
    const client = !Client ? undefined : other ? <Client key={`${current}-table`} module="./table-view.tsx" props={other.table} flexGrow={1} /> : <Client key="table" module="./table-view.tsx" props={table} flexGrow={1} />
    // The body is as tall as the pane the surface gave it, so the table grows and shrinks with the window.
    const data: PaneData = { focused: e.props.isFocused, version: await versionOf($), current, found, jobs: tabJobs, list, l, table: client, other, height: e.props.scroll?.bodyRows, room: Math.max(1, (e.viewport?.rows ?? 24) - 5), columns: e.props.bodyColumns ?? e.viewport?.columns ?? 0 }
    return paneView(el, data, { show: t => show($, t), press: k => press($, l, k), pressSessions: k => pressSessions($, k, current as Exclude<Tab, 'subagents'>), stepJobs: d => stepJobs($, d), close: () => $.ui.close({ id: PANE }) })
  })

  // Only the typed command and the button ask for the keyboard: any other open of the pane loses `focus` (D3).
  on('ui.open', { id: PANE }, async ($, e, next) => {
    if (!e.focus) return next(e)
    if (asking > 0) return next(e)
    await logFocus($, 'ui.open', next.origin.plugin, false, 'focus stripped')
    return next(unfocused(e))
  })

  // Every move of the focus ring in the pane, logged; only the person's lands (a plugin's `$.ui.focus` or `autoFocus` is refused).
  on('ui.focus', { requestId: PANE }, async ($, e, next) => {
    const person = e.origin.kind === 'person'
    if (person) lastKey = await $.clock.now()
    await logFocus($, 'ui.focus', e.origin.kind === 'plugin' ? `plugin:${e.origin.name}` : 'person', person, e.element ?? '')
    return person ? next(e) : { deny: 'divramod-subagent-context: only the person moves the focus in its pane' }
  })

  // A press in the pane is a key the module sees: it holds the idle release off.
  on('ui.press', { requestId: PANE }, async ($, e, next) => {
    lastKey = await $.clock.now()
    return next(e)
  })
}
