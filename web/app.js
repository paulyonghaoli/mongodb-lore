// Lore interface: plain JS, no build step.
// Analyst view (ask, replay with and without memory, compare roles), reviewer view (memory
// lifecycle), skills and the audit log. Every request carries the current user in X-User;
// permissions are enforced by the server, the interface only shows what was applied.
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ROLE_LABELS = { finance_lead: "Finance lead", analyst: "Analyst", store_manager: "Store manager" };
const roleLabel = (r) => ROLE_LABELS[r] || r;
// The questions most likely to be asked in the demo, grouped by what they show. Edit this list to
// change the templates on the Analyst view. `as` is the user a question is written for: clicking it
// signs in as that user first. Without `as`, the question is asked as whoever is signed in.
const TEMPLATES = [
  { group: "Memory changes the answer", hint: "Then use Compare: With and without memory", items: [
    { q: "What was net margin by region in Q3?" },
    { q: "Net margin must subtract returns. Show Q3 by region again", as: "fatima" },
    { q: "Which region had the weakest margin last quarter?" },
    { q: "What were October sales by region, on the basis we use for Q4 targets?" },
  ] },
  { group: "Who can see what", hint: "Then use Compare: Across all roles", items: [
    { q: "Return rate by region in Q3" },
    { q: "Why did East's return rate rise in Q3?" },
    { q: "Which of my stores lost margin since July?", as: "sam" },
    { q: "What is our supplier cost for footwear?", as: "sam" },
    { q: "Why is footwear margin lower than other categories?", as: "fatima" },
  ] },
  { group: "Repeated analyses", hint: "Answered questions like these become episodes, and then a skill", items: [
    { q: "Return rate by category in September" },
    { q: "Return rate by category in October" },
    { q: "Sales growth by region, August to September" },
  ] },
];

const state = {
  users: [], me: null, tab: "analyst",
  sessionId: null, runs: null, runToken: 0,
  memories: [], memFilter: "", audit: [], auditFilter: "",
};

async function api(path, { method = "GET", body, as } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-User": as || state.me.user_id },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `${res.status} ${res.statusText}`);
  }
  return data;
}

// ---------- small helpers ----------
const slug = (t) => String(t).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const shortName = (u) => (u?.display_name || u?.user_id || "").split(" (")[0];
const userName = (id) => { const u = state.users.find((x) => x.user_id === id); return u ? shortName(u) : id; };
const plural = (n, word) => `${n} ${n === 1 ? word : word.replace(/y$/, "ie") + "s"}`;
const tags = (list, cls = "chip") => list.map((v) => `<span class="${cls}">${esc(v)}</span>`).join("");
const roleTags = (roles) => tags((roles || []).map(roleLabel));

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d)) return String(ts);
  const time = d.toLocaleTimeString("en-CA", { hour12: false });
  return d.toDateString() === new Date().toDateString()
    ? time : `${d.toLocaleDateString("en-CA", { month: "short", day: "numeric" })}, ${time.slice(0, 5)}`;
}
const fmtDate = (ts) => { const d = new Date(ts); return isNaN(d) ? String(ts) : d.toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }); };

function toast(message, bad = false) {
  const el = document.createElement("div");
  el.className = `toast${bad ? " bad" : ""}`;
  el.textContent = message;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), bad ? 7000 : 4000);
}

async function busy(buttons, fn) {
  buttons.forEach((b) => (b.disabled = true));
  try { await fn(); } catch (e) { toast(e.message, true); } finally { buttons.forEach((b) => (b.disabled = false)); }
}

// One dialog for every reviewer decision, so reasons are typed in the page and not in a browser prompt.
function openDialog({ title, body, confirm, danger, onSubmit }) {
  const dlg = $("#dialog");
  $("#dialog-title").textContent = title;
  $("#dialog-body").innerHTML = body;
  $("#dialog-error").classList.add("hidden");
  const ok = $("#dialog-confirm");
  ok.textContent = confirm;
  ok.className = danger ? "danger solid" : "";
  $("#dialog-form").onsubmit = async (e) => {
    e.preventDefault();
    ok.disabled = true;
    try {
      await onSubmit(new FormData($("#dialog-form")));
      dlg.close();
    } catch (err) {
      $("#dialog-error").textContent = err.message;
      $("#dialog-error").classList.remove("hidden");
    } finally { ok.disabled = false; }
  };
  dlg.showModal();
  ($("textarea, input", $("#dialog-body")) || ok).focus();
}
$("#dialog-cancel").addEventListener("click", () => $("#dialog").close());

// Answers use light markdown (bold and bullet lists). Everything is escaped first.
function formatAnswer(text) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const out = [];
  let items = [];
  const flush = () => { if (items.length) { out.push(`<ul>${items.map((x) => `<li>${x}</li>`).join("")}</ul>`); items = []; } };
  for (const line of String(text ?? "").split("\n")) {
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bullet) items.push(inline(bullet[1]));
    else { flush(); if (line.trim()) out.push(`<p>${inline(line)}</p>`); }
  }
  flush();
  return out.join("");
}

// ---------- result tables ----------
const RATIO_COLUMN = /(rate|margin|growth|share|ratio)/i;
const ALREADY_PERCENT = /(pct|percent)/i;

function columnKinds(columns, rows) {
  const kinds = {};
  for (const c of columns) {
    const nums = rows.map((r) => r[c]).filter((v) => typeof v === "number");
    kinds[c] = nums.length && RATIO_COLUMN.test(c) && !ALREADY_PERCENT.test(c) && nums.every((v) => Math.abs(v) <= 1.5)
      ? "ratio" : "plain";
  }
  return kinds;
}

function fmtCell(v, kind) {
  if (v === null || v === undefined) return '<span class="muted">–</span>';
  if (typeof v === "number") {
    if (kind === "ratio") return `${(v * 100).toFixed(1)}%`;
    if (Number.isInteger(v)) return v.toLocaleString("en-CA");
    const digits = Math.abs(v) < 1 ? 4 : 2;
    return v.toLocaleString("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: digits });
  }
  if (typeof v === "object") return esc(JSON.stringify(v));
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T00:00:00/.test(v)) return v.slice(0, 10);
  return esc(v);
}

