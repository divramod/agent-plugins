import type { RollUp } from '../types'
import { parseRollUp } from './masterplan'

// What follows a refresh of the sessions (live.ts) needs of the engine and the pane, as plain functions built in
// register.tsx (the engine's `$` is followed only inside the file that holds the hooks module, never across an import).
export type Io = {
  // This session's folder.
  cwd: () => Promise<string>
  // Starts one process and resolves once it has exited.
  run: (argv: readonly string[], init?: { timeoutMs?: number }) => Promise<{ exitCode: number; stdout: string }>
  // Whether the pane is open and shows the plans tab.
  shown: () => Promise<boolean>
  // The folder and the masterplan the plans tab shows now, and their replacements.
  home: () => Promise<string>
  setHome: (cwd: string) => Promise<unknown>
  get: () => Promise<RollUp | null>
  set: (plan: RollUp | null) => Promise<unknown>
}

// The masterplan of the folder `cwd`, from `hal2-cli-plans masterplan --repo <cwd> --json`: one process, a timeout, and
// null for everything else (the word `null`, a missing binary, an unknown subcommand of an older CLI, a failure).
export async function loadMasterplan(io: Pick<Io, 'run'>, cwd: string): Promise<RollUp | null> {
  if (!cwd) return null
  const out = await io.run(['hal2-cli-plans', 'masterplan', '--repo', cwd, '--json'], { timeoutMs: 3000 }).catch(() => undefined)
  return out && out.exitCode === 0 ? parseRollUp(out.stdout) : null
}

// What follows each refresh of the sessions, inside its turn (live.ts's `after`: never beside a session check, never
// two at once): the folder is kept, and the masterplan is asked only while the pane is open on the plans tab (plan
// 0275 D18: no process for a hidden tab or a closed pane). Each is written only when it changed.
export async function afterRefresh(io: Io) {
  const cwd = await io.cwd()
  if (cwd !== (await io.home())) await io.setHome(cwd)
  if (!(await io.shown())) return
  const plan = await loadMasterplan(io, cwd)
  if (JSON.stringify(plan) !== JSON.stringify(await io.get())) await io.set(plan)
}
