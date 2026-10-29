import type { SessionRow, Tab } from '../types'
import { parse, planOf, pointerOf } from './sessions'

// How often the timer asks for a refresh, in milliseconds (plan 0297 D3).
export const PACE = 30_000
// How long one pid's check may take before it counts as not alive.
export const CHECK_MS = 5_000

// What the check needs of the engine and the pane, as plain functions: the engine follows `$` only inside the hooks
// module's own file, so `register.tsx` builds this from its `$` and a test from fakes.
export type World = {
  // The Claude config folder (`~/.claude`) and this session's id.
  config: () => Promise<string>
  session: () => Promise<string>
  list: (dir: string) => Promise<readonly { name: string; kind: string }[]>
  read: (path: string) => Promise<unknown>
  // Starts one process and resolves once it has exited.
  run: (argv: readonly string[]) => Promise<{ exitCode: number }>
  // Whether the pane is open, and its current tab.
  open: () => Promise<boolean>
  tab: () => Promise<Tab>
  // The sessions the tabs show now, and their replacement.
  get: () => Promise<readonly SessionRow[]>
  set: (rows: SessionRow[]) => Promise<unknown>
  // What follows a refresh inside its turn (the masterplan, load.ts): it has ended before the next refresh may start.
  after?: () => Promise<unknown>
}

// The command that checks one pid: `kill -0` sends nothing (signal 0), it only asks whether the pid exists. Never a
// `ps` over a list of pids, which walks the whole process table.
export const argvOf = (pid: number) => ['kill', '-0', String(pid)]

// Whether the pid's process runs: exit code 0. Any other code, a run that fails or a pid that is none is not alive.
export async function alive(w: Pick<World, 'run'>, pid: number) {
  if (!Number.isInteger(pid) || pid <= 0) return false
  const run = await w.run(argvOf(pid)).catch(() => undefined)
  return run?.exitCode === 0
}

// The live sessions of this machine: each `<config>/sessions/<pid>.json` whose process still runs, one check per pid
// and one at a time, with the plan its folder names and the foreman its `LEAD` names (each read from the git dir's
// `hal/`, else `plans/`). A file or a plan that cannot be read is left out, never an error.
export async function loadSessions(w: World, config: string, session: string) {
  const dir = `${config}/sessions`
  const out: SessionRow[] = []
  for (const f of await w.list(dir).catch(() => [])) {
    if (f.kind !== 'file' || !/^\d+\.json$/.test(f.name)) continue
    const s = parse(String(await w.read(`${dir}/${f.name}`).catch(() => '')))
    if (!s || !(await alive(w, s.pid))) continue
    const plan = planOf(await pointerOf(p => w.read(p), s.cwd, 'CURRENT_PLAN'))
    out.push({ ...s, plan, lead: planOf(await pointerOf(p => w.read(p), s.cwd, 'LEAD')), here: s.id === session })
  }
  return out
}

// The session check of one loaded module: `refresh` reloads the sessions, `tick` is the timer's refresh.
export const sessionCheck = () => {
  // True while a refresh runs: a second one is skipped, never queued and never run beside it.
  let running = false

  // Reloads the sessions; they are written only when they changed, so a quiet round redraws nothing.
  const refresh = async (w: World) => {
    if (running) return
    running = true
    try {
      const next = await loadSessions(w, await w.config(), await w.session())
      if (JSON.stringify(next) !== JSON.stringify(await w.get())) await w.set(next)
      await w.after?.()
    } catch {
    } finally {
      running = false
    }
  }

  // The timer's refresh: only while the pane is open on the Plans or Agents tab; else no process and no file read.
  const tick = async (w: World) => {
    if (running) return
    try {
      if (!(await w.open())) return
      const tab = await w.tab()
      if (tab !== 'plans' && tab !== 'agents') return
    } catch {
      return
    }
    await refresh(w)
  }

  return { refresh, tick }
}
