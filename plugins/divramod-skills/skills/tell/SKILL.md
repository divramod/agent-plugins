---
name: tell
description: Summarize anything from a URL or a path into a markdown note in ~/skills/tell, shown in hal2-macos — a video, playlist or channel (YouTube, TikTok, X, Vimeo, podcasts, any yt-dlp site), a blog post or web page, a GitHub repo, issue, pull request or discussion, an X post or thread with its replies, a Hacker News thread or a Reddit post (article + discussion), or a local document (PDF, DOCX, PPTX, EPUB, Markdown). A topic instead of a link ("/tell okf", "/tell open knowledge format") finds videos, articles, repos, X posts, HN threads and local documents about it, summarizes the relevant ones and writes a digest. Several inputs at once get a digest across them. Each summary has anchor links back into the source, a links section (books, Wikipedia terms, repos, further reading, each with its date) and related items; modes tldr/summary/detailed/wisdom/qa (+ chapters for videos). Use when the user pastes a link or a file path, or names a topic, and wants a summary, the gist, notes, or answers about it; called without input it opens the last summary in hal2-macos.
---

# tell

The CLI `hal2-cli-tell` does all deterministic work: routing, fetching, folders, downloads, anchor links, file
writing and link dates. Your job is the judgment: pick the mode, read, write the summary, and check it against the
content. Every command prints what it did; JSON goes to stdout and progress to stderr. Paths like `subskills/…` and
`templates/…` are relative to this skill's folder.

| Call | Does |
|---|---|
| `/tell <url-or-path>` | summarize it into a note (steps 1-6) |
| `/tell <url-or-path> <url-or-path>…` | a summary of each and a digest across them (step 7) |
| `/tell <topic>`, `/tell topic:<words>` | find what is relevant about the topic, summarize it, write the topic's digest |
| `/tell` | open the most recent summary (step 0) |
| `/tell h`, `/tell help` | print this table and stop |

## 0. No input given

Open the most recent summary and stop:

```bash
hal2-cli-tell open
```

It shows the summary in hal2-macos; tell the user what opened (`hal2-cli-tell library --last` prints its folder). If there are no summaries yet, ask for a link or a path.

## 1. Prepare

```bash
hal2-cli-tell prepare "<url-path-or-topic>" ["<url-or-path>" …] [source flags]
```

