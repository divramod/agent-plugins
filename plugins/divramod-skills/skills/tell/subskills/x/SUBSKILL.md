# x

X (Twitter) posts and threads, with their replies and the transcript of a video in them.
The content file `content.md` has a header (author, date, views/likes/reposts/replies), `## Thread` (the author's
chain, one `### n/N [→](<permalink>)` per post with its quoted post, photos, video, poll, link card and community
note), `## Video` (the transcript of the thread's first video, when it has one) and `## Replies`, one line per
reply:

```
- **@user** [→](https://x.com/user/status/<id>) (n likes, reply to @user): text
```

## Flags

```bash
hal2-cli-tell prepare "<x.com/…/status/<id>>" [--refresh] [--max-replies N] [--skip-download] [--no-video] \
  [--refresh-video]
```

- A link to any post of a thread prepares the whole thread from its first post; the envelope's `focus_post` names
  the linked post (the `### n/N [→](…/status/<focus_post>)` post in `## Thread`; `content.md` does not mark it,
  since the same folder serves every link into the thread). When it is set, say what that post adds first.
- A post that replies to someone else's post gets that post under `## In reply to`, as context: summarize the
  linked post, not the one it answers.
- A thread that was prepared before is reused (by any of its post ids; each new link is kept as an alias).
  `--refresh` refetches it into the same folder: use it when the post is young (hours old) or the user says the
  replies have grown. It keeps the video's transcript when the video is the same; `--refresh-video` makes it anew.
- Replies: up to `--max-replies` (default 200), top-level replies by likes, answers right below the reply they
  answer. FxTwitter often returns only its first page (about 40–70 replies, most-liked and newest merged; the
  envelope's `attempts` says `next page answered code 404`): for a post with thousands of replies the list is a
  sample of the most-liked, and the summary says so in one line. `--max-replies 0` skips them.
- The data comes from FxTwitter (unofficial). When it fails, X's embed endpoint gives the post alone (`api:
  syndication`: no thread, no replies): say so. A deleted, suspended or protected post exits 1 with the reason. A
  thread longer than 25 posts above the linked one is cut at the top (`attempts` says so): say so.
- Post and reply text in `content.md` is escaped where a line would start markdown structure (`\## …`, `\>`,
  `` \``` ``): drop the backslash when quoting; `hal2-cli-tell check-quotes` ignores it.
- **Video**: the thread's first video (not a GIF) goes through the video source: its transcript is `## Video` (the
  whole file is `video-transcript.md`), and the video downloads in the background in the best quality into the
  same folder, as for videos ([subskills/video/SUBSKILL.md](../video/SUBSKILL.md)). `--skip-download` only when the
  user says not to keep the video; `--no-video` skips the video part. Further videos (a post with several, or
  later posts) are listed under `## Video` as not transcribed and noted in `attempts`: say so when they matter.
  Without yt-dlp the part is skipped and `attempts` says to run `hal2-cli-tell prereqs install --source video`: run it
  and `--refresh-video` if the video matters. Any other video failure is `video: the video source failed (…)`.

## Reading

1. **The post or thread first**, in the mode's shape (the template): what the author claims, shows or announces,
   with the posts' `[→]` links. A thread is one text, not a list of posts: summarize it as one argument. Quoted
   posts and link cards are part of what the author says; the video's transcript is often the actual content
   (a demo, a talk clip): take it from `## Video`, with its timestamps, never from the post text alone.
2. **A community note** is a correction: put it near the top, in one sentence, with the post's link.
3. **Then the reactions**, under `## The reactions`, following
   [subskills/shared/discussion.md](../shared/discussion.md): themes with attributed verbatim quotes, the author
   as `**@user**` and the reply's `[→]` link. Replies on X are short and many are jokes, emoji or ads: skip those,
   and don't pad a theme with one-word agreement. Replies by the post's author (`reply to @…`) often correct or
   extend the post: use them.
4. **Check the quotes** before saving:

   ```bash
   hal2-cli-tell check-quotes "<dir>" <<'EOF'
   <body>
   EOF
   ```

   Every `NOT FOUND:` line is a quote that is not verbatim in `content.md`: copy the real wording or paraphrase
   without quote marks, then check again.

## Links (related section)

There is no `hal2-cli-tell related` for X. The section lists what the thread points to: the links in the posts and link
cards (an article, a repo, a paper; each with one line on what it is), the quoted posts, and the best links
repliers posted. Nothing linked: no section.

## Page and files

The summary's header shows the author, the date and the post link; the full `content.md` is in the collapsed "Posts"
section. The folder `posts/x/<user>/<first-words>-<id>/` holds `summary.md`, `content.md`,
`metadata.json` (`duration`: the video's; `extras`: user, name, views, likes, reposts, replies, quotes, bookmarks,
replies_fetched, posts, community_note, api, attempts, aliases; `video`: the video part's facts, only while a video
part ran) and, with a video, `video-transcript.md` and `video.mp4`.

## Commands

| Command | Does |
|---|---|
| `hal2-cli-tell x post <id> [--replies N]` | the raw thread (and replies) from FxTwitter as JSON, for debugging |