function resultTable(r, changed) {
  const rows = r.rows || [], columns = r.columns || [];
  if (!rows.length) return r.outcome === "answered" ? '<p class="muted small">The query returned no rows.</p>' : "";
  const kinds = columnKinds(columns, rows);
  const isNum = (c) => rows.some((x) => typeof x[c] === "number");
  const head = columns.map((c) => `<th class="${isNum(c) ? "num" : ""}">${esc(c)}</th>`).join("");
  const body = rows.slice(0, 50).map((row, i) => `<tr>${columns.map((c) => {
    const cls = [typeof row[c] === "number" ? "num" : "", changed?.has(`${i}:${c}`) ? "changed" : ""].join(" ").trim();
    const raw = typeof row[c] === "number" ? ` title="${esc(row[c])}"` : "";
    return `<td class="${cls}"${raw}>${fmtCell(row[c], kinds[c])}</td>`;
  }).join("")}</tr>`).join("");
  const note = rows.length > 50 ? `Showing 50 of ${rows.length} rows` : plural(rows.length, "row");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <div class="muted small">${note}</div>`;
}

// Cells in `run` whose number differs from the same row in `base`. Rows are matched on their text
// columns. Two runs may name a column differently, so a number that appears anywhere in the matching
// base row counts as unchanged.
function diffRows(base, run) {
  const changed = new Set();
  if (!base?.rows || !run?.rows) return changed;
  const keyOf = (r) => {
    const cols = r.columns.filter((c) => r.rows.some((x) => x[c] != null && typeof x[c] !== "number"));
    return cols.length ? (row) => cols.map((c) => JSON.stringify(row[c])).join("|") : (row, i) => String(i);
  };
  const baseKey = keyOf(base), runKey = keyOf(run);
  const index = new Map(base.rows.map((row, i) => [baseKey(row, i), row]));
  run.rows.forEach((row, i) => {
    const b = index.get(runKey(row, i));
    const baseNumbers = b ? Object.values(b).filter((x) => typeof x === "number") : [];
    for (const c of run.columns) {
      const v = row[c];
      if (typeof v !== "number") continue;
      const same = (x) => Math.abs(x - v) <= 5e-5 * Math.max(1, Math.abs(v));
      const unchanged = b && (typeof b[c] === "number" ? same(b[c]) : baseNumbers.some(same));
      if (!unchanged) changed.add(`${i}:${c}`);
    }
  });
  return changed;
}

// Line-level diff of two pretty-printed pipelines: returns the line numbers unique to each side.
function lineDiff(a, b) {
  const norm = (s) => s.trim().replace(/,$/, "");
  const A = a.map(norm), B = b.map(norm);
  const dp = Array.from({ length: A.length + 1 }, () => new Uint16Array(B.length + 1));
  for (let i = A.length - 1; i >= 0; i--) {
    for (let j = B.length - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const onlyA = new Set(), onlyB = new Set();
  let i = 0, j = 0;
  while (i < A.length && j < B.length) {
    if (A[i] === B[j]) { i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) onlyA.add(i++);
    else onlyB.add(j++);
  }
  while (i < A.length) onlyA.add(i++);
  while (j < B.length) onlyB.add(j++);
  return [onlyA, onlyB];
}

const pipelineLines = (r) => JSON.stringify(r?.pipeline ?? [], null, 2).split("\n");
const pipelineHtml = (lines, marked) =>
  `<pre>${lines.map((l, i) => `<span class="ln${marked?.has(i) ? " diff" : ""}">${esc(l) || " "}</span>`).join("")}</pre>`;

// ---------- analyst: one run rendered as a card ----------
function appliedMemories(r) {
  const cited = new Set((r.metrics_used || []).map((m) => m.split("@")[0]));
  const used = r.memories_used || [];
  return [used.filter((m) => cited.has(slug(m.title))), used.filter((m) => !cited.has(slug(m.title)))];
}

function permissionsBox(r) {
  const g = r.governance || {};
  const rows = Object.entries(g.row_filter || {});
  const removed = g.removed_fields || [];
  const cls = g.rejected ? "box-bad" : rows.length || removed.length ? "box-warn" : "";
  return `<div class="box ${cls}">
    <div class="box-title">Permissions applied</div>
    <div class="kv"><span>Rows</span><span>${rows.length ? tags(rows.map(([k, v]) => `${k} = ${v}`)) : "All rows"}</span></div>
    <div class="kv"><span>Hidden fields</span><span>${removed.length ? tags(removed) : "None"}</span></div>
    ${g.hidden_fields_referenced?.length ? `<div class="kv"><span>Query used</span><span>${tags(g.hidden_fields_referenced)}</span></div>` : ""}
  </div>`;
}

function memoryBox(r) {
  let body;
  if (!r.use_memory) body = '<span class="muted">Switched off for this run.</span>';
  else if (!r.memories_used?.length) body = '<span class="muted">No memory was retrieved for this question.</span>';
  else {
    const [applied, others] = appliedMemories(r);
    body = applied.map((m) => `<div class="mem-used"><span class="chip chip-accent">${esc(m.title)} v${esc(m.version)}</span>
      <span class="def">${esc(m.content)}</span></div>`).join("");
    if (others.length) {
      body += `<div class="muted">${applied.length ? "Also in context" : "In context"}: ${others.map((m) =>
        `<span class="chip" title="${esc(m.content)}">${esc(m.title)} v${esc(m.version)}</span>`).join("")}</div>`;
    }
  }
  const skill = r.skill_used
    ? `<div class="mem-used"><span class="muted">Reused skill</span> <span class="chip chip-accent">${esc(r.skill_used.name)}</span>
       <code>${esc(JSON.stringify(r.skill_used.parameters || {}))}</code></div>` : "";
  return `<div class="box"><div class="box-title">Shared memory</div>${body}${skill}</div>`;
}

function proposalCallout(r) {
  const p = r.proposed_memory_pending;
  if (!p) return "";
  const next = state.me.can_review
    ? '<button type="button" class="link" data-goto="reviewer">Review it now</button>'
    : "A reviewer must approve it before it changes anyone's answers.";
  return `<div class="callout pending"><span class="label">Correction proposed for review:</span>
    ${esc(p.title)} v${esc(p.version)} · visible to ${roleTags(p.visibility)}
    <div class="small">${esc(p.content)}</div><div class="small">${next}</div></div>`;
}

const OUTCOMES = {
  answered: ["Answered", "tag-ok"], user_confirmed: ["Answered", "tag-ok"],
  rejected: ["Blocked by the query guard", "tag-bad"], failed: ["Query failed", "tag-bad"],
};

function runCard(run, { changed, marked, showPipeline } = {}) {
  const head = (extra = "") => `<div class="card-head"><h3>${esc(run.title)}</h3>${extra}</div>`;
  if (run.error) return `<div class="card">${head('<span class="tag tag-bad">Request failed</span>')}<div class="callout bad">${esc(run.error)}</div></div>`;
  if (!run.result) {
    return `<div class="card">${head()}<div class="waiting"><span class="spinner"></span>
      Planning, running and explaining… <span class="elapsed" data-start="${run.started}">0s</span></div></div>`;
  }
  const r = run.result;
  const [label, cls] = OUTCOMES[r.outcome] || [r.outcome, ""];
  const blocked = r.outcome === "rejected";
  const answer = blocked
    ? `<div class="callout bad"><span class="label">Blocked by the query guard.</span> ${esc(r.governance?.rejected || r.answer)}</div>
       <div class="answer small"><span class="muted">What the agent tried:</span> ${esc(r.interpretation)}</div>`
    : r.outcome === "failed"
      ? `<div class="callout bad">${esc(r.answer)}</div>`
      : `<div class="answer">${formatAnswer(r.answer)}</div>`;
  const assumptions = r.assumptions?.length ? `<ul class="small">${r.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "";
  const usage = r.usage ? ` · ${plural(r.usage.calls ?? 0, "model call")} · ${(r.usage.input_tokens ?? 0) + (r.usage.output_tokens ?? 0)} tokens` : "";
  return `<div class="card">
    ${head(`<span class="tag ${cls}">${esc(label)}</span>`)}
    ${answer}
    ${resultTable(r, changed)}
    <div class="boxes">${permissionsBox(r)}${memoryBox(r)}</div>
    ${proposalCallout(r)}
    <details${showPipeline ? " open" : ""}><summary>Query, interpretation and assumptions</summary>
      ${blocked ? "" : `<p class="small">${esc(r.interpretation)}</p>`}
      ${assumptions}
      ${pipelineHtml(pipelineLines(r), marked)}
      <p class="muted small">Turn ${esc(r.turn_id)}${usage}</p>
    </details>
  </div>`;
}

// ---------- analyst: comparison summaries ----------
function replaySummary(without, withMem) {
  if (!without.result || !withMem.result) return "";
  const a = without.result, b = withMem.result;
  const [applied] = appliedMemories(b);
  const samePipeline = JSON.stringify(a.pipeline) === JSON.stringify(b.pipeline);
  const changed = diffRows(a, b);
  const numbers = (b.rows || []).reduce((n, row) => n + (b.columns || []).filter((c) => typeof row[c] === "number").length, 0);
  // Say only what the two runs show: a reworded query with the same numbers is not a changed result.
  const resultDiffers = changed.size > 0 || a.outcome !== b.outcome;
  const differs = resultDiffers || !samePipeline;
  const headline = resultDiffers ? "Shared memory changed the result"
    : samePipeline ? "Same query and result with and without memory"
      : "Shared memory changed the query, and the numbers came out the same";
  const facts = [
    applied.length ? `Definition applied: ${applied.map((m) => `${esc(m.title)} v${esc(m.version)}`).join(", ")}`
      : `${plural((b.memories_used || []).length, "memory")} in context, none cited as a metric definition`,
    samePipeline ? "The query is identical in both runs" : "The query is different (changed lines are highlighted)",
    a.outcome !== b.outcome ? `Outcome: ${esc(a.outcome)} without memory, ${esc(b.outcome)} with it`
      : `${changed.size} of ${numbers} numbers differ${changed.size ? " (highlighted)" : ""}`,
  ];
  return `<div class="summary${differs ? "" : " same"}"><strong>${headline}</strong>
    <ul>${facts.map((f) => `<li>${f}</li>`).join("")}</ul></div>`;
}

function rolesSummary(runs) {
  if (runs.some((x) => !x.result && !x.error)) return "";
  const facts = runs.map((x) => {
    if (x.error) return `<strong>${esc(x.title)}</strong>: request failed`;
    const r = x.result, g = r.governance || {};
    const limits = [
      ...Object.entries(g.row_filter || {}).map(([k, v]) => `rows where ${k} = ${v}`),
      ...((g.removed_fields || []).length ? [`without ${g.removed_fields.join(", ")}`] : []),
    ];
    const what = r.outcome === "rejected" ? "blocked by the query guard" : r.outcome === "failed" ? "query failed" : plural((r.rows || []).length, "row");
    return `<strong>${esc(shortName(x.user))}</strong> (${esc(roleLabel(x.user.role))}): ${esc(what)}${limits.length ? `, ${esc(limits.join(", "))}` : ", all rows and fields"}`;
  });
  return `<div class="summary"><strong>One question, each role's own answer</strong>
    <ul>${facts.map((f) => `<li>${f}</li>`).join("")}</ul>
    <div class="small muted">Each column is a separate request sent with that user's identity. Highlighted numbers differ from the first column.</div></div>`;
}

function renderRuns() {
  const set = state.runs;
  const el = $("#results");
  if (!set) {
    el.innerHTML = '<div class="empty">Ask a question to see the answer, the permissions applied to it and the memory behind it.</div>';
    return;
  }
  const [first, ...rest] = set.runs;
  let summary = "";
  const cards = [];
  if (set.mode === "ask") {
    cards.push(runCard(first));
  } else {
    summary = set.mode === "replay" ? replaySummary(first, rest[0]) : rolesSummary(set.runs);
    const baseLines = pipelineLines(first.result);
    let baseMarked = new Set(), queryDiffers = false;
    const others = rest.map((run) => {
      if (!first.result || !run.result) return runCard(run);
      const [onlyBase, onlyRun] = lineDiff(baseLines, pipelineLines(run.result));
      if (set.mode === "replay") { baseMarked = onlyBase; queryDiffers = onlyBase.size + onlyRun.size > 0; }
      return runCard(run, { changed: diffRows(first.result, run.result), marked: onlyRun, showPipeline: queryDiffers });
    });
    cards.push(runCard(first, { marked: baseMarked, showPipeline: queryDiffers }), ...others);
  }
  el.innerHTML = `${summary}<div class="compare" style="--cols:${cards.length}">${cards.join("")}</div>`;
}

setInterval(() => $$(".elapsed").forEach((e) => { e.textContent = `${Math.round((Date.now() - Number(e.dataset.start)) / 1000)}s`; }), 1000);

// ---------- analyst: running questions ----------
async function runQuestion(mode) {
  const question = $("#question").value.trim();
  if (!question) { $("#question").focus(); return; }
  const token = ++state.runToken;
  const me = state.me;
  // The replay and the role comparison send independent requests in parallel, each in its own
  // session, so turn IDs never collide. Only a plain ask continues the current session.
  const specs = {
    ask: [{ title: `${shortName(me)}'s answer`, user: me, useMemory: $("#use-memory").checked, session: state.sessionId, keepSession: true }],
    replay: [
      { title: "Without memory", user: me, useMemory: false, session: null },
      { title: "With shared memory", user: me, useMemory: true, session: null },
    ],
    roles: state.users.map((u) => ({ title: u.display_name, user: u, useMemory: $("#use-memory").checked, session: null })),
  }[mode];
  const runs = specs.map((s) => ({ ...s, started: Date.now() }));
  state.runs = { mode, question, runs };
  renderRuns();
  const buttons = $$("#ask-btn, #replay-btn, #roles-btn");
  buttons.forEach((b) => (b.disabled = true));
  await Promise.all(runs.map(async (run) => {
    try {
      run.result = await api("/api/ask", {
        method: "POST", as: run.user.user_id,
        body: { question, session_id: run.session, use_memory: run.useMemory },
      });
    } catch (e) { run.error = e.message; }
    if (token !== state.runToken) return;
    if (run.keepSession && run.result) { state.sessionId = run.result.session_id; $("#session-id").textContent = state.sessionId; }
    renderRuns();
  }));
  if (token === state.runToken) buttons.forEach((b) => (b.disabled = false));
  if (state.runs?.runs.some((x) => x.result?.proposed_memory_pending)) refreshPending();
}

$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); runQuestion("ask"); });
$("#replay-btn").addEventListener("click", () => runQuestion("replay"));
$("#roles-btn").addEventListener("click", () => runQuestion("roles"));
$("#new-session").addEventListener("click", (e) => { e.preventDefault(); resetSession(); });
// ---------- analyst: question templates ----------
function renderTemplates() {
  const known = (id) => state.users.some((u) => u.user_id === id);
  $("#template-groups").innerHTML = TEMPLATES.map((g) => `<div class="template-group">
    <span class="template-label" title="${esc(g.hint)}">${esc(g.group)}</span>
    <div class="template-items">${g.items.map((t) => `<button type="button" class="template" data-q="${esc(t.q)}"${
      t.as && known(t.as) ? ` data-as="${esc(t.as)}" title="Signs in as ${esc(userName(t.as))} and fills the question"><span class="who">${esc(userName(t.as))}</span>`
        : ' title="Fills the question for the signed-in user">'}${esc(t.q)}</button>`).join("")}</div>
  </div>`).join("");
}
$("#template-groups").addEventListener("click", (e) => {
  const b = e.target.closest(".template");
  if (!b) return;
  if (b.dataset.as && b.dataset.as !== state.me.user_id) {
    setUser(b.dataset.as);
    toast(`Now signed in as ${state.me.display_name}`);
  }
  $("#question").value = b.dataset.q;
  $("#question").focus();
});
// Remember whether the presenter folded the templates away
try { if (localStorage.getItem("lore.templates") === "closed") $("#templates").open = false; } catch { /* storage unavailable */ }
$("#templates").addEventListener("toggle", (e) => {
  try { localStorage.setItem("lore.templates", e.target.open ? "open" : "closed"); } catch { /* storage unavailable */ }
});
$("#results").addEventListener("click", (e) => { const b = e.target.closest("[data-goto]"); if (b) showTab(b.dataset.goto); });

