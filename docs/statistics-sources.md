# Public / Open Danish Data Sources — catalog for the data lake

Catalog of PUBLIC / OPEN statistics and data sources in Denmark that could feed the
B2B/B2C data lake. Complements what's already ingested (smiley food-inspection, CVR
company/accounting, Rejseplanen, news RSS). For each source: what it covers, access method,
format, license + commercial-reuse status, update frequency, and a usefulness note.

**Verification note (2026-07-23):** API endpoints, licenses, and shutdown dates below were
checked via web search/fetch on this date. Items I could not fully verify are flagged
"UNVERIFIED". Two shutdowns to watch: **DAWA closes 17 Aug 2026** (migrate to Datafordeler/DAR);
**Sundhedsdatastyrelsen dissolves 31 Dec 2026**, replaced by "Digital Health Denmark" from 1 Jan 2027.

Recurring license shorthand:
- **CC BY 4.0** = free commercial + non-commercial reuse, attribution required. Green light.
- **Datafordeler / basic-data (grunddata)** = free, CC BY 4.0, but confidential/personal registers
  (CPR, some BBR fields) need a data-processor agreement.
- Aggregators/scrapers (boligsiden, Boliga, Tjek tilbudsavis) generally **forbid commercial reuse** —
  go to the authoritative public source instead.

---

## 1. National statistics — Danmarks Statistik (Statistics Denmark)

### StatBank API (statistikbanken / api.statbank.dk)
- **Covers:** ~2,000+ tables across demographics, economy, labour, prices, retail turnover,
  housing, household consumption, tourism, national accounts, trade, agriculture, environment.
  The backbone national-statistics source.
- **Access:** Public REST API, no auth (except the CATALOGUE format). Base `https://api.statbank.dk/v1/`.
  Endpoints: `/subjects` (subject hierarchy), `/tables` (list/filter tables), `/tableinfo`
  (table metadata + variables/codes), `/data` (retrieve data). POST recommended, GET supported.
- **Formats:** JSONSTAT, CSV, PX, DSTML, XLSX, HTML, PNG, BULK, SDMXCOMPACT, SDMXGENERIC. UTF-8, TLS 1.2+.
- **License:** **CC BY 4.0** — free commercial + non-commercial, source attribution required. Green light.
- **Rate/size limit:** non-bulk formats capped at **1,000,000 cells per request**; streaming/BULK
  formats have no cap (use BULK for large table pulls). No documented per-minute rate limit.
- **Update frequency:** varies per table (daily/monthly/quarterly/annual); each table has a release schedule.
- **Usefulness:** HIGHEST — one clean API covers most macro/demographic/economic context to join
  onto business and geo data. Start here for any aggregate stat. Good client libs exist (R `dkstat`,
  Python `danstat`) for reference, but call the API directly.

**Tables of interest (IDs to confirm against `/tables` — some IDs UNVERIFIED):**
- Consumption: **FU** series (Forbrugsundersøgelsen) — household consumption by COICOP group (5-digit,
  ~269 groups), household type, region, income. Annual. FU02 is discontinued ("AFSLUTTET"); use
  current FU tables (e.g. FU12/FU17/FU18-style).
- Prices: **PRIS** / forbrugerprisindeks (CPI), monthly.
- Retail trade turnover index (detailomsætning) — monthly, good demand signal for retail vertical.
- Demographics: **FOLK** population, **BEV** births/deaths, migration — quarterly/annual, geographic.
- Housing: **BOL** housing stock / **EJEN** property, **BM** building & construction.
- Tourism: **TURIST** overnight stays by region/nationality/accommodation — monthly.
- Labour: **RAS** register-based employment.
- Food waste: DST publishes some "spisevaner og madspild" material, but the authoritative food-waste
  tonnage series is Miljøstyrelsen (see §7), not StatBank.

---

## 2. Basic data & geo — Datafordeler, Dataforsyningen, DAWA

### Datafordeler (datafordeler.dk)
- **Covers:** authoritative Danish "grunddata" (basic data) registers: **DAR** (address register),
  **BBR** (buildings & housing), **Matriklen** (cadastre), **GeoDanmark** (topographic geodata),
  **DHM** elevation, company basic data. Legally authoritative — usable in binding processes.
- **Access:** REST + WFS/WMS APIs. **Free self-service registration** at datafordeler.dk to create a
  service user (username/password or certificate). Confidential registers / personal data (CPR, some
  BBR person fields) require a **data-processor agreement**; open subsets are freely available.
