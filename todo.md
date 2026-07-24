# TODO

>>> CURRENT STATUS + full handoff: see CLAUDE.md "SESSION HANDOFF" section. <<<
>>> As of 2026-07-24 20:00: harvest + extract + analyze + ENGLISH OVERLAY all running. Harvest
>>> ETA ~23:50 tonight, overlay ETA ~07:30 Sat. Sliders (0 = pause) control all rates live.
>>> CVR access APPROVED — credentials due ~2026-08-14, so WireGuard is the critical pre-req.

Pipelines built + running (harvest/extract/analyze/translate/overlay). vLLM+gpt-oss-20b live.
Dashboard live (VPS:8080, creds in secrets/). Remaining work below + CLAUDE.md next-steps.

## Phase 0 — machine prep (user runs sudo; see README)
- [x] Mount external SSD at /mnt/ext (keep exFAT)
- [x] Install Docker + Compose + nvidia-container-toolkit + fio; verify GPU-in-Docker
- [x] I/O benchmark → bench/RESULTS.md. NVMe ~67x faster on 4K random read → hot data on NVMe.
- [x] python3-venv installed by user
- [x] systemd auto-resume units (systemd/denmarkapi-*.service; README §5 installs them)
- [x] Dashboard LIVE (VPS:8080, Basic Auth, ETA/throughput/errors/pause button)
- [x] vLLM + gpt-oss-20b in Docker (docker-compose.yml)
- [x] OVERLAY: baked template labels — 17 variants OCR'd once into data/templates/*.json specs;
      patched at PDF level (no image re-encode). 100% of labels from the curated dictionary.
- [x] OVERLAY: production driver (resumable state pipeline, --watch, dashboard slider) +
      per-line translation cache + id-keyed translation (fixed a silent label-shift bug).
- [x] OVERLAY: batch-run STARTED 2026-07-24 19:50 (--watch, slider-controlled, resumable).
      ~170k reports at ~4/s -> ETA ~07:30 Sat, ~66 GB. Progress: dashboard 'English PDFs' tab.
- [ ] Install systemd/denmarkapi-overlay.service (needs sudo) so it resumes after reboot
- [x] OVERLAY: re-flow long English instead of shrinking the font (paragraph-level translation
      + column flow + leading pinned to the form's rules)
- [x] OVERLAY: translate business names (user decision 2026-07-24); addresses/CVR/dates stay
- [x] OVERLAY: handle template variants never seen before (built on first sight at runtime)
- [x] Dashboard: per-stage pause by dragging a slider to 0; global Pause/Resume buttons removed
- [x] Dashboard: make the stage ETAs consistent (project final totals; floor at harvest ETA)
- [x] translate.py now REUSES the overlay's paragraph cache (100% hit / 0 LLM calls on reports
      the overlay has done; ~250 reports/s). Old whole-text rows deleted.
- [ ] Run translate.py over the corpus AFTER the overlay finishes (~10-15 min, nearly free).
      Don't run it alongside — they share one concurrency slider.
- [x] Resume harvest gently after findsmiley recovers; retry failed businesses + pending downloads
      (2026-07-24: running at 2.6 req/s, 0 errors, the 405 failed report downloads all recovered)
- [x] Resume analyze --watch
- [x] Dashboard speed sliders (harvest req/s + analyze concurrency), live via control.json

## Phase 1 — access (kick off first, runs in parallel)
- [x] Fill CVR number in docs/cvr-access-email.md; user sends to cvrselvbetjening@erst.dk
- [x] Sign advertisement-protection declaration; ERST replied 2026-07-24: registered, credentials
      to arrive within three weeks (i.e. by ~2026-08-14)
- [ ] **WireGuard gateway — now the blocking pre-req** (see Phase 4). Must be live and tested
      before the credentials land, and the IPv4 we give ERST must be the one we actually egress
      from. Don't leave this to the day the creds arrive.

## Phase 2 — smiley pipeline
- [x] Fetcher (denmarkapi/smiley/fetch_index.py): scrapes links, dated snapshots, hashed, resumable
- [x] Profile schema → Parquet. 58,616 businesses. CVR 98% / P-nr 97% coverage → JOIN VALIDATED.
      Per-business page = DetailsView.htm?virk=<navnelbnr>. 6,595 have no inspection yet.
      553 reklame_beskyttelse=1 (GDPR). Geo only 53% → NEED GEOCODING (DAWA) for map.
- [ ] Parse XML snapshot too (59MB) — may hold more fields than xlsx; compare
- [ ] Geocode ~47% missing coords. NOTE: DAWA shuts 2026-08-17. Plan (docs/geocoding.md):
      primary = CVR P-unit coords (free, ~97%, comes with CVR access); fallback = bulk DAR
      register joined locally (no live API). Skip live DAWA dependency.
- [ ] Reverse-engineer per-business page (virk=<navnelbnr>) → report-ID → PDF URL (samples first)
- [ ] Download a few sample PDFs, inspect, THEN bulk download (to /mnt/ext archive)
- [ ] Design snapshot/monitoring for new reports (diff snapshots; check update cadence)

## Phase 3 — LLM extraction
- [ ] vLLM + gpt-oss-20b in Docker; confirm VRAM fit; benchmark tok/s on real prompt
- [ ] Discover PDF field taxonomy WITHOUT full pass (sample + cluster — see plan)
- [ ] Pipeline: deterministic parse → boilerplate dedupe → LLM on novel text → hash cache
- [ ] English translation pass (dedupe identical strings)
- [ ] Define + validate extraction schema on hand-labeled sample

