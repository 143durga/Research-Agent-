const alertsEl = document.getElementById("alerts");
const resultEl = document.getElementById("qResult");
const genQBtn = document.getElementById("genQBtn");

function renderQuestion(q) {
  return `
  <div class="claim-block">
    <h4>${escapeHtml(q.question)}</h4>
    <p class="small">${escapeHtml(q.motivation || "")}</p>
    <div class="small muted">Method: ${escapeHtml(q.possible_method || "n/a")} · Dataset: ${escapeHtml(q.possible_dataset || "n/a")} · Metrics: ${escapeHtml(q.possible_metrics || "n/a")} · Difficulty: ${escapeHtml(q.difficulty || "n/a")}</div>
    ${q.open_assumptions ? `<div class="evidence inferred">Open assumptions: ${escapeHtml(q.open_assumptions)}</div>` : ""}
    <div class="btn-row"><button class="btn small secondary planBtn" data-q-id="${q.id}">Create experiment plan</button></div>
  </div>`;
}

genQBtn?.addEventListener("click", async () => {
  const ids = Array.from(document.querySelectorAll(".qPaper:checked")).map(el => parseInt(el.value));
  if (!ids.length) { showAlert(alertsEl, "Select at least one paper.", "error"); return; }
  const count = parseInt(document.getElementById("qCount").value) || 5;
  setLoading(genQBtn, true, "Generating...");
  resultEl.innerHTML = "";
  try {
    const data = await apiPost("/api/questions/generate", { paper_ids: ids, count });
    resultEl.innerHTML = `<div class="card"><h3 class="mt-0">Newly generated questions</h3>${data.questions.map(renderQuestion).join("")}</div>`;
  } catch (e) {
    showAlert(alertsEl, e.message, "error");
  } finally {
    setLoading(genQBtn, false, "Generate questions");
  }
});

document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".planBtn");
  if (!btn) return;
  setLoading(btn, true, "Planning...");
  try {
    await apiPost("/api/experiments/plan", { question_id: parseInt(btn.dataset.qId) });
    showAlert(alertsEl, "Experiment plan created. View it on the Experiment Planner page.", "ok");
  } catch (e) {
    showAlert(alertsEl, e.message, "error");
  } finally {
    setLoading(btn, false, "Create experiment plan");
  }
});