- **Formats:** JSON, XML, GML, WFS/WMS/WMTS.
- **License:** **CC BY 4.0** for free basic data (attribute the register, e.g. "BBR").
- **Update frequency:** near-real-time to daily depending on register (event-driven replication available).
- **Usefulness:** HIGH — canonical source for addresses (DAR), building attributes (BBR: use, year built,
  area, heating, technical installations), and cadastre. This is the **long-term replacement for DAWA**.

### DAWA (Danmarks Adressers Web API — dawadocs.dataforsyningen.dk)
- **Covers:** addresses, access addresses, road names, zones, "steder" (places), address washing
  (datavask), autocomplete, DAR history, reverse geocoding.
- **Access:** simple public REST, no auth, very developer-friendly (much easier than Datafordeler).
- **Formats:** JSON, GeoJSON, CSV; bulk replication endpoints.
- **License:** free public data (basic-data terms).
- **⚠️ SHUTTING DOWN:** DAWA closes **17 August 2026** (postponed from 1 July 2026). Autocomplete users
  must migrate to the "Adressevælger"; API users migrate to **DAR via Datafordeler**.
- **Usefulness:** HIGH short-term (this project already geocodes smiley via DAWA), but **plan migration
  to DAR/Datafordeler before Aug 2026** — do not build new long-term dependencies on DAWA.

### Dataforsyningen / GeoDanmark / Klimadatastyrelsen (dataforsyningen.dk)
- **Covers:** free public geodata & maps — background maps, orthophotos (annual nationwide GeoDanmark
  ortofoto), satellite imagery, elevation (DHM/DEM), place names, administrative boundaries
  (municipalities, regions, parishes), cadastral map, sea/depth data.
- **Access:** webservices (WMS, WMTS, WFS, WCS) + downloads + APIs. **Token-based auth** — free account
  at dataforsyningen.dk to generate a token. (Agency renamed: SDFE → SDFI → now **Klimadatastyrelsen** /
  Agency for Climate Data; docs on confluence.sdfi.dk / klimadatastyrelsen.dk.)
- **Formats:** raster tiles, GeoTIFF, GML, WFS/WMS.
- **License:** free geodata (CC BY 4.0-style basic-data terms), commercial reuse allowed w/ attribution.
- **Update frequency:** orthophotos annual; elevation periodic; vector data continuous.
- **Usefulness:** MEDIUM-HIGH — basemaps + boundaries for the map product; orthophotos/elevation for
  enrichment. GeoDanmark also gives building/road/hydrography topographic vectors.

### OpenStreetMap Denmark
- **Covers:** crowd-sourced POIs, roads, buildings, land use for Denmark.
- **Access:** **Geofabrik** regional extracts (`download.geofabrik.de/europe/denmark.html`), Overpass API
  for queries, planet diffs.
- **Formats:** PBF, OSM XML, shapefile extracts.
- **License:** **ODbL** — commercial reuse allowed BUT share-alike; attribution "© OpenStreetMap
  contributors". Note the share-alike obligation before mixing into proprietary derived DB.
- **Update frequency:** continuous; Geofabrik daily extracts.
- **Usefulness:** MEDIUM — good POI/name cross-reference and fallback geometry; watch ODbL share-alike.

---

## 3. Open data portals (municipal & thematic)

### Open Data DK (opendata.dk)
- **Covers:** municipal + regional open data — parking, traffic counts, cycle counts, bins, urban trees,
  cultural events, geodata, budgets. Aggregates many municipalities (Copenhagen, Aarhus, Aalborg, etc.).
- **Access:** **CKAN portal + CKAN Data API** (`/api/3/action/…`, DataStore SQL queries). Per-dataset
  download links. Managed by Open Data DK (assoc. of municipalities/regions, w/ Digitaliseringsstyrelsen,
  Erhvervsstyrelsen, KL).
- **Formats:** CSV, JSON, GeoJSON, WFS, XLSX (varies per dataset).
- **License:** mostly open (per-dataset; commonly CC BY 4.0 or "Andet (Open)"). **Check per dataset** —
  license field varies. UNVERIFIED as a blanket statement.
- **Update frequency:** varies widely per dataset (many stale/one-off).
- **Usefulness:** MEDIUM — breadth of hyper-local municipal signals; quality/freshness uneven. Good for
  city-level enrichment (e.g. Copenhagen mobility, Aarhus events).

### Virk / datacvr (Erhvervsstyrelsen) — already partly in scope
- **Covers:** CVR company register (2.2M+ companies, 2.8M+ production units, participants), and
  **offentliggørelser** (published annual accounts, PDF + XBRL).
- **Access:** system-to-system Elasticsearch distribution. `distribution.virk.dk/cvr-permanent`
  (needs access via cvrselvbetjening@erst.dk, IP allowlist) and `distribution.virk.dk/offentliggoerelser`
  (accounts index, **no login**, gzip required). Also datacvr.virk.dk web UI.
