# CLAUDE.md — context for Claude

## Goal
Collect all publicly available Danish data, process with LLMs, join into a queryable data lake
to launch B2B/B2C products. Phase 1 = smiley (food inspection) + CVR (company + accounting).
First app: map of every food business (incl. new ones with no report yet) with parsed inspection
history (rat issues etc.), in-app PDF viewer, English translation, and CVR/accounting data.

## Machine (verified 2026-07-23)
- GPU: RTX 4090, 24 GB VRAM. Driver 595.84 / CUDA 13.2.
- CPU 24 cores, 62 GB RAM.
- NVMe: 1.8 TB ext4 on `/`, ~1.7 TB free. Working data lives here.
- External: `/dev/sda1` 3.6 TB **exFAT** over USB3 (10 Gb). Mount at `/mnt/ext`. Keep exFAT
  (Windows-readable, doubles as personal backup). Backup/overflow tier, NOT hot data.
- Docker NOT installed yet; no nvidia-container-toolkit. See README setup.

## Key decisions
- All code in **Python**.
- LLM: **gpt-oss-20b on vLLM in Docker** (user has run 20b here before; full PDF pass ~10h — fine).
- Storage: NVMe-first, external for backup/overflow until NVMe ~half full.
- Store tabular data as **Parquet**; query with **DuckDB** (in-process, reads Parquet directly).
- Minimize LLM calls: deterministic parse of templated PDF fields + content-hash dedupe of
  boilerplate; LLM only on novel free text; hash-keyed cache. Translation likely needs a fuller
  pass but still dedupe identical strings.

