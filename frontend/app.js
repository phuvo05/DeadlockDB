const elements = {
  balanceA: document.querySelector("#balance-a"),
  balanceB: document.querySelector("#balance-b"),
  total: document.querySelector("#total-balance"),
  invariantTotal: document.querySelector("#invariant-total"),
  invariantStatus: document.querySelector("#invariant-status"),
  serviceStatus: document.querySelector("#service-status"),
  timeline: document.querySelector("#timeline"),
  result: document.querySelector("#result-content"),
  resultBadge: document.querySelector("#result-badge"),
  runId: document.querySelector("#run-id"),
  loading: document.querySelector("#loading-message"),
  error: document.querySelector("#error-message"),
};

const actionButtons = [...document.querySelectorAll("[data-mode]"), document.querySelector("#reset-database")];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function money(value) {
  return `$${Number(value).toLocaleString("en-US")}`;
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.hidden = false;
}

function clearError() {
  elements.error.hidden = true;
  elements.error.textContent = "";
}

async function requestJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("Backend unavailable. Is Docker Compose running?");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || "Unexpected API error";
    if (response.status === 503) throw new Error("Database unavailable. Check PostgreSQL health.");
    if (response.status === 409) throw new Error("Another demo is already running.");
    throw new Error(detail);
  }
  return payload;
}

function updateBalances(payload) {
  const accounts = payload.accounts || payload.balances || [];
  const accountA = accounts.find((account) => account.id === 1);
  const accountB = accounts.find((account) => account.id === 2);
  if (accountA) elements.balanceA.textContent = money(accountA.balance);
  if (accountB) elements.balanceB.textContent = money(accountB.balance);
  if (payload.total_balance !== undefined) {
    elements.total.textContent = money(payload.total_balance);
    elements.invariantTotal.textContent = Number(payload.total_balance).toLocaleString("en-US");
  }
  if (payload.invariant_ok !== undefined) {
    const ok = payload.invariant_ok !== false;
    elements.invariantStatus.textContent = ok ? "A + B = 2,000 ✓" : "DATA INTEGRITY ERROR";
    elements.invariantStatus.classList.toggle("bad", !ok);
  }
}

function setBusy(busy) {
  actionButtons.forEach((button) => { button.disabled = busy; });
  elements.loading.hidden = !busy;
}

function renderTimeline(events = []) {
  if (!events.length) {
    elements.timeline.innerHTML = '<p class="empty-state">No events recorded.</p>';
    return;
  }
  elements.timeline.innerHTML = events.map((event) => {
    const transaction = event.transaction || "RUN";
    const eventClass = event.event.includes("DEADLOCK") ? "event-deadlock" :
      event.event.includes("COMMIT") ? "event-commit" :
      event.event.includes("WAIT") ? "event-wait" : "";
    const chipClass = transaction.toLowerCase();
    return `<div class="timeline-row ${eventClass}">
      <span class="timeline-time">${escapeHtml(event.elapsed_ms)} ms</span>
      <span class="transaction-chip ${chipClass}">${escapeHtml(transaction)}</span>
      <span class="timeline-event"><strong>${escapeHtml(event.event)}</strong><span>${escapeHtml(event.message)}</span></span>
    </div>`;
  }).join("");
}

function explanation(mode, payload) {
  if (mode === "deadlock") {
    return "T1 and T2 acquired the two rows in opposite order. Each waited for a row owned by the other, creating a circular wait. PostgreSQL detected the cycle and aborted the selected victim with SQLSTATE 40P01.";
  }
  if (mode === "safe-ordering") {
    return "Both transactions acquired account IDs in ascending order. T2 may wait for T1, but there is no circular dependency, so this is lock contention rather than a deadlock.";
  }
  return "The first attempt created a real deadlock. The victim rolled back, waited with bounded backoff and jitter, then retried the complete transaction and committed.";
}

function renderBloomResult(payload) {
  elements.resultBadge.textContent = "Probabilistic lookup";
  elements.resultBadge.className = "result-badge neutral";
  const checks = (payload.checks || []).map((check) => {
    const statusClass = check.maybe_present ? "bloom-maybe" : "bloom-absent";
    const groundTruth = check.inserted ? "Inserted sample" : "Not inserted";
    return `<article class="bloom-check ${statusClass}">
      <header><strong>${escapeHtml(check.value)}</strong><span>${escapeHtml(check.interpretation)}</span></header>
      <p>${escapeHtml(groundTruth)} · maybe_present=${escapeHtml(check.maybe_present)}</p>
    </article>`;
  }).join("");
  const applications = (payload.applications || []).map((application) =>
    `<li>${escapeHtml(application)}</li>`
  ).join("");
  const rate = `${(Number(payload.estimated_false_positive_rate || 0) * 100).toFixed(2)}%`;
  elements.result.innerHTML = `<div class="result-summary">
    <div class="metric"><span class="metric-label">Bit array</span><span class="metric-value">${escapeHtml(payload.bit_size)}</span></div>
    <div class="metric"><span class="metric-label">Hash functions</span><span class="metric-value">${escapeHtml(payload.hash_count)}</span></div>
    <div class="metric"><span class="metric-label">Inserted items</span><span class="metric-value">${escapeHtml(payload.inserted_items?.length || 0)}</span></div>
    <div class="metric"><span class="metric-label">Estimated false positives</span><span class="metric-value">${escapeHtml(rate)}</span></div>
  </div><div class="bloom-list">${checks}</div>
  <div class="bloom-applications"><span class="metric-label">Useful applications</span><ul>${applications}</ul></div>
  <p class="explanation">False means definitely absent. True only means possibly present, so production code must confirm positive matches against the source of truth.</p>`;
}

