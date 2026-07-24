"""One-time OCR + patch of the BAKED template chrome on smiley report PDFs.

The reports are a full-page background raster (yellow paper, green header bands, letterhead,
legend, footer banner) with per-report vector text on top. overlay_pdf.py can translate the
vector text, but the template's own labels — "Kontrolrapport", "Kontrolleret", "Ingen
anmærkninger", the findsmiley.dk footer — live INSIDE that image and stay Danish.

Rather than re-encoding the raster per report (expensive, and the JPEG bytes differ per file),
we do the work ONCE per template VARIANT and then patch at the PDF level: cover each label with
its own background colour and draw the English on top. Cheap per report, no image surgery.

Pipeline per variant:
  1. variant_key()  — perceptual hash of the background, so visually identical templates that
     differ in JPEG bytes collapse to one key. Decoded via JPEG draft mode (~8x faster).
  2. OCR (rapidocr, CPU, no system package) — boxes + Danish text. The model has no æøå, so it
     returns 'Rengoring' for 'Rengøring'; the LLM translating them is told to expect that.
  3. Colours straight from the pixels: fill = modal colour in the box (text is a minority),
     text colour = the pixel furthest from it. Works on white, yellow and green bands alike.
  4. avail_x1 — scan right from the box until the background colour changes, so a longer English
     label may grow into the band it sits on but never spills out of it.
  5. Translate all labels for the variant in ONE LLM call; store spec as JSON.

Build:  python -m denmarkapi.smiley.template --build --sample 600
        python -m denmarkapi.smiley.template --render <variant>   # visual check
"""
from __future__ import annotations
import argparse
import glob
import hashlib
import io
import json
import random
import sys
import threading
import time
from collections import Counter

import numpy as np
from PIL import Image

from .. import config
from ..llm import client

SPEC_DIR = config.DATA / "templates"
MIN_BG_WIDTH = 600          # smaller images are the 130x130 smiley icons, not the background
PHASH_SIZE = 48

_ocr = None
_ocr_lock = threading.Lock()

# Every label carries an explicit id and the model must echo it back. Positional alignment is
# NOT safe: a model that merges or drops one line silently shifts every label after it onto the
# wrong box, which is exactly what the first version of this did.
LABELS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "en"],
        "properties": {"id": {"type": "integer"}, "en": {"type": "string"}}}}},
}

SYSTEM = (
    "You translate the fixed labels of a Danish food-inspection report form (Fødevarestyrelsen "
    "'Kontrolrapport') into English. You get a JSON array of items, each with an 'id' and the "
    "OCR'd Danish text 'da'. "
    "IMPORTANT: the OCR cannot read Danish æ/ø/å — it writes 'ae'/'o'/'a' instead (Rengoring = "
    "Rengøring, Pabud = Påbud, bemaerkninger = bemærkninger) — and it sometimes drops spaces "
    "between words. Recover the intended Danish, then translate it. "
    "Return one item per input id, echoing the SAME id with its English text. Do not merge, "
    "split, add or drop items, and do not renumber. "
    "This is a government form: use the official English terms used by the Danish food authority. "
    "Leave UNCHANGED (copy verbatim): postal addresses, street names, phone numbers, URLs, "
    "e-mail addresses, CVR/P numbers, standalone numbers and dates. If a line is already English "
    "or is a proper noun, copy it unchanged."
)

