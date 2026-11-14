// CSV as Python's csv module reads and writes it (RFC 4180, QUOTE_MINIMAL), so a file the
// editor saves differs from the one it read only where something was edited: same quoting,
// same line ending (taxonomy.csv: "\n" with a BOM; curation/*.csv: "\r\n").
(function () {
  "use strict";

  function parse(text) {
    var bom = text.charCodeAt(0) === 0xfeff;
    if (bom) text = text.slice(1);
    var firstNl = text.indexOf("\n");
    var eol = firstNl > 0 && text[firstNl - 1] === "\r" ? "\r\n" : "\n";
    var rows = [], row = [], field = "", i = 0, n = text.length, quoted = false;
    while (i < n) {
      var c = text[i];
      if (quoted) {
        if (c === '"') {
          if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
          quoted = false; i++; continue;
        }
        field += c; i++; continue;
      }
      if (c === '"' && field === "") { quoted = true; i++; continue; }
      if (c === ",") { row.push(field); field = ""; i++; continue; }
      if (c === "\r" || c === "\n") {
        row.push(field); rows.push(row); row = []; field = "";
        i += c === "\r" && text[i + 1] === "\n" ? 2 : 1;
        continue;
      }
      field += c; i++;
    }
    if (field !== "" || row.length) { row.push(field); rows.push(row); }
    return { rows: rows, bom: bom, eol: eol };
  }

  // A table: {columns, rows: [objects], bom, eol}. Columns missing from a row read as "".
  function readTable(text, wantColumns) {
    var p = parse(text || "");
    var header = p.rows.length ? p.rows[0] : (wantColumns || []).slice();
    var columns = header.slice();
    (wantColumns || []).forEach(function (c) { if (columns.indexOf(c) < 0) columns.push(c); });
    var rows = [];
    for (var r = 1; r < p.rows.length; r++) {
      var cells = p.rows[r];
      if (cells.length === 1 && cells[0] === "") continue;     // a blank line
      var o = {};
      columns.forEach(function (c) { o[c] = ""; });
      header.forEach(function (c, j) { o[c] = cells[j] == null ? "" : cells[j]; });
      rows.push(o);
    }
    return { columns: columns, rows: rows, bom: p.bom, eol: p.eol, header: header };
  }

  function quote(v) {
    v = v == null ? "" : String(v);
    return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }

  function writeTable(t, columns) {
    var cols = columns || t.columns;
    var out = [cols.map(quote).join(",")];
    t.rows.forEach(function (r) {
      out.push(cols.map(function (c) { return quote(r[c]); }).join(","));
    });
    return (t.bom ? "﻿" : "") + out.join(t.eol) + t.eol;
  }

  window.IOGCSV = { parse: parse, readTable: readTable, writeTable: writeTable, quote: quote };
})();
