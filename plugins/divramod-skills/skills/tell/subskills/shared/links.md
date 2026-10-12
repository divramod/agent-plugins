# Links: how to find and check them

The links section (`templates/shared/links.md`) turns the source into a reading list: repos, whatever it mentions
(books, theories, frameworks, tools, papers, people), Wikipedia for the terms a reader needs, and a short "Further
reading" list on its topic. The source's related section (similar videos, similar repos, past discussions, …)
follows it; its subskill says how to fill it.

- **Look every link up with web search; never guess a URL.** Only link what you found.
- **Books:** the Amazon product page (`https://www.amazon.com/dp/<ASIN>`), which has the description and reviews.
  If there is none, use Goodreads or the publisher's page. Name the author and say in one line what the book is about.
- **Terms, theories, frameworks:** the English Wikipedia article, only for terms that matter for the summary. Skip
  everyday words.
- **GitHub repos:** every repo the source shows, uses or names. Link the repo, not the author's profile.
- **Tools and projects:** the official site. **Papers:** arXiv, DOI or the publisher's page.
- "Mentioned in the source" holds only what the content file names, with its anchor link. Anything else goes under
  "Further reading" (3-5 of the best sources on the topic: official docs, the original paper, a good explainer, a
  counterpoint), so it's always clear what the author said and what you added.
- **Dates are added for you.** When you save, `hal2-cli-tell save` checks every link and writes how current it is right
  after it: videos, papers and articles get their publish date; GitHub repos their latest release (version + date)
  and last commit on the default branch; packages their latest version; books the first-publication year; Wikipedia
  the last edit. Never write dates yourself. To see the dates before saving (e.g. to prefer recent sources), run the
  check below.
- Fix or drop every link reported as broken (`BROKEN LINK:` when saving, `broken` below). `unverified` means the
  site blocks scripts (often Amazon): keep those links when your web search showed the page.

```bash
hal2-cli-tell check-links <<'EOF'
<body>
EOF
```

To refresh the dates of an existing summary later (new releases, new commits):
`hal2-cli-tell check-links --folder "<dir>" --annotate`.
