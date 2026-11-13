/* Curation admin: talks to the local server's /api (src/guaminsects/server.py). Every save
 * is validated against the whole tree on the server; errors come back as a list. */
(function () {
  "use strict";
  var RANKS = ["Subphylum", "Class", "Order", "Family", "Genus", "Species", "Subspecies"];
  var FIELDS = [["name", "Name"], ["rank", "Rank"], ["authorship", "Authorship"], ["parent_id", "Parent id (e.g. KVC9L)"],
    ["status", "Status"], ["accepted_id", "Merge into id (status synonym)"], ["common_name", "Common name"],
    ["establishment", "Establishment"], ["hidden", "Hidden (1 hides it and all below)"],
    ["verified", "Editor confirmed (1: you confirm it is in Micronesia)"], ["note", "Note"]];
  var CHOICES = { status: ["", "accepted", "synonym", "doubtful", "morphospecies"],
    establishment: ["", "native", "endemic", "introduced", "invasive", "unknown"],
    hidden: ["", "0", "1"], verified: ["", "0", "1"], rank: [""].concat(RANKS) };
  var KINDS = [["inat_observation", "iNaturalist observation id"], ["gbif_occurrence", "GBIF occurrence key"],
    ["photo_file", "Photo file in data/curated_photos/"], ["photo_url", "Photo URL"]];
  var LICENSES = ["", "cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"];
  var $ = function (s, el) { return (el || document).querySelector(s); };
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function api(path, body) {
    return fetch("/api/" + path, body ? { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) } : {}).then(function (r) { return r.json(); });
  }
  function options(list, value, blank) {
    return list.map(function (o) {
      return "<option" + (o === value ? " selected" : "") + ' value="' + esc(o) + '">' +
        esc(o || blank || "(keep GBIF's value)") + "</option>";
    }).join("");
  }
  function report(res, ok) {
    var el = $("#status");
    if (res.ok) { el.className = "notice"; el.textContent = ok + " Rebuilding the local site…"; poll(); }
    else { el.className = "notice warn-box"; el.innerHTML = "<b>Not saved.</b><br>" + (res.errors || []).map(esc).join("<br>"); }
    return res.ok;
  }
  function poll() {
    setTimeout(function () {
      api("status").then(function (s) {
        if (s.running) return poll();
        $("#status").textContent = s.error ? "Rebuild failed: " + s.error : "Saved; local site rebuilt " + (s.last ? s.last.at : "") + ".";
      });
    }, 1500);
  }

  // A search box with a pick list under it.
  function picker(input, list, onPick) {
    var t = null;
    input.addEventListener("input", function () {
      clearTimeout(t);
      t = setTimeout(function () {
        var q = input.value.trim();
        // An id typed in: a Catalogue of Life id (KVC9L) or gbif:<key>, name-<n>, IOG-<n>.
        if (/^(gbif:\d+|name-\d+|IOG-\d+|[0-9A-Z]{3,7})$/.test(q) && !/^[A-Z][a-z]/.test(q)) {
          list.innerHTML = '<li data-id="' + esc(q) + '">Id ' + esc(q) + "</li>"; return;
        }
        if (q.length < 2) { list.innerHTML = ""; return; }
        api("taxa?q=" + encodeURIComponent(q)).then(function (rows) {
          list.innerHTML = rows.map(function (r) {
            return '<li data-id="' + r.taxon_id + '"><span class="s-rank">' + esc(r.rank) + "</span> " + esc(r.name) +
              (r.origin === "curated" ? ' <span class="badge muted">curated</span>' : "") + "</li>";
          }).join("") || '<li class="muted">No match</li>';
        });
      }, 150);
    });
    list.addEventListener("click", function (e) {
      var li = e.target.closest("li[data-id]");
      if (li) { list.innerHTML = ""; onPick(li.getAttribute("data-id"), li.textContent); }
    });
  }

  function showTaxon(id) {
    api("taxon/" + encodeURIComponent(id)).then(function (d) {
      var t = d.taxon, c = d.curated || {};
      if (!t) {
        // A COL id or GBIF key not in the tree yet: offer to add it (the server fetches it).
        $("#edit").innerHTML = "<p>" + esc(id) + " is not in the tree. Adding it fetches it (COL id " +
          "or gbif:&lt;key&gt;) and matches it to the Catalogue of Life.</p>" +
          '<button id="addkey">Add ' + esc(id) + "</button>";
        $("#addkey").onclick = function () {
          api("taxon", { taxon_id: String(id), note: "", reason: "added by key" }).then(function (r) {
            if (report(r, "Added.")) showTaxon(id);
          });
        };
        return;
      }
      var g = d.gbif || {};
      var rows = FIELDS.map(function (f) {
        var k = f[0], cur = c[k] || "", base = { name: 1, authorship: 1, parent_id: 1, common_name: 1, rank: 1 }[k] ? t[k] : "";
        var input = CHOICES[k] ? '<select name="' + k + '">' + options(CHOICES[k], cur) + "</select>"
          : k === "note" ? '<textarea name="note" rows="2">' + esc(cur) + "</textarea>"
          : '<input name="' + k + '" value="' + esc(cur) + '">';
        return "<tr><th>" + esc(f[1]) + "</th><td>" + input + '</td><td class="muted small">' +
          (base != null && base !== "" ? "now: " + esc(base) : "") + "</td></tr>";
      }).join("");
      $("#edit").innerHTML = '<p><span class="rank-chip">' + esc(t.rank) + "</span> <b>" + esc(t.name) + "</b> " +
        '<a href="index.html#/t/' + t.taxon_id + '" target="_blank">page ↗</a> · id ' + t.taxon_id +
        (d.parent ? " · in " + esc(d.parent.name) : "") + " · " + (t.in_col ? "Catalogue of Life" :
          t.origin === "curated" ? "added by hand" : "not in the Catalogue of Life") + "</p>" +
        (t.match_note ? '<p class="muted small">' + esc(t.match_note) + "</p>" : "") +
        ((d.names || []).length ? '<p class="small">Names merged here (split one out: open its id, status accepted): ' +
          d.names.map(function (n) {
            return '<a href="#" data-id="' + esc(n.name_id) + '"><i>' + esc(n.name) + "</i></a> (" + esc(n.kind) + ")";
          }).join("; ") + "</p>" : "") +
        '<p class="muted small">Blank = keep the source\'s value. To merge this into another taxon: status ' +
        "synonym and that taxon's id as Merge into. Parent can also be given by searching below.</p>" +
        '<form id="ed" class="form"><table class="ed">' + rows + "</table>" +
        '<label>Move under (search) <input name="parent_pick" autocomplete="off"></label><ul class="pick" data-for="ed"></ul>' +
        '<label>Reason / source <input name="reason" value="' + esc(c.reason || "") + '"></label>' +
        '<label>Citation <input name="citation" value="' + esc(c.citation || "") + '"></label>' +
        '<button type="submit">Save</button> ' + (d.curated ? '<button type="button" id="clear">Remove all hand edits</button>' : "") +
        "</form><h3 class=\"gap\">Evidence</h3><ul class=\"ev\">" + d.evidence.map(function (e) {
          return "<li>" + esc(e.kind) + " " + esc(e.ref) + (e.license ? " · " + esc(e.license) : "") +
            (e.credit ? " · " + esc(e.credit) : "") + (e.note ? " · " + esc(e.note) : "") +
            ' <button type="button" class="link" data-kind="' + esc(e.kind) + '" data-ref="' + esc(e.ref) + '">remove</button></li>';
        }).join("") + "</ul>" +
        '<form id="ev" class="form"><label>Kind <select name="kind">' + KINDS.map(function (k) {
          return '<option value="' + k[0] + '">' + esc(k[1]) + "</option>"; }).join("") + "</select></label>" +
        '<label>Id, file or URL <input name="ref" required></label>' +
        '<label>License (photos) <select name="license">' + options(LICENSES, "", "(none: not a photo)") + "</select></label>" +
        '<label>Credit <input name="credit" placeholder="© M. A. Johnston"></label>' +
        '<label>Note <input name="note" placeholder="e.g. Guam, Ritidian, 2026"></label>' +
        "<button type=\"submit\">Add evidence</button></form>";
      $("#edit").insertAdjacentHTML("beforeend", '<h3 class="gap">Found in the literature</h3><div id="mentions" class="small muted">Loading…</div>');
      api("mentions/" + encodeURIComponent(t.taxon_id)).then(function (ms) {
        $("#mentions").className = "";
        $("#mentions").innerHTML = ms.length ? '<table class="curated">' + ms.map(function (m) {
          return '<tr class="d-' + esc(m.decision) + '"><td>' + esc(m.kind) + "<br><span class=\"muted small\">" + esc(m.method) +
            "</span></td><td><b>" + esc(m.file.split("/").pop().replace(/\.pdf$/, "")) + "</b> p. " + m.page +
            (m.islands ? " · " + esc(m.islands) : "") + '<br><span class="muted small">' + esc(m.snippet || "") + "</span></td><td>" +
            ["accepted", "rejected", "pending"].map(function (d) {
              return '<button type="button" class="link dec" data-d="' + d + '" data-f="' + esc(m.file) + '" data-p="' + m.page +
                '" data-n="' + esc(m.name_found) + '"' + (m.decision === d ? ' disabled' : "") + ">" + (d === "pending" ? "undo" : d.slice(0, -2)) + "</button>";
            }).join(" ") + '<br><span class="small">' + esc(m.decision) + "</span></td></tr>";
        }).join("") + "</table>" : '<p class="muted small">Nothing found in the PDF library.</p>';
        $("#mentions").querySelectorAll("button.dec").forEach(function (b) {
          b.onclick = function () {
            api("decision", { file: b.getAttribute("data-f"), page: b.getAttribute("data-p"), name: b.getAttribute("data-n"),
              decision: b.getAttribute("data-d") }).then(function (r) { if (report(r, "Decision saved.")) showTaxon(t.taxon_id); });
          };
        });
      });
      var ed = $("#ed");
      picker(ed.parent_pick, $('.pick[data-for="ed"]'), function (pid, label) {
        ed.parent_id.value = pid; ed.parent_pick.value = label.trim();
      });
      ed.onsubmit = function (e) {
        e.preventDefault();
        var row = { taxon_id: String(t.taxon_id), reason: ed.reason.value, citation: ed.citation.value };
        FIELDS.forEach(function (f) { row[f[0]] = ed[f[0]].value; });
        api("taxon", row).then(function (r) { if (report(r, "Saved.")) { showTaxon(t.taxon_id); loadCurated(); } });
      };
      if ($("#clear")) $("#clear").onclick = function () {
        api("taxon/" + encodeURIComponent(t.taxon_id) + "/delete", {}).then(function (r) { if (report(r, "Edits removed.")) { showTaxon(t.taxon_id); loadCurated(); } });
      };
      var ev = $("#ev");
      ev.onsubmit = function (e) {
        e.preventDefault();
        api("evidence", { taxon_id: String(t.taxon_id), kind: ev.kind.value, ref: ev.ref.value, license: ev.license.value,
          credit: ev.credit.value, note: ev.note.value }).then(function (r) { if (report(r, "Evidence added.")) showTaxon(t.taxon_id); });
      };
      $("#edit").querySelectorAll(".ev button").forEach(function (b) {
        b.onclick = function () {
          api("evidence/delete", { taxon_id: String(t.taxon_id), kind: b.getAttribute("data-kind"), ref: b.getAttribute("data-ref") })
            .then(function (r) { if (report(r, "Evidence removed.")) showTaxon(t.taxon_id); });
        };
      });
    });
  }

  function loadCurated() {
    api("curated").then(function (rows) {
      $("#n-curated").textContent = "(" + rows.length + ")";
      $("#curated").innerHTML = rows.map(function (r) {
        var changed = FIELDS.filter(function (f) { return r[f[0]]; }).map(function (f) { return f[0]; }).join(", ");
        return '<tr><td><a href="#" data-id="' + r.taxon_id + '">' + esc(r.taxon_id) + "</a></td><td>" + esc(r.name) +
          "</td><td>" + esc(changed) + "</td><td>" + esc(r.editor) + " " + esc(r.edited) + "</td><td>" + esc(r.reason) + "</td></tr>";
      }).join("");
    });
  }
  $("#curated").addEventListener("click", function (e) {
    var a = e.target.closest("a[data-id]");
    if (a) { e.preventDefault(); showTaxon(a.getAttribute("data-id")); }
  });
  $("#edit").addEventListener("click", function (e) {      // a merged name: open its own id
    var a = e.target.closest("a[data-id]");
    if (a) { e.preventDefault(); showTaxon(a.getAttribute("data-id")); }
  });

  var add = $("#add");
  add.rank.innerHTML = options(RANKS, "Species").replace('value="">(GBIF\'s value)', "");
  picker($("#find"), $("#found"), showTaxon);
  picker(add.parent_pick, $('.pick[data-for="add"]'), function (pid, label) {
    add.parent_id.value = pid; add.parent_pick.value = label.trim();
  });
  add.onsubmit = function (e) {
    e.preventDefault();
    if (!add.parent_id.value) { report({ ok: false, errors: ["Choose a parent from the list."] }); return; }
    api("taxon", { rank: add.rank.value, name: add.name.value, parent_id: add.parent_id.value, status: add.status.value,
      authorship: add.authorship.value, common_name: add.common_name.value, note: add.note.value, reason: add.reason.value })
      .then(function (r) { if (report(r, "Added " + add.name.value + ".")) { add.reset(); loadCurated(); } });
  };
  fetch("/api/status").then(function () { loadCurated(); }, function () { $("#offline").hidden = false; });
})();