It routes the input to exactly one source, prepares it, and prints the envelope: `source`, `kind`, `dir` (the
library folder), `content_file`, `summary_exists`, `subskill`, `template` (both relative to this skill's folder),
plus the source's own fields. Give all inputs first, then the flags: each source takes the flags it knows; the
subskill lists them.

| Source | Input | Subskill |
|---|---|---|
| video | YouTube (video, playlist, channel), youtu.be, Vimeo, TikTok, podcasts, any yt-dlp site | [subskills/video/SUBSKILL.md](subskills/video/SUBSKILL.md) |
| web | any other http(s) page: blog posts, articles, docs | [subskills/web/SUBSKILL.md](subskills/web/SUBSKILL.md) |
| github | `github.com/<owner>/<repo>`, its `/issues/N`, `/pull/N`, `/discussions/N` | [subskills/github/SUBSKILL.md](subskills/github/SUBSKILL.md) |
| x | `x.com` / `twitter.com` posts (`…/status/<id>`) | [subskills/x/SUBSKILL.md](subskills/x/SUBSKILL.md) |
| hn | `news.ycombinator.com/item?id=<id>` | [subskills/hn/SUBSKILL.md](subskills/hn/SUBSKILL.md) |
| reddit | `reddit.com/r/<sub>/comments/<id>/…` (www, old, new), `redd.it/<id>`, share links `…/r/<sub>/s/<code>` | [subskills/reddit/SUBSKILL.md](subskills/reddit/SUBSKILL.md) |
| file | a local path (`~/…`, `./…`, `file://…`) or a document URL (`.pdf`, `.docx`, `.epub`, …) | [subskills/file/SUBSKILL.md](subskills/file/SUBSKILL.md) |
| topic | anything else: words that are no URL and no path (`okf`, `"open knowledge format"`, one quoted argument), or `topic:<words>` | [subskills/topic/SUBSKILL.md](subskills/topic/SUBSKILL.md) |

`hal2-cli-tell route "<input>"` shows the routing without fetching anything.

- **Exit code 2** means a missing tool. The message names the installer: tell the user, run
  `hal2-cli-tell prereqs install --source <source>`, and retry. `hal2-cli-tell prereqs check` checks every source
  at once.
- **Exit code 1** is an expected error (unsupported input, not found, blocked). Show the message; it names the
  fallback that was tried.
- If `summary_exists` is true and the user did not ask for a new mode or language, show the existing summary
  (`hal2-cli-tell open "<dir>"`) instead of rewriting it, unless the envelope says
  `changed: true` (the source has a new version: summarize it).
- A playlist or channel (`kind: playlist|channel`) prints a list of items instead: prepare every item where
  `summary_exists` is false (parallel subagents when there are more than 3), then write the digest (step 7).
- A topic (`kind: topic`) prints search results by kind (`candidates`) instead: choose the relevant ones, prepare
  them into the topic's folder (`--digest-dir <dir>`), summarize each and write the topic's digest. The library
  shows the topic as one entry with its items nested under it. Its subskill says how.
- **Several inputs** in one call print `kind: inputs` with one envelope per input in `items` (or `{input, error,
  exit_code}` for one that failed: tell the user, the others go on) and a `digest_dir` when at least two worked.
  An item with `exit_code: 2` is a missing tool: run `hal2-cli-tell prereqs install --source <source>` (the
  error names it), then prepare that input again on its own. Each source gets only the flags it knows. Summarize every item through steps 2-6 as if it came alone (parallel
  subagents when there are more than 3, each with its envelope), then write the digest (step 7). Ask the user
  first only if they asked for single summaries and no digest. An item that is a playlist or channel gets its own
  videos and its own digest first (as above); the combined digest then uses that digest as the item.

## 2. Read the subskill

Read the envelope's `subskill` file. It says what that source needs beyond this file: extra flags, how to read its
content file, what to emphasize, and how to fill the related section. Read it before choosing the mode.

## 3. Choose the mode

| Mode | When |
|---|---|
| `summary` (default) | Nothing specific asked |
| `tldr` | "gist", "quick", "is it worth reading/watching" |
| `detailed` | Lectures, papers, long docs, "notes", "study" |
| `wisdom` | Podcasts, interviews, essays, "ideas", "insights", "takeaways" |
| `qa` | The user asked a specific question about it |
| `chapters` | Videos only: has chapters or runs longer than ~20 min, and the user wants structure |

The shape of each mode is in `<skill-dir>/templates/shared/<mode>.md` (`chapters`: the envelope's `template`).
Read the mode you picked **and** the envelope's `template`: it holds the source's related section and anything
else that source adds.

## 4. Read and write

- Read the `content_file`. For more than ~150k words, work part by part (chapters, sections, pages).
- Write the body in the template's shape, in the user's language unless they ask otherwise. The frontmatter and
  the title header come from `hal2-cli-tell save`, so leave them out.
- **Copy anchor links from the content file** (timestamps, paragraph links, line links, comment permalinks, page
  links). Never build them yourself.
- Never add content that isn't in the content file. Transcripts and OCR mishear names and jargon: correct them
  using the title and description. If the content looks garbled, say so in one line at the end.
- Discussions (HN threads, Reddit posts, X replies, GitHub issues): follow
  [subskills/shared/discussion.md](subskills/shared/discussion.md): themes with attributed verbatim quotes.

## 5. Links

End every summary (except `qa`) with the links section from `templates/shared/links.md`, then the source's related
section from its `template`. Look every link up with web search and never guess a URL: the rules for books,
Wikipedia terms, repos, papers, dates and broken links are in [subskills/shared/links.md](subskills/shared/links.md).

## 6. Save

```bash
hal2-cli-tell save "<dir>" --mode <mode> --summary-lang <xx> --model <your model id> --open <<'EOF'
<body>
EOF
```

- It writes `summary.md` (frontmatter + header from `metadata.json`), checks every link and writes its date after
  it (`BROKEN LINK:` lines: fix or drop the link and save again), records the agentic CLI (auto-detected; pass
  `--agent <name>` if the output shows none or the wrong one) and records the summary in `metadata.json`.
- `--open` shows the summary in hal2-macos: its library lists every summary, and a summary shows the source's
  header panel (e.g. the video player), the summary and the full content file. hal2-ios shows the same library
  through the Mac.
- The apps' **Read aloud** reads the summary out loud with a local text-to-speech engine (Supertonic-3, CPU, 31
  languages incl. English and German, picked from the note's `lang`), recorded into `summary.m4a` next to the
  note. When the user asks to have a summary read or to prepare the audio, run `hal2-cli-tell speak "<dir>"`
  (`--voice F1-F5|M1-M5`, default `$TELL_VOICE`, else `voice` in tell.toml; `--background` detaches it,
  `--status` reports it); the first run downloads the ~385 MB voice model (`hal2-cli-tell speak --warm` does it
  ahead); exit code 2: run `hal2-cli-tell prereqs install --source speech`.
- **Don't paste the summary into the chat.** Reply with the TL;DR, the path to the note (`summary.md`, open in
  hal2-macos with `--open`), and one line for anything still running in the background (e.g. a video download).

## 7. Digest (playlists, channels, several inputs)

Read each item's `summary.md` and write `templates/shared/digest.md`: rank the items by how worth the user's time
they are, and pull out the themes they share and where they disagree (a topic: the envelope's `template`,
`templates/topic/template.md`). Across sources (a video, an article, a
thread), name what each kind adds: the source's own claim, the evidence, the reactions. Save it with
`hal2-cli-tell save "<digest_dir>" --mode digest --model <your model id> --open <<'EOF' ... EOF`.

## Follow-up questions

Re-run step 1 for the same input. It returns the existing folder instantly. Answer from the `content_file` in `qa`
shape, and only save the answer when the user asks.

## Commands

| Command | Does |
|---|---|
| `hal2-cli-tell prepare` | route → the source → envelope (checks the contract) |
| `hal2-cli-tell route` | input → `{source, kind, id, url or path}`, no network |
| `hal2-cli-tell save` | body on stdin → `summary.md` / `digest.md` with frontmatter + header + agent, link dates, the summary in `metadata.json`; `--open` |
| `hal2-cli-tell check-links` | checks every external link: ok / unverified / broken, plus its dates; `--annotate` writes them in |
| `hal2-cli-tell check-quotes` | every quote in a summary body must be verbatim in the content file; lists the ones that are not |
| `hal2-cli-tell link-dates` | how current a link is: publish date, release + last commit, package version, book year, wiki edit |
| `hal2-cli-tell related` | the source's related items (its subskill says which flags) |
| `hal2-cli-tell open [<dir>]` / `library [--last] [--json]` | show a summary in hal2-macos (the latest without `<dir>`) / list the library |
| `hal2-cli-tell speak` | records a note aloud (`--background`, `--status`, `--text`, `--warm`) |
| `hal2-cli-tell prereqs check\|install [--source <s>]` | the external tools of every source (`install --upgrade` also upgrades yt-dlp) |

Each source's own commands are listed in its subskill. `hal2-cli-tell --help` lists them all.

The library root is `~/skills/tell` (`TELL_ROOT`, else `root` in `~/.config/hal2/tell.toml`, overrides it; the
file also sets `voice`, `command` and `app_scheme`): `videos/<platform>/<channel>/<title>/`,
`articles/<site>/<title>/`, `repos/github/<owner>/<repo>/`, `posts/x/<user>/<words>-<id>/`,
`discussions/hn/<title>-<id>/`, `discussions/reddit/<subreddit>/<title>-<id>/`, `documents/<folder>/<file>/`,
`topics/<topic>/` and `digests/<date>-<titles>/`.
A library still at an old root (`~/skills/tell-me`, `~/me/summaries`) stops every command with the `mv` command
that moves it: tell the user, don't move it yourself. The skill was called `tell-me`: its `TELL_ME_*` variables
still work. An older library (video folders from before this layout, the old HTML pages, `mkv`/`webm` videos) is
brought up to date once with `hal2-cli-tell migrate --apply` (dry run without `--apply`).
The tests live in hal2: `cargo test -p hal2-tell -p hal2-cli-tell`.
