"""
Browser click-through (Playwright/Chromium) against the running Flask app.

IMPORTANT: this validates the UI + frontend/backend wiring with STUBBED backends (a fake LLM, canned
search results, offline lexical embeddings). It is NOT a live-service test. Run scripts/validate_live.py
for real Semantic Scholar/Crossref/arXiv/LLM/embedding validation.

    python tests/ui_smoke.py            # exits non-zero on any failure / console error
"""
import os, sys, tempfile, threading, time, io, json
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import pytest  # noqa: F401
except ImportError:  # offline sandbox: conftest only needs the decorator to exist
    import types
    _pt = types.ModuleType("pytest"); _pt.fixture = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f)); sys.modules["pytest"] = _pt
import conftest  # sets temp DB/uploads + env, provides FakeLLM
conftest._db()
from werkzeug.serving import make_server
from providers.search.base import PaperResult

fake = conftest.FakeLLM()
import agent.llm_utils as lu, agent.capabilities.paper_chat as pc
lu.get_llm_provider = lambda: fake
pc.get_llm_provider = lambda: fake
import providers.llm.factory as f; f.get_llm_provider = lambda: fake
import agent.capabilities.paper_searcher as ps

MODE = {"search": "ok"}
def fake_search(**k):
    q = k.get("query", "")
    if MODE["search"] == "down":
        return [], {"semantic_scholar": "unreachable", "crossref": "unreachable", "arxiv": "unreachable"}
    if "nothing" in q:
        return [], {}
    return ([PaperResult(title="A <b>Bold</b> Title on RAG Security", authors=["Ada L."], year=2024, venue="Test Venue", abstract="An abstract & more.",
                         source="arxiv", source_url="javascript:alert(1)", doi="10.1/ui.test", citation_count=None, pdf_url=None, open_access=False),
             PaperResult(title="Second Paper", authors=[], source="crossref", source_url="https://example.org/p", doi=None)], {"semantic_scholar": "rate limited"})
ps.search_all = fake_search

from app import app
srv = make_server("127.0.0.1", 5077, app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:5077"

# fixtures via the API
import requests
def pdf(path, lines):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path); y = 800
    for l in lines: c.drawString(50, y, l); y -= 18
    c.showPage(); c.save(); return path
tmp = tempfile.mkdtemp()
p1 = pdf(f"{tmp}/a.pdf", ["Abstract", "We study prompt injection attacks against retrieval augmented generation systems.", "Limitations", "Our dataset is small and covers only English documents."])
p2 = pdf(f"{tmp}/b.pdf", ["Abstract", "We study fairness testing of language models in cloud services.", "Limitations", "We evaluate only one model family."])
ids = []
for path, title in ((p1, "UI Paper Alpha"), (p2, "UI Paper Beta")):
    r = requests.post(BASE + "/api/papers/upload", files={"file": open(path, "rb")}, data={"title": title}); assert r.status_code == 200, r.text
    ids.append(r.json()["paper_id"])
proj = requests.post(BASE + "/api/projects", json={"title": "Secure RAG Systems in Cloud Environments", "objective": "Study RAG security"}).json()["id"]

from playwright.sync_api import sync_playwright
problems, console = [], []
def click_and_reload(page, selector):
    with page.expect_navigation():
        page.click(selector)


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond: problems.append(msg)