function resetSession() { state.sessionId = null; $("#session-id").textContent = "new"; }

// ---------- reviewer: memories ----------
const MEMORY_STATUSES = ["pending", "active", "superseded", "expired", "rejected", "forgotten"];

function pills(el, options, current, counts) {
  el.innerHTML = options.map(([value, label]) =>
    `<button type="button" class="pill${value === current ? " active" : ""}" data-value="${esc(value)}">${esc(label)}${
      counts ? `<span class="n">${counts[value] ?? 0}</span>` : ""}</button>`).join("");
}

function memoryItem(m) {
  const src = m.source || {};
  const sample = m.synthetic || src.proposed_by === "seed";
  const meta = [`Proposed by ${esc(userName(src.proposed_by))}${src.turn_id ? ` in turn <code>${esc(src.turn_id)}</code>` : ""}`];
  if (src.corrects_memory) meta.push(`Corrects <code>${esc(src.corrects_memory)}</code>`);
  if (m.approved_by) meta.push(`Approved by ${esc(userName(m.approved_by))}${m.approved_at ? `, ${esc(fmtTime(m.approved_at))}` : ""}`);
  if (m.superseded_by) meta.push(`Superseded by <code>${esc(m.superseded_by)}</code>`);
  if (m.expires_at) meta.push(`${m.status === "expired" ? "Expired" : "Expires"} ${esc(fmtDate(m.expires_at))}`);
  else if (m.status === "active") meta.push("No expiry");
  const reasons = [];
  if (m.rejected) reasons.push(`Rejected by ${esc(userName(m.rejected.by))}: ${esc(m.rejected.reason || "no reason given")}`);
  if (m.forgotten) reasons.push(`Forgotten by ${esc(userName(m.forgotten.by))}, ${esc(fmtTime(m.forgotten.at))}: ${esc(m.forgotten.reason)}`);
  const actions = [];
  if (state.me.can_review) {
    if (m.status === "pending") actions.push(["approve", "Approve", ""], ["reject", "Reject", "secondary"]);
    if (m.status === "active") actions.push(["expire", "Expire", "secondary"]);
    if (m.status !== "forgotten") actions.push(["forget", "Forget", "danger"]);
  }
  const retrievable = m.status === "active";
  return `<div class="item${retrievable ? "" : " dim"}">
    <div class="item-head">
      <span class="status status-${esc(m.status)}">${esc(m.status)}</span>
      <span class="item-title">${esc(m.title)}</span><span class="chip">v${esc(m.version)}</span>
      <span class="muted small">${esc(m.type)}</span>
      ${sample ? '<span class="muted small">· sample data</span>' : ""}
      <span class="muted small">· visible to</span> ${roleTags(m.visibility)}
    </div>
    <div class="item-body">${esc(m.content)}${reasons.map((x) => `<div class="reason error">${x}</div>`).join("")}</div>
    <div class="item-meta"><code>${esc(m.memory_id)}</code>${meta.map((x) => `<span>${x}</span>`).join("")}</div>
    <div class="item-actions">${actions.map(([act, label, cls]) =>
      `<button type="button" class="small ${cls}" data-act="${act}" data-id="${esc(m.memory_id)}">${label}</button>`).join("")}</div>
  </div>`;
}

