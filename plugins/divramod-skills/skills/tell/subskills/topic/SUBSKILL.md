# topic

A topic instead of a link: `/tell okf`, `/tell open knowledge format`. Every input that is neither a URL nor a path
is a topic (`topic:<words>` forces it, e.g. for a topic that looks like a host or a file name). A topic has no
content of its own: like a playlist, its envelope lists candidates. You choose the relevant ones, each gets its own
summary through its own source, and the digest across them lands in the topic's folder.

## Flags

```bash
hal2-cli-tell prepare "<topic>" [--also "<query>" …] [--limit 8] [--only video,web,github,hn,file] [--dir <folder> …]
```

Pass the whole topic as **one quoted argument** (`"open knowledge format"`, not three words: three inputs would be
three topics).

- It searches YouTube (yt-dlp), the web (Bing), GitHub repos, Hacker News stories (Algolia) and local documents
  (Spotlight on macOS, else ripgrep over the text formats; default: the home folder, `--dir` or
  `$TELL_TOPIC_DIRS`, folders split by `:`, narrow it) for the topic and every `--also` query. A web result that is
  a repo, a video, an X post, an HN or a Reddit thread is listed under that kind.
- Library items whose summary names the topic come first (`found: library`). Every candidate that is already
  summarized has `summary_exists: true` and its `dir`: preparing it again is instant.
- `notes` names each search that failed (tell the user in one line) and always the X note: **X has no search
  without a login.** Run your own web search (`site:x.com <topic>`, also for the `--also` names) and take the post
  links (`x.com/<user>/status/<id>`) of the posts that are really about it.
- `digest_exists: true` and the user did not ask for a new look: show the digest in hal2-macos
  (`hal2-cli-tell open "<dir>"`). Topics move fast: offer to search again.

## Choosing

1. **Is the topic what the results are about?** An abbreviation (`okf`) or a common word matches several things
   (the Open Knowledge Format, the Open Knowledge Foundation, a band). Read the titles and snippets: when one
   meaning dominates and fits the user's context, run prepare again with `--also "<full name>"`; when two are
   plausible, ask the user which one (AskUserQuestion) before summarizing anything.
2. **Pick the items worth the user's time**, about 8-12 in all:
   - the primary sources first: the official announcement or spec, the project's repo, the creator's talk;
   - 2-3 videos (an explainer and a critical or hands-on one beat three alike);
   - 2-4 articles (the announcement, an independent explainer, a critique);
   - 1-3 repos (the reference implementation, the most used tool; stars and the last push say how alive it is);
   - 1-2 HN threads with a real discussion (comments > 10), 1-3 X posts with substance, not reactions;
   - local documents only when they are about the topic, not when the word merely occurs in them (a scan, a log).
     They are the user's own notes: name the ones you found, even the ones you skip.

   Skip duplicates (a repost of the same article, the same talk twice), SEO filler (a "complete guide" with no
   author) and results about another meaning.
3. Tell the user the list (one line each: kind, title, why) and go on, unless they asked to choose themselves.

## Preparing and summarizing the chosen items

```bash
hal2-cli-tell prepare "<input 1>" "<input 2>" … --digest-dir "<topic dir>" [source flags]
```

Take each candidate's `input` as it is (a URL or a path), plus the X links from your own search. Every item is then
an ordinary input: follow SKILL.md steps 2-6 for each (its own subskill, the default mode `summary`, parallel
subagents when there are more than 3, each handed its envelope from this call), without opening each summary. Items
with `summary_exists` are not rewritten. When you add items later, pass the earlier ones again: the call replaces
the topic's item list.

**One library entry per topic.** Each item the topic creates is marked `topic_only` in its `metadata.json`: the
library lists it under the topic's entry, not on its own. Items that were in the library before stay
where they are (and are listed under the topic too). So never run `hal2-cli-tell prepare` for a single item again (a
subagent re-preparing "its" item would drop the mark and list the item on its own); that is only right when the
user asks about that item directly.

## The digest

Write the topic's digest in the shape of `templates/topic/template.md` (the envelope's `template`; the second
prepare prints it too): what the topic is, the ranking, what each kind of source adds, the themes and the splits,
then the links section and the candidates you did not summarize. Save it into the topic's folder:

```bash
hal2-cli-tell save "<topic dir>" --mode digest --summary-lang <xx> --model <your model id> --open < body.md
```

(or the body on stdin as in SKILL.md step 6).

## Page and files

The folder `topics/<topic>/` holds `metadata.json` (kind: digest, `queries`, `items`), `candidates.md` (the search results section of its summary), `candidates.json` (every
search result by kind, with the notes) and, once saved, `digest.md`. The library lists it with the
digests.
