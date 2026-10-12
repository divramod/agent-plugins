# hn

Hacker News threads: the linked article and the discussion about it, in one summary with two parts.
The content file `content.md` has a header (points, comment count, the article's URL), `## Article` (the linked
page through the web source's extractor, with `[¶n]` paragraph anchors, or the post's own text for Ask HN / Show
HN / Tell HN), and `## Discussion`: one `### Thread n (k comments)` per top-level comment in HN's ranking, one
line per comment:

```
- **author** [→](https://news.ycombinator.com/item?id=<comment id>) (depth n, reply to <author>): text
```

## Flags

```bash
hal2-cli-tell prepare "<news.ycombinator.com/item?id=N>" [--refresh] [--no-article]
```

- A comment link prepares its whole story; the envelope's `focus_comment` names that comment. When the user
  linked a comment, open the summary with what that comment and its replies say, then the rest.
- A thread that was prepared before is reused by the story id. `--refresh` refetches it into the same folder:
  use it when the thread is young (hours old) or the user says the discussion has grown.
- `--no-article` skips the linked page (the user only wants the discussion).
- The tree comes from Algolia; when Algolia lags behind (a busy new post) the official API is walked instead
  (`extractor: firebase`). A comment that could not be fetched there is left out and counted in `attempts`:
  say so if it matters. Deleted and dead comments are dropped; their replies stay (`reply to [deleted]`).
- A Show HN that links a page and has text keeps the author's text first in `## Article`, then the page.
- The article can fail (paywall, a bot challenge, a PDF): `## Article` then says why in one italic line and the
  discussion is still there. Summarize the article from what commenters quote and say so; never from memory.

## Reading

1. **The article first**, in the mode's shape, under `## The article` (the template). Read it the way the web
   subskill says ([subskills/web/SUBSKILL.md](../web/SUBSKILL.md) → Reading). An Ask HN has no article: summarize
   the question instead, in two or three sentences. The article is fetched today: for a thread months or years
   old, the page may have changed (a landing page, a rewritten README). When commenters discuss or quote things
   the article no longer says, say so in one line and take those claims from the quotes, not the page.
2. **Then the discussion**, under `## The discussion`, following
   [subskills/shared/discussion.md](../shared/discussion.md): themes with attributed verbatim quotes.
   - Work thread by thread (`### Thread n`): the first threads are the ones HN ranks highest, but a big
     subthread deep down can carry the strongest disagreement.
   - For more than ~300 comments, read the top ~15 threads in full and skim the rest for first-hand reports
     and corrections.
   - Say what the thread adds to the article: corrections, first-hand experience, prior art, the author
     replying (the header's `posted by` may be the author; commenters often say so).
   - Link a comment with its `[→]` permalink, copied from the content file.
3. **Check the quotes** before saving:

   ```bash
   hal2-cli-tell check-quotes "<dir>" <<'EOF'
   <body>
   EOF
   ```

   Every `NOT FOUND:` line is a quote that is not verbatim in `content.md`: copy the real wording or turn it into
   a paraphrase without quote marks, then check again.

## Past discussions (related section)

```bash
hal2-cli-tell related "<dir>"
```

It lists other HN threads about the same article (most comments first) and marks those already summarized.
List the ones with comments (at most 5), each with its date and one line on how it differed (it may be years
older); add `([summary](<path>))` when the output gives one. Comments that flag a dupe or link an earlier thread
("[dupe]", "Earlier: item?id=…") point at submissions of other URLs (the project page, the repo): add those
too, with the comment's `[→]` link. Nothing from either: no section.

## Page and files

The summary's header shows who posted it, the date and a link to the thread; the full `content.md` (article and
discussion) is in the collapsed section below the summary. The folder `discussions/hn/<title>-<id>/` holds
`summary.md`, `content.md` and `metadata.json` (`extras`: points, comments, threads,
article_url, article_extractor, article_words, snapshot, api).
