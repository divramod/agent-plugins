---
name: design
description: Design a spec's or plan's feature before it is built, on one interactive page `plans/<plan>/design.html` — `/design` (alias `/d`) reads the spec.md or plan.md of the plan in the `CURRENT_PLAN` pointer, splits it into feats (a tab each), decides per feat what needs designing and which kinds (GUI as a real HTML prototype inside the app's current look; backend as current vs new flow in Mermaid, ERD in DBML diffed green/yellow/red, Excalidraw; plus acceptance scenarios, states and sequence with contract of research 0093), writes them as versioned files through `design.py new` and renders the page; a simple feat gets no design. `/design update <feat>` writes the feat's next version and keeps the old ones to compare; `/design serve` opens the page where the user toggles each design accepted and comments; `/design status` reads the review back (accepted versions, open comments) and answers the comments with updates. The page's layout is fixed (the desktop app reads it later); only `design.py` writes it. Use when the user says /design, /d, "design this feature", "make a prototype", "draw the flow / the ERD", "update the design of <feat>", "which designs are accepted", or a spec or plan needs its design. `/design h` shows help.
---

# design (alias d)

`S=<skill-dir>/scripts`. A plan folder's designs are files in `plans/<plan>/design/<feat>/<kind>/v<n>/` with a
`meta.json`, and one generated page `plans/<plan>/design.html` shows them (decisions D3-D7 of hal2 plan 0364).
`design.py` is the deterministic part: the store, the versions, the render, the review state. You only judge: what
needs designing, which kinds, and the designs' content. The folder may be a spec folder without `plan.md` (spec skill).
In a farm whose plans live in its plan store (hal2 plan 0409) the folder is a copy outside the tree whose paths
`design.py` prints absolute: write the files there, never under `plans/`; every command takes the copy in, and
`design.py apply` does after your own edits.

| Call | Does |
|---|---|
| `/design` (`/d`, `/design create`) | design the plan or spec named in the `CURRENT_PLAN` pointer: feats, kinds, first versions, render |
| `/design create <plan>` | the same for another plan folder (`364`, `0364`, its folder name) |
| `/design update <feat> [<what>]` | the feat's next version of the kinds the change touches; older versions stay (D6) |
| `/design serve` | serve the page on 127.0.0.1 so the accept toggles and comments save (D7) |
| `/design status` | per feat and kind: versions, the accepted one, the comments; then answer open comments |
| `/design h` | print this table and stop |

Every `design.py` call takes `--plan <n|slug>` (else the `CURRENT_PLAN` pointer) and `--repo <dir>`. Commands:
`new <feat> <kind> [--title T] [--base NOTE] [--json]`, `render [--out PATH]`, `list [--json]`,
`serve [--port 0] [--open]`, `status [--json]`, `accepted --json`.

## Create

1. Read the folder's `spec.md`, else `plan.md` (Goal, Brief, Context), and what they link. No folder named: ask which
   plan (one line). `python3 $S/design.py list` shows designs that already exist: then this is an update, not a create.
2. Split the feature into **feats**, the user's subfeatures: each is a tab of the page, a kebab-case name (`login`,
   `sync-status`). One feat is fine for a small feature.
3. Per feat decide **whether** it needs a design. A simple feat (a rename, a flag, a fix, a change with one obvious
   shape) needs none: say so in one line and leave it out. When no feat needs one, say so and stop: no page.
4. Per feat decide **which kinds**, by the table below: GUI where it changes what a person sees, backend kinds where it
   changes data, a flow or an interface; a feat that touches both gets both ("frontend and backend designs" on its
   tab). At most the three top kinds of research 0093 besides flow, ERD and GUI; the optional ones only where they
   apply (a premortem of research 0093: eight artifacts nobody reads).
5. Per kind: `python3 $S/design.py new <feat> <kind> --title "<title>" --base "<what it builds on>"`, then write its
   files into the printed `v1/` folder (names below). `--base` says what the design starts from: "hal9k-desktop's
   Projects view, @hal9k/ui ListDetail", "the hub schema of code/rust/libs/hal2-hub-db".
6. `python3 $S/design.py render`, then tell the user in a few lines: the feats, their kinds, the page's path, and
   `/design serve` to review it.

### Kinds

| Kind | Files | When |
|---|---|---|
| `gui` | `screen.html` (more screens: `<name>.html`); `current.html` beside `new.html` for a changed screen | a person sees it |
| `flow` | `current.mmd` beside `new.mmd` (Mermaid `flowchart`), or `flow.mmd` for a new flow | data or control moves |
| `erd` | `current.dbml` beside `new.dbml` (the page diffs them: green added, yellow changed, red removed) | stored data changes |
| `scenarios` | `scenarios.md`: table ID, Given, When, Then; happy, edge and failure rows | every designed feat (top) |
| `states` | `states.mmd` (`stateDiagram-v2`) + `matrix.md` (screen x empty, loading, error, partial, offline) | it has states (top) |
| `sequence` | `current.mmd`/`new.mmd` (`sequenceDiagram`) + `contract.md` (call, input, output, errors, latency) | it crosses a boundary (top) |
| `drawing` | `drawing.excalidraw` | a picture says it better than a diagram |
| `context`, `nfr`, `threats`, `rollout` | `context.mmd` (flowchart with subgraphs, no C4 syntax); `nfr.md`, `threats.md` (STRIDE per boundary), `rollout.md` or `rollout.mmd` (`gantt`) | optional: architecture, budgets, auth or data leaving, migrations |

