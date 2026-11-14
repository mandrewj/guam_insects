"""The taxonomy editor (editor/): its vocabulary is the Python code's, its CSV files are
byte-identical to Python's, and what it predicts for an edit is what `resolve` makes of it.
Browser tests run the editor's own JavaScript in Chromium (Playwright) and are skipped when
no browser is installed (`uv run playwright install chromium`)."""

import subprocess
import time

import pytest
from conftest import C

from guaminsects import config, curation, editor, ids, snapshot, taxonomy

ASSETS = config.ROOT / "editor" / "assets"


def test_spec_js_is_current():
    assert editor.SPEC_JS.read_text(encoding="utf-8") == editor.spec_js(), \
        "editor/assets/spec.js is stale: run `uv run guaminsects editor-spec`"


@pytest.fixture(scope="module")
def browser():
    sync = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync.sync_playwright().start()
        b = pw.chromium.launch()
    except Exception as e:                      # no browser installed
        pytest.skip(f"no Chromium for Playwright: {e}")
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.set_content("<html><body></body></html>")
    for s in ("spec.js", "csv.js", "model.js"):
        pg.add_script_tag(path=str(ASSETS / s))
    yield pg
    assert not errors
    pg.close()


def run(page, texts, ops, name="T. Editor"):
    """Replay `ops` on the files; returns {files, rows (changed), errors, checks, ops}."""
    return page.evaluate("""([texts, ops, name]) => {
      const base = IOGModel.makeBase(texts, {kind: "files", label: "test"});
      const all = ops.map(o => IOGModel.op(o.type, o, name));
      const st = IOGModel.replay(base, all);
      const rows = {};
      for (const id of st.changed.keys()) if (st.row(id)) rows[id] = st.row(id);
      return {files: IOGModel.files(st), rows, errors: all.map(o => o.error), checks: IOGModel.check(st),
              ops: all, describe: all.map(o => IOGModel.describe(o, st))};
    }""", [texts, ops, name])


def repo_texts():
    return {p: (config.ROOT / p).read_text(encoding="utf-8") if (config.ROOT / p).exists() else None
            for p in editor.FILES}


def test_repo_files_round_trip_byte_for_byte(page):
    texts = repo_texts()
    same = page.evaluate("""(texts) => Object.fromEntries(Object.entries(texts).filter(([, t]) => t != null)
        .map(([p, t]) => [p, IOGCSV.writeTable(IOGCSV.readTable(t)) === t]))""", texts)
    assert same and all(same.values()), same


def fixture_texts(conn, files):
    taxonomy.write(taxonomy.rows(conn))
    paths = {"taxonomy.csv": taxonomy.REPO_CSV, "curation/taxa.csv": files[0],
             "curation/evidence.csv": files[1],
             "curation/annotations.csv": files[0].with_name("annotations.csv")}
    return {k: p.read_text(encoding="utf-8") if p.exists() else None for k, p in paths.items()}, paths


