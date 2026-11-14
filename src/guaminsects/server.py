"""`guaminsects serve`: the built site (site.nosync/public) on http://localhost, plus a curation API.

The site itself is static (it also works from file://) and is the same one deployed. The JSON
endpoints below write curation/taxa.csv and curation/evidence.csv through curation.py, the
same code a spreadsheet import uses; no page of the site calls them (the admin page is gone;
the local review tool will). Every save is validated against the whole tree before the file
is replaced, and the site is rebuilt afterwards. The server binds to 127.0.0.1 only.

    GET  /api/taxa?q=oryct          name search over the tree (for pickers)
    GET  /api/taxon/<id>            the resolved taxon, its curated row and evidence
    GET  /api/curated               every curated row
    POST /api/taxon                 {row fields}: add (no taxon_id) or change a taxon
    POST /api/taxon/<id>/delete     drop a curated row
    POST /api/evidence              {taxon_id, kind, ref, license, credit, note}
    POST /api/evidence/delete       {taxon_id, kind, ref}
    GET  /api/mentions/<id>         what the PDF scan found for a taxon
    POST /api/decision              {file, page, name, decision}: accepted|rejected|pending
    GET  /api/status                rebuild status
"""

import functools
import http.server
import json
import threading
import urllib.parse
from pathlib import Path

from . import curation, db, ids

_rebuild = {"running": False, "last": None, "error": None, "pending": False}
_lock = threading.Lock()


def _rebuild_site() -> None:
    from . import site

    with _lock:
        if _rebuild["running"]:
            _rebuild["pending"] = True
            return
        _rebuild["running"] = True
    try:
        while True:
            _rebuild["pending"] = False
            stats = site.build(db.connect())
            _rebuild["last"], _rebuild["error"] = {**stats, "at": db.now()}, None
            if not _rebuild["pending"]:
                break
    except Exception as e:                       # reported by /api/status
        _rebuild["error"] = str(e)
    finally:
        _rebuild["running"] = False


def _ensure_known(conn, row: dict) -> None:
    """A curator may add a taxon by a Catalogue of Life id or a GBIF key the tree does not
    have yet: fetch it (and, for a GBIF key, match its name to COL) first."""
    ext = str(row.get("taxon_id") or "").strip()
    if not ext or not ids.valid(ext):
        return
    tid = ids.to_int(ext)
    from .cli import col_client, gbif_client

    if ids.kind(tid) == "col" and not conn.execute(
            "SELECT 1 FROM col_taxa WHERE taxon_id = ? AND full = 1", (tid,)).fetchone():
        from .enrich import col

        col.fetch_taxa(conn, col_client(), {tid})
    elif ids.kind(tid) == "gbif" and not conn.execute(
            "SELECT 1 FROM name_matches WHERE key = ?", (tid,)).fetchone():
        from . import names
        from .enrich.gbif_checklist import fetch_taxa

        fetch_taxa(conn, gbif_client(), {tid})
        names.match_keys(conn, col_client(), {tid})


def _external(t: dict | None) -> dict | None:
    """A taxa row as the API returns it: ids in their external form."""
    if not t:
        return None
    t = dict(t)
    t["tid"] = t["taxon_id"]
    t["taxon_id"] = t["ext_id"] or ids.to_ext(t["taxon_id"])
    for f in ("parent_id", "accepted_id"):
        if t.get(f) is not None:
            t[f] = ids.to_ext(t[f])
    return t


