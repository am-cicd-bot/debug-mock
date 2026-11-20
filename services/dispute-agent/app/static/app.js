let activeTicketId = null;
let cachedAccounts = [];

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusBadgeClass(status) {
  if (!status) return "badge-neutral";
  if (status.includes("RESOLVED") || status.includes("POSTED") || status.includes("SUBMITTED")) return "badge-ok";
  if (status.includes("QUEUED") || status.includes("AWAITING") || status.includes("ESCALATED")) return "badge-warn";
  if (status.includes("DENIED") || status.includes("ERROR")) return "badge-err";
  return "badge-neutral";
}

function formatCents(cents) {
  const val = Number(cents || 0) / 100;
  return "$" + val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

document.querySelectorAll(".nav-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    const target = document.getElementById(btn.dataset.view);
    if (target) target.classList.add("active");
    if (btn.dataset.view === "traces-view") loadSpans();
    if (btn.dataset.view === "intake-view") ensureAccountsLoaded();
  });
});

async function loadQueue() {
  const search = document.getElementById("search-input").value.trim();
  const status = document.getElementById("status-filter").value;
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (status) params.set("status", status);

  const listEl = document.getElementById("ticket-list");
  const res = await fetch(`/api/disputes?${params.toString()}`);
  if (!res.ok) {
    listEl.innerHTML = `<div style="padding:16px; color:var(--status-err-fg);">Query failed (HTTP ${res.status})</div>`;
    return;
  }
  const data = await res.json();
  const disputes = data.disputes || [];

  if (!disputes.length) {
    listEl.innerHTML = `<div style="padding:18px; color:var(--text-muted);">No matching dispute tickets.</div>`;
    return;
  }

  listEl.innerHTML = disputes
    .map(
      (d) => `
      <div class="ticket-row ${d.ticket_id === activeTicketId ? "selected" : ""}" data-id="${escapeHtml(d.ticket_id)}">
        <div class="ticket-row-top">
          <span class="mono" style="font-weight:600;">${escapeHtml(d.ticket_id)}</span>
          <span class="badge ${statusBadgeClass(d.status)}">${escapeHtml(d.status)}</span>
        </div>
        <div style="font-size:12.5px; color:var(--text-secondary); margin-bottom:4px;">
          <span class="mono">${escapeHtml(d.account_id)}</span> &middot;
          <span class="mono">${escapeHtml(d.transaction_id)}</span> &middot;
          <span>${escapeHtml(d.dispute_category)}</span>
        </div>
        <div style="font-size:12.5px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          ${escapeHtml(d.customer_narrative)}
        </div>
      </div>
    `
    )
    .join("");

  listEl.querySelectorAll(".ticket-row").forEach((row) => {
    row.addEventListener("click", () => selectTicket(row.dataset.id));
  });

  if (!activeTicketId && disputes.length > 0) {
    selectTicket(disputes[0].ticket_id);
  }
}

async function selectTicket(ticketId) {
  activeTicketId = ticketId;
  document.querySelectorAll(".ticket-row").forEach((r) => {
    r.classList.toggle("selected", r.dataset.id === ticketId);
  });

  const runBtn = document.getElementById("run-triage-btn");
  runBtn.disabled = false;
  document.getElementById("detail-title").textContent = `Dispute Case ${ticketId}`;

  const body = document.getElementById("detail-body");
  body.innerHTML = `<p style="color:var(--text-muted);">Loading case record...</p>`;

  const res = await fetch(`/api/disputes/${encodeURIComponent(ticketId)}`);
  if (!res.ok) {
    body.innerHTML = `<p style="color:var(--status-err-fg);">Unable to load dispute ${escapeHtml(ticketId)}.</p>`;
    return;
  }
  const payload = await res.json();
  renderTicketDetail(payload.dispute, payload.core_ledger_records);
}