def test_the_editor_and_resolve_agree(page, conn, files):
    texts, paths = fixture_texts(conn, files)
    ops = [
        {"type": "tag", "id": "ORGIG", "place": "Rota", "status": "present", "source": "Buden 2004"},
        {"type": "tag", "id": "ORGIG", "place": "Yap", "status": "doubtful"},
        {"type": "voucher", "id": "ORGIG", "url": "https://www.inaturalist.org/observations/987654",
         "note": "unidentified on iNat"},
        {"type": "link", "id": "ORRHI", "url": "https://example.org/crb", "label": "CRB fact sheet"},
        {"type": "set", "id": "ORGIG", "column": "vernacularName", "value": "giant rhinoceros beetle"},
        {"type": "verify", "id": "ORRHI", "on": True, "source": "UOG specimen 12"},
        # a name COL lacks, merged into a COL species
        {"type": "synonymize", "id": "gbif:777", "into": "ORGIG", "reason": "same species"},
        # a COL synonym split out as its own species under Oryctes
        {"type": "split", "id": "gbif:2080570", "parent": "ORYCT", "reason": "a test"},
        {"type": "add", "parent": "ORYCT", "rank": "Species", "name": "Oryctes sp. GU-1",
         "status": "morphospecies", "note": "Ritidian"},
        {"type": "addName", "into": "ORRHI", "name": "Oryctes rhinoceras", "authorship": "Typo, 1900"},
        {"type": "move", "id": "CALIS", "parent": "SCARB"},
        {"type": "hide", "id": "CALLI", "reason": "nothing left in it"},
    ]
    out = run(page, texts, ops)
    assert out["errors"] == [None] * len(ops), list(zip(out["describe"], out["errors"], strict=True))
    assert out["checks"] == []
    assert set(out["files"]) == {"taxonomy.csv", "curation/taxa.csv", "curation/evidence.csv",
                                 "curation/annotations.csv"}
    new_id = out["ops"][8]["newId"]
    assert new_id == "IOG-1" and out["ops"][9]["newId"] == "IOG-2"
    # What the editor commits is what resolve reads ...
    for rel, path in paths.items():
        if rel != "taxonomy.csv":
            path.write_text(out["files"][rel], encoding="utf-8")
    cur = curation.load(*files)
    assert {r["taxon_id"]: r["editor"] for r in cur.rows if r["editor"] != "build"}.keys() >= {
        "ORGIG", "ORRHI", "gbif:777", "gbif:2080570", "IOG-1", "IOG-2", "CALIS", "CALLI"}
    assert all(a["added_by"] == "T. Editor" for a in cur.annotations)
    curation.resolve(conn, cur)
    after = {r["taxonID"]: r for r in taxonomy.rows(conn)}
    # ... and the rows it shows are the rows the rebuild writes, in every column it edits.
    cols = list(taxonomy.EDITABLE) + taxonomy.LIST_COLUMNS + ["taxonomicStatus", "modifiedBy"]
    for tid, mine in out["rows"].items():
        assert tid in after, f"{tid} is not in the rebuilt taxonomy"
        for c in cols:
            if c == "verificationStatus" and mine[c] != taxonomy.CONFIRMED:
                continue                       # computed levels: the rebuild decides
            assert str(after[tid][c]) == mine[c], (tid, c, after[tid][c], mine[c])
    assert after["gbif:777"]["acceptedNameUsageID"] == "ORGIG"
    assert after[new_id]["parentNameUsageID"] == "ORYCT"
    assert after["IOG-2"]["acceptedNameUsageID"] == "ORRHI"
    assert after["IOG-2"]["scientificNameAuthorship"] == "Typo, 1900"
    assert after["CALIS"]["family"] == "Scarabaeidae" == out["rows"]["CALIS"]["family"]
    # The order of the rows is the rebuild's too (depth first, children by name).
    js_order = page.evaluate("""([texts, ops]) => {
      const st = IOGModel.replay(IOGModel.makeBase(texts, {}), ops.map(o => IOGModel.op(o.type, o, "x")));
      return st.rows.map(r => r.taxonID); }""", [texts, ops])
    assert js_order == list(after)


def test_bad_edits_are_refused_and_leave_nothing(page, conn, files):
    texts, _ = fixture_texts(conn, files)
    ops = [
        {"type": "tag", "id": "ORGIG", "place": "Atlantis"},
        {"type": "synonymize", "id": "ORYCT", "into": "ORGIG"},        # genus into a species
        {"type": "move", "id": "ORYCT", "parent": "ORRHI"},            # under its own species
        {"type": "voucher", "id": "ORGIG", "url": "https://example.org/obs/1"},
        {"type": "set", "id": "ORGIG", "column": "gbifRecords", "value": "5"},
        {"type": "set", "id": "gbif:2080570", "column": "scientificName", "value": "X"},  # synonym
        {"type": "remove", "id": "ORGIG"},
        {"type": "link", "id": "ORGIG", "url": "ftp://x"},
    ]
    out = run(page, texts, ops)
    assert all(out["errors"]), list(zip(out["describe"], out["errors"], strict=True))
    assert "taxonomy.csv" not in out["files"] or set(out["files"]) == {"taxonomy.csv"}
    assert not {k for k in out["files"] if k.startswith("curation/")}


def test_list_cells_typed_in_the_table(page, conn, files):
    texts, _ = fixture_texts(conn, files)
    out = run(page, texts, [
        {"type": "set", "id": "ORGIG", "column": "distributionTags",
         "value": "Guam: present | Palau: absent (Nafus 1994)"},
        {"type": "set", "id": "ORGIG", "column": "associatedOccurrences",
         "value": "https://www.gbif.org/occurrence/42"},
        {"type": "set", "id": "ORGIG", "column": "distributionTags", "value": "Guam: present"},
        {"type": "set", "id": "ORGIG", "column": "distributionTags", "value": "Guam: maybe"},
    ])
    assert out["errors"][:3] == [None] * 3 and "present|absent|doubtful" in out["errors"][3]
    assert out["rows"]["ORGIG"]["distributionTags"] == "Guam: present"
    assert out["rows"]["ORGIG"]["associatedOccurrences"] == "https://www.gbif.org/occurrence/42"


