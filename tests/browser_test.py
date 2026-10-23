"""Browser checks for the website (Milestone 2-4 tests: T2.1-T2.5, T3.1-T3.7, T4.1-T4.8).

Run:  python tests/seed.py            (sample data first)
      python tests/browser_test.py [screenshot_dir]
Needs .env, Python Playwright and Pillow; drives the installed Microsoft Edge.
Serves the site itself on http://localhost:8765. Items it adds are named __test__...
and are removed (with their photos) at the end using the service key.
"""

import io
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib import request

from PIL import Image
from playwright.sync_api import sync_playwright

from smoke_test import BASE, ROOT, SERVICE, TEST_PREFIX, TOKEN, call

PORT = 8765
URL = f"http://localhost:{PORT}/"
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None

results = []


def check(label, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        -> {detail}"))


def db_rows():
    status, body = call("GET", "/rest/v1/jellycats?deleted_at=is.null&select=id,name,nickname,notes,status,category,photo_path",
                        key=SERVICE)
    assert status == 200, body
    return {r["id"]: r for r in body}


def shown_ids(page):
    return page.eval_on_selector_all("#grid .card", "cards => cards.map(c => c.dataset.id)")


def count_label(page):
    return page.text_content("#count")


def wait_loaded(page):
    page.wait_for_function("!document.querySelector('.spinner')")


def matches(row, q):
    return any(f and q in f.lower() for f in (row["name"], row["nickname"], row["notes"]))


def run_m2(browser):
    rows = db_rows()
    owned = {i for i, r in rows.items() if r["status"] == "owned"}
    wish = {i for i, r in rows.items() if r["status"] == "wishlist"}
    page = browser.new_page(viewport={"width": 375, "height": 800})
    page.goto(URL)
    wait_loaded(page)

    print("\nT2.1 Seeded rows render")
    ids = shown_ids(page)
    check(f"collection shows all {len(owned)} owned rows", set(ids) == owned, f"{ids}")
    check("count label matches", count_label(page) == f"{len(owned)} Jellycats", count_label(page))
    with_photo = {i for i in owned if rows[i]["photo_path"]}
    page.wait_for_function("[...document.querySelectorAll('#grid img')].every(i => i.complete)", timeout=15000)
    loaded = page.eval_on_selector_all(
        "#grid .card", "cards => cards.filter(c => c.querySelector('img')?.naturalWidth > 0).map(c => c.dataset.id)")
    check(f"all {len(with_photo)} photos display", set(loaded) == with_photo, f"{loaded}")
    check("cards without a photo show the placeholder",
          page.locator("#grid .placeholder").count() == len(owned) - len(with_photo),
          page.locator("#grid .placeholder").count())
    if SHOTS:
        page.screenshot(path=SHOTS / "phone-collection.png", full_page=True)

    print("\nT2.2 Search")
    page.fill("#search", "bun")
    expected = {i for i in owned if matches(rows[i], "bun")}
    check(f"'bun' shows only the {len(expected)} matching cards", set(shown_ids(page)) == expected,
          f"{shown_ids(page)} vs {expected}")
    page.fill("#search", "sleeps on")
    check("search looks in notes too", set(shown_ids(page)) == {i for i in owned if matches(rows[i], "sleeps on")},
          f"{shown_ids(page)}")
    page.fill("#search", "zzz-nothing")
    check("no-match message appears", "No Jellycats match" in page.text_content("#status"),
          page.text_content("#status"))
    page.fill("#search", "")
    check("clearing restores all", set(shown_ids(page)) == owned, f"{shown_ids(page)}")

    print("\nT2.3 Tabs and category filter")
    page.click("[data-tab=wishlist]")
    check("wishlist tab shows only wishlist items", set(shown_ids(page)) == wish, f"{shown_ids(page)}")
    check("section title switches", page.text_content("#section-title").strip().lower() == "wishlist",
          page.text_content("#section-title"))
    check("wishlist cards have a badge", page.locator("#grid .badge").count() == len(wish),
          page.locator("#grid .badge").count())
    page.click("[data-tab=owned]")
    check("collection tab shows only owned items", set(shown_ids(page)) == owned, f"{shown_ids(page)}")
    page.select_option("#category", "Bunnies")
    bunnies = {i for i in owned if rows[i]["category"] == "Bunnies"}
    check("category filter works", set(shown_ids(page)) == bunnies, f"{shown_ids(page)}")
    page.fill("#search", "blossom")
    both = {i for i in bunnies if matches(rows[i], "blossom")}
    check("category + search combine", set(shown_ids(page)) == both and both, f"{shown_ids(page)}")
    page.fill("#search", "")
    page.select_option("#category", "")

    print("\nT2.4 Layout")
    for width in (375, 1280):
        page.set_viewport_size({"width": width, "height": 800})
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        cols = page.evaluate("getComputedStyle(document.querySelector('#grid')).gridTemplateColumns.split(' ').length")
        check(f"{width}px: no sideways scroll ({cols} columns)", overflow <= 0, f"overflows by {overflow}px")
        if SHOTS and width == 1280:
            page.screenshot(path=SHOTS / "desktop-collection.png", full_page=True)
    page.close()

    print("\nT2.5 Error, retry and empty states")
    page = browser.new_page(viewport={"width": 375, "height": 800})
    page.route("**/rest/v1/**", lambda route: route.abort())
    page.goto(URL)
    page.wait_for_selector(".status.is-error")
    check("network blocked: error message shown", "Couldn't load" in page.text_content("#status"),
          page.text_content("#status"))
    if SHOTS:
        page.screenshot(path=SHOTS / "phone-error.png")
    page.unroute("**/rest/v1/**")
    page.click("#status button")
    wait_loaded(page)
    check("retry loads the cards", set(shown_ids(page)) == owned, f"{shown_ids(page)}")
    page.close()

    page = browser.new_page(viewport={"width": 375, "height": 800})
    page.route("**/rest/v1/jellycats**", lambda route: route.fulfill(status=200, json=[]))
    page.goto(URL)
    wait_loaded(page)
    check("no rows: empty message shown", "waiting to grow" in page.text_content("#status"),
          page.text_content("#status"))
    check("no rows: count says 0", count_label(page) == "0 Jellycats", count_label(page))
    if SHOTS:
        page.screenshot(path=SHOTS / "phone-empty.png")
    page.close()


# ───── Milestone 3 ─────

PHOTOS_SEEN = set()
TMP = Path(tempfile.mkdtemp(prefix="jellycat-test-"))


def big_photo():
    """A 4032x3024 phone-sized JPEG, over 5 MB: smooth colours plus grain, like a real photo."""
    w, h = 4032, 3024
    ramp = Image.linear_gradient("L").resize((w, h))
    img = Image.merge("RGB", (ramp, ramp.rotate(90).resize((w, h)), Image.new("L", (w, h), 180)))
    grain = Image.effect_noise((w, h), 40).convert("RGB")
    img = Image.blend(img, grain, 0.25)
    path = TMP / "big.jpg"
    img.save(path, quality=97)
    return path


def rotated_photo():
    """Stored 400 wide x 200 tall, with the EXIF tag a phone writes when held upright (displays 200x400)."""
    img = Image.new("RGB", (400, 200), (220, 120, 120))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise to display
    path = TMP / "rotated.jpg"
    img.save(path, exif=exif)
    return path


def small_photo(colour, name):
    path = TMP / name
    Image.new("RGB", (300, 300), colour).save(path)
    return path


def test_rows():
    status, body = call("GET", f"/rest/v1/jellycats?name=like.{TEST_PREFIX}*&select=*", key=SERVICE)
    assert status == 200, body
    for r in body:
        if r["photo_path"]:
            PHOTOS_SEEN.add(r["photo_path"])
    return body


def test_row(name):
    rows = [r for r in test_rows() if r["name"] == name]
    assert len(rows) == 1, f"expected one row named {name}, found {len(rows)}"
    return rows[0]


def stored_photo(path):
    with request.urlopen(f"{BASE}/storage/v1/object/public/photos/{path}", timeout=30) as resp:
        data = resp.read()
    return len(data), Image.open(io.BytesIO(data)).size


def card_for(page, name):
    return page.locator("#grid .card", has=page.locator(".card-name", has_text=name))


def form_open(page):
    return page.evaluate("document.getElementById('form-dialog').open")


def wait_form_closed(page):
    page.wait_for_function("!document.getElementById('form-dialog').open", timeout=30000)


def choose_photo(page, path):
    page.set_input_files("#photo-input", str(path))
    page.wait_for_function("document.getElementById('save-btn').textContent === 'Save'", timeout=30000)


def add_item(page, name, photo=None, nickname=None):
    page.click("#add-btn")
    page.fill("#item-form [name=name]", name)
    if nickname:
        page.fill("#item-form [name=nickname]", nickname)
    if photo:
        choose_photo(page, photo)
    page.click("#save-btn")
    wait_form_closed(page)


def open_detail(page, name):
    card_for(page, name).locator(".card-btn").click()
    page.wait_for_selector("#detail-dialog[open]")


def run_m3(browser):
    page = browser.new_page(viewport={"width": 375, "height": 800})
    page.goto(URL)
    wait_loaded(page)

    print("\nT3.1 Add with only a name")
    name = f"{TEST_PREFIX} Only Name"
    add_item(page, name)
    check("new card appears without a reload", card_for(page, name).count() == 1, shown_ids(page))
    check("card shows the placeholder", card_for(page, name).locator(".placeholder").count() == 1)
    check("card has no empty nickname line", card_for(page, name).locator(".card-meta").count() == 0)
    row = test_row(name)
    check("saved with no photo or nickname", row["photo_path"] is None and row["nickname"] is None, row)

    print("\nT3.3 Empty name is blocked")
    before = len(test_rows())
    page.click("#add-btn")
    check("no message before trying to save", not page.is_visible("#name-error"))
    page.fill("#item-form [name=name]", "   ")
    page.click("#save-btn")
    check("message shown", page.is_visible("#name-error"))
    check("form stays open", form_open(page))
    check("nothing saved", len(test_rows()) == before)
    page.fill("#item-form [name=name]", "B")
    check("message clears when typing", not page.is_visible("#name-error"))
    check("date and 'from' shown for collection items", page.is_visible("#acquired-fields"))
    page.click(".segmented span:has-text('On my wishlist')")
    check("date and 'from' hidden for wishlist items", not page.is_visible("#acquired-fields"))
    page.click("#form-dialog [data-close]")

    print("\nT3.6 Double-tap Save")
    name = f"{TEST_PREFIX} Double Tap"
    page.click("#add-btn")
    page.fill("#item-form [name=name]", name)
    page.evaluate("() => { const f = document.getElementById('item-form'); f.requestSubmit(); f.requestSubmit(); }")
    wait_form_closed(page)
    time.sleep(1)
    rows = [r for r in test_rows() if r["name"] == name]
    check("only one row created", len(rows) == 1, f"{len(rows)} rows")

    print("\nT3.2 Large phone photo is shrunk")
    big = big_photo()
    name = f"{TEST_PREFIX} Big Photo"
    page.click("#add-btn")
    page.fill("#item-form [name=name]", name)
    page.fill("#item-form [name=nickname]", "Biggie")
    choose_photo(page, big)
    check("preview shows before saving", page.locator("#photo-preview img").count() == 1)
    page.click("#save-btn")
    wait_form_closed(page)
    size, dims = stored_photo(test_row(name)["photo_path"])
    check(f"original is {big.stat().st_size / 1e6:.1f} MB (test needs 5+)", big.stat().st_size > 5e6)
    check(f"stored photo is {size // 1024} KB (under 400)", size < 400 * 1024)
    check(f"stored photo is {dims[0]}x{dims[1]} (longest side 1200)", max(dims) == 1200, dims)

    print("\nT3.8 (automated part) Camera rotation")
    name = f"{TEST_PREFIX} Rotated"
    add_item(page, name, photo=rotated_photo())
    size, dims = stored_photo(test_row(name)["photo_path"])
    check(f"upright phone photo stays upright ({dims[0]}x{dims[1]})", dims == (200, 400), dims)

    print("\nT3.4 Edits survive a reload; replacing a photo")
    name = f"{TEST_PREFIX} Big Photo"
    old_path = test_row(name)["photo_path"]
    open_detail(page, name)
    check("detail shows Edit and Delete", page.is_visible("#edit-btn") and page.is_visible("#delete-btn"))
    page.click("#edit-btn")
    check("edit form shows no error messages",
          not page.is_visible("#name-error") and not page.is_visible("#photo-error") and not page.is_visible("#form-error"))
    page.fill("#item-form [name=nickname]", "Big Bun")
    page.fill("#item-form [name=notes]", "Edited by the test")
    choose_photo(page, small_photo((90, 160, 220), "blue.png"))
    page.click("#save-btn")
    wait_form_closed(page)
    check("detail view shows the edit", "Big Bun" in page.text_content("#detail-fields"))
    page.click("#detail-dialog [data-close]")
    page.reload()
    wait_loaded(page)
    check("nickname survives reload", "Big Bun" in card_for(page, name).text_content())
    row = test_row(name)
    check("photo was replaced", row["photo_path"] and row["photo_path"] != old_path, row["photo_path"])
    card_for(page, name).scroll_into_view_if_needed()
    page.wait_for_function(
        "p => [...document.querySelectorAll('#grid img')].some(i => i.src.endsWith(p) && i.naturalWidth > 0)",
        arg=row["photo_path"], timeout=15000)
    check("new photo displays", True)

    print("\nT3.1b Removing photo and nickname")
    open_detail(page, name)
    page.click("#edit-btn")
    page.click("#photo-remove")
    page.fill("#item-form [name=nickname]", "")
    page.click("#save-btn")
    wait_form_closed(page)
    page.click("#detail-dialog [data-close]")
    row = test_row(name)
    check("saved with no photo or nickname", row["photo_path"] is None and row["nickname"] is None, row)
    check("card falls back to placeholder", card_for(page, name).locator(".placeholder").count() == 1)
    check("card has no nickname line", card_for(page, name).locator(".card-meta").count() == 0)

    print("\nT3.5 Delete and undo")
    name = f"{TEST_PREFIX} Only Name"
    open_detail(page, name)
    page.click("#delete-btn")
    page.wait_for_selector("#toast:not([hidden])")
    check("card disappears", card_for(page, name).count() == 0)
    page.click("#toast-undo")
    page.wait_for_function("n => [...document.querySelectorAll('.card-name')].some(c => c.textContent === n)", arg=name)
    check("undo brings it back", card_for(page, name).count() == 1)
    check("undo cleared deleted_at", test_row(name)["deleted_at"] is None)
    open_detail(page, name)
    page.click("#delete-btn")
    page.wait_for_selector("#toast:not([hidden])")
    page.wait_for_selector("#toast", state="hidden", timeout=10000)
    check("toast goes away by itself", True)
    page.reload()
    wait_loaded(page)
    check("stays gone after reload", card_for(page, name).count() == 0)
    check("row still exists with deleted_at set", test_row(name)["deleted_at"] is not None)
    if SHOTS:
        open_detail(page, f"{TEST_PREFIX} Rotated")
        page.screenshot(path=SHOTS / "phone-detail.png")
        page.click("#edit-btn")
        page.screenshot(path=SHOTS / "phone-form.png")
        page.click("#form-dialog [data-close]")
    page.close()

    print("\nT3.7 Two browsers")
    a = browser.new_context().new_page()
    b = browser.new_context().new_page()
    a.goto(URL)
    b.goto(URL)
    wait_loaded(a)
    wait_loaded(b)
    name = f"{TEST_PREFIX} Seen Elsewhere {random.randint(1000, 9999)}"
    add_item(a, name)
    check("not in browser B before refresh", card_for(b, name).count() == 0)
    b.reload()
    wait_loaded(b)
    check("shows in browser B after refresh", card_for(b, name).count() == 1)
    a.context.close()
    b.context.close()


# ───── Milestone 4 ─────

def family_page(browser, token=TOKEN, claim_name=None):
    """A fresh browser (own storage) opened via the family link."""
    page = browser.new_context(viewport={"width": 375, "height": 800}).new_page()
    page.goto(f"{URL}?f={token}")
    wait_loaded(page)
    if claim_name:
        page.evaluate("n => localStorage.setItem('jellycat.claimName', n)", claim_name)
        page.reload()
        wait_loaded(page)
    return page


def her_page(browser):
    page = browser.new_context(viewport={"width": 375, "height": 800}).new_page()
    page.goto(URL)
    wait_loaded(page)
    return page


def stored_token(page):
    return page.evaluate("localStorage.getItem('jellycat.familyToken')")


def db_claims():
    status, body = call("POST", "/rest/v1/rpc/get_claims", body={"p_token": TOKEN})
    assert status == 200, body
    return {c["jellycat_id"]: c["claimed_by"] for c in body}


def show_wishlist(page):
    page.click("[data-tab=wishlist]")


def run_m4(browser):
    name = f"{TEST_PREFIX} Wish Croissant"
    status, body = call("POST", "/rest/v1/jellycats", key=SERVICE, body={"name": name, "status": "wishlist"},
                        headers={"Prefer": "return=representation"})
    assert status == 201, body
    item_id = body[0]["id"]

    print("\nT4.1 Her view never touches claims")
    page = browser.new_context(viewport={"width": 375, "height": 800}).new_page()
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    page.goto(URL)
    wait_loaded(page)
    show_wishlist(page)
    open_detail(page, name)
    page.click("#detail-dialog [data-close]")
    page.click("[data-tab=owned]")
    bad = [u for u in requests if "rpc/" in u or "claims" in u]
    check(f"{len(requests)} requests, none to claims or rpc/", not bad, bad)
    check("no family banner", not page.is_visible("#family-banner"))
    show_wishlist(page)
    check("no claim buttons or claim text", "laim" not in page.text_content("#grid"), page.text_content("#grid"))
    check("wishlist cards offer 'Got it!'", card_for(page, name).locator("text=Got it!").count() == 1)

    print("\nT4.2 Console snooping from her view")
    result = page.evaluate("""async () => {
        const direct = await db.from('claims').select();
        const guess = await db.rpc('get_claims', { p_token: 'guess' });
        return { direct: { data: direct.data, error: !!direct.error }, guess: { data: guess.data, error: !!guess.error } };
    }""")
    check("from('claims').select() returns nothing", result["direct"]["error"] or not result["direct"]["data"], result)
    check("rpc('get_claims', guess) is refused", result["guess"]["error"] and not result["guess"]["data"], result)
    page.context.close()

    print("\nT4.3 Family link")
    a = family_page(browser)
    check("banner shown", a.is_visible("#family-banner"))
    check("banner names Kristen", "hidden from Kristen" in a.text_content("#family-banner"))
    check("token removed from the address bar", "f=" not in a.url and TOKEN not in a.url, a.url)
    check("token remembered", stored_token(a) == TOKEN)
    a.reload()
    wait_loaded(a)
    check("reload keeps family view", a.is_visible("#family-banner"))

    print("\nT4.4 Tampered token")
    t = family_page(browser, token=TOKEN[:-4] + "abcd")
    check("falls back to her view", not t.is_visible("#family-banner"))
    check("nothing saved", stored_token(t) is None)
    check("token removed from the address bar", "f=" not in t.url, t.url)
    t.context.close()

    print("\nT4.5 Claim in A; hidden in B; shown in C")
    show_wishlist(a)
    card_for(a, name).locator("text=Claim this").click()
    a.wait_for_selector("#name-dialog[open]")
    check("asks for your name the first time", True)
    a.fill("#name-form [name=claimer]", "Test Mom")
    a.click("#name-ok")
    a.wait_for_function("n => document.querySelector('#grid').textContent.includes('Claimed by Test Mom')", arg=name)
    check("A shows 'Claimed by Test Mom'", "Claimed by Test Mom" in card_for(a, name).text_content())
    check("database has the claim", db_claims().get(item_id) == "Test Mom", db_claims())
    check("name remembered for next time", a.evaluate("localStorage.getItem('jellycat.claimName')") == "Test Mom")

    b = her_page(browser)
    show_wishlist(b)
    b_text = card_for(b, name).text_content()
    check("her view: item looks unclaimed", "laim" not in b_text and "Test Mom" not in b.content(), b_text)

    c = family_page(browser, claim_name="Uncle Bob")
    show_wishlist(c)
    c_text = card_for(c, name).text_content()
    check("C (family) shows 'Claimed by Test Mom'", "Claimed by Test Mom" in c_text, c_text)
    check("C can't unclaim someone else's claim", card_for(c, name).locator("text=Unclaim").count() == 0)

    print("\nT4.6 Unclaim")
    check("A sees Unclaim", card_for(a, name).locator("text=Unclaim").count() == 1)
    card_for(a, name).locator("text=Unclaim").click()
    a.wait_for_function("n => !document.querySelector('#grid').textContent.includes('Claimed by')")
    check("claim removed in A", card_for(a, name).locator("text=Claim this").count() == 1)
    check("claim removed in database", item_id not in db_claims(), db_claims())
    c.reload()
    wait_loaded(c)
    show_wishlist(c)
    check("C sees it free again after refresh", card_for(c, name).locator("text=Claim this").count() == 1)

    print("\nT4.5b Two people claim at once")
    card_for(a, name).locator("text=Claim this").click()          # A claims (name already saved)
    a.wait_for_function("() => document.querySelector('#grid').textContent.includes('Claimed by Test Mom')")
    card_for(c, name).locator("text=Claim this").click()          # C still shows the old, unclaimed state
    c.wait_for_function("() => document.querySelector('#grid').textContent.includes('Claimed by Test Mom')")
    check("second claimer is told it's taken", "Already claimed by Test Mom" in c.text_content("#toast"),
          c.text_content("#toast"))
    check("database still has the first claim", db_claims().get(item_id) == "Test Mom", db_claims())
    if SHOTS:
        a.screenshot(path=SHOTS / "family-wishlist.png", full_page=True)

    print("\nT4.7 Got it!")
    open_detail(a, name)
    a.click("#detail-actions >> text=Got it!")
    a.wait_for_selector("#toast:has-text('joined the collection')")
    check("leaves the wishlist", card_for(a, name).count() == 0)
    a.click("[data-tab=owned]")
    check("appears in the collection", card_for(a, name).count() == 1)
    row = test_row(name)
    check("saved as owned with today's date", row["status"] == "owned" and row["acquired_date"] == time.strftime("%Y-%m-%d"),
          row)
    check("claim removed from database", item_id not in db_claims(), db_claims())
    check("giver saved as 'Gift from Test Mom'", row["acquired_from"] == "Gift from Test Mom", row)
    open_detail(a, name)
    check("detail view shows the giver", "Gift from Test Mom" in a.text_content("#detail-fields"))
    a.click("#detail-dialog [data-close]")

    print("\nT4.8 Leave family view")
    a.click("#leave-family")
    check("banner gone", not a.is_visible("#family-banner"))
    check("token forgotten", stored_token(a) is None)
    a.reload()
    wait_loaded(a)
    check("still her view after reload", not a.is_visible("#family-banner"))
    for p in (a, b, c):
        p.context.close()


def cleanup():
    print("\nCleanup (service key)")
    test_rows()
    if PHOTOS_SEEN:
        call("DELETE", "/storage/v1/object/photos", key=SERVICE, body={"prefixes": sorted(PHOTOS_SEEN)})
    call("DELETE", f"/rest/v1/jellycats?name=like.{TEST_PREFIX}*", key=SERVICE)
    check("no test rows left behind", test_rows() == [])


if __name__ == "__main__":
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT)], cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            try:
                run_m2(browser)
                run_m3(browser)
                run_m4(browser)
            finally:
                browser.close()
                cleanup()
    finally:
        server.terminate()
    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)
