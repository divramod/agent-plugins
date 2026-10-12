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

// One Claude Code session of this machine, from `~/.claude/sessions/<pid>.json`; `plan` is its folder's `plans/CURRENT_PLAN`.
export type SessionRow = { id: string; pid: number; name: string; cwd: string; kind: string; status: string; startedAt: number; plan: string; here: boolean }

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
    'divramod-subagent-context': { rows: SubagentRow[]; view: TableState | null; epoch: number; sessions: SessionRow[]; tab: Tab; plansView: TableState | null; agentsView: TableState | null; jobsView: TableState | null; jobs: JobRow[]; jobType: string }
  }
}