- **Formats:** JSON (Elasticsearch), PDF + XBRL for filings.
- **License:** public register, free reuse; honor **reklamebeskyttelse** (advertising-protection) flag;
  sole proprietors = personal data (GDPR). (Already covered in CLAUDE.md.)
- **Update frequency:** daily.
- **Usefulness:** HIGHEST (core, already in Phase 1).

---

## 4. Geo / addresses / cadastre
(Primary sources covered in §2: DAR, BBR, Matriklen, GeoDanmark, DHM, OSM.)
- **DAR (Danmarks Adresseregister):** authoritative addresses & road names via Datafordeler. CC BY 4.0.
  This is the go-forward source as DAWA sunsets.
- **BBR (Bygnings- og Boligregistret):** every property/building/unit — use code, year built, area,
  heating, technical installations. Via Datafordeler (open subset CC BY 4.0; person fields restricted).
  Directly useful to enrich food-business locations with building attributes.
- **Matriklen (cadastre):** parcels/land registration via Datafordeler.
- **Skråfoto / orthophotos:** oblique + orthophoto imagery via Dataforsyningen/Klimadatastyrelsen.

---

## 5. Energy
### Energi Data Service (energidataservice.dk) — Energinet
- **Covers:** electricity spot prices, consumption & production (by source: wind, solar, etc.), CO2
  emission intensity, grid/transmission data, gas data. Danish national TSO data.
- **Access:** fully public **REST API + downloads**, no auth. Also on opendata.dk.
- **Formats:** JSON, CSV; datasets queryable via API filters.
- **License:** open ("Andet (Open)"); free commercial reuse. (Verify exact license string per dataset.)
- **Update frequency:** real-time / hourly for many series.
- **Usefulness:** MEDIUM-HIGH — clean, reliable, high-frequency. Great B2B signal (energy prices, CO2)
  and easy to ingest.

---

## 6. Weather / climate — DMI Open Data
- **Covers:** meteorological observations (temp, wind, humidity, pressure, precipitation) from all DK +
  Greenland stations; climate data (station values, bounding-box queries); forecast model output
  (HARMONIE-AROME 2 km); radar; oceanographic; lightning.
- **Access:** **OGC API – Features** REST. **New endpoint `opendataapi.dmi.dk`** (live since 2025-12-02).
  As of **2026-03-26 no API key required** (previously key-gated via dmi.dk/friedata). Docs:
  `dmi.dk/friedata/dokumentation`. Also mirrored on AWS Open Data registry.
- **Formats:** GeoJSON FeatureCollections; GRIB for model data.
- **License:** free/open (DMI frie data). Commercial reuse allowed w/ attribution. (Confirm current terms.)
- **Update frequency:** observations ~10-min/hourly; forecasts several times daily.
- **Usefulness:** MEDIUM-HIGH — weather is a strong covariate for retail/food/mobility demand; now
  key-free = trivial to ingest.

---

## 7. Environment — Danmarks Miljøportal & Miljøstyrelsen
### Danmarks Miljøportal (miljoeportal.dk / arealdata)
- **Covers:** environmental & nature data — water quality, soil contamination (DKjord), protected nature,
  land use, forest map, groundwater (PULS/Jupiter), rat sightings (Rottereden), climate adaptation.
- **Access:** **WMS/WFS/WMTS + REST/SOAP** web services; Arealdata catalogue; file extracts. Some services
  need registration; QGIS plugin (dmpcatalogue) available.
- **Formats:** WMS/WFS/WMTS, SHAPE, TAB, GDB, GeoJSON.
- **License:** open environmental data (per-service; verify). Commercial reuse generally allowed.
- **Update frequency:** varies per dataset.
- **Usefulness:** MEDIUM — niche but rich geo/environmental enrichment.

### Food-waste statistics — Miljøstyrelsen (madspild)
- **Covers:** national food-waste tonnage by sector (households, retail, food service, industry, primary
  production) and by food category. E.g. 2025 report: >873,000 t avoidable food waste/yr; households ~36%,
  retail ~23%.
- **Access:** PDF reports (mst.dk / www2.mst.dk/Udgiv/publications), DCA Aarhus Univ. reports (dcapub.au.dk),
  NGO "Stop Spild af Mad" summaries (stopspildafmad.org/madspild-i-tal). No API — **report/PDF scraping**.
- **Formats:** PDF, some tables.
- **License:** public-sector reports, generally reusable w/ attribution (verify per report).
- **Update frequency:** periodic (multi-year studies; some annual updates).
- **Usefulness:** MEDIUM — authoritative food-waste context for the food/smiley + Too Good To Go angle.

