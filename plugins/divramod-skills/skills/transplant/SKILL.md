---
name: transplant
description: Transplant a foreman — move it with everything it has grown (its branch, plan, handoff, servants) from one field to another, so it carries on there and the old field is reset to the barn and free (hal2 plan 0286). `/transplant 09` in a foreman's field moves that foreman to field 09; `/transplant 34 09` (the farmer's or the steward's session) moves the foreman of a field that has no live session; `--dry-run` shows every check and changes nothing; `/transplant cancel` ends a prepared one; `/transplant history` lists the earlier ones. It runs the checks, prepares and reserves the target, frees the target of a resting session, has the foreman hand off and commit, drives `hal2-cli-git worktree transplant`, pushes, tells the servants and the farmer and starts the foreman in the target with `/handoff c`. Only the user starts it. Use when the user says /transplant, "transplant 34 to 09", "umpflanzen", "move this foreman to field 09" or "move the foreman to another worktree". `/transplant h` shows help.
---

# transplant

Moves a foreman to another field and leaves a record of it (`hal2-cli-git worktree transplants` is the history).
`S=<skill-dir>/scripts`, `T="python3 $S/transplant.py"`, `H=hal2-cli-git`. The command changes two fields and resets
one; this skill does what needs a session around it. Read a JSON's `status` and `refused.reason`, never its prose.

| Call | Does |
|---|---|
| `/transplant <to>` | in the foreman's own field: move this foreman to field `<to>` and carry on there in a new session |
| `/transplant <from> <to>` | in the farmer's session (or the steward's on a farm without a farmer): move the foreman of field `<from>`, which has no live session |
| `/transplant --dry-run <to>` | (also `--dry-run <from> <to>`) run every check, print them and what would happen, change nothing |
| `/transplant cancel [<from>]` | end a prepared transplant of this field (or of `<from>`): the target is free again |
| `/transplant history` | the earlier transplants, newest first (`$H worktree transplants`; `--limit <n>`) |
| `/transplant h`, `/transplant help` | print this table and stop |

## Who starts it

Only the user: `/transplant <to>` typed in the foreman's session, or the user's order to the farmer or the steward
("transplant 34 to 09"). Never a plan, a foreman on its own, the farmer's tick or another session's idea (hal2 plan
0286, D11). The user's `/transplant` is the consent for everything below, the pushes included: the skill asks nothing
unless a step says so. A field with a **live session** is never driven from another session: the order goes to that
session as a relayed decision and it runs `/transplant <to>` itself.

## Run

1. **Check.** `$T check [<from>] <to>` (`<to>` and `<from>` are numbers, `7` is `07`; without `<from>` it is this
   session's field). Exit 0: the JSON has the dry run's `checks` and `would`. With `--dry-run` print them as a table
   (check, ok, why) and the `would` line, and stop. Exit 1: its `stop` says why, `advice` what to do; tell the user
   and end the skill (nothing was changed):
   - `no-command`: the installed `hal2-cli-git` has no `worktree transplant` yet (it comes with the plan's bring in;
     `bash $S/check-prerequisites.sh` says so too). Say so, end.
   - `live-session`: send the user's order to that session (SendMessage; in the farmer's session with an ack id from
     `acks.py instruct`): `the user decided: "<their words>"`, it runs `/transplant <to>`. End.
   - `disk`: the target must be created and the disk is short; prune a field, run the same command again.
   - `refused`: `reason`, the `files` and `advice` (also `$T advice <reason> <from> <to>`).
   - `call` (name the source), `error` (the message). Exit 2: a tool is missing: `bash $S/install-prerequisites.sh`.
2. **Prepare.** `$H worktree transplant <from> <to> --prepare --json`: `status` ok means the checks held, the record
   exists (`prepared`) and the target is kept (its `plans/CURRENT_PLAN` holds `transplant-from-<from>`). Anything
   else: say the reason with its advice, end.
3. **Free the target.** `$T free <from> <to>`: an idle session in the target is stopped by signal through
   [delete-field](../delete-field/SKILL.md)'s `stop.py`. Exit 3: it refused (a draft,
   background tasks, a session that started to work) and cancelled the transplant itself, nothing was moved: tell
   the user the `refused` text, end. A stopped session is not restarted.
