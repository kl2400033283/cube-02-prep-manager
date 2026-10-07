/* Prep Manager console v3 (vanilla JS, no build step). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pct = (x) => (x == null ? "n/a" : `${(x * 100).toFixed(x >= 0.995 || x === 0 ? 0 : 1)}%`);

const state = { key: "alpha-demo-key", scenarios: [], scenario: null, uploads: [], record: null, records: [] };

const LABEL = { PASS: "Pass", FAIL: "Fail", UNCERTAIN: "Needs review", NOT_REQUIRED: "Not required", PENDING_REVIEW: "Pending review" };
const HEADLINE = {
  PASS: "Ready to ship",
  FAIL: "Fix before shipping",
  UNCERTAIN: "Needs a human look",
  PENDING_REVIEW: "Sent to review (system fault)",
};
const ICON = {
  PASS: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  FAIL: '<svg viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17"/></svg>',
  UNCERTAIN: '<svg viewBox="0 0 24 24"><path d="M9.5 9a2.6 2.6 0 1 1 3.6 2.4c-.7.3-1.1.9-1.1 1.6v.6M12 17.2v.1"/></svg>',
  NOT_REQUIRED: '<svg viewBox="0 0 24 24"><path d="M7 12h10"/></svg>',
};
ICON.PENDING_REVIEW = ICON.UNCERTAIN;
const ENGINE = { station_cv: "Station camera engine", local_ocr: "Offline text engine", free_vision: "Free AI vision ($0)", claude_vision: "Claude vision", quality_gate: "Quality gate", fail_open: "Fail-open", none: "—" };
const STEPS = [
  ["RESOLVE_REQUIREMENTS", "Working out which rules apply"],
  ["INGEST_IMAGES", "Fingerprinting the photos"],
  ["QUALITY_GATE", "Checking photo quality"],
  ["ROUTE", "Choosing how to look"],
  ["PERCEIVE", "Looking at the unit"],
  ["VERIFY_AND_JUDGE", "Applying the rules"],
  ["DECIDE", "Deciding"],
  ["SEAL_EVIDENCE", "Sealing the evidence"],
];

/* ------------------------------------------------------------------ helpers */
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast show${err ? " err" : ""}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = "toast"), 3600);
}