# The form's fixed vocabulary, transcribed from the template itself and keyed by the normalised
# OCR string. These are the terms that appear on every report, so they are worth pinning rather
# than re-deriving per variant: the LLM handles anything not listed here.
OVERRIDES = {
    # letterhead / footer
    "kontrolrapport": "Inspection Report",
    "ministerietforfodevarer": "Ministry of Food,",
    "landbrugogfiskeri": "Agriculture and Fisheries",
    "fodevarestyrelsen": "Danish Veterinary and Food Administration",
    "mereomfodevarekontrologklagemulighederpawwwfindsmileydk":
        "More about food inspection and how to complain at www.findsmiley.dk",
    # business block
    "virksomhed": "Business",
    "adresse": "Address",
    "postnrby": "Postcode/Town",
    "cvrnr": "CVR no.",
    "dennekontroldato": "This inspection, date",
    "tidligerekontrol": "Previous inspections",
    "dato": "Date",
    # inspected-items table
    "kontrolleret": "Inspected",
    "resultat": "Result",
    "hygiejnehandteringaffodevarer": "Hygiene: Food handling",
    "rengoring": "Cleaning",
    "vedligeholdelse": "Maintenance",
    "virksomhedensegenkontrol": "Own-check system",
    "offentliggorelseafkontrolrapport": "Display of the inspection report",
    "uddannelseihygiejne": "Training in hygiene",
    "maerkningoginformation": "Labelling and information",
    "godkendelsermv": "Approvals etc.",
    "saerligemaerkningsordninger": "Special labelling schemes",
    "varestandarder": "Product standards",
    "tilsaetningsstoffermv": "Additives etc.",
    "kemiskeforureninger": "Chemical contamination",
    "emballagemv": "Packaging etc.",
    "andet": "Other",
    "ikkeallereglerbliverkontrollerethvergang": "Not all rules are checked every time",
    # legend
    "betyder": "Means",
    "ingenanmaerkninger": "No remarks",
    "indskaerpelse": "Injunction",
    "pabudforbudellertvangsboder": "Order, prohibition or coercive fines",
    "bodeforlaegpolitianmkarantaene": "Fine, police report, quarantine,",
    "autorisationellerregistreringfrataget": "authorisation or registration withdrawn",
    "darligsteresultatbestemmeraktuelsmiley":
        "The worst result determines the current smiley",
    "udgaetsymbolvisesfor": "Discontinued symbol. Shown for",
    "indskaerpelsergivetfor2022": "injunctions issued before 2022",
    # inspection type
    "kontroltypeogaktivitet": "Inspection type and activity",
    "ordinaerkontrol": "Routine inspection",
    "kontrolkampagne": "Inspection campaign",
    "ekstrakontrol": "Follow-up inspection",
    "kaedekontrol": "Chain inspection",
    "andenkontrol": "Other inspection",
    # remarks + signature block
    "tilsynsforendesbemaerkninger": "Inspector's remarks",
    "kontrollensvarighed": "Duration of the inspection",
    "afleverettil": "Handed to",
    "tilsynsforendesunderskrift": "Inspector's signature",
    # older template generations + the smiley/elite placard
    "miljoogfodevareministeriet": "Ministry of Environment and Food",
    "miljoogfodevareminlsterlet": "Ministry of Environment and Food",
    "ministerietforfodevarerlandbrugogfiskeri":
        "Ministry of Food, Agriculture and Fisheries",
    "resultatbetyder": "Result Means",
    "pabudellerforbud": "Order or prohibition",
    "autnr": "Auth. no.",
    "ingenanmaerkningerpadeseneste": "No remarks in the last",
    "4rapporterogideseneste12mdr": "4 reports and in the last 12 months",
    "eliteingenanmaerkningerpadeseneste": "Elite: No remarks in the last",
    "elitestatuskanogsaopnasienkelteandresituationer":
        "Elite status can also be achieved in certain other situations,",
    "elitestatuskanogsaopnastenkelteandresituationer":
        "Elite status can also be achieved in certain other situations,",
    "sewwwfindsmileydk": "see www.findsmiley.dk",
    "scanoglaeskontrolrapportenpa": "Scan and read the inspection report at",
    "kontrolresume": "Inspection summary",
    "periode": "Period:",
    "antalkontroller": "Number of inspections:",
    "resumeaftilsynsforendesbemaerkninger": "Summary of the inspector's remarks",
    "kontrolresumeudfaerdigetaf": "Inspection summary prepared by",
    "ikeallereglerbliverkontrollerethvergang": "Not all rules are checked every time",
    # 'Bødeforlæg' is a FINE. The OCR mangles it several ways and the model has guessed
    # "Food for sale" and "Bodily Injury" from the garbled forms — pin every variant seen.
    "bodeforlaegpolitianmeldelse": "Fine, police report,",
    "bodeforlegpolitianmeldlse": "Fine, police report,",
    "bodeforlgolitianmelds": "Fine, police report,",
    "bodeforlegpolitianmkarantaene": "Fine, police report, quarantine,",
    "bodeforlaeg": "Fine,",
    "politianmeldelse": "police report",
    "virksomhedskarantaene": "business quarantine,",
}