4. **Hand off and commit** (only where this session is in `<from>`; for a field without a session skip to 5). Running
   hands finish their piece or are stopped with their state written into their step file. Then `/handoff`
   ([handoff](../handoff/SKILL.md): it records decisions and commits the docs), its first paragraph reading:
   `Transplanted from field <from> to field <to> on <date>. The foreman continues in field <to>, not here: run /mfm
   first, then carry on from Next. The branch line names field <from>; this handoff is field <to>'s own now.` Then
   commit everything the plan changed (code, plan files; never secrets, git-ignored files stay). `git status
   --porcelain` must be empty afterwards: the drive refuses `dirty`.
5. **Push the source.** Where the farm has an origin (`git remote get-url origin`): `git -C <from's folder> push -u
   origin HEAD` (the folder is in `git worktree list`). A failed push (offline) is reported and does not stop the
   transplant: the drive needs no network.
6. **Drive.** `$H worktree transplant <from> <to> --json`; `status` ok: the record (`state` arrived, `tip`, `plan`,
   `servants`, `side_branches`) is what you report. Otherwise (`refused` or `error`): `$T advice <reason> <from>
   <to>`, tell the user, end. The transplant stays prepared (a `conflict`: `/mfm` in the source, commit, run
   the same command again) or is cancelled as the JSON says; **never reset a field by hand**: a drive whose process
   died halfway is adopted by running the same command again, and `/transplant cancel` ends a prepared one.
   While a transplant is open (`prepared` or `driven`) the tollman never takes its two fields for orphans, however
   old it is, and never starts `/handoff c` in the source of a `driven` one; one open for over 60 minutes it reports
   to the farmer once, who finishes it by the same command or ends it with `/transplant cancel <from>` (plan 0294).
7. **Push the target.** `$T push <from> <to>`: the target's branch (`git push -u origin HEAD` in it); and, only from
   the old field's own session, once origin's `<to>` holds the tip origin's `<from>` holds, origin's `<from>` made the
   barn's too (a lease push, a plain one where the barn holds the tip already). `old` says which (`lease`, `plain`,
   `same`, `absent`, `none`, `kept`); for `kept` (from the farmer's or the steward's session, always) repeat its
   `note`: `origin/<from>` still holds the old tip, it is the old field's next push or the farmer's to remove, never
   force-pushed from here.
8. **Tell them** (SendMessage; find each session with `ListAgents`, its name `<repo>-<field>`, never a stale name;
   in the farmer's session with an ack id): each field of the record's `servants`: `your foreman is field <to> now
   (transplanted from <from> on <date>); report there`; the farmer `farmer-<repo>` (not when this is the farmer):
   `transplanted <from> to <to>, tip <tip7>, plan <plan>; field <from> is reset to the barn and free: remove it once
   its session has stopped`.
9. **Start the foreman.** `$T start <to>`: refuses unless the drive happened; leaves a session that runs in the
   target already and names it; else starts `/handoff c` there through `hal2-cli-git worktree run` at the model and
   effort of the plan's `run` ([create-worktree-session](../create-worktree-session/SKILL.md)'s `start`). Never
   `claude` itself, never `/exit`.
10. **End the turn** with three lines and start nothing new: `Transplanted field <from> to field <to>, tip <tip7>,
    plan <plan>.` / `The foreman runs in field <to> (<pane>); servants told: <fields or none>.` / `This session is
    idle in field <from>, free: <note of step 7 when kept>.` A session in `<from>` stays, idle: the farmer removes
    the field once the session has stopped.

`/transplant cancel [<from>]`: `$H worktree transplant <from> --cancel --json` (`<from>` is this field's name by
default); `status` ok: `cancelled`, the target's marker is given back; `not-prepared`: nothing was prepared, or its
work is in the target already (driven, or a drive that died halfway): the `detail` names the command that finishes it,
which only the user's order runs. A session that `free` stopped is not restarted.

## What it never does

Start `claude`, type `/exit`, reset or remove a field, force-push anything but step 7's guarded lease push from the
old field's own session, drive a field with a live session from outside, or run on a plan's or the tick's say.
