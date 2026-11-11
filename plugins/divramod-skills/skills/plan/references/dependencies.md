# Plan dependencies

A plan that waits for another plan declares it (plan 0595, record [plan-dependencies](../../../../../../../../.adr/plan-dependencies.md)):
`hal2-cli-plans depends add <NNNN> [--steps <the waiting steps>] [--needs <the dependency's steps>] --until pushed|main`
writes the entry into this plan's `depends_on`; `depends rm <NNNN> --yes` drops it, `depends list [--plan P | --all]
--json` shows each plan's `depends_on` and its computed `dependents` with their state (open, pushed, hitched, main),
`depends check` reports a wait the front matter does not name. A cycle is refused. The dependents are computed,
never written by hand or guessed.

- `new` and the autogrill: a dependency found while planning (another plan's number next to wait, needs, after,
  requires, blocked) is declared with `depends add` and decided in the ledger.
- `plan.py check` runs `depends check` over the current plan only (D20) and reports an undeclared wait; silent when
  the installed `hal2-cli-plans` lacks the command.
- `until pushed`: the dependent starts its waiting steps once the needed steps are done on the dependency's
  `origin/<field>`; `main`: once they are in the barn. A hitched dependency reaches both (plan 0696): `depends list --json` gives `head`
  (the hitched sha) and `merge` (`origin/<field>`) on a hitched link; the dependent merges that sha and goes on. For landing order every dependency counts (D17): the
  tollman rides the dependent after its dependency.
