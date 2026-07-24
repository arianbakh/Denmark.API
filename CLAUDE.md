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

## ===== SESSION HANDOFF (2026-07-24 ~20:00) =====

### RIGHT NOW — what is running on the GPU box
All four are plain `setsid nohup` processes (NOT systemd — see "sudo" gotcha), all resumable,
all safe to kill and restart at any time. Logs in data/logs/*.log.

| process | started as | state at 20:00 |
|---|---|---|
| harvest | `python -m denmarkapi.smiley.harvest` | 176,917 PDFs, 37,304 queued, ETA ~23:50 |
| extract | `python -m denmarkapi.smiley.extract --watch` | 176,891 done, keeps pace with harvest |
| analyze | `python -m denmarkapi.smiley.analyze --watch` | 68,106 done; CAUGHT UP (drains each batch in ~8s then idles 20s) |
| overlay | `python -u -m denmarkapi.smiley.overlay_pdf --watch` | **STARTED 2026-07-24 19:50**, 1,462/170,444, ~4/s, ETA ~07:30 Sat |
| dashpush | systemd `denmarkapi-dashpush` | pushes status.json to the VPS every 2s |

Check everything at a glance: `pgrep -af "[d]enmarkapi"` and the dashboard (URL/creds in
secrets/secrets.env). To restart one after editing its code, see the "old code in memory" gotcha.

### Live control — the dashboard sliders (no restart needed)
Dashboard (VPS) writes control.json -> push.py mirrors it to data/control.json -> pipelines
re-read it per request. Tabs: Harvest / Extraction / Analysis / English PDFs / System.
- `harvest_rate` — findsmiley requests/sec, clamped 0–10. **Default 2.6.**
- `analyze_concurrency` — in-flight LLM requests, 0–128. Default 32.
- `overlay_concurrency` — in-flight LLM requests for English PDFs, 0–64. **Currently 24.**
**ZERO = PAUSE that stage.** There are no Pause/Resume buttons any more: one global switch could
not express "stop crawling findsmiley but keep the GPU busy", and since in-flight work drains for
~25s it looked like the button did nothing. Verified: harvest froze, vLLM went 30 -> 0 -> 32.
`--rate` / `--concurrency` CLI flags still PIN a value and ignore the slider.

### Data progress (source of truth = data/state.db; dashboard renders it)
- Smiley index: 58,616 businesses — ALL scraped, 0 failures.
- Reports: 176,917 PDFs (37,304 queued, 1,917 skipped = ids that never had a PDF).
- Extract (deterministic, no LLM): 176,891. Flags are keyword MENTIONS, not findings.
- Analyze (LLM): 68,106. severity DERIVED from findings, not the model's own label.
- Overlay (English PDFs): 1,462. Output data/pdfs_en/<shard>/<id>.pdf, ~424 KB each.
- Disk: 59 GB Danish + English growing to ~66 GB. 1.6 TB free — not a constraint.

### The English-PDF overlay (denmarkapi/smiley/{overlay_pdf,template,trans_cache,urls}.py)
Redacts the Danish vector text in a COPY of the original and draws English in its place, so the
layout survives. Four things make it work at scale; each was a real failure first:
1. **Template chrome** is baked into the page's background raster. 17-18 variants exist, keyed by
   perceptual hash; each is OCR'd ONCE (rapidocr, pip-only, no sudo) into data/templates/<key>.json
   and patched at PDF level — no image re-encoding. 100% of labels resolve from the curated DA->EN
   dictionary in template.py (OVERRIDES/KEEP); the LLM translates none of them. An unseen variant
   is built on first sight at runtime (ensure_spec) and logged to data/templates/_unknown.json.
2. **Paragraph-level translation + column reflow.** English is 15-25% longer, so line-by-line
   translation shrank fonts to 4pt. Consecutive prose lines become paragraphs, adjacent paragraphs
   in a column are laid out as one flow, and each line is stamped on the ORIGINAL BASELINE
   (span origin) at the measured pitch, so text sits on the form's printed rules.
3. **trans_cache.py** — paragraph-keyed cache in data/trans_cache.db, shared across all reports.
   78% hit rate rising to 100% on re-runs; a page whose blocks are all known costs 0 LLM calls.
4. **id-keyed LLM output** — the model returns {id, en} and must echo the id. A missing id leaves
   a gap; positional alignment silently shifted every later line onto the wrong place.

Measured: 4.4-4.7 reports/s at concurrency 24; 0 errors, 0 unknown variants, 0.000% lines left in
Danish over 1,200+ report regressions. Early in a run the LLM is the throttle, later it is CPU.

### translate.py — searchable English text (FIXED 2026-07-24, not yet run at scale)
parquet/smiley_translate: report_id, navnelbnr, text_en. Companion to the overlay's PDF.
It now **reuses the overlay's paragraph cache** instead of paying the LLM a second time. The old
version translated each report's whole text in one call, keyed on that whole text, so it shared
nothing with the overlay and every report was translated twice. Now it opens the same PDF, groups
lines with the same code (overlay_pdf._lines / _paragraphs) and looks the blocks up by the same
key, so:
  * on reports the overlay has already done: **100% cache hit, 0 LLM calls, ~250 reports/s**;
  * on reports it has not: ~70% hit, and whatever it does pay for lands in the shared cache, so
    the overlay gets those free when it arrives. Whichever stage sees a paragraph first pays.
It needs the PDF on disk, not just the extract parquet — that parquet's text comes from a
different extractor (pdfplumber) and would not produce matching keys. The 8 rows from the old
whole-text method were deleted so the table is uniform.

### GOTCHAS — these each cost real time; do not rediscover them
- **`pkill -f` can kill this session.** If the same command ALSO contains the plain module path
  (e.g. a restart line), pkill matches the shell's own cmdline and kills it. Put the pkill in a
  SEPARATE call and bracket the pattern: `pkill -f "denmarkapi[.]smiley[.]harvest"`.
- **Long-running processes hold OLD code.** Editing a module does nothing until you restart the
  process. After changing control.py/harvest.py/etc., restart the affected pipelines.
- **sudo needs a password** — the user runs systemd installs. Units live in systemd/ and are
  installed with: `sudo cp systemd/denmarkapi-*.service /etc/systemd/system/ && sudo systemctl
  daemon-reload && sudo systemctl enable ...`. denmarkapi-overlay.service is NEW and not installed.
- **PyMuPDF `apply_redactions` rebuilds the page and drops registered fonts** — register fonts
  AFTER it, or insert_text fails with "need font file or buffer".
- **`insert_textbox` writes NOTHING if the text does not fit** and returns a negative number, so a
  shrink loop that stops above 4pt silently drops whole paragraphs.
- **`get_text` blocks are not ordered top-to-bottom across columns** — never infer "what is below
  this" from block order; use geometry.
- **findsmiley regenerates each PDF per request** — same text and images, different bytes (71-byte
  timestamp). Byte hashes/ETags cannot detect content change; compare extracted text.
- **Never scp onto a file something else is reading** — scp truncates first. Write to a tmp path
  and rename (push.py does `ssh 'cat > tmp && mv'`).
- **Python buffers stdout when redirected** — run background pipelines with `-u` or logs stay empty.
- Shell lacks the docker group: run docker via `sg docker -c "..."`.

### Serving the PDFs (decided 2026-07-24)
- **No link table needed.** The report id IS the filename; the URL is a pure function of it.
  Everything is in denmarkapi/smiley/urls.py: report_url / business_url / pdf_path / en_pdf_path /
  links(id). Verified live against report 7219723.
- Hot-linking findsmiley instead of serving our own copies is NOT recommended: one request to a
  public authority per page view (they 503'd site-wide under load on 2026-07-23), our availability
  becomes theirs, and the English PDFs must be served by us regardless. Licence is Open Public Data
  (reuse with attribution) so redistributing our copies is fine — attribute Fødevarestyrelsen.
- Recommended: serve our own copies + show the derived findsmiley URL as "view original", which
  doubles as the attribution.
- ~62 GB Danish + ~66 GB English ≈ 128 GB. No CDN needed to launch.

### External access
- **CVR system-to-system: APPROVED** (ERST, 2026-07-24): credentials due within three weeks, i.e.
  by ~2026-08-14. The endpoint is IPv4-allowlisted, so the **WireGuard gateway must be live and
  tested BEFORE they arrive**, and the IPv4 we hand ERST must be the one we actually egress from.
- Rejseplanen Labs: registered; check feeds (esp. live vehicle positions) when resumed.

### NEXT STEPS (priority order)
1. (in flight, nothing to do) harvest ETA ~23:50 tonight; overlay ETA ~07:30 Saturday. If the
   circuit breaker trips, harvest EXITS — wait, probe findsmiley with ONE request, then restart.
2. **WireGuard gateway on the VPS + route GPU egress through it** — critical path for CVR
   (~2026-08-14). Policy-route ONLY distribution.virk.dk through the tunnel so a tunnel outage
   cannot stall harvest/dashboard. Verify the observed source IP, make it survive reboot, THEN
   send ERST that IPv4.
3. Install denmarkapi-overlay.service (needs sudo) so the overlay resumes after a reboot.
4. **Run translate.py once the overlay is done** — `python -u -m denmarkapi.smiley.translate
   --watch`. It is now cache-sharing (see below) so it costs ~10-15 min of CPU for the whole
   corpus and almost no LLM. Do NOT run it alongside the overlay: they share one concurrency
   slider, so it would just slow the overlay down for no gain.
5. CVR/accounts + Rejseplanen once access lands; geocoding via DAR / CVR P-units.

### Samples for eyeballing (examples/, gitignored)
- `7085509_da.pdf` / `7085509_en.pdf` — 7-page report, confirmed rat findings, ban + fine.
- `news_sample.md` — 274 headlines, per-feed counts, and how dedup works.
- Regenerate: `python -m denmarkapi.smiley.overlay_pdf --report 7085509`.

- Terms check done: smiley data is Open Public Data License (reuse w/ attribution); no rate/crawl
  clause, no robots.txt. We attribute Fødevarestyrelsen. 503 = server protection, not a violation.
