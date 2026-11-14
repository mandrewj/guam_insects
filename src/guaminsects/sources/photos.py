"""Photos: candidates from iNaturalist, Wikimedia Commons and GBIF occurrences, selection, and
~200 px WebP thumbnails. Writes photos.csv and media/thumbs/.

The public site shows photos from their hosts (Commons thumbnails, iNaturalist's open-data
bucket, GBIF's image cache), with author, licence and a link to the source page (CLAUDE.md
rule 3). What we keep is one small thumbnail per card photo, small enough to ship in git and
inside the 100 MB deploy.

Allowed licences: CC0 (and public domain), CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA. No ND,
no all-rights-reserved, no GFDL-only.

Selection: a species shows its own photos (iNaturalist observations from Micronesia, then
iNat's taxon photos, then Commons, then specimens from anywhere). A genus, family or order
shows up to three of the species under it that are recorded here, Guam's best-recorded first,
and says whose pictures they are (`from_id`); its own Wikidata image comes after. A borrowed
photo is never lent on.
"""

import hashlib
import io
import re
import sys
from pathlib import Path

import httpx
from PIL import Image

from .. import config, ids, schema
from . import gbif as gbifapi

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
INAT = "https://api.inaturalist.org/v1"
THUMB_DIR = config.ROOT / "media" / "thumbs"
THUMB_WIDTH = 200
INAT_OK = set(schema.LICENCES)
LANDSCAPE = 1.2
COMMONS_DISPLAY, COMMONS_THUMB = 960, 330     # standard widths Wikimedia serves
GBIF_CACHE = "https://api.gbif.org/v1/image/cache"
INAT_DATASET = "50c9509d-22c7-4a22-a47d-8c48425ef4a7"
NOT_A_PHOTO = re.compile(r"waveform|spectrogram|sonogram|oscillogram|label", re.I)
PER_TAXON = 6


def commons_license(meta: dict) -> tuple[str, str] | None:
    """(code, url) for an allowed Commons licence, else None."""
    short = (meta.get("LicenseShortName", {}).get("value") or "").strip()
    url = meta.get("LicenseUrl", {}).get("value") or ""
    s = short.lower().replace("_", " ")
    if re.search(r"\bnd\b|no ?deriv", s):
        return None
    if s in ("public domain", "pd") or s.startswith(("pd-", "pd ", "public domain")) or "cc0" in s:
        return "cc0", url or "https://creativecommons.org/publicdomain/zero/1.0/"
    m = re.match(r"cc[ -]by(-nc)?(-sa)?\b", s)
    if m:
        return "cc-by" + (m.group(1) or "") + (m.group(2) or ""), url
    return None


def commons_size(url: str, width: int) -> str:
    """The same Commons thumbnail at a standard width; an original (small file) as it is."""
    return re.sub(r"/\d+px-", f"/{width}px-", url) if "/thumb/" in url else url


def cc_url(code: str) -> str:
    if code == "cc0":
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    return f"https://creativecommons.org/licenses/{code[3:]}/4.0/"


def gbif_license(text: str | None) -> str | None:
    """An allowed licence code from a GBIF media or record licence (URL or words), else None."""
    s = (text or "").lower().replace("_", "-")
    if not s or re.search(r"\bnd\b|-nd\b|no-?deriv|noderiv|all rights", s):
        return None
    if "zero" in s or "cc0" in s or "publicdomain" in s or "public domain" in s:
        return "cc0"
    m = re.search(r"\bby(-nc)?(-sa)?\b", s.replace(" ", "-"))
    if m and ("creativecommons" in s or "cc" in s):
        return "cc-by" + (m.group(1) or "") + (m.group(2) or "")
    return None


