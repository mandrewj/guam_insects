"""`guaminsects serve`: the built site on http://localhost, plus the curation admin.

The site itself is static (it also works from file://). The admin page (admin.html, local
build only) talks to the JSON endpoints below, which write curation/taxa.csv and
curation/evidence.csv through curation.py, the same code a spreadsheet import uses. Every
save is validated against the whole tree before the file is replaced, and the local site
is rebuilt afterwards. The server binds to 127.0.0.1 only; none of this exists on Vercel.

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

from . import config, curation, db

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
            stats = site.build(db.connect(), "local")
            _rebuild["last"], _rebuild["error"] = {**stats, "at": db.now()}, None
            if not _rebuild["pending"]:
                break
    except Exception as e:                       # shown on the admin page
        _rebuild["error"] = str(e)
    finally:
        _rebuild["running"] = False


def _ensure_gbif_key(conn, row: dict) -> None:
    """A curator may add a GBIF taxon by its key: fetch it (and its parents) first."""
    tid = str(row.get("taxon_id") or "")
    if tid.isdigit() and int(tid) < config.CURATED_ID_BASE and not conn.execute(
            "SELECT 1 FROM gbif_taxa WHERE gbif_key = ?", (int(tid),)).fetchone():
        from .cli import gbif_client
        from .enrich.gbif_checklist import fetch_taxa

        fetch_taxa(conn, gbif_client(), {int(tid)})


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
                "SELECT taxon_id, rank, name, status, origin FROM taxa WHERE name LIKE ? "
                "ORDER BY name LIKE ? DESC, length(name) LIMIT 25", (f"%{term}%", f"{term}%"))
            return self._json([dict(r) for r in rows])
        if url.path.startswith("/api/taxon/"):
            tid = url.path.rsplit("/", 1)[-1]
            t = conn.execute("SELECT * FROM taxa WHERE taxon_id = ?", (tid,)).fetchone()
            cur = curation.load(assign_ids=False)
            row = next((r for r in cur.rows if r["taxon_id"] == tid), None)
            ev = [e for e in cur.evidence if e["taxon_id"] == tid]
            parent = t and conn.execute("SELECT name, rank FROM taxa WHERE taxon_id = ?",
                                        (t["parent_id"],)).fetchone()
            g = t and t["gbif_key"] and conn.execute(
                "SELECT * FROM gbif_taxa WHERE gbif_key = ?", (t["gbif_key"],)).fetchone()
            return self._json({"taxon": dict(t) if t else None, "curated": row, "evidence": ev,
                               "parent": dict(parent) if parent else None,
                               "gbif": dict(g) if g else None})
        if url.path.startswith("/api/mentions/"):
            tid = int(url.path.rsplit("/", 1)[-1])
            rows = conn.execute(
                "SELECT file, page, name_found, method, kind, areas, islands, snippet, decision "
                "FROM pdf_mentions WHERE taxon_id = ? ORDER BY kind != 'heading', file, page",
                (tid,)).fetchall()
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
                _ensure_gbif_key(conn, data)
                stats = curation.upsert(conn, data, editor=data.pop("editor", None) or
                                        self.editor, reason=data.get("reason", ""))
            elif url.path.startswith("/api/taxon/") and url.path.endswith("/delete"):
                stats = curation.remove(conn, int(url.path.split("/")[3]))
            elif url.path == "/api/evidence":
                stats = curation.add_evidence(conn, data, editor=self.editor)
            elif url.path == "/api/decision":
                from . import literature

                n = literature.decide(conn, data["file"], int(data["page"]), data["name"],
                                      data["decision"], self.editor, data.get("note", ""))
                stats = {"mentions": n}
            elif url.path == "/api/evidence/delete":
                stats = curation.remove_evidence(conn, int(data["taxon_id"]), data["kind"],
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
        print(f"nothing built at {root}; run `uv run guaminsects build {root.name}` first")
        return 1
    Handler.editor = editor
    handler = functools.partial(Handler, directory=str(root))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        admin = " (admin: /admin.html)" if (root / "admin.html").exists() else ""
        print(f"serving {root} at http://localhost:{port}/{admin}  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
