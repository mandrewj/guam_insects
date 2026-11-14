// The editor's model: the files as loaded (the base) plus a list of operations (the edits),
// replayed in order to give the current state. Nothing here touches the page.
//
// Every operation writes what `resolve` reads (curation/taxa.csv, evidence.csv,
// annotations.csv: the same rules as curation.py and taxonomy.import_edits) and updates
// taxonomy.csv to match, so the table shows the edit at once. Computed columns (records,
// verification levels, literature) are refreshed by the rebuild after a commit.
(function () {
  "use strict";
  const S = window.IOG_SPEC;
  const CSV = window.IOGCSV;
  const CONFIRMED = S.levels[S.levels.length - 1];
  const RANK_ORDER = ["Subphylum", "Class", "Order", "Family", "Genus", "Subgenus", "Species",
                      "Subspecies", "Variety", "Form"];
  const PLACE = new Map(S.places.map(p => [p[0], { area: p[1], group: p[2] }]));
  const AREA_ORDER = S.areas.map(a => a.code);
  const ID_RE = /^([0-9A-Z]{1,7}|gbif:\d+|name-\d+|IOG-\d+)$/;
  const EDITABLE = S.editable;                 // taxonomy column -> curation/taxa.csv column
  const LIST = new Set(S.listColumns);
  const FILES = { taxonomy: "taxonomy.csv", taxa: "curation/taxa.csv",
                  evidence: "curation/evidence.csv", annotations: "curation/annotations.csv" };
  const COLUMNS_OF = { taxonomy: S.columns, taxa: S.taxaColumns, evidence: S.evidenceColumns,
                       annotations: S.annotationColumns };
  const CLASSIFICATION = { Class: "class", Order: "order", Family: "family", Genus: "genus" };

  const validId = s => ID_RE.test(s || "");
  const iogNum = s => { const m = /^IOG-(\d+)$/.exec(s || ""); return m ? +m[1] : 0; };
  const today = () => new Date().toISOString().slice(0, 10);
  const blank = cols => Object.fromEntries(cols.map(c => [c, ""]));
  const rankIndex = r => { const i = RANK_ORDER.indexOf(r); return i < 0 ? 99 : i; };
  const fold = s => (s || "").toLowerCase();

  // ------------------------------------------------------------ cell formats (taxonomy.py)
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
  const formatLink = a => a.note ? `${a.note} <${a.value}>` : a.value;
  function parseLink(text) {
    const t = text.trim();
    if (t.endsWith(">") && t.includes(" <")) {
      const i = t.lastIndexOf(" <");
      return { value: t.slice(i + 2, -1).trim(), note: t.slice(0, i).trim() };
    }
    return { value: t, note: "" };
  }
  const splitList = v => (v || "").split("|").map(x => x.trim()).filter(Boolean);
  const isUrl = v => /^https?:\/\/\S+$/.test(v || "");

  // ------------------------------------------------------------ the base (files as loaded)
  // texts: {path: text or null (absent)}; source: {kind, label, sha}
  function makeBase(texts, source) {
    const tables = {};
    for (const [key, path] of Object.entries(FILES)) {
      const text = texts[path];
      const t = CSV.readTable(text || "", COLUMNS_OF[key]);
      if (text == null || text === "") {        // a file not there yet: Python's defaults
        t.bom = false;
        t.eol = key === "taxonomy" ? "\n" : "\r\n";
      }
      if (key === "taxonomy") t.bom = true;
      // Columns in the order the Python code writes them, then any others the file had.
      t.columns = COLUMNS_OF[key].concat(t.columns.filter(c => !COLUMNS_OF[key].includes(c)));
      tables[key] = t;
    }
    return { texts, tables, source: source || { kind: "files", label: "files" } };
  }

  // ------------------------------------------------------------ state = base + operations
  class State {
    constructor(base) {
      this.base = base;
      const T = base.tables;
      this.byId = new Map();
      this.order = [];
      for (const r of T.taxonomy.rows) {
        if (!r.taxonID || this.byId.has(r.taxonID)) continue;
        this.byId.set(r.taxonID, r);
        this.order.push(r.taxonID);
      }
      this.cur = T.taxa.rows.slice();
      this.evidence = T.evidence.rows.slice();
      this.annotations = T.annotations.rows.slice();
      this.own = new Set();              // objects this state may change (copies)
      this.changed = new Map();          // taxonID -> Set of columns changed
      this.structural = false;
      this.touched = new Set();          // ids whose list cells are recomputed at the end
      this.added = new Set();            // taxonIDs added by an operation
      this.removed = new Set();
      this._kids = null;
      let max = 0;
      for (const id of this.order) max = Math.max(max, iogNum(id));
      for (const r of this.cur) max = Math.max(max, iogNum(r.taxon_id));
      this.nextIog = max + 1;
    }

    row(id) { return this.byId.get(id); }
    name(id) { const r = this.row(id); return r ? r.scientificName : id; }
    isSynonym(r) { return r && r.taxonomicStatus === "synonym"; }
    shownId(id) {
      const r = this.row(id);
      return r && this.isSynonym(r) && r.acceptedNameUsageID ? r.acceptedNameUsageID : id;
    }
    mrow(id) {                           // the row, copied before its first change
      let r = this.byId.get(id);
      if (!r) throw new Error(`no taxon ${id}`);
      if (!this.own.has(r)) { r = Object.assign({}, r); this.own.add(r); this.byId.set(id, r); }
      return r;
    }
    setCell(id, col, value) {
      const r = this.mrow(id);
      if (r[col] === value) return;
      r[col] = value;
      if (!this.changed.has(id)) this.changed.set(id, new Set());
      this.changed.get(id).add(col);
    }
    kids() {                             // parent id -> accepted child ids
      if (!this._kids) {
        this._kids = new Map();
        for (const id of this.order) {
          const r = this.byId.get(id);
          if (this.isSynonym(r) || !r.parentNameUsageID) continue;
          if (!this._kids.has(r.parentNameUsageID)) this._kids.set(r.parentNameUsageID, []);
          this._kids.get(r.parentNameUsageID).push(id);
        }
      }
      return this._kids;
    }
    children(id) { return this.kids().get(id) || []; }
    synonymsOf(id) {
      return this.order.filter(x => { const r = this.byId.get(x); return this.isSynonym(r) && r.acceptedNameUsageID === id; });
    }
    descendants(id) {
      const out = [], stack = [id];
      while (stack.length) {
        for (const c of this.children(stack.pop())) { out.push(c); stack.push(c); }
      }
      return out;
    }
    isUnder(id, ancestor) {              // is `id` at or below `ancestor`?
      const seen = new Set();
      for (let x = id; x && !seen.has(x); x = (this.row(x) || {}).parentNameUsageID) {
        if (x === ancestor) return true;
        seen.add(x);
      }
      return false;
    }
    lineage(id) {
      const out = [], seen = new Set();
      for (let x = (this.row(id) || {}).parentNameUsageID; x && !seen.has(x); x = (this.row(x) || {}).parentNameUsageID) {
        seen.add(x); out.unshift(x);
      }
      return out;
    }
    structure() { this.structural = true; this._kids = null; }

    // curation/taxa.csv rows ---------------------------------------------------------
    curRow(id, create) {
      let i = this.cur.findIndex(r => r.taxon_id === id);
      if (i < 0) {
        if (!create) return null;
        this.cur.push(Object.assign(blank(this.base.tables.taxa.columns), { taxon_id: id }));
        i = this.cur.length - 1;
        this.own.add(this.cur[i]);
      } else if (!this.own.has(this.cur[i])) {
        this.cur[i] = Object.assign({}, this.cur[i]);
        this.own.add(this.cur[i]);
      }
      return this.cur[i];
    }
    curate(id, fields, op) {
      const r = this.curRow(id, true);
      Object.assign(r, fields, { editor: op.by, edited: op.date });
      if (op.reason) r.reason = op.reason;
      // A source taxon's row with nothing left to override goes (as curation.upsert does).
      const overrides = S.overrideFields.concat(["parent_name"]);
      if (!/^IOG-/.test(id) && !overrides.some(f => r[f])) this.cur.splice(this.cur.indexOf(r), 1);
      const shown = this.shownId(id);
      if (this.row(shown)) {
        const cf = new Set((this.row(shown).curatedFields || "").split(",").filter(Boolean));
        for (const f of Object.keys(fields)) if (S.overrideFields.includes(f) && fields[f] !== "") cf.add(f);
        this.setCell(shown, "curatedFields", [...cf].join(","));
      }
      this.stamp(id, op);
    }
    stamp(id, op) {
      if (!this.row(id) || this.removed.has(id)) return;
      this.setCell(id, "modifiedBy", op.by);
      this.setCell(id, "modified", op.date);
    }
    newId() { return "IOG-" + this.nextIog++; }

    // annotations and evidence for a displayed taxon --------------------------------------
    annFor(id, kind) {
      return this.annotations.filter(a => a.kind === kind && this.shownId(a.taxon_id) === id);
    }
    occFor(id) {
      return this.evidence.filter(e => occurrenceUrl(e) && this.shownId(e.taxon_id) === id);
    }
    listsChanged(id, op) {               // a tag, voucher or link was added or removed
      this.touched.add(id);
      this.recomputeLists(id);
      this.stamp(id, op);
    }
    recomputeLists(id) {
      if (!this.row(id) || this.isSynonym(this.row(id))) return;
      this.setCell(id, "distributionTags", this.annFor(id, "distribution").map(formatTag).join(S.sep));
      this.setCell(id, "associatedReferences", this.annFor(id, "link").map(formatLink).join(S.sep));
      this.setCell(id, "associatedOccurrences", this.occFor(id).map(occurrenceUrl).join(S.sep));
    }

    // ------------------------------------------------------------ at the end of a replay
    finish() {
      if (this.structural) this.reorder();
      for (const id of this.touched) {
        this.recomputeLists(id);
        const r = this.row(id);
        if (!r || this.isSynonym(r)) continue;
        const present = new Set(this.annFor(id, "distribution").filter(a => (a.status || "present") === "present")
          .map(a => PLACE.get(a.value).area));
        if (present.size) {
          const areas = new Set(splitList(r.recordedIn).concat([...present]));
          this.setCell(id, "recordedIn", AREA_ORDER.filter(a => areas.has(a)).join(S.sep));
        }
      }
      this.rows = this.order.map(id => this.byId.get(id));
    }
    reorder() {
      this._kids = null;
      const kids = this.kids(), syn = new Map(), roots = [];
      for (const id of this.order) {
        const r = this.byId.get(id);
        if (this.isSynonym(r)) {
          const a = r.acceptedNameUsageID;
          if (!syn.has(a)) syn.set(a, []);
          syn.get(a).push(id);
        } else if (!r.parentNameUsageID || !this.byId.has(r.parentNameUsageID)) roots.push(id);
      }
      const byName = (a, b) => { const x = fold(this.name(a)), y = fold(this.name(b)); return x < y ? -1 : x > y ? 1 : 0; };
      const out = [], seen = new Set();
      const visit = (id, cls) => {
        if (seen.has(id)) return;
        seen.add(id);
        out.push(id);
        const r = this.byId.get(id);
        const mine = Object.assign({}, cls);
        if (CLASSIFICATION[r.taxonRank]) mine[CLASSIFICATION[r.taxonRank]] = r.scientificName;
        this.classify(id, mine);
        const p = r.parentNameUsageID ? this.byId.get(r.parentNameUsageID) : null;
        if (p && r.parentNameUsage !== p.scientificName) this.setCell(id, "parentNameUsage", p.scientificName);
        // Other names by name, as resolve writes them (taxon_names ORDER BY name).
        const names = (syn.get(id) || []).slice().sort((x, y) => {
          const p = this.name(x), q = this.name(y); return p < q ? -1 : p > q ? 1 : 0; });
        for (const s of names) {
          seen.add(s); out.push(s);
          this.classify(s, mine);
          if (this.row(s).acceptedNameUsage !== r.scientificName) this.setCell(s, "acceptedNameUsage", r.scientificName);
        }
        for (const c of (kids.get(id) || []).slice().sort(byName)) visit(c, mine);
      };
      for (const id of roots) visit(id, {});
      for (const id of this.order) if (!seen.has(id)) out.push(id);   // orphans (shown last)
      this.order = out;
    }
    classify(id, cls) {
      const r = this.byId.get(id);
      const ranked = rankIndex(r.taxonRank);
      for (const [rank, col] of Object.entries(CLASSIFICATION)) {
        // A column names the taxon of that rank above (or at) this one; below family the
        // family is always filled (taxonomy.py), so an empty value means none in the chain.
        const want = rankIndex(rank) <= ranked ? (cls[col] || "") : "";
        if ((r[col] || "") !== want) {
          if (col === "family" && r.family !== want) {
            if (r.subfamily) this.setCell(id, "subfamily", "");
            if (r.tribe) this.setCell(id, "tribe", "");
          }
          this.setCell(id, col, want);
        }
      }
    }
  }

  // ------------------------------------------------------------ operations
  // Each: (state, op) -> void; throws Error with a message for the user when it cannot apply.
  const need = (cond, msg) => { if (!cond) throw new Error(msg); };
  function accepted(st, id, what) {
    const r = st.row(id);
    need(r, `${what || "taxon"} ${id} is not in the taxonomy`);
    need(!st.isSynonym(r), `${r.scientificName} (${id}) is a synonym: work on ${st.name(r.acceptedNameUsageID)} instead`);
    return r;
  }
  function checkParent(st, id, parentId, rank) {
    const p = accepted(st, parentId, "parent");
    need(!id || !st.isUnder(parentId, id), `${st.name(parentId)} is under ${st.name(id)}: that would be a cycle`);
    need(rankIndex(p.taxonRank) < rankIndex(rank),
         `a ${rank} cannot go under a ${p.taxonRank} (${p.scientificName})`);
    return p;
  }

  const OPS = {
    set(st, op) {
      const col = op.column, v = (op.value == null ? "" : String(op.value)).trim();
      const r = st.row(op.id);
      need(r, `no taxon ${op.id}`);
      if (LIST.has(col)) return setList(st, op, r, col, v);
      need(col in EDITABLE, `${col} is computed from the sources and cannot be edited`);
      if (col === "parentNameUsageID") return OPS.move(st, Object.assign({}, op, { parent: v }));
      if (col === "parentNameUsage") {
        const hits = st.order.filter(x => { const y = st.row(x); return !st.isSynonym(y) && y.scientificName === v; });
        need(hits.length === 1, `${hits.length} taxa are named "${v}": pick the parent by id`);
        return OPS.move(st, Object.assign({}, op, { parent: hits[0] }));
      }
      if (col === "acceptedNameUsageID") {
        if (!v) return OPS.split(st, op);
        return OPS.synonymize(st, Object.assign({}, op, { into: v }));
      }
      if (col === "taxonomicStatus") {
        need(S.statuses.includes(v), `status must be one of ${S.statuses.join(", ")}`);
        if (v === "synonym") { need(st.isSynonym(r), "use Synonymize (or acceptedNameUsageID) to merge a taxon into another"); return; }
        if (st.isSynonym(r)) return OPS.split(st, op);
        st.curate(op.id, { status: v === "accepted" ? "" : v }, op);
        st.setCell(op.id, "taxonomicStatus", v);
        return;
      }
      if (col === "hidden") return v === "1" ? OPS.hide(st, op) : OPS.unhide(st, op);
      if (col === "verificationStatus") {
        need(S.levels.includes(v), `verificationStatus must be one of ${S.levels.join(", ")}`);
        if (v === CONFIRMED) return OPS.verify(st, Object.assign({}, op, { on: true }));
        need(r.verificationStatus === CONFIRMED, "only 'editor confirmed' can be set by hand; the other levels follow from the sources");
        return OPS.verify(st, Object.assign({}, op, { on: false }));
      }
      // A merged name's row overrides the taxon it is shown as (tree.py), so a synonym's own
      // cells are not edited: split it out first.
      need(!st.isSynonym(r), `${r.scientificName} is a synonym of ${st.name(r.acceptedNameUsageID)}: ` +
           "edit that taxon, or split this name out first");
      if (col === "taxonRank") {
        need(S.ranks.includes(v), `rank must be one of ${S.ranks.join(", ")}`);
        const p = r.parentNameUsageID && st.row(r.parentNameUsageID);
        need(!p || rankIndex(p.taxonRank) < rankIndex(v), `a ${v} cannot be under a ${p && p.taxonRank}`);
        need(st.children(op.id).every(c => rankIndex(st.row(c).taxonRank) > rankIndex(v)),
             `taxa under ${r.scientificName} would rank at or above it`);
      }
      if (col === "establishmentMeans") need(!v || S.establishment.includes(v), `establishment must be one of ${S.establishment.join(", ")}`);
      if (col === "scientificName" || col === "taxonRank") need(v || !/^IOG-/.test(op.id), "a taxon added here needs a name and a rank");
      st.curate(op.id, { [EDITABLE[col]]: v }, op);
      st.setCell(op.id, col, v);
      if (col === "scientificName" || col === "taxonRank") st.structure();
    },

    move(st, op) {
      const r = accepted(st, op.id);
      need(op.parent, "choose the parent");
      checkParent(st, op.id, op.parent, r.taxonRank);
      if (r.parentNameUsageID === op.parent) return;
      st.curate(op.id, { parent_id: op.parent, parent_name: "" }, op);
      st.setCell(op.id, "parentNameUsageID", op.parent);
      st.setCell(op.id, "parentNameUsage", st.name(op.parent));
      st.structure();
    },

    synonymize(st, op) {
      const r = accepted(st, op.id), into = accepted(st, op.into, "accepted taxon");
      need(op.id !== op.into, "a taxon cannot be a synonym of itself");
      need(r.taxonRank === into.taxonRank, `${r.scientificName} is a ${r.taxonRank}, ${into.scientificName} a ${into.taxonRank}: merge taxa of the same rank`);
      need(!st.isUnder(op.into, op.id), `${into.scientificName} is under ${r.scientificName}`);
      st.curate(op.id, { status: "synonym", accepted_id: op.into }, op);
      st.setCell(op.id, "taxonomicStatus", "synonym");
      st.setCell(op.id, "acceptedNameUsageID", op.into);
      st.setCell(op.id, "acceptedNameUsage", into.scientificName);
      st.setCell(op.id, "parentNameUsageID", "");
      st.setCell(op.id, "parentNameUsage", "");
      st.setCell(op.id, "nameMatch", "curated merge");
      if (op.reason) st.setCell(op.id, "matchRemarks", op.reason);
      for (const s of st.synonymsOf(op.id)) {           // its own other names follow it
        st.setCell(s, "acceptedNameUsageID", op.into);
        st.setCell(s, "acceptedNameUsage", into.scientificName);
      }
      for (const c of st.children(op.id)) {             // resolve moves them the same way
        st.setCell(c, "parentNameUsageID", op.into);
        st.setCell(c, "parentNameUsage", into.scientificName);
      }
      st.touched.add(op.id); st.touched.add(op.into);
      st.stamp(op.into, op);
      st.structure();
    },

    split(st, op) {
      const r = st.row(op.id);
      need(r && st.isSynonym(r), `${st.name(op.id)} is not a synonym`);
      const acc = st.row(r.acceptedNameUsageID);
      const parent = op.parent || (acc && acc.parentNameUsageID) || "";
      const cur = st.curRow(op.id, false);
      const kind = /^IOG-/.test(op.id) ? "curated" : /^(gbif:|name-)/.test(op.id) ? "source" : "col";
      if (kind === "col" && cur && cur.status === "synonym") {
        st.curate(op.id, Object.assign({ status: "", accepted_id: "" }, op.parent ? { parent_id: op.parent } : {}), op);
      } else {
        need(kind !== "col", `${r.scientificName} is a Catalogue of Life synonym; it cannot be split here`);
        need(parent, "choose the parent it goes under");
        checkParent(st, op.id, parent, r.taxonRank || (acc && acc.taxonRank));
        st.curate(op.id, { status: "accepted", accepted_id: "", parent_id: parent }, op);
      }
      st.setCell(op.id, "taxonomicStatus", "accepted");
      st.setCell(op.id, "acceptedNameUsageID", "");
      st.setCell(op.id, "acceptedNameUsage", "");
      if (parent) {
        st.setCell(op.id, "parentNameUsageID", parent);
        st.setCell(op.id, "parentNameUsage", st.name(parent));
      }
      st.setCell(op.id, "nameMatch", "curated split");
      if (acc) { st.touched.add(acc.taxonID); st.stamp(acc.taxonID, op); }
      st.touched.add(op.id);
      st.structure();
    },

    add(st, op) {
      const name = (op.name || "").trim();
      need(name, "a new taxon needs a name");
      need(S.ranks.includes(op.rank), `rank must be one of ${S.ranks.join(", ")}`);
      const status = op.status || "accepted";
      need(status === "accepted" || status === "morphospecies" || status === "doubtful", "a new taxon is accepted, doubtful or a morphospecies");
      const p = checkParent(st, null, op.parent, op.rank);
      need(!st.children(op.parent).some(c => st.name(c) === name), `${p.scientificName} already has ${name}`);
      const id = op.newId && !st.byId.has(op.newId) && !st.curRow(op.newId, false) ? op.newId : st.newId();
      op.newId = id;
      st.nextIog = Math.max(st.nextIog, iogNum(id) + 1);
      st.curate(id, { rank: op.rank, name, authorship: op.authorship || "", parent_id: op.parent,
                      status, common_name: op.common || "", note: op.note || "" }, op);
      const r = Object.assign(blank(st.base.tables.taxonomy.columns), {
        taxonID: id, parentNameUsageID: op.parent, parentNameUsage: p.scientificName,
        scientificName: name, scientificNameAuthorship: op.authorship || "", taxonRank: op.rank,
        taxonomicStatus: status, vernacularName: op.common || "", kingdom: "Animalia",
        phylum: "Arthropoda", inCatalogueOfLife: "no", verificationStatus: "unconfirmed",
        literatureRecords: "0", specimenRecords: "0", gbifRecords: "0", inatObservations: "0",
        nameAccordingTo: "Insects of Guam curator", taxonRemarks: op.note || "", hidden: "0",
        curatedFields: "", modifiedBy: op.by, modified: op.date });
      st.own.add(r);
      st.byId.set(id, r);
      st.order.push(id);
      st.added.add(id);
      st.changed.set(id, new Set(["*"]));
      st.structure();
    },

    addName(st, op) {
      const acc = accepted(st, op.into, "accepted taxon");
      const name = (op.name || "").trim();
      need(name, "the name is empty");
      need(![op.into].concat(st.synonymsOf(op.into)).some(x => st.name(x) === name && (st.row(x).scientificNameAuthorship || "") === (op.authorship || "")),
           `${name} is already a name of ${acc.scientificName}`);
      const id = op.newId && !st.byId.has(op.newId) && !st.curRow(op.newId, false) ? op.newId : st.newId();
      op.newId = id;
      st.nextIog = Math.max(st.nextIog, iogNum(id) + 1);
      st.curate(id, { rank: acc.taxonRank, name, authorship: op.authorship || "", status: "synonym",
                      accepted_id: op.into }, op);
      const r = Object.assign(blank(st.base.tables.taxonomy.columns), {
        taxonID: id, acceptedNameUsageID: op.into, acceptedNameUsage: acc.scientificName,
        scientificName: name, scientificNameAuthorship: op.authorship || "", taxonRank: acc.taxonRank,
        taxonomicStatus: "synonym", inCatalogueOfLife: "no", nameMatch: "curated merge",
        matchRemarks: op.reason || "", hidden: acc.hidden || "0", modifiedBy: op.by, modified: op.date });
      st.own.add(r);
      st.byId.set(id, r);
      st.order.push(id);
      st.added.add(id);
      st.changed.set(id, new Set(["*"]));
      st.stamp(op.into, op);
      st.structure();
    },

    hide(st, op) {
      accepted(st, op.id);
      st.curate(op.id, { hidden: "1" }, op);
      for (const x of [op.id].concat(st.descendants(op.id))) {
        st.setCell(x, "hidden", "1");
        for (const s of st.synonymsOf(x)) st.setCell(s, "hidden", "1");
      }
    },
    unhide(st, op) {
      accepted(st, op.id);
      st.curate(op.id, { hidden: "" }, op);
      for (const x of [op.id].concat(st.descendants(op.id))) {
        const own = st.curRow(x, false);
        if (x !== op.id && own && own.hidden === "1") continue;
        st.setCell(x, "hidden", "0");
        for (const s of st.synonymsOf(x)) st.setCell(s, "hidden", "0");
      }
    },
    // Delete for good: only a taxon added here (IOG-), with nothing under it.
    remove(st, op) {
      const r = st.row(op.id);
      need(r && /^IOG-/.test(op.id), "only a taxon added in this editor (IOG-) can be deleted; hide others");
      need(!st.children(op.id).length, `${r.scientificName} has taxa under it: move or delete them first`);
      const gone = new Set([op.id].concat(st.synonymsOf(op.id).filter(s => /^IOG-/.test(s))));
      st.cur = st.cur.filter(c => !gone.has(c.taxon_id));
      st.evidence = st.evidence.filter(e => !gone.has(e.taxon_id));
      st.annotations = st.annotations.filter(a => !gone.has(a.taxon_id));
      for (const s of st.synonymsOf(op.id)) if (!gone.has(s)) {     // source names it held
        st.setCell(s, "acceptedNameUsageID", r.parentNameUsageID);
      }
      for (const x of gone) { st.byId.delete(x); st.removed.add(x); }
      st.order = st.order.filter(x => !gone.has(x));
      if (r.acceptedNameUsageID) { st.touched.add(r.acceptedNameUsageID); st.stamp(r.acceptedNameUsageID, op); }
      st.structure();
    },

    verify(st, op) {
      const r = accepted(st, op.id);
      st.curate(op.id, op.on ? { verified: "1", citation: op.source || "" } : { verified: "", citation: "" }, op);
      st.setCell(op.id, "verificationStatus", op.on ? CONFIRMED : (r.verificationStatus === CONFIRMED ? "unconfirmed" : r.verificationStatus));
      st.setCell(op.id, "verificationSource", op.on ? (op.source || "") : "");
      st.setCell(op.id, "verifiedBy", op.on ? op.by : "");
      st.setCell(op.id, "verifiedDate", op.on ? op.date : "");
    },

    tag(st, op) {
      accepted(st, op.id);
      need(PLACE.has(op.place), `"${op.place}" is not a place on the list`);
      const status = op.status || "present";
      need(S.distributionStatus.includes(status), `status must be one of ${S.distributionStatus.join(", ")}`);
      const have = st.annFor(op.id, "distribution").find(a => a.value === op.place);
      const fields = { status, source: (op.source || "").trim(), note: (op.note || "").trim(), added_by: op.by, added: op.date };
      if (have) {
        const i = st.annotations.indexOf(have);
        st.annotations[i] = Object.assign({}, have, fields);
      } else {
        st.annotations.push(Object.assign(blank(st.base.tables.annotations.columns),
          { taxon_id: op.id, kind: "distribution", value: op.place }, fields));
      }
      st.listsChanged(op.id, op);
    },
    untag(st, op) {
      const before = st.annotations.length;
      st.annotations = st.annotations.filter(a => !(a.kind === "distribution" && a.value === op.place && st.shownId(a.taxon_id) === op.id));
      need(st.annotations.length < before, `${st.name(op.id)} has no tag for ${op.place}`);
      st.listsChanged(op.id, op);
    },
    voucher(st, op) {
      accepted(st, op.id);
      const { kind, ref } = parseOccurrence(op.url || "");
      need(!st.evidence.some(e => e.kind === kind && e.ref === ref && st.shownId(e.taxon_id) === op.id), "that record is already a voucher here");
      const other = st.evidence.find(e => e.kind === kind && e.ref === ref);
      need(!other, `that record is already a voucher for ${other && st.name(st.shownId(other.taxon_id))}`);
      st.evidence.push(Object.assign(blank(st.base.tables.evidence.columns),
        { taxon_id: op.id, kind, ref, note: (op.note || "").trim(), editor: op.by, edited: op.date }));
      st.listsChanged(op.id, op);
    },
    unvoucher(st, op) {
      const { kind, ref } = parseOccurrence(op.url || "");
      const before = st.evidence.length;
      st.evidence = st.evidence.filter(e => !(e.kind === kind && e.ref === ref && st.shownId(e.taxon_id) === op.id));
      need(st.evidence.length < before, "no such voucher");
      st.listsChanged(op.id, op);
    },
    link(st, op) {
      accepted(st, op.id);
      const url = (op.url || "").trim();
      need(isUrl(url), `a link needs a URL (https://...), not "${url}"`);
      const have = st.annFor(op.id, "link").find(a => a.value === url);
      const fields = { note: (op.label || "").trim(), added_by: op.by, added: op.date };
      if (have) st.annotations[st.annotations.indexOf(have)] = Object.assign({}, have, fields);
      else st.annotations.push(Object.assign(blank(st.base.tables.annotations.columns), { taxon_id: op.id, kind: "link", value: url }, fields));
      st.listsChanged(op.id, op);
    },
    unlink(st, op) {
      const before = st.annotations.length;
      st.annotations = st.annotations.filter(a => !(a.kind === "link" && a.value === op.url && st.shownId(a.taxon_id) === op.id));
      need(st.annotations.length < before, "no such link");
      st.listsChanged(op.id, op);
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

  function replay(base, ops) {
    const st = new State(base);
    // A taxon added here gets a new IOG- id when its old one was taken meanwhile (someone
    // else committed an IOG-5 first): later operations follow it to the new id.
    const remap = new Map();
    for (const op of ops) {
      const fn = OPS[op.type];
      for (const f of ["id", "into", "parent"]) if (remap.has(op[f])) op[f] = remap.get(op[f]);
      const before = op.newId;
      try {
        if (!fn) throw new Error(`unknown operation ${op.type}`);
        // An operation that throws half way must leave nothing behind.
        const snap = snapshot(st);
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
    return { byId: new Map(st.byId), order: st.order.slice(), cur: st.cur.slice(),
             evidence: st.evidence.slice(), annotations: st.annotations.slice(),
             changed: new Map([...st.changed].map(([k, v]) => [k, new Set(v)])),
             structural: st.structural, touched: new Set(st.touched), added: new Set(st.added),
             removed: new Set(st.removed), nextIog: st.nextIog,
             // rows changed in place by this op: keep their values
             rows: new Map([...st.byId].filter(([, r]) => st.own.has(r)).map(([k, r]) => [k, Object.assign({}, r)])),
             curRows: st.cur.filter(r => st.own.has(r)).map(r => [r, Object.assign({}, r)]) };
  }
  function restore(st, s) {
    Object.assign(st, { byId: s.byId, order: s.order, cur: s.cur, evidence: s.evidence,
                        annotations: s.annotations, changed: s.changed, structural: s.structural,
                        touched: s.touched, added: s.added, removed: s.removed, nextIog: s.nextIog });
    for (const [k, vals] of s.rows) { const r = st.byId.get(k); if (r) Object.assign(r, vals); }
    for (const [r, vals] of s.curRows) Object.assign(r, vals);
    st._kids = null;
  }

  // ------------------------------------------------------------ checks before a commit
  // The same checks curation.load makes, so a commit never breaks the rebuild on them.
  function check(st) {
    const errors = [], seen = new Set();
    st.cur.forEach((r, i) => {
      const where = `curation/taxa.csv line ${i + 2}`;
      if (!r.taxon_id) { if (!(r.name && r.rank)) errors.push(`${where}: a new taxon needs a name and a rank`); return; }
      if (!validId(r.taxon_id)) errors.push(`${where}: ${r.taxon_id} is not an id`);
      if (seen.has(r.taxon_id)) errors.push(`${where}: ${r.taxon_id} appears twice`);
      seen.add(r.taxon_id);
      if (/^IOG-/.test(r.taxon_id) && !(r.name && r.rank)) errors.push(`${where}: ${r.taxon_id} needs a name and a rank`);
      if (r.rank && !S.ranks.includes(r.rank)) errors.push(`${where}: rank ${r.rank}`);
      if (r.status && !S.statuses.includes(r.status)) errors.push(`${where}: status ${r.status}`);
      if (r.status === "synonym" && !r.accepted_id) errors.push(`${where}: a synonym needs accepted_id`);
      if (r.establishment && !S.establishment.includes(r.establishment)) errors.push(`${where}: establishment ${r.establishment}`);
      for (const f of ["hidden", "verified"]) if (r[f] && r[f] !== "0" && r[f] !== "1") errors.push(`${where}: ${f} must be 0 or 1`);
      for (const f of ["parent_id", "accepted_id"]) if (r[f] && !validId(r[f])) errors.push(`${where}: ${f} ${r[f]} is not an id`);
      for (const f of ["parent_id", "accepted_id"]) if (r[f] && !st.row(r[f])) errors.push(`${where}: ${f} ${r[f]} is not in the taxonomy`);
    });
    st.evidence.forEach((e, i) => {
      const where = `curation/evidence.csv line ${i + 2}`;
      if (!validId(e.taxon_id)) errors.push(`${where}: ${e.taxon_id} is not an id`);
      if (!S.evidenceKinds.includes(e.kind)) errors.push(`${where}: kind ${e.kind}`);
      if (!e.ref) errors.push(`${where}: ref is empty`);
      if ((e.kind === "photo_file" || e.kind === "photo_url") && !S.licenses.includes(e.license)) errors.push(`${where}: a photo needs a licence`);
      if ((e.kind === "inat_observation" || e.kind === "gbif_occurrence") && !/^\d+$/.test(e.ref)) errors.push(`${where}: ref must be the record's number`);
      if (!st.row(st.shownId(e.taxon_id))) errors.push(`${where}: ${e.taxon_id} is not in the taxonomy`);
    });
    const ann = new Set();
    st.annotations.forEach((a, i) => {
      const where = `curation/annotations.csv line ${i + 2}`;
      if (!validId(a.taxon_id)) errors.push(`${where}: ${a.taxon_id} is not an id`);
      if (a.kind === "distribution") {
        if (!PLACE.has(a.value)) errors.push(`${where}: ${a.value} is not a place on the list`);
        if (!S.distributionStatus.includes(a.status)) errors.push(`${where}: status ${a.status}`);
      } else if (a.kind === "link") {
        if (!isUrl(a.value)) errors.push(`${where}: a link needs a URL`);
      } else errors.push(`${where}: kind ${a.kind}`);
      if (!a.added_by) errors.push(`${where}: added_by is empty`);
      const k = a.taxon_id + "|" + a.kind + "|" + a.value;
      if (ann.has(k)) errors.push(`${where}: ${a.kind} ${a.value} twice`);
      ann.add(k);
      if (!st.row(st.shownId(a.taxon_id))) errors.push(`${where}: ${a.taxon_id} is not in the taxonomy`);
    });
    return errors;
  }

  // ------------------------------------------------------------ the files to commit
  function files(st) {
    const T = st.base.tables, out = {};
    const tables = {
      taxonomy: Object.assign({}, T.taxonomy, { rows: st.rows }),
      taxa: Object.assign({}, T.taxa, { rows: st.cur }),
      evidence: Object.assign({}, T.evidence, { rows: st.evidence }),
      annotations: Object.assign({}, T.annotations, { rows: st.annotations }),
    };
    for (const [key, path] of Object.entries(FILES)) {
      const old = st.base.texts[path];
      if (old == null && !tables[key].rows.length) continue;     // still absent, still empty
      const text = CSV.writeTable(tables[key]);
      if (text !== (old == null ? "" : old)) out[path] = text;
    }
    return out;
  }

  // ------------------------------------------------------------ words for the change list
  function describe(op, st) {
    const n = id => (st && st.row(id) ? st.name(id) : id);
    const who = n(op.id || op.into);
    switch (op.type) {
      case "set": return `${who}: ${op.column} → "${op.value}"`;
      case "move": return `${who}: moved under ${n(op.parent)}`;
      case "synonymize": return `${n(op.id)} merged into ${n(op.into)} (synonym)`;
      case "split": return `${who}: split out as its own taxon` + (op.parent ? ` under ${n(op.parent)}` : "");
      case "add": return `added ${op.status === "morphospecies" ? "morphospecies" : op.rank} ${op.name} under ${n(op.parent)}` + (op.newId ? ` (${op.newId})` : "");
      case "addName": return `${n(op.into)}: added the name ${op.name}${op.authorship ? " " + op.authorship : ""}`;
      case "hide": return `${who}: hidden (deleted from the site)`;
      case "unhide": return `${who}: shown again`;
      case "remove": return `deleted ${op.id}`;
      case "verify": return `${who}: ${op.on ? "confirmed" + (op.source ? ` (${op.source})` : "") : "confirmation removed"}`;
      case "tag": return `${who}: ${op.place} ${op.status || "present"}${op.source ? ` (${op.source})` : ""}`;
      case "untag": return `${who}: removed the ${op.place} tag`;
      case "voucher": return `${who}: voucher ${op.url}`;
      case "unvoucher": return `${who}: removed voucher ${op.url}`;
      case "link": return `${who}: link ${op.label ? op.label + " " : ""}${op.url}`;
      case "unlink": return `${who}: removed link ${op.url}`;
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

  window.IOGModel = {
    makeBase, replay, check, files, describe, commitMessage, op, FILES,
    validId, parseTag, formatTag, parseOccurrence, occurrenceUrl, parseLink, formatLink,
    splitList, isUrl, PLACE, RANK_ORDER, CONFIRMED, rankIndex, EDITABLE, LIST,
  };
})();
