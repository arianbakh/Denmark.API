# Geocoding plan (DAWA is shutting down)

Problem: smiley XLSX has coords for only 53% of businesses; the map needs ~all of them.
DAWA (dawa.aws.dk / api.dataforsyningen.dk) — the obvious geocoder — **shuts down 2026-08-17**
(~3 weeks out). So don't build on the live DAWA API.

## How coordinates actually work (verified 2026-07-23)
CVR does NOT contain lat/lon. Chain is two steps:
1. P-number → CVR → canonical address (+ DAR access-address UUID in full CVR data).
2. address → the address register (DAR) → coordinates.
Verified with Gather Mind P-no 1032602165 → "Valdemars Have 30, 8000 Aarhus C" → DAR
adgangsadresse 2b82f454-… → x=10.19666 (lon), y=56.15164 (lat).
=> The coordinate SOURCE is always the address register. CVR only improves match quality.

## Decision: don't depend on any live geocoding API. Ingest the register in bulk.

### Now (only option, and enough) — bulk DAR register, joined locally
- Ingest the official **Danmarks Adresse Register (DAR)** as a BULK download (whole DK,
  adgangsadresser with ETRS89/WGS84 x,y) → Parquet/DuckDB table. One-off, no live API, no
  rate limits, no abuse risk, survives DAWA shutdown.
- Geocode smiley by joining its address strings (adresse1 → vejnavn/husnr + postnr) to DAR.
  Light normalization; unmatched rows fall back to postnr-centroid.

### Later (enhancer, needs CVR access) — exact join via P-number
- Once CVR access lands: for the 97% with a P-number, CVR gives the canonical address / DAR
  UUID → exact join to the DAR table (no fuzzy matching). Fills gaps + fixes mismatches.

## Not urgent
Map is a later phase. Geocoding can wait until we ingest DAR; no need to race the DAWA shutdown.

## TODO
- [ ] Confirm exact DAR bulk-download URL + format on Datafordeler/Dataforsyningen; ingest → Parquet.
- [ ] Geocode smiley via address join; measure match rate; postnr-centroid fallback for the rest.
- [ ] After CVR access: re-join the P-number rows on DAR UUID for exactness.
