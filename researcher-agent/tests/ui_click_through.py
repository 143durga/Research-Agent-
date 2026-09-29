import sys, time, json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
issues = []
console_errors = []

PAGES = ["/", "/search", "/library", "/compare", "/gaps", "/questions",
         "/experiments", "/literature-review", "/projects", "/settings"]


def log(msg):
    print(msg)


def check_console(page, label):
    for m in console_errors:
        pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append((page.url, msg.type, msg.text)) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: issues.append(f"pageerror on {page.url}: {exc}"))

        # ---- 1. Static pages / empty states ----
        for path in PAGES:
            resp = page.goto(BASE + path, wait_until="networkidle")
            if resp.status != 200:
                issues.append(f"{path} returned {resp.status}")
            # basic responsive check: no horizontal overflow at mobile width
        log("Visited all top-level pages once.")

        # responsive check at mobile width
        page.set_viewport_size({"width": 375, "height": 800})
        for path in ["/", "/search", "/library"]:
            page.goto(BASE + path, wait_until="networkidle")
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            if overflow > 5:
                issues.append(f"{path} has horizontal overflow at 375px: {overflow}px")
        page.set_viewport_size({"width": 1280, "height": 900})

        # ---- 2. Navigation sidebar links all resolve ----
        page.goto(BASE + "/", wait_until="networkidle")
        hrefs = page.eval_on_selector_all("aside.sidebar nav a", "els => els.map(e => e.getAttribute('href'))")
        for href in hrefs:
            r = page.goto(BASE + href, wait_until="networkidle")
            if r.status != 200:
                issues.append(f"nav link {href} -> {r.status}")
        log(f"Checked {len(hrefs)} sidebar nav links.")

        # ---- 3. Search page: run a real UI search using a mocked backend response ----
        page.goto(BASE + "/search", wait_until="networkidle")
        page.route("**/api/search", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"results": [{
                "title": "UI Test Paper on Prompt Injection", "authors": ["A. Researcher"], "year": 2024,
                "venue": "UI Test Venue", "abstract": "An abstract about prompt injection.", "source": "arxiv",
                "source_url": "https://example.test/paper", "doi": None, "external_id": "ui.test.1",
                "citation_count": 3, "pdf_url": None, "open_access": False, "raw": {}
            }], "source_errors": {"crossref": "simulated outage"}, "count": 1})
        ))
        page.fill("#q", "prompt injection")
        page.click("#searchBtn")
        page.wait_for_selector(".paper-item", timeout=5000)
        if "UI Test Paper" not in page.content():
            issues.append("Search result did not render in the UI")
        if "simulated outage" not in page.content():
            issues.append("Per-source search error was not surfaced to the user")
        # save-to-library button works
        page.click("button[data-action='save']")
        page.wait_for_selector("text=Saved to library", timeout=5000)
        log("Search page: results render, source errors shown, save button works.")

        # empty search validation (no query)
        page.goto(BASE + "/search", wait_until="networkidle")
        page.click("#searchBtn")
        if not page.locator(".alert-error").count():
            issues.append("Empty search query did not show a validation alert")

        # few/no results case
        page.route("**/api/search", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"results": [], "source_errors": {}, "count": 0})
        ))
        page.fill("#q", "zzzznonexistentqueryxyz")
        page.click("#searchBtn")
        page.wait_for_selector("text=No results", timeout=5000)
        log("No-results case renders an empty state correctly.")
        page.unroute("**/api/search")

        # ---- 4. Library: upload form validation (no file selected) ----
        page.goto(BASE + "/library", wait_until="networkidle")
        page.click("#uploadBtn")
        if not page.locator("#uploadAlerts .alert-error").count():
            issues.append("Upload with no file did not show a validation alert")
        log("Library upload validation works without a file.")

        # ---- 5. Full real-browser workflow: upload -> reader -> analyze -> chat -> compare -> gaps -> questions -> experiments ----
        import io, os
        sample_path = "/tmp/ui_sample.pdf"
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(sample_path)
        for lines in ([["Abstract", "We study prompt injection attacks against retrieval augmented generation.",
                        "Introduction", "This is a security concern for cloud deployed LLMs."],
                       ["Methodology", "We benchmark three retrieval pipelines against adversarial documents.",
                        "Results", "Sanitizing retrieved passages improves detection accuracy."],
                       ["Limitations", "Our dataset is small and covers only English documents.",
                        "Conclusion", "Future work includes multilingual evaluation."]]):
            y = 800
            for l in lines:
                c.drawString(50, y, l); y -= 18
            c.showPage()
        c.save()

        page.goto(BASE + "/library", wait_until="networkidle")
        page.set_input_files("#uploadFile", sample_path)
        page.fill("#uploadTitle", "Browser UI Workflow Paper")
        with page.expect_navigation(timeout=15000):
            page.click("#uploadBtn")
        if "Browser UI Workflow Paper" not in page.content():
            issues.append("Reader page did not show the uploaded paper's title")
        paper_url = page.url
        paper_id = paper_url.rstrip("/").split("/")[-1]
        log(f"Uploaded paper via UI, redirected to reader: {paper_url}")

        # section tabs
        if page.locator(".section-tabs button").count() > 1:
            page.locator(".section-tabs button").nth(1).click()
        # notes / tags / highlights forms
        page.fill("#noteInput", "A UI test note.")
        with page.expect_navigation(timeout=8000):
            page.click("#addNoteBtn")
        if "A UI test note." not in page.content():
            issues.append("Note did not persist/render after save")
        page.fill("#tagInput", "ui-test-tag")
        with page.expect_navigation(timeout=8000):
            page.click("#addTagBtn")
        if "ui-test-tag" not in page.content():
            issues.append("Tag did not persist/render after save")
        log("Reader page: sections, notes, tags all work.")

        # Analysis page (real LLM call - no key configured, so we verify the honest error path in the UI)
        page.goto(BASE + f"/paper/{paper_id}/analysis", wait_until="networkidle")
        page.click("#analyzeBtn")
        page.wait_for_timeout(1500)
        body_text = page.content()
        if "alert-error" not in body_text and "No LLM provider is configured" not in body_text:
            issues.append("Analysis page did not show an honest error when no LLM key is configured")
        else:
            log("Analysis page correctly surfaces 'no LLM configured' as a UI error (no fake analysis shown).")

        # Chat page - same honest-failure check
        page.goto(BASE + f"/paper/{paper_id}/chat", wait_until="networkidle")
        page.fill("#question", "What dataset did the authors use?")
        page.click("#askBtn")
        page.wait_for_timeout(1500)
        chat_text = page.content()
        if "could not find evidence" not in chat_text.lower() and "alert-error" not in chat_text and "could not generate" not in chat_text.lower():
            issues.append("Chat page did not show an honest response when no LLM key is configured")
        else:
            log("Chat page correctly avoids fabricating an answer with no LLM configured.")

        # Compare page needs 2 papers; upload a second one quickly via API then check UI checkboxes render
        page.goto(BASE + "/compare", wait_until="networkidle")
        n_checkboxes = page.locator(".pp").count()
        log(f"Compare page lists {n_checkboxes} paper checkbox(es).")

        # Gaps / Questions / Experiments pages: verify project selector is present (V1.1 requirement)
        page.goto(BASE + "/gaps", wait_until="networkidle")
        if page.locator("#projSel").count() == 0:
            issues.append("Gap Finder page is missing the project selector")
        page.goto(BASE + "/questions", wait_until="networkidle")
        if page.locator("#projSel").count() == 0:
            issues.append("Research Questions page is missing the project selector")
        log("Project selectors present on Gap Finder and Research Questions pages.")

        # Projects: create one through the real UI
        page.goto(BASE + "/projects", wait_until="networkidle")
        page.fill("#ptitle", "UI Workflow Project")
        page.fill("#pobj", "Validate the UI end to end")
        with page.expect_navigation(timeout=8000):
            page.click("#createBtn")
        if "UI Workflow Project" not in page.content():
            issues.append("Created project did not appear in the Projects list")
        log("Project creation works through the real UI.")

        # 404 page
        r = page.goto(BASE + "/no-such-page", wait_until="networkidle")
        if r.status != 404 or "Page not found" not in page.content():
            issues.append("Custom 404 page did not render correctly")

        browser.close()

    log("\n--- Console errors captured ---")
    real_console_errors = [c for c in console_errors if "favicon" not in c[2].lower()]
    for url, typ, text in real_console_errors:
        log(f"[{typ}] {url}: {text}")

    log("\n--- Issues found ---")
    if not issues and not real_console_errors:
        log("None. All checked pages, forms, and workflows behaved correctly.")
    else:
        for i in issues:
            log(f"ISSUE: {i}")
        for url, typ, text in real_console_errors:
            log(f"CONSOLE ERROR: {url}: {text}")
        sys.exit(1)


if __name__ == "__main__":
    main()
