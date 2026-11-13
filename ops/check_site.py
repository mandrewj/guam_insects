"""Smoke-test the built site via file:// in real browsers (ported from entobase).

    uv run python ops/check_site.py                  # Chrome + WebKit + Firefox, desktop + phone
    uv run python ops/check_site.py --shots /tmp/s   # also save screenshots of key pages
    uv run python ops/check_site.py --browsers chrome --target local

Fixtures (Catalogue of Life ids): B6LCL Odonata, BZS Libellulidae, 4CGSL Pantala flavescens
(photos, Wikipedia, literature). WebKit/Firefox need `uv run playwright install webkit firefox` once; missing
browsers are skipped. Exit status 1 if any check fails. Photos are hotlinked, so the image
check needs the network.
"""

import argparse
import csv
import io
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from guaminsects import ids  # noqa: E402  (id parity check)
from guaminsects.search import tokens  # noqa: E402  (tokenizer parity check)

SIZES = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 390, "height": 844}}
ID_SAMPLES = ["KVC9L", "4CGSL", "N", "gbif:1045882", "name-12", "IOG-3"]
TOKEN_SAMPLES = ["Mécoptères du Québec", "Globe skimmers and Wandering gliders",
                 "the mosses & bus", "Pantala flavescens's species-group", "glass ibis classes"]
ORDER, FAMILY, SPECIES = "B6LCL", "BZS", "4CGSL"
SHOTS = {"home": "", "family": f"#/t/{FAMILY}", "species": f"#/t/{SPECIES}",
         "identify": f"#/id/{ORDER}", "search": "#/search?q=wandering%20glider"}


def click(page, selector: str) -> None:
    """A pointer click, except on WebKit: Playwright's WebKit driver on macOS 26 refuses every
    pointer click ("<html> intercepts pointer events"), even on a one-button test page, so
    there the click is dispatched as an event. Chrome and Firefox get real clicks."""
    if page.context.browser.browser_type.name == "webkit":
        page.locator(selector).first.dispatch_event("click")
    else:
        page.click(selector)


