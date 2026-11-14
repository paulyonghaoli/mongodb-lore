// Lore interface: plain JS, no build step.
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let sessionId = null;

function userId() { return $("#user").value; }

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-User": userId() },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : res.statusText);
  return data;
}

function fmt(v) {
  if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(Math.abs(v) < 1 ? 4 : 2);
  if (v && typeof v === "object") return JSON.stringify(v);
  return v;
}

function table(columns, rows) {
  if (!rows?.length) return '<p class="muted small">No rows.</p>';
  return `<table><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows
    .slice(0, 50)
    .map((r) => `<tr>${columns.map((c) => `<td>${esc(fmt(r[c]))}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;
}

function resultCard(r, title) {
  const g = r.governance || {};
  const gov = g.rejected
    ? `<div class="gov rejected"><strong>Blocked by the query guard:</strong> ${esc(g.rejected)}</div>`
    : `<div class="gov"><strong>Permissions applied:</strong> row filter ${esc(JSON.stringify(g.row_filter || {}))}
       ${g.removed_fields?.length ? `· removed fields: ${g.removed_fields.map((f) => `<span class="chip">${esc(f)}</span>`).join("")}` : "· no fields removed"}</div>`;
  const mems = r.memories_used?.length
    ? r.memories_used.map((m) => `<span class="chip" title="${esc(m.content)}">${esc(m.title)} v${m.version}</span>`).join("")
    : '<span class="muted">none</span>';
  const pending = r.proposed_memory_pending
    ? `<div class="pending">Proposed a memory correction for review: <strong>${esc(r.proposed_memory_pending.title)}</strong>
       v${r.proposed_memory_pending.version} (${esc(r.proposed_memory_pending.memory_id)})</div>`
    : "";
  return `<div class="card">
    ${title ? `<h3>${esc(title)}</h3>` : ""}
    <div class="answer">${esc(r.answer)}</div>
    <div class="small"><strong>Memory used:</strong> ${mems}
      ${r.metrics_used?.length ? ` · <strong>Metrics:</strong> ${r.metrics_used.map((m) => `<span class="chip">${esc(m)}</span>`).join("")}` : ""}
      ${r.skill_used ? ` · <strong>Skill:</strong> <span class="chip">${esc(r.skill_used.name)}</span>` : ""}</div>
    ${gov}${pending}
    ${table(r.columns, r.rows)}
    <details><summary class="small">Interpretation, assumptions and pipeline</summary>
      <p class="small">${esc(r.interpretation)}</p>
      ${r.assumptions?.length ? `<ul class="small">${r.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
      <pre>${esc(JSON.stringify(r.pipeline, null, 2))}</pre>
      <p class="muted small">Turn ${esc(r.turn_id)} · ${esc(r.outcome)} · ${r.usage?.calls ?? 0} model calls</p>
    </details>
  </div>`;
}

async function withBusy(btns, fn) {
  btns.forEach((b) => (b.disabled = true));
  try { await fn(); } catch (e) { alert(e.message); } finally { btns.forEach((b) => (b.disabled = false)); }
}

// ---------- analyst ----------
$("#ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#question").value.trim();
  if (!q) return;
  withBusy([...document.querySelectorAll("#ask-form button")], async () => {
    $("#results").className = "";
    $("#results").innerHTML = '<p class="muted">Thinking…</p>';
    const r = await api("/api/ask", { method: "POST", body: { question: q, session_id: sessionId, use_memory: $("#use-memory").checked } });
    sessionId = r.session_id; $("#session-id").textContent = sessionId;
    $("#results").innerHTML = resultCard(r);
  });
});

$("#replay").addEventListener("click", () => {
  const q = $("#question").value.trim();
  if (!q) return;
  withBusy([...document.querySelectorAll("#ask-form button")], async () => {
    $("#results").className = "compare";
    $("#results").innerHTML = '<p class="muted">Running twice…</p>';
    const r = await api("/api/replay", { method: "POST", body: { question: q, session_id: sessionId } });
    sessionId = r.with_memory.session_id; $("#session-id").textContent = sessionId;
    $("#results").innerHTML = resultCard(r.without_memory, "Without memory") + resultCard(r.with_memory, "With shared memory");
  });
});

$("#new-session").addEventListener("click", (e) => { e.preventDefault(); sessionId = null; $("#session-id").textContent = "new"; });

// ---------- reviewer ----------
async function loadMemories() {
  const status = $("#mem-status").value;
  const mems = await api(`/api/memories${status ? `?status=${status}` : ""}`);
  const me = window.__me;
  $("#mem-table tbody").innerHTML = mems.map((m) => {
    const actions = [];
    if (me?.can_review) {
      if (m.status === "pending") actions.push(["approve", "Approve"], ["reject", "Reject"]);
      if (m.status === "active") actions.push(["expire", "Expire"]);
      if (m.status !== "forgotten") actions.push(["forget", "Forget"]);
    }
    const extra = m.forgotten ? `<div class="muted small">forgotten by ${esc(m.forgotten.by)}: ${esc(m.forgotten.reason)}</div>` : "";
    return `<tr>
      <td>${esc(m.memory_id)}</td><td>${esc(m.title)}${m.source?.corrects_memory ? `<div class="muted small">corrects ${esc(m.source.corrects_memory)}</div>` : ""}</td><td>${m.version}</td>
      <td class="status-${esc(m.status)}">${esc(m.status)}</td>
      <td>${(m.visibility || []).map((v) => `<span class="chip">${esc(v)}</span>`).join("")}</td>
      <td class="small">${m.expires_at ? esc(new Date(m.expires_at).toLocaleString()) : "No expiry"}</td>
      <td class="content">${esc(m.content)}${extra}</td>
      <td class="small">${esc(m.source?.proposed_by)}${m.approved_by ? ` → ${esc(m.approved_by)}` : ""}</td>
      <td>${actions.map(([a, l]) => `<button data-mem="${esc(m.memory_id)}" data-act="${a}">${l}</button>`).join(" ")}</td>
    </tr>`;
  }).join("");
}

async function loadMonthlyReview() {
  const runs = await api("/api/memory-review/runs");
  const select = $("#monthly-batch");
  const previous = select.value;
  select.innerHTML = '<option value="">Select a completed scan</option>' + runs
    .filter((r) => r.status === "complete")
    .map((r) => `<option value="${esc(r.batch_id)}">${esc(r.batch_id)}</option>`).join("");
  if (runs.some((r) => r.batch_id === previous && r.status === "complete")) select.value = previous;
  else if (select.options.length > 1) select.selectedIndex = 1;

  const batch = select.value;
  if (!batch) {
    $("#query-review-table tbody").innerHTML = "";
    $("#memory-review-table tbody").innerHTML = "";
    return;
  }
  const [queries, memories] = await Promise.all([
    api(`/api/memory-review/items?batch_id=${encodeURIComponent(batch)}&item_type=query&status=pending`),
    api(`/api/memory-review/items?batch_id=${encodeURIComponent(batch)}&item_type=memory&status=pending`),
  ]);
  $("#query-review-table tbody").innerHTML = queries.map((item) => `<tr>
    <td>${esc(item.user_id)} <span class="muted small">(${esc(item.role)})</span></td>
    <td class="content">${esc(item.question)}</td><td>${esc(item.outcome)}</td>
    <td><button data-review-item="${esc(item.item_id)}" data-review-action="retain">Keep</button>
        <button data-review-item="${esc(item.item_id)}" data-review-action="delete">Delete query</button></td>
  </tr>`).join("");
  $("#memory-review-table tbody").innerHTML = memories.map((item) => `<tr>
    <td>${esc(item.title)} <span class="muted small">${esc(item.memory_id)}</span></td>
    <td>${item.version}</td><td class="content">${esc(item.content)}<div class="muted small">${esc(item.review_reason)}</div></td>
    <td><button data-review-item="${esc(item.item_id)}" data-review-action="retain">Keep memory</button>
        <button data-review-item="${esc(item.item_id)}" data-review-action="delete">Forget memory</button></td>
  </tr>`).join("");
}

$("#monthly-run").addEventListener("click", (e) => withBusy([e.target], async () => {
  const summary = await api("/api/memory-review/run", { method: "POST" });
  alert(`Monthly review ${summary.batch_id}: ${summary.query_items} queries, ${summary.memory_items} unused memories, ${summary.proposed_memory_ids.length} memory proposals.`);
  await loadMonthlyReview();
}));
$("#monthly-refresh").addEventListener("click", () => loadMonthlyReview().catch((e) => alert(e.message)));
$("#monthly-batch").addEventListener("change", () => loadMonthlyReview().catch((e) => alert(e.message)));
document.querySelector("#reviewer").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-review-item]");
  if (!b) return;
  const action = b.dataset.reviewAction, itemId = b.dataset.reviewItem;
  let body;
  if (action === "delete") {
    const reason = prompt("Reason for deleting this query or forgetting this memory:");
    if (reason === null) return;
    body = { reason };
  }
  withBusy([b], async () => {
    await api(`/api/memory-review/items/${encodeURIComponent(itemId)}/${action}`, {
      method: "POST", ...(body ? { body } : {}),
    });
    await loadMonthlyReview();
    await loadMemories();
  });
});