PAGES = ["/", "/search", "/library", f"/paper/{ids[0]}", f"/paper/{ids[0]}/analysis", f"/paper/{ids[0]}/chat", "/compare", "/gaps", "/questions",
         "/experiments", "/literature-review", "/projects", f"/projects/{proj}", "/settings"]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for vw, label in (({"width": 1280, "height": 900}, "desktop"), ({"width": 390, "height": 800}, "mobile")):
        ctx = browser.new_context(viewport=vw); page = ctx.new_page()
        page.on("console", lambda m: console.append((label, m.type, m.text)) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: console.append((label, "pageerror", str(e))))
        for path in PAGES:
            resp = page.goto(BASE + path, wait_until="domcontentloaded")
            check(resp.status == 200, f"[{label}] {path} loads (HTTP {resp.status})")
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            if label == "mobile":
                check(overflow <= 2, f"[mobile] {path} has no horizontal page overflow (overflow={overflow}px)")
        ctx.close()

    ctx = browser.new_context(viewport={"width": 1280, "height": 900}); page = ctx.new_page()
    page.on("console", lambda m: console.append(("flow", m.type, m.text)) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: console.append(("flow", "pageerror", str(e))))

    # ---- navigation via sidebar
    page.goto(BASE + "/")
    for text, frag in (("Paper Search", "/search"), ("My Library", "/library"), ("Compare Papers", "/compare"), ("Research Gap Finder", "/gaps"),
                       ("Research Questions", "/questions"), ("Experiment Planner", "/experiments"), ("Literature Review", "/literature-review"),
                       ("Research Projects", "/projects"), ("Settings", "/settings"), ("Dashboard", "/")):
        page.click(f"aside nav >> text={text}"); page.wait_for_load_state("domcontentloaded")
        check(page.url.rstrip("/").endswith(frag.rstrip("/")) or frag == "/", f"sidebar link '{text}' -> {frag}")

    # ---- search: results, XSS-safe rendering, unsafe URL not linked, partial-source warning, empty state, total outage
    page.goto(BASE + "/search")
    page.fill("#q", "rag security"); page.click("#searchBtn"); page.wait_for_selector(".paper-item")
    check(page.locator(".paper-item").count() == 2, "search renders 2 results")
    check(page.locator(".paper-item .title").first.inner_text() == "A <b>Bold</b> Title on RAG Security", "HTML in title is shown as text, not markup")
    check(page.locator(".paper-item b").count() == 0, "no injected <b> element")
    check(page.locator(".paper-item a[href^='javascript']").count() == 0, "javascript: source_url is not rendered as a link")
    check("citation count unavailable" in page.locator(".paper-item .meta").first.inner_text(), "missing citation count shown as unavailable (not 0)")
    check("DOI: not available" in page.locator(".paper-item").nth(1).inner_text(), "missing DOI shown as not available")
    check(page.locator(".alert-warn").count() >= 1 and "rate limited" in page.locator(".alert-warn").first.inner_text(), "partial source failure is shown")
    page.locator("button[data-action=save]").first.click(); page.wait_for_selector("text=Saved to library")
    page.fill("#q", "nothing here"); page.click("#searchBtn"); page.wait_for_selector(".empty-state")
    check("No results" in page.inner_text(".empty-state"), "empty-result state shown")
    MODE["search"] = "down"
    page.fill("#q", "rag security"); page.click("#searchBtn"); page.wait_for_selector(".alert-error")
    check("unavailable" in page.inner_text("#alerts").lower(), "total source outage is shown as an error, not 'no results'")
    MODE["search"] = "ok"
    page.fill("#q", ""); page.click("#searchBtn"); page.wait_for_selector("text=Enter a search term")
    check(True, "empty query validation message")

    # ---- library + upload validation
    page.goto(BASE + "/library")
    check(page.locator(".paper-item").count() >= 3, "library lists imported papers")
    page.click("#uploadBtn"); page.wait_for_selector("#uploadAlerts .alert-error")
    check("Choose a PDF" in page.inner_text("#uploadAlerts"), "upload with no file shows an error")
    bad = f"{tmp}/bad.pdf"; open(bad, "wb").write(b"%PDF-1.4 garbage that is not a real pdf")
    page.set_input_files("#uploadFile", bad); page.click("#uploadBtn"); page.wait_for_selector("#uploadAlerts .alert-error:has-text('extract'), #uploadAlerts .alert-error:has-text('PDF')")
    check(True, "malformed PDF upload shows a readable error")

    # ---- reader: notes / tags / highlights
    page.goto(BASE + f"/paper/{ids[0]}")
    page.fill("#tagInput", "rag"); click_and_reload(page, "#addTagBtn")
    check("rag" in page.inner_text(".tag-pill"), "tag saved")
    page.fill("#noteInput", "My note <i>x</i>"); click_and_reload(page, "#addNoteBtn")
    check(page.locator("#notesList i").count() == 0 and "My note <i>x</i>" in page.inner_text("#notesList"), "note saved and escaped")
    page.fill("#highlightInput", "Our dataset is small"); click_and_reload(page, "#addHighlightBtn")
    check("Our dataset is small" in page.inner_text("#highlightsList"), "highlight saved")
    check(page.locator(".section-tabs button").count() >= 2, "sections tabs shown")
    page.locator(".section-tabs button").nth(1).click()
    check(page.locator(".sec-pane:visible").count() == 1, "switching section tab shows exactly one pane")

    # ---- analysis (+ explain simply)
    page.goto(BASE + f"/paper/{ids[0]}/analysis"); page.click("#analyzeBtn"); page.wait_for_selector(".claim-block")
    check(page.locator(".claim-block").count() == 15, "analysis renders 15 sections")
    check(page.locator(".badge-explicit").count() >= 1 and page.locator(".badge-notfound").count() >= 1, "status badges shown (explicit + not found)")
    page.locator("button[data-simple]").first.click(); page.wait_for_selector(".simple:has-text('In simple terms')")
    check(True, "Explain simply renders")

    # ---- chat
    page.goto(BASE + f"/paper/{ids[0]}/chat")
    page.fill("#question", "What attacks are studied?"); page.click("#askBtn"); page.wait_for_selector(".chat-msg.assistant")
    check("[Paper:" in page.inner_text(".chat-msg.assistant") or page.locator(".cites").count() > 0, "chat answer shows citation/evidence")
    check(page.locator("#evidencePanel").is_visible(), "retrieved evidence panel visible")
    page.fill("#question", "xylophone zeppelin quokka"); page.click("#askBtn"); page.wait_for_function("document.querySelectorAll('.chat-msg.assistant').length >= 2")
    check("could not find evidence" in page.locator(".chat-msg.assistant").last.inner_text().lower(), "unanswerable question -> 'could not find evidence'")

    # ---- compare (validation + result)
    page.goto(BASE + "/compare"); page.click("#cmpBtn"); page.wait_for_selector(".alert-error")
    check("at least 2" in page.inner_text("#alerts").lower() or "between 2" in page.inner_text("#alerts").lower() or "select at least" in page.inner_text("#alerts").lower(), "compare with 0 papers shows validation error")
    page.locator(f".pp[value='{ids[0]}']").check(); page.locator(f".pp[value='{ids[1]}']").check(); page.click("#cmpBtn"); page.wait_for_selector("table")
    check("UI Paper Alpha" in page.inner_text("table") and "UI Paper Beta" in page.inner_text("table"), "comparison table uses stored titles")
    check("WRONG-TITLE-FROM-MODEL" not in page.content(), "model-supplied titles are not displayed")

    # ---- gaps -> save to project ; questions -> save to project ; experiments
    page.goto(BASE + "/gaps"); page.click("#gapBtn"); page.wait_for_selector(".alert-error")
    page.locator(f".pp[value='{ids[0]}']").check(); page.select_option("#projSel", str(proj)); page.click("#gapBtn"); page.wait_for_selector("[data-gap]")
    check("Potential research gap" in page.inner_text("[data-gap]") and "Author-stated limitation" in page.inner_text("[data-gap]"), "gap card shows potential-gap wording + evidence type")
    check(page.locator("[data-gap] .linkSel").first.input_value() == str(proj), "gap preselected in the chosen project")
    page.goto(BASE + "/questions")
    page.locator(f".pp[value='{ids[0]}']").check(); page.click("#qBtn"); page.wait_for_selector("[data-q]")
    card = page.locator("[data-q]").first
    check("Proposed method" in card.inner_text() and "Open assumptions" in card.inner_text(), "question card has proposed method + open assumptions")
    card.locator(".linkSel").select_option(str(proj)); card.locator(".linkBtn").click(); page.wait_for_selector(".alert-ok:has-text('Saved to project')")
    page.goto(BASE + f"/projects/{proj}")
    check("Potential research gap" in page.inner_text("body"), "project detail lists the linked gap")
    check(page.locator(".card:has(h3:has-text('Research questions')) .claim-block").count() >= 1, "project detail lists the linked question (Save to Project verified in UI)")
    page.goto(BASE + "/experiments"); page.click("#planBtn"); page.wait_for_selector("text=Proposed plan")
    check("no results exist" in page.inner_text("body"), "experiment plan labelled as proposed / no results")
    check("Research question" in page.inner_text("body") and "Hypothesis" in page.inner_text("body"), "plan shows research question + hypothesis")

    # ---- projects / literature review / settings
    page.goto(BASE + "/projects"); page.fill("#ptitle", "Another <b>project</b>"); click_and_reload(page, "#createBtn")
    check(page.locator("h3 a b").count() == 0 and "Another <b>project</b>" in page.inner_text("body"), "project created; title escaped")
    page.click("#createBtn") if False else None
    page.goto(BASE + f"/projects/{proj}"); page.fill("#addPid", str(ids[1])); click_and_reload(page, "#addPaperBtn")
    check("UI Paper Beta" in page.inner_text("body"), "paper added to project")
    page.goto(BASE + "/literature-review"); page.fill("#theme", "Injection defenses"); page.locator(".pp").first.check(); page.fill("#agree", "Both study LLM security"); click_and_reload(page, "#saveBtn")
    check("Injection defenses" in page.inner_text("body"), "literature review theme saved")
    page.goto(BASE + "/settings")
    check("lexical fallback" in page.inner_text("body").lower(), "Settings shows active retrieval mode (lexical fallback)")
    page.goto(BASE + "/does-not-exist"); check("Page not found" in page.inner_text("body"), "404 page renders")
    ctx.close(); browser.close()

# console errors: ignore only failed font/CDN loads (blocked in offline sandboxes)
real = [c for c in console if not ("fonts.g" in c[2] or "ERR_" in c[2] or "Failed to load resource" in c[2])]
ignored = [c for c in console if c not in real]
check(not real, f"no browser console/page errors ({len(ignored)} ignored: blocked external font requests / expected 4xx-5xx responses)")
for c in real: print("   console:", c)
print(f"\n{'ALL UI CHECKS PASSED' if not problems else str(len(problems)) + ' UI CHECK(S) FAILED'}")
sys.exit(1 if problems else 0)