def test_new_ids_follow_when_taken_meanwhile(page, conn, files):
    texts, _ = fixture_texts(conn, files)
    ops = [{"type": "add", "parent": "ORYCT", "rank": "Species", "name": "Oryctes sp. A",
            "status": "morphospecies", "newId": "IOG-1"},
           {"type": "tag", "id": "IOG-1", "place": "Guam", "status": "present"}]
    # Someone else committed IOG-1 first.
    rows = curation.load(*files).rows + [{c: "" for c in curation.TAXA_COLUMNS} | {
        "taxon_id": "IOG-1", "rank": "Genus", "name": "Novus", "parent_id": "SCARB"}]
    curation.write_csv(files[0], curation.TAXA_COLUMNS, rows)
    curation.resolve(conn, curation.load(*files))
    texts, _ = fixture_texts(conn, files)
    out = run(page, texts, ops)
    assert out["errors"] == [None, None]
    assert out["ops"][0]["newId"] == "IOG-2" and out["ops"][1]["id"] == "IOG-2"


# ---------------------------------------------------------------- the backend for the editor

def test_a_merged_genus_takes_its_species_along(conn, files):
    rows = curation.load(*files).rows + [{c: "" for c in curation.TAXA_COLUMNS} | {
        "taxon_id": "ORYCT", "status": "synonym", "accepted_id": "CALIS"}]
    curation.write_csv(files[0], curation.TAXA_COLUMNS, rows)
    curation.resolve(conn, curation.load(*files))
    t = {r["ext_id"]: dict(r) for r in conn.execute("SELECT * FROM taxa")}
    assert "ORYCT" not in t
    assert ids.to_ext(t["ORRHI"]["parent_id"]) == "CALIS"
    assert conn.execute("SELECT 1 FROM taxon_names WHERE name_id = ? AND taxon_id = ?",
                        (C("ORYCT"), C("CALIS"))).fetchone()


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def clone(tmp_path, monkeypatch):
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, "clone", "-q", str(remote), str(work))
    git(work, "config", "user.name", "Local Git")
    git(work, "config", "user.email", "local@example.org")
    (work / "curation").mkdir()
    for rel in editor.FILES:
        src = config.ROOT / rel
        (work / rel).write_text(src.read_text(encoding="utf-8") if src.exists() else
                                ",".join(curation.ANNOTATION_COLUMNS) + "\r\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    git(work, "push", "-q", "origin", "HEAD:main")
    monkeypatch.setattr(config, "ROOT", work)
    return work, remote


def test_local_commit_credits_the_editor_and_pushes(clone):
    work, remote = clone
    base = git(work, "rev-parse", "HEAD")
    ann = (work / "curation/annotations.csv").read_text() + \
        "L2655,distribution,Guam,present,,,A. Person,2026-11-14\r\n"
    out = editor.commit({"curation/annotations.csv": ann}, "Editor: 1 change by A. Person",
                        "A. Person", base)
    assert out["ok"] and out["pushed"], out
    assert git(remote, "log", "-1", "--format=%an|%s", "main") == \
        "A. Person|Editor: 1 change by A. Person"
    # a stale base, a bad file, a file the editor does not own
    assert editor.commit({}, "x", "A. Person", base)["status"] == 409
    head = git(work, "rev-parse", "HEAD")
    bad = editor.commit({"curation/annotations.csv": ann + "L2655,distribution,Atlantis,present,,,A,\r\n"},
                        "x", "A. Person", head)
    assert bad["status"] == 400 and "Atlantis" in " ".join(bad["errors"])
    assert editor.commit({"src/x.py": "x"}, "x", "A. Person", head)["status"] == 400
    assert editor.commit({}, "x", " ", head)["status"] == 400


def test_local_commit_replays_onto_a_newer_remote(clone, tmp_path):
    work, remote = clone
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    git(other, "config", "user.name", "Other")
    git(other, "config", "user.email", "o@example.org")
    (other / "README.md").write_text("someone else's change\n")
    git(other, "add", "README.md")
    git(other, "commit", "-q", "-m", "other")
    git(other, "push", "-q", "origin", "HEAD:main")
    base = git(work, "rev-parse", "HEAD")
    ann = (work / "curation/annotations.csv").read_text() + \
        "L2655,link,https://example.org,,,,A. Person,2026-11-14\r\n"
    out = editor.commit({"curation/annotations.csv": ann}, "Editor: link", "A. Person", base)
    assert out["ok"] and out["pushed"], out
    assert git(remote, "log", "--format=%s", "main").splitlines()[:2] == ["Editor: link", "other"]


def test_local_server_serves_only_the_editor_and_its_files(clone):
    import http.client
    import threading
    from functools import partial
    from http.server import ThreadingHTTPServer

    work, _ = clone
    (work / "editor").mkdir()
    (work / "editor" / "index.html").write_text("<p>editor</p>")
    (work / "secret.txt").write_text("no")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(editor.Handler, directory=str(work)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        def get(path, method="GET", headers=None, body=None):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, r.read()
        assert get("/editor/index.html")[0] == 200
        assert get("/taxonomy.csv")[0] == 200
        assert get("/secret.txt")[0] == 404
        assert get("/editor/../secret.txt")[0] == 404
        status, body = get("/api/editor/info")
        assert status == 200 and b'"head"' in body
        status, _ = get("/api/editor/commit", "POST", {"Origin": "https://evil.example",
                                                       "Content-Type": "application/json"}, b"{}")
        assert status == 403
    finally:
        srv.shutdown()


def test_snapshot_strips_pdf_text(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "s.sqlite")
    conn.execute("CREATE TABLE pdf_mentions (mention_id INTEGER, snippet TEXT, page INTEGER)")
    conn.execute("CREATE TABLE later_table (context TEXT, name TEXT)")
    conn.execute("INSERT INTO pdf_mentions VALUES (1, 'a sentence from a book', 3)")
    conn.execute("INSERT INTO later_table VALUES ('more words', 'Oryctes')")
    out = snapshot.strip(conn)
    assert out == {"pdf_mentions.snippet": 1, "later_table.context": 1}
    assert conn.execute("SELECT snippet, page FROM pdf_mentions").fetchone() == (None, 3)
    assert conn.execute("SELECT context, name FROM later_table").fetchone() == (None, "Oryctes")


def test_ui_loads_and_edits_from_files(browser, conn, files, tmp_path):
    """The whole page from file://: load the CSV files, tag a taxon with the form, see the
    change listed, and get the files to commit."""
    texts, paths = fixture_texts(conn, files)
    pg = browser.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.add_init_script("localStorage.setItem('iog-editor-name', 'UI Tester');")
    pg.route("**/api.github.com/**", lambda r: r.abort())
    pg.route("**/raw.githubusercontent.com/**", lambda r: r.abort())
    pg.goto((config.ROOT / "editor" / "index.html").as_uri())
    pg.wait_for_selector("#start-load", timeout=10000)        # GitHub unreachable here
    pg.click("#start-load")
    pg.set_input_files(".filepick input", [str(p) for p in paths.values() if p.exists()])
    pg.wait_for_function("window.IOGApp.st && window.IOGApp.st.rows.length > 5")
    pg.fill("#q", "gigas")
    pg.wait_for_selector('#list .item[data-id="ORGIG"]')
    pg.click('#list .item[data-id="ORGIG"]')
    pg.select_option('form[data-form="tag"] select[name="place"]', "Saipan")
    pg.fill('form[data-form="tag"] input[name="source"]', "seen 2026")
    pg.click('form[data-form="tag"] button[type="submit"]')
    pg.wait_for_selector(".chip.st-present")
    assert "Saipan" in pg.inner_text(".chips")
    assert pg.inner_text("#n-changes") == "1"
    pg.click("#changes-btn")
    assert "Saipan present" in pg.inner_text("#tab-changes")
    pg.click('.tabs button[data-tab="table"]')
    pg.wait_for_selector('.g-body .r[data-id="ORGIG"]')
    files_out = pg.evaluate("IOGModel.files(IOGApp.st)")
    assert "Saipan,present,seen 2026,,UI Tester" in files_out["curation/annotations.csv"]
    time.sleep(0.1)
    assert not errors, errors
    pg.close()
