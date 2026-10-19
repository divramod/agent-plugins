# Calibration

`W=hal2-cli-llm-wiki`, as in [SKILL.md](../SKILL.md). Read on the first batch of a wiki and when a source type is new to it. Skipping it and running large batches is
gambling on quality.

## Expected extract rate by source type

A rate far outside the range means the classification is off: re-read the segments before writing atoms.

| Source | Extract | Focus |
|---|---|---|
| Posts | 70-90 % | author-curated, mostly worth it |
| Replies | 10-15 % | mostly noise; only deep explanations |
| Transcripts | 40-60 % | skip greetings, repetition, tangents |
| Articles, papers | 80-95 % | the filter is topic relevance |
| Notes, memos | 20-40 % | many action items and fragments |
| Conversation logs | 15-30 % | conclusions and decisions only |

Classes: **extract** (a knowledge point, view or method that stands alone), **skip** (social filler, restating,
action items, pure emotion), **defer** (possibly valuable, needs context; revisit after the batch, never re-read in
the meantime).

## First batch

1. Ingest the first 10-20 segments of the first source only.
2. Show the user the result in one short message: the numbers extracted, skipped and deferred, and the atoms
   written (id and first line). Two questions in the Q form, no more: did the classification miss anything worth
   keeping, and is the extraction what the user wants (voice kept, claim stands alone)?
3. Record the answers where they last: a `$W log` line, and in the next ingests' judgment. Then run the rest of
   the batch without asking again.

Order sources: published content first (already self-filtered), deep material next, private notes last.

## Good and bad atoms

An atom adds the claim's reason or structure in the author's voice; it is not the source pasted under a title.
Test for splitting: if removing one view leaves the other intact, two atoms. A three-part concept is one atom.
