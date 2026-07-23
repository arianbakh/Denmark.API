# Tilbudsavis sources & terms (source-first, no aggregators)

Decision: ignore aggregators (Tjek/eTilbudsavis, MineTilbud). Go to each chain directly.
Getting the PDFs = backlog. This doc = enumerate producers + terms status (what's allowed now).

## Legal position (applies to all below)
Every chain reserves ALL IP rights to its tilbudsavis (text, images, layout) — confirmed on
Salling Group's terms; it is the standard position across Danish retail. Consequences:
- Allowed: viewing; deep-linking to the chain's own tilbudsavis page.
- NOT allowed without a written agreement: hosting/redistributing their PDFs, or commercial
  reuse of extracted content (prices, images) in our product.
- Raw facts (a price, a product name, validity dates) are not themselves copyrightable, but
  systematic scraping + the PDF's expression are, and it breaches site terms.
=> Path forward NOW = seek a data/partnership or official feed per chain. Do not scrape.
   Verify each chain's specific terms page at agreement time.

## Grocery (priority — join to store locations)
| Group | Chains | Own tilbudsavis page | Cadence |
|---|---|---|---|
| Salling Group (~32%) | Netto, Føtex, Bilka | yes, per-chain sites | weekly |
| Coop (~27%) | Kvickly, SuperBrugsen, Dagli'/Lokal Brugsen, Coop 365 | yes | weekly |
| REMA 1000 (~19%) | REMA 1000 | rema1000.dk | weekly (Sun) |
| Dagrofa (~15%) | Meny, Spar, Min Købmand, Let-Køb | yes | weekly |
| Lidl (~4%) | Lidl | lidl.dk + app | weekly |
Note: Aldi exited Denmark in 2023 (stores taken over by REMA 1000). Fakta closed.

## Non-food chains that publish tilbudsaviser (secondary)
- Home/DIY/garden: JYSK, Bauhaus, Silvan, STARK, XL-BYG, Davidsen, Harald Nyborg, jem & fix,
  Imerco, Ilva, Sinnerup, Daells Bolighus
- Electronics: Elgiganten, Power
- Health/beauty/variety: Matas, Normal
- Toys/sport: BR (Salling), Sport24, Sportmaster, Fætter BR

## Strategy: build internally NOW, publish only after permission
User decision: download + build/test the ingestion pipeline internally in parallel with
partnership talks, so nothing is blocked and we're ready to flip on once a deal lands.
- OK now: internal prototype only — download, parse, test on our own machines, NOT published,
  not redistributed, no public product using their content yet.
- Gate: public/commercial use waits for a written agreement or official feed per chain.
- Keep provenance + fetch dates so we can prove/replace content if terms require it.
- Lower legal risk if we prefer official per-chain feeds over scraping even for the prototype.

## Next actions (now)
- [ ] For each grocery group: locate its official tilbudsavis page + check for any public/partner feed
- [ ] Read each group's terms page; record allowed/forbidden per chain
- [ ] Draft partnership/permission inquiry template (like the CVR email) for chains we want
- [ ] Build internal prototype ingestion (download + parse + test), UNPUBLISHED
- [ ] Flip to production per chain only after permission/feed confirmed
