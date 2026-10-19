# LLM lint

`W=hal2-cli-llm-wiki`, as in [SKILL.md](../SKILL.md). Read when `lint brief` has candidates. The code layer has already run (`lint` clean); the model sees only what code
narrowed, never every page. **Report, never rewrite**: a finding goes into the log and to the user; no page is edited
by this step, and two claims are never blended into one.

## The brief's candidates, in this order of severity

1. **Contradiction candidates**: page pairs that share atoms or tags. Read the two pages' matching sections
   (`$W show <slug> --section <h2>`), not the pages. Verdict: *contradiction* (name both pages, the conflicting
   sentences, which atoms they come from), *different scope* (say so, no finding), *evolved* (the newer atom
   supersedes: the fix is `atom supersede` and a compile).
2. **Concept gaps**: a concept linked from 2 or more pages with no page of its own. Verdict: *write a page* (it
   becomes a compile candidate once it has 3 atoms; if it has fewer, a finding "needs atoms"), or *not a concept*.
3. **Expired claims**: dated claims past the horizon (versions, dates, "as of"). Verdict: *still true* (cite the
   check), *outdated* (finding; the fix is a new atom and supersede), *unknown* (finding "verify").
4. **Branch proposals**: merge or split candidates; see [branches.md](branches.md).

## Output

One line per finding in the log, `$W log "lint: <severity> <kind> <pages or atoms>: <what>"`, then to the user a
list sorted by severity (contradictions, ghost links, orphans, gaps, expired). Fixes are the user's go or a later
compile; do not run them in this step. Write nothing when the brief has no candidates, and say so in one line.

## Cost

A brief is about 10-30k tokens: run it at most weekly, with `--changed`. An external check (a web search to
verify a claim) is corroboration only, never a replacement for the wiki's own claim, and only on request.