function renderTicketDetail(d, ledgerRecords) {
  const body = document.getElementById("detail-body");
  const credits = (ledgerRecords && ledgerRecords.provisional_credits) || [];
  const chargebacks = (ledgerRecords && ledgerRecords.network_chargebacks) || [];
  const steps = d.steps || [];

  const creditsHtml = credits.length
    ? credits
        .map(
          (c) => `
          <div style="padding:8px 0; border-bottom:1px solid var(--border-hairline); font-size:13px;">
            <div><strong class="mono">${escapeHtml(c.credit_id)}</strong> &mdash; Posted Amount: <strong>${formatCents(c.amount_cents)}</strong> (<span class="mono">${c.amount_cents} cents</span>)</div>
            <div style="color:var(--text-muted); font-size:12px;">Idempotency-Key: <span class="mono">${escapeHtml(c.idempotency_key || "none")}</span></div>
          </div>`
        )
        .join("")
    : `<div style="color:var(--text-muted); font-size:13px;">No provisional credit rows in Core Ledger for this ticket.</div>`;

  const cbHtml = chargebacks.length
    ? chargebacks
        .map(
          (cb) => `
          <div style="padding:8px 0; border-bottom:1px solid var(--border-hairline); font-size:13px;">
            <div><strong class="mono">${escapeHtml(cb.filing_id)}</strong> &mdash; Code <span class="mono">${escapeHtml(cb.reason_code)}</span> &middot; ${formatCents(cb.disputed_amount_cents)}</div>
            <div style="color:var(--text-muted); font-size:12px;">Status: ${escapeHtml(cb.network_status)}</div>
          </div>`
        )
        .join("")
    : `<div style="color:var(--text-muted); font-size:13px;">No accepted network chargebacks in Core Ledger for this ticket.</div>`;

  const stepsHtml = steps.length
    ? steps
        .map(
          (s) => `
          <div class="step-item">
            <div style="display:flex; justify-content:space-between; font-size:12.5px;">
              <span><strong>Step ${s.step_number}</strong> &middot; <span class="mono">${escapeHtml(s.action_type)}</span> ${s.tool_name ? `(${escapeHtml(s.tool_name)})` : ""}</span>
              <span class="mono" style="color:var(--text-muted);">${s.latency_ms} ms</span>
            </div>
            <pre class="code-block">${escapeHtml(s.action_type === "TOOL_RESULT" ? s.output_payload : (s.output_payload !== "{}" ? s.output_payload : s.input_payload))}</pre>
          </div>`
        )
        .join("")
    : `<div style="color:var(--text-muted); font-size:13px;">Ticket has not been triaged yet. Click <strong>Run Automated Triage</strong> above.</div>`;

  body.innerHTML = `
    <div class="meta-strip">
      <div>
        <div class="meta-label">Status</div>
        <div class="meta-value"><span class="badge ${statusBadgeClass(d.status)}">${escapeHtml(d.status)}</span></div>
      </div>
      <div>
        <div class="meta-label">Account / TXN</div>
        <div class="meta-value mono">${escapeHtml(d.account_id)} / ${escapeHtml(d.transaction_id)}</div>
      </div>
      <div>
        <div class="meta-label">Reason Code</div>
        <div class="meta-value mono">${escapeHtml(d.assigned_reason_code || "—")}</div>
      </div>
      <div>
        <div class="meta-label">Triage Latency</div>
        <div class="meta-value mono">${d.processing_latency_ms ? `${d.processing_latency_ms} ms` : "—"}</div>
      </div>
      <div>
        <div class="meta-label">OTel Trace ID</div>
        <div class="meta-value mono" style="font-size:11.5px; word-break:break-all;">${escapeHtml(d.trace_id || "—")}</div>
      </div>
    </div>

    <div class="section-heading">Customer Claim &amp; Submitted Evidence</div>
    <div class="prose-box">${escapeHtml(d.customer_narrative)}${d.customer_evidence ? `\n\nEvidence: ${escapeHtml(d.customer_evidence)}` : ""}</div>

    <div class="split-columns">
      <div>
        <div class="section-heading">Core Ledger Provisional Credits (Actual DB State)</div>
        <div class="prose-box">${creditsHtml}</div>
      </div>
      <div>
        <div class="section-heading">Core Network Chargebacks (Actual DB State)</div>
        <div class="prose-box">${cbHtml}</div>
      </div>
    </div>

    <div class="split-columns">
      <div>
        <div class="section-heading">Agent Analyst Summary</div>
        <div class="prose-box">${escapeHtml(d.agent_summary || "Pending triage execution.")}</div>
      </div>
      <div>
        <div class="section-heading">Drafted Customer Response</div>
        <div class="prose-box">${escapeHtml(d.customer_response_draft || "Pending triage execution.")}</div>
      </div>
    </div>

    <div class="section-heading">Agent Reasoning &amp; Tool Execution Steps</div>
    <div>${stepsHtml}</div>
  `;
}

