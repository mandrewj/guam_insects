"""The taxonomy editor (editor/): its vocabulary is the Python code's, its CSV files are
byte-identical to what Python's dataset.write makes, and what it commits passes dataset.check
and builds. Browser tests run the editor's own JavaScript in Chromium (Playwright) and are
skipped when no browser is installed (`uv run playwright install chromium`)."""

import subprocess
import time

import pytest

from guaminsects import config, dataset, editor
from guaminsects.build import records

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
              ops: all, describe: all.map(o => IOGModel.describe(o, st)), order: st.rows.map(r => r.taxonID)};
    }""", [texts, ops, name])


def texts_of(root):
    return {"dataset/" + t.file: (root / t.file).read_text(encoding="utf-8")
            if (root / t.file).exists() else None
            for t in (dataset.schema.table(n) for n in editor.EDIT_TABLES + editor.READ_TABLES)}


def test_repo_files_round_trip_byte_for_byte(page):
    texts = {p: (config.ROOT / p).read_text(encoding="utf-8")
             for p in editor.FILES if (config.ROOT / p).exists()}
    assert texts
    same = page.evaluate("""(texts) => Object.fromEntries(Object.entries(texts)
        .map(([p, t]) => [p, IOGCSV.writeTable(IOGCSV.readTable(t)) === t]))""", texts)
    assert all(same.values()), same


def test_the_editor_and_python_agree(page, world, tmp_path):
    texts = texts_of(world)
    ops = [
        {"type": "tag", "id": "ORGIG", "place": "Rota", "status": "present", "source": "Buden 2004"},
        {"type": "tag", "id": "ORGIG", "place": "Yap", "status": "doubtful"},
        {"type": "voucher", "id": "ORGIG", "url": "https://www.inaturalist.org/observations/987654",
         "note": "unidentified on iNat"},
        {"type": "link", "id": "ORRHI", "url": "https://example.org/crb", "label": "CRB fact sheet"},
        {"type": "set", "id": "ORGIG", "column": "vernacularName", "value": "giant rhinoceros beetle"},
        {"type": "verify", "id": "ORRHI", "on": True, "source": "UOG specimen 12"},
        {"type": "nativity", "id": "ORRHI", "value": "introduced", "source": "d1"},
        # a name COL lacks, merged into a COL species: its records follow through accepted_id
        {"type": "synonymize", "id": "gbif:777", "into": "ORGIG", "reason": "same species"},
        # a COL-synonym is not split here, but a hand-made name is
        {"type": "add", "parent": "ORYCT", "rank": "Species", "name": "Oryctes sp. GU-1",
         "status": "morphospecies", "note": "Ritidian"},
        {"type": "addName", "into": "ORRHI", "name": "Oryctes rhinoceras", "authorship": "Typo, 1900"},
        {"type": "move", "id": "CALIS", "parent": "SCARB"},
        {"type": "hide", "id": "CALLI", "reason": "nothing left in it"},
        {"type": "review", "id": "ORGIG", "table": "literature", "doc": "d1", "kind": "account"},
        {"type": "reject", "id": "ORGIG", "table": "notes", "doc": "d1", "topic": "biology"},
        {"type": "place", "unplacedName": "Zorotypus guineensis", "name": "Zorotypus guineensis",
         "rank": "Species", "parent": "ORYCT"},
    ]
    out = run(page, texts, ops)
    assert out["errors"] == [None] * len(ops), list(zip(out["describe"], out["errors"], strict=True))
    assert out["checks"] == []
    assert set(out["files"]) == {"dataset/taxa.csv", "dataset/distribution.csv", "dataset/vouchers.csv",
                                 "dataset/links.csv", "dataset/literature.csv", "dataset/notes.csv",
                                 "dataset/unplaced.csv".replace("dataset/", "dataset/review/")}
    assert out["ops"][8]["newId"] == "IOG-1" and out["ops"][9]["newId"] == "IOG-2"
    assert out["ops"][14]["newId"] == "IOG-3"
    # What the editor commits is what Python reads: it passes the checks ...
    new = tmp_path / "after"
    new.mkdir()
    for rel, text in {**texts, **out["files"]}.items():
        if text is not None:
            (new / rel.removeprefix("dataset/")).parent.mkdir(parents=True, exist_ok=True)
            (new / rel.removeprefix("dataset/")).write_text(text, encoding="utf-8")
    ds = dataset.load(new)
    assert dataset.check(ds).items == []
    # ... is canonical (Python writing it again changes nothing, so rows are in Python's order) ...
    import shutil

    again = tmp_path / "again"
    shutil.copytree(new, again)                  # a table that exists is written even when empty
    dataset.write(ds, again)
    for f in new.rglob("*.csv"):
        assert f.read_bytes() == (again / f.relative_to(new)).read_bytes(), f.name
    # ... and builds, showing the edits.
    recs = records.build_records(ds, thumbs=tmp_path)
    from conftest import C
    gigas = recs[C("ORGIG")]
    assert [d["place"] for d in gigas["distribution"]] == ["Rota", "Yap"]
    assert gigas["common"] == "giant rhinoceros beetle" and gigas["evidence"][0]["ref"] == "987654"
    assert gigas["literature"][0]["machine_read"] is False and gigas["synonyms"].count("Oryctes marianus") == 1
    assert recs[C("ORRHI")]["nativity"] == "introduced" and recs[C("ORRHI")]["nativity_review"] == "editor"
    assert recs[C("CALIS")]["lineage"][-1]["name"] == "Scarabaeidae"
    assert recs[C("CALLI")]["hidden"] is True
    assert any(r["name"] == "Zorotypus guineensis" for r in recs.values())
    # The row order the editor shows is the rebuild's.
    assert out["order"] == [r["id"] for r in ds["taxa"]]


def test_bad_edits_are_refused_and_leave_nothing(page, world):
    texts = texts_of(world)
    ops = [
        {"type": "tag", "id": "ORGIG", "place": "Atlantis"},
        {"type": "synonymize", "id": "ORYCT", "into": "ORGIG"},        # genus into a species
        {"type": "move", "id": "ORYCT", "parent": "ORRHI"},            # under its own species
        {"type": "voucher", "id": "ORGIG", "url": "https://example.org/obs/1"},
        {"type": "set", "id": "ORGIG", "column": "gbifRecords", "value": "5"},
        {"type": "set", "id": "gbif:2080570", "column": "vernacularName", "value": "X"},  # a synonym
        {"type": "remove", "id": "ORGIG"},
        {"type": "link", "id": "ORGIG", "url": "ftp://x"},
        {"type": "nativity", "id": "ORGIG", "value": "alien"},
        {"type": "review", "id": "ORRHI", "table": "literature"},      # nothing machine-made there
    ]
    out = run(page, texts, ops)
    assert all(out["errors"]), list(zip(out["describe"], out["errors"], strict=True))
    assert out["files"] == {}


def test_list_cells_typed_in_the_table(page, world):
    out = run(page, texts_of(world), [
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


def test_a_merge_and_its_undo_lose_nothing(page, world):
    """Rows keep pointing at the synonym; accepted_id is the whole merge."""
    texts = texts_of(world)
    out = run(page, texts, [{"type": "synonymize", "id": "gbif:777", "into": "ORGIG"}])
    assert out["errors"] == [None]
    taxa = out["files"]["dataset/taxa.csv"]
    assert "gbif:777," in taxa and ",ORGIG," in taxa
    assert set(out["files"]) == {"dataset/taxa.csv"}              # no other table changed
    back = run(page, {**texts, **out["files"]}, [{"type": "split", "id": "gbif:777", "parent": "ORYCT"}])
    assert back["errors"] == [None] and back["checks"] == []


def test_new_ids_follow_when_taken_meanwhile(page, world):
    ops = [{"type": "add", "parent": "ORYCT", "rank": "Species", "name": "Oryctes sp. A",
            "status": "morphospecies", "newId": "IOG-1"},
           {"type": "tag", "id": "IOG-1", "place": "Guam", "status": "present"}]
    # Someone else committed IOG-1 first.
    ds = dataset.load(world)
    ds["taxa"].append({"id": "IOG-1", "parent_id": "SCARB", "rank": "Genus", "name": "Novus",
                       "status": "accepted", "nativity": "unknown", "in_col": "no"})
    dataset.write(ds, world)
    out = run(page, texts_of(world), ops)
    assert out["errors"] == [None, None]
    assert out["ops"][0]["newId"] == "IOG-2" and out["ops"][1]["id"] == "IOG-2"


# ---------------------------------------------------------------- the backend for the editor

def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def clone(tmp_path, monkeypatch, world):
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, "clone", "-q", str(remote), str(work))
    git(work, "config", "user.name", "Local Git")
    git(work, "config", "user.email", "local@example.org")
    ds = dataset.load(world)
    dataset.write(ds, work / "dataset")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    git(work, "push", "-q", "origin", "HEAD:main")
    monkeypatch.setattr(config, "ROOT", work)
    return work, remote


DIST = "dataset/distribution.csv"


def test_local_commit_credits_the_editor_and_pushes(clone):
    work, remote = clone
    base = git(work, "rev-parse", "HEAD")
    ann = ((work / DIST).read_text(encoding="utf-8")
           if (work / DIST).exists() else "\ufefftaxon_id,place,status,source,added_by,added\n")
    good = ann + "ORGIG,Guam,present,,A. Person,2026-11-14\n"
    out = editor.commit({DIST: good}, "Editor: 1 change by A. Person", "A. Person", base)
    assert out["ok"] and out["pushed"], out
    assert git(remote, "log", "-1", "--format=%an|%s", "main") == \
        "A. Person|Editor: 1 change by A. Person"
    # a stale base, a bad file, a file the editor does not own
    assert editor.commit({}, "x", "A. Person", base)["status"] == 409
    head = git(work, "rev-parse", "HEAD")
    bad = editor.commit({DIST: good + "ORGIG,Atlantis,present,,A,2026-11-14\n"}, "x", "A. Person", head)
    assert bad["status"] == 400 and "Atlantis" in " ".join(bad["errors"])
    assert editor.commit({"src/x.py": "x"}, "x", "A. Person", head)["status"] == 400
    assert editor.commit({"dataset/records.csv": "x"}, "x", "A. Person", head)["status"] == 400   # read-only
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
    text = ((work / DIST).read_text(encoding="utf-8") if (work / DIST).exists()
            else "\ufefftaxon_id,place,status,source,added_by,added\n") + "ORGIG,Rota,present,,A. Person,2026-11-14\n"
    out = editor.commit({DIST: text}, "Editor: tag", "A. Person", base)
    assert out["ok"] and out["pushed"], out
    assert git(remote, "log", "--format=%s", "main").splitlines()[:2] == ["Editor: tag", "other"]


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
        assert get("/dataset/taxa.csv")[0] == 200
        assert get("/secret.txt")[0] == 404
        assert get("/editor/../secret.txt")[0] == 404
        status, body = get("/api/editor/info")
        assert status == 200 and b'"head"' in body
        status, _ = get("/api/editor/commit", "POST", {"Origin": "https://evil.example",
                                                       "Content-Type": "application/json"}, b"{}")
        assert status == 403
    finally:
        srv.shutdown()


def test_ui_loads_and_edits_from_files(browser, world):
    """The whole page from file://: load the CSV files, tag a taxon with the form, see the
    change listed, review a machine-read row, and get the files to commit."""
    pg = browser.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.add_init_script("localStorage.setItem('iog-editor-name', 'UI Tester');")
    pg.route("**/api.github.com/**", lambda r: r.abort())
    pg.route("**/raw.githubusercontent.com/**", lambda r: r.abort())
    pg.goto((config.ROOT / "editor" / "index.html").as_uri())
    pg.wait_for_selector("#start-load", timeout=10000)        # GitHub unreachable here
    pg.click("#start-load")
    pg.set_input_files(".filepick input", [str(p) for p in world.rglob("*.csv")])
    pg.wait_for_function("window.IOGApp.st && window.IOGApp.st.rows.length > 5")
    pg.fill("#q", "gigas")
    pg.wait_for_selector('#list .item[data-id="ORGIG"]')
    pg.click('#list .item[data-id="ORGIG"]')
    pg.select_option('form[data-form="tag"] select[name="place"]', "Saipan")
    pg.fill('form[data-form="tag"] input[name="source"]', "seen 2026")
    pg.click('form[data-form="tag"] button[type="submit"]')
    pg.wait_for_selector(".chip.st-present")
    assert "Saipan" in pg.inner_text(".chips")
    assert "machine-read" in pg.inner_text("#tab-taxon")
    pg.click('button[data-act="review"][data-table="literature"]')
    pg.wait_for_selector("text=checked")
    assert pg.inner_text("#n-changes") == "2"
    pg.click('.tabs button[data-tab="review"]')
    assert "A paper" in pg.inner_text("#tab-review") or "A. Author" in pg.inner_text("#tab-review")
    pg.click("#changes-btn")
    assert "Saipan present" in pg.inner_text("#tab-changes")
    pg.click('.tabs button[data-tab="table"]')
    pg.wait_for_selector('.g-body .r[data-id="ORGIG"]')
    files_out = pg.evaluate("IOGModel.files(IOGApp.st)")
    assert "ORGIG,Saipan,present,seen 2026,UI Tester" in files_out["dataset/distribution.csv"]
    assert ",editor,UI Tester," in files_out["dataset/literature.csv"]
    time.sleep(0.1)
    assert not errors, errors
    pg.close()


def test_local_server_refuses_a_foreign_host_and_cleans_the_author(clone):
    import http.client
    import threading
    from functools import partial
    from http.server import ThreadingHTTPServer

    work, remote = clone
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(editor.Handler, directory=str(work)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        c.request("GET", "/api/editor/info", headers={"Host": "evil.example"})
        assert c.getresponse().status == 403          # DNS rebinding: the page's own host
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        c.request("GET", "/api/editor/info")
        assert c.getresponse().status == 200
    finally:
        srv.shutdown()
    base = git(work, "rev-parse", "HEAD")
    text = ((work / DIST).read_text(encoding="utf-8") if (work / DIST).exists()
            else "﻿taxon_id,place,status,source,added_by,added\n") + "ORGIG,Guam,present,,A,2026-11-14\n"
    out = editor.commit({DIST: text}, "m", "Eve <evil@x.org>\nAuthor: x", base)
    assert out["ok"], out
    assert git(remote, "log", "-1", "--format=%an", "main") == "Eve evil@x.orgAuthor: x"


def test_confirm_a_whole_document(page, world, tmp_path):
    ds = dataset.load(world)
    ds["hosts"] = [{"taxon_id": "ORGIG", "host": "coconut palm", "doc_id": "d1", "pages": "4", "review": "machine"}]
    gigas = next(r for r in ds["taxa"] if r["id"] == "ORGIG")
    gigas.update(nativity="introduced", nativity_source="d1", nativity_review="machine")
    dataset.write(ds, world)
    texts = texts_of(world)
    out = run(page, texts, [{"type": "reviewDoc", "doc": "d1", "nativity": True},
                            {"type": "reviewDoc", "doc": "d1"}])
    assert out["errors"][0] is None and "nothing machine-made" in out["errors"][1]
    new = tmp_path / "after"
    new.mkdir()
    for rel, text in {**texts, **out["files"]}.items():
        if text is not None:
            (new / rel.removeprefix("dataset/")).parent.mkdir(parents=True, exist_ok=True)
            (new / rel.removeprefix("dataset/")).write_text(text, encoding="utf-8")
    after = dataset.load(new)
    assert dataset.check(after).items == []
    assert {r["review"] for r in after["literature"] + after["notes"] + after["hosts"]} == {"editor"}
    assert after["literature"][0]["reviewed_by"] == "T. Editor"
    assert next(r for r in after["taxa"] if r["id"] == "ORGIG")["nativity_review"] == "editor"
    # without the box ticked, a nativity value stays machine
    only = run(page, texts, [{"type": "reviewDoc", "doc": "d1"}])
    assert "dataset/taxa.csv" not in only["files"]          # no taxon row changed


def test_an_unplaced_name_can_be_merged_into_a_taxon(page, world, tmp_path):
    texts = texts_of(world)
    out = run(page, texts, [{"type": "placeSynonym", "unplacedName": "Zorotypus guineensis",
                             "into": "ORGIG", "authorship": "Silvestri, 1913"}])
    assert out["errors"] == [None] and out["checks"] == []
    new = tmp_path / "after"
    new.mkdir()
    for rel, text in {**texts, **out["files"]}.items():
        if text is not None:
            (new / rel.removeprefix("dataset/")).parent.mkdir(parents=True, exist_ok=True)
            (new / rel.removeprefix("dataset/")).write_text(text, encoding="utf-8")
    ds = dataset.load(new)
    assert dataset.check(ds).items == []
    syn = next(r for r in ds["taxa"] if r["name"] == "Zorotypus guineensis")
    assert syn["status"] == "synonym" and syn["accepted_id"] == "ORGIG" and syn["id"] == out["ops"][0]["newId"]
    assert ds["unplaced"] == []
    # a later literature scan finds the name and files it under the valid taxon
    from guaminsects.literature import finder
    assert finder.Lexicon(ds).names["Zorotypus guineensis"] == "ORGIG"
    # merging an accepted taxon carries every row that points at it
    merged = run(page, texts, [{"type": "synonymize", "id": "ORRHI", "into": "ORGIG"}])
    assert merged["errors"] == [None] and set(merged["files"]) == {"dataset/taxa.csv"}
