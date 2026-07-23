# Citizenship-test prep (B2C idea) — sources & approach

Idea: use public official materials to generate near-infinite practice questions for people
studying for the Danish citizenship test.

## Test structure (Indfødsretsprøven, 45 Q / 45 min)
- 35 Q from the official læremateriale (6 chapters: history, democracy, economy, Denmark & the
  world, cultural life, themes).
- 5 Q value-based (free speech, equality, religion vs. law...).
- 5 Q current affairs — events with major DK news interest in the **last 6 months** before the
  test (NOT 2 years).
- Medborgerskabsprøven = sibling test, same idea.
- **Both tests held twice/yr: summer (May/June) + winter (November).** Each current-affairs
  window = preceding ~6 months → summer≈Dec–May, winter≈May–Nov. Windows slide/overlap and do
  NOT match a Jan "year in review" → backfill must be MONTH-level so we can cut any sitting's
  6-month window.

## Corpus (all free + public from SIRI / uim.dk)
- Læremateriale (6 chapters) — free download, PDF + audio. New edition ~end Aug yearly.
- Past test sets + answer keys — published after each test → free labeled Q/A, incl. historical
  current-affairs questions.
=> 40/45 question types fully covered by licensed official material. LLM generates unlimited
   fresh items grounded in it. This is the clean 90%.

## Current-affairs 5 Q — the only "news" part
- Don't need articles verbatim, only the topics/events (facts aren't copyrightable).
- RSS gives only the latest items, NOT history → handle in two ways:
  - Backfill (works retroactively): Danish Wikipedia year/month-in-review ("2025 i Danmark",
    monthly event lists) — CC BY-SA, exactly the notable-events recap the test uses. Plus past
    published tests = real historical current-affairs Q/A. Plus DR/TV2 year-in-review.
  - Accumulate forward: tiny daily cron polling RSS → store topics in our own archive. Can't get
    RSS history, but 6-month window fills in a few months. Cheap insurance if we commit.
- => historical RSS is a non-problem; Wikipedia backfill alone covers the past.

## News archive — NOT the tool
- Mediestream (Royal Danish Library, 32M+ pages): free only >100yr-old papers; recent = physical
  visit only, no public API. Useless for last-6-months current affairs.

## Approach when we build it
- [ ] Pull læremateriale (current + past editions) + all past test sets/answer keys from uim.dk
- [ ] LLM generates + validates practice questions per chapter (dedupe, difficulty tags)
- [ ] Light topic-signal scraper (RSS) for current affairs; generate original Qs from topics
- [ ] Keep edition dates — material changes yearly
