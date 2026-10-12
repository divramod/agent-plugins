# video

YouTube (videos, playlists, channels), youtu.be, Vimeo, TikTok, X videos, podcasts and any other yt-dlp site.
The content file `content.md` is the transcript with timestamp links, chapters and the description.

## Flags

```bash
hal2-cli-tell prepare "<url>" [--skip-download] [--visual] [--lang xx] [--limit N]
```

- The video is **always downloaded and kept** in the **highest available quality** as an mp4 (H.264/AAC first,
  what the apps' player plays; no re-encoding); an earlier lower-quality file is upgraded. The download runs **in the
  background** (`video_download.status: running` in the envelope), so carry on without waiting: when it finishes it
  adds the video to `metadata.json` and `summary.md` by itself.
- `--skip-download` only when the user says not to download or keep the video. The summary in hal2-macos then
  offers **Download Video** instead.
- `--visual` when the video is visual: slides, code, UI demos, diagrams, or a user asking "what does it show". The
  script then waits for the download (frames need it) while it fetches the transcript. With `--skip-download` it
  fetches only a <=1080p copy for the frames. Then also read `frames/index.md` and look at the frames that matter.
- `--lang xx` picks the transcript language (default: the spoken language).
- A bot check or HTTP 429 in the output means retry with `--cookies-from-browser chrome` (`TELL_BROWSER=chrome`
  makes it the default). If that fails too, run `hal2-cli-tell prereqs install --source video --upgrade` (yt-dlp
  ages fast).
- Without captions the transcript comes from local Whisper, which can take minutes. Run it in the background and
  tell the user.
- **Playlists and channels** print `kind: playlist|channel` with the videos (channels: the latest 10, `--limit N`).
  Prepare and summarize every video where `summary_exists` is false, then write the digest.

## Writing

- `transcript_source` says where the text came from. Auto-captions and Whisper mishear names and jargon: fix them
  from the title and description. If an auto-generated or Whisper transcript looks garbled, say so in one line.
- Use `chapters` mode (in `templates/video/template.md`) when the video has chapters or runs longer than ~20 min and
  the user wants structure.
- Lectures and talks: fill "Slides & course materials" (template) from `description_links.slides`, then search the
  course or conference page. Add `description_links.repos` under GitHub repos.

## Similar videos (related section)

Pick 2-4 search queries (the topic, the key concepts, the speaker or channel plus the topic) and run
`hal2-cli-tell related "<dir>" --query "<q1>" --query "<q2>"`. Choose 4-6 of the results, best first, and say in
one line what each adds. Each result has its `published` date: prefer recent videos when the topic moves fast. Only
link videos from its output; where a result has a `summary` path, also add `([summary](<that path>))`.

## Page and files

The summary's player in hal2-macos is the local video, else the YouTube embed; timestamp links seek it. With a
local video it offers **Delete Video** (falls back to YouTube). Downloaded videos carry the title, channel, date,
URL and chapters as file metadata (players like VLC show the title); for a video downloaded before that, run
`hal2-cli-tell video tag "<dir>"`. The folder holds `summary.md`, `content.md`, `metadata.json`, and `video.mp4` /
`frames/` when those were requested. A library with older `video.mkv`/`.webm` files or folders from before the
multi-source layout is brought up to date with `hal2-cli-tell migrate --apply` (dry run without `--apply`).

## Commands

| Command | Does |
|---|---|
| `hal2-cli-tell prepare` | metadata → folder → [video in background] → transcript (captions, else Whisper) → [frames]; reuses folders by video id; playlists/channels list their videos + a digest folder; `--dir <folder> --content-part video` makes the video a part of another item (an x post: `video-transcript.md`, no `videos/…` entry); a URL with several videos (an x post) takes `--playlist-item N` |
| `hal2-cli-tell video download "<dir>" "<url>"` | video download (detached, status in `.video-download.json`, `--quality best\|1080p\|720p\|audio`), then metadata + chapters into the file; `video tag\|delete\|status "<dir>"` |
| `hal2-cli-tell video frames "<dir>"` | scene-change keyframes → `frames/` + `index.md` (called by `--visual`) |
| `hal2-cli-tell related "<dir>" --query …` | YouTube search for your queries → similar videos (deduped, marks already-summarized ones) |