`scenarios` and `sequence` are the ones the plan's steps cite (a done-when names a scenario ID), so a designed feat that
crosses a boundary gets both. Goals, non-goals and alternatives belong in the spec, not here.

### GUI: a real prototype in the current look

"gui designs should include real prototypes of the designs, brought as far, as it makes sense". A prototype is one
self-contained `.html` file the page shows in a sandboxed iframe: plain HTML, CSS and JavaScript; an npm package only
from a pinned CDN URL (`https://cdn.jsdelivr.net/npm/<pkg>@<x.y.z>/+esm`), never a build step. Clickable where the
flow matters (tabs switch, a form validates, an empty and an error state are reachable), static where it does not.
Stop where a further step costs more than it decides.

"if there is already a software with gui, the design skill should use the current look or frame": for an app that
exists, start from its current frame and put the new feature into it, so the user sees it "in real or close to be
real". For hal9k-desktop that is `@hal9k/tokens` (the `--hal9k-<group>-<name>` custom properties,
`code/typescript/libs/hal9k-tokens/tokens/`, docs/hal9k-desktop.md "Themes") and `@hal9k/ui`'s components and
templates (`code/typescript/libs/hal9k-ui/src/`, the components page `hal9k://app/components`, docs/hal9k-desktop.md
"Build a view from the templates"): copy the token values the prototype needs into its `<style>`, rebuild the window's
places (title bar, tabs, the view's scaffold) and use the components' names and shapes. Another app: its own design
system or screenshots. A new app: a plain, calm frame; say that it has no base.

### Backend: from the current schema and flow

"take the current database structure and backend architecture as base". `current.dbml` is the schema as it is today,
written from its source (migrations, the ORM's models, `designs/erd/diagrams/*.dbml`), only the tables the feat
touches and their neighbours; `new.dbml` is that file changed. Same for flows: `current.mmd` is today's flow from the
code, `new.mmd` the changed one, side by side on the page. A new thing without a current state gets only its `new.*`
or a plain `flow.mmd`.

## Update

`/design update <feat> [<what>]` ("create a new design for the feat ... so that i can then compare the old and new"):

1. `python3 $S/design.py status --json` for the feat: its versions, the accepted one, its comments. The user's words
   and the open comments say what changes.
2. Per kind the change touches: `python3 $S/design.py new <feat> <kind>`; it copies the latest version's files into
   `v<n+1>/`, so edit those. Never change an older version's folder: it is the history the user compares (D6). Kinds
   the change does not touch keep their version.
3. `python3 $S/design.py render`; tell the user which versions are new and that the page's compare view shows
   `v<n>` beside `v<n+1>`.

A new feat in an update is created as in Create, steps 3-5.

## Review: serve, accept, comment

"every design should have a toggle, if it is accepted or not and should have a comment/annotation function".

- `python3 $S/design.py serve [--open]` (a background shell): re-renders the page and serves it on 127.0.0.1 only;
  give the user the printed URL (`--open` opens it on macOS). There the toggles and comments save into the committed
  `design/state.json`. Opened from `file://`, the page shows them read-only with the serve command. Stop the server
  when the review is done (its own PID or the task, never a pattern kill).
- `/design status`: `python3 $S/design.py status --json`, then per open comment either answer it in the conversation
  (a question) or make it a change with Update (a wish). Say in one line per feat what is accepted and what is open.
- `python3 $S/design.py accepted --json` lists only the accepted versions with their file paths: the plan skill builds
  on them (D10), and an implementation step checks its result against them.
- Accepting is the user's: never set a design accepted yourself, never delete a comment you did not write.

## Rules

- The page has one fixed layout: header "plan <n> <name> - design", side nav of feats and designs, feat tabs, kind
  tabs, version tabs, prev/next, compare. It is the contract the desktop app's project view reads later (D3): never
  edit `design.html` by hand, never add a second page; change a design's files and render again.
- Only `design.py` creates versions and writes `state.json`; you write only the files inside the newest `v<n>/` you
  just created.
- The folder's `design/` and `design.html` are committed with the plan or spec (no other commit of this skill); a
  render of unchanged designs leaves git clean.
- A design file holds no secret, token, real personal data or production URL with credentials; sample data is made up.
- Called by the spec skill after `spec.md` is written, and by the plan skill's New plan when the feature changes a GUI,
  data or a flow and has no design yet (D10); it skips simple feats there as here.

Prerequisites: `scripts/check-prerequisites.sh` (python3; `open` or `xdg-open` only for `serve --open`); the page loads
Mermaid, Markdown and Excalidraw from pinned jsDelivr URLs, so it needs the network once per browser cache.