def thumb_name(photo_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", photo_id)[:120] + ".webp"


def _text(html: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def gbif_photos(o: dict, per_occurrence: int) -> list[dict]:
    """The usable images of one GBIF occurrence, as photo dicts: a licence from the image,
    else the record's."""
    out = []
    for m in o.get("media") or []:
        ident = m.get("identifier") or ""
        if m.get("type") != "StillImage" or not ident.startswith("http") or \
                not (m.get("format") or "image/").startswith("image/") or \
                NOT_A_PHOTO.search(ident + " " + (m.get("title") or "")):
            continue
        lic = gbif_license(m.get("license")) if m.get("license") else gbif_license(o.get("license"))
        if not lic:
            continue
        lic_url = m["license"] if (m.get("license") or "").startswith("http") else cc_url(lic)
        holder = m.get("rightsHolder") or m.get("creator") or o.get("recordedBy") or \
            o.get("institutionCode") or "unknown"
        inat = re.search(r"inaturalist-open-data\.s3\.amazonaws\.com/photos/(\d+)/", ident) or \
            re.search(r"static\.inaturalist\.org/photos/(\d+)/", ident)
        if inat:
            page = o.get("occurrenceID") if str(o.get("occurrenceID", "")).startswith("http") \
                else m.get("references") or f"https://www.gbif.org/occurrence/{o['key']}"
            base = re.sub(r"/original\.", "/{}.", ident)
            out.append({"photo_id": f"inat:{inat.group(1)}", "source": "inaturalist",
                        "page_url": page, "display_url": base.format("large"),
                        "thumb_url": base.format("small"), "licence": lic, "licence_url": lic_url,
                        "attribution": f"© {holder}" if lic != "cc0" else holder})
        else:
            h = hashlib.md5(ident.encode()).hexdigest()
            where = " ".join(x for x in (o.get("institutionCode"), o.get("catalogNumber")) if x)
            cache = f"occurrence/{o['key']}/media/{h}"
            out.append({"photo_id": f"gbif:{o['key']}:{h[:10]}", "source": "gbif",
                        "page_url": f"https://www.gbif.org/occurrence/{o['key']}",
                        "display_url": f"{GBIF_CACHE}/fit-in/{COMMONS_DISPLAY}x/{cache}",
                        "thumb_url": f"{GBIF_CACHE}/{COMMONS_THUMB}x/{cache}", "licence": lic,
                        "licence_url": lic_url,
                        "attribution": ("© " if lic != "cc0" else "") + holder +
                        (f" · {where}" if where else "")})
        if len(out) == per_occurrence:
            break
    return out


# --- candidates ------------------------------------------------------------------------------

def inat_candidates(ds, taxa: list[str], client) -> dict[str, list[dict]]:
    """iNaturalist taxon photos (the curated set on each taxon page), 30 taxa a request."""
    from .inat import patient_get

    by_inat: dict[int, list[str]] = {}
    want = set(taxa)
    for r in ds["links"]:
        if r["system"] == "inaturalist" and r["taxon_id"] in want and r["value"].isdigit() \
                and r["confidence"] in ("high", "medium"):
            by_inat.setdefault(int(r["value"]), []).append(r["taxon_id"])
    out: dict[str, list[dict]] = {}
    keys = sorted(by_inat)
    for i in range(0, len(keys), 30):
        d = patient_get(client, "/taxa/" + ",".join(map(str, keys[i:i + 30])), {})
        for t in d.get("results", []):
            for pos, tp in enumerate(t.get("taxon_photos") or []):
                ph = tp.get("photo") or {}
                lic = (ph.get("license_code") or "").lower()
                if lic not in INAT_OK:
                    continue
                url = ph.get("url") or ""
                dims = ph.get("original_dimensions") or {}
                cand = {"photo_id": f"inat:{ph['id']}", "source": "inaturalist",
                        "page_url": f"https://www.inaturalist.org/photos/{ph['id']}",
                        "display_url": url.replace("/square.", "/large."),
                        "thumb_url": url.replace("/square.", "/small."), "licence": lic,
                        "licence_url": cc_url(lic), "attribution": ph.get("attribution") or "",
                        "width": dims.get("width"), "height": dims.get("height"), "hint": 20 + pos}
                for tid in by_inat.get(t["id"], []):
                    out.setdefault(tid, []).append(cand)
    return out


def commons_candidates(ds, taxa: list[str], client) -> dict[str, list[dict]]:
    """Licence and sizes of the Commons file Wikidata names (P18) for each taxon."""
    want = set(taxa)
    files: dict[str, list[str]] = {}
    for r in ds["links"]:
        if r["system"] == "commons" and r["taxon_id"] in want and r["confidence"] == "high":
            files.setdefault(r["value"], []).append(r["taxon_id"])
    out: dict[str, list[dict]] = {}
    names = sorted(files)
    for i in range(0, len(names), 50):
        batch = names[i:i + 50]
        d = client.get(params={"action": "query", "format": "json", "formatversion": 2,
                               "titles": "|".join("File:" + f for f in batch),
                               "prop": "imageinfo", "iiprop": "url|size|extmetadata",
                               "iiurlwidth": COMMONS_DISPLAY})
        norm = {n["to"]: n["from"] for n in d.get("query", {}).get("normalized", [])}
        for page in d.get("query", {}).get("pages", []):
            title = norm.get(page.get("title"), page.get("title", ""))
            name = title.split(":", 1)[-1]
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            lic = commons_license(meta)
            if not lic or not info.get("thumburl"):
                continue
            artist = _text(meta.get("Artist", {}).get("value")) or "unknown author"
            cand = {"photo_id": f"commons:{name}", "source": "commons",
                    "page_url": info.get("descriptionurl"), "display_url": info["thumburl"],
                    "thumb_url": commons_size(info["thumburl"], COMMONS_THUMB), "licence": lic[0],
                    "licence_url": lic[1], "attribution": f"© {artist}" if lic[0] != "cc0" else artist,
                    "width": info.get("thumbwidth"), "height": info.get("thumbheight"), "hint": 30}
            for tid in files.get(name, []):
                out.setdefault(tid, []).append(cand)
    return out


def gbif_candidates(ds, taxa: list[str], gbif, per_taxon: int = PER_TAXON) -> dict[str, list[dict]]:
    """Images on GBIF occurrences of each species: first from the five areas (hint 5: an
    iNaturalist observation from here, 10: a specimen from here), else from anywhere (40)."""
    by_id = {r["id"]: r for r in ds["taxa"] if r["status"] != "synonym"}
    out: dict[str, list[dict]] = {}
    for t in taxa:
        r = by_id.get(t)
        if not r or r["rank"] not in ("Species", "Subspecies"):
            continue
        if r["in_col"] == "yes" and ids.valid(t) and ids.kind(ids.to_int(t)) == "col":
            base = [("checklistKey", gbifapi.COL_CHECKLIST), ("taxonKey", t)]
        elif r["gbif_key"]:
            base = [("taxonKey", r["gbif_key"])]
        else:
            continue
        for hint, extra in ((None, [("country", a["gbif"]) for a in config.AREAS]), (40, [])):
            d = gbif.get(gbifapi.OCC, base + [("mediaType", "StillImage"), ("limit", 20)] + extra)
            for o in d.get("results", []):
                h = hint or (5 if o.get("datasetKey") == INAT_DATASET else 10)
                for p in gbif_photos(o, 2 if hint is None else 1):
                    out.setdefault(t, []).append({**p, "hint": h})
            if out.get(t):
                break
    return {t: v[:per_taxon * 2] for t, v in out.items()}


# --- selection --------------------------------------------------------------------------------

def own_rows(cands: dict[str, list[dict]], today: str, per_taxon: int = PER_TAXON) -> list[dict]:
    """photos.csv `own` rows: each taxon's best candidates by hint, without repeats."""
    rows = []
    for t, lst in cands.items():
        seen: set[str] = set()
        for c in sorted(lst, key=lambda c: c["hint"]):
            if c["photo_id"] in seen:
                continue
            seen.add(c["photo_id"])
            rows.append({
                "taxon_id": t, "position": str(len(seen) - 1), "photo_id": c["photo_id"],
                "role": "own", "source": c["source"], "page_url": c["page_url"] or "",
                "display_url": c["display_url"] or "", "thumb": "", "thumb_url": c["thumb_url"] or "",
                "width": str(c.get("width") or ""), "height": str(c.get("height") or ""),
                "licence": c["licence"], "licence_url": c["licence_url"] or "",
                "attribution": c["attribution"] or "", "retrieved": today})
            if len(seen) == per_taxon:
                break
    return rows


def inherit(ds) -> int:
    """Recompute the `inherited` rows: a group with no photo of its own shows up to three
    species under it that are recorded here (Guam's best-recorded first, landscape preferred);
    one still without takes the first photo of each child that has one, deepest first."""
    taxa = {r["id"]: r for r in ds["taxa"] if r["status"] != "synonym"}
    kids: dict[str, list[str]] = {}
    for t, r in taxa.items():
        if r["parent_id"] and not r["hidden"]:
            kids.setdefault(r["parent_id"], []).append(t)
    guam: dict[str, int] = {}
    anyrec: dict[str, int] = {}
    for r in ds["records"]:
        if r["source"] in ("gbif", "inat", "gbif_specimens") and r["taxon_id"] in taxa:
            anyrec[r["taxon_id"]] = anyrec.get(r["taxon_id"], 0) + int(r["records"] or 0)
            if r["area"] == "GU":
                guam[r["taxon_id"]] = guam.get(r["taxon_id"], 0) + int(r["records"] or 0)
    own: dict[str, list[dict]] = {}
    for p in ds["photos"]:
        if p["role"] == "own" and p["taxon_id"] in taxa:
            own.setdefault(p["taxon_id"], []).append(p)
    for v in own.values():                 # contiguous from 0, so a second run shifts nothing
        v.sort(key=lambda p: int(p["position"]))
        for i, p in enumerate(v):
            p["position"] = str(i)
    ds["photos"] = [p for p in ds["photos"] if p["role"] == "own"]

    def under(t: str) -> list[str]:
        out, stack = [], [t]
        while stack:
            for c in kids.get(stack.pop(), ()):
                out.append(c)
                stack.append(c)
        return out

    species_with = sorted((t for t in own if taxa[t]["rank"] in ("Species", "Subspecies")
                           and not taxa[t]["hidden"]),
                          key=lambda t: (-guam.get(t, 0), -anyrec.get(t, 0), ids.to_int(t)))
    rows, first = [], {}
    for t, r in taxa.items():
        if r["rank"] in ("Species", "Subspecies"):
            if t in own:
                first[t] = (own[t][0]["photo_id"], t)
            continue
        below = set(under(t))
        borrowed = []
        for sp in species_with:
            if sp in below:
                pic = next((p for p in own[sp] if p["width"] and p["height"] and
                            int(p["width"]) >= LANDSCAPE * int(p["height"])), own[sp][0])
                borrowed.append((pic["photo_id"], sp))
                if len(borrowed) == 3:
                    break
        pos = 0
        for pid, sp in borrowed:
            rows.append((t, pos, pid, sp))
            pos += 1
        if borrowed:
            first[t] = (borrowed[0][0], borrowed[0][1])
        elif t in own:
            first[t] = (own[t][0]["photo_id"], t)
    have = {t for t, *_ in rows}
    for t in sorted(taxa, key=lambda x: -_depth(taxa, x)):
        r = taxa[t]
        if t in have or r["rank"] in ("Species", "Subspecies") or t in first:
            continue
        got = [first[c] for c in sorted(kids.get(t, []), key=lambda c: (-guam.get(c, 0), -anyrec.get(c, 0)))
               if c in first][:3]
        for pos, (pid, src) in enumerate(got):
            rows.append((t, pos, pid, src))
        if got:
            first[t] = got[0]
    for t, pos, pid, sp in rows:
        ds["photos"].append({"taxon_id": t, "position": str(pos), "photo_id": pid,
                             "role": "inherited", "from_id": sp})
    # a group's own photos (its Wikidata image) come after the borrowed ones
    for t in {t for t, *_ in rows} & set(own):
        shift = sum(1 for r in rows if r[0] == t)
        for p in own[t]:
            p["position"] = str(int(p["position"]) + shift)
    return len(rows)


def _depth(taxa: dict, t: str) -> int:
    n, seen = 0, set()
    while taxa.get(t, {}).get("parent_id") and t not in seen:
        seen.add(t)
        t = taxa[t]["parent_id"]
        n += 1
    return n


# --- thumbnails --------------------------------------------------------------------------------

def thumbnails(ds, http, media: Path = THUMB_DIR, limit: int | None = None) -> dict[str, int]:
    """A THUMB_WIDTH px WebP of each taxon's card photo (position 0 of its own rows), kept in
    media/thumbs/. A photo that is gone or refused is dropped from the dataset."""
    media.mkdir(parents=True, exist_ok=True)
    stats = {"wanted": 0, "made": 0, "had": 0, "failed": 0}
    todo = [p for p in ds["photos"] if p["role"] == "own" and p["position"] == "0"]
    stats["wanted"] = len(todo)
    dead = set()
    for p in todo[:limit]:
        name = thumb_name(p["photo_id"])
        if (media / name).exists() and p["width"]:
            p["thumb"] = name
            stats["had"] += 1
            continue
        try:
            raw = http.get_bytes(p["thumb_url"])
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            if not p["width"]:
                p["width"], p["height"] = str(img.width), str(img.height)
            h = round(img.height * THUMB_WIDTH / img.width)
            img.resize((THUMB_WIDTH, h), Image.LANCZOS).save(media / name, "WEBP", quality=72)
            p["thumb"] = name
            stats["made"] += 1
        except (httpx.HTTPError, OSError, TypeError) as e:
            print(f"  thumb {p['photo_id']}: {e}", file=sys.stderr)
            stats["failed"] += 1
            if isinstance(e, httpx.HTTPStatusError) and 400 <= e.response.status_code < 500:
                dead.add(p["photo_id"])
    if dead:
        ds["photos"] = [p for p in ds["photos"] if p["photo_id"] not in dead]
    return stats


def refresh(ds, taxa: list[str], clients: dict, today: str, make_thumbs: bool = True,
            progress=print) -> dict[str, int]:
    """Photos for these taxa (species and subspecies from the three sources; groups borrow),
    then every group's borrowed photos are chosen again, then thumbnails."""
    species = [t for t in taxa if next((r["rank"] for r in ds["taxa"] if r["id"] == t), "")
               in ("Species", "Subspecies")]
    cands: dict[str, list[dict]] = {}
    for fn, key in ((inat_candidates, "inat"), (commons_candidates, "commons"),
                    (gbif_candidates, "gbif")):
        got = fn(ds, taxa if fn is not gbif_candidates else species, clients[key])
        for t, lst in got.items():
            cands.setdefault(t, []).extend(lst)
        progress(f"  photo candidates ({key}): {sum(len(v) for v in got.values())}")
    mine = set(taxa)
    ds["photos"] = [p for p in ds["photos"] if not (p["taxon_id"] in mine and p["role"] == "own")]
    rows = own_rows(cands, today)
    ds["photos"].extend(rows)
    inherited = inherit(ds)
    stats = {"taxa_with_photos": len({r["taxon_id"] for r in rows}), "own": len(rows),
             "inherited": inherited}
    if make_thumbs:
        stats |= {f"thumbs_{k}": v for k, v in thumbnails(ds, clients["bytes"]).items()}
    return stats



# --- living organisms first ----------------------------------------------------------------------

def tier(photo_id: str) -> int:
    """0: an iNaturalist photo (a live organism in the field); 1: Wikimedia Commons (mixed:
    often good, sometimes a plate); 2: a GBIF specimen image (museum drawers, slides, labels,
    colour cards)."""
    return 0 if photo_id.startswith("inat:") else 1 if photo_id.startswith("commons:") else 2


def prefer_living(ds, inat_client, bytes_client, today: str, media: Path = THUMB_DIR,
                  progress=print) -> dict[str, int]:
    """Put living photos first. For a taxon whose best photo is a specimen image, iNaturalist's
    taxon photos (through its iNaturalist link) are added ahead of it; then every taxon's own
    photos are ordered by tier (stable inside a tier), borrowed photos are chosen again, and
    the card thumbnails that changed are made."""
    own: dict[str, list[dict]] = {}
    for p in ds["photos"]:
        if p["role"] == "own":
            own.setdefault(p["taxon_id"], []).append(p)
    for v in own.values():
        v.sort(key=lambda p: int(p["position"]))
    stats = {"taxa": len(own), "reordered": 0, "replaced": 0, "still_specimens": 0, "thumbs_made": 0}
    needy = [t for t, v in own.items() if min(tier(p["photo_id"]) for p in v) == 2]
    got = inat_candidates(ds, needy, inat_client)
    progress(f"  {len(needy)} taxa with only specimen images; iNaturalist photos for {len(got)}")
    fresh = {t: own_rows({t: lst}, today) for t, lst in got.items()}
    for t, rows in fresh.items():
        if rows:
            have = {p["photo_id"] for p in rows}
            own[t] = rows + [p for p in own[t] if p["photo_id"] not in have]
            stats["replaced"] += 1
    ds["photos"] = [p for p in ds["photos"] if p["role"] != "own" or p["taxon_id"] not in own]
    for t, v in own.items():
        before = v[0]["photo_id"]
        v.sort(key=lambda p: tier(p["photo_id"]))          # stable: iNaturalist, Commons, GBIF
        stats["reordered"] += v[0]["photo_id"] != before and t not in fresh
        stats["still_specimens"] += tier(v[0]["photo_id"]) == 2
        for i, p in enumerate(v):
            p["position"] = str(i)
            if i:
                p["thumb"] = ""                              # only a card photo has a thumbnail file
        ds["photos"].extend(v)
    inherit(ds)
    stats["thumbs_made"] = thumbnails(ds, bytes_client, media)["made"]
    used = {p["thumb"] for p in ds["photos"] if p.get("thumb")}
    for f in media.glob("*.webp"):
        if f.name not in used:
            f.unlink()
    return stats
