const alertsEl = document.getElementById("alerts");
const resultEl = document.getElementById("compareResult");
const compareBtn = document.getElementById("compareBtn");

function statusClass(s) {
  s = (s || "").toUpperCase();
  if (s === "EXPLICITLY_STATED") return "explicit";
  if (s === "INFERRED") return "inferred";
  return "notfound";
}

function cell(field) {
  if (!field) return `<span class="muted small">n/a</span>`;
  return `<div>${escapeHtml(field.value || "")}</div><div class="small">${statusBadge(field.status)}</div>`;
}

function renderList(title, items) {
  if (!items || !items.length) return "";
  return `<div class="card"><h3 class="mt-0">${title}</h3><ul>${items.map(i => `<li>${escapeHtml(i)}</li>`).join("")}</ul></div>`;
}

compareBtn?.addEventListener("click", async () => {
  const ids = Array.from(document.querySelectorAll(".cmpPaper:checked")).map(el => parseInt(el.value));
  if (ids.length < 2) { showAlert(alertsEl, "Select at least 2 papers.", "error"); return; }
  if (ids.length > 10) { showAlert(alertsEl, "Select at most 10 papers.", "error"); return; }
  setLoading(compareBtn, true, "Comparing...");
  resultEl.innerHTML = "";
  try {
    const data = await apiPost("/api/compare", { paper_ids: ids });
    const dims = ["problem","objective","methodology","model","dataset","evaluation_metrics","results","limitations","contributions","future_work"];
    let table = `<div class="card" style="overflow-x:auto"><h3 class="mt-0">Comparison table</h3><table><thead><tr><th>Paper</th>${dims.map(d => `<th>${d.replace('_',' ')}</th>`).join("")}</tr></thead><tbody>`;
    for (const row of data.comparison_table) {
      table += `<tr><td><strong>${escapeHtml(row.title)}</strong></td>${dims.map(d => `<td>${cell(row[d])}</td>`).join("")}</tr>`;
    }
    table += `</tbody></table></div>`;
    resultEl.innerHTML = table
      + renderList("Common themes", data.common_themes)
      + renderList("Differences", data.differences)
      + renderList("Conflicting findings", data.conflicting_findings)
      + renderList("Different datasets", data.different_datasets)
      + renderList("Different evaluation approaches", data.different_evaluation_approaches)
      + renderList("Research opportunities", data.research_opportunities)
      + `<p class="small muted">Model: ${escapeHtml(data.model_used)}</p>`;
  } catch (e) {
    showAlert(alertsEl, e.message, "error");
  } finally {
    setLoading(compareBtn, false, "Compare selected");
  }
});