$("#mem-table").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const act = b.dataset.act, id = b.dataset.mem;
  let body = {};
  if (act === "approve") {
    const row = b.closest("tr");
    const current = [...row.querySelectorAll(".chip")].map((x) => x.textContent).join(", ");
    const roles = prompt("Roles that can read this memory (finance_lead, analyst, store_manager):", current);
    if (roles === null) return;
    const selected = roles.split(",").map((x) => x.trim()).filter(Boolean);
    if (!selected.length) { alert("Select at least one role."); return; }
    const expiry = prompt("Expiry date/time in ISO format, or leave blank for no expiry:", "");
    if (expiry === null) return;
    body = { visibility: selected, ...(expiry.trim() ? { expires_at: expiry.trim() } : {}) };
  }
  if (act === "reject" || act === "forget" || act === "expire") {
    const reason = prompt(`Reason to ${act} ${id}?`);
    if (reason === null) return;
    body = { reason };
  }
  withBusy([b], async () => { await api(`/api/memories/${id}/${act}`, { method: "POST", body }); await loadMemories(); });
});

async function loadSkills() {
  const [clusters, { skills }] = await Promise.all([api("/api/skills/clusters"), api("/api/skills")]);
  $("#cluster-table tbody").innerHTML = clusters.map((c) => `<tr><td>${esc(c.cluster_id)}</td><td>${esc(c.intent)}</td>
    <td>${c.episodes}</td><td>${c.users.map((u) => `<span class="chip">${esc(u)}</span>`).join("")}</td>
    <td class="${c.ready ? "pass" : "muted"}">${c.ready ? "ready" : "not yet"}</td></tr>`).join("");
  $("#skill-table tbody").innerHTML = skills.map((s) => `<tr><td>${esc(s.name)}</td><td>${s.version}</td>
    <td class="status-${esc(s.status)}">${esc(s.status)}</td><td>${esc(s.description)}</td>
    <td>${(s.required_fields || []).map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</td>
    <td>${Object.entries(s.test_results || {}).map(([k, v]) => `${esc(k)}: <span class="${esc(v)}">${esc(v)}</span>`).join("<br>")}</td>
    <td>${window.__me?.can_review && ["draft", "stale"].includes(s.status) ? `<button data-skill="${esc(s.name)}">Publish</button>` : ""}</td></tr>`).join("");
}

