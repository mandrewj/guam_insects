/* entobase offline app: renders taxon pages from data/t/<bucket>/<id>.js records.
 * Works from file:// because data is loaded with <script> tags, not fetch(). */
(function () {
  "use strict";

  var app = document.getElementById("app");
  var records = new Map();   // id -> record
  var waiting = new Map();   // id -> {resolve, reject}
  var meta = null;

  var ITALIC_RANKS = { Genus: 1, Subgenus: 1, Species: 1, Subspecies: 1 };
  var SECTION_NOTE = "Text from BugGuide.net";

  // ------------------------------------------------------------------ data loading
  window.entobase = {
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
    if (!id) { app.innerHTML = "<p>No data has been built yet. Run <code>entobase build-site</code>.</p>"; return; }
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

  // ------------------------------------------------------------------ rendering
  function renderMissing(id) {
    setIdentify(false);
    app.innerHTML = '<div class="notice">Taxon ' + esc(id) + " isn't in this build yet. " +
      ext("https://bugguide.net/node/view/" + id, "View it on BugGuide") + ".</div>";
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
    document.title = r.name + (r.common ? " – " + r.common : "") + " · entobase";
    var html = [];
    if (isHome) html.push(homeIntro());
    html.push(breadcrumb(r));
    html.push(header(r));
    // Two columns: the photo, at-a-glance and classification stay put on the left while the
    // reading column scrolls. The photo used to sit beside the jump links and left the row empty.
    // The home page has no photo of its own and leads with the orders.
    html.push('<div class="layout"><aside class="side">');
    if (!isHome) html.push(gallery(r));
    html.push(facts(r));
    html.push(conservation(r));
    html.push(classification(r));
    html.push(links(r));
    html.push('</aside><div class="main">');
    if (!isHome) html.push(pageNav(r));
    if (r.status !== "parsed") {
      html.push('<div class="notice">Details for this taxon haven\'t been collected yet; ' +
                "they'll appear after a future crawl.</div>");
    }
    html.push(familyIndex(r));
    html.push(children(r));
    html.push(sections(r));
    html.push(hostPlants(r));
    html.push(factSheets(r));
    html.push(wikipedia(r));
    html.push(worksCited(r));
    html.push("</div></div>");
    html.push(attribution(r));
    app.innerHTML = html.join("");
    pinSide();
    var crumbs = app.querySelector(".crumbs ol");
    if (crumbs) crumbs.scrollLeft = crumbs.scrollWidth;   // phones: show the nearest parents
    qInput.value = "";
    restoreScroll();
  }

  // Identify: every taxon in a group side by side, each with its picture and its range,
  // because those are the two things that separate look-alikes at a glance. Selecting one
  // goes a rank deeper while it still has members, and opens the page when it does not.
  function identifyPanel(c, keys) {
    var href = c.kids ? identifyHref(c.id, keys) : "#/t/" + c.id;
    var filtering = keys.length > 0;
    var unknown = !c.regions;
    var pic = c.thumb
      ? '<img class="ip-photo" src="' + esc(c.thumb) + '" alt="" loading="lazy">'
      : '<span class="ip-photo ip-none">' + esc(initials(c.name)) + "</span>";
    var map = c.map
      ? '<span class="ip-map"><img src="' + esc(meta.basemap) + '" alt="" loading="lazy">' +
        '<img class="ip-overlay" src="' + esc(c.map) + '" alt="" loading="lazy"></span>'
      : '<span class="ip-map ip-none" title="No GBIF records mapped">no range map</span>';
    var sub = (c.rank === "Species" || c.rank === "Subspecies")
      ? esc(c.common || "")
      : (c.species_count ? c.species_count + " species" : esc(displayRank(c.rank, c.name)));
    return '<a class="ip' + (filtering && unknown ? " ip-unknown" : "") + '" href="' + href + '">' +
      '<span class="ip-figures">' + pic + map + "</span>" +
      '<span class="ip-name">' + sciName(c.rank, c.name) + "</span>" +
      '<span class="ip-sub">' + sub + (c.kids ? " ›" : "") +
      (filtering && unknown ? ' <span class="ip-flag" title="No state or province records, ' +
        'so we cannot say whether it occurs here">no range data</span>' : "") +
      "</span></a>";
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
        identifyHref(r.id, withRegion(keys, x.key)) + '" role="button" aria-pressed="' + on + '">' +
        esc(x.label) + "</a>";
    }).join("");
    var clear = keys.length
      ? '<a class="chip chip-clear" href="' + identifyHref(r.id, []) + '">Clear</a>' : "";
    var note = keys.length
      ? '<p class="ip-count">' + counts.hit + " recorded in " +
        esc(keys.map(regionLabel).join(" or ")) +
        (counts.unknown ? " · " + counts.unknown + " with no range data" : "") +
        (counts.out ? " · " + counts.out + " not recorded there" : "") + "</p>"
      : "";
    return '<nav class="ip-filter" aria-label="Region">' + chips + clear + "</nav>" + note +
      '<details class="ip-mapkey"><summary>What the regions cover</summary>' +
      '<p class="muted">A taxon counts as recorded in a region when GBIF has an occurrence in one of its states or provinces ' +
      '(NatureServe state ranks where GBIF has none); a genus or family takes the union of its species.</p>' +
      '<img src="assets/img/regions.svg" alt="Map of the four regions, shaded by colour. ' +
      'Texas is in both the southeast and the southwest, California in both the southwest ' +
      'and the northwest." loading="lazy"></details>';
  }

  function renderIdentify(r, keys) {
    currentId = r.id;
    document.title = "Identify: " + r.name + " · entobase";
    var kids = r.children.filter(function (c) { return !c.hidden; });
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
          : '<p class="muted">Nothing here is recorded in ' +
            esc(keys.map(regionLabel).join(" or ")) + '. <a href="' +
            identifyHref(r.id, []) + '">Clear the filter</a>.</p>')
      : '<p class="muted">Nothing below ' + sciName(r.rank, r.name) + " to compare. " +
        '<a href="#/t/' + r.id + '">Open its page</a> instead.</p>';
    app.innerHTML = breadcrumb(r) +
      '<header class="taxon-head"><div class="head-line">' +
      '<span class="rank-chip">Identify</span><h1>' + sciName(r.rank, r.name) + "</h1>" +
      '<p class="badges"><a class="ip-exit" href="#/t/' + r.id + '">Full page</a></p></div>' +
      (kids.length ? '<p class="common">' + kids.length + " to compare" +
        (r.children.length > kids.length ? " (" + (r.children.length - kids.length) + " placeholder or fossil page" +
          (r.children.length - kids.length === 1 ? "" : "s") + " left out)" : "") + "</p>" : "") +
      "</header>" + body;
    setIdentify(true);
    restoreScroll();
  }

  // Breadcrumb from Insecta (this reference's root) down to the parent.
  function breadcrumb(r) {
    var start = 0;
    r.lineage.forEach(function (a, i) { if (a.name === LINK_FROM) start = i; });
    var trail = r.lineage.slice(start);
    if (!trail.length) return "";
    return '<nav class="crumbs" aria-label="Taxonomy"><ol>' + trail.map(function (a) {
      return '<li><a href="#/t/' + a.id + '" title="' + esc(a.rank) + (a.common ? ": " + esc(a.common) : "") +
        '">' + sciName(a.rank, a.name) + "</a></li>";
    }).join("") + "</ol></nav>";
  }

  // "On this page" chips; links scroll within the page (the hash is the route).
  function pageNav(r) {
    var items = [];
    if (r.children.length) items.push(["s-children", "Included taxa"]);
    r.sections.forEach(function (s) { items.push(["s-" + s.key, s.heading]); });
    if (r.map && !r.sections.some(function (s) { return s.key === "range"; })) items.push(["s-map", "Distribution"]);
    if (r.hosts.length) items.push(["s-hosts", "Host plants"]);
    if (r.factsheets.length) items.push(["s-sheets", "Fact sheets"]);
    if (r.wikipedia) items.push(["s-wikipedia", "Wikipedia"]);
    if (r.works_cited.length) items.push(["s-refs", "Works cited"]);
    items.push(["s-sources", "Sources"]);
    if (items.length < 4) return "";
    return '<nav class="page-nav" aria-label="On this page"><span class="pn-label">On this page</span>' +
      items.map(function (x) {
        return '<a href="#" class="jump" data-target="' + esc(x[0]) + '">' + esc(x[1]) + "</a>";
      }).join("") + "</nav>";
  }

  function homeIntro() {
    var c = meta.counts, stats = [
      [c.taxa, "taxa"], [c.parsed, "with full BugGuide details"], [c.species, "species"],
      [c.photos, "with photos"], [c.maps, "with range maps"]];
    return '<section class="hero"><p class="lede">An offline reference to North American insects, ' +
      "built from BugGuide, iNaturalist, Wikipedia and GBIF. Start below with the insect orders, " +
      'or press <kbd>/</kbd> to search.</p><ul class="stats">' + stats.filter(function (x) {
        return x[0] != null;
      }).map(function (x) {
        return "<li><strong>" + Number(x[0]).toLocaleString() + "</strong> " + esc(x[1]) + "</li>";
      }).join("") + '</ul><p class="fresh">Data updated ' + fmtDate(meta.built_at) + "</p></section>";
  }

  function header(r) {
    var badges = [];
    if (r.placeholder) badges.push('<span class="badge warn">Placeholder page (' + esc(r.placeholder.replace("_", " ")) + ")</span>");
    if (r.fossil) badges.push('<span class="badge fossil">Fossil taxon</span>');
    if (r.status !== "parsed") badges.push('<span class="badge muted">Details pending</span>');
    var commons = [];
    if (r.common) commons.push(esc(r.common));
    if (r.inat && r.inat.common && (!r.common || r.inat.common.toLowerCase() !== r.common.toLowerCase())) {
      commons.push(esc(r.inat.common) + ' <span class="src">(iNaturalist)</span>');
    }
    var bw = r.bugwood;
    if (bw && bw.common && commons.every(function (c) { return c.toLowerCase().indexOf(bw.common.toLowerCase()) !== 0; })) {
      commons.push(esc(bw.common) + ' <span class="src">(Bugwood)</span>');
    }
    // Rank, name and badges share one line: five stacked rows used to push the photo and
    // the first real content most of the way down the opening screen.
    return '<header class="taxon-head"><div class="head-line">' +
      '<span class="rank-chip">' + esc(displayRank(r.rank, r.name)) + "</span>" +
      "<h1>" + sciName(r.rank, r.name) +
      (r.authority ? ' <span class="authority">' + esc(r.authority) + "</span>" : "") + "</h1>" +
      (badges.length ? '<p class="badges">' + badges.join(" ") + "</p>" : "") + "</div>" +
      (commons.length ? '<p class="common">' + commons.join(" · ") + "</p>" : "") +
      (!r.photos.length && r.status === "parsed"
        ? '<p class="muted nophoto">No openly licensed photo yet. ' + ext(r.sources.bugguide.url, "BugGuide") + " may have one.</p>" : "") +
      (bw && (bw.guilds.length || bw.nativity)
        ? '<p class="guilds" title="Bugwood">' + bw.guilds.concat(bw.nativity ? [bw.nativity] : []).map(function (g) {
            return '<span class="chip-tag">' + esc(g) + "</span>"; }).join(" ") + "</p>" : "") + "</header>";
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
    if (c.placeholder) sub.push("placeholder: " + esc(c.placeholder.replace("_", " ")));
    if (c.fossil) sub.push("fossil");
    return '<li><a class="card' + (c.thumb || withTile ? " has-thumb" : "") + '" href="#/t/' + c.id + '">' +
      (c.thumb ? '<img class="card-thumb" src="' + esc(c.thumb) + '" alt="" loading="lazy">'
               : withTile ? '<span class="card-thumb tile" aria-hidden="true">' + esc(initials(c.name)) + "</span>" : "") +
      '<span class="card-rank">' + esc(displayRank(c.rank, c.name)) +
      '</span><span class="card-name">' + sciName(c.rank, c.name) + "</span>" +
      (sub.length ? '<span class="card-sub">' + sub.join(" · ") + "</span>" : "") + "</a></li>";
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
    var shown = r.children.filter(function (c) { return !c.hidden; });
    var hidden = r.children.filter(function (c) { return c.hidden; });
    // If any card has a photo, give the others a lettered tile so the grid lines up.
    var tiles = function (list) {
      var any = list.some(function (c) { return c.thumb; });
      return list.map(function (c) { return childCard(c, any); }).join("");
    };
    var out = '<section class="browse" id="s-children"><h2>Included taxa</h2>';
    if (shown.length && r.child_groups.length) {
      // Curated order (curation.toml): each group under a small heading, then any others.
      var byId = new Map(shown.map(function (c) { return [c.id, c]; })), used = new Set();
      var withTile = shown.some(function (c) { return c.thumb; });
      var grid = function (list) { return '<ul class="cards">' + list.map(function (c) { return childCard(c, withTile); }).join("") + "</ul>"; };
      r.child_groups.forEach(function (g) {
        var list = g.ids.map(function (id) { return byId.get(id); }).filter(Boolean);
        list.forEach(function (c) { used.add(c.id); });
        if (list.length) out += (g.label ? '<h3 class="group-label">' + esc(g.label) + "</h3>" : "") + grid(list);
      });
      var rest = shown.filter(function (c) { return !used.has(c.id); });
      if (rest.length) out += '<h3 class="group-label">Other</h3>' + grid(rest);
      if (r.child_order_source) out += '<p class="order-note">Listed in phylogenetic order, after ' + esc(r.child_order_source) + "</p>";
    } else if (shown.length) {
      out += '<ul class="cards">' + tiles(shown) + "</ul>";
    }
    if (hidden.length) {
      out += '<details class="hidden-pages"><summary>Other pages (' + hidden.length +
        "): placeholders and fossils</summary><ul class=\"cards\">" + tiles(hidden) +
        "</ul></details>";
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
    var stack = '<img src="' + esc(m.basemap) + '" alt="Map of North America" loading="lazy">' +
      '<img class="map-overlay" src="' + esc(m.overlay) + '" alt="GBIF records of ' + esc(r.name) + '" loading="lazy">';
    return '<figure class="map">' + (m.key
      ? '<a class="map-stack" href="https://www.gbif.org/occurrence/map?taxon_key=' + m.key +
        '&continent=NORTH_AMERICA" target="_blank" rel="noopener" title="Explore on GBIF">' + stack + "</a>"
      : '<div class="map-stack">' + stack + "</div>") +
      '<figcaption class="g-cap"><strong>' + Number(m.na_records).toLocaleString() +
      "</strong> georeferenced records in North America" + years + "." + groupNote(m) + " " + gbifCredit(m) + ".</figcaption></figure>";
  }

  // BugGuide sections, with the GBIF map placed right after Range (or first if there's no Range).
  function sections(r) {
    var map = mapFigure(r), placed = false;
    var body = r.sections.map(function (s) {
      var html = '<section class="info" id="s-' + esc(s.key) + '"><h2>' + esc(s.heading) + "</h2>" +
        '<div class="prose">' + s.html + "</div></section>";
      if (s.key === "range" && map) { placed = true; html += map; }
      return html;
    }).join("");
    if (!placed && map) body = '<section class="info" id="s-map"><h2>Distribution</h2>' + map + "</section>" + body;
    if (!r.sections.length) return body;
    return body + '<p class="section-note">' + SECTION_NOTE + " (" +
      ext(r.sources.bugguide.url, "original page") + "); see attribution below.</p>";
  }

  // Host plants (NHM HOSTS, CC0). Grouped by plant family, which is how a reader looks:
  // "does it eat anything in the carrot family?" rather than plant by plant.
  function hostPlants(r) {
    if (!r.hosts.length) return "";
    var families = [], byFamily = {};
    r.hosts.forEach(function (h) {
      var fam = h.family || "Unplaced";
      if (!byFamily[fam]) { byFamily[fam] = []; families.push(fam); }
      byFamily[fam].push(h);
    });
    families.sort();
    var body = families.map(function (fam) {
      return "<dt>" + esc(fam) + "</dt><dd>" + byFamily[fam].map(function (h) {
        return '<span class="host" title="' + h.n + " record" + (h.n === 1 ? "" : "s") +
          (h.where ? ": " + esc(h.where) : "") + '"><i>' + esc(h.name) + "</i></span>";
      }).join(", ") + "</dd>";
    }).join("");
    return '<section class="info" id="s-hosts"><h2>Host plants</h2>' +
      '<dl class="hosts">' + body + "</dl>" +
      '<p class="section-note">' + r.hosts.length + " recorded pairing" +
      (r.hosts.length === 1 ? "" : "s") + " from " + ext(HOSTS_URL, "NHM HOSTS") +
      " (CC0); hover a plant for the localities. Worldwide records, so some may be " +
      "outside North America.</p></section>";
  }

  // Extension fact sheets: identification and biology only, quoted verbatim and cited.
  // These are generally all rights reserved, so the source is named on every extract.
  function factSheets(r) {
    if (!r.factsheets.length) return "";
    var body = r.factsheets.map(function (d) {
      var secs = d.sections.map(function (sec) {
        return "<h3>" + esc(sec.heading) + "</h3>" +
          sec.text.split("\n").filter(function (p) { return p.trim(); })
            .map(function (p) { return "<p>" + esc(p) + "</p>"; }).join("");
      }).join("");
      return '<article class="sheet"><blockquote class="prose">' + secs + "</blockquote>" +
        '<p class="sheet-cite">' + ext(d.url, esc(d.title)) + " \u2014 " + esc(d.org) +
        (d.copyright ? ". " + esc(d.copyright) : "") + ". Quoted verbatim.</p></article>";
    }).join("");
    return '<section class="info" id="s-sheets"><h2>From extension fact sheets</h2>' + body +
      "</section>";
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
    var collapsed = r.sections.length > 0;   // with no BugGuide text, show the article in full
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

  function worksCited(r) {
    if (!r.works_cited.length) return "";
    return '<section class="refs" id="s-refs"><h2>Works cited</h2><ol>' + r.works_cited.map(function (w) {
      var bits = [];
      if (w.authors) bits.push(esc(stripDot(w.authors)));
      if (w.year) bits.push(esc(w.year));
      var line = bits.length ? bits.join(". ") + ". " : "";
      var pub = w.publication && w.publication !== w.year ? " " + esc(stripDot(w.publication)) + "." : "";
      var extra = [];
      if (w.doi) extra.push(ext("https://doi.org/" + w.doi, "doi:" + esc(w.doi)));
      (w.urls || []).slice(0, 2).forEach(function (u, i) { extra.push(ext(u, i ? "link" : "online")); });
      extra.push(ext(w.url, "BugGuide reference"));
      return '<li id="ref-' + w.id + '" value="' + esc(w.n) + '">' + line + "<cite>" + esc(w.title) +
        "</cite>" + (/[.?!]$/.test(w.title) ? "" : ".") + (pub || (w.cited_as && !w.authors ? " " + esc(w.cited_as) : "")) +
        ' <span class="ref-links">' + extra.join(" · ") + "</span></li>";
    }).join("") + "</ol></section>";
  }

  // Stat tiles: exact below 2,000, then ">2k", ">97k", ">1.2M" (exact value on hover).
  function compact(n) {
    if (n < 2000) return n.toLocaleString();
    if (n < 1e6) return ">" + Math.floor(n / 1000) + "k";
    return ">" + Math.floor(n / 1e5) / 10 + "M";
  }

  function facts(r) {
    var rows = [];
    // The third item is the tile's tone: our own counts in the page accent, then one hue
    // per outside source, so a number's origin reads without checking the label.
    if (r.rank !== "Species" && r.species_count) rows.push(["Species", r.species_count, ""]);
    if (r.children.length) rows.push(["Included taxa", r.children.length, ""]);
    if (r.inat && r.inat.observations) rows.push(["iNat obs. (N.\u00a0Am.)", r.inat.observations, " t-inat"]);
    if (r.map && r.map.na_records) rows.push(["GBIF records (N.\u00a0Am.)", r.map.na_records, " t-gbif"]);
    if (!rows.length) return "";
    return '<div class="box"><h3>At a glance</h3><dl class="facts">' + rows.map(function (x) {
      return '<div class="fact' + x[2] + '" title="' + esc(x[0]) + ": " + Number(x[1]).toLocaleString() +
        '"><dd>' + esc(compact(Number(x[1]))) + "</dd><dt>" + esc(x[0]) + "</dt></div>";
    }).join("") + "</dl></div>";
  }

  // Conservation status (NatureServe, CC BY). The G rank is the headline; the state and
  // province ranks double as the clearest statement of where the species is known from.
  var RANK_TONE = { G1: "t-crit", G2: "t-crit", G3: "t-warn", G4: "t-ok", G5: "t-ok" };
  function conservation(r) {
    var c = r.conservation;
    if (!c || !c.rank) return "";
    var nations = Object.keys(c.nations).sort().map(function (k) {
      return esc(k) + "\u00a0" + esc(c.nations[k]);
    }).join(" · ");
    var native = c.states.filter(function (s) { return s.native; });
    var n = c.states.length, places = n + (n === 1 ? " state or province" : " states or provinces");
    var where = n
      ? '<p class="cs-where" title="' + esc(c.states.map(function (s) {
          return s.code + " " + (s.rank || "?") + (s.native ? "" : " (introduced)");
        }).join(", ")) + '">' + (native.length === 0
          ? "Introduced; recorded in " + places
          : "Recorded in " + places + (native.length < n
            ? ", native in " + native.length + ", introduced in " + (n - native.length) : "")) + "</p>"
      : "";
    return '<div class="box"><h3>Conservation status</h3>' +
      '<p class="cs-rank ' + (RANK_TONE[c.rank] || "t-unranked") + '"><strong>' + esc(c.rank) +
      "</strong>" + (c.meaning ? " " + esc(c.meaning) : "") + "</p>" +
      (nations ? '<p class="cs-nations" title="G = global, N = national, S = state or province. ' +
        'NNA and SNA mean not applicable: the species is not native there.">' + nations + "</p>" : "") + where +
      '<p class="cs-src">' + ext(c.url || NATURESERVE_URL, "NatureServe") + "</p></div>";
  }

  // Classification: every rank from Kingdom down; Insecta and everything below it link to
  // their pages (the higher ranks are outside this reference's scope).
  var LINK_FROM = "Insecta";
  var HOSTS_URL = "https://doi.org/10.5519/havt50xw";
  var NATURESERVE_URL = "https://explorer.natureserve.org/";
  function classification(r) {
    var chain = r.lineage.concat([{ id: r.id, rank: r.rank, name: r.name, common: r.common }]);
    var kingdom = r.classification.length && r.classification[0][0] === "Kingdom" ? r.classification[0][1] : "Animalia (Animals)";
    var linking = false;
    var rows = ['<tr><th>Kingdom</th><td>' + esc(kingdom) + "</td></tr>"];
    chain.forEach(function (a, i) {
      if (a.name === LINK_FROM) linking = true;
      var self = i === chain.length - 1;
      var label = sciName(a.rank, a.name) + (a.common ? ' <span class="c-common">' + esc(a.common) + "</span>" : "") +
        (self && r.authority ? '<span class="c-auth">' + esc(r.authority) + "</span>" : "");
      var cell = linking && !self ? '<a href="#/t/' + a.id + '">' + label + "</a>" : label;
      rows.push("<tr" + (self ? ' class="self"' : "") + "><th>" + esc(a.rank) + "</th><td>" + cell + "</td></tr>");
    });
    var path = chain.slice(Math.max(0, chain.length - 4), -1).filter(function (a) {
      return a.rank !== "No Taxon";
    }).map(function (a) { return sciName(a.rank, a.name); }).join(" › ");
    return '<details class="box classif-box"' + (narrow() ? "" : " open") + "><summary><h3>Classification</h3>" +
      (path ? '<span class="classif-path">' + path + "</span>" : "") + "</summary>" +
      '<table class="classif">' + rows.join("") + "</table></details>";
  }
  function narrow() { return window.matchMedia("(max-width: 860px)").matches; }

  function links(r) {
    var items = ['<li>' + ext(r.sources.bugguide.url, "BugGuide") + "</li>"];
    r.links.forEach(function (l) {
      var flag = l.confidence && l.confidence !== "high"
        ? ' <span class="badge ' + (l.confidence === "review" ? "warn" : "muted") + '" title="' +
          esc(l.note || "") + '">' + esc(l.confidence) + "</span>" : "";
      items.push("<li>" + ext(l.url, esc(l.label)) + flag + "</li>");
    });
    return '<div class="box"><h3>Elsewhere</h3><ul class="links">' + items.join("") + "</ul></div>";
  }

  function attribution(r) {
    var bg = r.sources.bugguide, rows = [];
    if (r.status === "parsed") {
      var authors = bg.contributors.filter(function (c) { return c.role === "author"; });
      var others = bg.contributors.filter(function (c) { return c.role !== "author"; });
      var person = function (c) { return ext(c.url, esc(c.name)); };
      rows.push("<li><strong>BugGuide</strong>: text, classification and references from " +
        ext(bg.url, "this BugGuide page") + "." +
        (authors.length ? " Contributed by " + authors.map(person).join(", ") +
          (bg.contributed_on ? " on " + esc(bg.contributed_on) : "") + "." : "") +
        (others.length ? " Additional contributions by " + others.map(person).join(", ") + "." : "") +
        (bg.updated_on ? " Last updated on BugGuide " + esc(bg.updated_on) + "." : "") +
        " Retrieved " + fmtDate(bg.fetched_at) + ". © the individual contributors; BugGuide is hosted by Iowa State University.</li>");
    } else {
      rows.push("<li><strong>BugGuide</strong>: name and position in the tree from " +
        ext(bg.url, "BugGuide") + "; page details not yet retrieved.</li>");
    }
    if (r.inline_images.length) {
      rows.push("<li><strong>Images in the text</strong>: " + r.inline_images.map(function (m) {
        return ext(m.url, "photo #" + m.id) + (m.photographer ? " © " + esc(m.photographer) +
          (m.year ? " " + esc(m.year) : "") : "");
      }).join("; ") + " (via BugGuide).</li>");
    }
    if (r.photos.length) {
      rows.push("<li><strong>Photos</strong>: " + r.photos.map(function (ph, i) {
        return (i + 1) + ") " + photoCaption(ph) + ", retrieved " + fmtDate(ph.retrieved);
      }).join("; ") + ". Resized copies; click a photo to enlarge it, and use its source link for the original.</li>");
    }
    if (r.map) rows.push("<li><strong>Map</strong>: " + gbifCredit(r.map) + ".</li>");
    if (r.wikipedia) rows.push("<li><strong>Wikipedia</strong>: text from the " + wikiCredit(r.wikipedia) + ".</li>");
    if (r.inat && (r.inat.common || r.inat.observations != null)) {
      rows.push("<li><strong>iNaturalist</strong>: " + (r.inat.common ? "common name and " : "") +
        "the count of observations in the United States and Canada, from " +
        ext("https://www.inaturalist.org/taxa/" + r.inat.id, "this iNaturalist taxon page") +
        ", read through the public API.</li>");
    }
    if (r.authority && r.authority_source) {
      var AUTH = { gbif: "GBIF", wikispecies: "Wikispecies (CC BY-SA)", wikidata: "Wikidata (CC0)", wikipedia: "Wikipedia (CC BY-SA)" };
      rows.push("<li><strong>Authority</strong>: the name's author and year come from " +
        esc(AUTH[r.authority_source] || r.authority_source) + ", since BugGuide gives none.</li>");
    }
    if (r.bugwood) {
      rows.push("<li><strong>Bugwood</strong>: common name, feeding guilds" + (r.bugwood.nativity ? ", native status" : "") +
        " and ITIS number from " + ext("https://developers.bugwoodcloud.org/", "Bugwood Center for Invasive Species and Ecosystem Health") +
        ", University of Georgia, read through their public API. Their photographs are not reproduced here" +
        (r.bugwood.images ? " (" + Number(r.bugwood.images).toLocaleString() + " exist; see the link above)" : "") + ".</li>");
    }
    if (r.links.length) {
      rows.push("<li><strong>Cross-links</strong>: matched via Wikidata, iNaturalist and Wikipedia; " +
        "matches below high confidence are labelled.</li>");
    }
    if (r.hosts.length) {
      rows.push("<li><strong>Host plants</strong>: " + ext(HOSTS_URL, "HOSTS \u2013 a Database " +
        "of the World's Lepidopteran Hostplants") + ", Robinson, Ackery, Kitching, Beccaloni " +
        "&amp; Hern\u00e1ndez (2023), Natural History Museum. Released CC0.</li>");
    }
    if (r.conservation && r.conservation.rank) {
      rows.push("<li><strong>Conservation status</strong>: NatureServe. " +
        new Date(r.built_at).getFullYear() + ". " + ext(NATURESERVE_URL,
        "NatureServe Explorer [web application]") + ". NatureServe, Arlington, Virginia. " +
        "Licensed CC\u00a0BY\u00a04.0.</li>");
    }
    if (r.factsheets.length) {
      rows.push("<li><strong>Extension fact sheets</strong>: " + r.factsheets.map(function (d) {
        return ext(d.url, esc(d.title)) + " (" + esc(d.org) +
          (d.copyright ? "; " + esc(d.copyright) : "") + ")";
      }).join("; ") + ". Identification and biology sections quoted verbatim; rights remain " +
        "with the publisher.</li>");
    }
    rows.push("<li><strong>This page</strong>: data built " + fmtDate(r.built_at) + ".</li>");
    return '<section class="attribution" id="s-sources"><h2>Sources &amp; attribution</h2><ul>' + rows.join("") +
      "</ul></section>";
  }

  // ------------------------------------------------------------------ search
  // Tokenizing must match src/entobase/search.py exactly (fold, split, stopwords, stem).
  var names = null;            // [{id, name, commons, rank, ctx, hidden, fname, fcommons, words}]
  var shards = new Map();      // shard key -> {term: postings}
  var scriptPromises = new Map();
  var STOP = null;

  window.entobase.names = function (rows) {
    names = rows.map(function (r) {
      var fname = fold(r[1]), fcommons = r[2] ? r[2].split(" | ").map(fold) : [];
      return { id: r[0], name: r[1], commons: r[2], rank: r[3], ctx: r[4], hidden: !!r[5],
               fname: fname, fcommons: fcommons,
               words: (fname + " " + fcommons.join(" ")).split(/[^a-z0-9]+/).filter(Boolean) };
    });
  };
  window.entobase.ft = function (key, data) { shards.set(key, data); };
  window.entobase.tokens = function (s) { return tokens(s); };   // exposed for tests

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
    document.title = (q ? q + " · " : "") + "Search · entobase";
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
        (includeHidden ? "Hide" : "Include") + " placeholder &amp; fossil pages</a></p>"];
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
      el.innerHTML = "entobase · offline build " + fmtDate(meta.built_at) +
        " · Content belongs to its credited authors and sources; for personal reference. " +
        "BugGuide text and images are not licensed for AI training.";
    }
  }
})();
