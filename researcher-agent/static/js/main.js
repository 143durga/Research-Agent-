// Shared helpers for Researcher Agent pages.

async function apiPost(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(data.error || `Request failed (${resp.status})`);
    err.data = data;
    throw err;
  }
  return data;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusBadge(status) {
  const s = (status || "").toUpperCase();
  if (s === "EXPLICITLY_STATED") return `<span class="badge badge-explicit">Explicitly stated</span>`;
  if (s === "INFERRED") return `<span class="badge badge-inferred">Inferred</span>`;
  return `<span class="badge badge-notfound">Not found</span>`;
}

function evidenceClass(status) {
  const s = (status || "").toUpperCase();
  if (s === "EXPLICITLY_STATED") return "explicit";
  if (s === "INFERRED") return "inferred";
  return "notfound";
}

function showAlert(container, message, kind = "error") {
  const el = document.createElement("div");
  el.className = `alert alert-${kind}`;
  el.textContent = message;
  container.prepend(el);
  setTimeout(() => el.remove(), 9000);
}

function setLoading(btn, isLoading, loadingText = "Working...") {
  if (!btn) return;
  if (isLoading) {
    btn.dataset.originalText = btn.dataset.originalText || btn.textContent;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> ${loadingText}`;
  } else {
    btn.disabled = false;
    btn.textContent = btn.dataset.originalText || btn.textContent;
  }
}

function safeHttp(url) {
  try { const u = new URL(url); return (u.protocol === "http:" || u.protocol === "https:") ? u.href : null; }
  catch (e) { return null; }
}
