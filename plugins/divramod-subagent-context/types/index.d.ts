export type SubagentRow = {
  id: string
  description: string
  model: string
  effort: string
  calls: number
  now: number
  peak: number
  compactions: number
  seconds: number
  // When its first and its latest step were seen (`$.clock.now()` ms); rows keep the order of `started`.
  started: number
  mtime: number
  // Its AgentStatus as `$.agent.list()` last gave it.
  status: string
  // Its transcript was over 4 MiB and was not read; calls, now, peak and compactions are 0 then.
  large?: boolean
}

// One Claude Code session of this machine, from `~/.claude/sessions/<pid>.json`; `plan` is its folder's `CURRENT_PLAN`,
// `lead` the first line of its `LEAD` (`<foreman's field> <plan> <step>`, empty when the file is not there).
export type SessionRow = { id: string; pid: number; name: string; cwd: string; kind: string; status: string; startedAt: number; plan: string; lead: string; here: boolean }

// The step a row of the roll-up works on next; `status` is the step table's word, empty while the step is open.
export type NextStep = { number: string; title: string; status: string }

// One row of a masterplan, as `hal2-cli-plans masterplan --json` gives it (the contract's fixture is
// code/rust/apps/hal2-cli-plans/tests/fixtures/expected/masterplan.json); the fields the mod does not read are left out.
export type RollUpRow = {
  row: string
  status: string
  needs: string[]
  slug: string
  done: number
  total: number
  next: NextStep | null
  current_in: string[]
}

// A masterplan's roll-up. `current_in` lists the fields whose CURRENT_PLAN is the masterplan itself (a servant's field).
export type RollUp = {
  id: number
  slug: string
  title: string
  crop: { name: string; glyph: string; code: string } | null
  current_in: string[]
  plans_done: number
  plans_total: number
  steps_done: number
  steps_total: number
  plus: boolean
  rows: RollUpRow[]
}

// The pane's top-level tab.
export type Tab = 'subagents' | 'plans' | 'agents' | 'jobs'

// One background job of this session (a shell, a subagent, a monitor, a workflow, a cron ...), from the `background_tasks`
// and `session_crons` the engine hands the Stop hooks; `ended` once a later snapshot no longer lists it.
export type JobRow = { id: string; type: string; status: string; text: string; detail: string; first: number; last: number; ended: boolean }

// The table's sort, column widths and filter, as its Client last posted them; kept for the session.
export type TableState = {
  sort: { col: number; dir: 'asc' | 'desc' } | null
  widths: number[]
  filter: 'all' | 'running' | 'finished'
  // The row `j` `k` stand on (its subagent id), null for none.
  cursor?: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'divramod-subagent-context': { rows: SubagentRow[]; view: TableState | null; epoch: number; sessions: SessionRow[]; tab: Tab; plansView: TableState | null; agentsView: TableState | null; jobsView: TableState | null; jobs: JobRow[]; jobType: string; masterplan: RollUp | null; home: string }
  }
}