async function api(path, opts = {}) {
  const headers = { "X-API-Key": state.key, ...(opts.headers || {}) };
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  const res = await fetch(path, { ...opts, headers });
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const d = data && data.detail;
    const err = new Error(Array.isArray(d) ? d.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join("; ") : d || res.statusText);
    err.status = res.status;
    throw err;
  }
  return data;
}
const store = (k, v) => { try { localStorage.setItem(k, v); } catch { /* unavailable */ } };
const load = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
function download(name, content, type = "application/json") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  Object.assign(document.createElement("a"), { href: url, download: name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const ago = (iso) => {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
};

/* ------------------------------------------------------------------ boot */
document.addEventListener("DOMContentLoaded", init);

async function init() {
  const theme = load("pm-theme");
  if (theme) document.documentElement.dataset.theme = theme;
  $("#themeBtn").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store("pm-theme", next);
  };
  $$("[data-tab]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); showTab(b.dataset.tab); }));
  $("#tenant").onchange = (e) => {
    state.key = e.target.value;
    toast(`Switched to ${e.target.selectedOptions[0].text}`);
    refreshStats();
    if ($("#view-records").classList.contains("active")) loadRecords();
    if ($("#view-insights").classList.contains("active")) loadInsights();
  };
  $("#unitForm").onsubmit = (e) => { e.preventDefault(); runInspection(); };
  $("#fileInput").onchange = (e) => handleFiles(e.target.files);
  $("#cameraInput").onchange = (e) => handleFiles(e.target.files);
  $("#viewer").addEventListener("dragover", (e) => e.preventDefault());
  $("#viewer").addEventListener("drop", (e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); });
  $("#decisionFilter").onchange = loadRecords;
  $("#recordSearch").oninput = renderRecords;
  $("#exportCsv").onclick = exportCsv;
  $("#auditBtn").onclick = runAudit;
  $$("[data-drill]").forEach((b) => (b.onclick = () => { showTab("inspect"); runDrill(b.dataset.drill); }));
  setupOverride();

  try {
    const [cats, scn, rules, card] = await Promise.all(
      ["/api/v1/categories", "/api/v1/scenarios", "/api/v1/rules", "/api/v1/agent"].map((u) => fetch(u).then((r) => r.json())));
    $("#categorySel").innerHTML = cats.categories.map((c) => `<option value="${esc(c.key)}">${esc(c.label)}</option>`).join("");
    $("#marksBox").insertAdjacentHTML("beforeend", Object.entries(cats.handling_marks).map(([k, v]) =>
      `<label class="chip"><input type="checkbox" name="mark" value="${esc(k)}"><span>${esc(v)}</span></label>`).join(""));
    state.scenarios = scn.scenarios;
    renderSamples();
    renderRules(rules);
    renderAbout(card);
    selectScenario(state.scenarios[0]);
  } catch (e) {
    toast(`Could not load the console: ${e.message}`, true);
  }
  refreshStats();
}

function showTab(tab) {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${tab}`));
  if (tab === "records") loadRecords();
  if (tab === "insights") loadInsights();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function refreshStats() {
  try {
    const m = await api("/api/v1/metrics");
    $("#statStrip").innerHTML = [
      [m.total_units, "Units inspected"],
      [pct(m.pass_rate), "Ready to ship"],
      [`${(m.latency_ms.p50 / 1000).toFixed(1)}s`, "Typical time"],
    ].map(([v, k]) => `<div class="stat"><b>${esc(v)}</b><span>${esc(k)}</span></div>`).join("");
  } catch { /* decorative */ }
}

/* ------------------------------------------------------------------ step 1: photo */
function renderSamples() {
  $("#samples").innerHTML = state.scenarios.map((s) => `
    <button type="button" class="sample" data-id="${esc(s.scenario_id)}" title="${esc(s.story)}">
      <img src="${esc(s.image_url)}" alt="" loading="lazy">
      <div><b>${esc(s.challenge_case)}</b><small class="${esc(s.expected)}">Expected: ${esc(LABEL[s.expected])}</small></div>
    </button>`).join("");
  $$(".sample").forEach((b) => (b.onclick = () => selectScenario(state.scenarios.find((s) => s.scenario_id === b.dataset.id))));
}


function selectScenario(s) {
  if (!s) return;
  state.scenario = s;
  state.uploads = [];
  $("#uploadThumbs").innerHTML = "";
  $$(".sample").forEach((b) => b.classList.toggle("active", b.dataset.id === s.scenario_id));
  fillForm(s.unit);
  showImage(s.image_url);
  resetResult();
}

function fillForm(u) {
  const f = $("#unitForm").elements;
  for (const n of ["unit_id", "fnsku", "category", "bag_length_in", "bag_width_in", "bag_opening_in", "polybag_spec_mil"]) f[n].value = u[n] ?? "";
  for (const n of ["wo_polybag", "wo_suffocation_warning", "wo_expiry_date"]) f[n].checked = !!u[n];
  $$('input[name="mark"]').forEach((c) => (c.checked = (u.wo_handling_marks || []).includes(c.value)));
  $(".more-fields").open = !!(u.bag_length_in || u.bag_opening_in);
}

function showImage(src) {
  $("#viewerEmpty").hidden = true;
  $("#viewerStage").hidden = false;
  $("#stageImg").src = src;
  $("#overlay").innerHTML = "";
  $("#overlayLabels").innerHTML = "";
}

/* Phone photos: apply EXIF rotation and shrink big captures before sending them over cellular.
   Keeps up to 2560 px on the long edge (enough for the native-resolution blur check). */
const UPLOAD_MAX_EDGE = 2560;
async function shrinkForUpload(file) {
  if (!("createImageBitmap" in window)) return file;
  let bmp;
  try { bmp = await createImageBitmap(file, { imageOrientation: "from-image" }); } catch { return file; }
  const scale = Math.min(1, UPLOAD_MAX_EDGE / Math.max(bmp.width, bmp.height));
  if (scale === 1 && file.size < 3 * 1024 * 1024) { bmp.close?.(); return file; }
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale);
  c.height = Math.round(bmp.height * scale);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close?.();
  return await new Promise((res) => c.toBlob((b) => res(b || file), "image/jpeg", 0.9));
}

async function withRetry(fn, tries = 3) {
  for (let i = 0; ; i++) {
    try { return await fn(); }
    catch (e) {
      const transient = !e.status || e.status >= 500 || e.status === 429;
      if (i >= tries - 1 || !transient) throw e;
      await new Promise((r) => setTimeout(r, 800 * 2 ** i));
    }
  }
}

async function handleFiles(files) {
  const list = [...files].slice(0, 4);
  if (!list.length) return;
  state.scenario = null;
  state.uploads = [];
  $$(".sample").forEach((b) => b.classList.remove("active"));
  $("#uploadThumbs").innerHTML = "";
  for (const file of list) {
    try {
      const blob = await shrinkForUpload(file);
      const r = await withRetry(() => {
        const fd = new FormData();
        fd.append("file", blob, file.name.replace(/\.[^.]+$/, "") + (blob.type === "image/jpeg" ? ".jpg" : ""));
        return api("/api/v1/assets", { method: "POST", body: fd });
      });
      state.uploads.push(r);
      $("#uploadThumbs").insertAdjacentHTML("beforeend", `<img src="${esc(r.preview_url)}" alt="" title="${esc(file.name)}">`);
    } catch (e) { toast(`${file.name}: ${e.message}`, true); }
  }
  $("#fileInput").value = "";
  if ($("#cameraInput")) $("#cameraInput").value = "";
  if (state.uploads.length) {
    showImage(state.uploads[0].preview_url);
    $("#unitForm").elements.unit_id.value = `UNIT-${Date.now().toString().slice(-6)}`;
    resetResult();
    toast(`${state.uploads.length} photo(s) uploaded. Check step 2, then Inspect.`);
  }
}

/* ------------------------------------------------------------------ inspection */
function payload() {
  const f = $("#unitForm").elements;
  const num = (n) => (f[n].value === "" ? null : Number(f[n].value));
  const p = {
    unit_id: f.unit_id.value.trim(), fnsku: f.fnsku.value.trim() || "UNKNOWN", category: f.category.value,
    bag_length_in: num("bag_length_in"), bag_width_in: num("bag_width_in"), bag_opening_in: num("bag_opening_in"),
    polybag_spec_mil: num("polybag_spec_mil"),
    wo_polybag: f.wo_polybag.checked, wo_suffocation_warning: f.wo_suffocation_warning.checked, wo_expiry_date: f.wo_expiry_date.checked,
    wo_handling_marks: $$('input[name="mark"]:checked').map((c) => c.value),
  };
  if (state.scenario) {
    const u = state.scenario.unit;
    Object.assign(p, { scenario_id: state.scenario.scenario_id, sku: u.sku, asin: u.asin, work_order_id: u.work_order_id, fba_shipment_id: u.fba_shipment_id });
  } else {
    p.asset_ids = state.uploads.map((u) => u.asset_id);
  }
  return p;
}

function runInspection() {
  if (!state.scenario && !state.uploads.length) return toast("Pick a sample or upload a photo first.", true);
  return withProgress(() => api("/api/v1/inspections", { method: "POST", json: payload() }));
}

function runDrill(fault) {
  const scenario_id = state.scenario ? state.scenario.scenario_id : "correct-prep";
  return withProgress(async () => {
    const r = await api("/api/v1/drills/fail-open", { method: "POST", json: { scenario_id, fault } });
    toast(`Drill: simulated ${fault === "timeout" ? "model timeout" : "vision outage"} → sent to review in ${(r.wall_ms / 1000).toFixed(1)} s. The line never stopped.`);
    return r;
  });
}

async function withProgress(fn) {
  const btn = $("#runBtn");
  btn.disabled = true;
  btn.querySelector("span").textContent = "Inspecting…";
  $("#viewerStage").classList.add("scanning");
  $("#overlay").innerHTML = "";
  $("#overlayLabels").innerHTML = "";
  $("#resultEmpty").hidden = true;
  $("#result").hidden = true;
  $("#progress").hidden = false;
  $("#progressSteps").innerHTML = STEPS.map(([k, t]) => `<li data-step="${k}"><i></i>${esc(t)}<small></small></li>`).join("");
  // Gentle optimistic animation while the request runs; real timings are filled in afterwards.
  let i = 0;
  const items = $$("#progressSteps li");
  const tick = setInterval(() => {
    if (i < items.length - 1) { items[i]?.classList.replace("active", "done"); items[i]?.classList.add("done"); i += 1; }
    items[i]?.classList.add("active");
  }, 380);
  items[0].classList.add("active");
  try {
    const r = await fn();
    clearInterval(tick);
    const trace = Object.fromEntries((r.record.trace || []).map((s) => [s.step, s]));
    for (const li of items) {
      const s = trace[li.dataset.step];
      li.className = "done";
      if (s) li.querySelector("small").textContent = s.latency_ms ? `${s.latency_ms < 1000 ? Math.round(s.latency_ms) + " ms" : (s.latency_ms / 1000).toFixed(1) + " s"}` : s.status === "skipped" ? "skipped" : "";
      await sleep(45);
    }
    await sleep(250);
    renderRecord(r);
    refreshStats();
  } catch (e) {
    clearInterval(tick);
    toast(e.message, true);
    resetResult();
  } finally {
    $("#viewerStage").classList.remove("scanning");
    btn.disabled = false;
    btn.querySelector("span").textContent = "Inspect unit";
  }
}

function resetResult() {
  state.record = null;
  $("#progress").hidden = true;
  $("#result").hidden = true;
  $("#resultEmpty").hidden = false;
}

/* ------------------------------------------------------------------ step 3: result */
function renderRecord(resp) {
  const rec = resp.record;
  state.record = resp;
  const d = rec.outcome.decision;
  const required = rec.checks.filter((c) => c.verdict !== "NOT_REQUIRED");
  const passed = required.filter((c) => c.verdict === "PASS").length;
  const p = rec.perception || {};
  drawOverlay(rec);

  const ORDER = { FAIL: 0, UNCERTAIN: 1, PASS: 2, NOT_REQUIRED: 3 };
  const checks = [...rec.checks].sort((a, b) => ORDER[a.verdict] - ORDER[b.verdict]);

  const notices = [];
  if (p.provider === "local_ocr" && required.some((c) => c.verdict === "UNCERTAIN")) {
    notices.push(`<div class="notice info"><b>Phone-photo mode.</b> The offline text engine proves what it can <i>read</i> — warning wording, FNSKU, expiry date, sticker text — but it can't see whether a bag is sealed or a label is flat, so those are marked <b>Needs review</b>. If this frame is from the prep-station camera, choose <b>Station camera</b> in step 1 and inspect again.</div>`);
  }
  if ((p.routing_reason || "").includes("OUT OF DOMAIN")) {
    notices.push(`<div class="notice"><b>Real-world photo, no vision model available.</b> The station camera engine is only reliable on calibrated station frames, so its findings are shown as <b>Needs review</b> instead of guessed.</div>`);
  }
  if (rec.status === "failed_open") {
    notices.push(`<div class="notice"><b>The vision step didn't answer in time.</b> The unit was released to review with its photos kept, so the line never stopped.</div>`);
  }

  const panels = [];
  if (rec.outcome.action_items?.length && d !== "PASS") {
    panels.push(`<details class="panel" open><summary>What to do next<span class="count">${rec.outcome.action_items.length}</span></summary><ul>${rec.outcome.action_items.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>`);
  }
  if (rec.discrepancies?.length) {
    panels.push(`<details class="panel" open><summary>Work order missed something<span class="count">${rec.discrepancies.length}</span></summary><ul>${rec.discrepancies.map((x) => `<li>${esc(x.detail)}</li>`).join("")}</ul></details>`);
  }
  if (rec.attestations?.length) {
    panels.push(`<details class="panel"><summary>Can't be proven from a photo<span class="count">${rec.attestations.length}</span></summary><ul>${rec.attestations.map((a) => `<li><b>${esc(a.title)}</b> — ${esc(a.detail)}</li>`).join("")}</ul></details>`);
  }
  if (rec.overrides?.length) {
    panels.push(`<details class="panel" open><summary>Overrides<span class="count">${rec.overrides.length}</span></summary><ul>${rec.overrides.map((o) => `<li><b>${esc(titleOf(rec, o.check_key))}</b>: ${esc(LABEL[o.original_verdict])} → ${esc(LABEL[o.new_verdict])} by ${esc(o.role || "operator")} ${esc(o.operator_id)} — “${esc(o.reason)}”</li>`).join("")}</ul></details>`);
  }

  $("#result").innerHTML = `
    <div class="verdict ${esc(d)}">
      <div class="v-icon">${ICON[d]}</div>
      <div class="v-text">
        <small>${esc(LABEL[d])}</small>
        <h2>${esc(HEADLINE[d])}</h2>
        <p>${d === "PASS" ? `All ${required.length} required checks verified from the photo.` : esc(summaryLine(rec))}</p>
      </div>
    </div>
    <div class="v-meta">
      <div><b>${passed} / ${required.length}</b>checks passed</div>
      <div><b>${esc(ENGINE[p.provider] || p.provider || "—")}</b>looked at the photo</div>
      <div><b>${(rec.total_latency_ms / 1000).toFixed(1)} s</b>time taken</div>
      <div><b>$${(p.cost_usd || 0).toFixed(3)}</b>model cost</div>
    </div>
    ${notices.join("")}
    <div class="checks">${checks.map(checkRow).join("")}</div>
    ${panels.join("")}
    <div class="seal">
      <div class="seal-top">🔏 Evidence sealed <span class="${resp.integrity_verified ? "ok" : "bad"}">${resp.integrity_verified ? "✓ verified" : "✗ mismatch"}</span></div>
      <div class="hash">SHA-256 ${esc(rec.content_hash)} · ${esc(rec.record_id)}</div>
      <div class="seal-actions">
        <button class="ghost-btn" id="verifyBtn">Re-verify</button>
        <button class="ghost-btn" id="packetBtn">Dispute packet (Agent 05)</button>
        <button class="ghost-btn" id="jsonBtn">Raw record</button>
      </div>
    </div>`;

  $("#progress").hidden = true;
  $("#resultEmpty").hidden = true;
  $("#result").hidden = false;

  $$(".check[data-key]").forEach((el) => {
    el.onmouseenter = () => highlight(el.dataset.key);
    el.onmouseleave = () => highlight(null);
  });
  $$("[data-override]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); openOverride(b.dataset.override); }));
  $("#verifyBtn").onclick = verifyRecord;
  $("#packetBtn").onclick = downloadPacket;
  $("#jsonBtn").onclick = () => download(`${rec.record_id}.json`, JSON.stringify(rec, null, 2));
  if (window.innerWidth < 1100) $("#resultCard").scrollIntoView({ behavior: "smooth" });
}

const titleOf = (rec, key) => (rec.checks.find((c) => c.check_key === key) || {}).title || key;

function summaryLine(rec) {
  const bad = rec.checks.filter((c) => c.verdict === "FAIL").map((c) => c.title);
  const unc = rec.checks.filter((c) => c.verdict === "UNCERTAIN").map((c) => c.title);
  if (rec.status === "failed_open") return "The vision step timed out; a person should check this unit.";
  const parts = [];
  if (bad.length) parts.push(`Failed: ${bad.join(", ")}.`);
  if (unc.length) parts.push(`Couldn't confirm: ${unc.join(", ")}.`);
  return parts.join(" ");
}

const HIDDEN_MEAS = new Set(["format_check", "glare_regions", "glare_on_product"]);
const MEAS_LABEL = {
  est_font_pt: "Warning print size (pt)", seal_coverage: "Seal coverage", open_gap_in: "Open gap (in)", haze_margin_fraction: "Film margin",
  bag_width_in: "Bag width (in)", visible_barcodes: "Barcodes visible", fnsku_format_labels: "FNSKU labels", label_width_in: "Label width (in)",
  brightness_step: "Brightness step", edge_falloff: "Edge fall-off", tape_contact: "Tape contact", fragments: "Panel pieces",
  occluded_band_in: "Hidden band (in)", text_lines: "Text lines", label_fill: "Label visible", occluder_fraction: "Covered", ink_fraction: "Ink",
  text_sharpness: "Print sharpness", panel_width_in: "Panel width (in)", panel_sharpness: "Panel sharpness", date_text: "Date read",
  fnsku_text: "FNSKU read", warning_text: "Warning read", wording_ok: "Wording OK", detected_marks: "Stickers found",
  exposed_width_fraction: "Exposed part", exposed_barcode_type: "Exposed type",
};

function checkRow(c) {
  if (c.verdict === "NOT_REQUIRED") {
    return `<details class="check na"><summary><span class="c-dot NOT_REQUIRED">${ICON.NOT_REQUIRED}</span><span class="c-main"><b>${esc(c.title)}</b><span>Not required for this unit</span></span><span class="pill NOT_REQUIRED">Not required</span></summary></details>`;
  }
  const fmt = (v) => { const s = Array.isArray(v) ? v.join(", ") || "none" : typeof v === "boolean" ? (v ? "yes" : "no") : typeof v === "number" ? (v <= 1 && v > 0 && !Number.isInteger(v) ? `${Math.round(v * 100)}%` : v) : String(v); return String(s).length > 70 ? String(s).slice(0, 67) + "…" : s; };
  const meas = Object.entries(c.measurements || {}).filter(([k, v]) => !HIDDEN_MEAS.has(k) && v !== null && v !== "" && typeof v !== "object" || Array.isArray(v))
    .filter(([k]) => !HIDDEN_MEAS.has(k)).slice(0, 8)
    .map(([k, v]) => `<div><span>${esc(MEAS_LABEL[k] || k.replace(/_/g, " "))}</span><b>${esc(fmt(v))}</b></div>`).join("");
  const tags = [...(c.rule_ids || []).map((r) => `<span class="tag rule">${esc(r)}</span>`),
    ...(c.required_by || []).map((r) => `<span class="tag ${r === "work_order" ? "wo" : ""}">${r === "work_order" ? "Work order" : "Amazon rule"}</span>`)].join("");
  return `
    <details class="check" data-key="${esc(c.check_key)}">
      <summary>
        <span class="c-dot ${esc(c.verdict)}">${ICON[c.verdict]}</span>
        <span class="c-main"><b>${esc(c.title)}</b><span>${esc(c.detail)}</span></span>
        <span class="pill ${esc(c.verdict)}">${esc(LABEL[c.verdict])}</span>
        <svg class="chev" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>
      </summary>
      <div class="c-body">
        ${c.remediation ? `<div class="fix ${c.verdict === "UNCERTAIN" ? "unc" : ""}"><b>${c.verdict === "FAIL" ? "How to fix" : "What would settle it"}</b>${esc(c.remediation)}</div>` : ""}
        ${meas ? `<div class="kv">${meas}</div>` : ""}
        <div class="conf"><span>Confidence</span><span class="bar"><i style="width:${Math.round(c.confidence * 100)}%"></i></span><span>${Math.round(c.confidence * 100)}%</span></div>
        <div class="tags">${tags}<span class="tag">${esc(c.reason_code)}</span></div>
        <div class="c-actions"><button class="text-btn" data-override="${esc(c.check_key)}">Override…</button></div>
      </div>
    </details>`;
}

function drawOverlay(rec) {
  const VC = { PASS: "pass", FAIL: "fail", UNCERTAIN: "unc" };
  const boxes = [], tags = [];
  for (const c of rec.checks) {
    const cls = VC[c.verdict];
    if (!cls) continue;
    for (const r of c.regions || []) {
      if (r.view_index !== 0) continue;
      const [x0, y0, x1, y1] = r.bbox.map((v) => v * 1000);
      boxes.push(`<rect class="box ${cls}" data-key="${esc(c.check_key)}" x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}"/>`);
      if (c.verdict !== "PASS") tags.push(`<span class="ov-tag ${cls}" data-key="${esc(c.check_key)}" style="left:${x0 / 10}%;top:${y0 / 10}%">${esc(c.title)}</span>`);
    }
  }
  $("#overlay").innerHTML = boxes.join("");
  $("#overlayLabels").innerHTML = tags.join("");
}

function highlight(key) {
  $$("#overlay .box").forEach((b) => { b.classList.toggle("dim", !!key && b.dataset.key !== key); b.classList.toggle("hl", !!key && b.dataset.key === key); });
  $$("#overlayLabels .ov-tag").forEach((t) => t.classList.toggle("dim", !!key && t.dataset.key !== key));
}

async function verifyRecord() {
  try {
    const v = await api(`/api/v1/records/${encodeURIComponent(state.record.record.record_id)}/verify`);
    toast(v.integrity_verified ? `Seal chain verified ✓ — original + ${v.override_chain_length} override(s) replayed, ${v.seal_chain_length} keyed seal(s) valid.` : `Integrity problem: ${(v.problems || []).join("; ")}`, !v.integrity_verified);
  } catch (e) { toast(e.message, true); }
}

async function downloadPacket() {
  const id = state.record.record.record_id;
  try { download(`dispute-${id}.json`, JSON.stringify(await api(`/api/v1/records/${encodeURIComponent(id)}/dispute-packet`), null, 2)); }
  catch (e) { toast(e.message, true); }
}

/* ------------------------------------------------------------------ override */
function setupOverride() {
  const dlg = $("#overrideDlg"), form = $("#overrideForm");
  dlg.addEventListener("close", async () => {
    if (dlg.returnValue !== "ok") return;
    const f = form.elements;
    try {
      const r = await api(`/api/v1/records/${encodeURIComponent(state.record.record.record_id)}/overrides`, {
        method: "POST", json: { check_key: dlg.dataset.key, new_verdict: f.new_verdict.value, reason: f.reason.value, expected_content_hash: state.record.record.content_hash },
      });
      renderRecord(r);
      toast("Override saved. The agent's original answer is kept in the record.");
      form.reset();
    } catch (e) { toast(e.message, true); }
  });
}

function openOverride(key) {
  const c = state.record.record.checks.find((x) => x.check_key === key);
  const dlg = $("#overrideDlg");
  dlg.dataset.key = key;
  $("#ovCheck").textContent = `${c.title} — the agent said “${LABEL[c.verdict]}”. Your override is added on top; the original stays in the record.`;
  dlg.showModal();
}

/* ------------------------------------------------------------------ history */
async function loadRecords() {
  try {
    const dec = $("#decisionFilter").value;
    const r = await api(`/api/v1/records?limit=200${dec ? `&decision=${dec}` : ""}`);
    state.records = r.records;
    renderRecords();
  } catch (e) { toast(e.message, true); }
}

function renderRecords() {
  const q = $("#recordSearch").value.trim().toLowerCase();
  const rows = state.records.filter((x) => !q || x.unit_id.toLowerCase().includes(q) || x.record_id.toLowerCase().includes(q));
  $("#recordsTable tbody").innerHTML = rows.map((x) => `
    <tr data-id="${esc(x.record_id)}">
      <td><b>${esc(x.unit_id)}</b></td>
      <td><span class="pill ${esc(x.decision)}">${esc(LABEL[x.decision])}</span></td>
      <td>${esc((x.category || "").replace(/_/g, " "))}</td>
      <td>${esc(ENGINE[x.provider] || x.provider || "—")}</td>
      <td>${(x.total_latency_ms / 1000).toFixed(1)} s</td>
      <td title="${esc(new Date(x.captured_at).toLocaleString())}">${esc(ago(x.captured_at))}</td>
      <td class="mono">${esc(x.record_id)}</td>
    </tr>`).join("") || `<tr class="empty-row"><td colspan="7">No inspections yet for this prep center — run one on the Inspect tab.</td></tr>`;
  $$("#recordsTable tbody tr[data-id]").forEach((tr) => (tr.onclick = () => openRecord(tr.dataset.id)));
}

function exportCsv() {
  if (!state.records.length) return toast("Nothing to export yet.", true);
  const cols = ["record_id", "unit_id", "decision", "category", "provider", "total_latency_ms", "captured_at", "content_hash"];
  const csv = [cols.join(","), ...state.records.map((r) => cols.map((c) => `"${String(r[c] ?? "").replace(/"/g, '""')}"`).join(","))].join("\n");
  download(`prep-manager-history-${new Date().toISOString().slice(0, 10)}.csv`, csv, "text/csv");
}

async function openRecord(id) {
  try {
    const r = await api(`/api/v1/records/${encodeURIComponent(id)}`);
    state.scenario = null;
    $$(".sample").forEach((b) => b.classList.remove("active"));
    showTab("inspect");
    const url = (r.image_urls || []).find(Boolean);
    if (url) showImage(url);
    renderRecord(r);
  } catch (e) { toast(e.message, true); }
}

async function runAudit() {
  try {
    const a = await api("/api/v1/tenancy/audit");
    toast(a.isolation_verified ? "Isolation verified ✓ — 0 records visible across prep centers." : `Leak detected: ${a.cross_tenant_rows_visible} rows!`, !a.isolation_verified);
  } catch (e) { toast(e.message, true); }
}

/* ------------------------------------------------------------------ insights */
const COLOR = { PASS: "var(--pass)", FAIL: "var(--fail)", UNCERTAIN: "var(--unc)", PENDING_REVIEW: "#f97316", NOT_REQUIRED: "var(--na)" };

async function loadInsights() {
  try {
    const m = await api("/api/v1/metrics");
    $("#liveKpis").innerHTML = [
      ["Units inspected", m.total_units, ""],
      ["Ready to ship", pct(m.pass_rate), "passed every check"],
      ["Sent to a human", pct(m.uncertain_rate), "honest “needs review”"],
      ["Typical time", `${(m.latency_ms.p50 / 1000).toFixed(1)} s`, `slowest 5%: ${(m.latency_ms.p95 / 1000).toFixed(1)} s`],
      ["Model cost", `$${m.avg_cost_usd.toFixed(3)}`, "average per unit"],
      ["Line stoppages", 0, `${m.fail_open_count} fail-open event(s), none blocked`],
    ].map(([k, v, s]) => `<div class="kpi"><span>${esc(k)}</span><b>${esc(v)}</b><small>${esc(s)}</small></div>`).join("");
    $("#decisionChart").innerHTML = donut(m.decisions);
    $("#perCheckChart").innerHTML = stacked(m.per_check);
  } catch (e) { toast(e.message, true); }
  try {
    const r = await fetch("/api/v1/evaluation");
    if (!r.ok) throw new Error();
    renderEval(await r.json());
  } catch {
    $("#evalKpis").innerHTML = `<div class="kpi"><span>Evaluation</span><b>—</b><small>run eval/run_eval.py</small></div>`;
  }
}

function donut(dec) {
  const total = Object.values(dec).reduce((a, b) => a + b, 0);
  if (!total) return `<p class="muted">No inspections yet.</p>`;
  const R = 62, C = 2 * Math.PI * R;
  let acc = 0;
  const arcs = Object.entries(dec).filter(([, v]) => v).map(([k, v]) => {
    const len = (v / total) * C;
    const s = `<circle r="${R}" cx="80" cy="80" fill="none" stroke="${COLOR[k]}" stroke-width="20" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-acc}" transform="rotate(-90 80 80)"/>`;
    acc += len;
    return s;
  }).join("");
  return `<div class="donut"><svg width="160" height="160" viewBox="0 0 160 160"><circle r="${R}" cx="80" cy="80" fill="none" stroke="var(--surface-3)" stroke-width="20"/>${arcs}
    <text x="80" y="78" text-anchor="middle" fill="var(--text)" font-size="28" font-weight="800">${total}</text><text x="80" y="98" text-anchor="middle" fill="var(--text-3)" font-size="11" font-weight="600">units</text></svg>
    <div class="legend">${Object.entries(dec).map(([k, v]) => `<span><i style="background:${COLOR[k]}"></i>${esc(LABEL[k])} · ${v}</span>`).join("")}</div></div>`;
}

function stacked(perCheck) {
  const keys = Object.keys(perCheck);
  if (!keys.length) return `<p class="muted">No inspections yet.</p>`;
  const order = ["PASS", "FAIL", "UNCERTAIN", "NOT_REQUIRED"];
  return keys.map((k) => {
    const v = perCheck[k];
    const tot = Object.values(v).reduce((a, b) => a + b, 0) || 1;
    return `<div class="bar-row"><span>${esc(k.replace(/_/g, " ").replace(/\b\w/, (c) => c.toUpperCase()))}</span><span class="track">${order.map((x) => (v[x] ? `<i style="width:${(v[x] / tot) * 100}%;background:${COLOR[x]}" title="${LABEL[x]}: ${v[x]}"></i>` : "")).join("")}</span><span class="n">${tot}</span></div>`;
  }).join("") + `<div class="legend">${order.map((x) => `<span><i style="background:${COLOR[x]}"></i>${LABEL[x]}</span>`).join("")}</div>`;
}

function renderEval(e) {
  $("#evalKpis").innerHTML = [
    ["Clean photos correct", pct(e.clean_accuracy), "normal + slight defocus", true],
    ["Bad photos handled safely", pct(e.degraded_safe_rate), "right answer or “needs review”", true],
    ["Defects missed", e.missed_defects, "bad units passed", e.missed_defects === 0],
    ["False alarms", e.false_alarms, "good units failed", e.false_alarms === 0],
    ["Sent to a human", pct(e.uncertain_rate), "of all 50 units"],
    ["Typical time", `${(e.latency_ms.p50 / 1000).toFixed(2)} s`, "station camera engine"],
  ].map(([k, v, s, good]) => `<div class="kpi ${good ? "good" : ""}"><span>${esc(k)}</span><b>${esc(v)}</b><small>${esc(s)}</small></div>`).join("");
  $("#evalChecks").innerHTML = `<thead><tr><th>Check</th><th>Units</th><th>Right</th><th>Missed</th><th>False alarm</th><th>Review</th></tr></thead><tbody>` +
    Object.values(e.per_check).map((c) => `<tr><td>${esc(c.title)}</td><td>${c.applicable}</td><td>${c.tp + c.tn}</td><td class="${c.fn ? "bad-num" : ""}">${c.fn}</td><td class="${c.fp ? "bad-num" : ""}">${c.fp}</td><td>${c.uncertain}</td></tr>`).join("") + "</tbody>";
  const OC = { correct: ["var(--pass)", "Right answer"], abstained: ["var(--unc)", "Needs review"], missed_defect: ["var(--fail)", "Missed defect"], false_alarm: ["#f97316", "False alarm"] };
  const NAMES = { normal: "Normal", soft: "Slightly blurry", blur: "Motion blur", glare: "Glare", dark: "Too dark" };
  $("#condChart").innerHTML = Object.entries(e.by_condition).map(([cond, v]) => {
    const tot = Object.values(v).reduce((a, b) => a + b, 0) || 1;
    return `<div class="bar-row"><span>${esc(NAMES[cond] || cond)}</span><span class="track">${Object.keys(OC).map((k) => (v[k] ? `<i style="width:${(v[k] / tot) * 100}%;background:${OC[k][0]}" title="${OC[k][1]}: ${v[k]}"></i>` : "")).join("")}</span><span class="n">${tot}</span></div>`;
  }).join("") + `<div class="legend">${Object.values(OC).map(([c, l]) => `<span><i style="background:${c}"></i>${l}</span>`).join("")}</div>`;
}

/* ------------------------------------------------------------------ rules & about */
function renderRules(r) {
  $("#rulesGrid").innerHTML = r.rules.map((x) => `
    <article class="card rule">
      <div class="rule-top"><span class="rule-id">${esc(x.rule_id)}</span><span class="src ${esc(x.source)}">${x.source === "amazon_fba" ? "AMAZON FBA" : "WORK ORDER"}</span></div>
      <h3>${esc(x.title)}</h3>
      <p>${esc(x.requirement)}</p>
      <div class="tags"><span class="tag ${x.visually_verifiable ? "rule" : ""}">${x.visually_verifiable ? "Checked from the photo" : "Needs a document"}</span></div>
      <p class="ref">${esc(x.source_ref)}</p>
    </article>`).join("");
}

function renderAbout(card) {
  $("#agentTagline").textContent = card.tagline;
  const pc = card.perception;
  $("#agentCard").innerHTML = `
    <div class="two"><h3>The agent in two lines</h3>${card.description.map((l) => `<p>${esc(l)}</p>`).join("")}</div>
    <div><h3>Running now</h3><div class="runtime">
      <div><span>Version</span><b>${esc(card.version)}</b></div>
      <div><span>Rules</span><b>${esc(card.rules_version)}</b></div>
      <div><span>Station frames</span><b>Station camera engine</b></div>
      <div><span>Phone photos</span><b>${pc.free_vision_configured ? `Free AI vision · ${esc((pc.free_vision_model || "").split("/").pop())} + offline text engine` : "Offline text engine"}</b></div>
      <div><span>Paid AI services</span><b>${pc.paid_models_allowed ? "Allowed" : "Locked off — $0 guaranteed"}</b></div>
      <div><span>Time budget</span><b>${(pc.timeout_ms / 1000).toFixed(0)} s station · up to 3 min free AI, then send to review</b></div>
    </div></div>`;
  const nodes = [
    ["Work out the rules", "Combines Amazon's rules for the category with the work order, and flags anything the work order forgot."],
    ["Fingerprint the photos", "Every image gets a SHA-256 fingerprint, so the evidence can't be swapped later."],
    ["Check photo quality", "Measures blur, glare and exposure. Unusable photos skip the model and ask for a retake."],
    ["Choose how to look", "Station frames → station camera engine. Phone photos → Claude vision, or the offline text engine without a key."],
    ["Look at the unit", "Describes what it sees — never decides. One model call at most, with a hard time limit."],
    ["Apply the rules", "A rule engine turns observations into Pass / Fail / Needs review, and cites the rule."],
    ["Decide & advise", "Any Fail → fix before shipping. Any doubt → a human looks. Gives the exact fix."],
    ["Seal the record", "Stores the result once, sealed with SHA-256, ready for a fee dispute months later."],
  ];
  $("#flow").innerHTML = nodes.map(([t, d]) => `<div class="node"><b>${esc(t)}</b><p>${esc(d)}</p></div>`).join("");
}