# Labels to leave in Danish verbatim: postal addresses and contact lines.
KEEP = {
    "stationsparken31332600glostruptif4572276900wwwfvstdk",
    "stationsparken312600glostrup",
    "4572276900wwwfvstdkkontakt",
}


def _norm(s: str) -> str:
    """Fold OCR quirks and Danish letters to a common key: no spaces/punctuation, æø å -> ae o a."""
    s = s.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    return "".join(ch for ch in s if ch.isalnum())


# --- variant identification --------------------------------------------------

def _decode(img_bytes: bytes, draft_to: int | None = PHASH_SIZE) -> Image.Image:
    im = Image.open(io.BytesIO(img_bytes))
    if draft_to:
        im.draft("L", (draft_to, draft_to))   # JPEG-only fast path; ignored for PNG
    return im


def variant_key(img_bytes: bytes) -> str:
    """Perceptual hash — identical layout, different JPEG bytes -> same key."""
    im = _decode(img_bytes).convert("L").resize((PHASH_SIZE, PHASH_SIZE), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32)
    return hashlib.sha256((a > a.mean()).tobytes()).hexdigest()[:16]


def page_backgrounds(doc, page):
    """Yield (xref, img_bytes, rect) for each full-page background image on the page."""
    for im in page.get_images(full=True):
        xref = im[0]
        # get_images already carries the dimensions (im[2]); checking them BEFORE extracting
        # avoids decoding the four 130x130 smiley icons on every page.
        if im[2] < MIN_BG_WIDTH:
            continue
        try:
            b = doc.extract_image(xref)
        except Exception:
            continue
        if b.get("width", 0) < MIN_BG_WIDTH:
            continue
        rects = page.get_image_rects(xref)
        if not rects:
            continue
        yield xref, b["image"], rects[0]


# --- colour + geometry from the pixels ---------------------------------------