function renderResult(payload) {
  if (payload.mode === "bloom-filter") {
    renderBloomResult(payload);
    return;
  }
  const deadlock = payload.deadlock_detected;
  elements.resultBadge.textContent = deadlock ? "Deadlock observed" : "Completed safely";
  elements.resultBadge.className = `result-badge ${deadlock ? "danger" : "success"}`;
  const victim = payload.victim || "None";
  const transactions = (payload.transactions || []).map((transaction) => {
    const statusClass = transaction.status === "COMMITTED" ? "" : "rollback";
    const victimText = transaction.deadlock_victim ? " · deadlock victim" : "";
    const retryText = transaction.attempts > 1 ? ` · attempt ${transaction.attempts}` : "";
    return `<article class="tx-card"><header><strong>${escapeHtml(transaction.transaction_id)}</strong><span class="tx-status ${statusClass}">${escapeHtml(transaction.status)}</span></header>
      <p class="tx-meta">${escapeHtml(transaction.source_id)} → ${escapeHtml(transaction.destination_id)} · ${money(transaction.amount)}${escapeHtml(victimText)}${escapeHtml(retryText)}${transaction.sqlstate ? ` · SQLSTATE ${escapeHtml(transaction.sqlstate)}` : ""}</p></article>`;
  }).join("");
  elements.result.innerHTML = `<div class="result-summary">
    <div class="metric"><span class="metric-label">Deadlock</span><span class="metric-value ${deadlock ? "bad" : "good"}">${deadlock ? "YES" : "NO"}</span></div>
    <div class="metric"><span class="metric-label">Victim</span><span class="metric-value">${escapeHtml(victim)}</span></div>
    <div class="metric"><span class="metric-label">SQLSTATE</span><span class="metric-value">${escapeHtml((payload.transactions.find((item) => item.sqlstate) || {}).sqlstate || "—")}</span></div>
    <div class="metric"><span class="metric-label">Duration</span><span class="metric-value">${escapeHtml(payload.duration_ms)} ms</span></div>
  </div><div class="tx-list">${transactions}</div><p class="explanation">${escapeHtml(explanation(payload.mode, payload))}</p>`;
}

async function refreshAccounts() {
  const payload = await requestJson("/api/accounts");
  updateBalances(payload);
  elements.serviceStatus.textContent = "Database connected";
  elements.serviceStatus.className = "status-pill ok";
}

async function runDemo(mode) {
  clearError();
  setBusy(true);
  elements.loading.textContent = mode === "bloom-filter"
    ? "Building an in-memory Bloom Filter…"
    : "Running two PostgreSQL transactions…";
  elements.runId.textContent = "Running…";
  try {
    const payload = await requestJson(`/api/demo/${mode}`, { method: "POST" });
    updateBalances(payload);
    renderTimeline(payload.events);
    renderResult(payload);
    elements.runId.textContent = `run_id ${payload.run_id}`;
  } catch (error) {
    showError(error.message || "Unexpected API error");
    elements.runId.textContent = "Run failed";
  } finally {
    setBusy(false);
  }
}

async function resetDatabase() {
  clearError();
  setBusy(true);
  try {
    const payload = await requestJson("/api/reset", { method: "POST" });
    updateBalances(payload);
    elements.timeline.innerHTML = '<p class="empty-state">Database reset. Choose a scenario to see PostgreSQL events.</p>';
    elements.result.innerHTML = '<p class="empty-state">Run a demo to see the deadlock victim, SQLSTATE, and final state.</p>';
    elements.resultBadge.textContent = "Reset";
    elements.resultBadge.className = "result-badge neutral";
    elements.runId.textContent = "No run yet";
  } catch (error) {
    showError(error.message || "Unexpected API error");
  } finally {
    setBusy(false);
  }
}

document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => runDemo(button.dataset.mode));
});
document.querySelector("#reset-database").addEventListener("click", resetDatabase);

refreshAccounts().catch((error) => {
  elements.serviceStatus.textContent = "Database unavailable";
  elements.serviceStatus.className = "status-pill error";
  showError(error.message || "Backend unavailable");
});
