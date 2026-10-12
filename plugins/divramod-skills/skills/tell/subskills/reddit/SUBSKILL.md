# reddit

Reddit posts: the post's own text, the page it links to, and the discussion, in one summary.
The content file `content.md` has a header (subreddit, score and upvote ratio, comment count, flair, the linked
article or media), `## Post` (the post's text with a `[→]` link to it), `## Article` (a link post's page through the
web source's extractor, with `[¶n]` paragraph anchors) and `## Discussion`: one `### Thread n (k comments)` per
top-level comment, best first, one line per comment:

```
- **author** (OP) [→](https://www.reddit.com/r/<sub>/comments/<post>/_/<comment>/) (depth n, reply to <author>, 12 points): text
```

`(OP)` marks the post's author, `(mod)` a moderator speaking as one.

## Flags

```bash
hal2-cli-tell prepare "<reddit post, comment or share link>" [--refresh] [--no-article]
```

- Every link form works: `reddit.com/r/<sub>/comments/<id>/…` (www, old, new, np), `redd.it/<id>`, a share link
  `reddit.com/r/<sub>/s/<code>` (resolved to its post first) and a comment link, which prepares the whole post;
  the envelope's `focus_comment` names that comment. When the user linked a comment, open the summary with what
  that comment and its replies say, then the rest.
- A post that was prepared before is reused by its id. `--refresh` refetches it into the same folder: use it when
  the post is young (hours old) or the user says the discussion has grown.
- `--no-article` skips the linked page (the user only wants the discussion).
- Where the data comes from (`api` in the envelope): Reddit's JSON (`reddit`), Reddit with an app token
  (`oauth`, when `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are set) or the Arctic Shift archive (`arctic`).
  Reddit blocks anonymous requests from many networks (`attempts` says so); the archive then has the full tree,
  but for a post younger than ~36 hours its scores and newest comments are still missing: the header says so,
  and so should the summary, in one line. When no API answers, tell the user how to set up a free Reddit app
  (the error says how).
- `not_loaded` counts comments Reddit folded behind "load more": they are not in the content file. Say so if it
  is a large share of `num_comments`.
- A video or image post (`media` in the envelope) has no article: summarize the title, the text and the
  discussion. For the video itself, offer to run the skill on the `media` URL (a `v.redd.it` link goes to the
  video source).
- A crosspost's text and link are its parent's; the header names the subreddit it came from.

## Reading

1. **The original first**, under `## The post` (the template): the post's text, and for a link post the article in
   the mode's shape, read the way the web subskill says ([subskills/web/SUBSKILL.md](../web/SUBSKILL.md) →
   Reading). A question post ("How do I…", "Should I…") is summarized as the question in two or three sentences.
2. **Then the discussion**, under `## The discussion`, following
   [subskills/shared/discussion.md](../shared/discussion.md): themes with attributed verbatim quotes.
   - Scores show what the subreddit agreed with; a question post's best answers are usually its top threads.
     Say when the top answer and the OP's replies (`(OP)`) disagree or when the OP changed their mind.
   - For more than ~300 comments, read the top ~15 threads in full and skim the rest for first-hand reports and
     corrections.
   - Link a comment with its `[→]` permalink, copied from the content file.
3. **Check the quotes** before saving:

   ```bash
   hal2-cli-tell check-quotes "<dir>" <<'EOF'
   <body>
   EOF
   ```

   Every `NOT FOUND:` line is a quote that is not verbatim in `content.md`: copy the real wording or turn it into
   a paraphrase without quote marks, then check again.

## Other posts of the article (related section)

```bash
hal2-cli-tell related "<dir>"
```

For a link post it lists other Reddit posts of the same page (other subreddits, earlier submissions; most
comments first) and marks those already summarized. List the ones with comments (at most 5), each with its
subreddit, date and one line on how the reaction differed; add `([summary](<path>))` when the output gives one.
A Hacker News thread about the same page is related too when the library has one (`discussions/hn/`). Nothing
from either: no section.

## Page and files

The summary's header shows the subreddit, score, comment count and a link to the post; the full `content.md` is in the
collapsed section below the summary. The folder `discussions/reddit/<subreddit>/<title>-<id>/` holds
`summary.md`, `content.md` and `metadata.json` (`extras`: subreddit, score, upvote_ratio, comments,
num_comments, threads, not_loaded, flair, article_url, media, crosspost_from, over_18, api, attempts, and the
article's facts).
