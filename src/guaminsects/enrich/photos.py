"""Photos: candidates from Wikimedia Commons and iNaturalist, selection, and thumbnails.

The public site shows photos from their hosts (Commons thumbnails, iNaturalist's open-data
bucket), with author, licence and a link to the source page (CLAUDE.md rule 3). What we keep
is a ~200 px WebP thumbnail per taxon for cards and identify tiles, small enough (~8 KB) to
ship inside the 100 MB deploy (data/media/thumbs/, copied into the build).

Allowed licences: CC0 (and public domain), CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA. No ND,
no all-rights-reserved, no GFDL-only.

Selection (`select`): a species shows its own photos (iNaturalist observations from
Micronesia, then iNat's taxon photos, then Commons). A genus, family or order shows up to
three of the species under it that are recorded here, Guam's best-recorded first, and says
whose pictures they are (`from_taxon_id`); its own Wikidata image comes after. A borrowed
photo is never lent on, and a 'review' link supplies no photos.
"""

import io
import re
import sys
import urllib.parse

import httpx
from PIL import Image

from .. import config, db
from .http import ApiClient

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
INAT = "https://api.inaturalist.org/v1"
THUMB_DIR = config.MEDIA_DIR / "thumbs"
THUMB_WIDTH = 200
INAT_OK = {"cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"}
LANDSCAPE = 1.2
# Wikimedia serves only standard thumbnail widths (https://w.wiki/GHai); others answer 400.
COMMONS_DISPLAY, COMMONS_THUMB = 960, 330


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
        code = "cc-by" + (m.group(1) or "") + (m.group(2) or "")
        return code, url
    return None


def commons_size(url: str, width: int) -> str:
    """The same Commons thumbnail at a standard width; an original (small file) as it is."""
    return re.sub(r"/\d+px-", f"/{width}px-", url) if "/thumb/" in url else url