function renderMemories() {
  const counts = { "": state.memories.length };
  for (const m of state.memories) counts[m.status] = (counts[m.status] || 0) + 1;
  pills($("#mem-filters"), [["", "All"], ...MEMORY_STATUSES.map((s) => [s, s[0].toUpperCase() + s.slice(1)])], state.memFilter, counts);
  const shown = state.memories.filter((m) => !state.memFilter || m.status === state.memFilter);
  $("#mem-note").textContent = state.me.can_review
    ? "You are the reviewer. Only active memories reach the agent; every decision here is written to the audit log, and nothing is deleted."
    : `You see the memories visible to your role (${roleLabel(state.me.role)}). Only a reviewer can approve, expire or forget them.`;
  $("#mem-list").innerHTML = shown.length ? shown.map(memoryItem).join("") : '<div class="empty">No memories with this status.</div>';
  const pending = counts.pending || 0;
  $("#pending-badge").textContent = pending;
  $("#pending-badge").classList.toggle("hidden", !pending || !state.me.can_review);
}

async function loadMemories() { state.memories = await api("/api/memories"); renderMemories(); }
const refreshPending = () => loadMemories().catch(() => {});

const quote = (m) => `<div class="quote"><strong>${esc(m.title)} v${esc(m.version)}</strong><br>${esc(m.content)}</div>`;
const reasonField = (label, required) =>
  `<label class="field">${label}<textarea name="reason"${required ? " required" : ""}></textarea></label>`;