def _box_colours(arr: np.ndarray, x0, y0, x1, y1):
    """(fill, text) RGB. Fill = modal colour (text is a minority of the box's pixels)."""
    crop = arr[y0:y1, x0:x1].reshape(-1, 3)
    if not len(crop):
        return (255, 255, 255), (0, 0, 0)
    q = (crop // 8 * 8).astype(np.uint8)                      # quantise: JPEG noise
    keys, counts = np.unique(q, axis=0, return_counts=True)
    fill = keys[counts.argmax()].astype(int)
    dist = np.abs(crop.astype(int) - fill).sum(axis=1)        # furthest pixel = the ink
    text = crop[dist.argmax()].astype(int)
    return tuple(int(v) for v in fill), tuple(int(v) for v in text)


def _avail_x1(arr: np.ndarray, x1, y0, y1, fill, limit) -> int:
    """How far right the English may grow: until ANY pixel in the band stops matching.

    This used to test the band's MEAN colour, which a 1-2px table border or ruled line barely
    moves — so a longer English label grew straight over the border and 'ate' it. Testing the
    worst row instead stops at the first line of ink, and the label shrinks to fit instead.
    """
    band = arr[max(0, y0):max(y0 + 1, y1), :, :].astype(int)
    if band.size == 0:
        return limit
    f = np.array(fill, dtype=int)
    for x in range(x1, limit):
        if np.abs(band[:, x, :] - f).sum(axis=1).max() > 90:   # any ink -> edge of the band
            return x
    return limit


def _is_bold(arr: np.ndarray, x0, y0, x1, y1, fill, text) -> bool:
    crop = arr[y0:y1, x0:x1].reshape(-1, 3).astype(int)
    if not len(crop):
        return False
    f, t = np.array(fill), np.array(text)
    ink = np.abs(crop - t).sum(axis=1) < np.abs(crop - f).sum(axis=1)
    return ink.mean() > 0.34          # ink coverage; bold headers sit well above regular text


# --- spec building -----------------------------------------------------------

def _ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def build_spec(key: str, img_bytes: bytes) -> dict:
    """OCR + colour-sample + translate one template variant. Returns the spec dict."""
    im = _decode(img_bytes, draft_to=None).convert("RGB")
    arr = np.asarray(im)
    h, w = arr.shape[:2]
    with _ocr_lock:
        res, _ = _ocr_engine()(np.asarray(im))
    res = res or []

    boxes = []
    for quad, txt, conf in res:
        if not txt.strip():
            continue
        x0 = max(0, int(min(p[0] for p in quad)) - 2)
        y0 = max(0, int(min(p[1] for p in quad)) - 2)
        x1 = min(w, int(max(p[0] for p in quad)) + 2)
        y1 = min(h, int(max(p[1] for p in quad)) + 2)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        fill, text = _box_colours(arr, x0, y0, x1, y1)
        boxes.append({
            "bbox": [x0, y0, x1, y1], "da": txt, "conf": float(conf),
            "fill": list(fill), "color": list(text),
            "bold": bool(_is_bold(arr, x0, y0, x1, y1, fill, text)),
            "avail_x1": int(_avail_x1(arr, x1, y0, y1, fill, w - 2)),
        })

    ens = _translate([b["da"] for b in boxes])
    for b, en in zip(boxes, ens):
        k = _norm(b["da"])
        b["en"] = b["da"] if k in KEEP else OVERRIDES.get(k, en)
    # Nothing to do for labels that translate to themselves (addresses, URLs, numbers).
    boxes = [b for b in boxes if _norm(b["en"]) != _norm(b["da"])]
    return {"variant": key, "width": w, "height": h, "built_at": time.time(), "boxes": boxes}


def _translate(texts: list[str]) -> list[str]:
    if not texts:
        return []
    out = client.chat(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": json.dumps(
             {"items": [{"id": i, "da": t} for i, t in enumerate(texts)]}, ensure_ascii=False)}],
        schema=LABELS_SCHEMA, max_tokens=4096, reasoning_effort="low")
    got = {it["id"]: it["en"] for it in out.get("items", [])
           if isinstance(it, dict) and isinstance(it.get("id"), int)}
    # An id the model failed to return keeps its Danish — a gap, never a shift.
    return [got.get(i, t) for i, t in enumerate(texts)]


# --- spec store --------------------------------------------------------------

_specs: dict[str, dict | None] = {}
_specs_lock = threading.Lock()


def spec_path(key: str):
    return SPEC_DIR / f"{key}.json"


def save_spec(spec: dict) -> None:
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    p = spec_path(spec["variant"])
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(spec, ensure_ascii=False))
    tmp.replace(p)


def load_spec(key: str) -> dict | None:
    """Cached; a miss is cached too (unknown variants must not re-hit the disk per page)."""
    with _specs_lock:
        if key in _specs:
            return _specs[key]
    p = spec_path(key)
    spec = None
    if p.exists():
        try:
            spec = json.loads(p.read_text())
        except Exception:
            spec = None
    with _specs_lock:
        _specs[key] = spec
    return spec


def known_variants() -> set[str]:
    return {p.stem for p in SPEC_DIR.glob("*.json")
            if not p.stem.startswith("_")} if SPEC_DIR.exists() else set()