document.getElementById("run-triage-btn").addEventListener("click", async () => {
  if (!activeTicketId) return;
  const btn = document.getElementById("run-triage-btn");
  btn.disabled = true;
  btn.textContent = "Triaging...";
  try {
    const res = await fetch(`/api/disputes/${encodeURIComponent(activeTicketId)}/triage`, {
      method: "POST",
    });
    if (res.ok) {
      const data = await res.json();
      renderTicketDetail(data.dispute, data.core_ledger_records);
      await loadQueue();
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "Run Automated Triage";
  }
});

document.getElementById("refresh-queue-btn").addEventListener("click", loadQueue);
document.getElementById("search-input").addEventListener("input", loadQueue);
document.getElementById("status-filter").addEventListener("change", loadQueue);

async function ensureAccountsLoaded() {
  if (cachedAccounts.length) return;
  const res = await fetch("/api/accounts");
  if (!res.ok) return;
  const data = await res.json();
  cachedAccounts = data.accounts || [];
  const acctSelect = document.getElementById("intake-account");
  acctSelect.innerHTML = cachedAccounts
    .map((a) => `<option value="${escapeHtml(a.account_id)}" data-email="${escapeHtml(a.primary_contact_email)}">${escapeHtml(a.account_id)} — ${escapeHtml(a.company_name)} (${escapeHtml(a.tier)})</option>`)
    .join("");
  acctSelect.addEventListener("change", () => {
    const opt = acctSelect.selectedOptions[0];
    if (opt && opt.dataset.email) {
      document.getElementById("intake-email").value = opt.dataset.email;
    }
    loadAccountTransactions(acctSelect.value);
  });
  if (cachedAccounts.length) {
    loadAccountTransactions(cachedAccounts[0].account_id);
  }
}

async function loadAccountTransactions(accountId) {
  const txSelect = document.getElementById("intake-transaction");
  txSelect.innerHTML = `<option value="">Loading transactions...</option>`;
  const res = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/transactions`);
  if (!res.ok) return;
  const data = await res.json();
  const txns = data.transactions || [];
  txSelect.innerHTML = txns
    .map(
      (t) =>
        `<option value="${escapeHtml(t.transaction_id)}">${escapeHtml(t.transaction_id)} | ${formatCents(t.amount_cents)} | ${escapeHtml(t.payment_rail)} | ${escapeHtml(t.status)} | ${escapeHtml(t.statement_descriptor)}</option>`
    )
    .join("");
}

document.getElementById("intake-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const submitBtn = document.getElementById("intake-submit-btn");
  const statusMsg = document.getElementById("intake-status-msg");
  submitBtn.disabled = true;
  statusMsg.textContent = "Running autonomous triage & clearing...";

  const payload = {
    account_id: document.getElementById("intake-account").value,
    transaction_id: document.getElementById("intake-transaction").value,
    submitted_by_email: document.getElementById("intake-email").value,
    dispute_category: document.getElementById("intake-category").value,
    customer_narrative: document.getElementById("intake-narrative").value,
    customer_evidence: document.getElementById("intake-evidence").value,
    evidence_url: document.getElementById("intake-url").value || null,
    auto_triage: true,
  };

  try {
    const res = await fetch("/api/disputes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const created = await res.json();
      activeTicketId = created.dispute.ticket_id;
      document.getElementById("intake-narrative").value = "";
      document.getElementById("intake-evidence").value = "";
      document.getElementById("intake-url").value = "";
      statusMsg.textContent = "";
      document.querySelector('[data-view="queue-view"]').click();
      await loadQueue();
      await selectTicket(activeTicketId);
    } else {
      statusMsg.textContent = `Submission failed (HTTP ${res.status})`;
    }
  } finally {
    submitBtn.disabled = false;
  }
});

async function loadSpans() {
  const traceId = document.getElementById("trace-filter-input").value.trim();
  const qs = traceId ? `?limit=120&trace_id=${encodeURIComponent(traceId)}` : "?limit=120";
  const res = await fetch(`/api/telemetry/spans${qs}`);
  if (!res.ok) return;
  const data = await res.json();
  const spans = data.spans || [];
  const maxDur = Math.max(1, ...spans.map((s) => s.duration_ms || 1));

  const tbody = document.getElementById("spans-tbody");
  if (!spans.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--text-muted);">No spans recorded yet. Trigger a dispute triage to generate OpenTelemetry traces.</td></tr>`;
    return;
  }

  tbody.innerHTML = spans
    .map((s) => {
      const pct = Math.min(100, Math.max(3, Math.round((s.duration_ms / maxDur) * 100)));
      const attrs = Object.entries(s.attributes || {})
        .slice(0, 4)
        .map(([k, v]) => `${k}=${String(v).slice(0, 48)}`)
        .join(", ");
      return `
        <tr>
          <td class="mono" style="font-size:11.5px;">${escapeHtml(s.trace_id.slice(0, 16))}...</td>
          <td class="mono">${escapeHtml(s.name)}</td>
          <td class="mono">${s.duration_ms}</td>
          <td><div class="latency-bar-track"><div class="latency-bar-fill" style="width:${pct}%"></div></div></td>
          <td><span class="badge ${s.status === "ERROR" ? "badge-err" : "badge-ok"}">${escapeHtml(s.status)}</span></td>
          <td class="mono" style="font-size:11.5px; color:var(--text-secondary);">${escapeHtml(attrs)}</td>
        </tr>
      `;
    })
    .join("");
}

document.getElementById("refresh-spans-btn").addEventListener("click", loadSpans);
document.getElementById("trace-filter-input").addEventListener("input", loadSpans);

loadQueue();
