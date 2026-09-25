"""Screenshot a UI route for visual QA.

    .venv/bin/python scripts/shot.py URL OUT.png [--dark] [--click "Button text"]...

Prints any browser console errors (a clean screen prints none).
"""
import sys

from playwright.sync_api import sync_playwright

url, out = sys.argv[1], sys.argv[2]
dark = "--dark" in sys.argv
clicks = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--click"]
errors: list[str] = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
    page.add_init_script(f"localStorage.setItem('plugai-theme', '{'desk' if dark else 'book'}')")
    page.goto(url, wait_until="networkidle")
    for text in clicks:
        target = page.get_by_role("button", name=text, exact=True)
        if target.count() == 0:
            target = page.get_by_role("tab", name=text, exact=True)
        if target.count() == 0:
            target = page.get_by_role("radio", name=text, exact=True)
        target.first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(700)
    page.wait_for_timeout(500)
    # The app scrolls inside <main>; grow the viewport to the content so nothing is cut off.
    h = page.evaluate("() => { const m = document.querySelector('main'); return m ? m.scrollHeight + 80 : 900 }")
    page.set_viewport_size({"width": 1440, "height": max(900, min(int(h), 6000))})
    page.wait_for_timeout(300)
    page.screenshot(path=out, full_page=True)
    browser.close()
print("saved", out)
for e in errors:
    print(e)