# --- variants we have never seen before ---------------------------------------
# The specs were built from a SAMPLE of the PDFs we had at the time, and ~55k reports were
# still being downloaded. A template we have never seen must therefore be expected at any
# point, and must not silently leave a page in Danish. So: build its spec on first sight,
# once per variant, and record it either way so the dashboard can surface it.
UNKNOWN_LOG = SPEC_DIR / "_unknown.json"
_build_lock = threading.Lock()
_attempted: set[str] = set()
_unknown_seen: Counter = Counter()


def _record_unknown(key: str) -> None:
    _unknown_seen[key] += 1
    try:
        SPEC_DIR.mkdir(parents=True, exist_ok=True)
        tmp = UNKNOWN_LOG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dict(_unknown_seen)))
        tmp.replace(UNKNOWN_LOG)
    except Exception:
        pass


def ensure_spec(key: str, img_bytes: bytes, auto_build: bool = True) -> dict | None:
    """Spec for this variant, building it on first sight. None if that is not possible."""
    spec = load_spec(key)
    if spec is not None:
        return spec
    if not auto_build:
        _record_unknown(key)
        return None
    with _build_lock:                      # one builder per variant; others skip this page
        if key in _attempted:
            _record_unknown(key)
            return None
        _attempted.add(key)
    try:
        if not client.is_up():
            _record_unknown(key)
            return None
        spec = build_spec(key, img_bytes)
        save_spec(spec)
        with _specs_lock:
            _specs[key] = spec
        print(f"  [template] built spec for NEW variant {key} ({len(spec['boxes'])} labels)",
              file=sys.stderr)
        return spec
    except Exception as e:
        print(f"  [template] could not build spec for {key}: {str(e)[:120]}", file=sys.stderr)
        _record_unknown(key)
        return None


def unknown_variants() -> dict:
    try:
        return json.loads(UNKNOWN_LOG.read_text())
    except Exception:
        return {}


# --- applying a spec to a page ----------------------------------------------

def patch_page(doc, page, insert_text, obstacles=None) -> tuple[int, int]:
    """Cover the baked Danish labels and draw English. Returns (patched, unknown_variants).

    English labels are longer than Danish ones, so a label is allowed to grow to the right —
    but only until the band it sits on ends (avail_x1, from the pixels) AND only until the
    report's own text starts. `obstacles` are the vector text rects, which the caller must
    collect BEFORE redacting them, since by the time we patch, the page carries no text.
    """
    import fitz
    patched = unknown = 0
    for xref, img_bytes, rect in page_backgrounds(doc, page):
        key = variant_key(img_bytes)
        spec = ensure_spec(key, img_bytes)
        if spec is None:
            unknown += 1
            continue
        sx = rect.width / spec["width"]
        sy = rect.height / spec["height"]
        for b in spec["boxes"]:
            x0, y0, x1, y1 = b["bbox"]
            r = fitz.Rect(rect.x0 + x0 * sx, rect.y0 + y0 * sy,
                          rect.x0 + x1 * sx, rect.y0 + y1 * sy)
            page.draw_rect(r, color=None, fill=[c / 255 for c in b["fill"]], width=0)
            limit = rect.x0 + b["avail_x1"] * sx
            for ob in (obstacles or ()):        # stop before the report's own text
                if ob.x0 >= r.x1 - 1 and ob.y1 > r.y0 + 1 and ob.y0 < r.y1 - 1:
                    limit = min(limit, ob.x0 - 2)
            grow = fitz.Rect(r.x0, r.y0, max(limit, r.x1), r.y1)
            insert_text(page, grow, b["en"], r.height, [c / 255 for c in b["color"]], b["bold"])
            patched += 1
    return patched, unknown


# --- CLI ---------------------------------------------------------------------