class Handler(http.server.SimpleHTTPRequestHandler):
    editor = "curator"

    def log_message(self, fmt, *args):          # quieter: only API calls
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if not url.path.startswith("/api/"):
            return super().do_GET()
        conn = db.connect()
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/api/taxa":
            term = (q.get("q") or [""])[0].strip()
            rows = conn.execute(
                "SELECT taxon_id, ext_id, rank, name, status, origin, in_col FROM taxa "
                "WHERE name LIKE ? ORDER BY name LIKE ? DESC, length(name) LIMIT 25",
                (f"%{term}%", f"{term}%"))
            return self._json([_external(r) for r in rows])
        if url.path.startswith("/api/taxon/"):
            ext = urllib.parse.unquote(url.path.rsplit("/", 1)[-1])
            if not ids.valid(ext):
                return self._json({"error": f"not an id: {ext}"}, 404)
            tid = ids.to_int(ext)
            shown = conn.execute("SELECT taxon_id FROM taxon_keys WHERE key = ?", (tid,)).fetchone()
            t = conn.execute("SELECT * FROM taxa WHERE taxon_id = ?",
                             (shown[0] if shown else tid,)).fetchone()
            cur = curation.load(assign_ids=False)
            row = next((r for r in cur.rows if r["taxon_id"] == ext), None)
            ev = [e for e in cur.evidence if e["taxon_id"] == ext]
            parent = t and conn.execute("SELECT name, rank FROM taxa WHERE taxon_id = ?",
                                        (t["parent_id"],)).fetchone()
            names = t and [dict(r) | {"name_id": ids.to_ext(r["name_id"])} for r in conn.execute(
                "SELECT * FROM taxon_names WHERE taxon_id = ? ORDER BY name", (t["taxon_id"],))]
            return self._json({"taxon": _external(t), "curated": row, "evidence": ev,
                               "parent": dict(parent) if parent else None,
                               "names": names or []})
        if url.path.startswith("/api/mentions/"):
            ext = urllib.parse.unquote(url.path.rsplit("/", 1)[-1])
            tid = ids.to_int(ext) if ids.valid(ext) else -1
            rows = conn.execute(
                "SELECT file, page, name_found, method, kind, areas, islands, snippet, decision "
                "FROM pdf_mentions WHERE taxon_id IN (SELECT key FROM taxon_keys WHERE "
                "taxon_id = ?) ORDER BY kind != 'heading', file, page", (tid,)).fetchall()
            return self._json([dict(r) for r in rows])
        if url.path == "/api/curated":
            return self._json(curation.load(assign_ids=False).rows)
        if url.path == "/api/status":
            return self._json(_rebuild)
        return self._json({"error": "unknown endpoint"}, 404)

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        conn = db.connect()
        try:
            data = self._body()
            if url.path == "/api/taxon":
                _ensure_known(conn, data)
                stats = curation.upsert(conn, data, editor=data.pop("editor", None) or
                                        self.editor, reason=data.get("reason", ""))
            elif url.path.startswith("/api/taxon/") and url.path.endswith("/delete"):
                stats = curation.remove(conn, urllib.parse.unquote(url.path.split("/")[3]))
            elif url.path == "/api/evidence":
                stats = curation.add_evidence(conn, data, editor=self.editor)
            elif url.path == "/api/decision":
                from . import literature

                n = literature.decide(conn, data["file"], int(data["page"]), data["name"],
                                      data["decision"], self.editor, data.get("note", ""))
                stats = {"mentions": n}
            elif url.path == "/api/evidence/delete":
                stats = curation.remove_evidence(conn, str(data["taxon_id"]), data["kind"],
                                                 data["ref"])
            else:
                return self._json({"error": "unknown endpoint"}, 404)
        except curation.CurationError as e:
            return self._json({"ok": False, "errors": str(e).split("\n")}, 400)
        except (ValueError, KeyError) as e:
            return self._json({"ok": False, "errors": [f"bad request: {e}"]}, 400)
        threading.Thread(target=_rebuild_site, daemon=True).start()
        return self._json({"ok": True, "stats": stats})


def serve(root: Path, port: int = 8765, editor: str = "curator") -> int:
    if not (root / "index.html").exists():
        print(f"nothing built at {root}; run `uv run guaminsects build` first")
        return 1
    Handler.editor = editor
    handler = functools.partial(Handler, directory=str(root))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving {root} at http://localhost:{port}/  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