$("#skill-table").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-skill]");
  if (b) withBusy([b], async () => { await api(`/api/skills/${b.dataset.skill}/publish`, { method: "POST" }); await loadSkills(); });
});
$("#skills-generate").addEventListener("click", (e) =>
  withBusy([e.target], async () => { await api("/api/skills/generate", { method: "POST", body: {} }); await loadSkills(); }));
$("#skills-refresh").addEventListener("click", () => loadSkills().catch((e) => alert(e.message)));
$("#mem-refresh").addEventListener("click", () => loadMemories().catch((e) => alert(e.message)));
$("#mem-status").addEventListener("change", () => loadMemories().catch((e) => alert(e.message)));

// ---------- audit ----------
async function loadAudit() {
  const events = await api("/api/audit?limit=100");
  $("#audit-table tbody").innerHTML = events.map((ev) => `<tr><td class="small">${esc(ev.ts.replace("T", " ").slice(0, 19))}</td>
    <td>${esc(ev.actor)}</td><td>${esc(ev.role)}</td><td>${esc(ev.action)}</td>
    <td>${esc(ev.target?.kind)} ${esc(ev.target?.id)}</td>
    <td class="content small">${esc(JSON.stringify(Object.fromEntries(Object.entries(ev.details || {}).filter(([k]) => k !== "pipeline"))))}</td></tr>`).join("");
}
$("#audit-refresh").addEventListener("click", () => loadAudit().catch((e) => alert(e.message)));

// ---------- tabs and users ----------
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("hidden", p.id !== t.dataset.tab));
  if (t.dataset.tab === "reviewer") { loadMemories().catch((e) => alert(e.message)); loadSkills().catch((e) => alert(e.message)); loadMonthlyReview().catch((e) => alert(e.message)); }
  if (t.dataset.tab === "audit") loadAudit().catch((e) => alert(e.message));
}));

async function init() {
  const users = await fetch("/api/users").then((r) => r.json());
  $("#user").innerHTML = users.map((u) => `<option value="${esc(u.user_id)}">${esc(u.display_name)}</option>`).join("");
  const onUser = async () => { window.__me = users.find((u) => u.user_id === userId()); sessionId = null; $("#session-id").textContent = "new"; };
  $("#user").addEventListener("change", onUser);
  onUser();
}
init();