const MEMORY_DIALOGS = {
  approve(m) {
    const roles = [...new Set(state.users.map((u) => u.role))];
    const active = state.memories.find((x) => x.title === m.title && x.status === "active" && x.memory_id !== m.memory_id);
    return {
      title: "Approve this memory", confirm: "Approve",
      body: `${quote(m)}
        <fieldset><legend>Visible to</legend>${roles.map((r) => `<label class="check"><input type="checkbox" name="visibility"
          value="${esc(r)}"${m.visibility?.includes(r) ? " checked" : ""}> ${esc(roleLabel(r))}</label>`).join("")}</fieldset>
        <label class="field">Expires on (optional)<input type="date" name="expires"></label>
        <div class="small muted">Once approved it is embedded and the agent can retrieve it for these roles.
          ${active ? `It supersedes the active v${esc(active.version)}.` : ""}</div>`,
      send(form) {
        const visibility = form.getAll("visibility");
        if (!visibility.length) throw new Error("Choose at least one role that can see this memory.");
        const expires = form.get("expires");
        return { visibility, expires_at: expires ? `${expires}T23:59:59Z` : null };
      },
      done: "approved",
    };
  },
  reject: (m) => ({
    title: "Reject this proposal", confirm: "Reject", danger: true, done: "rejected",
    body: `${quote(m)}${reasonField("Reason (shown to the team)", false)}`,
    send: (form) => ({ reason: form.get("reason").trim() }),
  }),
  expire: (m) => ({
    title: "Expire this memory now", confirm: "Expire", danger: true, done: "expired",
    body: `${quote(m)}${reasonField("Reason (optional)", false)}
      <div class="small muted">The agent stops retrieving it from the next question on. It stays listed here as expired.</div>`,
    send: (form) => ({ reason: form.get("reason").trim() }),
  }),
  forget: (m) => ({
    title: "Forget this memory", confirm: "Forget", danger: true, done: "forgotten",
    body: `${quote(m)}${reasonField("Reason (required)", true)}
      <div class="small muted">Its embedding is removed so it can never be retrieved again. The text and your reason stay for the audit record.</div>`,
    send: (form) => ({ reason: form.get("reason").trim() }),
  }),
};

