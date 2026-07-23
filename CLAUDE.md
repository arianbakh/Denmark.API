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
- GPU box may be `poweroff`'d anytime → ALL pipelines must be resumable + (todo) auto-resume on boot.
  Dashboard (todo) reads state.db; snapshot to VPS so it's viewable when GPU is off.

## Progress (2026-07-23)
- Phase 0 done: benchmark (bench/RESULTS.md) → NVMe for hot data, external for archive/backup.
- Smiley index fetched + profiled + Parquet (data/parquet/smiley_status.parquet). 58,616 rows,
  CVR 98% coverage (join validated). Per-business URL = DetailsView.htm?virk=<navnelbnr>.
  Geo only 53% → geocode via DAWA. 553 ad-protected (GDPR).
- CVR + Rejseplanen applications sent (awaiting reply). Poller accumulating meanwhile.
- NEXT: parse XML; PDF-URL reverse-engineer from virk pages; vLLM+gpt-oss-20b; dashboard; boot-resume unit.
