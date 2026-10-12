# web

Blog posts, articles, essays and docs pages: any http(s) page no other source claims.
The content file `content.md` is the article as markdown, every paragraph, list and quote starting with a `[¶n]`
anchor link, plus a header (site, author, published date, extractor) and the page's description.

## Flags

```bash
hal2-cli-tell prepare "<url>" [--refresh]
```

- The page is fetched once and run through **trafilatura and defuddle**; the better text wins. Under 200 words
  (a JavaScript-only page, a teaser) it tries **Jina Reader** (renders JavaScript), then the latest **Wayback
  Machine** snapshot. The envelope's `extractor` says which one won and `attempts` lists every try.
- A page that was prepared before is reused by its canonical URL (no `www.`, tracking params or `#section`; an
  app route like `#/guide` is kept). Short links, redirects and the page's declared canonical URL all find the same
  folder. `--refresh` refetches it into the same folder, e.g. when the user says the article was updated.
- `snapshot` set means the text comes from the Wayback Machine, and the anchor links open that archived copy. Say
  which case in one line: `gone` (404/410) set means the live page no longer exists; otherwise the live page was
  cut off (paywall, JavaScript) and the archive had more.
- A URL that serves a PDF or another document is a file input, not a web page: `prepare` hands it to the file
  source by itself (the envelope's `source` is `file`; read that subskill).

## Anchor links

`[¶n](<url>#:~:text=<first words>)` is a text fragment: the browser scrolls to that paragraph and highlights it.
Headings with an id on the page get `[#](<url>#<id>)`. Copy them next to the points they support; cite the section
heading's `[#]` for a whole section. Firefox before v131 ignores text fragments and just opens the page.

## Reading

Decide what kind of page it is first; it changes what the summary should do:

- **Argument / essay / opinion:** the thesis, the steps of the argument, the evidence for each, and what the
  author concedes or leaves out. Use the template's `argument` part.
- **News / report:** who, what, when, the numbers, and who is quoted. Keep the author's claims apart from the
  sources they cite.
- **Tutorial / how-to:** the goal, the prerequisites, the steps in order and the gotchas. Keep commands and
  config verbatim (code blocks are in the content file).
- **Docs / reference page:** what it covers, the key concepts and APIs, the defaults and limits. Say which
  version it documents when the page says so.
- **Listicle / roundup:** every item with one line on why it made the list; skip the filler between them.
- **Announcement / release post:** what changed, who it affects, how to upgrade, what breaks.

## Extraction problems

- **Under ~200 words**, or the text stops mid-sentence: probably a paywall, a login wall or a mostly-visual page.
  Summarize what is there and say in one line that the article is cut off. Don't fill the gap from memory.
- **Garbled or noisy text** (menus, cookie banners, "related posts" in the middle, repeated lines): skip the
  noise; if it makes the content unreliable, say so in one line at the end.
- **Redirected to a consent or login page** (an `attempts` entry says so): the text came from Jina or the archive.
  Check that its title matches the page asked for; if it is a site's home page instead, say the page is gone.
- **A private address** (localhost, a LAN IP, a single-label or `.local`/`.internal` host): Jina and the
  Wayback Machine are skipped, so a JavaScript-only page there stays short. Say so instead of guessing the rest.
  An intranet host with a public-looking name is not detected: don't pass such URLs if they must stay private.
- **`prepare` exits 1 with "answered HTTP 403"** (a bot challenge or an error page): tell the user and
  show the attempts; the page may still open in a browser.
- **Comments** are not extracted. If the user wants the discussion, look for an HN thread (a `hn` input) instead.
- `published` can be missing: then say "undated" rather than guessing.

## Similar articles (related section)

Run 2-3 web searches: the article's topic, its central claim, and the author or site plus the topic. Pick 3-5
articles that add something: a counterpoint, a deeper dive, the original source it builds on, a more recent
update. Prefer recent ones when the topic moves fast, never the page itself, and say in one line what each adds.
Then run `hal2-cli-tell related "<dir>" --url <u1> --url <u2> ...` with your picks: it drops the article
itself and duplicates, and gives a `summary` path for those already in the library; add `([summary](<path>))` to them.

## Page and files

The summary's header shows the author, the date and a link to the site; the full `content.md` (with the
archived-copy line when a snapshot was used) is in the collapsed **Article** section below the summary. The folder
`articles/<site>/<title>/` holds `summary.md`, `content.md` and `metadata.json` (`extras`: description, language,
image, attempts, snapshot).

## Commands

| Command | Does |
|---|---|
| `hal2-cli-tell related "<dir>" --url …` | candidate similar-article URLs → deduped, the article itself dropped, library summaries marked |
| `hal2-cli-tell web extract "<url>"` | the raw extractor result (trafilatura + defuddle in parallel, the better text wins → Jina Reader → Wayback), for debugging |