$("#mem-list").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const m = state.memories.find((x) => x.memory_id === b.dataset.id);
  const spec = MEMORY_DIALOGS[b.dataset.act](m);
  openDialog({
    ...spec,
    async onSubmit(form) {
      await api(`/api/memories/${encodeURIComponent(m.memory_id)}/${b.dataset.act}`, { method: "POST", body: spec.send(form) });
      toast(`${m.title} v${m.version} ${spec.done}. Recorded in the audit log.`);
      await loadMemories();
    },
  });
});
$("#mem-filters").addEventListener("click", (e) => {
  const b = e.target.closest(".pill");
  if (b) { state.memFilter = b.dataset.value; renderMemories(); }
});
$("#mem-refresh").addEventListener("click", (e) => busy([e.target], loadMemories));

// ---------- reviewer: monthly query and memory review ----------
// Reviewer-only routes under /api/memory-review (memory governance workstream).
async function loadMonthlyReview() {
  $("#monthly").classList.toggle("hidden", !state.me.can_review);
  if (!state.me.can_review) return;
  const runs = await api("/api/memory-review/runs");
  const complete = runs.filter((r) => r.status === "complete");
  const select = $("#monthly-batch");
  const previous = select.value;
  select.innerHTML = complete.length
    ? complete.map((r) => `<option value="${esc(r.batch_id)}">${esc(r.batch_id)}</option>`).join("")
    : '<option value="">No completed scan yet</option>';
  if (complete.some((r) => r.batch_id === previous)) select.value = previous;
  const failed = runs.find((r) => r.status === "failed");
  $("#monthly-note").textContent = failed ? `The scan for ${failed.batch_id} failed: ${failed.error || "unknown error"}` : "";
  $("#monthly-note").classList.toggle("hidden", !failed);

  const batch = select.value;
  if (!batch) {
    $("#query-review-list").innerHTML = '<div class="empty">Run a scan to build the review queue.</div>';
    $("#memory-review-list").innerHTML = "";
    return;
  }
  const items = (type) => api(`/api/memory-review/items?batch_id=${encodeURIComponent(batch)}&item_type=${type}&status=pending`);
  const [queries, memories] = await Promise.all([items("query"), items("memory")]);
  const actions = (item, keep, remove) => `<div class="item-actions">
    <button type="button" class="small secondary" data-review-item="${esc(item.item_id)}" data-review-action="retain">${keep}</button>
    <button type="button" class="small danger" data-review-item="${esc(item.item_id)}" data-review-action="delete"
      data-review-type="${esc(item.item_type)}" data-review-label="${esc(item.question || item.title)}">${remove}</button></div>`;
  $("#query-review-list").innerHTML = queries.length ? queries.map((q) => `<div class="item">
    <div class="item-head"><span class="status status-${esc(q.outcome)}">${esc(q.outcome)}</span>
      <span class="item-title">${esc(q.question)}</span></div>
    <div class="item-meta"><span>Asked by ${esc(userName(q.user_id))} (${esc(roleLabel(q.role))})</span>
      <code>${esc(q.turn_id)}</code></div>
    ${actions(q, "Keep", "Delete query")}</div>`).join("") : '<div class="empty">No queries are waiting for a decision.</div>';
  $("#memory-review-list").innerHTML = memories.length ? memories.map((m) => `<div class="item">
    <div class="item-head"><span class="item-title">${esc(m.title)}</span><span class="chip">v${esc(m.version)}</span></div>
    <div class="item-body">${esc(m.content)}<div class="reason muted">${esc(m.review_reason)}</div></div>
    <div class="item-meta"><code>${esc(m.memory_id)}</code></div>
    ${actions(m, "Keep memory", "Forget memory")}</div>`).join("") : '<div class="empty">Every active memory was used in this month.</div>';
}

$("#monthly-run").addEventListener("click", (e) => busy([e.target], async () => {
  const run = await api("/api/memory-review/run", { method: "POST" });
  toast(`Monthly review ${run.batch_id}: ${plural(run.query_items ?? 0, "query")}, ${plural(run.memory_items ?? 0, "unused memory")}, ${
    plural((run.proposed_memory_ids || []).length, "memory proposal")}.`);
  await Promise.all([loadMonthlyReview(), loadMemories()]);
}));
$("#monthly-refresh").addEventListener("click", (e) => busy([e.target], loadMonthlyReview));
$("#monthly-batch").addEventListener("change", () => loadMonthlyReview().catch((e) => toast(e.message, true)));
$("#monthly").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-review-item]");
  if (!b) return;
  const path = `/api/memory-review/items/${encodeURIComponent(b.dataset.reviewItem)}/${b.dataset.reviewAction}`;
  const reload = () => Promise.all([loadMonthlyReview(), loadMemories()]);
  if (b.dataset.reviewAction === "retain") {
    busy([b], async () => { await api(path, { method: "POST" }); toast("Kept. Recorded in the audit log."); await reload(); });
    return;
  }
  const isQuery = b.dataset.reviewType === "query";
  openDialog({
    title: isQuery ? "Delete this query" : "Forget this memory", confirm: isQuery ? "Delete query" : "Forget memory", danger: true,
    body: `<div class="quote">${esc(b.dataset.reviewLabel)}</div>${reasonField("Reason (required)", true)}
      <div class="small muted">${isQuery
        ? "The saved question and the episodes built from it are deleted, and a skill built on them is retired. The audit log keeps a record without the question text."
        : "Its embedding is removed so it can never be retrieved again. The text and your reason stay for the audit record."}</div>`,
    async onSubmit(form) {
      await api(path, { method: "POST", body: { reason: form.get("reason").trim() } });
      toast(`${isQuery ? "Query deleted" : "Memory forgotten"}. Recorded in the audit log.`);
      await reload();
    },
  });
});

// ---------- skills ----------
function prettyJson(text) {
  try { return JSON.stringify(typeof text === "string" ? JSON.parse(text) : text, null, 2); } catch { return String(text); }
}

