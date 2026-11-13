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
        "SELECT t.taxon_id, w.image FROM wikidata_taxa w JOIN taxa t ON t.gbif_key = w.gbif_key "
        "WHERE w.image IS NOT NULL AND w.confidence = 'high'").fetchall()
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
        "SELECT t.taxon_id, w.inat_id FROM wikidata_taxa w JOIN taxa t ON t.gbif_key = w.gbif_key "
        "WHERE w.inat_id IS NOT NULL AND w.confidence = 'high'").fetchall()
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


def _cc_url(code: str) -> str:
    if code == "cc0":
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    return f"https://creativecommons.org/licenses/{code[3:]}/4.0/"


def select(conn, per_taxon: int = 6) -> dict[str, int]:
    """Rebuild taxon_photos: own photos by rank_hint, then borrowing for taxa with none."""
    cands: dict[int, list[dict]] = {}
    for r in conn.execute(
            "SELECT c.taxon_id, c.rank_hint, p.* FROM photo_candidates c JOIN photos p "
            "ON p.photo_id = c.photo_id WHERE p.status = 'ok' ORDER BY c.taxon_id, c.rank_hint"):
        cands.setdefault(r["taxon_id"], []).append(dict(r))
    taxa = {r["taxon_id"]: dict(r) for r in conn.execute(
        "SELECT taxon_id, parent_id, rank, lineage, hidden FROM taxa")}
    guam = dict(conn.execute("SELECT taxon_id, SUM(records) FROM taxon_presence WHERE area = 'GU' "
                             "GROUP BY taxon_id"))
    any_rec = dict(conn.execute("SELECT taxon_id, SUM(records) FROM taxon_presence GROUP BY taxon_id"))
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
    with conn:
        conn.execute("DELETE FROM taxon_photos")
        conn.executemany("INSERT INTO taxon_photos (taxon_id, position, photo_id, role, "
                         "from_taxon_id, selected_at) VALUES (?, ?, ?, ?, ?, ?)",
                         [(*r, db.now()) for r in rows])
    return {"with_own": len(own), "borrowed": lent}


def thumbs(conn, limit: int | None = None) -> dict[str, int]:
    """A THUMB_WIDTH px WebP of each taxon's card photo, kept in data/media/thumbs/."""
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT DISTINCT p.photo_id, p.thumb_url, p.source FROM taxon_photos tp JOIN photos p "
        "ON p.photo_id = tp.photo_id WHERE tp.position = 0").fetchall()
    stats = {"wanted": len(rows), "made": 0, "had": 0, "failed": 0}
    hosts = {"commons": ApiClient("", 1.0), "inaturalist": ApiClient("", 1.0)}
    for r in rows[:limit]:
        path = THUMB_DIR / thumb_name(r["photo_id"])
        if path.exists():
            stats["had"] += 1
            continue
        try:
            raw = hosts[r["source"]].get_bytes(r["thumb_url"])
            img = Image.open(io.BytesIO(raw)).convert("RGB")
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
