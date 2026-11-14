// The editor's model: the dataset tables as loaded (the base) plus a list of operations (the
// edits), replayed in order to give the current state. Nothing here touches the page.
//
// The tables are dataset/*.csv (schema.py): the taxa table is edited directly, one cell per
// field; distribution, vouchers, links, literature, notes and hosts are lists of rows. Writing
// them back gives the same bytes Python's dataset.write would (sorted rows, BOM, "\n"), so a
// commit changes only what was edited. Rows that point at a synonym still point at it after a
// merge; the build follows accepted_id (docs/REFACTOR.md).
(function () {
  "use strict";
  const S = window.IOG_SPEC;
  const CSV = window.IOGCSV;
  const T = S.tables;
  const SEP = S.sep;
  const RANK = S.rankOrder;
  const CONFIRMED = "editor confirmed";
  const PLACE = new Map(S.places.map(p => [p[0], { area: p[1], group: p[2] }]));
  const AREA_ORDER = S.areas.map(a => a.code);
  const COL_BASE = 1e11, NAME_BASE = 3e11, LOCAL_BASE = 5e11;
  const ID_RE = /^([0-9A-Z]{1,7}|gbif:\d+|name-\d+|IOG-\d+)$/;
  const SYN = "synonym";

  const validId = s => ID_RE.test(s || "");
  const iogNum = s => { const m = /^IOG-(\d+)$/.exec(s || ""); return m ? +m[1] : 0; };
  const today = () => new Date().toISOString().slice(0, 10);
  const blank = name => Object.fromEntries(T[name].columns.map(c => [c, ""]));
  const rankIdx = r => (r in RANK ? RANK[r] : 99);
  const fold = s => (s || "").toLowerCase();
  const splitList = v => (v || "").split("|").map(x => x.trim()).filter(Boolean);
  const isUrl = v => /^https?:\/\/\S+$/.test(v || "");

  // ids.to_int: the order rows are filed in
  function tid(ext) {
    let m;
    if ((m = /^gbif:(\d+)$/.exec(ext))) return +m[1];
    if ((m = /^name-(\d+)$/.exec(ext))) return NAME_BASE + +m[1];
    if ((m = /^IOG-(\d+)$/.exec(ext))) return LOCAL_BASE + +m[1];
    if (/^[0-9A-Z]{1,7}$/.test(ext)) return COL_BASE + parseInt(ext, 36);
    return 2 ** 62;
  }

  // ------------------------------------------------------------ references
  const slugOf = s => (s || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 56).replace(/-+$/, "");
  // literature/stage.py citation(): "Linnavuori, R. 1960. Title. Insects of Micronesia 6(5): 231-344."
  function citationOf(r) {
    let head = [(r.authors || "").replace(/\.+$/, ""), r.year].filter(Boolean).join(". ");
    if (head) head += ". ";
    const where = r.container ? r.container + (r.volume ? " " + r.volume : "") + (r.pages ? ": " + r.pages : "") : "";
    return head + (r.title || "").replace(/\.+$/, "") + "." + (where ? ` ${where}.` : "");
  }
  const DOC_FIELDS = ["title", "authors", "year", "container", "volume", "pages", "doi", "url", "licence", "kind"];

  // ------------------------------------------------------------ cell formats (build/export.py)
  const formatTag = a => `${a.value}: ${a.status || "present"}` + (a.source ? ` (${a.source})` : "");
  function parseTag(text) {
    const t = text.trim(), i = t.indexOf(":");
    if (i < 0) throw new Error(`"${t}" is not "Place: present|absent|doubtful (source)"`);
    const place = t.slice(0, i).trim(), rest = t.slice(i + 1).trim();
    const sp = rest.indexOf(" ");
    const status = sp < 0 ? rest : rest.slice(0, sp);
    let source = sp < 0 ? "" : rest.slice(sp + 1).trim();
    if (!S.distributionStatus.includes(status) ||
        (source && !(source.startsWith("(") && source.endsWith(")"))))
      throw new Error(`"${t}" is not "Place: present|absent|doubtful (source)"`);
    if (source) source = source.slice(1, -1).trim();
    return { value: place, status, source };
  }
  const occurrenceUrl = e => e.kind === "inat_observation" ? S.inatObs + e.ref :
    e.kind === "gbif_occurrence" ? S.gbifOcc + e.ref : null;
  function parseOccurrence(text) {
    const t = text.trim().split("?")[0].split("#")[0].replace(/\/+$/, "");
    const pats = [[/^https?:\/\/(www\.)?inaturalist\.org\/observations\/(\d+)$/, "inat_observation"],
                  [/^https?:\/\/(www\.)?gbif\.org\/occurrence\/(\d+)$/, "gbif_occurrence"]];
    for (const [re, kind] of pats) {
      const m = re.exec(t);
      if (m) return { kind, ref: m[2] };
    }
    throw new Error(`"${text}" is not an iNaturalist observation or GBIF occurrence URL ` +
                    "(https://www.inaturalist.org/observations/123, https://www.gbif.org/occurrence/123)");
  }
  // A taxon page on iNaturalist or GBIF (or its bare number) -> the number as a string.
  function parseTaxonRef(text, kind) {
    const t = (text || "").trim().split("?")[0].split("#")[0].replace(/\/+$/, "");
    if (!t) return "";
    if (/^\d+$/.test(t)) return t;
    const re = kind === "inat" ? /^https?:\/\/(www\.)?inaturalist\.org\/taxa\/(\d+)(-[^/]*)?$/
                               : /^https?:\/\/(www\.)?gbif\.org\/(?:[a-z-]+\/)?species\/(\d+)$/;
    const m = re.exec(t);
    if (!m) throw new Error(`"${text}" is not ${kind === "inat" ? "an iNaturalist taxon" : "a GBIF species"} page or number ` +
      (kind === "inat" ? "(https://www.inaturalist.org/taxa/47158)" : "(https://www.gbif.org/species/1234567)"));
    return m[2];
  }
  const formatLink = a => a.note ? `${a.note} <${a.value}>` : a.value;
  function parseLink(text) {
    const t = text.trim();
    if (t.endsWith(">") && t.includes(" <")) {
      const i = t.lastIndexOf(" <");
      return { value: t.slice(i + 2, -1).trim(), note: t.slice(0, i).trim() };
    }
    return { value: t, note: "" };
  }

  // ------------------------------------------------------------ writing the tables like Python
  // dataset.sort_rows: taxa depth first (children by name, a taxon's names after it); the
  // others by the taxon's id order, then their own key columns.
  function cmpKey(a, b) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const x = a[i], y = b[i];
      if (Array.isArray(x)) {
        const c = cmpKey(x, y);
        if (c) return c;
      } else if (x !== y) return x < y ? -1 : 1;
    }
    return a.length - b.length;
  }
  function sortTaxa(rows) {
    const accepted = rows.filter(r => r.status !== SYN);
    const byId = new Map(accepted.map(r => [r.id, r]));
    const kids = new Map(), names = new Map();
    for (const r of accepted) { if (!kids.has(r.parent_id)) kids.set(r.parent_id, []); kids.get(r.parent_id).push(r); }
    for (const r of rows) if (r.status === SYN) { if (!names.has(r.accepted_id)) names.set(r.accepted_id, []); names.get(r.accepted_id).push(r); }
    const byName = (a, b) => cmpKey([fold(a.name), tid(a.id)], [fold(b.name), tid(b.id)]);
    const out = [], seen = new Set();
    const roots = accepted.filter(r => !r.parent_id || !byId.has(r.parent_id));
    roots.sort((a, b) => cmpKey([a.parent_id !== "" ? 1 : 0, fold(a.name), tid(a.id)], [b.parent_id !== "" ? 1 : 0, fold(b.name), tid(b.id)]));
    const stack = roots.slice().reverse();
    while (stack.length) {
      const r = stack.pop();
      if (seen.has(r.id)) continue;
      seen.add(r.id);
      out.push(r);
      for (const n of (names.get(r.id) || []).slice().sort(byName)) out.push(n);
      for (const k of (kids.get(r.id) || []).slice().sort(byName).reverse()) stack.push(k);
    }
    for (const r of rows) if (r.status === SYN && !byId.has(r.accepted_id)) out.push(r);
    for (const r of accepted) if (!seen.has(r.id)) out.push(r);
    return out;
  }
  function sortRows(name, rows) {
    if (name === "taxa") return sortTaxa(rows);
    const t = T[name], hasTaxon = t.columns.includes("taxon_id");
    const key = r => {
      const parts = hasTaxon ? [tid(r.taxon_id)] : [];
      for (const c of t.key) {
        if (c === "taxon_id") continue;
        const v = r[c] || "";
        parts.push(/^\d+$/.test(v) && (c === "position" || c === "year") ? [0, +v, ""] : [1, 0, fold(v), v]);
      }
      return parts;
    };
    return rows.map(r => [key(r), r]).sort((a, b) => cmpKey(a[0], b[0])).map(x => x[1]);
  }

  // ------------------------------------------------------------ the base (files as loaded)
  // texts: {path: text or null (absent)}; source: {kind, label, sha}
  function makeBase(texts, source) {
    const tables = {};
    for (const name of Object.keys(T)) {
      const t = CSV.readTable(texts[T[name].file] || "", T[name].columns);
      t.bom = true;
      t.eol = "\n";
      t.columns = T[name].columns;
      tables[name] = t;
    }
    return { texts, tables, source: source || { kind: "files", label: "files" } };
  }

  // ------------------------------------------------------------ view rows (what the page shows)
  // The old taxonomy.csv field names, so the page's table and panels keep their words.
  const LEGACY = {
    scientificName: "name", scientificNameAuthorship: "authorship", taxonRank: "rank",
    taxonomicStatus: "status", vernacularName: "common_name", establishmentMeans: "nativity",
    taxonRemarks: "note", parentNameUsageID: "parent_id", acceptedNameUsageID: "accepted_id",
    inCatalogueOfLife: "in_col", nameMatch: "name_match", matchRemarks: "match_note",
    nameSources: "name_sources", modifiedBy: "modified_by", verifiedBy: "verified_by",
    verifiedDate: "verified_date", verificationSource: "verification_source", taxonID: "id",
  };
  const BACK = Object.fromEntries(Object.entries(LEGACY).map(([k, v]) => [v, k]));

  // ------------------------------------------------------------ state = base + operations
  class State {
    constructor(base) {
      this.base = base;
      const B = base.tables;
      this.d = new Map();                // id -> taxa row (copied before its first change)
      this.order = [];
      for (const r of B.taxa.rows) {
        if (!r.id || this.d.has(r.id)) continue;
        this.d.set(r.id, r);
        this.order.push(r.id);
      }
      this.t = {};                       // the other editable tables, as row arrays
      for (const name of S.editTables) if (name !== "taxa") this.t[name] = B[name].rows.slice();
      this.own = new Set();
      this.changed = new Map();          // id -> Set of columns changed
      this.added = new Set();
      this.removed = new Set();
      this.structural = false;
      this._kids = null;
      this.lookup = { documents: new Map(this.t.documents.map(r => [r.doc_id, r])) };
      let max = 0;
      for (const id of this.order) max = Math.max(max, iogNum(id));
      this.nextIog = max + 1;
    }
    // --- dataset rows, for the operations
    r(id) { return this.d.get(id); }
    name(id) { const r = this.d.get(id); return r ? r.name : id; }
    isSyn(r) { return r && r.status === SYN; }
    shownId(id) {
      const r = this.d.get(id);
      return r && r.status === SYN && r.accepted_id ? r.accepted_id : id;
    }
    mrow(id) {
      let r = this.d.get(id);
      if (!r) throw new Error(`no taxon ${id}`);
      if (!this.own.has(r)) { r = Object.assign({}, r); this.own.add(r); this.d.set(id, r); }
      return r;
    }
    setCell(id, col, value) {
      const r = this.mrow(id);
      if (r[col] === value) return;
      r[col] = value;
      if (!this.changed.has(id)) this.changed.set(id, new Set());
      this.changed.get(id).add(col);
    }
    stamp(id, op) {
      if (!this.d.has(id) || this.removed.has(id)) return;
      this.setCell(id, "modified_by", op.by);
      this.setCell(id, "modified", op.date);
    }
    kids() {
      if (!this._kids) {
        this._kids = new Map();
        for (const id of this.order) {
          const r = this.d.get(id);
          if (r.status === SYN || !r.parent_id) continue;
          if (!this._kids.has(r.parent_id)) this._kids.set(r.parent_id, []);
          this._kids.get(r.parent_id).push(id);
        }
      }
      return this._kids;
    }
    children(id) { return this.kids().get(id) || []; }
    synonymsOf(id) { return this.order.filter(x => { const r = this.d.get(x); return r.status === SYN && r.accepted_id === id; }); }
    descendants(id) {
      const out = [], stack = [id];
      while (stack.length) for (const c of this.children(stack.pop())) { out.push(c); stack.push(c); }
      return out;
    }
    isUnder(id, ancestor) {
      const seen = new Set();
      for (let x = id; x && !seen.has(x); x = (this.d.get(x) || {}).parent_id) {
        if (x === ancestor) return true;
        seen.add(x);
      }
      return false;
    }
    lineage(id) {
      const out = [], seen = new Set();
      for (let x = (this.d.get(id) || {}).parent_id; x && !seen.has(x); x = (this.d.get(x) || {}).parent_id) { seen.add(x); out.unshift(x); }
      return out;
    }
    structure() { this.structural = true; this._kids = null; }
    newId() { return "IOG-" + this.nextIog++; }

    // --- rows of the list tables for a displayed taxon
    mine(name, id) { return this.t[name].filter(r => this.shownId(r.taxon_id) === id); }
    annFor(id, kind) {                   // the shapes the page reads
      if (kind === "distribution") return this.mine("distribution", id).map(r => ({ value: r.place, status: r.status, source: r.source, doc: r.doc_id, added_by: r.added_by, added: r.added }));
      return this.mine("links", id).filter(r => r.system === "editor").map(r => ({ value: r.value, note: r.label, added_by: r.added_by, added: r.added }));
    }
    occFor(id) {
      return this.mine("vouchers", id).filter(e => occurrenceUrl(e)).map(e => ({ kind: e.kind, ref: e.ref, note: e.note, editor: e.added_by, edited: e.added }));
    }

    // ------------------------------------------------------------ at the end of a replay
    finish() {
      if (this.structural) this.reorder();
      this.buildViews();
    }
    reorder() {
      const sorted = sortTaxa(this.order.map(id => this.d.get(id)));
      this.order = sorted.map(r => r.id);
      this._kids = null;
    }
    buildViews() {
      const B = this.base.tables;
      const own = name => {
        const m = new Map();
        for (const r of (this.t[name] || B[name].rows)) {
          const id = this.shownId(r.taxon_id);
          if (!m.has(id)) m.set(id, []);
          m.get(id).push(r);
        }
        return m;
      };
      const records = new Map();
      for (const r of B.records.rows) {
        const id = this.shownId(r.taxon_id);
        if (!records.has(id)) records.set(id, []);
        records.get(id).push(r);
      }
      this.recordsBy = records;
      this.islandsBy = new Map();
      for (const r of B.islands.rows) {
        const id = this.shownId(r.taxon_id);
        if (!this.islandsBy.has(id)) this.islandsBy.set(id, []);
        this.islandsBy.get(id).push(r);
      }
      const lits = own("literature"), notes = own("notes"), dists = own("distribution"),
            vouchers = own("vouchers"), links = own("links");
      const doc = id => this.lookup.documents.get(id) || { citation: id, title: id };
      const conflict = id => {
        const vals = new Set((lits.get(id) || []).filter(r => r.status).map(r => r.status === "endemic" ? "native" : r.status === "invasive" ? "introduced" : r.status));
        vals.delete("unknown"); vals.delete("cryptogenic");
        const nat = this.d.get(id).nativity;
        return vals.size > 1 || (vals.size === 1 && nat !== "unknown" && !vals.has(nat));
      };
      this.views = new Map();
      const st_excl = new Map(this.t.unplaced.filter(u => u.status === "excluded").map(u => [u.name, u]));
      for (const id of this.order) {
        const r = this.d.get(id);
        const acc = r.status === SYN ? this.d.get(r.accepted_id) : null;
        const par = r.parent_id ? this.d.get(r.parent_id) : null;
        const base = acc || r;
        const chain = this.lineage(acc ? acc.id : id).map(x => this.d.get(x)).concat(acc ? [acc] : [r]);
        const by = {};
        for (const a of chain) by[a.rank] = a.name;
        const ownRecs = records.get(id) || [];
        const sum = src => ownRecs.filter(x => x.source === src).reduce((n, x) => n + +x.records, 0);
        const areas = new Set(ownRecs.filter(x => x.source !== "gbif_specimens" && +x.records).map(x => x.area));
        for (const l of (lits.get(id) || [])) if (l.kind !== "mention") splitList(l.areas).forEach(a => areas.add(a));
        for (const x of (dists.get(id) || [])) if (x.status === "present") areas.add((PLACE.get(x.place) || { area: "" }).area);
        const litRows = lits.get(id) || [];
        const docsHere = [...new Set(litRows.map(l => l.doc_id))];
        const machineLit = litRows.filter(l => l.review === "machine").length;
        const v = Object.assign({}, r, {
          taxonID: r.id, parentNameUsageID: r.parent_id, parentNameUsage: par ? par.name : "",
          acceptedNameUsageID: r.accepted_id, acceptedNameUsage: acc ? acc.name : "",
          scientificName: r.name, scientificNameAuthorship: r.authorship, taxonRank: r.rank,
          taxonomicStatus: r.status, vernacularName: r.common_name, taxonRemarks: r.note,
          establishmentMeans: r.nativity === "unknown" ? "" : r.nativity,
          inCatalogueOfLife: r.in_col, nameMatch: r.name_match, matchRemarks: r.match_note,
          nameSources: r.name_sources, hidden: r.hidden === "yes" ? "1" : "0",
          modifiedBy: r.modified_by, verifiedBy: r.verified_by, verifiedDate: r.verified_date,
          verificationSource: r.verification_source,
          verificationStatus: r.verified === "yes" ? CONFIRMED : "",
          class: by.Class || "", order: by.Order || "", family: by.Family || "", genus: by.Genus || "",
          nameAccordingTo: /^IOG-/.test(id) ? "Insects of Guam curator" : r.in_col === "yes" ? "Catalogue of Life" : "source name",
          references: r.in_col === "yes" && /^[0-9A-Z]{1,7}$/.test(id) ? "https://www.catalogueoflife.org/data/taxon/" + id : (r.gbif_key ? "https://www.gbif.org/species/" + r.gbif_key : ""),
          recordedIn: AREA_ORDER.filter(a => areas.has(a)).join(SEP),
          islands: [...new Set((this.islandsBy.get(id) || []).map(x => x.island))].sort().join(SEP),
          distributionTags: (dists.get(id) || []).map(x => formatTag({ value: x.place, status: x.status, source: x.source })).join(SEP),
          associatedOccurrences: (vouchers.get(id) || []).map(occurrenceUrl).filter(Boolean).join(SEP),
          associatedReferences: (links.get(id) || []).filter(x => x.system === "editor").map(x => formatLink({ value: x.value, note: x.label })).join(SEP),
          gbifRecords: sum("gbif"), specimenRecords: sum("gbif_specimens"), inatObservations: sum("inat"),
          literatureRecords: docsHere.length,
          literatureSources: docsHere.map(d => doc(d).citation + (litRows.some(l => l.doc_id === d && l.review === "machine") ? " [machine-read]" : "")).join(SEP),
          verificationRemarks: machineLit && !litRows.some(l => l.review !== "machine") ? "literature records machine-read only" : "",
          excludedReason: (st_excl.get(r.name) || {}).note || "",
          machineLit, machineNotes: (notes.get(id) || []).filter(n => n.review === "machine").length,
          noteCount: (notes.get(id) || []).length, nativityConflict: r.status !== SYN && conflict(id),
        });
        this.views.set(id, v);
      }
      this.rows = this.order.map(id => this.views.get(id));
    }
    row(id) { return this.views ? this.views.get(id) : undefined; }
  }

  // ------------------------------------------------------------ operations
  const need = (cond, msg) => { if (!cond) throw new Error(msg); };
  function accepted(st, id, what) {
    const r = st.r(id);
    need(r, `${what || "taxon"} ${id} is not in the taxonomy`);
    need(!st.isSyn(r), `${r.name} (${id}) is a synonym: work on ${st.name(r.accepted_id)} instead`);
    return r;
  }
  function checkParent(st, id, parentId, rank) {
    const p = accepted(st, parentId, "parent");
    need(!id || !st.isUnder(parentId, id), `${st.name(parentId)} is under ${st.name(id)}: that would be a cycle`);
    need(rankIdx(p.rank) < rankIdx(rank), `a ${rank} cannot go under a ${p.rank} (${p.name})`);
    return p;
  }
  const column = c => LEGACY[c] || c;
  const EDITABLE = new Set(["name", "authorship", "rank", "status", "common_name", "other_common_names",
    "nativity", "nativity_source", "iucn", "superfamily", "subfamily", "tribe", "in_col", "gbif_key",
    "name_match", "match_note", "name_sources", "hidden", "hidden_reason", "note", "flag",
    "parent_id", "accepted_id", "verified"]);
  const OPS = {
    set(st, op) {
      let col = column(op.column);
      const v = (op.value == null ? "" : String(op.value)).trim();
      const r = st.r(op.id);
      need(r, `no taxon ${op.id}`);
      if (op.column === "verificationStatus") {
        need(v === CONFIRMED || v === "", "only 'editor confirmed' can be set by hand");
        return OPS.verify(st, Object.assign({}, op, { on: v === CONFIRMED }));
      }
      if (col === "parent_id") return OPS.move(st, Object.assign({}, op, { parent: v }));
      if (op.column === "parentNameUsage") {
        const hits = st.order.filter(x => { const y = st.r(x); return y.status !== SYN && y.name === v; });
        need(hits.length === 1, `${hits.length} taxa are named "${v}": pick the parent by id`);
        return OPS.move(st, Object.assign({}, op, { parent: hits[0] }));
      }
      if (col === "accepted_id") return v ? OPS.synonymize(st, Object.assign({}, op, { into: v })) : OPS.split(st, op);
      if (col === "nativity") return OPS.nativity(st, Object.assign({}, op, { value: v || "unknown" }));
      if (col === "hidden") return (v === "1" || v === "yes") ? OPS.hide(st, op) : OPS.unhide(st, op);
      need(EDITABLE.has(col), `${op.column} is computed and cannot be edited`);
      if (col === "status") {
        need(S.statuses.includes(v), `status must be one of ${S.statuses.join(", ")}`);
        if (v === SYN) { need(st.isSyn(r), "use Synonymize to merge a taxon into another"); return; }
        if (st.isSyn(r)) return OPS.split(st, op);
      }
      need(!st.isSyn(r) || col === "name" || col === "authorship" || col === "match_note" || col === "name_match" || col === "name_sources",
           `${r.name} is a name of ${st.name(r.accepted_id)}: edit that taxon, or split this name out first`);
      if (col === "rank") {
        need(S.ranks.includes(v), `rank must be one of ${S.ranks.join(", ")}`);
        const p = r.parent_id && st.r(r.parent_id);
        need(!p || rankIdx(p.rank) < rankIdx(v), `a ${v} cannot be under a ${p && p.rank}`);
        need(st.children(op.id).every(c => rankIdx(st.r(c).rank) > rankIdx(v)), `taxa under ${r.name} would rank at or above it`);
      }
      if (col === "name" || col === "rank") need(v, "a name and a rank are required");
      if (col === "in_col") need(v === "yes" || v === "no", "in_col is yes or no");
      if (col === "flag") need(v === "" || v === "new", "flag is new or empty");
      if (col === "gbif_key") need(v === "" || /^\d+$/.test(v), "the GBIF key is a number");
      st.setCell(op.id, col, v);
      st.stamp(op.id, op);
      if (col === "name" || col === "rank") st.structure();
    },

    nativity(st, op) {
      const r = st.r(op.id);
      need(r && !st.isSyn(r), `${st.name(op.id)} is not an accepted taxon`);
      need(S.nativity.includes(op.value), `nativity must be one of ${S.nativity.join(", ")}`);
      const src = (op.source || "").trim();
      need(!src || src === "editor" || src === "gbif" || st.lookup.documents.has(src),
           "the source must be a reference from the list (or create one), or left blank");
      st.setCell(op.id, "nativity", op.value);
      st.setCell(op.id, "nativity_source", op.value === "unknown" ? "" : (src || "editor"));
      st.setCell(op.id, "nativity_review", op.value === "unknown" ? "" : "editor");
      st.stamp(op.id, op);
    },
    // An editor agrees with a value a tool set.
    confirmNativity(st, op) {
      const r = st.r(op.id);
      need(r && r.nativity !== "unknown", "nothing to confirm: the nativity is unknown");
      st.setCell(op.id, "nativity_review", "editor");
      st.stamp(op.id, op);
    },

    move(st, op) {
      const r = accepted(st, op.id);
      need(op.parent, "choose the parent");
      checkParent(st, op.id, op.parent, r.rank);
      if (r.parent_id === op.parent) return;
      st.setCell(op.id, "parent_id", op.parent);
      st.stamp(op.id, op);
      st.structure();
    },

    synonymize(st, op) {
      const r = accepted(st, op.id), into = accepted(st, op.into, "accepted taxon");
      need(op.id !== op.into, "a taxon cannot be a synonym of itself");
      need(r.rank === into.rank, `${r.name} is a ${r.rank}, ${into.name} a ${into.rank}: merge taxa of the same rank`);
      need(!st.isUnder(op.into, op.id), `${into.name} is under ${r.name}`);
      st.setCell(op.id, "status", SYN);
      st.setCell(op.id, "accepted_id", op.into);
      st.setCell(op.id, "parent_id", "");
      st.setCell(op.id, "name_match", "curated merge");
      if (op.reason) st.setCell(op.id, "match_note", op.reason);
      st.stamp(op.id, op);
      for (const s of st.synonymsOf(op.id)) st.setCell(s, "accepted_id", op.into);   // its other names follow
      for (const c of st.children(op.id)) st.setCell(c, "parent_id", op.into);       // and the taxa under it
      st.stamp(op.into, op);
      st.structure();
    },

    split(st, op) {
      const r = st.r(op.id);
      need(r && st.isSyn(r), `${st.name(op.id)} is not a synonym`);
      const acc = st.r(r.accepted_id);
      const parent = op.parent || (acc && acc.parent_id) || "";
      need(r.name_match !== "COL synonym", `${r.name} is a Catalogue of Life synonym; it cannot be split here`);
      need(parent, "choose the parent it goes under");
      checkParent(st, op.id, parent, r.rank || (acc && acc.rank));
      st.setCell(op.id, "status", "accepted");
      st.setCell(op.id, "accepted_id", "");
      st.setCell(op.id, "parent_id", parent);
      st.setCell(op.id, "name_match", "curated split");
      if (!r.nativity) st.setCell(op.id, "nativity", "unknown");
      st.stamp(op.id, op);
      if (acc) st.stamp(acc.id, op);
      st.structure();
    },

    add(st, op) {
      const name = (op.name || "").trim();
      need(name, "a new taxon needs a name");
      need(S.ranks.includes(op.rank), `rank must be one of ${S.ranks.join(", ")}`);
      const status = op.status || "accepted";
      need(["accepted", "morphospecies", "doubtful"].includes(status), "a new taxon is accepted, doubtful or a morphospecies");
      const p = checkParent(st, null, op.parent, op.rank);
      need(!st.children(op.parent).some(c => st.name(c) === name), `${p.name} already has ${name}`);
      // A specific iNaturalist and/or GBIF taxon: refuse one that is already a taxon here.
      const inat = parseTaxonRef(op.inat, "inat"), gbif = parseTaxonRef(op.gbif, "gbif");
      if (gbif) {
        const dup = [...st.d.values()].find(x => x.status !== SYN && String(x.gbif_key) === gbif);
        need(!dup, `GBIF ${gbif} is already ${dup && dup.name} (${dup && dup.id}): link to it instead of adding a duplicate`);
      }
      if (inat) {
        const dup = st.t.links.find(l => l.system === "inaturalist" && l.value === inat);
        const who = dup && st.d.get(st.shownId(dup.taxon_id));
        need(!dup, `iNaturalist ${inat} is already ${who ? who.name + " (" + who.id + ")" : "linked to a taxon"}: link to it instead of adding a duplicate`);
      }
      const id = op.newId && !st.d.has(op.newId) ? op.newId : st.newId();
      op.newId = id;
      st.nextIog = Math.max(st.nextIog, iogNum(id) + 1);
      if (inat) st.t.links.push(Object.assign(blank("links"), { taxon_id: id, system: "inaturalist", value: inat,
        confidence: "high", note: "linked by editor", added_by: op.by, added: op.date }));
      const r = Object.assign(blank("taxa"), {
        id, parent_id: op.parent, rank: op.rank, name, authorship: op.authorship || "", status,
        gbif_key: gbif, common_name: op.common || "", nativity: "unknown", in_col: "no", note: op.note || "",
        added_by: op.by, added: op.date, modified_by: op.by, modified: op.date });
      st.own.add(r);
      st.d.set(id, r);
      st.order.push(id);
      st.added.add(id);
      st.changed.set(id, new Set(["*"]));
      st.structure();
    },

    addName(st, op) {
      const acc = accepted(st, op.into, "accepted taxon");
      const name = (op.name || "").trim();
      need(name, "the name is empty");
      need(![op.into].concat(st.synonymsOf(op.into)).some(x => st.name(x) === name && (st.r(x).authorship || "") === (op.authorship || "")),
           `${name} is already a name of ${acc.name}`);
      const id = op.newId && !st.d.has(op.newId) ? op.newId : st.newId();
      op.newId = id;
      st.nextIog = Math.max(st.nextIog, iogNum(id) + 1);
      const r = Object.assign(blank("taxa"), {
        id, accepted_id: op.into, rank: acc.rank, name, authorship: op.authorship || "", status: SYN,
        in_col: "no", name_match: "curated merge", match_note: op.reason || "",
        added_by: op.by, added: op.date });
      st.own.add(r);
      st.d.set(id, r);
      st.order.push(id);
      st.added.add(id);
      st.changed.set(id, new Set(["*"]));
      st.stamp(op.into, op);
      st.structure();
    },

    hide(st, op) {
      accepted(st, op.id);
      st.setCell(op.id, "hidden", "yes");
      st.setCell(op.id, "hidden_reason", op.reason || "");
      for (const x of st.descendants(op.id)) {
        if (st.r(x).hidden === "yes") continue;
        st.setCell(x, "hidden", "yes");
        st.setCell(x, "hidden_reason", `under ${op.id}`);
      }
      st.stamp(op.id, op);
    },
    unhide(st, op) {
      accepted(st, op.id);
      st.setCell(op.id, "hidden", "");
      st.setCell(op.id, "hidden_reason", "");
      for (const x of st.descendants(op.id)) {
        if (st.r(x).hidden_reason === `under ${op.id}`) { st.setCell(x, "hidden", ""); st.setCell(x, "hidden_reason", ""); }
      }
      st.stamp(op.id, op);
    },
    // Delete for good: only a taxon added here (IOG-), with nothing under it.
    remove(st, op) {
      const r = st.r(op.id);
      need(r && /^IOG-/.test(op.id), "only a taxon added in this editor (IOG-) can be deleted; hide others");
      need(!st.children(op.id).length, `${r.name} has taxa under it: move or delete them first`);
      const gone = new Set([op.id].concat(st.synonymsOf(op.id).filter(s => /^IOG-/.test(s))));
      for (const name of Object.keys(st.t)) st.t[name] = st.t[name].filter(x => !gone.has(x.taxon_id));
      for (const s of st.synonymsOf(op.id)) if (!gone.has(s)) st.setCell(s, "accepted_id", r.parent_id);   // source names it held
      for (const x of gone) { st.d.delete(x); st.removed.add(x); }
      st.order = st.order.filter(x => !gone.has(x));
      if (r.accepted_id) st.stamp(r.accepted_id, op);
      st.structure();
    },

    verify(st, op) {
      accepted(st, op.id);
      st.setCell(op.id, "verified", op.on ? "yes" : "");
      st.setCell(op.id, "verified_by", op.on ? op.by : "");
      st.setCell(op.id, "verified_date", op.on ? op.date : "");
      st.setCell(op.id, "verification_source", op.on ? (op.source || "") : "");
      st.stamp(op.id, op);
    },
    // A reviewed tool-made taxon no longer needs a second look.
    clearFlag(st, op) {
      need(st.r(op.id) && st.r(op.id).flag === "new", "that taxon is not flagged new");
      st.setCell(op.id, "flag", "");
      st.stamp(op.id, op);
    },

    tag(st, op) {
      accepted(st, op.id);
      need(PLACE.has(op.place), `"${op.place}" is not a place on the list`);
      const status = op.status || "present";
      need(S.distributionStatus.includes(status), `status must be one of ${S.distributionStatus.join(", ")}`);
      if (op.doc) need(st.lookup.documents.has(op.doc), "pick a reference from the list, or create one");
      const have = st.t.distribution.findIndex(a => a.place === op.place && st.shownId(a.taxon_id) === op.id);
      const row = Object.assign(blank("distribution"), { taxon_id: op.id, place: op.place, status,
        source: (op.source || "").trim(), doc_id: op.doc || "", added_by: op.by, added: op.date });
      if (have >= 0) {       // a tag edited without a reference keeps the one it had
        const keep = op.doc || st.t.distribution[have].doc_id;
        st.t.distribution[have] = Object.assign({}, st.t.distribution[have], row, { doc_id: keep });
      } else st.t.distribution.push(row);
      st.stamp(op.id, op);
    },
    untag(st, op) {
      const before = st.t.distribution.length;
      st.t.distribution = st.t.distribution.filter(a => !(a.place === op.place && st.shownId(a.taxon_id) === op.id));
      need(st.t.distribution.length < before, `${st.name(op.id)} has no tag for ${op.place}`);
      st.stamp(op.id, op);
    },
    voucher(st, op) {
      accepted(st, op.id);
      const { kind, ref } = parseOccurrence(op.url || "");
      const other = st.t.vouchers.find(e => e.kind === kind && e.ref === ref);
      need(!other, other && st.shownId(other.taxon_id) === op.id ? "that record is already a voucher here" :
           `that record is already a voucher for ${other && st.name(st.shownId(other.taxon_id))}`);
      st.t.vouchers.push(Object.assign(blank("vouchers"), { taxon_id: op.id, kind, ref,
        note: (op.note || "").trim(), added_by: op.by, added: op.date }));
      st.stamp(op.id, op);
    },
    unvoucher(st, op) {
      const { kind, ref } = parseOccurrence(op.url || "");
      const before = st.t.vouchers.length;
      st.t.vouchers = st.t.vouchers.filter(e => !(e.kind === kind && e.ref === ref && st.shownId(e.taxon_id) === op.id));
      need(st.t.vouchers.length < before, "no such voucher");
      st.stamp(op.id, op);
    },
    link(st, op) {
      accepted(st, op.id);
      const url = (op.url || "").trim();
      need(isUrl(url), `a link needs a URL (https://...), not "${url}"`);
      const have = st.t.links.findIndex(a => a.system === "editor" && a.value === url && st.shownId(a.taxon_id) === op.id);
      const row = Object.assign(blank("links"), { taxon_id: op.id, system: "editor", value: url,
        label: (op.label || "").trim(), confidence: "high", added_by: op.by, added: op.date });
      if (have >= 0) st.t.links[have] = Object.assign({}, st.t.links[have], row);
      else st.t.links.push(row);
      st.stamp(op.id, op);
    },
    unlink(st, op) {
      const before = st.t.links.length;
      st.t.links = st.t.links.filter(a => !(a.system === "editor" && a.value === op.url && st.shownId(a.taxon_id) === op.id));
      need(st.t.links.length < before, "no such link");
      st.stamp(op.id, op);
    },

    // A name with records that no tool could place: put it under a parent (a new taxon),
    // and take it off the worklist.
    place(st, op) {
      const row = st.t.unplaced.find(u => u.name === op.unplacedName);
      need(row, `${op.unplacedName} is not on the unplaced list`);
      OPS.add(st, op);
      st.t.unplaced = st.t.unplaced.filter(u => u.name !== op.unplacedName);
    },

    // An unplaced name that is another name of a taxon already here: it becomes a synonym row
    // under it, so every record, literature row and photo that uses the name (now or in a later
    // sync or ingest, which look names up here first) is the valid taxon's.
    placeSynonym(st, op) {
      const row = st.t.unplaced.find(u => u.name === op.unplacedName);
      need(row, `${op.unplacedName} is not on the unplaced list`);
      OPS.addName(st, Object.assign(op, { name: op.name || op.unplacedName,
        reason: op.reason || `from the unplaced list (${row.source})` }));
      st.t.unplaced = st.t.unplaced.filter(u => u.name !== op.unplacedName);
    },

    // Keep a name out for good (an extinct fossil, not a hexapod, a bad record): a taxon in the
    // tree is hidden with everything under it; the name goes on the unplaced page as
    // excluded, and match, sync and lit never add it (or its species) again.
    exclude(st, op) {
      const reason = (op.reason || "").trim();
      need(reason, "say why it is excluded (e.g. extinct fossil taxon)");
      let name = (op.name || "").trim(), rank = op.rank || "", key = op.key || "";
      if (op.id) {
        const r = accepted(st, op.id);
        OPS.hide(st, Object.assign({}, op, { reason: "excluded: " + reason }));
        name = r.name; rank = r.rank; key = op.id;
      }
      need(name, "which name?");
      const have = st.t.unplaced.find(u => u.name === name);
      need(!have || have.status !== "excluded", `${name} is already excluded`);
      if (have) {
        Object.assign(have, { status: "excluded", note: reason, added_by: op.by, added: op.date });
        st.t.unplaced = st.t.unplaced.slice();
      } else {
        st.t.unplaced.push(Object.assign(blank("unplaced"), { name, rank, source: "editor", key,
          note: reason, status: "excluded", added_by: op.by, added: op.date }));
      }
    },
    unexclude(st, op) {
      const row = st.t.unplaced.find(u => u.name === op.name && u.status === "excluded");
      need(row, `${op.name} is not excluded`);
      const id = st.d.has(row.key) ? row.key : null;
      if (id && /^excluded:/.test(st.r(id).hidden_reason)) OPS.unhide(st, Object.assign({}, op, { id }));
      st.t.unplaced = st.t.unplaced.filter(u => u !== row);
    },

    // --- references: documents.csv is the one bibliography every source is cited from
    newDocument(st, op) {
      const title = (op.title || "").trim();
      need(title, "a reference needs a title");
      const year = (op.year || "").trim();
      need(!year || /^\d{4}$/.test(year), "the year is four digits");
      need(!(op.url || "").trim() || isUrl(op.url.trim()), "the address must start with http:// or https://");
      const surname = ((op.authors || "").split(/[,;]/)[0] || "").trim();
      const same = [...st.lookup.documents.values()].find(d =>
        slugOf(d.title) === slugOf(title) && (d.year || "") === year && slugOf((d.authors || "").split(/[,;]/)[0]) === slugOf(surname));
      if (same) { op.newId = same.doc_id; return; }               // already in the bibliography: use it
      const base = slugOf(`${surname} ${year} ${title}`) || "reference";
      let id = op.newId && !st.lookup.documents.has(op.newId) ? op.newId : base, n = 2;
      while (st.lookup.documents.has(id)) id = `${base}-${n++}`;
      op.newId = id;
      const row = Object.assign(blank("documents"), { doc_id: id, added_by: op.by, added: op.date, kind: op.kind || "paper" });
      for (const f of DOC_FIELDS) if (op[f] != null && f !== "kind") row[f] = String(op[f]).trim();
      row.citation = citationOf(row);
      st.t.documents.push(row);
      st.lookup.documents.set(id, row);
    },
    editDocument(st, op) {
      const i = st.t.documents.findIndex(d => d.doc_id === op.doc);
      need(i >= 0, `no reference ${op.doc}`);
      const row = Object.assign({}, st.t.documents[i]);
      for (const f of DOC_FIELDS) if (op[f] != null) row[f] = String(op[f]).trim();
      need(row.title, "a reference needs a title");
      need(!row.year || /^\d{4}$/.test(row.year), "the year is four digits");
      need(!row.url || isUrl(row.url), "the address must start with http:// or https://");
      row.citation = citationOf(row);
      st.t.documents[i] = row;
      st.lookup.documents.set(op.doc, row);
    },
    removeDocument(st, op) {
      need(st.lookup.documents.has(op.doc), `no reference ${op.doc}`);
      const used = ["literature", "notes", "hosts", "distribution", "islands"].filter(t => st.t[t] && st.t[t].some(r => r.doc_id === op.doc))
        .concat(st.order.some(id => st.d.get(id).nativity_source === op.doc) ? ["nativity"] : []);
      need(!used.length, `it is still cited (${used.join(", ")}): remove those first, or merge it into another reference`);
      st.t.documents = st.t.documents.filter(d => d.doc_id !== op.doc);
      st.lookup.documents.delete(op.doc);
    },
    // Cite a source for a taxon: a literature row (what the document says about it)
    citeSource(st, op) {
      accepted(st, op.id);
      need(st.lookup.documents.has(op.doc), "pick a reference from the list, or create one");
      const kind = op.kind || "account";
      need(["account", "mention", "checklist"].includes(kind), "kind is account, mention or checklist");
      const fields = {};
      for (const f of ["pages", "name_printed", "areas", "islands", "status", "status_area", "first_record_year", "status_page"]) {
        if (op[f] != null && String(op[f]).trim() !== "") fields[f] = String(op[f]).trim();
      }
      const i = st.t.literature.findIndex(r => st.shownId(r.taxon_id) === op.id && r.doc_id === op.doc && r.kind === kind);
      if (i >= 0) {
        st.t.literature[i] = Object.assign({}, st.t.literature[i], fields, { review: "editor", reviewed_by: op.by, reviewed: op.date });
      } else {
        st.t.literature.push(Object.assign(blank("literature"), fields, { taxon_id: op.id, doc_id: op.doc, kind,
          method: "manual", review: "editor", reviewed_by: op.by, reviewed: op.date, added_by: op.by, added: op.date }));
      }
      st.stamp(op.id, op);
    },

    // --- review of what a tool wrote: confirm (review = editor) or reject (delete the row)
    review(st, op) {
      need(["literature", "notes", "hosts"].includes(op.table), "review literature, notes or hosts");
      let n = 0;
      st.t[op.table] = st.t[op.table].map(r => {
        if (st.shownId(r.taxon_id) !== op.id || (op.doc && r.doc_id !== op.doc) ||
            (op.kind && r.kind !== op.kind) || r.review !== "machine") return r;
        n++;
        const out = Object.assign({}, r, { review: "editor" });
        if ("reviewed_by" in r) Object.assign(out, { reviewed_by: op.by, reviewed: op.date });
        return out;
      });
      need(n, "nothing machine-made to review there");
      st.stamp(op.id, op);
    },
    // Confirm everything a tool read from one document (literature, notes, host plants, and
    // with op.nativity the nativity values it set), after the editor has spot-checked it.
    reviewDoc(st, op) {
      need(st.lookup.documents.has(op.doc), `no document ${op.doc}`);
      let n = 0;
      for (const table of ["literature", "notes", "hosts"]) {
        st.t[table] = st.t[table].map(r => {
          if (r.doc_id !== op.doc || r.review !== "machine") return r;
          n++;
          const out = Object.assign({}, r, { review: "editor" });
          if ("reviewed_by" in r) Object.assign(out, { reviewed_by: op.by, reviewed: op.date });
          return out;
        });
      }
      if (op.nativity) {
        for (const id of st.order) {
          const r = st.d.get(id);
          if (r.nativity_source === op.doc && r.nativity_review === "machine") {
            st.setCell(id, "nativity_review", "editor");
            st.stamp(id, op);
            n++;
          }
        }
      }
      need(n, "nothing machine-made from that document");
    },
    // Accept the direct children of a taxon as they are: clear a tool's `new` flag, confirm the
    // machine-read literature, notes and host rows and a machine-set nativity of each. Only the
    // children listed (all of them direct children of op.id); nothing underneath, no other field.
    acceptChildren(st, op) {
      const parent = accepted(st, op.id);
      const kids = new Set(op.children || []);
      need(kids.size, "no children chosen");
      for (const c of kids) need(st.r(c) && st.r(c).parent_id === op.id, `${st.name(c)} is not a direct child of ${parent.name}`);
      let n = 0;
      for (const c of kids) {
        const r = st.r(c);
        if (r.flag === "new") { st.setCell(c, "flag", ""); n++; }
        if (r.nativity !== "unknown" && r.nativity_review === "machine") { st.setCell(c, "nativity_review", "editor"); n++; }
        st.stamp(c, op);
      }
      for (const table of ["literature", "notes", "hosts"]) {
        st.t[table] = st.t[table].map(r => {
          if (r.review !== "machine" || !kids.has(st.shownId(r.taxon_id))) return r;
          n++;
          const out = Object.assign({}, r, { review: "editor" });
          if ("reviewed_by" in r) Object.assign(out, { reviewed_by: op.by, reviewed: op.date });
          return out;
        });
      }
      need(n, "nothing to accept: those children are already reviewed");
    },
    // Correct a literature row or a note a tool wrote; editing it confirms it.
    editLit(st, op) {
      const i = st.t.literature.findIndex(r => st.shownId(r.taxon_id) === op.id && r.doc_id === op.doc && r.kind === op.kind);
      need(i >= 0, "no such literature row");
      const fields = {};
      for (const f of ["pages", "name_printed", "areas", "islands", "status", "status_area", "first_record_year", "status_page"]) {
        if (op[f] != null) fields[f] = String(op[f]).trim();
      }
      st.t.literature[i] = Object.assign({}, st.t.literature[i], fields, { review: "editor", reviewed_by: op.by, reviewed: op.date });
      st.stamp(op.id, op);
    },
    editNote(st, op) {
      const i = st.t.notes.findIndex(r => st.shownId(r.taxon_id) === op.id && r.doc_id === op.doc && r.topic === op.topic);
      need(i >= 0, "no such note");
      const fields = {};
      for (const f of ["note", "pages"]) if (op[f] != null) fields[f] = String(op[f]).trim();
      if (op.newTopic && op.newTopic !== op.topic) {
        need(!st.t.notes.some(r => st.shownId(r.taxon_id) === op.id && r.doc_id === op.doc && r.topic === op.newTopic), "that taxon already has a note on that topic from this document");
        fields.topic = op.newTopic;
      }
      need(!("note" in fields) || fields.note, "a note cannot be empty");
      st.t.notes[i] = Object.assign({}, st.t.notes[i], fields, { review: "editor" });
      st.stamp(op.id, op);
    },
    reject(st, op) {
      need(["literature", "notes", "hosts"].includes(op.table), "reject literature, notes or hosts");
      const before = st.t[op.table].length;
      st.t[op.table] = st.t[op.table].filter(r => !(st.shownId(r.taxon_id) === op.id && (!op.doc || r.doc_id === op.doc) &&
        (!op.kind || r.kind === op.kind) && (!op.topic || r.topic === op.topic) && (!op.host || r.host === op.host)));
      need(st.t[op.table].length < before, "no such row");
      st.stamp(op.id, op);
    },
  };

  // A list cell typed in the table: the items added, changed and removed, as operations.
  function setList(st, op, r, col, value) {
    const before = splitList(r[col]), after = splitList(value);
    const sub = o => Object.assign({}, op, o);
    if (col === "distributionTags") {
      const old = new Map(before.map(x => { const t = parseTag(x); return [t.value, t]; }));
      const now = new Map(after.map(x => { const t = parseTag(x); return [t.value, t]; }));
      for (const [place] of old) if (!now.has(place)) OPS.untag(st, sub({ place }));
      for (const [place, t] of now) {
        const o = old.get(place);
        if (!o || o.status !== t.status || o.source !== t.source) OPS.tag(st, sub({ place, status: t.status, source: t.source }));
      }
    } else if (col === "associatedOccurrences") {
      const key = x => { const o = parseOccurrence(x); return o.kind + ":" + o.ref; };
      const old = new Set(before.map(key)), now = new Map(after.map(x => [key(x), x]));
      for (const x of before) if (!now.has(key(x))) OPS.unvoucher(st, sub({ url: x }));
      for (const [k, x] of now) if (!old.has(k)) OPS.voucher(st, sub({ url: x }));
    } else {
      const old = new Map(before.map(x => { const l = parseLink(x); return [l.value, l]; }));
      const now = new Map(after.map(x => { const l = parseLink(x); return [l.value, l]; }));
      for (const [url] of old) if (!now.has(url)) OPS.unlink(st, sub({ url }));
      for (const [url, l] of now) {
        const o = old.get(url);
        if (!o || o.note !== l.note) OPS.link(st, sub({ url, label: l.note }));
      }
    }
  }
  const LIST = new Set(["distributionTags", "associatedOccurrences", "associatedReferences"]);
  const origSet = OPS.set;
  OPS.set = function (st, op) {
    if (LIST.has(op.column)) {
      need(st.r(op.id), `no taxon ${op.id}`);
      const cur = currentList(st, op.id, op.column);
      return setList(st, op, { [op.column]: cur }, op.column, (op.value == null ? "" : String(op.value)).trim());
    }
    return origSet(st, op);
  };
  function currentList(st, id, col) {
    if (col === "distributionTags") return st.annFor(id, "distribution").map(formatTag).join(SEP);
    if (col === "associatedOccurrences") return st.occFor(id).map(occurrenceUrl).join(SEP);
    return st.annFor(id, "link").map(formatLink).join(SEP);
  }

  function replay(base, ops) {
    const st = new State(base);
    // A taxon added here gets a new IOG- id when its old one was taken meanwhile (someone
    // else committed an IOG-5 first): later operations follow it to the new id.
    const remap = new Map();
    for (const op of ops) {
      const fn = OPS[op.type];
      for (const f of ["id", "into", "parent", "doc", "source"]) if (remap.has(op[f])) op[f] = remap.get(op[f]);
      const before = op.newId;
      try {
        if (!fn) throw new Error(`unknown operation ${op.type}`);
        const snap = snapshot(st);                 // an operation that throws half way leaves nothing
        try { fn(st, op); op.error = null; } catch (e) { restore(st, snap); throw e; }
      } catch (e) {
        op.error = e.message;
      }
      if (before && op.newId && before !== op.newId) remap.set(before, op.newId);
    }
    st.finish();
    return st;
  }
  function snapshot(st) {
    return { d: new Map(st.d), order: st.order.slice(), t: Object.fromEntries(Object.entries(st.t).map(([k, v]) => [k, v.slice()])),
             changed: new Map([...st.changed].map(([k, v]) => [k, new Set(v)])), structural: st.structural,
             added: new Set(st.added), removed: new Set(st.removed), nextIog: st.nextIog,
             rows: new Map([...st.d].filter(([, r]) => st.own.has(r)).map(([k, r]) => [k, Object.assign({}, r)])) };
  }
  function restore(st, s) {
    Object.assign(st, { d: s.d, order: s.order, t: s.t, changed: s.changed, structural: s.structural,
                        added: s.added, removed: s.removed, nextIog: s.nextIog });
    for (const [k, vals] of s.rows) { const r = st.d.get(k); if (r) Object.assign(r, vals); }
    st._kids = null;
  }

  // ------------------------------------------------------------ checks before a commit
  // The same checks dataset.check makes on what the editor writes, so a commit never breaks
  // the rebuild: required cells, enums, kinds, references, unique keys, the tree.
  const KIND = {
    int: v => /^-?\d+$/.test(v), date: v => /^\d{4}-\d{2}-\d{2}$/.test(v), url: isUrl,
    bool: v => v === "yes" || v === "no", id: validId,
  };
  function check(st) {
    const errors = [], taxa = new Map(st.order.map(id => [id, st.d.get(id)]));
    const tables = Object.assign({ taxa: st.order.map(id => st.d.get(id)) }, st.t);
    for (const [name, rows] of Object.entries(tables)) {
      const t = T[name], seen = new Set();
      rows.forEach((r, i) => {
        const where = `${t.file} line ${i + 2}`;
        for (const [c, spec] of Object.entries(t.cols)) {
          const v = r[c] || "";
          if (v !== v.trim() || /\n/.test(v)) errors.push(`${where}: ${c} has stray whitespace or a newline`);
          if (!v) { if (spec.required) errors.push(`${where}: ${c} is required`); continue; }
          if (spec.enum.length) {
            const items = spec.kind === "list" ? splitList(v) : [v];
            for (const it of items) if (!spec.enum.includes(it)) errors.push(`${where}: ${c} ${JSON.stringify(it)} is not one of ${spec.enum.slice(0, 8).join(", ")}`);
          }
          if (KIND[spec.kind] && !KIND[spec.kind](v)) errors.push(`${where}: ${c} ${JSON.stringify(v)} is not a valid ${spec.kind}`);
          if (spec.maxlen && v.length > spec.maxlen) errors.push(`${where}: ${c} is ${v.length} characters (at most ${spec.maxlen})`);
          if (spec.ref === "taxa" && !taxa.has(v)) errors.push(`${where}: ${c} ${v} is not in the taxonomy`);
        }
        const key = t.key.map(c => r[c] || "").join("\u0001");
        if (seen.has(key)) errors.push(`${where}: duplicate key ${t.key.map(c => r[c] || "").join(" / ")}`);
        seen.add(key);
      });
    }
    const roots = [...taxa.values()].filter(r => r.status !== SYN && !r.parent_id);
    if (roots.length !== 1) errors.push(`taxa: expected one root, found ${roots.length}`);
    for (const r of taxa.values()) {
      const where = `${r.name} (${r.id})`;
      if (r.status === SYN) {
        const a = taxa.get(r.accepted_id);
        if (!r.accepted_id) errors.push(`${where}: a synonym needs accepted_id`);
        else if (a && a.status === SYN) errors.push(`${where}: accepted_id points at another synonym`);
        if (r.parent_id) errors.push(`${where}: a synonym has no parent`);
        continue;
      }
      if (r.accepted_id) errors.push(`${where}: only a synonym has accepted_id`);
      if (!r.nativity) errors.push(`${where}: no nativity`);
      const p = r.parent_id && taxa.get(r.parent_id);
      if (p) {
        if (p.status === SYN) errors.push(`${where}: its parent is a synonym`);
        else if (rankIdx(p.rank) >= rankIdx(r.rank)) errors.push(`${where}: rank ${r.rank} does not descend from ${p.rank}`);
      }
      const seen = new Set();
      for (let x = r; x && x.parent_id; x = taxa.get(x.parent_id)) {
        if (seen.has(x.id)) { errors.push(`${where}: a cycle in the tree`); break; }
        seen.add(x.id);
      }
    }
    for (const a of st.t.distribution) if (!PLACE.has(a.place)) errors.push(`distribution: ${a.place} is not a place`);
    for (const e of st.t.vouchers) if ((e.kind === "photo_file" || e.kind === "photo_url") && !S.licenses.includes(e.licence)) errors.push(`vouchers: a photo needs a licence`);
    return errors;
  }

  // ------------------------------------------------------------ the files to commit
  function files(st) {
    const B = st.base.tables, out = {};
    for (const name of S.editTables) {
      const rows = name === "taxa" ? st.order.map(id => st.d.get(id)) : st.t[name];
      const path = T[name].file, old = st.base.texts[path];
      if (old == null && !rows.length) continue;
      const text = CSV.writeTable(Object.assign({}, B[name], { rows: sortRows(name, rows) }));
      if (text !== (old == null ? "" : old)) out[path] = text;
    }
    return out;
  }

  // ------------------------------------------------------------ words for the change list
  function describe(op, st) {
    const n = id => (st && st.r(id) ? st.name(id) : id);
    const who = n(op.id || op.into);
    switch (op.type) {
      case "set": return `${who}: ${op.column} → "${op.value}"`;
      case "nativity": return `${who}: ${op.value}${op.source ? ` (${op.source})` : ""}`;
      case "confirmNativity": return `${who}: nativity confirmed`;
      case "move": return `${who}: moved under ${n(op.parent)}`;
      case "synonymize": return `${n(op.id)} merged into ${n(op.into)} (synonym)`;
      case "split": return `${who}: split out as its own taxon` + (op.parent ? ` under ${n(op.parent)}` : "");
      case "add": return `added ${op.status === "morphospecies" ? "morphospecies" : op.rank} ${op.name} under ${n(op.parent)}` + (op.newId ? ` (${op.newId})` : "");
      case "addName": return `${n(op.into)}: added the name ${op.name}${op.authorship ? " " + op.authorship : ""}`;
      case "hide": return `${who}: hidden (deleted from the site)`;
      case "unhide": return `${who}: shown again`;
      case "remove": return `deleted ${op.id}`;
      case "verify": return `${who}: ${op.on ? "confirmed" + (op.source ? ` (${op.source})` : "") : "confirmation removed"}`;
      case "clearFlag": return `${who}: reviewed (flag new cleared)`;
      case "tag": return `${who}: ${op.place} ${op.status || "present"}${op.doc ? ` (${op.doc})` : op.source ? ` (${op.source})` : ""}`;
      case "untag": return `${who}: removed the ${op.place} tag`;
      case "voucher": return `${who}: voucher ${op.url}`;
      case "unvoucher": return `${who}: removed voucher ${op.url}`;
      case "link": return `${who}: link ${op.label ? op.label + " " : ""}${op.url}`;
      case "unlink": return `${who}: removed link ${op.url}`;
      case "exclude": return `${op.id ? n(op.id) : op.name} excluded: ${op.reason}`;
      case "unexclude": return `${op.name}: no longer excluded`;
      case "placeSynonym": return `${op.unplacedName} merged into ${n(op.into)} as a synonym` + (op.newId ? ` (${op.newId})` : "");
      case "place": return `${op.name} placed under ${n(op.parent)}` + (op.newId ? ` (${op.newId})` : "");
      case "acceptChildren": return `${who}: ${(op.children || []).length} direct children accepted`;
      case "editLit": return `${who}: literature row from ${op.doc} corrected and confirmed`;
      case "editNote": return `${who}: note from ${op.doc} corrected and confirmed`;
      case "newDocument": return `new reference: ${op.authors ? op.authors + " " : ""}${op.year || ""} ${op.title}` + (op.newId ? ` (${op.newId})` : "");
      case "editDocument": return `reference ${op.doc} corrected`;
      case "removeDocument": return `reference ${op.doc} removed`;
      case "citeSource": return `${who}: cited ${op.doc}${op.pages ? ", p. " + op.pages : ""}`;
      case "reviewDoc": return `${op.doc}: every machine-read row confirmed${op.nativity ? " (and its nativity values)" : ""}`;
      case "review": return `${who}: ${op.table}${op.doc ? " from " + op.doc : ""} reviewed`;
      case "reject": return `${who}: ${op.table} row${op.doc ? " from " + op.doc : ""} rejected`;
      default: return op.type;
    }
  }

  function commitMessage(ops, st, author, extra) {
    const good = ops.filter(o => !o.error);
    const head = extra && extra.trim() ? extra.trim().split("\n")[0] :
      `Editor: ${good.length} change${good.length === 1 ? "" : "s"} by ${author}`;
    const body = good.slice(0, 200).map(o => "- " + describe(o, st));
    if (good.length > 200) body.push(`- … and ${good.length - 200} more`);
    const more = extra && extra.trim().split("\n").slice(1).join("\n").trim();
    return [head, "", ...(more ? [more, ""] : []), ...body, "", `Added-by: ${author}`].join("\n");
  }

  function op(type, fields, by) {
    return Object.assign({ type, by, date: today(), at: new Date().toISOString() }, fields);
  }

  // The view-row columns a person may edit in the table, and the dataset column each is.
  const EDITABLE_VIEW = {};
  for (const c of EDITABLE) { EDITABLE_VIEW[c] = c; EDITABLE_VIEW[BACK[c] || c] = c; }
  EDITABLE_VIEW.verificationStatus = "verified";
  EDITABLE_VIEW.parentNameUsage = "parent_id";

  window.IOGModel = {
    makeBase, replay, check, files, describe, commitMessage, op, sortRows, tid,
    validId, parseTaxonRef, parseTag, formatTag, parseOccurrence, occurrenceUrl, parseLink, formatLink,
    splitList, isUrl, PLACE, CONFIRMED, rankIndex: rankIdx, EDITABLE: EDITABLE_VIEW, LIST,
    LEGACY,
  };
})();