def discover(sample: int | None) -> list[tuple[str, bytes, int]]:
    """Group page backgrounds by variant. sample=None scans every downloaded PDF."""
    import fitz
    from concurrent.futures import ThreadPoolExecutor
    paths = glob.glob(str(config.PDF_DIR / "*" / "*.pdf"))
    if sample:
        random.seed(11)
        paths = random.sample(paths, min(sample, len(paths)))
    counts: Counter = Counter()
    example: dict[str, bytes] = {}
    lock = threading.Lock()

    def scan(p):
        try:
            doc = fitz.open(p)
        except Exception:
            return
        for page in doc:
            for _, img_bytes, _ in page_backgrounds(doc, page):
                k = variant_key(img_bytes)
                with lock:
                    counts[k] += 1
                    example.setdefault(k, img_bytes)
        doc.close()

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, _ in enumerate(ex.map(scan, paths), 1):
            if i % 20000 == 0:
                print(f"  scanned {i}/{len(paths)} PDFs, {len(counts)} variants so far")
    return [(k, example[k], n) for k, n in counts.most_common()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="discover variants and build specs")
    ap.add_argument("--sample", type=int, default=600, help="PDFs to sample when discovering")
    ap.add_argument("--all", action="store_true", help="scan EVERY downloaded PDF, not a sample")
    ap.add_argument("--top", type=int, default=None, help="only build the N most common variants")
    ap.add_argument("--force", action="store_true", help="rebuild specs that already exist")
    ap.add_argument("--render", type=str, default=None, help="write a patched sample PDF+PNG")
    args = ap.parse_args()

    if args.render:
        return _render(args.render)
    if not args.build:
        ap.print_help()
        return 2
    if not client.is_up():
        print("ERROR: vLLM not reachable at", client.BASE, file=sys.stderr)
        return 1

    variants = discover(None if args.all else args.sample)
    total = sum(n for _, _, n in variants)
    print(f"{len(variants)} variants over {total} page-backgrounds")
    have = known_variants()
    built = 0
    for i, (key, img_bytes, n) in enumerate(variants[:args.top]):
        if key in have and not args.force:
            print(f"  [{i}] {key}  n={n:5d} ({100*n/total:4.1f}%)  already built")
            continue
        t0 = time.time()
        spec = build_spec(key, img_bytes)
        save_spec(spec)
        built += 1
        print(f"  [{i}] {key}  n={n:5d} ({100*n/total:4.1f}%)  "
              f"{len(spec['boxes'])} labels in {time.time()-t0:.1f}s -> {spec_path(key).name}")
    print(f"built {built} specs -> {SPEC_DIR}")
    return 0


def _render(key_or_pdf: str) -> int:
    """Render a report with only the template patch applied — for eyeballing the result."""
    import fitz
    from .overlay_pdf import _tpl_insert as _insert_fitted   # same sizing as the real overlay
    paths = glob.glob(str(config.PDF_DIR / "*" / "*.pdf"))
    random.seed(11)
    target = None
    if key_or_pdf.endswith(".pdf"):
        target = key_or_pdf
    else:
        for p in random.sample(paths, min(400, len(paths))):
            doc = fitz.open(p)
            for page in doc:
                for _, img_bytes, _ in page_backgrounds(doc, page):
                    if variant_key(img_bytes) == key_or_pdf:
                        target = p
                        break
            doc.close()
            if target:
                break
    if not target:
        print("no sample PDF found for", key_or_pdf, file=sys.stderr)
        return 1
    doc = fitz.open(target)
    tot = unk = 0
    for page in doc:
        obstacles = [fitz.Rect(l["bbox"]) for blk in page.get_text("dict")["blocks"]
                     for l in blk.get("lines", [])]
        p, u = patch_page(doc, page, _insert_fitted, obstacles)
        tot += p
        unk += u
    out = config.DATA / "templates" / f"render_{key_or_pdf[:12]}.pdf"
    doc.save(str(out))
    png = out.with_suffix(".png")
    doc[0].get_pixmap(dpi=140).save(str(png))
    doc.close()
    print(f"{target}: patched {tot} labels ({unk} unknown-variant pages) -> {out}\n{png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
