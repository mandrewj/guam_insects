/* Insects of Guam (and Micronesia): renders taxon pages from data/t/<bucket>/<id>.js records.
 * Works from file:// and from any static host, because data is loaded with <script> tags,
 * not fetch(). Ported from entobase. */
(function () {
  "use strict";

  var app = document.getElementById("app");
  var records = new Map();   // id -> record
  var waiting = new Map();   // id -> {resolve, reject}
  var meta = null;

  var ITALIC_RANKS = { Genus: 1, Subgenus: 1, Species: 1, Subspecies: 1 };
  var SITE = "Insects of Guam";

  // ------------------------------------------------------------------ data loading
  window.guaminsects = {
    meta: function (m) { meta = m; renderSiteFooter(); route(); },
    load: function (rec) {
      records.set(rec.id, rec);
      if (records.size > 300) {        // search snippets load dozens of records; keep the recent ones
        var drop = records.size - 200;
        for (var key of records.keys()) { if (drop-- <= 0) break; if (key !== currentId) records.delete(key); }
      }
      var w = waiting.get(rec.id);
      if (w) { waiting.delete(rec.id); w.resolve(rec); }
    }
  };

  var pending = new Map();      // id -> the promise of a load in flight, so two callers share it
  function loadRecord(id) {
    if (records.has(id)) return Promise.resolve(records.get(id));
    if (pending.has(id)) return pending.get(id);
    var p = new Promise(function (resolve, reject) {
      waiting.set(id, { resolve: resolve, reject: reject });
      var s = document.createElement("script");
      s.src = "data/t/" + Math.floor(id / 1000) + "/" + id + ".js";
      s.onload = function () { s.remove(); };
      s.onerror = function () { s.remove(); waiting.delete(id); reject(new Error("missing")); };
      document.head.appendChild(s);
    });
    pending.set(id, p);
    var done = function () { pending.delete(id); };
    p.then(done, done);
    return p;
  }

  // ------------------------------------------------------------------ helpers
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // BugGuide files subgenera, species groups and series under "No Taxon", and a species
  // group under "Species"; say which they are instead of the filing label.
  function displayRank(rank, name) {
    var n = name || "";
    if (rank === "No Taxon" || rank === "Species" && /\bgroup$/i.test(n)) {
      if (/^subgenus\b/i.test(n)) return "Subgenus";
      if (/\bgroup$/i.test(n) || /species[- ]group/i.test(n)) return "Species group";
      if (/^series\b/i.test(n)) return "Series";
      return rank === "No Taxon" ? "Group" : rank;
    }
    return rank;
  }
  function sciName(rank, name) {
    return ITALIC_RANKS[rank] ? "<i>" + esc(name) + "</i>" : esc(name);
  }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return isNaN(d) ? esc(iso) : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
  var INVARIANT = { species: 1 };
  function plural(n, word) { return n + " " + word + (n === 1 || INVARIANT[word] ? "" : "s"); }
  function stripDot(s) { return String(s).replace(/\.\s*$/, ""); }
  function ext(url, label) {
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + label + "</a>";
  }

  // ------------------------------------------------------------------ scroll memory
  // Back/forward returns to where you were; following a link starts at the top.
  // Positions are keyed by the page actually on screen (`shown`), not location.hash: Safari and
  // Firefox fire scroll events after the hash changes but before the new page renders.
  var scrollPos = new Map(), linkNav = false, shown = null;
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  window.addEventListener("scroll", function () {
    if (shown !== null) scrollPos.set(shown, window.scrollY);
  }, { passive: true });
  window.addEventListener("hashchange", function () { shown = null; }, true);
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest('a[href^="#/"]');
    if (a) linkNav = true;
  }, true);
  function restoreScroll() {
    var y = linkNav ? 0 : (scrollPos.get(location.hash) || 0);
    linkNav = false;
    window.scrollTo(0, y);
    shown = location.hash;
  }

  // ------------------------------------------------------------------ routing
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var SCROLL = REDUCED ? "auto" : "smooth";

  // After a page replaces <main> the focused link is gone and focus falls to <body>; put it on
  // the heading so keyboard and screen-reader users start at the top of the new page.
  function focusTitle() {
    var h = app.querySelector("h1");
    if (!h) return;
    h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
  }

  function route() {
    if (!meta) return;
    var hash = location.hash;        // a slow load must not paint over a page the reader left
    var live = function (fn) { return function (v) { if (location.hash === hash) { fn(v); focusTitle(); } }; };
    var sm = location.hash.match(/^#\/search\?(.*)$/);
    if (sm) {
      var params = new URLSearchParams(sm[1]);
      renderSearch(params.get("q") || "", params.get("hidden") === "1");
      return;
    }
    var im = location.hash.match(/^#\/id\/(\d+)(?:\?r=([a-z,]+))?/);
    if (im) {
      var iid = Number(im[1]);
      var valid = (meta.regions || []).map(function (x) { return x.key; });
      var keys = (im[2] || "").split(",").filter(function (k) { return valid.indexOf(k) >= 0; });
      loadRecord(iid).then(live(function (rec) { renderIdentify(rec, keys); }),
                           live(function () { renderMissing(iid); }));
      return;
    }
    var m = location.hash.match(/^#\/t\/(\d+)/);
    var id = m ? Number(m[1]) : meta.root;
    if (!id) { app.innerHTML = "<p>No data has been built yet. Run <code>uv run guaminsects build</code>.</p>"; return; }
    loadRecord(id).then(live(function (rec) { renderTaxon(rec, !m); }),
                        live(function () { renderMissing(id); }));
  }
  // Header toggle: swaps between a taxon page and the identify grid for the same taxon, so
  // it always lands on whatever the reader is already looking at.
  var identifyBtn = document.getElementById("identify");

  function setIdentify(on) {
    if (!identifyBtn) return;
    identifyBtn.setAttribute("aria-pressed", on ? "true" : "false");
    identifyBtn.classList.toggle("on", on);
  }

  if (identifyBtn) {
    identifyBtn.addEventListener("click", function () {
      var id = currentId || meta.root;
      if (!id) return;
      location.hash = (identifyBtn.classList.contains("on") ? "#/t/" : "#/id/") + id;
    });
  }

  window.addEventListener("hashchange", route);

  app.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.jump");
    if (!a) return;
    e.preventDefault();
    var el = document.getElementById(a.getAttribute("data-target"));
    if (el) el.scrollIntoView({ behavior: SCROLL, block: "start" });
  });

  // Citations scroll to Works Cited instead of changing the route.
  app.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.cite");
    if (!a) return;
    e.preventDefault();
    var li = document.getElementById("ref-" + a.getAttribute("data-ref"));
    if (li) {
      li.scrollIntoView({ behavior: SCROLL, block: "center" });
      li.classList.add("flash");
      setTimeout(function () { li.classList.remove("flash"); }, 1600);
    }
  });


  function renderMissing(id) {
    setIdentify(false);
    app.innerHTML = '<div class="notice">Taxon ' + esc(id) + " isn't in this build. It may have " +
      "been merged or removed; try searching for its name.</div>";
  }

  var currentId = null;
  // The left column rides down the page with the reading column. Taller than the window, it
  // would otherwise hide its own bottom; so its sticky offset goes negative by the overflow
  // and it parks once its last line is on screen, then waits for the layout to end. No inner
  // scrollbar, so nothing is clipped. Shorter than the window, it simply sticks under the header.
  var sideWatch = null;
  function pinSide() {
    if (sideWatch) { sideWatch.disconnect(); sideWatch = null; }
    var side = app.querySelector(".layout > .side");
    if (!side || !window.matchMedia("(min-width: 861px)").matches) return;
    function fit() {
      var top = Math.min(64, window.innerHeight - side.offsetHeight - 12);
      side.style.top = top + "px";
    }
    fit();
    if (window.ResizeObserver) { sideWatch = new ResizeObserver(fit); sideWatch.observe(side); }
    else window.addEventListener("resize", fit);
  }


  function renderTaxon(r, isHome) {
    currentId = r.id;
    setIdentify(false);
    document.title = (isHome ? "" : r.name + (r.common ? " – " + r.common : "") + " · ") + SITE;
    // The home page lists the orders straight away: Hexapoda's own children are four
    // classes, and Insecta holds nearly everything.
    var shown = isHome && meta.home.length ? Object.assign({}, r, { children: meta.home, families: [] }) : r;
    var html = [];
    if (isHome) html.push(homeIntro());
    else html.push(breadcrumb(r));
    if (!isHome) html.push(header(r));
    // Two columns: the photo, at-a-glance, island records and classification stay put on the
    // left while the reading column scrolls.
    html.push('<div class="layout"><aside class="side">');
    if (!isHome) html.push(gallery(r));
    html.push(facts(r));
    html.push(presenceBox(r));
    html.push(iucnBox(r));
    if (!isHome) html.push(classification(r));
    html.push(links(r));
    html.push('</aside><div class="main">');
    if (!isHome) html.push(pageNav(r));
    if (!isHome) html.push(curatedNote(r));
    html.push(children(shown));
    html.push(familyIndex(shown));
    html.push(sections(r));
    html.push(hostCrops(r));
    html.push(literature(r));
    html.push(evidence(r));
    html.push(wikipedia(r));
    html.push("</div></div>");
    html.push(attribution(r));
    app.innerHTML = html.join("");
    pinSide();
    var crumbs = app.querySelector(".crumbs ol");
    if (crumbs) crumbs.scrollLeft = crumbs.scrollWidth;   // phones: show the nearest parents
    qInput.value = "";
    restoreScroll();
  }


  function identifyPanel(c, keys) {
    var href = c.kids ? identifyHref(c.id, keys) : "#/t/" + c.id;
    var filtering = keys.length > 0;
    var unknown = !c.regions;
    var pic = c.thumb
      ? '<img class="ip-photo" src="' + esc(c.thumb) + '" alt="" loading="lazy">'
      : '<span class="ip-photo ip-none">' + esc(initials(c.name)) + "</span>";
    var map = '<span class="ip-map ip-isles">' + islandMap(c.regions, c.isles, true) + "</span>";
    var sub = (c.rank === "Species" || c.rank === "Subspecies")
      ? esc(c.common || "")
      : (c.species_count ? plural(c.species_count, "species") : esc(displayRank(c.rank, c.name)));
    var where = c.regions ? '<span class="ip-where">' + c.regions.map(function (k) {
      return '<span class="isle r-' + esc(k) + '">' + esc(regionLabel(k)) + "</span>";
    }).join("") + "</span>" : "";
    return '<a class="ip' + (filtering && unknown ? " ip-unknown" : "") + '" href="' + href + '">' +
      '<span class="ip-figures">' + pic + map + "</span>" +
      '<span class="ip-name">' + sciName(c.rank, c.name) + "</span>" +
      '<span class="ip-sub">' + sub + (c.kids ? " ›" : "") + "</span>" + where +
      (filtering && unknown ? '<span class="ip-flag" title="No dated record from any island group, ' +
        'so we cannot say where it occurs">no locality data</span>' : "") +
      "</a>";
  }

  function identifyHref(id, keys) {
    var r = (keys || []).join(",");
    return "#/id/" + id + (r ? "?r=" + r : "");
  }

  // Clicking a region adds or removes it; the panels show anything in ANY chosen region,
  // since the regions overlap and a reader picking two means "either".
  function withRegion(keys, key) {
    var next = keys.filter(function (k) { return k !== key; });
    if (next.length === keys.length) next = keys.concat([key]);
    return (meta.regions || []).map(function (x) { return x.key; })
      .filter(function (k) { return next.indexOf(k) >= 0; });
  }

  function regionLabel(key) {
    var found = (meta.regions || []).filter(function (x) { return x.key === key; })[0];
    return found ? found.label : key;
  }


  function identifyFilter(r, keys, counts) {
    var chips = (meta.regions || []).map(function (x) {
      var on = keys.indexOf(x.key) >= 0;
      return '<a class="chip r-' + esc(x.key) + (on ? " on" : "") + '" href="' +
        identifyHref(r.id, withRegion(keys, x.key)) + '" role="button" aria-pressed="' + on +
        '" title="' + esc(x.name) + '">' + esc(x.label) + "</a>";
    }).join("");
    var clear = keys.length
      ? '<a class="chip chip-clear" href="' + identifyHref(r.id, []) + '">Clear</a>' : "";
    var note = keys.length
      ? '<p class="ip-count">' + counts.hit + " recorded from " +
        esc(keys.map(regionLabel).join(" or ")) +
        (counts.unknown ? " · " + counts.unknown + " with no locality data" : "") +
        (counts.out ? " · " + counts.out + " not recorded there" : "") + "</p>"
      : "";
    return '<nav class="ip-filter" aria-label="Island group">' + chips + clear + "</nav>" + note +
      '<details class="ip-mapkey"><summary>What the island groups cover</summary>' +
      '<p class="muted">Guam; the Commonwealth of the Northern Mariana Islands (Saipan, Tinian, ' +
      'Rota and the northern islands); Palau; the Federated States of Micronesia (Yap, Chuuk, ' +
      'Pohnpei, Kosrae); the Marshall Islands. A taxon counts as recorded from a group when ' +
      'GBIF holds a record from there, iNaturalist has a research-grade observation there, or a ' +
      'digitised checklist lists it for that group; a genus or family takes the union of its species.</p></details>';
  }


  function renderIdentify(r, keys) {
    currentId = r.id;
    document.title = "Identify: " + r.name + " · " + SITE;
    var kids = r.children.filter(function (c) { return !c.hidden && c.status !== "synonym"; });
    var counts = { hit: 0, unknown: 0, out: 0 };
    var shown = kids.filter(function (c) {
      if (!keys.length) return true;
      if (!c.regions) { counts.unknown++; return true; }
      var hit = c.regions.some(function (k) { return keys.indexOf(k) >= 0; });
      if (hit) counts.hit++; else counts.out++;
      return hit;
    });
    var body = kids.length
      ? identifyFilter(r, keys, counts) +
        (shown.length
          ? '<div class="ip-grid">' + shown.map(function (c) {
              return identifyPanel(c, keys);
            }).join("") + "</div>"
          : '<p class="muted">Nothing here is recorded from ' +
            esc(keys.map(regionLabel).join(" or ")) + '. <a href="' +
            identifyHref(r.id, []) + '">Clear the filter</a>.</p>')
      : '<p class="muted">Nothing below ' + sciName(r.rank, r.name) + " to compare. " +
        '<a href="#/t/' + r.id + '">Open its page</a> instead.</p>';
    var left = r.children.length - kids.length;
    app.innerHTML = breadcrumb(r) +
      '<header class="taxon-head"><div class="head-line">' +
      '<span class="rank-chip">Identify</span><h1>' + sciName(r.rank, r.name) + "</h1>" +
      '<p class="badges"><a class="ip-exit" href="#/t/' + r.id + '">Full page</a></p></div>' +
      (kids.length ? '<p class="common">' + kids.length + " to compare" +
        (left ? " (" + left + " hidden page" + (left === 1 ? "" : "s") + " or synonym" +
          (left === 1 ? "" : "s") + " left out)" : "") + "</p>" : "") +
      "</header>" + body;
    setIdentify(true);
    restoreScroll();
  }

  // Breadcrumb from Hexapoda (this reference's root) down to the parent.
  function breadcrumb(r) {
    var trail = r.lineage;
    if (!trail.length) return "";
    return '<nav class="crumbs" aria-label="Taxonomy"><ol>' + trail.map(function (a) {
      return '<li><a href="#/t/' + a.id + '" title="' + esc(a.rank) + (a.common ? ": " + esc(a.common) : "") +
        '">' + sciName(a.rank, a.name) + "</a></li>";
    }).join("") + "</ol></nav>";
  }


  function pageNav(r) {
    var items = [];
    if (r.children.length) items.push(["s-children", "Included taxa"]);
    r.sections.forEach(function (s) { items.push(["s-" + s.key, s.heading]); });
    if (r.map) items.push(["s-map", "Distribution"]);
    if (r.hosts && r.hosts.length) items.push(["s-hosts", "Crops attacked"]);
    if (r.literature.length) items.push(["s-literature", "Literature"]);
    if (r.evidence.length) items.push(["s-evidence", "Evidence"]);
    if (r.wikipedia) items.push(["s-wikipedia", "Wikipedia"]);
    items.push(["s-sources", "Sources"]);
    if (items.length < 3) return "";
    return '<nav class="page-nav" aria-label="On this page"><span class="pn-label">On this page</span>' +
      items.map(function (x) {
        return '<a href="#" class="jump" data-target="' + esc(x[0]) + '">' + esc(x[1]) + "</a>";
      }).join("") + "</nav>";
  }


  function homeIntro() {
    var c = meta.counts, stats = [
      [c.species, "species"], [c.guam, "recorded from Guam"], [c.literature, "in digitised literature"],
      [c.morphospecies || null, "morphospecies"], [c.photos || null, "with photos"]];
    return '<section class="hero"><h1 class="hero-title">' + esc(meta.title) +
      ' <span class="hero-sub">' + esc(meta.subtitle) + "</span></h1>" +
      '<p class="lede">The insects and other hexapods of Guam, the Northern Mariana Islands, Palau, ' +
      "the Federated States of Micronesia and the Marshall Islands. Regional lists are thin, so " +
      "this reference pools them: museum and survey records on GBIF (including the University " +
      "of Guam Insect Collection), iNaturalist observations, and the digitised <i>Insects of " +
      "Guam</i> and <i>Insects of Micronesia</i>. Start with an order below, use " +
      "<b>Identify</b> to compare a group island by island, or press <kbd>/</kbd> to search.</p>" +
      '<ul class="stats">' + stats.filter(function (x) {
        return x[0] != null;
      }).map(function (x) {
        return "<li><strong>" + Number(x[0]).toLocaleString() + "</strong> " + esc(x[1]) + "</li>";
      }).join("") + '</ul><p class="fresh">Data updated ' + fmtDate(meta.built_at) + "</p></section>";
  }


  var STATUS = { native: ["Native", "ok"], endemic: ["Endemic", "ok"], introduced: ["Introduced", "warn"],
                 invasive: ["Invasive", "crit"], unknown: ["Status unknown", "muted"] };
  function header(r) {
    var badges = [];
    if (r.establishment && STATUS[r.establishment]) {
      badges.push('<span class="badge est-' + STATUS[r.establishment][1] + '" title="Curated">' +
        esc(STATUS[r.establishment][0]) + "</span>");
    } else if (r.status_sources && r.status_sources.length) {
      // Not curated: say what the sources say, and that a machine read it.
      var s0 = r.status_sources[0], st = STATUS[s0.status] || [s0.status, "muted"];
      badges.push('<span class="badge est-' + st[1] + '" title="' + esc(r.status_sources.map(function (x) {
        return regionLabel(x.area.toLowerCase()) + ": " + x.status + (x.year ? " (first noted " + x.year + ")" : "") +
          " per " + x.citation;
      }).join("; ")) + ' (read by machine, not yet checked)">' + esc(st[0]) + "*</span>");
    }
    if (r.status === "morphospecies") badges.push('<span class="badge morpho" title="Not formally named; recognised from specimens or photos">Morphospecies</span>');
    if (r.status === "synonym") badges.push('<span class="badge warn">Synonym</span>');
    if (r.status === "doubtful") badges.push('<span class="badge warn" title="GBIF marks this name doubtful">Doubtful name</span>');
    if (r.hidden) badges.push('<span class="badge muted" title="' + esc(r.hidden_reason || "") + '">Hidden</span>');
    if (r.origin === "curated" && r.status !== "morphospecies") badges.push('<span class="badge muted" title="Added by hand, not from GBIF">Curated</span>');
    var commons = [];
    if (r.common) commons.push(esc(r.common));
    return '<header class="taxon-head"><div class="head-line">' +
      '<span class="rank-chip">' + esc(displayRank(r.rank, r.name)) + "</span>" +
      "<h1>" + sciName(r.rank, r.name) +
      (r.authority ? ' <span class="authority">' + esc(r.authority) + "</span>" : "") + "</h1>" +
      (badges.length ? '<p class="badges">' + badges.join(" ") + "</p>" : "") + "</div>" +
      (commons.length ? '<p class="common">' + commons.join(" · ") + "</p>" : "") +
      (r.status === "synonym" && r.accepted_id ? '<p class="notice">A synonym; see the <a href="#/t/' +
        r.accepted_id + '">accepted name</a>.</p>' : "") + "</header>";
  }

  function photoCaption(ph) {
    // A photo borrowed from a taxon below says so first: a tribe page showing one of its
    // species must not read as a picture of the tribe.
    var of = ph.of ? '<a href="#/t/' + ph.of_id + '">' + esc(ph.of) + "</a>" : "";
    return (ph.of ? (ITALIC_RANKS[ph.of_rank] ? "<i>" + of + "</i>" : of) + ", " +
            "an included taxon · " : "") +
      esc(ph.attribution || "") + " · " +
      (ph.license_url ? ext(ph.license_url, esc(ph.license)) : esc(ph.license)) + " · " +
      '<span class="cap-flag">Source</span> ' + ext(ph.page, esc(ph.source) + " ↗");
  }

  function gallery(r) {
    if (!r.photos.length) return "";
    var first = r.photos[0];
    var thumbs = r.photos.length > 1 ? '<div class="g-thumbs">' + r.photos.map(function (ph, i) {
      return '<button type="button" class="g-thumb' + (i ? "" : " active") + '" data-i="' + i +
        '" aria-label="Photo ' + (i + 1) + '"><img src="' + esc(ph.thumb) + '" alt="" loading="lazy"></button>';
    }).join("") + "</div>" : "";
    // A button, not a link to the source: the caption carries the source link, and clicking
    // the picture should enlarge it rather than navigate away from the page.
    return '<figure class="gallery"><button type="button" class="g-main" data-i="0" ' +
      'title="Click to enlarge"><img src="' + esc(first.display) +
      '" alt="' + esc(r.name) + '" width="' + first.w + '" height="' + first.h + '"></button>' +
      thumbs + '<figcaption class="g-cap">' + photoCaption(first) + "</figcaption></figure>";
  }

  // Lightbox. Built once and reused; Escape, the backdrop and the close button all dismiss
  // it, and the arrows step through a taxon's photos without closing.
  var lightbox = null, lightboxAt = 0;

  var lightboxOpener = null;

  function closeLightbox() {
    if (lightbox && !lightbox.hidden) {
      lightbox.hidden = true;
      if (lightboxOpener && document.contains(lightboxOpener)) lightboxOpener.focus();
    }
    document.body.classList.remove("no-scroll");
  }
  window.addEventListener("hashchange", closeLightbox);   // Back must not leave it over the next page

  function showLightbox(i) {
    var rec = records.get(currentId);
    if (!rec || !rec.photos.length) return;
    lightboxAt = (i + rec.photos.length) % rec.photos.length;
    var ph = rec.photos[lightboxAt];
    var many = rec.photos.length > 1;
    if (!lightbox) {
      lightbox = document.createElement("div");
      lightbox.className = "lightbox";
      lightbox.setAttribute("role", "dialog");
      lightbox.setAttribute("aria-modal", "true");
      lightbox.setAttribute("aria-label", "Photograph");
      lightbox.hidden = true;
      document.body.appendChild(lightbox);
    }
    lightbox.innerHTML =
      '<button type="button" class="lb-close" aria-label="Close">\u00d7</button>' +
      (many ? '<button type="button" class="lb-step lb-prev" aria-label="Previous">\u2039</button>' : "") +
      '<figure class="lb-figure"><img src="' + esc(ph.display) + '" alt="' + esc(rec.name) + '">' +
      '<figcaption>' + photoCaption(ph) +
      (many ? ' · ' + (lightboxAt + 1) + " of " + rec.photos.length : "") + "</figcaption></figure>" +
      (many ? '<button type="button" class="lb-step lb-next" aria-label="Next">\u203a</button>' : "");
    if (lightbox.hidden) lightboxOpener = document.activeElement;
    lightbox.hidden = false;
    document.body.classList.add("no-scroll");
    var closeBtn = lightbox.querySelector(".lb-close");
    if (closeBtn) closeBtn.focus();
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (t.closest && t.closest("button.g-main")) {
      showLightbox(Number(t.closest("button.g-main").getAttribute("data-i")) || 0);
      return;
    }
    if (!lightbox || lightbox.hidden || !lightbox.contains(t)) return;
    if (t.closest(".lb-prev")) showLightbox(lightboxAt - 1);
    else if (t.closest(".lb-next")) showLightbox(lightboxAt + 1);
    // The caption's own links must still work; anything else dismisses.
    else if (t.closest(".lb-close") || !t.closest("figcaption")) closeLightbox();
  });

  document.addEventListener("keydown", function (e) {
    if (!lightbox || lightbox.hidden) return;
    if (e.key === "Escape") closeLightbox();
    else if (e.key === "ArrowLeft") showLightbox(lightboxAt - 1);
    else if (e.key === "ArrowRight") showLightbox(lightboxAt + 1);
  });

  // The Wikipedia preview is redundant while the full article is open.
  app.addEventListener("toggle", function (e) {
    if (!e.target.classList || !e.target.classList.contains("wiki-body")) return;
    var pv = e.target.parentNode.querySelector(".wiki-preview");
    if (pv) pv.hidden = e.target.open;
  }, true);

  // Gallery thumbnails swap the main photo and caption.
  app.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("button.g-thumb");
    if (!b) return;
    var rec = records.get(currentId), ph = rec && rec.photos[Number(b.getAttribute("data-i"))];
    if (!ph) return;
    var fig = b.closest(".gallery"), main = fig.querySelector(".g-main");
    main.setAttribute("data-i", b.getAttribute("data-i"));
    main.querySelector("img").src = ph.display;
    main.querySelector("img").width = ph.w;
    main.querySelector("img").height = ph.h;
    fig.querySelector(".g-cap").innerHTML = photoCaption(ph);
    fig.querySelectorAll(".g-thumb").forEach(function (t) { t.classList.toggle("active", t === b); });
  });

  function initials(name) {
    var w = String(name).replace(/[^A-Za-z ]/g, "").split(" ").filter(Boolean);
    return (w.length > 1 && /^[A-Z]/.test(w[1]) ? w[0][0] + w[1][0] : (w[0] || "?").slice(0, 2)).toUpperCase();
  }


  function childCard(c, withTile) {
    var sub = [];
    if (c.common) sub.push(esc(c.common));
    if (c.species_count && c.rank !== "Species") sub.push(plural(c.species_count, "species"));
    if (c.status === "morphospecies") sub.push("morphospecies");
    if (c.status === "synonym") sub.push("synonym");
    return '<li><a class="card' + (c.thumb || withTile ? " has-thumb" : "") + '" href="#/t/' + c.id + '">' +
      (c.thumb ? '<img class="card-thumb" src="' + esc(c.thumb) + '" alt="" loading="lazy">'
               : withTile ? '<span class="card-thumb tile" aria-hidden="true">' + esc(initials(c.name)) + "</span>" : "") +
      '<span class="card-rank">' + esc(displayRank(c.rank, c.name)) +
      '</span><span class="card-name">' + sciName(c.rank, c.name) + "</span>" +
      (sub.length ? '<span class="card-sub">' + sub.join(" · ") + "</span>" : "") +
      (c.regions ? '<span class="card-isles">' + c.regions.map(function (k) {
        return '<span class="isle r-' + esc(k) + '">' + esc(regionLabel(k)) + "</span>";
      }).join("") + "</span>" : "") + "</a></li>";
  }

  // Every family beneath an order, suborder or superfamily in one compact list.
  function familyIndex(r) {
    if (!r.families || r.families.length < 2) return "";
    return '<details class="families" id="s-families" open><summary>All ' + r.families.length +
      " families (" + r.families.reduce(function (n, f) { return n + f.n; }, 0).toLocaleString() +
      " species)</summary><ul>" + r.families.map(function (f) {
        return '<li><a href="#/t/' + f.id + '"><span class="f-name">' + esc(f.name) + "</span>" +
          (f.common ? ' <span class="f-common">' + esc(f.common) + "</span>" : "") +
          ' <span class="f-n">' + f.n.toLocaleString() + "</span></a></li>";
      }).join("") + "</ul></details>";
  }


  function children(r) {
    if (!r.children.length) return "";
    var shown = r.children.filter(function (c) { return !c.hidden && c.status !== "synonym"; });
    var hidden = r.children.filter(function (c) { return c.hidden || c.status === "synonym"; });
    // If any card has a photo, give the others a lettered tile so the grid lines up.
    var tiles = function (list) {
      var any = list.some(function (c) { return c.thumb; });
      return list.map(function (c) { return childCard(c, any); }).join("");
    };
    var out = '<section class="browse" id="s-children"><h2>' +
      (r.id === meta.root ? "Orders" : "Included taxa") + "</h2>";
    if (shown.length) out += '<ul class="cards">' + tiles(shown) + "</ul>";
    if (hidden.length) {
      out += '<details class="hidden-pages"><summary>Hidden pages and synonyms (' + hidden.length +
        ")</summary><ul class=\"cards\">" + tiles(hidden) + "</ul></details>";
    }
    return out + "</section>";
  }

  function gbifCredit(m) {
    return "Occurrence data: " + ext(m.key ? "https://www.gbif.org/species/" + m.key : "https://www.gbif.org/", "GBIF.org") +
      ", accessed " + fmtDate(m.retrieved) + ". Basemap © OpenMapTiles © OpenStreetMap contributors";
  }

  // A group map has no GBIF key to link to: it is drawn from the genera or species beneath.
  function groupNote(m) {
    if (!m.group) return "";
    var unit = m.group.level === "genus" ? ["genus", "genera"] : ["species", "species"];
    return " Drawn from the " + m.group.n.toLocaleString() + " " + (m.group.n === 1 ? unit[0] : unit[1]) +
      " it contains, since GBIF has no record of this group itself.";
  }


  function mapFigure(r) {
    var m = r.map;
    if (!m) return "";
    var years = m.min_year && m.max_year ? ", " + m.min_year + "–" + m.max_year : "";
    var stack = '<img src="' + esc(m.basemap) + '" alt="Map of Micronesia" loading="lazy">' +
      '<img class="map-overlay" src="' + esc(m.overlay) + '" alt="GBIF records of ' + esc(r.name) + '" loading="lazy">';
    return '<figure class="map">' + (m.key
      ? '<a class="map-stack" href="https://www.gbif.org/occurrence/map?taxon_key=' + m.key +
        '" target="_blank" rel="noopener" title="Explore on GBIF">' + stack + "</a>"
      : '<div class="map-stack">' + stack + "</div>") +
      '<figcaption class="g-cap"><strong>' + Number(m.records).toLocaleString() +
      "</strong> georeferenced records in Micronesia" + years + ". " + gbifCredit(m) + ".</figcaption></figure>";
  }


  // Text sections from sources (each says where it came from), with the map first.
  function sections(r) {
    var map = mapFigure(r);
    var body = map ? '<section class="info" id="s-map"><h2>Distribution</h2>' + map + "</section>" : "";
    return body + r.sections.map(function (s) {
      return '<section class="info" id="s-' + esc(s.key) + '"><h2>' + esc(s.heading) + "</h2>" +
        '<div class="prose">' + s.html + "</div>" +
        (s.note ? '<p class="section-note">' + s.note + "</p>" : "") + "</section>";
    }).join("");
  }



  function wikiCredit(w) {
    return "Wikipedia article " + ext(w.url, "“" + esc(w.title) + "”") + " (" +
      ext("https://en.wikipedia.org/w/index.php?oldid=" + w.revid, "revision of " + fmtDate(w.rev_timestamp)) +
      "), " + ext("https://creativecommons.org/licenses/by-sa/4.0/", "CC BY-SA 4.0") +
      ", retrieved " + fmtDate(w.retrieved);
  }

  function wikipedia(r) {
    var w = r.wikipedia;
    if (!w) return "";
    // Collapsed to a preview: articles on widespread species run to pages about other
    // continents, and the literature and island records are what this site adds.
    var collapsed = true;
    return '<section class="wiki" id="s-wikipedia"><h2>From Wikipedia</h2>' +
      (collapsed && w.preview ? '<p class="wiki-preview">' + esc(w.preview) + "</p>" : "") +
      '<details class="wiki-body"' + (collapsed ? "" : " open") + "><summary>" +
      '<span class="when-closed">Show entire Wikipedia article</span>' +
      '<span class="when-open">Hide Wikipedia article</span></summary>' +
      '<div class="prose">' + w.html + "</div></details>" +
      '<p class="section-note">' + (w.lead_only ? "Introduction only (the full article is very long; read it on Wikipedia). " : "") +
      "Text from the " + wikiCredit(w) + ". References and further " +
      "reading are on Wikipedia.</p></section>";
  }


  // Literature: digitised checklists and papers that list the taxon, with the islands each
  // supports. The public build cites; it never quotes the text.
  function literature(r) {
    if (!r.literature.length) return "";
    return '<section class="refs" id="s-literature"><h2>Literature</h2><ul class="lit">' +
      r.literature.map(function (w) {
        var where = w.areas.length ? ' <span class="lit-areas">' + w.areas.map(function (a) {
          return '<span class="isle r-' + esc(a.toLowerCase()) + '">' + esc(regionLabel(a.toLowerCase())) + "</span>";
        }).join("") + "</span>" : "";
        if (w.source === "pdf") {
          var pages = w.pages && w.pages.length ? (w.pages.length > 1 ? " pp. " : " p. ") + w.pages.join(", ") : "";
          return "<li>" + (w.treated ? '<span class="badge" title="The document has a section on this taxon">Treated</span> ' : "") +
            "<cite>" + esc(w.citation) + "</cite>" + esc(pages) + where +
            ' <span class="ref-links">' + (w.url ? ext(w.url, "publisher's copy") : "") +
            (w.file ? (w.url ? " · " : "") + '<a href="' + esc(w.file) + '" target="_blank" rel="noopener">local PDF</a>' : "") + "</span>" +
            (w.snippet ? '<blockquote class="lit-snip">' + esc(w.snippet) + "</blockquote>" : "") + "</li>";
        }
        return "<li><cite>" + esc(w.citation || w.title) + "</cite>" + where +
          ' <span class="ref-links">' + ext(w.url, w.source === "croppests" ? "the list online" : "checklist on GBIF") +
          (w.doi ? " · " + ext("https://doi.org/" + w.doi, "doi:" + esc(w.doi)) : "") + "</span></li>";
      }).join("") + "</ul>" +
      '<p class="section-note">Names found by machine in the literature: digitised checklists from ' +
      ext("https://plazi.org/", "Plazi") + " (via GBIF, CC0), and the text of the papers and monographs " +
      "listed. Island groups are those the document names in its account of the taxon. Not yet " +
      "checked by a person, so a mention can be a comparison or a misreading.</p></section>";
  }

  // Crops it is recorded attacking (Nafus & Schreiner's list; facts, cited).
  function hostCrops(r) {
    if (!r.hosts || !r.hosts.length) return "";
    return '<section class="info" id="s-hosts"><h2>Crops attacked</h2><p>' + r.hosts.map(esc).join(" · ") +
      '</p><p class="section-note">From the ' + ext("https://aubreymoore.github.io/crop-pest-list/",
        "List of Insects and Mites Attacking Crops in Micronesia") + " (D. Nafus &amp; I. Schreiner, " +
      "University of Guam; HTML by A. Moore &amp; A. Tudela). Compiled in the early 1990s.</p></section>";
  }

  // What a curator attached: iNaturalist observations, GBIF records, own photos.
  var EVIDENCE = { inat_observation: ["iNaturalist observation", "https://www.inaturalist.org/observations/"],
                   gbif_occurrence: ["GBIF record", "https://www.gbif.org/occurrence/"],
                   photo_file: ["Photo", null], photo_url: ["Photo", null] };
  function evidence(r) {
    if (!r.evidence.length) return "";
    return '<section class="refs" id="s-evidence"><h2>Evidence</h2><ul class="lit">' +
      r.evidence.map(function (e) {
        var kind = EVIDENCE[e.kind] || [e.kind, null];
        var url = kind[1] ? kind[1] + encodeURIComponent(e.ref) : (e.kind === "photo_url" ? e.ref : null);
        return "<li>" + (url ? ext(url, esc(kind[0]) + " " + esc(e.kind === "photo_url" ? "" : e.ref)) : esc(kind[0])) +
          (e.credit ? " · " + esc(e.credit) : "") + (e.license ? " · " + esc(e.license.toUpperCase()) : "") +
          (e.note ? ' <span class="muted">' + esc(e.note) + "</span>" : "") + "</li>";
      }).join("") + "</ul></section>";
  }

  function curatedNote(r) {
    var out = r.note ? '<div class="notice curated-note">' + esc(r.note) + "</div>" : "";
    if (r.status_sources && r.status_sources.length) {
      out += '<p class="status-note">' + r.status_sources.map(function (x) {
        return "<b>" + esc(regionLabel(x.area.toLowerCase())) + "</b>: " + esc(x.status) +
          (x.year ? ", first noticed " + x.year : "") + " (" + esc(x.citation) + (x.page ? " p. " + x.page : "") + ")";
      }).join("; ") + '. <span class="muted">Read by machine from the paper; not yet checked.</span></p>';
    }
    return out;
  }

  // Stat tiles: exact below 2,000, then ">2k", ">97k", ">1.2M" (exact value on hover).
  function compact(n) {
    if (n < 2000) return n.toLocaleString();
    if (n < 1e6) return ">" + Math.floor(n / 1000) + "k";
    return ">" + Math.floor(n / 1e5) / 10 + "M";
  }


  function facts(r) {
    var rows = [];
    var gu = (r.presence || []).filter(function (p) { return p.area === "GU"; })[0] || {};
    var gbifAll = (r.presence || []).reduce(function (n, p) { return n + p.gbif; }, 0);
    var inatAll = (r.presence || []).reduce(function (n, p) { return n + p.inat; }, 0);
    // The third item is the tile's tone: our own counts in the page accent, then one hue
    // per outside source, so a number's origin reads without checking the label.
    if (r.rank !== "Species" && r.species_count) rows.push(["Species", r.species_count, ""]);
    if (r.rank !== "Species" && gu.species) rows.push(["Species on Guam", gu.species, ""]);
    if (gu.inat) rows.push(["iNat obs. (Guam)", gu.inat, " t-inat"]);
    else if (inatAll) rows.push(["iNat obs. (Micronesia)", inatAll, " t-inat"]);
    if (gbifAll) rows.push(["GBIF records (Micronesia)", gbifAll, " t-gbif"]);
    if (!rows.length) return "";
    return '<div class="box"><h3>At a glance</h3><dl class="facts">' + rows.map(function (x) {
      return '<div class="fact' + x[2] + '" title="' + esc(x[0]) + ": " + Number(x[1]).toLocaleString() +
        '"><dd>' + esc(compact(Number(x[1]))) + "</dd><dt>" + esc(x[0]) + "</dt></div>";
    }).join("") + "</dl></div>";
  }


  // Schematic island map: every island a dot; islands named in the records in their group's
  // colour; a group with records but no island named lights its main islands faintly.
  // Drawn here from meta.geo (approximate positions), so no map image is shipped.
  var GROUP_LABELS = { GU: [13.4, 143.0, "Guam"], MP: [17.6, 147.2, "CNMI"], PW: [9.4, 133.6, "Palau"],
                       FM: [10.6, 151.0, "FSM"], MH: [13.0, 168.5, "Marshalls"] };
  function islandMap(regions, isles, small) {
    var g = meta.geo;
    if (!g) return "";
    var W = small ? 200 : 330, H = Math.round(W / 2), b = g.bounds;
    var x = function (lon) { return ((lon - b.west) / (b.east - b.west) * W).toFixed(1); };
    var y = function (lat) { return ((b.north - lat) / (b.north - b.south) * H).toFixed(1); };
    var named = new Set((isles || []).map(function (i) { return g.alias[i] || i; }));
    var areas = new Set((regions || []).map(function (k) { return k.toUpperCase(); }));
    var namedAreas = new Set(g.islands.filter(function (i) { return named.has(i[1]); }).map(function (i) { return i[0]; }));
    var dots = g.islands.map(function (i) {
      var a = i[0], cls = "dot", rad = small ? 1.4 : 1.8;
      if (named.has(i[1])) { cls += " on r-" + a.toLowerCase(); rad = small ? 2.6 : 3.2; }
      else if (areas.has(a) && !namedAreas.has(a) && g.anchors[a].indexOf(i[1]) >= 0) {
        cls += " faint r-" + a.toLowerCase(); rad = small ? 2.4 : 3;
      }
      return '<circle class="' + cls + '" cx="' + x(i[3]) + '" cy="' + y(i[2]) + '" r="' + rad + '"><title>' + esc(i[1]) + "</title></circle>";
    }).join("");
    var labels = small ? "" : Object.keys(GROUP_LABELS).map(function (a) {
      var L = GROUP_LABELS[a];
      return '<text class="glabel' + (areas.has(a) ? " r-" + a.toLowerCase() : "") + '" x="' + x(L[1]) + '" y="' + y(L[0]) + '">' + L[2] + "</text>";
    }).join("");
    return '<svg class="isle-map' + (small ? " small" : "") + '" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' +
      (areas.size ? "Recorded from " + Array.from(areas).map(function (a) { return regionLabel(a.toLowerCase()); }).join(", ") : "No records") +
      '"><rect class="sea" width="' + W + '" height="' + H + '" rx="6"></rect>' + labels + dots + "</svg>";
  }

  // IUCN Red List category as Wikidata records it (P141, CC0). The assessment itself is on
  // the IUCN site; we show the category and say where it came from.
  var IUCN_TONE = { "critically endangered": "t-crit", "endangered": "t-crit", "vulnerable": "t-warn",
                    "near threatened": "t-warn", "least concern": "t-ok", "extinct": "t-crit",
                    "extinct in the wild": "t-crit", "data deficient": "t-unranked" };
  function titleCase(s) { return String(s).replace(/\b[a-z]/g, function (c) { return c.toUpperCase(); }); }
  function iucnBox(r) {
    var c = r.conservation;
    if (!c || !c.iucn) return "";
    return '<div class="box"><h3>Conservation status</h3>' +
      '<p class="cs-rank ' + (IUCN_TONE[c.iucn.toLowerCase()] || "t-unranked") + '"><strong>' +
      esc(titleCase(c.iucn)) + "</strong></p>" +
      '<p class="cs-src">IUCN Red List category, as recorded on ' +
      ext("https://www.wikidata.org/wiki/" + c.qid, "Wikidata") + ". " +
      ext("https://www.iucnredlist.org/search?query=" + encodeURIComponent(r.name), "Search the Red List") + "</p></div>";
  }

  // Where it is recorded, island group by island group, Guam first; each source in its own
  // column because the counts overlap (research-grade iNat observations flow into GBIF).
  function presenceBox(r) {
    var rows = r.presence || [];
    var higher = r.rank !== "Species" && r.rank !== "Subspecies";
    if (!rows.length) {
      return r.rank === "Subphylum" ? "" : '<div class="box presence-box"><h3>Recorded from</h3><p class="muted">' +
        "No dated records from Micronesia in GBIF, iNaturalist or the digitised checklists yet.</p></div>";
    }
    var cell = function (n) { return n ? Number(n).toLocaleString() : '<span class="muted">–</span>'; };
    var head = "<tr><th></th>" + (higher ? '<th title="Species recorded there, any source">spp.</th>' : "") +
      '<th class="t-gbif" title="GBIF records">GBIF</th><th class="t-inat" title="iNaturalist research-grade observations">iNat</th>' +
      '<th title="' + (higher ? "Species listed in digitised checklists" : "Digitised checklists listing it") + '">Lit.</th></tr>';
    var body = rows.map(function (p) {
      return '<tr class="r-' + esc(p.area.toLowerCase()) + '"><th>' + esc(p.label) + "</th>" +
        (higher ? "<td>" + cell(p.species) + "</td>" : "") + "<td>" + cell(p.gbif) + "</td><td>" +
        cell(p.inat) + "</td><td>" + cell(p.literature) + "</td></tr>";
    }).join("");
    var isles = (r.islands || []).filter(function (x) { return x.islands.length; });
    var named = isles.length ? '<p class="isle-list">Islands named in the records: ' + isles.map(function (x) {
      return '<span class="r-' + esc(x.area.toLowerCase()) + '"><b>' + esc(x.label) + "</b> " + esc(x.islands.join(", ")) + "</span>";
    }).join("; ") + "</p>" : "";
    return '<div class="box presence-box"><h3>Recorded from</h3>' +
      islandMap((r.regions || []), [].concat.apply([], (r.islands || []).map(function (x) { return x.islands; }))) +
      '<table class="presence">' + head + body + "</table>" + named +
      '<p class="cs-src">Counts are records, not individuals; sources overlap, so they are not added. ' +
      "Map positions are approximate.</p></div>";
  }

  // Classification: Kingdom and phylum as text (outside this reference's scope), then every
  // rank from Hexapoda down, each linking to its page.

  function classification(r) {
    var chain = r.lineage.concat([{ id: r.id, rank: r.rank, name: r.name, common: r.common }]);
    var rows = ["<tr><th>Kingdom</th><td>Animalia</td></tr>", "<tr><th>Phylum</th><td>Arthropoda</td></tr>"];
    chain.forEach(function (a, i) {
      var self = i === chain.length - 1;
      var label = sciName(a.rank, a.name) + (a.common ? ' <span class="c-common">' + esc(a.common) + "</span>" : "") +
        (self && r.authority ? '<span class="c-auth">' + esc(r.authority) + "</span>" : "");
      var cell = !self ? '<a href="#/t/' + a.id + '">' + label + "</a>" : label;
      rows.push("<tr" + (self ? ' class="self"' : "") + "><th>" + esc(a.rank) + "</th><td>" + cell + "</td></tr>");
    });
    var path = chain.slice(Math.max(0, chain.length - 4), -1)
      .map(function (a) { return sciName(a.rank, a.name); }).join(" › ");
    return '<details class="box classif-box"' + (narrow() ? "" : " open") + "><summary><h3>Classification</h3>" +
      (path ? '<span class="classif-path">' + path + "</span>" : "") + "</summary>" +
      '<table class="classif">' + rows.join("") + "</table>" +
      (r.origin === "gbif" ? '<p class="cs-src">GBIF Backbone Taxonomy' +
        (r.curated.length ? "; edited by hand: " + esc(r.curated.join(", ").replace(/_/g, " ")) : "") + "</p>" : "") +
      "</details>";
  }
  function narrow() { return window.matchMedia("(max-width: 860px)").matches; }


  function links(r) {
    if (!r.links.length) return "";
    var items = r.links.map(function (l) {
      var flag = l.confidence && l.confidence !== "high"
        ? ' <span class="badge ' + (l.confidence === "review" ? "warn" : "muted") + '" title="' +
          esc(l.note || "") + '">' + esc(l.confidence) + "</span>" : "";
      return "<li>" + ext(l.url, esc(l.label)) + flag + "</li>";
    });
    return '<div class="box"><h3>Elsewhere</h3><ul class="links">' + items.join("") + "</ul></div>";
  }


  function attribution(r) {
    var rows = [], g = r.sources.gbif;
    if (g && g.key) {
      rows.push("<li><strong>Name and classification</strong>: GBIF Backbone Taxonomy, " +
        ext("https://www.gbif.org/species/" + g.key, "taxon " + g.key) + ", retrieved " + fmtDate(g.fetched_at) +
        (r.curated.length ? "; with hand edits (" + esc(r.curated.join(", ").replace(/_/g, " ")) + ")" : "") + ".</li>");
    } else if (r.origin === "curated") {
      rows.push("<li><strong>Name and placement</strong>: added by hand by this site's curator" +
        (r.status === "morphospecies" ? " as a morphospecies" : "") + ".</li>");
    }
    if ((r.presence || []).some(function (p) { return p.gbif; })) {
      rows.push("<li><strong>Record counts</strong>: Occurrence data: " + ext("https://www.gbif.org/", "GBIF.org") +
        ", accessed " + fmtDate(g && g.presence_fetched_at) + ", from published datasets including the " +
        ext("https://doi.org/10.15468/8z7axw", "University of Guam Insect Collection") +
        "; fossils, captive collections and records with location problems left out.</li>");
    }
    if (r.inat || (r.presence || []).some(function (p) { return p.inat; })) {
      rows.push("<li><strong>iNaturalist</strong>: research-grade, wild observations per island group" +
        (r.inat && r.inat.common ? ", and the common name" : "") + ", from " +
        (r.inat ? ext("https://www.inaturalist.org/taxa/" + r.inat.id, "iNaturalist") : "iNaturalist") +
        " through its public API.</li>");
    }
    if (r.literature.length) {
      rows.push("<li><strong>Literature</strong>: citations as given above. Checklists digitised by " +
        ext("https://plazi.org/", "Plazi") + " are published through GBIF under CC0. Papers and " +
        "monographs remain under their publishers' copyright: this page cites them and links to the " +
        "publisher's copy" + (meta.target === "local"
          ? "; the short passages shown are for personal reference in this local copy only.</li>"
          : ", and quotes none of their text.</li>"));
    }
    if (r.photos.length) {
      rows.push("<li><strong>Photos</strong>: " + r.photos.map(function (ph, i) {
        return (i + 1) + ") " + photoCaption(ph) + ", retrieved " + fmtDate(ph.retrieved);
      }).join("; ") + ". Shown from their source; use the source link for the original.</li>");
    }
    if (r.map) rows.push("<li><strong>Map</strong>: " + gbifCredit(r.map) + ".</li>");
    if (r.wikipedia) rows.push("<li><strong>Wikipedia</strong>: text from the " + wikiCredit(r.wikipedia) + ".</li>");
    if (r.conservation) rows.push("<li><strong>Conservation status</strong>: IUCN Red List category from " +
      ext("https://www.wikidata.org/wiki/" + r.conservation.qid, "Wikidata") + " (CC0).</li>");
    if (r.links.some(function (l) { return l.system === "wikidata" || l.system === "bugguide"; })) {
      rows.push("<li><strong>Cross-links</strong>: Wikidata (CC0) matched by GBIF key, with the name checked; " +
        "BugGuide pages via the author's entobase index of BugGuide. Links below high confidence are labelled.</li>");
    }
    rows.push("<li><strong>This page</strong>: data built " + fmtDate(r.built_at) + ".</li>");
    return '<section class="attribution" id="s-sources"><h2>Sources &amp; attribution</h2><ul>' + rows.join("") +
      "</ul></section>";
  }

  // ------------------------------------------------------------------ search
  // Tokenizing must match src/guaminsects/search.py exactly (fold, split, stopwords, stem).
  var names = null;            // [{id, name, commons, rank, ctx, hidden, fname, fcommons, words}]
  var shards = new Map();      // shard key -> {term: postings}
  var scriptPromises = new Map();
  var STOP = null;

  window.guaminsects.names = function (rows) {
    names = rows.map(function (r) {
      var fname = fold(r[1]), fcommons = r[2] ? r[2].split(" | ").map(fold) : [];
      return { id: r[0], name: r[1], commons: r[2], rank: r[3], ctx: r[4], hidden: !!r[5],
               fname: fname, fcommons: fcommons,
               words: (fname + " " + fcommons.join(" ")).split(/[^a-z0-9]+/).filter(Boolean) };
    });
  };
  window.guaminsects.ft = function (key, data) { shards.set(key, data); };
  window.guaminsects.tokens = function (s) { return tokens(s); };   // exposed for tests

  function loadScript(src) {
    if (!scriptPromises.has(src)) {
      scriptPromises.set(src, new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = src;
        s.onload = function () { s.remove(); resolve(); };
        s.onerror = function () { s.remove(); scriptPromises.delete(src); reject(new Error(src)); };
        document.head.appendChild(s);
      }));
    }
    return scriptPromises.get(src);
  }
  function loadNames() { return loadScript("data/s/names.js").then(function () { return names; }); }
  function loadShard(key) {
    if (meta.search.shards.indexOf(key) < 0) return Promise.resolve({});
    return loadScript("data/s/ft/" + key + ".js").then(function () { return shards.get(key) || {}; });
  }

  function fold(s) { return String(s).toLowerCase().normalize("NFKD").replace(/\p{M}/gu, ""); }
  function stem(t) {
    if (t.length > 4 && /ies$/.test(t)) return t.slice(0, -3) + "y";
    if (t.length > 4 && /sses$/.test(t)) return t.slice(0, -2);
    if (t.length > 3 && /s$/.test(t) && !/(ss|us|is)$/.test(t)) return t.slice(0, -1);
    return t;
  }
  function tokens(s) {
    if (!STOP) STOP = new Set(meta.search.stopwords);
    return fold(s).split(/[^a-z0-9]+/).filter(function (t) {
      return t.length >= 2 && !STOP.has(t);
    }).map(stem);
  }
  function decode(postings) {   // "a:3,1f" -> Map(id -> tf), ids delta-encoded base 36
    var out = new Map(), id = 0;
    postings.split(",").forEach(function (p) {
      var i = p.indexOf(":");
      id += parseInt(i < 0 ? p : p.slice(0, i), 36);
      out.set(id, i < 0 ? 1 : Number(p.slice(i + 1)));
    });
    return out;
  }

  function nameMatches(q, includeHidden, limit) {
    var fq = fold(q).trim();
    if (!fq || !names) return [];
    var qwords = fq.split(/[^a-z0-9]+/).filter(Boolean), hits = [];
    names.forEach(function (n) {
      if (n.hidden && !includeHidden) return;
      var score = 0;
      if (n.fname === fq || n.fcommons.indexOf(fq) >= 0) score = 100;
      else if (n.fname.indexOf(fq) === 0) score = 80;
      else if (n.fcommons.some(function (c) { return c.indexOf(fq) === 0; })) score = 70;
      else if (qwords.every(function (w) {
        return n.words.some(function (x) { return x.indexOf(w) === 0; });
      })) score = 50;
      else if (n.fname.indexOf(fq) >= 0 || n.fcommons.some(function (c) { return c.indexOf(fq) >= 0; })) score = 20;
      if (score) hits.push({ n: n, score: score });
    });
    hits.sort(function (a, b) {
      return b.score - a.score || a.n.name.length - b.n.name.length || (a.n.name < b.n.name ? -1 : 1);
    });
    return hits.slice(0, limit).map(function (h) { return h.n; });
  }

  // Full text: AND across terms (last term also matches as a prefix), TF-IDF ranking;
  // falls back to OR when no page has every term.
  function textSearch(q, includeHidden) {
    var terms = tokens(q);
    if (!terms.length) return loadNames().then(function () { return { terms: [], hits: [], partial: false }; });
    var prefixLast = !/\s$/.test(q) && terms[terms.length - 1].length >= 3;
    var keys = Array.from(new Set(terms.map(function (t) { return t.slice(0, 2); })));
    return Promise.all([loadNames()].concat(keys.map(loadShard))).then(function () {
      var hiddenIds = new Set(names.filter(function (n) { return n.hidden; }).map(function (n) { return n.id; }));
      var N = meta.search.docs;
      var perTerm = terms.map(function (t, i) {
        var shard = shards.get(t.slice(0, 2)) || {}, merged = new Map();
        var matching = prefixLast && i === terms.length - 1
          ? Object.keys(shard).filter(function (k) { return k.indexOf(t) === 0; })
          : (shard[t] ? [t] : []);
        matching.forEach(function (k) {
          decode(shard[k]).forEach(function (tf, id) { merged.set(id, (merged.get(id) || 0) + tf); });
        });
        return merged;
      });
      function score(requireAll) {
        var totals = new Map(), counts = new Map();
        perTerm.forEach(function (m) {
          var idf = Math.log(1 + N / Math.max(m.size, 1));
          m.forEach(function (tf, id) {
            if (!includeHidden && hiddenIds.has(id)) return;
            totals.set(id, (totals.get(id) || 0) + (1 + Math.log(tf)) * idf);
            counts.set(id, (counts.get(id) || 0) + 1);
          });
        });
        var hits = [];
        totals.forEach(function (s, id) {
          if (!requireAll || counts.get(id) === perTerm.length) hits.push({ id: id, score: s + counts.get(id) * 10 });
        });
        return hits.sort(function (a, b) { return b.score - a.score; });
      }
      var hits = score(true), partial = false;
      if (!hits.length && terms.length > 1) { hits = score(false); partial = hits.length > 0; }
      return { terms: terms, hits: hits, partial: partial };
    });
  }

  // Names within one or two edits of what was typed, for a query that found nothing. Compared a
  // word at a time against the names index, and only run when a search comes back empty.
  function editDistance(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    var prev = [], cur, i, j;
    for (j = 0; j <= b.length; j++) prev[j] = j;
    for (i = 1; i <= a.length; i++) {
      cur = [i];
      var best = i;
      for (j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (cur[j] < best) best = cur[j];
      }
      if (best > max) return max + 1;
      prev = cur;
    }
    return prev[b.length];
  }

  function didYouMean(q) {
    var words = fold(q).split(/[^a-z0-9]+/).filter(function (w) { return w.length >= 4; });
    if (!words.length || !names) return [];
    var seen = new Set(), found = [];
    words.slice(0, 2).forEach(function (w) {
      var max = w.length > 7 ? 2 : 1;
      for (var i = 0; i < names.length && found.length < 12; i++) {
        var n = names[i];
        if (n.hidden) continue;
        for (var k = 0; k < n.words.length; k++) {
          var cand = n.words[k];
          if (cand.charAt(0) !== w.charAt(0) || cand === w) continue;
          if (editDistance(w, cand, max) <= max && !seen.has(cand)) {
            seen.add(cand);
            found.push({ display: cand });
            break;
          }
        }
      }
    });
    return found.slice(0, 5);
  }

  function nameRow(n) {
    return '<li><a href="#/t/' + n.id + '"><span class="s-rank">' + esc(n.rank) + "</span> " +
      sciName(n.rank, n.name) + (n.commons ? ' <span class="s-common">' + esc(n.commons) + "</span>" : "") +
      (n.ctx ? ' <span class="s-ctx">' + esc(n.ctx) + "</span>" : "") +
      (n.hidden ? ' <span class="badge warn">hidden</span>' : "") + "</a></li>";
  }

  function snippet(rec, terms) {
    var html = rec.sections.map(function (s) { return s.html; }).join(" ");
    var text = new DOMParser().parseFromString(html, "text/html").body.textContent
      .replace(/\(\s*\d+(\s*,?\s*\d+)*\s*\)/g, "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    var stems = terms.map(function (t) { return t.replace(/y$/, "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); })
      .filter(function (t) { return t.length >= 2; });
    var re = stems.length ? new RegExp("\\b(" + stems.join("|") + ")\\w*", "i") : null;
    var m = re && re.exec(text), start = m ? Math.max(0, m.index - 80) : 0;
    if (start) { var sp = text.indexOf(" ", start); if (sp >= 0 && sp < m.index) start = sp + 1; }
    var piece = (start ? "…" : "") + text.slice(start, start + 240) + (text.length > start + 240 ? "…" : "");
    if (!stems.length) return esc(piece);
    // Split on the raw text and escape each piece, so a query like "amp" cannot land inside
    // an &amp; entity that esc() has already made.
    return piece.split(new RegExp("(\\b(?:" + stems.join("|") + ")\\w*)", "gi")).map(function (part, i) {
      return i % 2 ? "<mark>" + esc(part) + "</mark>" : esc(part);
    }).join("");
  }

  var PAGE = 40;
  function renderSearch(q, includeHidden, limit) {
    limit = limit || PAGE;
    setIdentify(false);
    document.title = (q ? q + " · " : "") + "Search · " + SITE;
    qInput.value = q;
    closeSuggest();
    if (!q.trim()) { app.innerHTML = "<h1 class=\"search-title\">Search</h1><p>Type a name or any words.</p>"; return; }
    var hash = location.hash;
    var keepY = limit > PAGE ? window.scrollY : null;      // "Show more" must not jump to the top
    if (keepY === null) app.innerHTML = '<p class="loading">Searching…</p>';
    textSearch(q, includeHidden).then(function (res) {
      if (location.hash !== hash) return;       // the reader has already moved on
      var named = nameMatches(q, includeHidden, 12);
      var namedIds = new Set(named.map(function (n) { return n.id; }));
      var byId = new Map(names.map(function (n) { return [n.id, n]; }));
      var text = res.hits.filter(function (h) { return !namedIds.has(h.id); });
      var hiddenUrl = "#/search?" + new URLSearchParams({ q: q, hidden: includeHidden ? "0" : "1" });
      var html = ['<h1 class="search-title">Results for “' + esc(q) + "”</h1>",
        '<p class="search-opts"><a href="' + hiddenUrl + '">' +
        (includeHidden ? "Hide" : "Include") + " hidden pages &amp; synonyms</a></p>"];
      if (named.length) {
        html.push('<section><h2>Taxa</h2><ul class="results names">' + named.map(nameRow).join("") + "</ul></section>");
      }
      var shown = fold(q).split(/[^a-z0-9]+/).filter(function (w) { return w.length >= 2 && !STOP.has(w); });
      html.push("<section><h2>Pages mentioning " + shown.map(function (t) { return "“" + esc(t) + "”"; }).join(res.partial ? " or " : " and ") + "</h2>");
      if (res.partial) html.push('<p class="muted">No page has every word; showing partial matches.</p>');
      if (!text.length) {
        html.push('<p class="muted">' + (named.length ? "No other pages."
          : "No matches. Check the spelling, or try a common name or a genus.") + "</p>");
        var guess = named.length ? [] : didYouMean(q);
        if (guess.length) {
          html.push('<p class="muted">Did you mean ' + guess.map(function (n) {
            return '<a href="#/search?q=' + encodeURIComponent(n.display) + '">' + esc(n.display) + "</a>";
          }).join(", ") + "?</p>");
        }
      }
      html.push('<ul class="results text">' + text.slice(0, limit).map(function (h) {
        var n = byId.get(h.id);
        return '<li data-id="' + h.id + '"><a href="#/t/' + h.id + '">' + (n ? sciName(n.rank, n.name) : h.id) + "</a>" +
          (n && n.commons ? ' <span class="s-common">' + esc(n.commons) + "</span>" : "") +
          (n && n.ctx ? ' <span class="s-ctx">' + esc(n.ctx) + "</span>" : "") + '<p class="snip"></p></li>';
      }).join("") + "</ul>");
      if (text.length > limit) html.push('<button class="more" type="button">Show more (' + (text.length - limit) + " left)</button>");
      html.push("</section>");
      app.innerHTML = html.join("");
      if (keepY === null) restoreScroll(); else window.scrollTo(0, keepY);
      var more = app.querySelector("button.more");
      if (more) more.addEventListener("click", function () { renderSearch(q, includeHidden, limit + PAGE); });
      app.querySelectorAll(".results.text li").forEach(function (li) {
        loadRecord(Number(li.getAttribute("data-id"))).then(function (rec) {
          li.querySelector(".snip").innerHTML = snippet(rec, res.terms);
        }, function () {});
      });
    });
  }

  // Header box: suggestions as you type; Enter opens the highlighted taxon or full results.
  var qInput = document.getElementById("q");
  var suggest = document.getElementById("suggest");
  var form = document.getElementById("search-form");
  var active = -1, timer = null;

  function closeSuggest() {
    suggest.hidden = true; suggest.innerHTML = ""; active = -1;
    qInput.removeAttribute("aria-activedescendant");
    qInput.setAttribute("aria-expanded", "false");
  }
  function showSuggest() {
    var q = qInput.value;
    if (!q.trim()) { closeSuggest(); return; }
    loadNames().then(function () {
      if (qInput.value !== q) return;
      var hits = nameMatches(q, false, 8);
      qInput.setAttribute("aria-expanded", "true");
      suggest.innerHTML = hits.map(function (n, i) {
        return '<li role="option" id="sg-' + i + '" data-id="' + n.id + '">' + sciName(n.rank, n.name) +
          (n.commons ? ' <span class="s-common">' + esc(n.commons) + "</span>" : "") +
          ' <span class="s-rank">' + esc(n.rank) + "</span></li>";
      }).join("") + '<li role="option" class="all' + (hits.length ? "" : " only") +
        '" data-all="1">Search all text for “' + esc(q) + "”</li>";
      suggest.hidden = false;
      active = -1;
    });
  }
  function setActive(i) {
    var items = suggest.querySelectorAll("li");
    if (!items.length) return;
    active = (i + items.length) % items.length;
    items.forEach(function (li, j) { li.classList.toggle("active", j === active); });
    qInput.setAttribute("aria-activedescendant", items[active].id || "");
  }
  function choose(li) {
    if (li && li.getAttribute("data-id")) location.hash = "#/t/" + li.getAttribute("data-id");
    else location.hash = "#/search?" + new URLSearchParams({ q: qInput.value });
    closeSuggest();
    qInput.blur();
  }
  // The "/" shortcut hint only makes sense with a keyboard; keep the phone placeholder short.
  if (window.matchMedia("(max-width: 600px)").matches) qInput.placeholder = "Search names & text";
  qInput.addEventListener("focus", function () { qInput.select(); });
  qInput.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(showSuggest, 60); });
  qInput.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") { e.preventDefault(); if (suggest.hidden) showSuggest(); else setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Escape") { closeSuggest(); }
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    choose(active >= 0 ? suggest.querySelectorAll("li")[active] : null);
  });
  suggest.addEventListener("mousedown", function (e) {
    var li = e.target.closest("li");
    if (li) { e.preventDefault(); choose(li); }
  });
  qInput.addEventListener("blur", function () { setTimeout(closeSuggest, 150); });
  document.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    if (e.key === "/" && tag !== "input" && tag !== "textarea") { e.preventDefault(); qInput.focus(); }
  });

  // Skip link: focus the content without touching the hash (the hash is the route).
  var skip = document.querySelector(".skip");
  if (skip) skip.addEventListener("click", function (e) { e.preventDefault(); app.focus(); });

  window.addEventListener("beforeprint", function () {
    app.querySelectorAll("details").forEach(function (d) { d.open = true; });
  });


  function renderSiteFooter() {
    var el = document.getElementById("site-footer");
    if (el && meta) {
      el.innerHTML = esc(meta.title + " " + meta.subtitle) + " · built " + fmtDate(meta.built_at) +
        " · Every photo, record and text carries its own credit and licence; see each page's " +
        "Sources section. · " + ext("https://github.com/mandrewj/guam_insects", "Source code") + " (MIT)" +
        (meta.target === "local" ? ' · <a href="admin.html">Curate</a> (needs <code>guaminsects serve</code>)' : "");
    }
  }
})();