def _text(html: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def commons_sweep(conn) -> dict[str, int]:
    """Licence and sizes for every Commons file Wikidata names (P18), 50 files a request."""
    rows = conn.execute(
        "SELECT taxon_id, image FROM taxon_wikidata "
        "WHERE image IS NOT NULL AND confidence = 'high'").fetchall()
    files: dict[str, list[int]] = {}
    for r in rows:
        name = urllib.parse.unquote(r["image"].rsplit("/", 1)[-1])
        files.setdefault(name, []).append(r["taxon_id"])
    known = {r[0] for r in conn.execute("SELECT photo_id FROM photos WHERE source = 'commons'")}
    todo = [f for f in files if f"commons:{f}" not in known]
    client = ApiClient(COMMONS_API, 1.0)
    stats = {"files": len(files), "asked": len(todo), "allowed": 0, "refused": 0}
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        d = client.get(params={"action": "query", "format": "json", "formatversion": 2,
                               "titles": "|".join("File:" + f for f in batch),
                               "prop": "imageinfo", "iiprop": "url|size|extmetadata",
                               "iiurlwidth": COMMONS_DISPLAY})
        stamp = db.now()
        norm = {n["to"]: n["from"] for n in d.get("query", {}).get("normalized", [])}
        with conn:
            for page in d.get("query", {}).get("pages", []):
                title = norm.get(page.get("title"), page.get("title", ""))
                name = title.split(":", 1)[-1]
                info = (page.get("imageinfo") or [{}])[0]
                meta = info.get("extmetadata") or {}
                lic = commons_license(meta)
                pid = f"commons:{name}"
                if not lic or not info.get("thumburl"):
                    stats["refused"] += 1
                    conn.execute("INSERT OR REPLACE INTO photos (photo_id, source, status, "
                                 "fetched_at) VALUES (?, 'commons', 'refused', ?)", (pid, stamp))
                    continue
                stats["allowed"] += 1
                w, h = info.get("thumbwidth"), info.get("thumbheight")
                artist = _text(meta.get("Artist", {}).get("value")) or "unknown author"
                conn.execute(
                    "INSERT OR REPLACE INTO photos (photo_id, source, page_url, display_url, "
                    "thumb_url, license_code, license_url, attribution, width, height, status, "
                    "fetched_at) VALUES (?, 'commons', ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?)",
                    (pid, info.get("descriptionurl"), info["thumburl"],
                     commons_size(info["thumburl"], COMMONS_THUMB), lic[0], lic[1],
                     f"© {artist}" if lic[0] != "cc0" else artist, w, h, stamp))
                for tid in files.get(name, []):
                    conn.execute("INSERT OR IGNORE INTO photo_candidates (taxon_id, photo_id, "
                                 "rank_hint) VALUES (?, ?, 30)", (tid, pid))
        print(f"  Commons: {min(i + 50, len(todo))}/{len(todo)}", file=sys.stderr)
    client.close()
    # Files answered before this run still need their candidate rows.
    with conn:
        for name, tids in files.items():
            for tid in tids:
                conn.execute("INSERT OR IGNORE INTO photo_candidates (taxon_id, photo_id, "
                             "rank_hint) SELECT ?, photo_id, 30 FROM photos WHERE photo_id = ? "
                             "AND status = 'ok'", (tid, f"commons:{name}"))
    return stats


def inat_taxon_sweep(conn, client: ApiClient) -> dict[str, int]:
    """iNaturalist taxon photos (the curated set on each taxon page), 30 taxa a request."""
    links = conn.execute(
        "SELECT taxon_id, inat_id FROM taxon_wikidata "
        "WHERE inat_id IS NOT NULL AND confidence = 'high'").fetchall()
    by_inat = {}
    for r in links:
        if str(r["inat_id"]).isdigit():
            by_inat.setdefault(int(r["inat_id"]), []).append(r["taxon_id"])
    done = {r[0] for r in conn.execute("SELECT inat_id FROM inat_photo_queries")}
    todo = sorted(set(by_inat) - done)
    stats = {"taxa": len(todo), "photos": 0, "refused": 0}
    from .inat_counts import patient_get

    for i in range(0, len(todo), 30):
        ids = todo[i:i + 30]
        d = patient_get(client, "/taxa/" + ",".join(map(str, ids)), {})
        stamp = db.now()
        with conn:
            for t in d.get("results", []):
                for pos, tp in enumerate(t.get("taxon_photos") or []):
                    ph = tp.get("photo") or {}
                    lic = (ph.get("license_code") or "").lower()
                    if lic not in INAT_OK:
                        stats["refused"] += 1
                        continue
                    url = ph.get("url") or ""
                    dims = ph.get("original_dimensions") or {}
                    pid = f"inat:{ph['id']}"
                    conn.execute(
                        "INSERT OR REPLACE INTO photos (photo_id, source, page_url, display_url, "
                        "thumb_url, license_code, license_url, attribution, width, height, status,"
                        " fetched_at) VALUES (?, 'inaturalist', ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?)",
                        (pid, f"https://www.inaturalist.org/photos/{ph['id']}",
                         url.replace("/square.", "/large."), url.replace("/square.", "/small."),
                         lic, _cc_url(lic), ph.get("attribution"), dims.get("width"),
                         dims.get("height"), stamp))
                    stats["photos"] += 1
                    for tid in by_inat.get(t["id"], []):
                        conn.execute("INSERT OR IGNORE INTO photo_candidates (taxon_id, photo_id, "
                                     "rank_hint) VALUES (?, ?, ?)", (tid, pid, 20 + pos))
            conn.executemany("INSERT OR REPLACE INTO inat_photo_queries (inat_id, asked_at) "
                             "VALUES (?, ?)", [(k, stamp) for k in ids])
        print(f"  iNat taxon photos: {min(i + 30, len(todo))}/{len(todo)}", file=sys.stderr)
    return stats


GBIF_OCC = "/occurrence/search"            # on cli.gbif_client (api.gbif.org/v1)
GBIF_CACHE = "https://api.gbif.org/v1/image/cache"
INAT_DATASET = "50c9509d-22c7-4a22-a47d-8c48425ef4a7"
# Specimen media that are not a picture of the animal: sound plots, labels on their own.
NOT_A_PHOTO = re.compile(r"waveform|spectrogram|sonogram|oscillogram|label", re.I)
REGION_PAGE = 300


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


def _gbif_photos(o: dict, per_occurrence: int) -> list[tuple]:
    """(photo_id, source, page, display, thumb, licence, licence url, attribution) for the
    usable images of one GBIF occurrence: a licence from the image, else the record's."""
    import hashlib

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
        lic_url = m["license"] if (m.get("license") or "").startswith("http") else _cc_url(lic)
        holder = m.get("rightsHolder") or m.get("creator") or o.get("recordedBy") or \
            o.get("institutionCode") or "unknown"
        inat = re.search(r"inaturalist-open-data\.s3\.amazonaws\.com/photos/(\d+)/", ident) or \
            re.search(r"static\.inaturalist\.org/photos/(\d+)/", ident)
        if inat:
            page = o.get("occurrenceID") if str(o.get("occurrenceID", "")).startswith("http") \
                else m.get("references") or f"https://www.gbif.org/occurrence/{o['key']}"
            base = re.sub(r"/original\.", "/{}.", ident)
            out.append((f"inat:{inat.group(1)}", "inaturalist", page, base.format("large"),
                        base.format("small"), lic, lic_url,
                        f"© {holder}" if lic != "cc0" else holder))
        else:
            h = hashlib.md5(ident.encode()).hexdigest()
            where = " ".join(x for x in (o.get("institutionCode"), o.get("catalogNumber")) if x)
            cache = f"occurrence/{o['key']}/media/{h}"
            out.append((f"gbif:{o['key']}:{h[:10]}", "gbif",
                        f"https://www.gbif.org/occurrence/{o['key']}",
                        f"{GBIF_CACHE}/fit-in/{COMMONS_DISPLAY}x/{cache}",
                        f"{GBIF_CACHE}/{COMMONS_THUMB}x/{cache}", lic, lic_url,
                        ("© " if lic != "cc0" else "") + holder + (f" · {where}" if where else "")))
        if len(out) == per_occurrence:
            break
    return out


def _store_gbif(conn, o: dict, tid: int, hint: int, per_occurrence: int, stamp: str) -> int:
    n = 0
    for pid, source, page, display, thumb, lic, lic_url, attribution in \
            _gbif_photos(o, per_occurrence):
        # An iNat photo met before (from iNat's own taxon photos) keeps that row.
        conn.execute(
            "INSERT OR IGNORE INTO photos (photo_id, source, page_url, display_url, thumb_url, "
            "license_code, license_url, attribution, status, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?)",
            (pid, source, page, display, thumb, lic, lic_url, attribution, stamp))
        conn.execute("INSERT INTO photo_candidates (taxon_id, photo_id, rank_hint) VALUES "
                     "(?, ?, ?) ON CONFLICT (taxon_id, photo_id) DO UPDATE SET "
                     "rank_hint = min(rank_hint, excluded.rank_hint)", (tid, pid, hint))
        n += 1
    return n


def _occurrence_taxon(o: dict, keys: dict[int, int]) -> int | None:
    from .. import ids
    from .gbif_checklist import COL_CHECKLIST as CHECKLIST

    usage = ((o.get("classifications") or {}).get(CHECKLIST) or {}).get("acceptedUsage") or {}
    # The extended release also has BOLD BINs ('BOLD.ADL3763'), which are not COL ids.
    col = [ids.from_col(usage["key"])] if ids.valid(usage.get("key") or "") and \
        ids.kind(ids.to_int(usage["key"])) == "col" else []
    for k in col + [o.get("acceptedTaxonKey"), o.get("taxonKey")]:
        if k is not None and k in keys:
            return keys[k]
    return None


def gbif_sweep(conn, client: ApiClient, per_taxon: int = 6) -> dict[str, int]:
    """Images on GBIF occurrences (iNaturalist observations, museum specimens, BOLD), with a
    licence on the image or the record. First every Hexapoda image from the five areas
    (rank_hint 5: an observation from here; 10: a specimen from here), then, for each species
    still without a photo of its own, images from anywhere (rank_hint 40)."""
    from .. import ids
    from .gbif_checklist import COL_CHECKLIST as CHECKLIST
    from .gbif_checklist import COL_HEXAPODA as ROOT

    keys = db.keymap(conn)
    stats = {"region_occurrences": 0, "region_photos": 0, "species_asked": 0,
             "species_found": 0, "photos": 0}
    base = {"checklistKey": CHECKLIST, "mediaType": "StillImage"}
    offset = 0
    while True:
        params = [*base.items(), ("taxonKey", ROOT), ("limit", REGION_PAGE),
                  ("offset", offset)] + [("country", a["gbif"]) for a in config.AREAS]
        d = client.get(GBIF_OCC, params)
        stamp = db.now()
        with conn:
            for o in d.get("results", []):
                tid = _occurrence_taxon(o, keys)
                if tid is None:
                    continue
                stats["region_occurrences"] += 1
                hint = 5 if o.get("datasetKey") == INAT_DATASET else 10
                stats["region_photos"] += _store_gbif(conn, o, tid, hint, 2, stamp)
        offset += REGION_PAGE
        print(f"  GBIF images in Micronesia: {min(offset, d.get('count', 0))}/{d.get('count')}",
              file=sys.stderr)
        if d.get("endOfRecords", True) or offset >= 100_000:
            break

    have = {keys.get(r[0], r[0]) for r in conn.execute(
        "SELECT c.taxon_id FROM photo_candidates c JOIN photos p ON p.photo_id = c.photo_id "
        "WHERE p.status = 'ok'")}
    asked = {r[0] for r in conn.execute("SELECT taxon_id FROM gbif_photo_queries")}
    todo = [r for r in conn.execute(
        "SELECT taxon_id FROM taxa WHERE rank IN ('Species', 'Subspecies') AND hidden = 0 "
        "ORDER BY taxon_id") if r[0] not in have and r[0] not in asked
        and ids.kind(r[0]) in ("col", "gbif")]
    for i, (tid,) in enumerate(todo):
        if ids.kind(tid) == "col":
            params = {**base, "taxonKey": ids.col_of(tid), "limit": 20}
        else:                                    # a Backbone species COL lacks
            params = {"mediaType": "StillImage", "taxonKey": tid, "limit": 20}
        d = client.get(GBIF_OCC, params)
        stamp, n = db.now(), 0
        with conn:
            for o in d.get("results", []):
                if n < per_taxon:
                    n += _store_gbif(conn, o, tid, 40, 1, stamp)
            conn.execute("INSERT OR REPLACE INTO gbif_photo_queries (taxon_id, images, asked_at)"
                         " VALUES (?, ?, ?)", (tid, n, stamp))
        stats["species_asked"] += 1
        stats["species_found"] += n > 0
        stats["photos"] += n
        if (i + 1) % 100 == 0:
            print(f"  GBIF images by species: {i + 1}/{len(todo)}, found {stats['species_found']}",
                  file=sys.stderr)
    return stats


def _cc_url(code: str) -> str:
    if code == "cc0":
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    return f"https://creativecommons.org/licenses/{code[3:]}/4.0/"


def select(conn, per_taxon: int = 6) -> dict[str, int]:
    """Rebuild taxon_photos: own photos by rank_hint, then borrowing for taxa with none."""
    # Candidates were found under whatever key the taxon had then (a GBIF Backbone key
    # before the Catalogue of Life): taxon_keys says which taxon each belongs to now.
    keys = db.keymap(conn)
    cands: dict[int, list[dict]] = {}
    seen: set[tuple[int, str]] = set()
    for r in conn.execute(
            "SELECT c.taxon_id, c.rank_hint, p.* FROM photo_candidates c JOIN photos p "
            "ON p.photo_id = c.photo_id WHERE p.status = 'ok' ORDER BY c.rank_hint, c.taxon_id"):
        tid = keys.get(r["taxon_id"], r["taxon_id"])
        if (tid, r["photo_id"]) not in seen:
            seen.add((tid, r["photo_id"]))
            cands.setdefault(tid, []).append(dict(r))
    taxa = {r["taxon_id"]: dict(r) for r in conn.execute(
        "SELECT taxon_id, parent_id, rank, lineage, hidden FROM taxa")}
    guam: dict[int, int] = {}
    any_rec: dict[int, int] = {}
    for r in conn.execute("SELECT taxon_id, area, records FROM taxon_presence "
                          "WHERE source != 'gbif_backbone'"):
        tid = keys.get(r["taxon_id"])
        if tid is not None:
            any_rec[tid] = any_rec.get(tid, 0) + (r["records"] or 0)
            if r["area"] == "GU":
                guam[tid] = guam.get(tid, 0) + (r["records"] or 0)
    rows = []
    own = {}
    for tid, lst in cands.items():
        if tid in taxa:
            own[tid] = lst[:per_taxon]
    # Species keep their own photos. Above species, a Wikidata image of a genus or family is
    # often a species that does not occur here (docs/LESSONS.md "foreign photos"), so a
    # photo of a species recorded in Micronesia comes first, Guam's best-recorded first,
    # landscape preferred; the group's own image is the fallback.
    species_with = [t for t in own if taxa[t]["rank"] in ("Species", "Subspecies")
                    and not taxa[t]["hidden"]]
    species_with.sort(key=lambda t: (-(guam.get(t) or 0), -(any_rec.get(t) or 0), t))
    lent = 0
    for tid, t in taxa.items():
        if t["rank"] in ("Species", "Subspecies"):
            rows += [(tid, i, p["photo_id"], "own", None) for i, p in enumerate(own.get(tid, []))]
            continue
        tag = f"/{tid}/"
        borrowed = []
        for sp in species_with:
            if tag in taxa[sp]["lineage"]:
                ph = next((p for p in own[sp] if p["width"] and p["height"]
                           and p["width"] >= LANDSCAPE * p["height"]), own[sp][0])
                borrowed.append((ph["photo_id"], sp))
                if len(borrowed) == 3:
                    break
        pos = 0
        for pid, sp in borrowed:
            rows.append((tid, pos, pid, "inherited", sp))
            pos += 1
        lent += bool(borrowed)
        for p in own.get(tid, [])[:2]:
            rows.append((tid, pos, p["photo_id"], "own", None))
            pos += 1
    # Still nothing (no species under it has a photo of its own, e.g. a class whose only
    # pictures are of families): take the first photo of each child that has one, deepest
    # taxa first so a family's picture reaches its order and then its class.
    first: dict[int, tuple[str, int]] = {}
    for tid, _pos, pid, role, sp in rows:
        if tid not in first:
            first[tid] = (pid, sp if role == "inherited" else tid)
    kids: dict[int, list[int]] = {}
    for tid, t in taxa.items():
        if t["parent_id"] is not None and not t["hidden"]:
            kids.setdefault(t["parent_id"], []).append(tid)
    raised = 0
    for tid in sorted(taxa, key=lambda x: -taxa[x]["lineage"].count("/")):
        if tid in first or taxa[tid]["rank"] in ("Species", "Subspecies"):
            continue
        got = [first[c] for c in sorted(kids.get(tid, []), key=lambda c: (-(guam.get(c) or 0),
                                                                          -(any_rec.get(c) or 0)))
               if c in first][:3]
        for pos, (pid, src) in enumerate(got):
            rows.append((tid, pos, pid, "inherited", src))
        if got:
            first[tid] = got[0]
            raised += 1
    with conn:
        conn.execute("DELETE FROM taxon_photos")
        conn.executemany("INSERT INTO taxon_photos (taxon_id, position, photo_id, role, "
                         "from_taxon_id, selected_at) VALUES (?, ?, ?, ?, ?, ?)",
                         [(*r, db.now()) for r in rows])
    return {"with_own": len(own), "borrowed": lent, "from_groups_below": raised}


def thumbs(conn, limit: int | None = None) -> dict[str, int]:
    """A THUMB_WIDTH px WebP of each taxon's card photo, kept in data/media/thumbs/."""
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT DISTINCT p.photo_id, p.thumb_url, p.source, p.width FROM taxon_photos tp "
        "JOIN photos p ON p.photo_id = tp.photo_id WHERE tp.position = 0"
        ).fetchall()
    stats = {"wanted": len(rows), "made": 0, "had": 0, "failed": 0}
    hosts = {"commons": ApiClient("", 1.0), "inaturalist": ApiClient("", 1.0),
             "gbif": ApiClient("", 0.5)}
    for r in rows[:limit]:
        path = THUMB_DIR / thumb_name(r["photo_id"])
        if path.exists() and r["width"]:
            stats["had"] += 1
            continue
        try:
            raw = hosts[r["source"]].get_bytes(r["thumb_url"])
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            if not r["width"]:
                # GBIF gives no size: the thumbnail's shape is the photo's, which is all the
                # page needs (the browser scales it).
                with conn:
                    conn.execute("UPDATE photos SET width = ?, height = ? WHERE photo_id = ?",
                                 (img.width, img.height, r["photo_id"]))
            h = round(img.height * THUMB_WIDTH / img.width)
            img.resize((THUMB_WIDTH, h), Image.LANCZOS).save(path, "WEBP", quality=72)
            stats["made"] += 1
        except (httpx.HTTPError, OSError, TypeError) as e:
            print(f"  thumb {r['photo_id']}: {e}", file=sys.stderr)
            stats["failed"] += 1
    for c in hosts.values():
        c.close()
    return stats


def thumb_name(photo_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", photo_id)[:120]
    return f"{safe}.webp"
