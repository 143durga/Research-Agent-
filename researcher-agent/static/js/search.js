const alertsEl = document.getElementById("alerts");
const resultsEl = document.getElementById("results");
const searchBtn = document.getElementById("searchBtn");

function renderResult(r, idx) {
  const authors = (r.authors || []).join(", ") || "Authors unknown";
  const meta = [r.year, r.venue, r.source].filter(Boolean).join(" · ");
  const doi = r.doi ? `<div class="small">DOI: <a href="https://doi.org/${encodeURI(r.doi)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.doi)}</a></div>` : `<div class="small muted">DOI: not available</div>`;
  const citeCount = (r.citation_count !== null && r.citation_count !== undefined) ? `${r.citation_count} citations` : "citation count unavailable";
  const oa = r.pdf_url ? `<span class="badge badge-explicit">Open access PDF</span>` : `<span class="badge badge-muted">No open-access PDF found</span>`;

  return `
  <div class="paper-item" id="result-${idx}">
    <div class="title">${escapeHtml(r.title)}</div>
    <div class="meta">${escapeHtml(authors)} ${meta ? "· " + escapeHtml(meta) : ""} · ${citeCount}</div>
    <div class="abstract">${r.abstract ? escapeHtml(r.abstract).slice(0, 420) + (r.abstract.length > 420 ? "…" : "") : "<span class=\"muted\">No abstract returned by the source.</span>"}</div>
    ${doi}
    <div style="margin:6px 0">${oa} <span class="badge badge-source">${escapeHtml(r.source)}</span></div>
    <div class="actions">
      ${safeHttp(r.source_url) ? `<a class="btn small secondary" href="${escapeHtml(safeHttp(r.source_url))}" target="_blank" rel="noopener noreferrer">View</a>` : ""}
      <button class="btn small secondary" data-action="save" data-idx="${idx}">Save to library</button>
      ${r.pdf_url ? `<button class="btn small" data-action="import" data-idx="${idx}">Import PDF</button>` : ""}
    </div>
  </div>`;
}

let lastResults = [];

async function runSearch() {
  const query = document.getElementById("q").value.trim();
  if (!query) { showAlert(alertsEl, "Enter a search term first.", "error"); return; }
  const author = document.getElementById("author").value.trim() || null;
  const year = document.getElementById("year").value ? parseInt(document.getElementById("year").value) : null;
  const oa = document.getElementById("oa").checked;
  const sources = Array.from(document.querySelectorAll(".src:checked")).map(el => el.value);

  setLoading(searchBtn, true, "Searching...");
  resultsEl.innerHTML = "";
  try {
    const data = await apiPost("/api/search", { query, author, year, open_access_only: oa, sources });
    lastResults = data.results;
    if (Object.keys(data.source_errors || {}).length) {
      for (const [src, msg] of Object.entries(data.source_errors)) {
        showAlert(alertsEl, `${src} was unavailable: ${msg}`, "warn");
      }
    }
    if (!lastResults.length) {
      resultsEl.innerHTML = `<div class="empty-state"><h3>No results</h3><p>Try a broader query or different sources.</p></div>`;
    } else {
      resultsEl.innerHTML = lastResults.map(renderResult).join("");
    }
  } catch (e) {
    showAlert(alertsEl, e.message, "error");
    for (const [src, msg] of Object.entries((e.data && e.data.source_errors) || {})) {
      showAlert(alertsEl, `${src}: ${msg}`, "warn");
    }
  } finally {
    setLoading(searchBtn, false);
  }
}

searchBtn.addEventListener("click", runSearch);
document.getElementById("q").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

resultsEl.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const idx = parseInt(btn.dataset.idx);
  const r = lastResults[idx];
  if (btn.dataset.action === "save") {
    setLoading(btn, true, "Saving...");
    try {
      const res = await apiPost("/api/papers/import", r);
      btn.textContent = "Saved to library";
      btn.disabled = true;
      showAlert(alertsEl, "Saved. Open it from My Library to import the PDF and analyze it.", "ok");
    } catch (err) {
      showAlert(alertsEl, err.message, "error");
      setLoading(btn, false);
    }
  } else if (btn.dataset.action === "import") {
    setLoading(btn, true, "Importing PDF...");
    try {
      const savedPaper = await apiPost("/api/papers/import", r);
      const pdfResult = await apiPost(`/api/papers/${savedPaper.paper_id}/import-pdf-from-url`, { url: r.pdf_url });
      showAlert(alertsEl, `Imported and chunked (${pdfResult.summary.chunks_created} chunks). Opening paper...`, "ok");
      window.location.href = `/paper/${savedPaper.paper_id}`;
    } catch (err) {
      showAlert(alertsEl, err.message, "error");
      setLoading(btn, false);
    }
  }
});