## Phase 4 — CVR + accounts
- [x] (pre-req, part 1) VPS is live and always-on — see CLAUDE.md "Infra"
- [ ] (pre-req, part 2) **WireGuard gateway on the VPS + route GPU-box egress through it**, so we
      present the VPS's static IPv4 to CVR's allowlist. CRITICAL PATH — creds due ~2026-08-14.
      Steps: wg on VPS (server) + GPU box (peer); policy-route only distribution.virk.dk traffic
      via the tunnel (keep harvest/dashboard on the normal uplink so a tunnel outage can't stall
      them); verify with a curl to an echo service that the observed source IP is the VPS's;
      make it survive reboot on both ends (wg-quick@wg0 enabled); only then send ERST that IPv4.
- [ ] Bulk pull CVR once access lands → Parquet
- [ ] Second pass: derive inspected branchekoder from joined data → find CVR food cos NOT in
      smiley ("no report yet" set for the map)
- [ ] Separate pipeline: offentliggoerelser ES → XBRL parse → Parquet (no login)

## Phase 5 — join + query
- [ ] DuckDB over Parquet, joined on CVR/P-number, provenance + snapshot dates preserved

## Tilbudsavis (research + internal prototype NOW) — see docs/tilbudsavis-sources.md
- [ ] Locate each grocery group's official tilbudsavis page + any public/partner feed
- [ ] Record allowed/forbidden per chain from their terms
- [ ] Draft partnership/permission inquiry template
- [ ] Build internal (unpublished) ingestion prototype — download + parse + test, ready to flip
- [ ] Go to production per chain ONLY after permission/feed confirmed

## Later / backlog
- [ ] OpenStreetMap (free). DK quality is high: ~3.7M buildings (~91% complete); addresses
      imported from official DK gov open data (DAR) since 2009, auto-synced, very high quality.
      Uses: building footprints + POIs for the map; alt geocoding source (has DAR addresses).
      License ODbL (attribution + share-alike on derived data — note for commercial use). Bulk:
      Geofabrik download.europe/denmark. Ties to [[geocoding]].
- [ ] DinGeo-style property/area data — get it from the ORIGINAL public sources, not dingeo:
      soil contamination (Danmarks Miljøportal), noise (EPA Støjdanmark), radon studies, flood
      maps, BBR buildings + valuations (Datafordeler), addresses (DAR). dingeo just aggregates
      these public sources; rebuild from source. Ties to [[geocoding]] + statistics-sources.
- [ ] Public statistics catalog: see docs/statistics-sources.md (built by background research).
      User recalled e.g. a food-waste-app usage report; want broad coverage of DK public stats.
- [ ] Supplier-change monitoring: subscribe to newsletters + periodically check the "news"/
      "nyheder" sections of all data suppliers (Fødevarestyrelsen, Erhvervsstyrelsen/Virk,
      Rejseplanen, Datafordeler, uim.dk, chains) so we get early warning of API/format changes
      (like the DAWA shutdown) instead of being surprised.
- [ ] Proper secret management (replace interim secrets/secrets.env): decide on a real solution
      (e.g. env + .env loader, sops/age, or a vault) and migrate.
- [ ] Decide UA "middle path": stay neutral to commercial/news targets but optionally identify to
      open-data gov sources that reward it (CVR, Datafordeler, Rejseplanen). Per-source UA already
      centralized. User must decide before enabling.
- [ ] Public transport: Rejseplanen = national, clearly-licensed source. Data = CC BY 4.0
      (attribution). Static GTFS free (rejseplanen.info/labs/GTFS.zip). Real-time via Labs API:
      free <=50k calls/mo (non-commercial); commercial needs paid agreement (~€5k/yr for
      100k/day). Midttrafik live (live.midttrafik.dk JSON) = app-backend, NO open license,
      portal restricted to municipalities → don't build on it. TODO: with Labs key, confirm if
      real-time includes vehicle GPS positions (VehiclePositions) or only departure predictions.
      Cost strategy: poll once/min + cache + fan out to all app users → ~43k calls/mo, under
      free 50k cap, near-realtime at €0. Works ONLY IF one call = all vehicles (bulk GTFS-RT
      feed); breaks if API is per-stop/per-query (~36k stops). Also unresolved: does the
      commercial-use-needs-agreement clause apply regardless of volume? Confirm both via Labs
      account, else email Rejseplanen.
- [ ] Citizenship-test prep (2nd B2C vertical) — corpus is free/public from uim.dk; see
      docs/citizenship-test.md. 40/45 Q types from official læremateriale + past tests; only the
      5 current-affairs Q need light RSS topic signals (no news archive — Mediestream unusable).
- [ ] Deploy RSS poller on VPS as soon as it's up (good use while waiting for ERST). Sources in
      docs/news-sources.md. Small feedparser cron → forward topic archive. Backfill via Wikipedia
      "202X i Danmark" + kforum media-mention rankings when we build the vertical.
- [ ] Fine-grained device stats for app support decisions: model-level breakdown (e.g. iPhone
      14 vs 15 vs 16, Samsung models), iOS/Android version distribution in Denmark. Sources:
      StatCounter (device model + OS version share for DK), Statista. Coarse stats already known
      (iOS ~53%, Android ~46%; Apple ~60% / Samsung ~22%).
- [ ] Dashboard: HTTPS (currently HTTP Basic Auth) — e.g. Caddy auto-TLS if we add a domain.
- [ ] Map app (frontend), PDF viewer, EN translation surfacing
- [ ] GDPR review before B2C (sole props / reklamebeskyttelse)