function clusterItem(c) {
  const draft = c.ready && state.me.can_review
    ? `<button type="button" class="small" data-draft="${esc(c.cluster_id)}">Draft skill</button>` : "";
  return `<div class="item">
    <div class="item-head"><span class="status status-${c.ready ? "ready" : "waiting"}">${c.ready ? "Ready" : "Not yet"}</span>
      <span class="item-title">${esc(c.intent)}</span></div>
    <div class="item-meta"><code>${esc(c.cluster_id)}</code><span>${plural(c.episodes, "episode")}</span>
      <span>from ${c.users.map((u) => esc(userName(u))).join(", ")}</span></div>
    <div class="item-actions">${draft}</div>
  </div>`;
}

function skillItem(s) {
  const tests = Object.entries(s.test_results || {});
  const passed = tests.length > 0 && tests.every(([, v]) => v === "pass");
  const actions = [];
  if (state.me.can_review) {
    if (["draft", "stale"].includes(s.status)) {
      actions.push(`<button type="button" class="small" data-skill="${esc(s.name)}" data-act="publish"${passed ? "" : ' disabled title="Tests must pass first"'}>Publish</button>`);
    }
    if (["draft", "stale", "published"].includes(s.status)) {
      actions.push(`<button type="button" class="small danger" data-skill="${esc(s.name)}" data-act="retire">Retire</button>`);
    }
  }
  const params = Object.entries(s.parameters || {});
  const versions = Object.entries(s.metric_versions || {}).map(([k, v]) => `${k}@${v}`);
  const availability = s.status !== "published" ? "" : s.offered_to_you
    ? '<span class="tag tag-ok">Available to you</span>' : '<span class="tag tag-warn">Needs a field hidden from you</span>';
  return `<div class="item${["retired"].includes(s.status) ? " dim" : ""}">
    <div class="item-head"><span class="status status-${esc(s.status)}">${esc(s.status)}</span>
      <span class="item-title">${esc(s.name)}</span><span class="chip">v${esc(s.version)}</span>
      ${tests.map(([k, v]) => `<span class="status status-${esc(v)}">${esc(k)} test: ${esc(v)}</span>`).join("")}
      ${availability}</div>
    <div class="item-body">${esc(s.description)}
      ${s.status === "stale" && s.stale_reason ? `<div class="reason error">Needs review: ${esc(s.stale_reason)}</div>` : ""}
      ${s.status === "retired" && s.retired_reason ? `<div class="reason muted">Retired: ${esc(s.retired_reason)}</div>` : ""}
      <details><summary>Parameters, fields and query template</summary>
        ${params.length ? `<div class="kv"><span>Parameters</span><span>${params.map(([k, v]) => `<code>${esc(k)}</code> ${esc(v)}`).join("<br>")}</span></div>` : ""}
        <div class="kv"><span>Reads fields</span><span>${tags(s.required_fields || []) || "–"}</span></div>
        ${versions.length ? `<div class="kv"><span>Built on</span><span>${tags(versions)}</span></div>` : ""}
        <div class="kv"><span>Episodes</span><span>${tags(s.source_episodes || []) || "–"}</span></div>
        <pre>${esc(prettyJson(s.pipeline_template))}</pre>
      </details></div>
    <div class="item-meta">${s.reviewed_by ? `<span>Published by ${esc(userName(s.reviewed_by))}${s.published_at ? `, ${esc(fmtTime(s.published_at))}` : ""}</span>` : "<span>Not reviewed yet</span>"}
      ${s.cluster_id ? `<span>From cluster <code>${esc(s.cluster_id)}</code></span>` : ""}</div>
    <div class="item-actions">${actions.join("")}</div>
  </div>`;
}

async function loadSkills() {
  const [clusters, { skills }] = await Promise.all([api("/api/skills/clusters"), api("/api/skills")]);
  $("#cluster-list").innerHTML = clusters.length ? clusters.map(clusterItem).join("")
    : '<div class="empty">No episodes yet. They appear after questions are answered and the learning worker has processed them.</div>';
  $("#skill-list").innerHTML = skills.length ? skills.map(skillItem).join("")
    : '<div class="empty">No skills yet. Draft one from a ready cluster.</div>';
}

$("#cluster-list").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-draft]");
  if (!b) return;
  busy([b], async () => {
    b.textContent = "Drafting and testing…";
    const s = await api("/api/skills/generate", { method: "POST", body: { cluster_id: b.dataset.draft } });
    toast(`Drafted ${s.name} v${s.version}. Tests: ${Object.entries(s.test_results || {}).map(([k, v]) => `${k} ${v}`).join(", ")}.`);
    await loadSkills();
  }).finally(() => { if (b.isConnected) b.textContent = "Draft skill"; });
});
$("#skill-list").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-skill]");
  if (!b) return;
  const name = b.dataset.skill;
  if (b.dataset.act === "publish") {
    busy([b], async () => {
      await api(`/api/skills/${encodeURIComponent(name)}/publish`, { method: "POST" });
      toast(`${name} published. Recorded in the audit log.`);
      await loadSkills();
    });
  } else {
    openDialog({
      title: `Retire ${name}`, confirm: "Retire", danger: true,
      body: `${reasonField("Reason", false)}<div class="small muted">The agent stops being offered this skill.</div>`,
      async onSubmit(form) {
        await api(`/api/skills/${encodeURIComponent(name)}/retire`, { method: "POST", body: { reason: form.get("reason").trim() } });
        toast(`${name} retired. Recorded in the audit log.`);
        await loadSkills();
      },
    });
  }
});
$("#skills-refresh").addEventListener("click", (e) => busy([e.target], loadSkills));

// ---------- audit ----------
const AUDIT_FILTERS = [["", "All"], ["query", "Queries"], ["memory", "Memory"], ["skill", "Skills"], ["review", "Review"]];
const ACTION_LABELS = {
  query: "Query", memory_propose: "Memory proposed", memory_approve: "Memory approved", memory_reject: "Memory rejected",
  memory_expire: "Memory expired", memory_forget: "Memory forgotten", skill_publish: "Skill published", skill_retire: "Skill retired",
  query_delete: "Query deleted", review_retain: "Kept after review",
};