---

## 8. Health — Sundhedsdatastyrelsen
### eSundhed (esundhed.dk)
- **Covers:** public health databank — operations, diagnoses, births, causes of death, medicine use,
  waiting times, at regional/municipal/hospital level. Aggregate, non-sensitive.
- **Access:** web databank with data tables + downloads. **No documented open REST API** (UNVERIFIED —
  some data exposed via opendata.dk mirror). "Closed eSundhed" (financing data) needs approval.
- **Formats:** web tables, Excel/CSV export.
- **License:** public data, freely accessible (verify reuse terms per dataset).
- **Update frequency:** varies per register (monthly/annual).
- **⚠️ ORG CHANGE:** Sundhedsdatastyrelsen ceases 31 Dec 2026; **Digital Health Denmark** from 1 Jan 2027.
  URLs/branding likely to change; access model expected to persist.
- **Usefulness:** LOW-MEDIUM for B2B/B2C data lake — aggregate only; microdata is register-gated for
  approved research (Forskerservice). Useful for population-health context, not individual-level.

Microdata (registers): individual-level health/social/economic registers are accessible **only** via
Danmarks Statistik / Sundhedsdatastyrelsen **Forskerservice** under strict researcher approval — not open,
not usable for a commercial data lake.

---

## 9. Real estate / property
- **BBR** (§2/§4) — authoritative building/housing attributes. Open subset CC BY 4.0. **Preferred source.**
- **Matriklen / Tinglysning:** cadastre via Datafordeler; land registration (Tinglysningen) has its own
  system-to-system access (deeds, mortgages) — some parts restricted/personal data.