## Data sources
- Smiley XLSX (current-status snapshot, versioned CMS URL — scrape link, don't hardcode):
  https://www.findsmiley.dk/Statistik/Smiley_data/Sider/default.aspx
  → e.g. .../Media/638212360671096207/smileystatus.xlsx and .../Smiley_xml.xml
- Per-business page w/ report history: findsmiley.dk/Sider/Kontrolrapport.aspx?virk=<id>
  (findsmiley shows up to 4 recent; pre-2012 not shown. Full history = harvest report IDs from
  business pages — reverse-engineer URL pattern with samples in Phase 2.)
- CVR system-to-system (Elasticsearch): request access → cvrselvbetjening@erst.dk. Free, ~weeks,
  IP allowlist (IPv4 only), sign advertisement-protection declaration. Endpoint
  http://distribution.virk.dk/cvr-permanent (Basic auth). No ES support from them.
- Accounts (NO login): http://distribution.virk.dk/offentliggoerelser (+/_search). ES index →
  metadata + URLs to PDF/XBRL filings. Numbers require XBRL parsing. gzip required.
- Tilbudsavis: dominated by **Tjek** (ex-ShopGun, powers eTilbudsavis) and **MineTilbud**
  (Forbruger-Kontakt). Tjek API terms forbid third-party commercial reuse w/o written approval →
  do NOT scrape aggregators. Path = go to chains' own tilbudsavis or license. See todo.

## Refinements (2026-07-23)
- "No report yet" set: don't guess food branchekoder up front. Do a **second pass after the
  join** — take the set of branchekoder that actually appear among inspected businesses (from
  CVR of all report-linked businesses), then find CVR companies in those codes absent from smiley.
- KEYWORD FLAGS ARE CANDIDATES, NOT FINDINGS. extract.py's has_pest / has_indskaerpelse /
  has_politianmeldelse etc. are keyword MENTIONS only. A report may say "no trace of rats",
  "self-checked for rats", or reference a PRIOR/resolved case ("politianmeldelse ... bragt i
  orden"). Use flags to PRE-FILTER into the LLM; the LLM decides actual finding + negation +
  status (occurred / resolved / checked-clean). Verified on real police-report samples.
- Inspection extraction is NOT boolean per issue. Capture, per issue type (e.g. rats):
  when it occurred, how many times, time-to-resolution, penalty/sanction, control type. Model as
  an event timeline per business, not flags.
- CVR ES needs static IPv4 whitelist; user has none. Plan: cheap Hetzner VPS (~€4/mo) as
  WireGuard gateway; GPU box egresses via it, storage/processing stay local. See email doc.
- Tilbudsavis: source-first, aggregators dropped. All chains reserve IP rights → no scraping;
  pursue partnership/official feed. Enumeration + terms in docs/tilbudsavis-sources.md. PDFs=backlog.

## GDPR note
Enkeltmandsvirksomheder (sole props) tie personal name to business = personal data. Register is
public, but reuse/profiling/marketing has rules; honor reklamebeskyttelse flag. Revisit before B2C.

## RULES (important)
- NEVER disclose the user's or company's private info (personal email, phone, address, VPS IP,
  identity/company markers in outbound User-Agents, etc.) to any third party/external service
  without asking the user FIRST. Neutral non-identifying User-Agent by default. User flagged this
  as "extremely important". (Exception: the CVR application the user sends himself.)

## Conventions
- Idempotent, resumable fetchers with dated snapshot dirs + content hashing.
- Politely identify the crawler; user's uplink is 1 Gbps (the real bottleneck).
- Python venv at .venv (bootstrapped via get-pip; python3-venv not installed — needs sudo).
- All progress/resume state in data/state.db (SQLite WAL). Atomic writes (tmp+rename).

## Infra (live as of 2026-07-23)
- VPS: <VPS_USER>@<VPS_IP> (see secrets/secrets.env; Ubuntu 26.04, 2 vCPU, 3.7GB, 34GB free).
  SSH key on GPU box. Always on. Hardened: ufw (22 only), key-only SSH, fail2ban.
- News poller LIVE on VPS: /root/news_poller.py + venv, systemd denmarknews.timer (hourly),
  DB /root/denmarknews/news.db. Feeds: DR x5 + Politiken + Børsen (TV2 has no clean RSS). Source
  = vps/news_poller.py in repo. 146 rows at start.
- GPU box may be `poweroff`'d anytime → ALL pipelines resumable. Auto-resume on boot via systemd
  units (systemd/denmarkapi-*.service; user installs with sudo — see README §5).
- Dashboard LIVE: GPU computes data/status.json (denmarkapi.dashboard) → pushes to VPS every 30s;
  VPS serves it (vps/dashboard_server.py, systemd denmarkdash.service, port 8080, Basic Auth,
  ufw-opened). URL/creds in secrets/secrets.env. Viewable when GPU off (shows staleness).
- VPS reboots too (updates) → all VPS services are `enabled` (autostart): denmarknews.timer,
  denmarkdash.service.

## LLM serving (live 2026-07-23)
- vLLM (v0.25.1) + openai/gpt-oss-20b in Docker (docker-compose.yml). OpenAI API at
  127.0.0.1:8000 (localhost only, never public). Model name 'gpt-oss-20b'. MXFP4/MARLIN,
  ~22GB VRAM, max_model_len 32768. Autostarts on reboot (restart: unless-stopped).
- Shell lacks docker group → run docker via `sg docker -c "..."`.
- Validated on real task: correctly resolves pest MENTION vs FINDING (negation-aware). ~64-193
  tok/s single-stream; batches higher. Weights in models/ (gitignored).

## ===== SESSION HANDOFF (state at 2026-07-24 16:30) =====

### CRITICAL operational state
- **findsmiley RECOVERED and harvest is RUNNING again** (probed 2026-07-24 15:02 UTC: HTTP 200 in
  0.27s). History: on 2026-07-23 findsmiley returned HTTP 503 site-wide; the old harvest kept
  retrying → user emergency-stopped. Fix in place: RateLimiter + CircuitBreaker (aborts on
  sustained 5xx/429/timeouts). Since resuming: 0 new errors, failed counts going DOWN.
  If it ever 503s again: stop, wait, probe with ONE manual request; if only the GPU IP is
  blocked, run harvest from the VPS.
- **GLOBAL PAUSE is CLEARED** (control.json paused=false). Pipelines are live.
- Control mechanism: dashboard writes control.json on VPS → push.py pulls it (scp to tmp+rename)
  to data/control.json → pipelines read it live. Knobs (all live, no restart needed):
  - `harvest_rate` — slider, findsmiley requests/sec, server-clamped 0–10. harvest.py's
    RateLimiter re-reads it per request. Default 2.6.
  - `analyze_concurrency` — slider, in-flight LLM requests, clamped 0–128. Default 32.
  - `overlay_concurrency` — slider, in-flight LLM requests for the English PDFs, 0–64. Default 8.
    Separate from analyze because both share the one vLLM.
  **ZERO = PAUSED for each stage.** The old global Pause/Resume buttons are GONE: one switch
  could not say "stop crawling findsmiley but keep the GPU busy", and because in-flight work
  drains for ~25s it looked like the button did nothing. Verified: harvest froze and vLLM
  in-flight went 30 → 0 → 32. (control.paused is still honoured for CLI use.)
  Endpoint: POST /control?action=set&harvest_rate=..&analyze_concurrency=..&overlay_concurrency=..
  `--rate` / `--concurrency` CLI flags still exist and PIN the value (slider ignored) if passed.
- **status.json is now written atomically to the VPS** (ssh 'cat > tmp && mv'). scp truncates
  its destination first, so copying straight onto the file the dashboard serves left a window
  where a reader got an empty file — which is why the archive size and rates sometimes appeared
  to DROP to zero. The server also keeps the last good snapshot rather than serving zeroes.
  Verified afterwards: 90 consecutive 1s polls, 0 drops, strictly increasing, and matching `du`.
  The disk scan also refreshes every 10s instead of 30 (it measures 0.37s over ~175k files), so
  the archive size no longer reads up to 30 MB behind reality.
- Dashboard is TABBED (Harvest / Extraction / Analysis / English PDFs / System) with each
  stage's slider in its own tab and % badges on the tab bar; PDFs have their own progress bar
  (the bare count said nothing about progress). Tab choice persists in localStorage.
- Dashboard ETAs are now ONE model, so they agree with each other. Each stage used to measure
  itself against the work known SO FAR, so extract/analyze claimed to finish BEFORE harvest —
  impossible, since they consume its output. Now: harvest remaining = pending+failed (it used
  to also count 'skipped' ids, which are resolved and never downloaded); every downstream stage
  projects its final total from the projected final report count and is floored at the harvest
  ETA. `derived.analyze_total` / `overlay_total` / `extract_total` carry those projections.

### Data progress (in data/state.db + data/parquet/) — snapshot at 2026-07-24 16:30
- Smiley index: 58,616 businesses (smiley_status.parquet). CVR 98% / P-nr 97% (join validated).
  Geo only 53% → geocode later (DAWA shuts 2026-08-17; use DAR bulk / CVR P-units, see docs/geocoding.md).
- Harvest: ~144.2k report PDFs downloaded (data/pdfs/<shard>/); the 3,175 businesses that failed in
  the throttling storm are being retried now and are draining. ~57k report downloads still queued.
  At 2.6 req/s the remaining ~72k requests finish ~00:00 on 2026-07-25.
- Extract (deterministic, no LLM): ~144k done → smiley_extract.parquet. Text via pdfplumber
  x_tolerance=1.5. Flags are keyword MENTIONS not findings (pest/injunction/etc.).
- Analyze (LLM gpt-oss-20b): running --watch. ~8.2k of ~55k reports-with-remarks done →
  smiley_analyze.parquet. severity DERIVED from findings. Measured ~7.5 reports/s at concurrency
  32, so analysis tracks well ahead of the harvest and is not the critical path.
- Translate/overlay: **production-ready, benchmarked on 2,500 reports, NOT yet run at scale.**
  overlay_pdf.py produces English PDFs (data/pdfs_en/) by redacting Danish vector text in a COPY
  of the original + inserting English (keeps layout). Now also:
  * template covers are GLYPH-TIGHT. OCR boxes are generous, so filling them painted over the
    form's own borders and underlines ("This inspection, date" ate its cell border,
    "Inspector's remarks" ate its underline). The cover now shrinks to the inked pixels, with
    rows that are inked >65% across treated as RULES and excluded — but only ROWS: a near-solid
    COLUMN is just a tall letter stem, and excluding those clipped the first letter off
    headings. Colours are still sampled from the LOOSE box (on a green band the commonest
    colour inside a glyph-tight box is the white text, which inverted fill/text), as are font
    size and baseline (deriving them from the tight box made label sizes jump around depending
    on whether a word happened to contain an ascender).
  * template.py — the baked template chrome is FIXED (was: stays Danish). 17 template variants
    identified by perceptual hash; each OCR'd once (rapidocr, pip-only, no sudo) and stored as a
    patch spec in data/templates/*.json. At overlay time each label is covered with its own
    sampled background colour and redrawn in English. NO image re-encoding.
    100% of labels come from a curated DA→EN dictionary in template.py (OVERRIDES/KEEP) —
    the LLM fallback now translates 0 of them. Verified visually.
    A template we have NEVER SEEN (the specs came from a sample, and ~55k reports were still
    downloading) is handled at runtime: template.ensure_spec() builds the spec on first sight,
    once per variant, and records misses in data/templates/_unknown.json. `--all` scans every
    downloaded PDF instead of a sample.
  * reflow — English runs ~15-25% longer than Danish. Translating line-by-line into the ORIGINAL
    line width forced the font down (to 4pt) and made pages look ragged. Now consecutive prose
    lines are grouped into paragraphs, adjacent paragraphs in a column are laid out as ONE flow,
    and leading is pinned to the form's printed line pitch so the text keeps sitting on the
    ruled lines and grows into the blank ones below. Form fields (business/address/postcode) are
    excluded by requiring the previous line to be wide, or the address got swallowed.
    TRANSLATION UNIT IS THE PARAGRAPH, not the line: asked to translate half a sentence the
    model helpfully completed it from context, which duplicated text across neighbouring lines.
  * trans_cache.py — translation cache (data/trans_cache.db) shared across all reports, keyed on
    the paragraph. 78% of blocks are served from cache; a page whose blocks are all known costs
    0 LLM calls.
  * id-keyed translation (was a REAL BUG): the model returns {id, en}, never a bare list. The
    old positional contract silently shifted every later label onto the wrong box when the model
    merged/dropped a line. Missing ids are retried once → 0.000% lines left in Danish.
  * fonts are subset before save (1.2 MB → 424 KB per PDF).
  (translate.py = full-text plain translation → parquet, still only 8 rows and arguably
  redundant with the overlay; decide before running it at scale.)

### Pipelines (denmarkapi/smiley/): harvest → extract → analyze / translate+overlay
All resumable, --watch modes, check control.wait_if_paused(). systemd units in systemd/.
Run via .venv/bin/python -m denmarkapi.smiley.<stage>. LLM stages need vLLM up.

### External access
- **CVR system-to-system: APPROVED.** Erhvervsstyrelsen replied 2026-07-24: "The information has
  now been registered and you will receive the user credentials within three weeks."
  → credentials expected by ~2026-08-14. ACTION WHILE WAITING: the endpoint is IP-allowlisted
  (IPv4), so the WireGuard gateway on the VPS must be up and the GPU box egressing through it
  BEFORE the credentials arrive — build and test that now, not on the day.
- Rejseplanen Labs: user registered; check feeds (esp. live vehicle positions) when resumed.

### NEXT STEPS (priority order)
1. (in flight) Harvest + extract + analyze running; harvest ETA ~00:00 2026-07-25. Check the
   dashboard; if the circuit breaker trips, harvest exits — restart it after a pause.
2. Set up the WireGuard gateway on the VPS + route GPU egress through it, ready for CVR creds
   (expected by ~2026-08-14). Whichever IPv4 we hand ERST must be the one we actually egress from.
3. **DECISION PENDING: run the English overlay over all ~162k reports.** Benchmarked at
   ~4.4 reports/s (concurrency 24, sharing vLLM with analyze) → ~10 h and ~66 GB. Start with
   `python -m denmarkapi.smiley.overlay_pdf --watch` (follows the dashboard slider). It is
   resumable, so it can just run alongside everything else. 1,200 already done.
4. CVR/accounts + Rejseplanen once access lands; geocoding via DAR/P-units.

### Overlay benchmark (2026-07-24, after reflow + baseline drawing)
| | value |
|---|---|
| reports/s @ concurrency 24, warm cache | **4.4** (CPU-bound; 0 LLM calls at 100% cache) |
| block-cache hit rate | 78% climbing to 100% on re-runs |
| errors / unknown template variants | 0 / 0 |
| lines left in Danish after retry | 0.000% |
| output size per PDF | 424 KB (original 415 KB) |
| projected full run | ~10 h, ~66 GB for ~162k reports |
Early in a run the LLM is the throttle (concurrency 8 -> ~1.2/s, 24 -> ~4.7/s); once the cache
is warm it is pure CPU. Two render costs were worth fixing: the word-wrap measured the whole
accumulated line per word (quadratic, 43% of CPU) — now each word is measured once at size 1
and scaled, since text_length is linear in size — and the smiley icons were being decoded on
every page before being discarded on size. 2.6 -> 4.4 reports/s.
Reliability: a page whose reply exceeds max_tokens comes back as truncated JSON; _call_chunked
halves the batch and retries, so one long report no longer fails. A report that fails
MAX_ATTEMPTS times is parked as 'skipped' so --watch cannot spin on it forever.
Sample Danish/English pair (long report, confirmed rat findings, ban + fine): examples/
(gitignored; regenerate with `overlay_pdf --report 7085509`).
- Terms check done: smiley data is Open Public Data License (reuse w/ attribution); no rate/crawl
  clause, no robots.txt. We attribute Fødevarestyrelsen. 503 = server protection, not a violation.