function auditSummary(ev) {
  const d = ev.details || {};
  if (ev.action === "query") {
    const limits = [
      ...Object.entries(d.filters || {}).map(([k, v]) => `rows where ${k} = ${v}`),
      ...((d.removed_fields || []).length ? [`hidden: ${d.removed_fields.join(", ")}`] : []),
    ];
    return `${d.query_deleted ? '<span class="muted">Question deleted after review</span>' : `“${esc(d.question)}”`}<div class="small muted">${d.rejected ? `<span class="error">Blocked: ${esc(d.rejected)}</span>` : `Status ${esc(d.status)}`}
      ${limits.length ? ` · ${esc(limits.join(" · "))}` : " · all rows and fields"}${d.turn_id ? ` · turn <code>${esc(d.turn_id)}</code>` : ""}</div>`;
  }
  const parts = [];
  if (d.title) parts.push(`${esc(d.title)}${d.version ? ` v${esc(d.version)}` : ""}`);
  else if (d.version) parts.push(`v${esc(d.version)}`);
  if (d.reason) parts.push(`Reason: ${esc(d.reason)}`);
  if (d.previous_status) parts.push(`was ${esc(d.previous_status)}`);
  if (d.visibility) parts.push(`visible to ${esc(d.visibility.map(roleLabel).join(", "))}`);
  if (d.superseded?.length) parts.push(`supersedes ${esc(d.superseded.join(", "))}`);
  if (d.corrects_memory) parts.push(`corrects ${esc(d.corrects_memory)}`);
  if (d.batch_id) parts.push(`monthly review ${esc(d.batch_id)}`);
  if (d.episodes_deleted) parts.push(`${plural(d.episodes_deleted, "episode")} deleted`);
  return parts.join(" · ");
}

function renderAudit() {
  pills($("#audit-filters"), AUDIT_FILTERS, state.auditFilter);
  const group = (ev) => (ev.action === "query_delete" ? "review" : ev.action.split("_")[0]);
  const shown = state.audit.filter((ev) => !state.auditFilter || group(ev) === state.auditFilter);
  $("#audit-note").textContent = state.me.can_review
    ? "Every query and every change to memory or skills, newest first."
    : "You see your own activity. Reviewers see everyone's.";
  if (!shown.length) { $("#audit-list").innerHTML = '<div class="empty">No events.</div>'; return; }
  $("#audit-list").innerHTML = `<table class="audit-table"><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
    <tbody>${shown.map((ev) => {
      const kind = ev.action === "query" ? (ev.details?.rejected ? "blocked" : "query")
        : ev.action === "query_delete" ? "review" : ev.action.split("_")[0];
      return `<tr><td class="when">${esc(fmtTime(ev.ts))}</td>
        <td>${esc(userName(ev.actor))} <span class="muted small">${esc(roleLabel(ev.role))}</span></td>
        <td><span class="act act-${kind}">${esc(kind === "blocked" ? "Query blocked" : ACTION_LABELS[ev.action] || ev.action)}</span></td>
        <td><code>${esc(ev.target?.id)}</code></td><td>${auditSummary(ev)}</td></tr>`;
    }).join("")}</tbody></table>`;
}

async function loadAudit() { state.audit = await api("/api/audit?limit=200"); renderAudit(); }
$("#audit-filters").addEventListener("click", (e) => {
  const b = e.target.closest(".pill");
  if (b) { state.auditFilter = b.dataset.value; renderAudit(); }
});
$("#audit-refresh").addEventListener("click", (e) => busy([e.target], loadAudit));

// ---------- tabs and identity ----------
const LOADERS = { reviewer: () => Promise.all([loadMemories(), loadMonthlyReview()]), skills: loadSkills, audit: loadAudit };

function syncUrl() { history.replaceState(null, "", `?user=${encodeURIComponent(state.me.user_id)}#${state.tab}`); }

function showTab(name) {
  if (!$(`#${CSS.escape(name)}.panel`)) name = "analyst";
  state.tab = name;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("hidden", p.id !== name));
  syncUrl();
  LOADERS[name]?.().catch((e) => toast(e.message, true));
}

function renderIdentity() {
  const u = state.me;
  const rows = Object.entries(u.rows || {});
  $("#identity").innerHTML = [
    `<span class="tag">${esc(roleLabel(u.role))}</span>`,
    `<span class="tag${rows.length ? " tag-warn" : ""}">Rows: ${rows.length ? esc(rows.map(([k, v]) => `${k} = ${v}`).join(", ")) : "all"}</span>`,
    `<span class="tag${u.hidden_fields?.length ? " tag-warn" : ""}">Hidden fields: ${u.hidden_fields?.length ? esc(u.hidden_fields.join(", ")) : "none"}</span>`,
    u.can_review ? '<span class="tag tag-accent">Reviewer</span>' : "",
  ].join("");
}

// Switching user starts clean: a new session, no results from the previous user, fresh lists.
function setUser(id) {
  state.me = state.users.find((u) => u.user_id === id) || state.users[0];
  $("#user").value = state.me.user_id;
  state.runToken++;
  state.runs = null;
  $$("#ask-btn, #replay-btn, #roles-btn").forEach((b) => (b.disabled = false));
  resetSession();
  renderIdentity();
  renderRuns();
  showTab(state.tab);
  if (state.tab !== "reviewer") refreshPending();
}

async function init() {
  state.users = await fetch("/api/users").then((r) => r.json());
  $("#user").innerHTML = state.users.map((u) => `<option value="${esc(u.user_id)}">${esc(u.display_name)}</option>`).join("");
  $("#user").addEventListener("change", (e) => setUser(e.target.value));
  renderTemplates();
  $$(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  window.addEventListener("hashchange", () => { if (location.hash.slice(1) !== state.tab) showTab(location.hash.slice(1)); });
  state.tab = location.hash.slice(1) || "analyst";
  setUser(new URLSearchParams(location.search).get("user"));
}
init();
