const alertsEl = document.getElementById("alerts");
const resultEl = document.getElementById("gapsResult");
const findGapsBtn = document.getElementById("findGapsBtn");

const GAP_TYPE_LABEL = t => (t || "other").replace(/_/g, " ");

function renderGap(g) {
  return `
  <div class="claim-block">
    <h4>${escapeHtml(GAP_TYPE_LABEL(g.gap_type))} gap</h4>
    <p>${escapeHtml(g.description)}</p>
    <p class="small muted">${escapeHtml(g.why_unresolved || "")}</p>
    ${(g.evidence || []).map(e => `<div class="evidence inferred">Paper ${e.paper_id}: "${escapeHtml(e.quote_or_paraphrase || "")}" <span class="muted">(${escapeHtml(e.section || "")})</span></div>`).join("")}
    ${g.potential_research_question ? `<div class="evidence explicit">Suggested question: ${escapeHtml(g.potential_research_question)}</div>` : ""}
    <div class="btn-row"><button class="btn small secondary genQBtn" data-gap-id="${g.id}">Generate research questions from this gap</button></div>
  </div>`;
}

findGapsBtn?.addEventListener("click", async () => {
  const ids = Array.from(document.querySelectorAll(".gapPaper:checked")).map(el => parseInt(el.value));
  if (!ids.length) { showAlert(alertsEl, "Select at least one paper.", "error"); return; }
  setLoading(findGapsBtn, true, "Analyzing limitations & future work...");
  resultEl.innerHTML = "";
  try {
    const data = await apiPost("/api/gaps/find", { paper_ids: ids });
    if (!data.gaps.length) {
      resultEl.innerHTML = `<div class="empty-state"><h3>No gaps surfaced</h3><p>The selected papers may not have explicit limitations/future-work sections. Try papers with the PDF fully imported.</p></div>`;
    } else {
      resultEl.innerHTML = `<div class="card"><h3 class="mt-0">Newly identified gaps</h3>${data.gaps.map(renderGap).join("")}</div>`;
    }
  } catch (e) {
    showAlert(alertsEl, e.message, "error");
  } finally {
    setLoading(findGapsBtn, false, "Find research gaps");
  }
});

document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".genQBtn");
  if (!btn) return;
  setLoading(btn, true, "Generating...");
  try {
    const data = await apiPost("/api/questions/generate", { gap_id: parseInt(btn.dataset.gapId), paper_ids: [] });
    showAlert(alertsEl, `Generated ${data.questions.length} research question(s). View them on the Research Questions page.`, "ok");
  } catch (e) {
    showAlert(alertsEl, e.message, "error");
  } finally {
    setLoading(btn, false, "Generate research questions from this gap");
  }
});
