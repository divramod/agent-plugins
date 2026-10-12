# Discussions: themes with quotes

For Hacker News threads, Reddit posts, X replies and GitHub issue, pull request and discussion comments. A
discussion is not linear, so don't retell it in order: group it by what people argue about.

1. **The original first.** Summarize what is being discussed (the linked article, the post, the issue body) in its
   own section before the discussion.
2. **Themes as headings.** 3-7 themes, most discussed first. Under each: one or two sentences on the position, then
   2-4 **verbatim quotes** with their author and the comment's anchor link, e.g.
   `> "the quote" (**username**, [link](<permalink from the content file>))`.
   Pick quotes that carry an argument, a number or first-hand experience, not agreement or jokes.
3. **Where people disagree.** Name the split and quote one voice from each side.
4. **Uncommon but interesting.** A short list of minority opinions and first-hand reports that don't fit a theme.
5. **Weight.** Say roughly how much of the thread a theme takes ("most replies", "a few commenters"); the content
   file gives comment counts and depth. Never present a single comment as the consensus.

Quotes must be copied exactly from the content file (whitespace aside); paraphrase outside quote marks. Before
saving, run `hal2-cli-tell check-quotes "<dir>"` with the body on stdin: it lists every quote that is not
in the content file (`NOT FOUND:`). Fix those and run it again until it exits 0.