- **Property valuations (ejendomsvurdering) & sales prices:** DST tables + Vurderingsstyrelsen. Historical
  sale prices also aggregated by **Boliga**/**Boligsiden** portals.
- **⚠️ Aggregators:** **Boligsiden.dk** and **Boliga** have NO documented public commercial API; scraping is
  done via 3rd-party tools (Apify) and their terms restrict reuse. Commercial resellers exist (ReData,
  BoligAPI, EjendomDanmark, Lasso) — **paid, licensed**, not open. For open/free: use **BBR + DST + Matriklen**.
- **Usefulness:** HIGH for enrichment (building age/size/use per address), but stick to authoritative public
  registers; avoid scraping portals for commercial use.

---

## 10. Transport / mobility
- **Rejseplanen** — journey planner / public-transport (already in scope; API via partnership).
- **Vejdirektoratet (Road Directorate) traffic data:** live traffic events, roadworks, congestion,
  winter road condition/deicing, road segments. **Free since 2020.** SDKs (iOS/web) on GitHub
  (`github.com/Vejdirektoratet`); NAP API base `https://data.vd-nap.dk`; **API key** via free account.
  Format JSON; real-time. Usefulness: MEDIUM (mobility signal).
- **Mastra traffic counts:** annual municipal + Road Directorate traffic counts, published via
  **opendata.dk** (Vejdirektoratet). CSV. Annual. Usefulness: MEDIUM (footfall/traffic proxy).
- **Rejsedata / DOT / GTFS:** Danish public-transport timetables are also published as **GTFS** feeds
  (rejseplanen/DOT) — check `rejsedata.dk` for open GTFS static + realtime (UNVERIFIED exact URL/terms).
  Useful open alternative for stops/routes.
- **DST transport tables:** vehicle stock, new registrations, passenger km (StatBank).

---

## 11. Sector / consumer signals
### Too Good To Go (food-waste app) — adoption in Denmark
- **Covers:** surplus-food marketplace, founded Denmark 2015. Global: ~120M registered users, ~180,000
  partners (Aug 2025). **Denmark-specific user counts are not officially published** (UNVERIFIED).
- **Access/data:** company financials via **CVR/regnskaber** (already ingestible) — e.g. Too Good To Go ApS
  (CVR 40316573) 2024 revenue DKK 725M (2023: 545M), profit DKK 9.6M. No open usage API.
- **License:** annual accounts are public (CVR); marketing stats are PR, cite carefully.
- **Usefulness:** MEDIUM — the DK financials are already reachable through your CVR pipeline; the "surplus
  bag"/partner data itself is proprietary. Good narrative + partner-count context for the food vertical.

### Retail / grocery / e-commerce statistics
- **DST retail turnover index** (§1) — authoritative, monthly, CC BY 4.0. **Preferred open source.**
- **FDIH / Dansk Erhverv "E-handelsanalysen"** — annual e-commerce reports (e.g. 2024: ~DKK 192bn online
  spend, grocery ~5.6% of e-commerce). PDF reports, free to read; **cite, don't redistribute wholesale**.
  (dansk erhverv PDF, e.g. danskehavecentre.dk mirror of E-handelsanalysen 2024.)
- **PostNord e-commerce report** — annual consumer survey (83% shop online monthly, 2024). PDF, free.
- **Euromonitor / Statista / ResearchAndMarkets** — paid market reports (retail/e-commerce). NOT open.
- **Usefulness:** MEDIUM — DST is the open backbone; industry PDFs add color but are report-scrape only.

---

## 12. EU / international with DK coverage
### Eurostat
- **Covers:** harmonized EU statistics incl. Denmark — economy, trade, demography, prices, tourism,
  environment, business demography.
- **Access:** public REST **statistics API** (data browser API), no auth.
- **Formats:** JSON-stat, SDMX, CSV.
- **License:** **free reuse, commercial + non-commercial, no written licence needed** (Eurostat reuse policy),
  attribution appreciated. Green light.
- **Update:** per dataset.
- **Usefulness:** MEDIUM-HIGH — cross-country benchmarking of DK; consistent definitions.

### OECD
- **Covers:** OECD-country indicators (economy, social, environment) incl. Denmark.
- **Access:** **SDMX REST API (SDMX-JSON)**, free, subject to OECD terms.
- **Formats:** SDMX-JSON, SDMX-ML, CSV.
- **License:** free of charge under OECD Terms & Conditions (check redistribution clause).
- **Usefulness:** MEDIUM — international benchmarking; overlaps Eurostat.

---

## 13. Research data
### Danish Data Archive (DDA) — now Rigsarkivet / DigiData
- **Covers:** ~3,000 datasets, mostly survey/social-science research data + administrative data.
- **Access:** **digidata.rigsarkivet.dk**. Datasets >20 yrs old w/o personal data = **freely
  downloadable**; newer/personal data requires an **application + approval**.
- **Formats:** SPSS/Stata/CSV survey files, documentation.
- **License:** varies; open for old non-personal data. Member of CESSDA ERIC.
- **Update:** archival, periodic accessions.
- **Usefulness:** LOW-MEDIUM — research/historical value; most useful items are gated. Not a live feed.

### University / other open datasets
- University repositories (KU, AU, DTU, CBS via re3data / national research-data services), plus
  **Zenodo/OSF** for DK research outputs. Ad hoc, per-dataset licenses. Usefulness: LOW (project-specific).

---

## Quick shutdown/deprecation flags
- **DAWA → closes 17 Aug 2026.** Migrate address geocoding to **DAR via Datafordeler** (this affects the
  smiley geocoding pipeline). Highest-priority migration item.
- **Sundhedsdatastyrelsen → dissolved 31 Dec 2026**, becomes **Digital Health Denmark** (1 Jan 2027);
  expect esundhed/URL changes.
- **Agency renames:** SDFE → SDFI → **Klimadatastyrelsen** (geodata). Old sdfe.dk links may redirect.
- **DST FU02** and various "AFSLUTTET" tables are discontinued — always resolve current table IDs via
  the `/tables` endpoint rather than hardcoding.

## Sources
- StatBank API: https://www.dst.dk/en/Statistik/hjaelp-til-statistikbanken/api
- Datafordeler: https://datafordeler.dk/ ; DAWA: https://dawadocs.dataforsyningen.dk/
- Dataforsyningen/Klimadatastyrelsen: https://dataforsyningen.dk/ ; https://www.klimadatastyrelsen.dk/kortlaegning/geodanmark
- Open Data DK: https://www.opendata.dk/
- Energi Data Service: https://www.energidataservice.dk/
- DMI open data: https://www.dmi.dk/friedata/dokumentation/
- Danmarks Miljøportal: https://miljoeportal.dk/ ; Miljøstyrelsen food waste: https://www2.mst.dk/
- eSundhed / Sundhedsdatastyrelsen: https://www.esundhed.dk/ ; https://sundhedsdatastyrelsen.dk/
- Vejdirektoratet: https://github.com/Vejdirektoratet ; Mastra via https://www.opendata.dk/vejdirektoratet
- Eurostat API: https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction
- OECD API: https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html
- DDA / Rigsarkivet: https://digidata.rigsarkivet.dk/ ; https://en.rigsarkivet.dk/guide/registry-data/
- Too Good To Go DK accounts (CVR 40316573): https://regnskaber.cvrapi.dk/40316573/
- OSM Denmark extracts: https://download.geofabrik.de/europe/denmark.html
