// The editor's page: find a taxon (search, worklists, the tree), work on it with tools,
// or edit any cell in the table; every change is listed until it is committed.
(function () {
  "use strict";
  const S = window.IOG_SPEC, M = window.IOGModel, IO = window.IOGIO;
  const $ = s => document.querySelector(s);
  const esc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fold = s => (s || "").toLowerCase();
  const LOW = new Set(["Genus", "Subgenus", "Species", "Subspecies", "Variety", "Form"]);
  const sci = (rank, name) => LOW.has(rank) ? `<i>${esc(name)}</i>` : esc(name);
  const store = {
    get(k, session) { try { return (session ? sessionStorage : localStorage).getItem(k); } catch (e) { return null; } },
    set(k, v, session) { try { (session ? sessionStorage : localStorage).setItem(k, v); } catch (e) { /* storage off */ } },
    del(k) { try { localStorage.removeItem(k); sessionStorage.removeItem(k); } catch (e) { /* storage off */ } },
  };
  const DRAFT = "iog-editor-draft";

  const app = {
    reviewDoc: null, base: null, loaded: null, ops: [], st: null, sel: null, tab: "taxon", queue: "browse", q: "",
    name: store.get("iog-editor-name") || "", search: new Map(),
    token: store.get("iog-editor-token") || store.get("iog-editor-token", true) || "",
    preset: store.get("iog-editor-preset") || "core", tableScope: "list", upl: -1,
  };

  // ------------------------------------------------------------ small helpers
  let toastTimer = null;
  function toast(msg, kind) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = kind || "";
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, kind === "error" ? 9000 : 3500);
  }
  const row = id => app.st && app.st.row(id);
  const isSyn = r => r && r.taxonomicStatus === "synonym";
  function label(id) {
    const r = row(id);
    return r ? sci(r.taxonRank, r.scientificName) : esc(id);
  }

  // ------------------------------------------------------------ state changes
  function recompute() {
    app.st = M.replay(app.base, app.ops);
    app.search = new Map();
    for (const r of app.st.rows) {
      app.search.set(r.taxonID, fold([r.scientificName, r.vernacularName, r.taxonID, r.scientificNameAuthorship].join(" ")));
    }
    saveDraft();
    render();
  }
  function addOp(type, fields, quiet) {
    if (!app.name) { askName(() => addOp(type, fields, quiet)); return null; }
    const op = M.op(type, fields, app.name);
    app.ops.push(op);
    recompute();
    if (op.error) {
      app.ops.pop();
      recompute();
      toast(op.error, "error");
      return null;
    }
    if (!quiet) toast(M.describe(op, app.st));
    return op;
  }
  function undo(i) {
    app.ops.splice(i, 1);
    recompute();
  }
  function saveDraft() {
    if (!app.base) return;
    if (!app.ops.length) { store.del(DRAFT); return; }
    store.set(DRAFT, JSON.stringify({ source: app.base.source, ops: app.ops, saved: new Date().toISOString() }));
  }
  function readDraft() {
    try { return JSON.parse(store.get(DRAFT) || "null"); } catch (e) { return null; }
  }

  // ------------------------------------------------------------ loading
  async function load(loader, keepOps) {
    $("#src").textContent = "loading…";
    let res;
    try { res = await loader(); }
    catch (e) {
      $("#src").textContent = app.base ? app.base.source.label : "nothing loaded";
      toast(e.message, "error");
      if (!app.base) renderStart(e.message);
      return false;
    }
    app.loaded = res;
    app.base = M.makeBase(res.texts, res.source);
    if (!keepOps) app.ops = [];
    recompute();
    if (!app.sel || !row(app.sel)) app.sel = (app.st.rows[0] || {}).taxonID || null;
    fromHash();
    render();
    if (res.info && res.info.dirty && res.info.dirty.length) {
      toast("Uncommitted changes in " + res.info.dirty.join(", ") + ": commit or discard them with git before committing here.", "error");
    }
    return true;
  }
  async function start() {
    renderStart();
    const draft = readDraft();
    const info = await IO.localInfo();
    const ok = await load(info ? IO.loadLocal : () => IO.loadGitHub({ token: app.token }));
    const restore = ok && draft && draft.ops && draft.ops.length ? () => offerDraft(draft) : null;
    if (!app.name) askName(restore); else if (restore) restore();
  }
  function offerDraft(draft) {
    openForm({
      title: "Restore unsaved changes?",
      intro: `${draft.ops.length} change${draft.ops.length === 1 ? "" : "s"} from ${new Date(draft.saved).toLocaleString()} ` +
        `(on ${esc(draft.source && draft.source.label)}) were not committed. Restore them onto what is loaded now?`,
      submit: "Restore", cancel: "Discard them",
      onCancel: () => store.del(DRAFT),
      onSubmit: () => {
        app.ops = draft.ops;
        recompute();
        const bad = app.ops.filter(o => o.error).length;
        if (bad) { setTab("changes"); toast(`${bad} change(s) no longer apply; see Changes`, "error"); }
        else toast(`Restored ${app.ops.length} changes`);
      },
    });
  }
  function chooseSource() {
    const kinds = [];
    openForm({
      title: "Load the taxonomy",
      intro: "Load from GitHub (the latest commit), from this clone (when opened through " +
        "<code>uv run guaminsects edit</code>), from a folder holding a clone (Chrome, Edge), or " +
        "from the CSV files themselves." + (app.ops.length ? ` Your ${app.ops.length} uncommitted changes are kept and replayed onto it.` : ""),
      fields: [
        { key: "repo", label: "GitHub repository", value: (app.base && app.base.source.repo) || S.repo },
        { key: "branch", label: "Branch", value: (app.base && app.base.source.branch) || S.branch },
      ],
      submit: "Load from GitHub",
      extra: (box, close) => {
        const b = document.createElement("div");
        b.className = "alt-loads";
        b.innerHTML = '<button type="button" data-k="local">This clone (local server)</button>' +
          (IO.canFolder() ? '<button type="button" data-k="folder">Open a folder…</button>' : "") +
          '<label class="filepick">Open files…<input type="file" accept=".csv,text/csv" multiple></label>';
        b.addEventListener("click", e => {
          const k = e.target.dataset && e.target.dataset.k;
          if (k === "local") { close(); load(IO.loadLocal, true); }
          if (k === "folder") { close(); load(IO.pickFolder, true); }
        });
        b.querySelector("input[type=file]").addEventListener("change", e => {
          const files = e.target.files;
          if (files.length) { close(); load(() => IO.loadFiles(files), true); }
        });
        box.appendChild(b);
        kinds.push(b);
      },
      onSubmit: v => { load(() => IO.loadGitHub({ repo: v.repo.trim(), branch: v.branch.trim(), token: app.token }), true); },
    });
  }

  // ------------------------------------------------------------ the name
  function askName(then) {
    openForm({
      title: "Who is editing?",
      intro: "Your name is recorded as <b>added by</b> on every change you make, and credited in the commit. " +
        "Everything added here is public.",
      fields: [{ key: "name", label: "Your name", value: app.name, required: true, placeholder: "e.g. M. Andrew Johnston" }],
      submit: "Save",
      onSubmit: v => {
        app.name = v.name.trim();
        store.set("iog-editor-name", app.name);
        renderHeader();
        if (then) setTimeout(then, 0);
      },
    });
  }

  // ------------------------------------------------------------ worklists
  const num = v => +(v || 0);
  const QUEUES = [
    ["browse", "Browse the tree", null],
    ["all", "All accepted taxa", r => !isSyn(r)],
    ["changed", "Changed, not committed", (r, st) => st.changed.has(r.taxonID)],
    ["annotated", "With editors' tags or links", r => r.distributionTags || r.associatedOccurrences || r.associatedReferences],
    ["notcol", "Not in the Catalogue of Life", r => !isSyn(r) && r.inCatalogueOfLife === "no" && r.nameAccordingTo !== "Insects of Guam curator"],
    ["spelling", "Merged by spelling", r => isSyn(r) && r.nameMatch === "spelling variant"],
    ["merged", "All merged names (synonyms)", r => isSyn(r)],
    ["machine", "Literature machine-read only", r => r.verificationRemarks === "literature records machine-read only"],
    ["new", "New from a tool (to review)", r => r.flag === "new"],
    ["litmachine", "Literature: machine-read rows to check", r => !isSyn(r) && r.machineLit > 0],
    ["notesmachine", "Notes: machine-written, to check", r => !isSyn(r) && r.machineNotes > 0],
    ["natunknown", "Species: nativity unknown", r => r.taxonRank === "Species" && !isSyn(r) && r.nativity === "unknown"],
    ["natmachine", "Nativity set by a tool (to confirm)", r => !isSyn(r) && r.nativity !== "unknown" && r.nativity_review === "machine"],
    ["natconflict", "Nativity in conflict", r => r.nativityConflict],
    ["unplaced", "Unplaced names (records, no taxon)", null],
    ["unconfirmed", "Species: observations only", r => r.taxonRank === "Species" && !isSyn(r) && r.verificationStatus === "unconfirmed"],
    ["thin", "Species on ≤ 2 GBIF records, nothing else", r => r.taxonRank === "Species" && !isSyn(r) && num(r.gbifRecords) <= 2 && !num(r.literatureRecords) && !num(r.inatObservations)],
    ["lonely", "Families with nothing under them", (r, st) => r.taxonRank === "Family" && !isSyn(r) && !st.children(r.taxonID).length],
    ["curated", "Added by hand (IOG-)", r => /^IOG-/.test(r.taxonID)],
    ["confirmed", "Editor confirmed", r => r.verificationStatus === M.CONFIRMED],
    ["introduced", "Nativity: introduced", r => !isSyn(r) && r.nativity === "introduced"],
    ["native", "Nativity: native", r => !isSyn(r) && r.nativity === "native"],
    ["hidden", "Hidden", r => r.hidden === "1" && !isSyn(r)],
  ];
  function matches() {
    const st = app.st;
    if (!st) return [];
    const terms = fold(app.q).split(/\s+/).filter(Boolean);
    const q = QUEUES.find(x => x[0] === app.queue);
    let rows = st.rows;
    if (q && q[2]) rows = rows.filter(r => q[2](r, st));
    if (terms.length) {
      rows = rows.filter(r => { const t = app.search.get(r.taxonID) || ""; return terms.every(x => t.includes(x)); });
      const first = terms.join(" ");
      rows = rows.slice().sort((a, b) =>
        (fold(b.scientificName).startsWith(first) - fold(a.scientificName).startsWith(first)) ||
        (isSyn(a) - isSyn(b)) || a.scientificName.length - b.scientificName.length);
    }
    return rows;
  }

  // ------------------------------------------------------------ rendering
  function render() {
    renderHeader();
    renderList();
    if (app.tab === "taxon") renderTaxon();
    if (app.tab === "table") renderTable();
    if (app.tab === "review") renderReview();
    if (app.tab === "changes") renderChanges();
  }
  function renderHeader() {
    $("#src").textContent = app.base ? app.base.source.label : "nothing loaded";
    $("#me-btn").textContent = app.name ? "Editing as " + app.name : "Your name…";
    const good = app.ops.filter(o => !o.error).length;
    $("#n-changes").textContent = app.ops.length;
    $("#n-changes").className = "count" + (app.ops.some(o => o.error) ? " bad" : "");
    $("#commit-btn").disabled = !good;
  }
  function item(r) {
    const st = app.st;
    const ch = st.changed.has(r.taxonID);
    const meta = isSyn(r) ? "= " + esc(st.name(r.acceptedNameUsageID)) : esc(r.taxonRank) + (r.family && r.taxonRank !== "Family" ? " · " + esc(r.family) : "");
    return `<div class="item${r.taxonID === app.sel ? " sel" : ""}${ch ? " chg" : ""}${r.hidden === "1" ? " hid" : ""}" data-id="${esc(r.taxonID)}" role="option">` +
      `<span class="nm">${sci(r.taxonRank, r.scientificName)}</span>` +
      (r.vernacularName ? ` <span class="cn">${esc(r.vernacularName)}</span>` : "") +
      `<span class="meta">${meta}</span></div>`;
  }
  function renderList() {
    const el = $("#list");
    if (!app.st) { el.innerHTML = ""; return; }
    const st = app.st;
    if (app.queue === "unplaced") {
      const rows = unplacedRows();
      el.innerHTML = `<p class="muted pad">${rows.length.toLocaleString()} names</p>` + rows.slice(0, 400).map((u, i) =>
        `<div class="item${i === app.upl ? " sel" : ""}" data-upl="${i}" role="option"><span class="nm">${esc(u.name)}</span>` +
        `<span class="meta">${esc(u.source)}${u.records ? " · " + esc(u.records) : ""}</span></div>`).join("");
      return;
    }
    if (app.queue === "browse" && !app.q.trim()) {
      const cur = row(app.sel) && !isSyn(row(app.sel)) ? app.sel : (row(app.sel) ? row(app.sel).acceptedNameUsageID : null);
      const root = st.rows.find(r => !isSyn(r) && !r.parentNameUsageID);
      const here = cur && row(cur) ? cur : root && root.taxonID;
      if (!here) { el.innerHTML = '<p class="muted pad">Empty taxonomy.</p>'; return; }
      const up = st.lineage(here).map(id => `<a href="#/t/${esc(id)}" class="crumb" data-id="${esc(id)}">${label(id)}</a>`).join(" › ");
      const kids = st.children(here).map(row);
      el.innerHTML = (up ? `<div class="crumbs pad">${up}</div>` : "") + item(row(here)) +
        `<div class="kids">${kids.map(item).join("") || '<p class="muted pad">Nothing under it.</p>'}</div>`;
      return;
    }
    const rows = matches(), max = 400;
    el.innerHTML = `<p class="muted pad">${rows.length.toLocaleString()} taxa</p>` + rows.slice(0, max).map(item).join("") +
      (rows.length > max ? `<p class="muted pad">… ${(rows.length - max).toLocaleString()} more: narrow the search.</p>` : "");
  }

  function select(id, tab) {
    if (!row(id)) return;
    app.sel = id;
    try { history.replaceState(null, "", "#/t/" + id); } catch (e) { /* file:// in some browsers */ }
    if (tab) setTab(tab); else render();
  }
  function fromHash() {
    const m = /^#\/t\/(.+)$/.exec(location.hash);
    if (m && row(decodeURIComponent(m[1]))) app.sel = decodeURIComponent(m[1]);
  }
  function setTab(t) {
    app.tab = t;
    for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === t));
    for (const k of ["taxon", "table", "review", "changes"]) $("#tab-" + k).hidden = k !== t;
    render();
  }

  function renderStart(err) {
    $("#tab-taxon").innerHTML = '<div class="start"><h1>Taxonomy editor</h1>' +
      "<p>Loading the latest taxonomy from GitHub…</p>" +
      (err ? `<p class="err">${esc(err)}</p><p><button type="button" class="primary" id="start-load">Load from somewhere else…</button></p>` : "") +
      "</div>";
    const b = $("#start-load");
    if (b) b.addEventListener("click", chooseSource);
  }

  // ---- the taxon panel
  function facts(r) {
    const f = [
      ["Common name", esc(r.vernacularName)],
      ["Nativity", esc(r.nativity) + (r.nativity !== "unknown" ? ` <span class="muted">${esc(r.nativity_review === "machine" ? "set by a tool, not yet confirmed" : "confirmed")}${r.nativity_source ? ", source: " + esc(r.nativity_source) : ""}</span>` : "") +
        (r.nativityConflict ? ' <span class="badge warn">statements disagree</span>' : "")],
      ["Recorded in", esc(r.recordedIn)], ["Islands", esc(r.islands)],
      ["Verification", esc(r.verificationStatus) + (r.verificationRemarks ? ` <span class="muted">(${esc(r.verificationRemarks)})</span>` : "") +
        (r.verifiedBy ? ` <span class="muted">by ${esc(r.verifiedBy)} ${esc(r.verifiedDate)}</span>` : "")],
      ["Records", `GBIF ${esc(r.gbifRecords || 0)} · specimens ${esc(r.specimenRecords || 0)} · iNat ${esc(r.inatObservations || 0)} · literature ${esc(r.literatureRecords || 0)}`],
      ["Classification", ["order", "superfamily", "family", "subfamily", "tribe"].filter(k => r[k]).map(k => esc(r[k])).join(" › ")],
      ["Name source", esc(r.nameAccordingTo) + (r.matchRemarks ? ` <span class="muted">${esc(r.matchRemarks)}</span>` : "")],
      ["Note on the page", esc(r.taxonRemarks)],
      ["Last edited", r.modifiedBy ? `${esc(r.modifiedBy)}, ${esc(r.modified)}` : ""],
      ["Flag", r.flag ? '<span class="badge new">new: added by a tool, not yet reviewed</span>' : ""],
    ].filter(x => x[1]);
    return '<dl class="facts">' + f.map(x => `<dt>${x[0]}</dt><dd>${x[1]}</dd>`).join("") + "</dl>";
  }
  function placeOptions(selected) {
    let html = "", area = null;
    for (const [name, a, group] of S.places) {
      if (a !== area) {
        if (area) html += "</optgroup>";
        html += `<optgroup label="${esc(S.areas.find(x => x.code === a).name)}">`;
        area = a;
      }
      html += `<option value="${esc(name)}"${name === selected ? " selected" : ""}>${group ? esc(name) + " (all)" : esc(name)}</option>`;
    }
    return html + "</optgroup>";
  }
  function renderTaxon() {
    const el = $("#tab-taxon");
    if (!app.st) return;
    if (app.queue === "unplaced") return renderUnplaced();
    const st = app.st, r = row(app.sel);
    if (!r) { el.innerHTML = '<p class="muted">Pick a taxon on the left.</p>'; return; }
    const id = r.taxonID;
    const badges = [];
    if (st.added.has(id)) badges.push('<span class="badge new">added here</span>');
    else if (st.changed.has(id)) badges.push('<span class="badge chg">changed</span>');
    if (r.inCatalogueOfLife === "no" && !isSyn(r)) badges.push('<span class="badge warn">not in the Catalogue of Life</span>');
    if (r.hidden === "1") badges.push('<span class="badge muted">hidden</span>');
    if (r.verificationStatus === M.CONFIRMED) badges.push('<span class="badge ok">confirmed</span>');
    if (r.taxonomicStatus === "morphospecies" || r.taxonomicStatus === "doubtful") badges.push(`<span class="badge muted">${esc(r.taxonomicStatus)}</span>`);
    const crumbs = st.lineage(isSyn(r) ? r.acceptedNameUsageID : id);
    const siteLink = `${S.site}#/t/${encodeURIComponent(isSyn(r) ? r.acceptedNameUsageID : id)}`;
    let html = '<div class="t-head">' +
      (crumbs.length ? `<div class="crumbs">${crumbs.map(x => `<a href="#/t/${esc(x)}" data-id="${esc(x)}">${label(x)}</a>`).join(" › ")}</div>` : "") +
      `<h1>${sci(r.taxonRank, r.scientificName)} <span class="auth">${esc(r.scientificNameAuthorship)}</span></h1>` +
      `<div class="t-sub">${esc(r.taxonRank)} · ${esc(r.taxonomicStatus)} · <code>${esc(id)}</code> ${badges.join(" ")}</div>` +
      `<div class="t-links"><a href="${esc(siteLink)}" target="_blank" rel="noopener">On the site ↗</a>` +
      (r.references ? ` · <a href="${esc(r.references)}" target="_blank" rel="noopener">${r.references.includes("catalogueoflife") ? "Catalogue of Life" : "GBIF"} ↗</a>` : "") + "</div></div>";

    if (isSyn(r)) {
      html += `<div class="notice">A name shown as <a href="#/t/${esc(r.acceptedNameUsageID)}" data-id="${esc(r.acceptedNameUsageID)}">${label(r.acceptedNameUsageID)}</a>` +
        ` (${esc(r.nameMatch)}${r.matchRemarks ? ": " + esc(r.matchRemarks) : ""}).` +
        (r.nameSources ? ` Used by ${esc(r.nameSources)}.` : "") + "</div>" +
        '<div class="toolbar"><button type="button" data-act="split">Split out as its own taxon…</button>' +
        (/^IOG-/.test(id) ? '<button type="button" data-act="remove" class="danger">Delete this name</button>' : "") + "</div>";
      el.innerHTML = html;
      return;
    }
    const isIog = /^IOG-/.test(id);
    html += '<div class="toolbar">' +
      '<button type="button" data-act="edit">Edit fields…</button>' +
      '<button type="button" data-act="synonymize">Synonymize into…</button>' +
      '<button type="button" data-act="move">Move…</button>' +
      '<button type="button" data-act="add">Add a taxon under it…</button>' +
      '<button type="button" data-act="addName">Add a name…</button>' +
      '<button type="button" data-act="nativity">Nativity…</button>' +
      (r.nativity !== "unknown" && r.nativity_review === "machine" ? '<button type="button" data-act="confirmNativity">Confirm nativity</button>' : "") +
      (r.flag === "new" ? '<button type="button" data-act="clearFlag">Mark reviewed</button>' : "") +
      (r.verificationStatus === M.CONFIRMED ? '<button type="button" data-act="unverify">Remove confirmation</button>'
        : '<button type="button" data-act="verify">Confirm…</button>') +
      (r.hidden === "1" ? '<button type="button" data-act="unhide">Show again</button>'
        : '<button type="button" data-act="hide" class="danger">Hide (delete)…</button>') +
      (isIog ? '<button type="button" data-act="remove" class="danger">Delete for good</button>' : "") +
      "</div>";
    html += facts(r);

    // distribution
    const tags = st.annFor(id, "distribution");
    html += '<section class="sec"><h2>Distribution tags</h2>' +
      (tags.length ? '<ul class="chips">' + tags.map(a =>
        `<li class="chip st-${esc(a.status)}"><b>${esc(a.value)}</b> ${esc(a.status)}` +
        (a.source ? ` <span class="src">${M.isUrl(a.source) ? `<a href="${esc(a.source)}" target="_blank" rel="noopener">source</a>` : esc(a.source)}</span>` : "") +
        ` <span class="by">${esc(a.added_by)} ${esc(a.added)}</span>` +
        `<button type="button" class="x" data-act="untag" data-v="${esc(a.value)}" aria-label="Remove ${esc(a.value)}">×</button></li>`).join("") + "</ul>"
        : '<p class="muted">None yet. Records from GBIF, iNaturalist and the literature: ' + (esc(r.recordedIn) || "none") + ".</p>") +
      '<form class="inline" data-form="tag"><select name="place" aria-label="Place">' + placeOptions("Guam") + "</select>" +
      '<select name="status" aria-label="Status">' + S.distributionStatus.map(s => `<option>${s}</option>`).join("") + "</select>" +
      '<input name="source" placeholder="Source: citation or URL (optional)" aria-label="Source">' +
      '<button type="submit">Add tag</button></form></section>';

    // vouchers
    const occ = st.occFor(id);
    html += '<section class="sec"><h2>Vouchers <span class="muted">iNaturalist observations, GBIF records</span></h2>' +
      (occ.length ? '<ul class="plain">' + occ.map(e => {
        const url = M.occurrenceUrl(e);
        return `<li><a href="${esc(url)}" target="_blank" rel="noopener">${e.kind === "inat_observation" ? "iNaturalist" : "GBIF"} ${esc(e.ref)}</a>` +
          (e.note ? ` <span class="muted">${esc(e.note)}</span>` : "") + ` <span class="by">${esc(e.editor)} ${esc(e.edited)}</span>` +
          `<button type="button" class="x" data-act="unvoucher" data-v="${esc(url)}" aria-label="Remove">×</button></li>`;
      }).join("") + "</ul>" : '<p class="muted">None yet. An unidentified iNaturalist observation can be a photo voucher.</p>') +
      '<form class="inline" data-form="voucher"><input name="url" required placeholder="https://www.inaturalist.org/observations/…  or  https://www.gbif.org/occurrence/…" aria-label="Record URL">' +
      '<input name="note" placeholder="Note (e.g. unidentified on iNat; photo shows the pronotum)" aria-label="Note">' +
      '<button type="submit">Add voucher</button></form></section>';

    // links
    const links = st.annFor(id, "link");
    html += '<section class="sec"><h2>Links</h2>' +
      (links.length ? '<ul class="plain">' + links.map(a =>
        `<li><a href="${esc(a.value)}" target="_blank" rel="noopener">${esc(a.note || a.value)}</a> <span class="by">${esc(a.added_by)} ${esc(a.added)}</span>` +
        `<button type="button" class="x" data-act="unlink" data-v="${esc(a.value)}" aria-label="Remove">×</button></li>`).join("") + "</ul>"
        : '<p class="muted">None yet.</p>') +
      '<form class="inline" data-form="link"><input name="url" required placeholder="https://…" aria-label="URL">' +
      '<input name="label" placeholder="Label (e.g. BOLD, a paper, a fact sheet)" aria-label="Label">' +
      '<button type="submit">Add link</button></form></section>';

    // names
    const syn = st.synonymsOf(id);
    if (syn.length) {
      html += `<section class="sec"><h2>Names merged here (${syn.length})</h2><ul class="plain">` + syn.map(s => {
        const n = row(s);
        return `<li><a href="#/t/${esc(s)}" data-id="${esc(s)}">${sci(n.taxonRank, n.scientificName)}</a> ${esc(n.scientificNameAuthorship)} ` +
          `<span class="muted">${esc(n.nameMatch)}${n.matchRemarks ? ": " + esc(n.matchRemarks) : ""}</span></li>`;
      }).join("") + "</ul></section>";
    }
    // under it
    const kids = st.children(id);
    if (kids.length) {
      html += `<section class="sec"><h2>Under it (${kids.length})</h2><ul class="cols">` + kids.map(k =>
        `<li><a href="#/t/${esc(k)}" data-id="${esc(k)}">${label(k)}</a></li>`).join("") + "</ul></section>";
    }
    html += reviewSections(id);
    el.innerHTML = html;
  }

  // What the literature tool wrote for this taxon, each row to confirm or reject.
  function reviewButtons(table, attrs) {
    const a = Object.entries(attrs).map(([k, v]) => `data-${k}="${esc(v)}"`).join(" ");
    return ` <button type="button" data-act="review" data-table="${table}" ${a}>Confirm</button>` +
      ` <button type="button" class="x" data-act="reject" data-table="${table}" ${a} aria-label="Reject">×</button>`;
  }
  const doc = d => (app.st.lookup.documents.get(d) || {});
  function reviewSections(id) {
    const st = app.st;
    let html = "";
    const lit = st.mine("literature", id);
    if (lit.length) {
      html += '<section class="sec"><h2>Literature</h2><ul class="plain small">' + lit.map(l => {
        const machine = l.review === "machine";
        return `<li>${esc(doc(l.doc_id).citation || l.doc_id)} <span class="muted">${esc(l.kind)}` +
          (l.pages ? ", p. " + esc(l.pages.replace(/ \| /g, ", ")) : "") + (l.areas ? " · " + esc(l.areas) : "") +
          (l.status ? " · " + esc(l.status) + (l.status_area ? " in " + esc(l.status_area) : "") : "") +
          (l.first_record_year ? " · first record " + esc(l.first_record_year) : "") + "</span> " +
          (machine ? '<span class="badge warn">machine-read</span>' + reviewButtons("literature", { doc: l.doc_id, kind: l.kind })
            : `<span class="badge ok">checked${l.reviewed_by ? " by " + esc(l.reviewed_by) : ""}</span>`) + "</li>";
      }).join("") + "</ul></section>";
    }
    const notes = st.mine("notes", id);
    if (notes.length) {
      html += '<section class="sec"><h2>Notes <span class="muted">paraphrased, shown on the site</span></h2><ul class="plain small">' + notes.map(n =>
        `<li>${esc(n.note)} <span class="muted">${esc(n.topic)} · ${esc(doc(n.doc_id).citation || n.doc_id)}${n.pages ? ", p. " + esc(n.pages) : ""} · ${esc(n.written_by)}</span> ` +
        (n.review === "machine" ? '<span class="badge warn">machine-written</span>' + reviewButtons("notes", { doc: n.doc_id, topic: n.topic })
          : '<span class="badge ok">checked</span>') + "</li>").join("") + "</ul></section>";
    }
    const hosts = st.mine("hosts", id);
    if (hosts.length) {
      html += '<section class="sec"><h2>Host plants</h2><ul class="plain small">' + hosts.map(h =>
        `<li>${esc(h.host)} <span class="muted">${esc(doc(h.doc_id).citation || h.doc_id || "")}</span>` +
        (h.review === "machine" ? ' <span class="badge warn">machine-read</span>' + reviewButtons("hosts", { doc: h.doc_id, host: h.host }) : "") + "</li>").join("") + "</ul></section>";
    }
    return html;
  }
  const unplacedRows = () => (app.st ? app.st.t.unplaced : []).slice().sort((a, b) => (+b.records || 0) - (+a.records || 0) || (a.name < b.name ? -1 : 1));
  function renderUnplaced() {
    const u = unplacedRows()[app.upl];
    $("#tab-taxon").innerHTML = !u ? '<p class="muted">Pick a name on the left: these have records that no tool could place in the tree.</p>' :
      `<div class="t-head"><h1>${esc(u.name)}</h1><div class="t-sub">${esc(u.rank || "rank unknown")} · from ${esc(u.source)} · ${esc(u.records || 0)} records</div></div>` +
      (u.note ? `<div class="notice">${esc(u.note)}</div>` : "") +
      `<div class="toolbar"><button type="button" data-act="place" data-i="${app.upl}">Place under a parent…</button>` +
      `<button type="button" data-act="placeSynonym" data-i="${app.upl}">Merge into an existing taxon…</button></div>`;
  }

  // ---- tools (buttons and inline forms on the taxon panel)
  function onTaxonClick(e) {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const st = app.st, id = app.sel, r = row(id), act = b.dataset.act, v = b.dataset.v;
    if (!app.name) return askName();
    if (act === "untag") return addOp("untag", { id, place: v });
    if (act === "unvoucher") return addOp("unvoucher", { id, url: v });
    if (act === "unlink") return addOp("unlink", { id, url: v });
    if (act === "unhide") return addOp("unhide", { id });
    if (act === "confirmNativity") return addOp("confirmNativity", { id });
    if (act === "clearFlag") return addOp("clearFlag", { id });
    if (act === "review" || act === "reject") {
      const d = b.dataset;
      return addOp(act, { id, table: d.table, doc: d.doc || "", kind: d.kind || "", topic: d.topic || "", host: d.host || "" });
    }
    if (act === "nativity") {
      return openForm({ title: "Nativity of " + r.scientificName,
        intro: "Native or introduced to Micronesia as a whole (statements for single island groups stay with the literature rows). Unknown clears it.",
        fields: [{ key: "value", label: "Nativity", type: "select", options: S.nativity, value: r.nativity },
                 { key: "source", label: "Source (a document, or leave blank for “editor”)", value: r.nativity_source !== "editor" ? r.nativity_source : "" }],
        submit: "Save", onSubmit: x => addOp("nativity", { id, value: x.value, source: x.source }) });
    }
    if (act === "placeSynonym") {
      const u = unplacedRows()[+b.dataset.i];
      return openForm({ title: "Merge " + u.name + " into a taxon",
        intro: "It becomes another name of the taxon you pick: searchable, listed on its page, and its records here and in later syncs and ingests count for that taxon.",
        fields: [{ key: "into", label: "The valid taxon it is the same as", type: "taxon", required: true, filter: x => !isSyn(x) },
                 { key: "authorship", label: "Authorship" },
                 { key: "reason", label: "Reason or source" }],
        submit: "Merge", onSubmit: x => { const op = addOp("placeSynonym", { unplacedName: u.name, into: x.into, authorship: x.authorship, reason: x.reason }); if (op) select(op.into); } });
    }
    if (act === "place") {
      const u = unplacedRows()[+b.dataset.i];
      return openForm({ title: "Place " + u.name,
        intro: "Put this name under a parent as a new taxon (IOG- id), taking it off the list.",
        fields: [{ key: "rank", label: "Rank", type: "select", options: S.ranks, value: (u.rank || "Species").replace(/^./, c => c.toUpperCase()) },
                 { key: "name", label: "Scientific name", value: u.name, required: true },
                 { key: "parent", label: "Under", type: "taxon", required: true, filter: x => !isSyn(x) },
                 { key: "note", label: "Note shown on the page", type: "textarea" }],
        submit: "Place", onSubmit: x => { const op = addOp("place", { unplacedName: u.name, key: u.key, name: x.name, rank: x.rank, parent: x.parent, note: x.note }); if (op) select(op.newId); } });
    }
    if (act === "unverify") return addOp("verify", { id, on: false });
    if (act === "edit") return editFields(r);
    if (act === "verify") {
      return openForm({ title: "Confirm " + r.scientificName, intro: "You confirm that this taxon occurs in Micronesia (verificationStatus: editor confirmed).",
        fields: [{ key: "source", label: "Source for the confirmation (citation, specimen, observation URL)" }],
        submit: "Confirm", onSubmit: x => addOp("verify", { id, on: true, source: x.source }) });
    }
    if (act === "synonymize") {
      return openForm({
        title: "Synonymize " + r.scientificName,
        intro: `${sci(r.taxonRank, r.scientificName)} becomes a name of the taxon you pick, and is shown as it. ` +
          `Its records, ${st.synonymsOf(id).length} other name(s) and ${st.children(id).length} taxa under it go with it. Undo: Split out.`,
        fields: [{ key: "into", label: `The accepted ${r.taxonRank.toLowerCase()} it is the same as`, type: "taxon", required: true,
                   filter: x => !isSyn(x) && x.taxonRank === r.taxonRank && x.taxonID !== id },
                 { key: "reason", label: "Reason or source" }],
        submit: "Synonymize", onSubmit: x => addOp("synonymize", { id, into: x.into, reason: x.reason }),
      });
    }
    if (act === "move") {
      return openForm({ title: "Move " + r.scientificName, intro: "Put it, and everything under it, under another taxon.",
        fields: [{ key: "parent", label: "New parent", type: "taxon", required: true,
                   filter: x => !isSyn(x) && M.rankIndex(x.taxonRank) < M.rankIndex(r.taxonRank) && !app.st.isUnder(x.taxonID, id) },
                 { key: "reason", label: "Reason or source" }],
        submit: "Move", onSubmit: x => addOp("move", { id, parent: x.parent, reason: x.reason }) });
    }
    if (act === "add") {
      const below = S.ranks.filter(k => M.rankIndex(k) > M.rankIndex(r.taxonRank));
      const def = { Order: "Family", Family: "Genus", Genus: "Species", Species: "Subspecies" }[r.taxonRank] || below[0];
      return openForm({ title: "Add a taxon under " + r.scientificName,
        intro: "A taxon no source has: a morphospecies (e.g. <i>Oryctes</i> sp. GU-1), a genus, a species. It gets an IOG- id.",
        fields: [{ key: "rank", label: "Rank", type: "select", options: below, value: def },
                 { key: "name", label: "Scientific name", required: true, placeholder: r.taxonRank === "Genus" ? r.scientificName + " sp. GU-1" : "" },
                 { key: "authorship", label: "Authorship", placeholder: "Linnaeus, 1758" },
                 { key: "status", label: "Status", type: "select", options: ["accepted", "morphospecies", "doubtful"],
                   value: r.taxonRank === "Genus" ? "morphospecies" : "accepted" },
                 { key: "common", label: "Common name (English)" },
                 { key: "note", label: "Note shown on the page", type: "textarea" },
                 { key: "reason", label: "Reason or source" }],
        submit: "Add", onSubmit: x => { const op = addOp("add", Object.assign({ parent: id }, x)); if (op) select(op.newId); } });
    }
    if (act === "addName") {
      return openForm({ title: "Add a name for " + r.scientificName,
        intro: "Another name for the same taxon (an old combination, a misspelling in the literature): searchable, and listed on its page.",
        fields: [{ key: "name", label: "Name", required: true }, { key: "authorship", label: "Authorship" },
                 { key: "reason", label: "Reason or source" }],
        submit: "Add name", onSubmit: x => addOp("addName", Object.assign({ into: id }, x)) });
    }
    if (act === "hide") {
      const n = st.descendants(id).length;
      return openForm({ title: "Hide " + r.scientificName,
        intro: `Hides it${n ? ` and the ${n} taxa under it` : ""} from the site. Nothing is deleted: <b>Show again</b> undoes it.`,
        fields: [{ key: "reason", label: "Why (e.g. a mislabelled specimen, not in Micronesia)", required: true }],
        submit: "Hide", danger: true, onSubmit: x => addOp("hide", { id, reason: x.reason }) });
    }
    if (act === "remove") {
      return openForm({ title: "Delete " + r.scientificName, intro: "Deletes this hand-added entry and its tags and vouchers for good.",
        submit: "Delete", danger: true, onSubmit: () => { const acc = r.acceptedNameUsageID || r.parentNameUsageID; if (addOp("remove", { id })) select(acc); } });
    }
    if (act === "split") {
      const acc = row(r.acceptedNameUsageID);
      return openForm({ title: "Split out " + r.scientificName,
        intro: `Make it its own taxon again instead of a name of ${acc ? sci(acc.taxonRank, acc.scientificName) : "its taxon"}.`,
        fields: [{ key: "parent", label: "Under", type: "taxon", value: acc && acc.parentNameUsageID,
                   filter: x => !isSyn(x) && M.rankIndex(x.taxonRank) < M.rankIndex(r.taxonRank) },
                 { key: "reason", label: "Reason or source" }],
        submit: "Split out", onSubmit: x => addOp("split", { id, parent: x.parent, reason: x.reason }) });
    }
  }
  function onTaxonSubmit(e) {
    const f = e.target.closest("form[data-form]");
    if (!f) return;
    e.preventDefault();
    if (!app.name) return askName();
    const v = Object.fromEntries(new FormData(f));
    const kind = f.dataset.form, id = app.sel;
    let op = null;
    if (kind === "tag") op = addOp("tag", { id, place: v.place, status: v.status, source: v.source });
    if (kind === "voucher") op = addOp("voucher", { id, url: v.url, note: v.note });
    if (kind === "link") op = addOp("link", { id, url: v.url, label: v.label });
    if (op) { const again = $(`#tab-taxon form[data-form="${kind}"] input`); if (again) again.focus(); }
  }
  function editFields(r) {
    const fields = [
      ["scientificName", "Scientific name"], ["scientificNameAuthorship", "Authorship"],
      ["taxonRank", "Rank", S.ranks], ["taxonomicStatus", "Status", ["accepted", "doubtful", "morphospecies"]],
      ["vernacularName", "Common name (English)"], ["other_common_names", "Other English names (separated by |)"],
      ["taxonRemarks", "Note shown on the page", "textarea"],
    ];
    openForm({ title: "Edit " + r.scientificName,
      intro: "Every field is in the table too. Nativity has its own tool.",
      fields: fields.map(([k, lab, t]) => ({ key: k, label: lab, value: r[k], type: Array.isArray(t) ? "select" : t || "text", options: Array.isArray(t) ? t : null }))
        .concat([{ key: "reason", label: "Reason or source" }]),
      submit: "Save",
      onSubmit: v => {
        for (const [k] of fields) {
          if ((v[k] || "") === (r[k] || "")) continue;
          if (!addOp("set", { id: r.taxonID, column: k, value: v[k], reason: v.reason }, true)) return false;
        }
        toast("Saved");
      } });
  }

  // ---- the table
  const PRESETS = {
    core: ["taxonID", "scientificName", "scientificNameAuthorship", "taxonRank", "taxonomicStatus", "parentNameUsage", "vernacularName", "family", "nativity", "recordedIn", "verificationStatus", "hidden"],
    nativity: ["taxonID", "scientificName", "taxonRank", "family", "nativity", "nativity_source", "nativity_review", "flag", "recordedIn", "literatureRecords"],
    distribution: ["taxonID", "scientificName", "taxonRank", "family", "recordedIn", "islands", "distributionTags", "associatedOccurrences", "gbifRecords", "inatObservations", "literatureRecords", "specimenRecords"],
    links: ["taxonID", "scientificName", "associatedOccurrences", "associatedReferences", "references", "taxonRemarks", "modifiedBy", "modified"],
    names: ["taxonID", "scientificName", "scientificNameAuthorship", "taxonomicStatus", "acceptedNameUsageID", "acceptedNameUsage", "nameMatch", "matchRemarks", "nameSources", "inCatalogueOfLife"],
    all: S.tables.taxa.columns,
  };
  const WIDE = { scientificName: 230, parentNameUsage: 170, acceptedNameUsage: 170, distributionTags: 260, associatedOccurrences: 280,
                 associatedReferences: 260, literatureSources: 320, matchRemarks: 240, taxonRemarks: 240, references: 240, nameSources: 160,
                 scientificNameAuthorship: 160, vernacularName: 160, verificationStatus: 140, verificationRemarks: 200, islands: 180 };
  const RH = 28;
  let tableRows = [], tableCols = [];
  function renderTable() {
    const el = $("#tab-table");
    if (!app.st) return;
    tableCols = PRESETS[app.preset] || PRESETS.core;
    tableRows = app.tableScope === "all" || (app.queue === "browse" && !app.q.trim()) ? app.st.rows : matches();
    const width = tableCols.reduce((s, c) => s + (WIDE[c] || 110), 0);
    if (!el.querySelector(".grid")) {
      el.innerHTML = '<div class="tbl-bar"><label>Columns <select id="preset">' +
        Object.keys(PRESETS).map(k => `<option value="${k}">${k}</option>`).join("") + "</select></label>" +
        '<label>Rows <select id="scope"><option value="list">the list on the left</option><option value="all">all</option></select></label>' +
        '<span id="tbl-n" class="muted"></span><span class="muted hint">Double-click a white cell to edit (Enter saves, Esc cancels); grey cells are computed.</span></div>' +
        '<div class="grid" tabindex="0"><div class="g-head"></div><div class="g-body"></div></div>';
      $("#preset").addEventListener("change", e => { app.preset = e.target.value; store.set("iog-editor-preset", app.preset); renderTable(); });
      $("#scope").addEventListener("change", e => { app.tableScope = e.target.value; renderTable(); });
      el.querySelector(".grid").addEventListener("scroll", paintRows);
      el.querySelector(".g-body").addEventListener("dblclick", startEdit);
      el.querySelector(".g-body").addEventListener("click", e => {
        const c = e.target.closest(".c");
        if (c && c.dataset.col === "taxonID") select(c.parentNode.dataset.id, "taxon");
        else if (c) { app.sel = c.parentNode.dataset.id; renderList(); paintRows(); }
      });
    }
    $("#preset").value = app.preset;
    $("#scope").value = app.tableScope;
    $("#tbl-n").textContent = tableRows.length.toLocaleString() + " rows";
    const head = el.querySelector(".g-head");
    head.style.width = width + "px";
    head.innerHTML = tableCols.map(c => `<div class="h${c in M.EDITABLE || M.LIST.has(c) ? "" : " ro"}" style="width:${WIDE[c] || 110}px" title="${esc(c)}">${esc(c)}</div>`).join("");
    const body = el.querySelector(".g-body");
    body.style.height = tableRows.length * RH + "px";
    body.style.width = width + "px";
    paintRows();
  }
  function paintRows() {
    const grid = $("#tab-table .grid");
    if (!grid) return;
    const body = grid.querySelector(".g-body");
    const top = Math.max(0, Math.floor((grid.scrollTop - 30) / RH) - 10);
    const n = Math.ceil(grid.clientHeight / RH) + 20;
    const ch = app.st.changed;
    let html = "";
    for (let i = top; i < Math.min(tableRows.length, top + n); i++) {
      const r = tableRows[i], changed = ch.get(r.taxonID);
      html += `<div class="r${r.taxonID === app.sel ? " sel" : ""}${isSyn(r) ? " syn" : ""}" data-id="${esc(r.taxonID)}" style="top:${i * RH}px">` +
        tableCols.map(c => {
          const editable = (c in M.EDITABLE || M.LIST.has(c)) && !(isSyn(r) && c !== "acceptedNameUsageID");
          const cls = "c" + (editable ? "" : " ro") + (changed && (changed.has(c) || changed.has("*")) ? " chg" : "");
          return `<div class="${cls}" data-col="${esc(c)}" style="width:${WIDE[c] || 110}px" title="${esc(r[c])}">${esc(r[c])}</div>`;
        }).join("") + "</div>";
    }
    body.innerHTML = html;
  }
  function startEdit(e) {
    const c = e.target.closest(".c");
    if (!c || c.classList.contains("ro")) {
      if (c) toast(`${c.dataset.col} is computed from the sources (or this is a merged name); it cannot be edited here.`);
      return;
    }
    if (!app.name) return askName();
    const id = c.parentNode.dataset.id, col = c.dataset.col, r = row(id);
    const input = document.createElement(col === "taxonRemarks" || col === "note" ? "textarea" : "input");
    input.className = "cell-edit";
    input.value = r[col] || "";
    c.textContent = "";
    c.appendChild(input);
    input.focus();
    input.select();
    let done = false;
    const finish = save => {
      if (done) return;
      done = true;
      if (save && input.value !== (r[col] || "")) addOp("set", { id, column: col, value: input.value });
      else paintRows();
    };
    input.addEventListener("keydown", k => {
      if (k.key === "Enter" && !k.shiftKey) { k.preventDefault(); finish(true); }
      if (k.key === "Escape") { k.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(false));
  }

  // ---- review by document: confirm everything a tool read from one document, after a spot check
  function machineByDoc() {
    const st = app.st, by = new Map();
    const get = d => { if (!by.has(d)) by.set(d, { lit: 0, notes: 0, hosts: 0, nat: 0, taxa: new Set() }); return by.get(d); };
    for (const [table, key] of [["literature", "lit"], ["notes", "notes"], ["hosts", "hosts"]]) {
      for (const r of st.t[table]) if (r.review === "machine" && r.doc_id) { const e = get(r.doc_id); e[key]++; e.taxa.add(st.shownId(r.taxon_id)); }
    }
    for (const id of st.order) {
      const r = st.d.get(id);
      if (r.nativity_review === "machine" && r.nativity_source && st.lookup.documents.has(r.nativity_source)) get(r.nativity_source).nat++;
    }
    return by;
  }
  function sample(rows, n) {              // evenly spread, so it is not just the first pages
    if (rows.length <= n) return rows;
    return Array.from({ length: n }, (_, i) => rows[Math.floor(i * rows.length / n)]);
  }
  function renderReview() {
    const el = $("#tab-review");
    if (!app.st) return;
    const st = app.st, by = machineByDoc();
    const docs = [...by.entries()].sort((a, b) => (b[1].lit + b[1].notes + b[1].hosts) - (a[1].lit + a[1].notes + a[1].hosts));
    if (app.reviewDoc && !by.has(app.reviewDoc)) app.reviewDoc = null;
    const doc = app.reviewDoc;
    const name = id => { const r = st.r(st.shownId(id)); return r ? sci(r.rank, r.name) : esc(id); };
    let html = '<h1>Review by document</h1><p class="muted">Everything a tool read from a document is <b>machine-read</b> until someone confirms it. ' +
      "Spot-check a document's rows below (they are spread across it), then confirm it all in one step. Reject single wrong rows on the taxon's own page first.</p>";
    html += '<div class="rv-docs">' + (docs.length ? '<table class="rv"><thead><tr><th>Document</th><th>Literature</th><th>Notes</th><th>Hosts</th><th>Nativity</th><th>Taxa</th></tr></thead><tbody>' +
      docs.map(([d, e]) => `<tr class="${d === doc ? "sel" : ""}" data-doc="${esc(d)}"><td>${esc((st.lookup.documents.get(d) || {}).citation || d)}</td>` +
        `<td>${e.lit}</td><td>${e.notes}</td><td>${e.hosts}</td><td>${e.nat}</td><td>${e.taxa.size}</td></tr>`).join("") + "</tbody></table>"
      : '<p class="ok">Nothing is waiting for review.</p>') + "</div>";
    if (doc) {
      const e = by.get(doc);
      const lit = st.t.literature.filter(r => r.doc_id === doc && r.review === "machine");
      const notes = st.t.notes.filter(r => r.doc_id === doc && r.review === "machine");
      html += `<h2>${esc((st.lookup.documents.get(doc) || {}).citation || doc)}</h2>` +
        `<p>${e.lit} literature rows, ${e.notes} notes, ${e.hosts} host plants` + (e.nat ? `, ${e.nat} nativity values` : "") + ` on ${e.taxa.size} taxa.</p>`;
      if (lit.length) {
        html += "<h3>Literature rows (a spread of " + Math.min(12, lit.length) + ")</h3><ul class='plain small'>" + sample(lit, 12).map(r =>
          `<li><a href="#/t/${esc(st.shownId(r.taxon_id))}" data-id="${esc(st.shownId(r.taxon_id))}">${name(r.taxon_id)}</a> <span class="muted">${esc(r.kind)}` +
          (r.pages ? ", p. " + esc(r.pages.replace(/ \| /g, ", ")) : "") + (r.areas ? " · " + esc(r.areas) : "") + (r.islands ? " · " + esc(r.islands) : "") +
          (r.status ? " · " + esc(r.status) : "") + (r.first_record_year ? " · " + esc(r.first_record_year) : "") + "</span></li>").join("") + "</ul>";
      }
      if (notes.length) {
        html += "<h3>Notes (a spread of " + Math.min(8, notes.length) + ")</h3><ul class='plain small'>" + sample(notes, 8).map(r =>
          `<li><a href="#/t/${esc(st.shownId(r.taxon_id))}" data-id="${esc(st.shownId(r.taxon_id))}">${name(r.taxon_id)}</a>: ${esc(r.note)} <span class="muted">${esc(r.topic)}, p. ${esc(r.pages)}</span></li>`).join("") + "</ul>";
      }
      html += '<div class="rv-confirm"><label><input type="checkbox" id="rv-nat"' + (e.nat ? " checked" : " disabled") + '> also confirm the ' + e.nat + ' nativity values this document set</label>' +
        `<p><button type="button" class="primary" id="rv-go">Confirm all ${e.lit + e.notes + e.hosts + (e.nat ? e.nat : 0)} machine-made rows from this document…</button></p></div>`;
    }
    el.innerHTML = html;
    el.querySelectorAll("tr[data-doc]").forEach(tr => tr.addEventListener("click", () => { app.reviewDoc = tr.dataset.doc; renderReview(); }));
    el.querySelectorAll("a[data-id]").forEach(a => a.addEventListener("click", e => { e.preventDefault(); select(a.dataset.id, "taxon"); }));
    const go = $("#rv-go");
    if (go) go.addEventListener("click", () => {
      if (!app.name) return askName();
      const nat = $("#rv-nat").checked;
      openForm({ title: "Confirm every machine-read row from this document?",
        intro: "You have spot-checked it. The rows become <b>editor</b>-confirmed, credited to " + esc(app.name) + ". Nothing is removed; reject wrong rows first.",
        submit: "Confirm all", onSubmit: () => { addOp("reviewDoc", { doc: app.reviewDoc, nativity: nat }); } });
    });
  }

  // ---- changes
  function renderChanges() {
    const el = $("#tab-changes");
    if (!app.st) return;
    const errors = M.check(app.st);
    const files = M.files(app.st);
    const bad = app.ops.filter(o => o.error).length;
    el.innerHTML = `<h1>${app.ops.length} change${app.ops.length === 1 ? "" : "s"} not committed</h1>` +
      `<p class="muted">Kept in this browser until you commit. Each is recorded as added by <b>${esc(app.name || "(no name yet)")}</b>.</p>` +
      (bad ? `<p class="err">${bad} change(s) no longer apply (the taxonomy changed under them); they are skipped. Undo them or fix them.</p>` : "") +
      (app.ops.length ? '<ol class="ops">' + app.ops.map((o, i) =>
        `<li class="${o.error ? "bad" : ""}"><span>${esc(M.describe(o, app.st))}</span> <span class="muted">${esc(o.by)} ${esc(o.date)}</span>` +
        (o.reason ? ` <span class="muted">· ${esc(o.reason)}</span>` : "") +
        (o.error ? `<div class="err">${esc(o.error)}</div>` : "") +
        `<button type="button" class="x" data-undo="${i}" aria-label="Undo">Undo</button></li>`).join("") + "</ol>" : "") +
      (app.ops.length ? `<h2>Checks</h2>` + (errors.length ? '<ul class="err">' + errors.map(x => `<li>${esc(x)}</li>`).join("") + "</ul>"
        : '<p class="ok">All checks pass.</p>') +
        "<h2>Files that change</h2><ul>" + Object.keys(files).map(p => `<li><code>${esc(p)}</code></li>`).join("") + "</ul>" +
        '<p><button type="button" class="primary" id="ch-commit">Commit…</button> <button type="button" id="ch-download">Download the changed files</button> ' +
        '<button type="button" class="danger" id="ch-discard">Discard all</button></p>' : "<p>Nothing to commit.</p>");
    const c = $("#ch-commit"); if (c) c.addEventListener("click", commitDialog);
    const d = $("#ch-download"); if (d) d.addEventListener("click", () => IO.download(M.files(app.st)));
    const x = $("#ch-discard"); if (x) x.addEventListener("click", () => openForm({
      title: "Discard every change?", intro: "This cannot be undone.", submit: "Discard", danger: true,
      onSubmit: () => { app.ops = []; recompute(); } }));
  }

  // ---- commit
  function commitDialog() {
    if (!app.name) return askName(commitDialog);
    const errors = M.check(app.st);
    const local = app.loaded && app.loaded.source.kind === "local";
    const folder = app.loaded && app.loaded.source.kind === "folder";
    const methods = [];
    if (local) methods.push(["local", "Commit and push from this clone (your git)"]);
    methods.push(["github", "Commit to GitHub with your token"]);
    if (folder) methods.push(["folder", "Save into the folder (then commit with git yourself)"]);
    methods.push(["download", "Download the changed files"]);
    const good = app.ops.filter(o => !o.error);
    openForm({
      title: `Commit ${good.length} change${good.length === 1 ? "" : "s"}`,
      intro: '<div class="warn-box"><b>This triggers a rebuild.</b> A commit goes straight to <code>' + esc(S.branch) +
        "</code> on GitHub, which rebuilds and redeploys the public site (" + esc(S.site) + ") in a few minutes. " +
        "Everything you added is public, credited to <b>" + esc(app.name) + "</b>.</div>" +
        (errors.length ? `<p class="err">${errors.length} check(s) fail; see Changes. Fix them first.</p>` : ""),
      fields: [
        { key: "method", label: "How", type: "radio", options: methods, value: methods[0][0] },
        { key: "message", label: "Commit message (first line)", value: `Editor: ${good.length} change${good.length === 1 ? "" : "s"} by ${app.name}` },
        { key: "token", label: "GitHub token (fine-grained, this repository, Contents: read and write)", type: "password", value: app.token,
          help: '<a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">Create a token ↗</a>; it stays in this browser.', show: v => v.method === "github" },
        { key: "remember", label: "Remember the token on this device", type: "checkbox", value: !!store.get("iog-editor-token"), show: v => v.method === "github" },
      ],
      submit: "Commit and rebuild",
      submitLabel: v => v.method === "download" ? "Download" : v.method === "folder" ? "Save" : "Commit and rebuild",
      disabled: !!errors.length,
      onSubmit: v => doCommit(v),
    });
  }
  async function doCommit(v) {
    const files = M.files(app.st);
    const message = M.commitMessage(app.ops, app.st, app.name, v.message);
    if (v.method === "download") { IO.download(files); toast("Downloaded " + Object.keys(files).length + " file(s)"); return; }
    if (v.method === "folder") {
      await IO.saveFolder(app.loaded.dir, files);
      toast("Saved into the folder. Commit and push them with git to rebuild the site.");
      await load(() => IO.loadFolder(app.loaded.dir));
      return;
    }
    if (v.method === "github") {
      const token = (v.token || "").trim();
      if (!token) throw new Error("a GitHub token is needed");
      app.token = token;
      if (v.remember) store.set("iog-editor-token", token); else { store.del("iog-editor-token"); store.set("iog-editor-token", token, true); }
      return commitGitHub(token, message, 0);
    }
    const res = await withRebase(() => IO.commitLocal({ files: M.files(app.st), message: M.commitMessage(app.ops, app.st, app.name, v.message),
                                                        author: app.name, baseSha: app.base.source.sha }), IO.loadLocal);
    afterCommit(res.sha, res.pushed ? "" : (res.error || "committed locally (not pushed)"));
    await load(IO.loadLocal);
  }
  async function commitGitHub(token, message, tries) {
    const src = app.base.source;
    const repo = src.kind === "github" ? src.repo : S.repo, branch = src.kind === "github" ? src.branch : S.branch;
    if (src.kind !== "github") {            // replay onto GitHub's latest first
      await rebase(() => IO.loadGitHub({ repo, branch, token }));
    }
    try {
      const res = await IO.commitGitHub({ repo, branch, token, baseSha: app.base.source.sha, files: M.files(app.st),
                                          message: M.commitMessage(app.ops, app.st, app.name, message.split("\n")[0]) });
      const texts = Object.assign({}, app.base.texts, M.files(app.st));
      app.base = M.makeBase(texts, Object.assign({}, app.base.source, { sha: res.sha, label: `${repo}@${branch} ${res.sha.slice(0, 7)}` }));
      app.loaded = { texts, source: app.base.source };
      app.ops = [];
      recompute();
      afterCommit(res.sha, "", repo, token);
    } catch (e) {
      if (e.moved && tries < 2) {
        toast("Someone committed meanwhile: replaying your changes onto theirs…");
        await rebase(() => IO.loadGitHub({ repo, branch, token }));
        return commitGitHub(token, message, tries + 1);
      }
      throw e;
    }
  }
  async function rebase(loader) {
    const ops = app.ops;
    const ok = await load(loader, true);
    if (!ok) throw new Error("could not reload to replay the changes");
    app.ops = ops;
    recompute();
    const bad = app.ops.filter(o => o.error);
    if (bad.length) { setTab("changes"); throw new Error(`${bad.length} change(s) no longer apply on the latest version; see Changes`); }
  }
  async function withRebase(fn, loader) {
    try { return await fn(); }
    catch (e) {
      if (!e.moved) throw e;
      await rebase(loader);
      return fn();
    }
  }
  function afterCommit(sha, warning, repo, token) {
    repo = repo || S.repo;
    const url = `https://github.com/${repo}/commit/${sha}`;
    openForm({
      title: "Committed",
      intro: `<p>Commit <a href="${esc(url)}" target="_blank" rel="noopener"><code>${esc(sha.slice(0, 7))}</code></a> by ${esc(app.name)}.` +
        (warning ? ` <span class="err">${esc(warning)}</span>` : "") + "</p>" +
        '<p id="rebuild">The rebuild starts in a moment…</p>',
      submit: "Close", cancel: null,
    });
    let n = 0;
    const poll = async () => {
      const el = document.getElementById("rebuild");
      if (!el) return;
      let run = null;
      try { run = await IO.rebuildStatus({ repo, sha, token }); } catch (e) { run = null; }
      if (run) {
        el.innerHTML = `Rebuild: <a href="${esc(run.url)}" target="_blank" rel="noopener">${esc(run.status)}${run.conclusion ? " · " + esc(run.conclusion) : ""}</a>` +
          (run.conclusion === "success" ? ` · <a href="${esc(S.site)}" target="_blank" rel="noopener">the site</a>` : "");
        if (run.status === "completed") return;
      }
      if (++n < 120) setTimeout(poll, 10000);
    };
    setTimeout(poll, 5000);
  }

  // ------------------------------------------------------------ dialogs
  function openForm(o) {
    const dlg = $("#dlg");
    const vals = {};
    let html = `<form method="dialog" class="dlg"><h2>${esc(o.title)}</h2>` + (o.intro ? `<div class="intro">${o.intro}</div>` : "");
    for (const f of o.fields || []) {
      vals[f.key] = f.value == null ? "" : f.value;
      html += `<div class="field" data-key="${esc(f.key)}">`;
      if (f.type === "checkbox") {
        html += `<label><input type="checkbox" name="${esc(f.key)}"${f.value ? " checked" : ""}> ${esc(f.label)}</label>`;
      } else if (f.type === "radio") {
        html += `<span class="lab">${esc(f.label)}</span>` + f.options.map(([k, lab]) =>
          `<label class="radio"><input type="radio" name="${esc(f.key)}" value="${esc(k)}"${k === f.value ? " checked" : ""}> ${esc(lab)}</label>`).join("");
      } else {
        html += `<label for="f-${esc(f.key)}">${esc(f.label)}${f.required ? " *" : ""}</label>`;
        if (f.type === "select") {
          html += `<select id="f-${esc(f.key)}" name="${esc(f.key)}">` + f.options.map(x => `<option${x === f.value ? " selected" : ""}>${esc(x)}</option>`).join("") + "</select>";
        } else if (f.type === "textarea") {
          html += `<textarea id="f-${esc(f.key)}" name="${esc(f.key)}" rows="3">${esc(f.value)}</textarea>`;
        } else if (f.type === "taxon") {
          html += `<input id="f-${esc(f.key)}" class="picker" autocomplete="off" placeholder="Type a name…" value="${esc(f.value ? app.st.name(f.value) : "")}">` +
            `<input type="hidden" name="${esc(f.key)}" value="${esc(f.value || "")}"><div class="picks"></div>`;
        } else {
          html += `<input id="f-${esc(f.key)}" name="${esc(f.key)}" type="${f.type === "password" ? "password" : "text"}" value="${esc(f.value)}"` +
            (f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : "") + ' autocomplete="off">';
        }
        if (f.help) html += `<div class="help">${f.help}</div>`;
      }
      html += "</div>";
    }
    html += '<div class="err" id="dlg-err" hidden></div><div class="buttons">' +
      (o.cancel === null ? "" : `<button type="button" value="cancel" id="dlg-cancel">${esc(o.cancel || "Cancel")}</button>`) +
      `<button type="submit" class="${o.danger ? "danger" : "primary"}" id="dlg-ok"${o.disabled ? " disabled" : ""}>${esc(o.submit || "OK")}</button></div></form>`;
    dlg.innerHTML = html;
    const form = dlg.querySelector("form");
    const read = () => {
      const v = {};
      for (const f of o.fields || []) {
        const el = form.elements[f.key];
        if (f.type === "checkbox") v[f.key] = el.checked;
        else if (f.type === "radio") v[f.key] = (form.querySelector(`input[name="${f.key}"]:checked`) || {}).value;
        else v[f.key] = el ? el.value : "";
      }
      return v;
    };
    const refresh = () => {
      const v = read();
      for (const f of o.fields || []) if (f.show) form.querySelector(`.field[data-key="${f.key}"]`).hidden = !f.show(v);
      if (o.submitLabel) form.querySelector("#dlg-ok").textContent = o.submitLabel(v);
    };
    form.addEventListener("change", refresh);
    for (const f of (o.fields || []).filter(x => x.type === "taxon")) wirePicker(form, f);
    const close = () => { if (dlg.open) dlg.close(); };
    if (o.extra) o.extra(form.querySelector(".buttons").parentNode.insertBefore(document.createElement("div"), form.querySelector("#dlg-err")), close);
    const cancel = form.querySelector("#dlg-cancel");
    if (cancel) cancel.addEventListener("click", () => { close(); if (o.onCancel) o.onCancel(); });
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const v = read();
      const missing = (o.fields || []).filter(f => f.required && !(v[f.key] || "").trim() && (!f.show || f.show(v)));
      const err = form.querySelector("#dlg-err");
      if (missing.length) { err.textContent = "Needed: " + missing.map(f => f.label).join(", "); err.hidden = false; return; }
      const ok = form.querySelector("#dlg-ok");
      ok.disabled = true;
      try {
        const r = o.onSubmit ? await o.onSubmit(v) : true;
        if (r === false) { ok.disabled = false; return; }
        if (dlg.querySelector("form") === form) close();
      } catch (ex) {
        err.textContent = ex.message; err.hidden = false; ok.disabled = false;
      }
    });
    refresh();
    if (!dlg.open) dlg.showModal();
    const first = form.querySelector("input:not([type=hidden]):not([type=radio]):not([type=checkbox]), select, textarea");
    if (first) first.focus();
  }
  function wirePicker(form, f) {
    const box = form.querySelector(`.field[data-key="${f.key}"]`);
    const input = box.querySelector(".picker"), hidden = box.querySelector("input[type=hidden]"), picks = box.querySelector(".picks");
    const show = () => {
      const terms = fold(input.value).split(/\s+/).filter(Boolean);
      if (!terms.length) { picks.innerHTML = ""; return; }
      const out = [];
      for (const r of app.st.rows) {
        if (f.filter && !f.filter(r)) continue;
        const t = app.search.get(r.taxonID) || "";
        if (terms.every(x => t.includes(x))) out.push(r);
        if (out.length > 400) break;
      }
      out.sort((a, b) => (fold(b.scientificName).startsWith(terms[0]) - fold(a.scientificName).startsWith(terms[0])) || a.scientificName.length - b.scientificName.length);
      picks.innerHTML = out.slice(0, 12).map(r => `<button type="button" data-id="${esc(r.taxonID)}">${sci(r.taxonRank, r.scientificName)} ` +
        `<span class="muted">${esc(r.taxonRank)}${r.family && r.taxonRank !== "Family" ? " · " + esc(r.family) : ""} · ${esc(r.taxonID)}</span></button>`).join("") ||
        '<p class="muted">No match.</p>';
    };
    input.addEventListener("input", () => { hidden.value = ""; show(); });
    picks.addEventListener("click", e => {
      const b = e.target.closest("button[data-id]");
      if (!b) return;
      hidden.value = b.dataset.id;
      input.value = app.st.name(b.dataset.id);
      picks.innerHTML = "";
    });
  }

  // ------------------------------------------------------------ wiring
  function init() {
    $("#queue").innerHTML = QUEUES.map(([k, lab]) => `<option value="${k}">${esc(lab)}</option>`).join("");
    $("#queue").addEventListener("change", e => { app.queue = e.target.value; render(); });
    let t = null;
    $("#q").addEventListener("input", e => {
      clearTimeout(t);
      t = setTimeout(() => { app.q = e.target.value; renderList(); if (app.tab === "table") renderTable(); }, 120);
    });
    $("#list").addEventListener("click", e => {
      const up = e.target.closest("[data-upl]");
      if (up) { app.upl = +up.dataset.upl; setTab("taxon"); return; }
      const it = e.target.closest("[data-id]");
      if (it) { e.preventDefault(); select(it.dataset.id, app.tab === "changes" ? "taxon" : null); }
    });
    $("#tab-taxon").addEventListener("click", e => {
      const a = e.target.closest("a[data-id]");
      if (a) { e.preventDefault(); return select(a.dataset.id); }
      onTaxonClick(e);
    });
    $("#tab-taxon").addEventListener("submit", onTaxonSubmit);
    $("#tab-changes").addEventListener("click", e => {
      const b = e.target.closest("button[data-undo]");
      if (b) undo(+b.dataset.undo);
    });
    for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => setTab(b.dataset.tab));
    $("#me-btn").addEventListener("click", () => askName());
    $("#changes-btn").addEventListener("click", () => setTab("changes"));
    $("#commit-btn").addEventListener("click", commitDialog);
    $("#src").addEventListener("click", chooseSource);
    window.addEventListener("hashchange", () => { fromHash(); render(); });
    document.addEventListener("keydown", e => {
      if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !$("#dlg").open) { e.preventDefault(); $("#q").focus(); }
    });
    window.addEventListener("beforeunload", e => { if (app.ops.length) { e.preventDefault(); e.returnValue = ""; } });
    window.addEventListener("resize", () => { if (app.tab === "table") paintRows(); });
    start();
  }
  window.IOGApp = app;              // for tests and the console
  init();
})();
