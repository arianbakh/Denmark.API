# News / "this year in Denmark" sources — for citizenship current-affairs Q

Two jobs: (A) BACKFILL past events retroactively; (B) FORWARD-POLL to accumulate from now.
Goal = know which events had major DK news interest, to generate original practice questions.
(We generate questions from facts; we do NOT republish article text.)

## A. Backfill "year in Denmark" (retroactive, no RSS needed)
GRANULARITY MATTERS: tests run twice/yr (summer May/June, winter Nov), each covering the
preceding ~6 months (summer≈Dec–May, winter≈May–Nov). Windows slide/overlap → need MONTH-level
sources to cut any sitting's window; annual "year in review" alone is too coarse.
- **Danish Wikipedia** (CC BY-SA — best structured source):
  - `da.wikipedia.org/wiki/Aktuelle_begivenheder` — ROLLING month-level current-events log →
    slice to any 6-month window. Primary half-yearly source.
  - `da.wikipedia.org/wiki/202X_i_Danmark` — annual event list per year.
  - `da.wikipedia.org/wiki/Kategori:Begivenheder_i_202X` — category of event pages (~33–41/yr).
  - `da.wikipedia.org/wiki/Skabelon:Aktuelle_begivenheder_202X`.
- Our own forward-poll archive (below) is month-stamped → self-serves any 6-month slice once running.
- Media-mention rankings (kforum/Infomedia) are usually ANNUAL; check for half-year editions,
  else month-level Wikipedia + our archive cover the windows.
- **Media-mention rankings = ideal importance signal:** kforum "Årets mest omtalte begivenheder"
  (ranks events by media coverage volume, based on Infomedia). Tells us what was BIG, not just
  what happened. Search yearly: "årets mest omtalte begivenheder <år>".
- **DR / TV2 "Året der gik"** annual retrospectives (+ regional, e.g. TV2 Kosmopol "ti begivenheder").
- **"Året der gik" quizzes** (e.g. goquiz.dk) — real year-review Q&A = great few-shot examples
  for our question generator.
- VisitDenmark "store begivenheder"; Danmarks Statistik year review (stats, secondary).

## B. Forward-poll RSS (start on the VPS while waiting for ERST) — verify exact URLs on deploy
- **DR** `https://www.dr.dk/nyheder/service/feeds/<feed>` — feeds: senestenyt, indland, udland,
  penge, politik, sporten (+ regional).
- **TV2** national RSS (`tv2.dk/.../feeds/nyheder/rss`) + 8 regional TV2 feeds.
- Consider: Ritzau, Politiken/Berlingske/Jyllands-Posten (headlines free), Folketinget /
  regeringen.dk (laws, political events).
- Poller = daily cron → store {date, source, title, summary, url, hash} in our archive; dedupe.
- Prioritize topics appearing across MULTIPLE outlets = proxy for "significant news interest".

## Licensing
- RSS titles/summaries: free to read; don't republish full text. Store as topic signal only.
- Wikipedia: CC BY-SA (attribute + share-alike if redistributing text; we output original Q → low risk).

## Deploy note
When VPS + SSH ready: I drop a small Python RSS poller (feedparser) as a daily systemd timer/cron.
It just accumulates the forward archive; backfill (A) is a one-off pull we run when building the vertical.