def check(page, url: str) -> dict[str, bool]:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    r = {}
    page.goto(url)
    page.wait_for_selector(".hero", timeout=10_000)
    r["home lists orders"] = page.locator("#s-children .card").count() >= 10
    r["tokenizer parity"] = all(page.evaluate("s => guaminsects.tokens(s)", s) == tokens(s)
                                for s in TOKEN_SAMPLES)
    r["id parity"] = all(page.evaluate("s => guaminsects.ids.tidOf(s)", s) == ids.to_int(s) and
                         page.evaluate("n => guaminsects.ids.extOf(n)", ids.to_int(s)) == s
                         for s in ID_SAMPLES)
    page.goto(url + f"#/t/{FAMILY}")
    page.wait_for_selector(".taxon-head h1")
    page.evaluate("document.querySelectorAll('img[loading=lazy]').forEach(i => i.loading = 'eager')")
    page.wait_for_timeout(1500)
    r["no broken images"] = page.evaluate(
        "[...document.images].every(i => !i.complete || i.naturalWidth > 0)")
    r["no sideways scroll"] = page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    r["presence table"] = page.locator("table.presence tr.r-gu").count() == 1
    r["region tooltips"] = "Mariana" in (page.locator("table.presence tr.r-gu abbr")
                                          .get_attribute("title") or "")
    r["checklist"] = page.locator(".checklist .cl a").count() > 10
    click(page, ".checklist button[data-cl='open']")
    r["checklist expands"] = page.evaluate(
        "[...document.querySelectorAll('.checklist details')].every(d => d.open)")
    # Taxonomy download: this family and everything under it, then the whole tree.
    rows = {}
    for key in (str(FAMILY), "all"):
        with page.expect_download() as dl:
            click(page, f"button[data-dl='{key}']")
        text = Path(dl.value.path()).read_text(encoding="utf-8-sig")
        rows[key] = list(csv.DictReader(io.StringIO(text)))
    r["download this taxon"] = len(rows[str(FAMILY)]) > 10 and \
        rows[str(FAMILY)][0]["taxonID"] == str(FAMILY) and \
        all(x["family"] == "Libellulidae" for x in rows[str(FAMILY)])
    r["download everything"] = len(rows["all"]) > 1000 and rows["all"][0]["taxonRank"] == "Subphylum"
    page.evaluate("window.scrollTo(0, 600)")
    page.wait_for_timeout(150)
    y = page.evaluate("scrollY")
    page.evaluate("document.querySelector('.cards a.card').click()")
    page.wait_for_function(f"!location.hash.endsWith('/{FAMILY}')")
    page.wait_for_selector(".taxon-head h1")
    r["link opens at top"] = page.evaluate("scrollY") == 0
    page.go_back()
    page.wait_for_selector(".taxon-head h1:has-text('Libellulidae')")
    page.wait_for_timeout(300)
    r["back restores scroll"] = abs(page.evaluate("scrollY") - y) < 5
    page.focus("#q")
    page.keyboard.type("globe ski")
    page.wait_for_selector("#suggest li[data-id]")
    r["name suggestions"] = any("Pantala" in t for t in
                                page.locator("#suggest li[data-id]").all_inner_texts())
    page.keyboard.press("Escape")
    page.goto(url + "#/search?q=migration")
    page.wait_for_selector(".results.text li, .muted", timeout=8_000)
    r["full-text search"] = page.locator(".results.text li").count() > 0
    page.goto(url + f"#/t/{SPECIES}")
    page.wait_for_selector(".g-main")
    # A DOM click: what matters is that the jump keeps the route (WebKit's hit-testing of
    # the sticky header can intercept a synthetic pointer click here).
    page.evaluate("document.querySelector(\"a.jump[data-target='s-literature']\").click()")
    page.wait_for_timeout(300)
    r["jump keeps route"] = page.url.endswith(f"#/t/{SPECIES}")
    r["literature listed"] = page.locator("#s-literature li").count() > 0
    r["wikipedia collapsed"] = page.locator(".wiki-body[open]").count() == 0
    click(page, "button.g-main")
    page.wait_for_selector(".lightbox img", state="visible", timeout=5_000)
    r["lightbox opens"] = page.locator(".lightbox[role=dialog]").first.is_visible()
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    r["lightbox closes"] = not page.locator(".lightbox").first.is_visible()
    # Identify: the toggle lands on the taxon in view; island chips filter and combine.
    page.goto(url + f"#/t/{ORDER}")
    page.wait_for_selector(".taxon-head h1")
    click(page, "#identify")
    page.wait_for_selector(".ip-grid .ip", timeout=8_000)
    r["identify lands on this taxon"] = page.url.endswith(f"#/id/{ORDER}")
    allp = page.locator(".ip").count()
    click(page, "#identify")
    page.wait_for_selector(".taxon-head h1")
    r["identify toggles back"] = page.url.endswith(f"#/t/{ORDER}")
    page.goto(url + f"#/id/{ORDER}?r=mh")
    page.wait_for_selector(".ip-count")
    mh = page.locator(".ip").count()
    r["island filter narrows"] = 0 < mh < allp
    r["island filter explains"] = "recorded from Marshalls" in page.locator(".ip-count").inner_text()
    click(page, ".chip.r-pw")
    page.wait_for_selector(".ip-count")
    r["islands combine"] = page.url.endswith("?r=pw,mh") and page.locator(".ip").count() >= mh
    click(page, ".chip.r-pw")
    page.wait_for_selector(".ip-count")
    r["islands deselect"] = page.url.endswith("?r=mh")
    page.goto(url + "#/search?q=the")
    page.reload()
    page.wait_for_selector("h1.search-title, .results, .muted", timeout=8000)
    r["stopword search cold"] = "Searching" not in page.locator("#app").inner_text()
    r["no JS errors"] = not errors
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--browsers", default="chrome,webkit,firefox")
    ap.add_argument("--target", default="public", choices=["public", "local"])
    ap.add_argument("--shots", type=Path, help="directory for screenshots")
    args = ap.parse_args()
    site = ROOT / "site" / args.target / "index.html"
    if not site.exists():
        print(f"no build at {site}; run `uv run guaminsects build {args.target}`")
        return 1
    url = site.as_uri()
    failed = False
    with sync_playwright() as p:
        engines = {"chrome": (p.chromium, {}), "webkit": (p.webkit, {}), "firefox": (p.firefox, {})}
        for name in args.browsers.split(","):
            launcher, opts = engines[name]
            try:
                browser = launcher.launch(headless=True, **opts)
            except PlaywrightError:
                print(f"{name:8} skipped (not installed)")
                continue
            for size, viewport in SIZES.items():
                touch = size == "phone" and name != "firefox"
                # Reduced motion: the app then scrolls instantly, so a click never lands while
                # a smooth scroll is still moving the page (WebKit reported the click blocked).
                ctx = browser.new_context(viewport=viewport, is_mobile=touch, has_touch=touch,
                                          reduced_motion="reduce")
                results = check(ctx.new_page(), url)
                bad = [k for k, ok in results.items() if not ok]
                failed |= bool(bad)
                print(f"{name:8} {size:8} {'ok' if not bad else 'FAILED: ' + ', '.join(bad)}")
                if args.shots:
                    args.shots.mkdir(parents=True, exist_ok=True)
                    page = ctx.new_page()
                    for label, frag in SHOTS.items():
                        page.goto(url + frag)
                        page.wait_for_selector(".taxon-head, .search-title, .hero")
                        page.wait_for_timeout(400)
                        page.screenshot(path=args.shots / f"{name}-{size}-{label}.png")
                ctx.close()
            browser.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
