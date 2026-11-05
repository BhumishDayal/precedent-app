/* Precedent product app. Client-side routes over /api/*; live updates over SSE (/api/stream) with a polling fallback. */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmt = n => (n == null || n === "" || isNaN(n) ? "–" : Number(n).toLocaleString());
const pct = (x, d = 0) => (x == null || isNaN(x) ? "–" : (x * 100).toFixed(d) + "%");
const tm = t => (t ? new Date(t).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"}) : "");
const dayLabel = t => { if (!t) return ""; const d = new Date(String(t).length <= 10 ? t + "T00:00:00" : t); return isNaN(d) ? "" : d.toLocaleDateString([], {month: "short", day: "numeric"}); };
const cap = s => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);
const ago = t => { if (!t) return "–"; const s2 = (Date.now() - new Date(t)) / 1000; if (isNaN(s2)) return "–";
  if (s2 < 5) return "just now"; if (s2 < 60) return `${Math.round(s2)} s ago`; if (s2 < 3600) return `${Math.round(s2 / 60)} min ago`;
  if (s2 < 86400) return `${Math.round(s2 / 3600)} h ago`; return dayLabel(t); };
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const recTag = `<span class="pill" style="height:18px;font-size:10.5px;margin-left:6px">fleet record</span>`;
const view = () => $("#view");

const failedGet = {};  // path -> the server's `detail` from its last failed GET, so an error state can say why
async function api(path, opts) {  // JSON or null; POSTs return {__status, __text} on HTTP errors
  try {
    const r = await fetch(path, opts);
    if (!r.ok) {
      const text = (await r.text()).slice(0, 300);
      if (opts && opts.method) return {__status: r.status, __text: text};
      let detail = ""; try { detail = JSON.parse(text).detail; } catch (e) { /* not JSON */ }
      failedGet[path] = typeof detail === "string" ? detail : "";
      return null;
    }
    delete failedGet[path];
    return await r.json();
  } catch (e) { failedGet[path] = ""; return null; }
}
const post = (path, body) => api(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
const errText = r => r && r.__text ? r.__text.replace(/[{}"]/g, "").replace(/^detail:/, "").trim() : "";
const loadError = (what, path) => `<span role="alert">${failedGet[path] ? esc(cap(failedGet[path]).replace(/([^.!?])$/, "$1.")) : `Couldn't load ${what}.`} <button class="linkbtn" data-retry>Try again</button></span>`;
function onActivate(el, fn) {  // rows and list items that behave like buttons: click, Enter or Space
  el.onclick = fn;
  el.onkeydown = e => { if (e.target === el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); fn(e); } };
}

const P = {
  server: '<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
  text: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  slack: '<line x1="4" x2="20" y1="9" y2="9"/><line x1="4" x2="20" y1="15" y2="15"/><line x1="10" x2="8" y1="3" y2="21"/><line x1="16" x2="14" y1="3" y2="21"/>',
  web: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
  keewano: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
  darwin: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  sparta: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  drive: '<line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  sigma: '<path d="M18 7V4H6l6 8-6 8h12v-3"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  heart: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  grid: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
};
const icon = (name, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || P.activity}</svg>`;
const CH_ICON = {server: "server", call: "phone", phone: "phone", voice: "phone", text: "text", sms: "text", imessage: "text", dial: "phone", slack: "slack",
  discord: "slack", teams: "slack", webhook: "web", web: "web", api: "web", keewano: "keewano", darwin: "darwin", sparta: "sparta", decision: "check",
  telemetry: "activity", alert: "bell", collector: "activity", resolve: "wrench", tech: "text", technician: "text"};

// The main UI shows names, never phone numbers, ids or dry-run wording.
const PEOPLE = {oncall: "the on-call engineer", tech: "the technician", techNumber: ""};
api("/api/stage").then(s => {
  if (!s) return;
  PEOPLE.oncall = s.oncall_name || PEOPLE.oncall; PEOPLE.tech = s.tech_name || PEOPLE.tech; PEOPLE.techNumber = s.tech_number || "";
  if (s.oncall_name) $("#pSub").textContent = `${s.oncall_name}'s phone`;
  phoneRender();
});
// Unconfigured servers name people by role ("On-call engineer"); inside a sentence that reads "the on-call engineer".
const say = n => /^(on-call engineer|technician)$/i.test(n || "") ? "the " + n.toLowerCase() : n;
const nameFor = phone => PEOPLE.techNumber && String(phone).replace(/\D/g, "") === PEOPLE.techNumber.replace(/\D/g, "") ? PEOPLE.tech : PEOPLE.oncall;
const ACTOR = {dial: "Dial", precedent: "Precedent", system: "Precedent", web: "Console", api: "API", keewano: "Keewano", darwin: "Darwin", sparta: "Sparta", slack: "Slack", collector: "Collector"};
function actorName(a) {
  if (!a) return "";
  if (/^\+?\d{8,15}$/.test(String(a))) return nameFor(a);
  return ACTOR[String(a).toLowerCase()] || String(a);
}
function human(t) {
  if (!t) return "";
  if (/not logged \(dry-run/i.test(t)) return "";  // nothing happened: not worth a row
  return cap(String(t)
    .replace(/\+\d{8,15}/g, m => nameFor(m))
    .replace(/\b(?:[Tt]he )?(On-call engineer|Technician)\b/g, (m, n) => say(n))
    .replace(/\s*[-–]\s*alert [0-9a-f]{6,}/gi, "")
    .replace(/\bCall dry-run\b/gi, "Call placed")
    .replace(/\s*\((?:dry-run|dry run)[^)]*\)/gi, "").replace(/\bdry-run\b:?\s*/gi, "")
    .replace(/\(via web\)/gi, "from the console").replace(/\(via call\)/gi, "on the call").replace(/\(via (\w+)\)/gi, "via $1")
    .replace(/\bDecision: swap\b/g, "Decision: Replace").replace(/\bDecision: wait\b/g, "Decision: Wait")
    .replace(/identical drives died/g, "identical drives failed").replace(/\s{2,}/g, " ").trim());
}

function toast(msg, ic = "bell") {
  const el = document.createElement("div");
  el.className = "toast"; el.innerHTML = icon(ic) + `<span>${esc(msg)}</span>`;
  $$("#toasts .toast").forEach(t => t.remove());  // one toast at a time
  $("#toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 200); }, 4000);
}

// Live updates come over SSE; pages poll only while the stream is down.
const Live ={mode: "connecting", subs: new Set(), es: null};
const STREAM_TYPES = ["telemetry_received", "alert_created", "call_state", "transcript_turn", "message_sent", "message_received", "decision",
  "action_started", "action_result", "notification", "keewano_logged", "fleet_heartbeat", "warning_triaged", "incident_resolved", "drive_failed",
  "incident_state", "incident_opened", "playbook_suggested", "sparta_verified"];
function setLive(mode) {
  Live.mode = mode;
  const el = $("#live"); if (!el) return;
  el.className = "live" + (mode === "live" ? " on" : mode === "poll" ? " poll" : "");
  el.querySelector("span").textContent = mode === "live" ? "Live" : mode === "poll" ? "Auto-refresh" : "Connecting";
}
function emit(ev) {
  if (!ev || !ev.type) return;
  for (const fn of Live.subs) { try { fn(ev); } catch (e) { /* one bad subscriber never breaks the stream */ } }
  globalToast(ev);
}
function connectStream() {
  if (!("EventSource" in window)) return setLive("poll");
  let es;
  try { es = new EventSource("/api/stream"); } catch (e) { return setLive("poll"); }
  Live.es = es;
  es.onopen = () => setLive("live");
  const handle = (type, raw) => { let d; try { d = JSON.parse(raw); } catch (e) { return; } emit({...d, type: d.type || type}); };
  es.onmessage = m => handle(null, m.data);
  STREAM_TYPES.forEach(t => es.addEventListener(t, m => handle(t, m.data)));
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) { setLive("poll"); es.close(); setTimeout(connectStream, 20000); }  // 404 / server gone
    else setLive("connecting");  // browser is auto-reconnecting
  };
}
const lastToast = {};
const simulated = ev => !!(ev.simulated || (ev.data && ev.data.simulated) || ev.via === "replay" || /simulated/i.test(String(ev.by || ev.actor || "")));
function globalToast(ev) {  // only what a person should notice now; never the ambient fleet stream or the simulated ops team
  if (simulated(ev)) return;
  const t = ev.type, serial = ev.serial || (ev.alert && ev.alert.serial) || "";
  const replay = /replay/i.test(String(ev.status || (ev.alert && ev.alert.status) || ev.text || ""));
  let msg = null, ic = "bell";
  if (t === "alert_created" && !replay) msg = `Paging ${PEOPLE.oncall} about drive ${serial}`;
  else if (t === "decision" && ev.choice) { msg = `Decision on ${serial || "a drive"}: ${CHOICE[ev.choice] || ev.choice}`; ic = "check"; }
  else if (t === "incident_resolved") { msg = `Incident resolved${serial ? ` for ${serial}` : ""}`; ic = "wrench"; }
  else if (t === "playbook_suggested") { msg = `A learned playbook applies to ${serial || "this warning"}`; ic = "wrench"; }
  else if (t === "sparta_verified") { msg = ev.ok === false ? "Sparta rehearsal failed: fix blocked" : "Sparta verified the fix"; ic = "sparta"; }
  else if ((t === "darwin_act") || (t === "action_result" && ev.sponsor === "darwin" && /act/i.test(String(ev.status || ev.detail || "")))) { msg = "Fix carried out via Darwin"; ic = "darwin"; }
  else if (/escalat/i.test(t) || /escalat/i.test(String(ev.text || "")) && t !== "warning_triaged") { msg = `Escalated${serial ? ` for ${serial}` : ""}: ${human(ev.text) || "no answer yet"}`; ic = "alert"; }
  if (!msg) return;
  const key = t + (ev.alert_id || serial);
  if (lastToast[key] && Date.now() - lastToast[key] < 5000) return;
  lastToast[key] = Date.now();
  toast(msg, ic);
}

let pageTimers = [], pageSubs = [], pageCleanup = [];
let routeGen = 0;  // bumped on every route(): a page that resumes after an await checks it before subscribing
function every(fn, ms) {  // page-scoped poll; skipped while the stream is live (events drive refresh instead)
  fn();
  pageTimers.push(setInterval(() => { if (Live.mode !== "live") fn(); }, ms));
}
function onEvent(fn) { Live.subs.add(fn); pageSubs.push(fn); }
function go(path) { history.pushState({}, "", path); route(); }
document.addEventListener("click", e => {
  if (e.target.closest("[data-retry]")) return route();
  const dismiss = e.target.closest("[data-dismiss]");
  if (dismiss) {
    try { localStorage.setItem("purpose:" + dismiss.dataset.dismiss, "1"); } catch (err) { /* private mode: hide for this visit only */ }
    return dismiss.closest(".purpose").remove();
  }
  const a = e.target.closest("a[href]");
  if (!a || a.target || e.metaKey || e.ctrlKey || e.shiftKey) return;
  const href = a.getAttribute("href");
  if (!href.startsWith("/app")) return;  // only console routes are client-side; /stage, /incident/{id}, landing are full pages
  e.preventDefault(); go(href);
});
window.addEventListener("popstate", route);
function crumbs(parts) {
  $("#crumbs").innerHTML = parts.map((p, i) => i === parts.length - 1 ? `<b>${p[0]}</b>` : `<a href="${p[1]}">${p[0]}</a><span>/</span>`).join("");
}
function route() {
  routeGen++;
  pageTimers.forEach(clearInterval); pageTimers = [];
  pageSubs.forEach(fn => Live.subs.delete(fn)); pageSubs = [];
  pageCleanup.forEach(fn => { try { fn(); } catch (e) {} }); pageCleanup = [];
  const path = location.pathname.replace(/^\/app/, "") || "/", q = new URLSearchParams(location.search);
  document.body.classList.toggle("embed", q.has("embed"));
  const section = path.startsWith("/systems") ? "systems" : path.startsWith("/comms") ? "comms" : path.startsWith("/logs") || path.startsWith("/activity") ? "activity" : path.startsWith("/drives") ? "drives" : path.startsWith("/graph") ? "drives"
    : path.startsWith("/integrations") ? "integrations" : path.startsWith("/impact") ? "impact" : "today";
  $$("nav a[data-nav]").forEach(a => a.classList.toggle("on", a.dataset.nav === section));
  window.scrollTo(0, 0);
  let m;
  view().classList.toggle("simple", ["today", "activity", "drives", "comms"].includes(section) && !path.startsWith("/graph"));
  phoneShow(!q.has("embed") && ((section === "today" && !path.startsWith("/incidents")) || /^\/drives\/[^/]+$/.test(path)));
  if (path === "/incidents/new") return pageNew();
  if ((m = path.match(/^\/incidents\/([^/]+)$/))) return pageIncident(decodeURIComponent(m[1]));
  if ((m = path.match(/^\/drives\/([^/]+)$/))) return pageStory(decodeURIComponent(m[1]));
  if (path.startsWith("/graph")) return pageGraph(q.get("alert_id"), q.get("serial"));
  if (section === "activity") return pageActivity(q);
  if (section === "comms") return pageComms();
  if (section === "systems" || (section === "integrations" && !q.has("full"))) return pageSystems();
  if (section === "drives") return pageDrivesSimple(q);
  if (section === "integrations") return pageIntegrations();
  if (section === "impact") return pageImpact();
  return path === "/incidents" ? pageIncidents() : pageToday();
}

function purpose(key, text) {  // a small, dismissible "What this is for" line at the top of a page
  let gone = false; try { gone = localStorage.getItem("purpose:" + key) === "1"; } catch (e) {}
  return gone ? "" : `<div class="purpose"><span>${text}</span><button class="btn ghost sm" aria-label="Dismiss" data-dismiss="${key}">${icon("x")}</button></div>`;
}
const dayName = t => { const d = new Date(t); if (isNaN(d)) return ""; const n = new Date();
  if (d.toDateString() === n.toDateString()) return "Today"; if (d.toDateString() === new Date(n - 864e5).toDateString()) return "Yesterday";
  return d.toLocaleDateString([], {month: "short", day: "numeric"}); };
const COUNTS = {watching: 0, checked: 0, harmless: 0, swap_list: 0, failures: 0};  // only ever go up while the console runs
const bump = o => { for (const k of Object.keys(COUNTS)) if (o && o[k] != null && +o[k] > COUNTS[k]) COUNTS[k] = +o[k]; };
const ATTR_WORDS = {5: "Reallocated sectors", 187: "Uncorrectable errors", 188: "Command timeouts", 197: "Pending sectors", 198: "Unreadable sectors"};
const whatsWrong = pattern => { if (!pattern) return "–"; const a = String(pattern).split(":")[0].split("+"), main = a.includes("197") ? "197" : a.includes("198") ? "198" : a[0];
  return `${ATTR_WORDS[main] || "SMART errors"} ${/high/.test(pattern) ? "rising fast" : "rising"}`; };
const whenLabel = t => { if (!t) return ""; const d = new Date(String(t).length <= 10 ? t + "T12:00:00" : t); if (isNaN(d)) return "";
  const today = new Date(); const same = d.toDateString() === today.toDateString(), y = new Date(today - 864e5).toDateString() === d.toDateString();
  const hm = String(t).length <= 10 ? "" : " " + d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  return same ? `Today${hm}` : y ? `Yesterday${hm}` : d.toLocaleDateString([], {month: "short", day: "numeric"}); };
async function decide(alertId, choice, card) {
  const r = await post(`/api/incidents/${encodeURIComponent(alertId)}/decide`, {choice, by: PEOPLE.oncall});
  if (!r || r.__status) { toast(r && r.__status === 404 ? "That incident is no longer open" : "Couldn't save the decision", "alert"); return false; }
  if (card) { card.classList.add("gone"); setTimeout(() => card.remove(), 220); }
  toast(choice === "swap" ? "Marked to replace. The technician has the details." : "Marked to wait. We'll keep watching.", "check");
  return true;
}
async function openIncidents() {  // open = paged, not yet decided or fixed, assigned to the on-call; null if nothing loaded
  const mineApi = await api("/api/incidents?assigned_to=me&open=true");
  if (mineApi && Array.isArray(mineApi.rows)) {
    if (mineApi.oncall) PEOPLE.oncall = mineApi.oncall;
    const iso = v => v == null || v === "" ? null : typeof v === "number" ? new Date(v > 1e12 ? v : v * 1000).toISOString() : String(v);  // ISO strings pass through
    return mineApi.rows.map(r => ({...r, alert_id: r.alert_id || r.id, ts: r.ts || iso(r.created_ts)}))
      .sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  }
  const [al, st] = await Promise.all([api("/api/alerts?limit=300&db=1"), statusMap()]);
  if (!al) return null;
  const rows = al.rows || [];
  // only incidents assigned to the on-call person; background replay incidents belong to the simulated ops team (Activity only)
  const mine = a => a.assigned_to ? a.assigned_to === PEOPLE.oncall : !/replay|simulated/i.test(String(a.status || "") + " " + String(a.text || ""));
  return rows.filter(a => mine(a) && !st[a.alert_id] && !/resolv|verif|decid|action/i.test(String(a.status || "")));
}

function pageToday() {
  crumbs([["Today"]]);
  view().innerHTML = purpose("today", "Everything that needs a person, and what Precedent handled on its own.") + `<div class="hello-row"><h1 class="hello" id="hello">Watching the fleet.</h1><button class="btn" id="simBtn">${icon("phone")}Simulate a real incident</button></div>
    <p class="sub2">Here is what needs you right now.</p><div class="simstrip" id="simStrip" hidden></div>
    <div class="tiles" id="tiles"></div>
    <div class="needs" id="needs"><div class="need"><div class="skel" style="width:40%"></div></div></div>
    <div class="twocol"><section class="panel"><h2>Happening now</h2><ul class="happening" id="now"><li><span></span><span></span><span class="faint">Waiting for the next event…</span></li></ul></section>
      <section class="panel"><h2 id="riskH">Most likely to fail next</h2><div class="risk" id="risk"><div class="skel"></div></div></section></div>
    <a class="auto" id="auto" href="/app/activity"></a><br><a class="auto" id="ops" href="/app/activity?f=person" style="margin-top:6px"></a>`;
  let prevTiles = {};
  const tiles = () => {
    const T = [["watching", "Drives watching"], ["checked", "Warnings checked"], ["harmless", "Harmless"], ["swap_list", "Added to swap list"], ["failures", "Failures today"]];
    if (!$("#tiles")) return;
    $("#tiles").innerHTML = T.map(([k, l]) => `<div class="tile"><div class="v ${prevTiles[k] != null && COUNTS[k] > prevTiles[k] ? "up" : ""}">${fmt(COUNTS[k] || 0)}</div><div class="l">${l}</div></div>`).join("");
    prevTiles = {...COUNTS};
  };
  const count = (n, one, many) => `<b>${fmt(n)}</b> ${n === 1 ? one : many}`;
  const sentence = () => {
    tiles();
    $("#hello").innerHTML = `Watching ${count(COUNTS.watching, "drive", "drives")}. ${count(COUNTS.checked, "warning", "warnings")} checked today. ${count(COUNTS.harmless, "was", "were")} harmless.`;
    $("#auto").textContent = `Handled automatically today: ${fmt(COUNTS.harmless)} harmless warnings · ${fmt(COUNTS.swap_list)} added to tomorrow's swap list`;
  };
  const counts = async () => {
    const t = await api("/api/today");
    if (t) bump(t);
    else {  // fallback: sum today's feed
      const [hb, wt] = await Promise.all([api("/api/feed?kind=fleet_heartbeat&limit=50"), api("/api/feed?kind=warning_triaged&limit=5000")]);
      const hbs = (hb && hb.rows) || [], ws = (wt && wt.rows) || [], d0 = todayISO();
      const last = hbs.map(e => e.date).filter(Boolean).sort().pop(), bySite = {};
      hbs.filter(e => e.date === last).forEach(e => { if (e.drives_reporting != null) bySite[e.site || "_"] = e.drives_reporting; });
      const today = ws.filter(e => !e.date || e.date === d0 || e.date === last);
      bump({watching: Object.values(bySite).reduce((a, b) => a + b, 0), checked: today.length,
            harmless: today.filter(e => verdictKey(e.verdict) === "harmless").length, swap_list: today.filter(e => verdictKey(e.verdict) === "swaplist").length});
    }
    if ($("#hello")) sentence();
  };
  const cards = async () => { try { await cardsInner(); } catch (e) {  // never leave the skeleton stuck
      if ($("#needs")) $("#needs").innerHTML = `<p class="faint">${loadError("what needs you")}</p>`; } };
  const cardsInner = async () => {
    const all = await openIncidents();
    if (!$("#needs")) return;
    if (!all) { $("#needs").innerHTML = `<p class="faint">${loadError("what needs you")}</p>`; return; }
    const open = all.slice(0, 8);
    const det = await Promise.all(open.map(a => Promise.all([api(`/api/incident/${encodeURIComponent(a.alert_id)}`), api(`/api/drives/${encodeURIComponent(a.serial)}`)])));
    if (!$("#needs")) return;
    if (!open.length) { $("#needs").innerHTML = ""; return; }
    $("#needs").innerHTML = open.map((a, i) => {
      const [inc, prof] = det[i], P2 = (inc && inc.found && inc.precedent) || a, L = (prof && prof.location) || {}, fix = a.suggested_fix || (inc && inc.suggested_fix);
      const act = P2.act !== false && (P2.rate == null || P2.rate >= 0.25 || /act|urgent/i.test(a.verdict || "act"));
      const site = a.site && !/replay|simulated/i.test(a.site) ? a.site : "";
      const where = [L.datacenter || site, L.pod_id && `pod ${L.pod_id}`, L.pod_slot_num && `slot ${+L.pod_slot_num}`].filter(Boolean).join(" · ");
      return `<div class="need" data-id="${esc(a.alert_id)}"><h3>${act ? "Replace" : "Check"} drive <span class="mono">${esc(a.serial)}</span></h3>
        <div class="btns"><button class="btn" data-d="swap">Replace</button><button class="btn secondary" data-d="wait">Wait</button><a class="btn ghost" href="/app/drives/${encodeURIComponent(a.serial)}">Details</a></div>
        <div class="why">${fmt(P2.died)} of ${fmt(P2.n)} drives like it failed within a month.</div>
        <div class="where">${esc(where)}${where ? " · " : ""}${ago(a.ts)}</div>
        ${fix ? `<div class="fix">Last time: ${esc(fix.by || "an engineer")} ${esc(lcFirst(fix.steps_text || fix.text || "logged a fix")).replace(/\.$/, "")}. <button class="linkbtn" data-fix>Apply that fix</button></div>` : ""}</div>`;
    }).join("");
    $$("#needs .need").forEach(card => {
      const id = card.dataset.id;
      $$("[data-d]", card).forEach(b => b.onclick = async () => { b.disabled = true; if (!(await decide(id, b.dataset.d, card))) b.disabled = false; else setTimeout(cards, 400); });
      const f = $("[data-fix]", card); if (f) f.onclick = async () => {
        const r = await post(`/api/incidents/${encodeURIComponent(id)}/apply-playbook`, {by: PEOPLE.tech});
        toast(!r || r.__status ? "Couldn't start the fix" : "Rehearsing the fix in Sparta, then an agent carries it out", !r || r.__status ? "alert" : "wrench");
      };
    });
  };
  const ops = async () => {
    const al = await api("/api/alerts?limit=300&db=1"), d0 = new Date().toDateString();
    const n = ((al && al.rows) || []).filter(a => (a.assigned_to ? a.assigned_to !== PEOPLE.oncall : /replay|simulated/i.test(String(a.status || ""))) && new Date(a.ts).toDateString() === d0).length;
    if ($("#ops")) $("#ops").textContent = n ? `The ops team handled ${fmt(n)} incident${n === 1 ? "" : "s"} today (see Activity)` : "";
  };
  ops(); every(ops, 30000);
  // "Simulate a real incident": 5 steps lit live from SSE
  const SIM = [["texted", "Texted you"], ["calling", "Calling you (in 5 s)"], ["oncall", "On the call"], ["report", "Report sent"], ["decided", "Waiting for your answer"]];
  const simLabel = `${icon("phone")}Simulate a real incident`;
  let sim = null;
  const paintSim = () => {
    const el = $("#simStrip"); if (!el) return;
    el.hidden = !sim; if (!sim) return;
    const idx = SIM.findIndex(([k]) => !sim.done[k]);
    el.innerHTML = SIM.map(([k, l], i) => `<span class="sst ${sim.done[k] ? "done" : i === idx ? "now" : ""}"><i></i>${k === "decided" && sim.done.decided ? `Decided: ${esc(sim.choice || "")}` : l}</span>`).join("");
  };
  const simDone = k => { if (!sim) return; for (const [kk] of SIM) { sim.done[kk] = true; if (kk === k) break; } paintSim(); };
  // The button is free again as soon as the server accepts a run: a later click starts over and the server stops the older run.
  $("#simBtn").onclick = async () => {
    const b = $("#simBtn"); b.disabled = true; b.innerHTML = `<span class="spin"></span>Starting…`;
    sim = {done: {}}; paintSim();
    const r = await post("/api/demo/simulate-incident");
    b.disabled = false; b.innerHTML = simLabel;
    if (!r || r.__status) {
      sim = null; paintSim();
      return toast(r && r.__status === 404 ? "Simulation isn't available on this server" : `Simulation didn't start: ${errText(r) || "the server didn't answer"}`, "alert");
    }
    sim.alert_id = r.alert_id;  // missing when a run started seconds ago (double click): follow that run
  };
  onEvent(ev => {
    if (!sim || (sim.alert_id && ev.alert_id && ev.alert_id !== sim.alert_id)) return;
    const body = String(ev.body || ev.text || "");
    if (ev.type === "message_sent" && /^(PRECEDENT SUMMARY|Summary for drive)/i.test(body)) simDone("report");
    else if (ev.type === "message_sent" && !sim.done.texted) simDone("texted");
    if (ev.type === "call_state") { const st = String(ev.state || "").toLowerCase();
      if (/ring|queued|initiat|dial/.test(st)) simDone("calling"); else if (/progress|answer|active|connected|complet|end/.test(st)) simDone("oncall"); }
    if (ev.type === "decision") { sim.choice = CHOICE[ev.choice] || ev.choice; simDone("decided"); }
  });

  // Happening now: the last 8 notable events, newest on top
  const notable = e => (e.type === "warning_triaged" && verdictKey(e.verdict) === "urgent") || ["drive_failed", "decision", "incident_resolved", "alert_created", "message_sent", "message_received", "sparta_verified"].includes(e.type)
    || (e.type === "call_state" && /end|complete|answer/i.test(e.state || ""));
  let nowRows = [];
  const paintNow = () => {
    const el = $("#now"); if (!el) return;
    const hm = t => new Date(t).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
    const rows = nowRows.filter(e => activitySentence(e));
    el.innerHTML = rows.length ? rows.map(e => { const bad = e.type === "drive_failed", need = e.type === "warning_triaged" || e.type === "alert_created";
      return `<li class="${e._new ? "new" : ""}"><time>${hm(e.ts)}</time><span style="color:${bad ? "var(--danger)" : need ? "var(--warn-ink)" : "var(--ink-3)"}">${icon(bad || need ? "alert" : /message|call/.test(e.type) ? "text" : "check")}</span>
        <span>${e.serial ? `<a href="/app/drives/${encodeURIComponent(e.serial)}" style="text-decoration:none">${esc(activitySentence(e))}</a>` : esc(activitySentence(e))}</span></li>`; }).join("")
      : `<li><span></span><span></span><span class="faint">Quiet right now. Notable events appear here the moment they happen.</span></li>`;
    nowRows.forEach(e => delete e._new);
  };
  api("/api/logs?limit=300").then(out => { const r = ((out && out.rows) || []).filter(notable); if (r.length && !nowRows.length) { nowRows = r.slice(0, 8); paintNow(); } else paintNow(); });
  // Most likely to fail next
  const risk = async () => {
    const out = await api("/api/keewano/at-risk"); const rows = ((out && out.rows) || []).slice(0, 5);
    if (!$("#risk")) return;
    $("#riskH").innerHTML = `Most likely to fail next${out && out.source === "keewano" ? `<div class="faint" style="font-size:12.5px;font-weight:400;margin-top:2px">Computed inside Keewano across ${fmt(out.scored)} drives that are warning</div>` : ""}`;
    const locs = await Promise.all(rows.map(r => r.datacenter ? null : api(`/api/drives/${encodeURIComponent(r.serial)}`)));
    if (!$("#risk")) return;
    $("#risk").innerHTML = rows.length ? rows.map((r, i) => { const L = (locs[i] && locs[i].location) || r;
      return `<a href="/app/drives/${encodeURIComponent(r.serial)}"><b>Drive <span class="mono">${esc(r.serial)}</span></b><span class="tnum">${fmt(r.died)} of ${fmt(r.n)} like it failed</span>
        <small>${esc([L.datacenter, L.pod_id && `pod ${L.pod_id}`].filter(Boolean).join(" · ") || r.model || "")}</small><small>${esc(whatsWrong(r.pattern || r.last_pattern))}</small></a>`; }).join("")
      : `<p class="faint" style="margin:0">No drive is close to failing right now.</p>`;
  };
  risk(); every(risk, 60000);
  every(counts, 20000); cards();
  let pend = null;
  onEvent(ev => {
    if (ev.type === "warning_triaged") { COUNTS.checked++; const v = verdictKey(ev.verdict); if (v === "harmless") COUNTS.harmless++; if (v === "swaplist") COUNTS.swap_list++; sentence(); }
    if (ev.type === "fleet_heartbeat" && ev.drives_reporting) { bump({watching: ev.drives_reporting}); sentence(); }
    if (ev.type === "drive_failed") { COUNTS.failures++; sentence(); }
    if (notable(ev)) { nowRows.unshift({...ev, ts: ev.ts || new Date().toISOString(), _new: true}); nowRows = nowRows.slice(0, 8); paintNow(); }
    if (["decision", "incident_resolved"].includes(ev.type) && ev.alert_id) {  // decided elsewhere (phone, Slack, ops team): fade the card out now
      const card = $(`#needs .need[data-id="${CSS.escape(ev.alert_id)}"]`); if (card) { card.classList.add("gone"); setTimeout(() => card.remove(), 220); }
    }
    if (["incident_opened", "alert_created", "decision", "incident_resolved", "incident_state", "playbook_suggested"].includes(ev.type)) { clearTimeout(pend); pend = setTimeout(cards, 600); }
  });
}
const lcFirst = t => String(t || "").charAt(0).toLowerCase() + String(t || "").slice(1);
const pressOne = (btns, on) => btns.forEach(x => { x.classList.toggle("on", x === on); x.setAttribute("aria-pressed", String(x === on)); });

const happenedText = r => {
  const k = r.kind || r.type || "", t = String(r.text || "");
  if (k === "smart_change") {
    const ms = [...t.matchAll(/(\w[\w ]*?) \((\d+)\) ([\d,]+) → ([\d,]+)/g)];
    if (ms.length) return ms.map(m => { const a = +m[3].replace(/,/g, ""), b = +m[4].replace(/,/g, ""), name = cap(m[1].trim());
      return b === 0 ? `${name} cleared (was ${m[3]})` : b < a ? `${name} fell from ${m[3]} to ${m[4]}` : `${name} ${a === 0 ? "jumped" : "rose"} from ${m[3]} to ${m[4]}`; }).join("; ");
  }
  if (k === "first_seen") return "Drive installed";
  if (k === "warning") { const m = r.data || {}; return `Warning: ${whatsWrong(m.pattern || (t.match(/Warning (\S+)/) || [])[1]).toLowerCase()}${m.n ? `. ${m.died} of ${m.n} drives like it failed` : ""}`; }
  if (k === "failed" || k === "drive_failed") return t.replace(/\.$/, "").replace(/Replaced \(fleet record\)\.?/, "").trim() || "Drive failed";
  if (/^Status:|keewano|incident_state/i.test(k + t)) return "";
  if (/^message_(sent|received)$/.test(k) && !/PRECEDENT SUMMARY/.test(t)) return "";      // replies show up as the decision row
  if (/^Texted |replied: |reply .* ignored/i.test(t)) return /ignored/i.test(t) ? "A later reply was kept as a comment (the first decision stands)" : "";
  if (/approved by|said (replace|wait)/i.test(t)) return human(t).replace(/Swap approved by (\w+) via (\w+)\.?/i, (m, who, via) => `${who} said replace (${via === "web" ? "from the console" : via === "call" ? "phone call" : via})`).replace(/\.$/, "");
  if (/PRECEDENT SUMMARY/.test(t)) return `Sent the full details to ${say(PEOPLE.tech)}`;
  return human(t).replace(/\.$/, "");
};
async function pageStory(serial) {
  const gen = routeGen;
  crumbs([["Drives", "/app/drives"], [`<span class="mono">${esc(serial)}</span>`]]);
  view().innerHTML = `<div class="skel" style="width:50%;height:28px;margin:12px 0"></div>`;
  const driveUrl = `/api/drives/${encodeURIComponent(serial)}`, storyUrl = `${driveUrl}/timeline`;
  const [p, al] = await Promise.all([api(driveUrl), api("/api/alerts?limit=300&db=1")]);
  if (gen !== routeGen) return;
  if (!p) { view().innerHTML = `<div class="calm">${loadError(`drive <span class="mono">${esc(serial)}</span>`, driveUrl)}</div>`; return; }
  if (!p.found) { view().innerHTML = `<div class="calm">No drive with serial <span class="mono">${esc(serial)}</span>.<br><br><a class="btn secondary" href="/app/drives">Back to drives</a></div>`; return; }
  const alert = ((al && al.rows) || []).find(a => a.serial === serial);
  const [inc, story, sc] = await Promise.all([alert ? api(`/api/incident/${encodeURIComponent(alert.alert_id)}`) : null, api(storyUrl),
    alert ? api(`/api/precedent/scoped?serial=${encodeURIComponent(serial)}&model=${encodeURIComponent(alert.model)}&pattern=${encodeURIComponent(alert.pattern)}`) : null]);
  if (gen !== routeGen) return;
  const lastW = (p.warnings || []).slice(-1)[0], dec = inc && inc.found && inc.decisions[0];
  const resolved = inc && /resolv|verif/.test(String(inc.state || ""));
  const P2 = (sc && sc.found && sc.network) || (inc && inc.precedent) || (lastW && lastW.n ? lastW : null) || {};
  const pill = p.failed_on && !alert ? `<span class="pill danger"><i></i>Failed</span>` : resolved ? `<span class="pill ok"><i></i>Fixed</span>`
    : dec ? `<span class="pill accent"><i></i>Decided</span>` : alert ? `<span class="pill warn"><i></i>Needs you</span>` : lastW ? `<span class="pill warn"><i></i>Watching</span>` : `<span class="pill ok"><i></i>Healthy</span>`;
  const big = p.failed_on && !alert ? `This drive failed on ${dayLabel(p.failed_on)}.` : resolved ? "This drive was fixed."
    : dec ? (dec.choice === "swap" ? "Replace this drive." : "Watch this drive.") : alert ? (P2.act === false ? "Watch this drive." : "Replace this drive.") : lastW ? "Watch this drive." : "This drive is healthy.";
  const why = P2.n ? `${fmt(P2.died)} of the ${fmt(P2.n)} drives like it (same model, same warning) failed within a month.` : lastW ? "It has started warning, but there isn't enough history on identical drives yet." : "No warnings so far.";
  const L = p.location || {}, fix = inc && inc.suggested_fix;
  const gq = alert ? `alert_id=${encodeURIComponent(alert.alert_id)}` : `serial=${encodeURIComponent(serial)}`;
  view().innerHTML = `<div>${pill}</div><h1 class="story-h">${big}</h1><p class="story-why">${why}</p>
    <div class="tabs" id="sTabs" style="margin-bottom:8px"><button class="on" data-t="ov" aria-pressed="true">Overview</button><button data-t="ct" aria-pressed="false">Calls &amp; texts</button><button data-t="hw" aria-pressed="false">How we decided</button><button data-t="mg" aria-pressed="false">Memory graph</button></div>
    <p class="faint" id="tabLine" style="font-size:13px;margin:0 0 4px">What's wrong, where it is, and what to do.</p>
    <div id="tab-ct" hidden></div><div id="tab-hw" hidden></div><div id="tab-mg" hidden></div>
    <div id="tab-ov">
    <div class="part" style="border-top:0"><div class="k">Where</div><div style="font-size:15px;margin-bottom:10px">${L.datacenter ? `${esc(L.datacenter)} › pod ${esc(L.pod_id)} › slot ${esc(String(+L.pod_slot_num))}` : "Location not known yet"}</div><div id="loc" style="max-width:420px"></div></div>
    <div class="part"><div class="k">What to do</div><div id="todo"></div></div>
    <div class="part"><div class="k">What happened</div><ul class="happened" id="happened"></ul></div>
    <div class="part"><details class="how"><summary>How we decided ${icon("chevron")}</summary><div style="margin-top:14px">
      ${sc && sc.found && sc.own ? `<p class="muted" style="margin:0 0 6px">${esc(sc.tenant || "Your fleet")} alone has ${fmt(sc.own.n)} drives like this (${fmt(sc.own.died)} failed)${sc.own.enough ? "" : ", too few to decide"}. Across ${fmt(sc.tenants_contributing)} customers there are ${fmt(sc.network.n)} (${fmt(sc.network.died)} failed).</p>` : ""}
      <svg class="chart" id="smart" viewBox="0 0 900 240" height="200" role="img" aria-label="SMART readings over time"></svg><div class="legend" id="legend"></div>
      <p style="margin:12px 0 0"><a class="btn secondary sm" href="/app/graph?${gq}">${icon("layers")}See how we decided</a></p></div></details></div></div>`;
  const tabs = {ct: () => commsInto($("#tab-ct"), {serial}), hw: () => reasoningInto($("#tab-hw"), gq, p),
    mg: () => { $("#tab-mg").innerHTML = `<iframe src="/app/graph?${gq}&embed=1" title="Memory graph" style="width:100%;height:620px;border:1px solid var(--line);border-radius:12px;background:var(--surface)"></iframe>`; }};
  const loaded = {};
  $$("#sTabs button").forEach(b => b.onclick = () => {
    pressOne($$("#sTabs button"), b);
    ["ov", "ct", "hw", "mg"].forEach(k => $("#tab-" + k).hidden = k !== b.dataset.t);
    $("#tabLine").textContent = {ov: "What's wrong, where it is, and what to do.", ct: "Every call and text about this drive, with the full transcript.",
      hw: "The reasoning, step by step, and which system did each step.", mg: "Everything Precedent remembers about this drive, as a graph."}[b.dataset.t];
    if (tabs[b.dataset.t] && (!loaded[b.dataset.t] || b.dataset.t === "ct")) { loaded[b.dataset.t] = true; tabs[b.dataset.t](); }
  });
  // what to do
  const todo = $("#todo");
  if (alert && !dec && !resolved) {
    todo.innerHTML = `<div class="row"><button class="btn lg" data-d="swap">Replace</button><button class="btn secondary lg" data-d="wait">Wait</button></div>`;
    $$("[data-d]", todo).forEach(b => b.onclick = async () => { b.disabled = true; if (await decide(alert.alert_id, b.dataset.d)) route(); else b.disabled = false; });
  } else if (alert && dec && !resolved) {
    todo.innerHTML = `<form id="resolve" autocomplete="off" class="row" style="flex-wrap:wrap"><input class="field" id="rNote" placeholder="What did you do? e.g. Reseated the SATA cable, errors stopped" style="flex:1;min-width:260px;height:38px" aria-label="What did you do?"><button class="btn">Log what you did</button></form>
      <div class="faint" style="font-size:13px;margin-top:6px">Precedent will suggest this next time the same warning appears.</div>`;
    $("#resolve").onsubmit = async e => {
      e.preventDefault(); const note = $("#rNote").value.trim(); if (!note) return $("#rNote").focus();
      const r = await post(`/api/incidents/${encodeURIComponent(alert.alert_id)}/resolve`, {action: guessAction(note), note, by: PEOPLE.tech});
      if (!r || r.__status) return toast("Couldn't save that", "alert");
      toast("Saved. Precedent will suggest it next time.", "check"); route();
    };
  } else todo.innerHTML = `<div class="muted">${resolved ? "Nothing to do. The fix is logged." : p.failed_on ? "Nothing to do. The drive has already failed and was replaced." : "Nothing to do. Precedent will tell you if this changes."}</div>`;
  if (fix && alert && !resolved) todo.insertAdjacentHTML("beforeend", `<div class="muted" style="margin-top:12px">Last time: ${esc(fix.by || "an engineer")} ${esc(lcFirst(fix.steps_text || "logged a fix")).replace(/\.$/, "")}. <button class="linkbtn" id="applyFix">Apply that fix</button></div>`);
  if ($("#applyFix")) $("#applyFix").onclick = async () => { const r = await post(`/api/incidents/${encodeURIComponent(alert.alert_id)}/apply-playbook`, {by: PEOPLE.tech});
    toast(!r || r.__status ? "Couldn't start the fix" : "Rehearsing the fix in Sparta, then an agent carries it out", !r || r.__status ? "alert" : "wrench"); };
  // what happened: newest first, plain sentences
  let rows = ((story && story.rows) || []).slice();
  const li = r => `<li class="${/warning|failed|decision/.test(r.kind || r.type || "") ? "big" : ""}"><time>${whenLabel(r.ts)}</time><span>${esc(r.s)}</span></li>`;
  const paint = () => {
    const items = rows.map(r => ({...r, s: happenedText(r)})).filter(r => r.s).sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
    const shown = items.slice(0, 14);
    $("#happened").innerHTML = shown.map(li).join("") +
      (items.length > shown.length ? `<li><time></time><button class="linkbtn" id="allH">Show all ${fmt(items.length)}</button></li>` : "")
      || `<li><time></time><span class="faint">${story ? "Nothing yet." : loadError("this drive's history", storyUrl)}</span></li>`;
    if ($("#allH")) $("#allH").onclick = () => { $("#happened").innerHTML = items.map(li).join(""); };
  };
  paint();
  drawSmart($("#smart"), $("#legend"), p.smart_history || [], p.warnings || [], p.failed_on);
  onEvent(ev => { if (ev.serial !== serial || ["telemetry_received", "transcript_turn"].includes(ev.type)) return;
    rows.push({ts: ev.ts || new Date().toISOString(), kind: ev.type, text: ev.text || feedSentence(ev)}); paint();
    if (["decision", "incident_resolved", "incident_opened", "alert_created"].includes(ev.type)) setTimeout(() => { if (gen === routeGen) route(); }, 600); });
  if (L.datacenter) {
    const pod = await api(`/api/fleet/map?datacenter=${encodeURIComponent(L.datacenter)}&vault_id=${encodeURIComponent(L.vault_id)}&pod_id=${encodeURIComponent(L.pod_id)}`);
    const slots = (pod && pod.slots) || [];
    if (gen === routeGen && slots.length) $("#loc").innerHTML = `<div class="slots" style="grid-template-columns:repeat(12,minmax(0,1fr))">${slots.map(x => { const me = x.serial === p.serial;
      return `<a class="slot ${esc(x.status)} ${me ? "me" : ""}" href="/app/drives/${encodeURIComponent(x.serial)}" title="Slot ${+x.slot} · ${esc(x.serial)}"><span style="background:${me ? "var(--accent)" : x.status === "failed" ? "var(--danger)" : x.status === "warned" ? "var(--warn)" : "transparent"}"></span></a>`; }).join("")}</div>
      <div class="legend"><span><span class="dot" style="background:var(--accent)"></span>This drive</span><span><span class="dot warn"></span>Warning</span><span><span class="dot danger"></span>Failed</span></div>`;
  }
}

// Drives map: datacenter -> vaults -> pod health tiles -> slot grid
async function pageDrivesMap(q) {
  crumbs([["Drives", "/app/drives"], ["Map"]]);
  view().innerHTML = `<div class="tabs" style="margin-bottom:18px"><a href="/app/drives">List</a><a class="on" href="/app/drives?view=map" aria-current="page">Map</a></div>
    ${purpose("drives", "Find any drive, where it sits, and how likely it is to fail.")}<h1 class="hello">Where the trouble is</h1><p class="sub2">Pick a datacenter, then a pod. Red pods have failed drives, amber pods have warnings.</p>
    <div class="row" id="dcChips" style="flex-wrap:wrap;gap:6px;margin-bottom:18px"></div>
    <div class="twocol" style="margin-top:0;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr)"><section class="panel"><div id="vaults"><div class="skel"></div></div></section>
      <section class="panel"><h2 id="podH">Choose a pod</h2><div id="podGrid" class="faint" style="font-size:14px">Click a pod tile to see its drives, slot by slot.</div></section></div>`;
  const fleet = await api("/api/fleet/map"), dcs = (fleet && fleet.datacenters) || [];
  let dc = q.get("dc") || (dcs[0] && dcs[0].datacenter);
  if (!$("#vaults")) return;
  if (!dc) { $("#vaults").innerHTML = `<p class="faint" style="margin:0">${fleet ? "No datacenters reporting yet." : loadError("the fleet map", "/api/fleet/map")}</p>`; return; }
  const chips = () => { $("#dcChips").innerHTML = dcs.map(d => `<button class="btn ${d.datacenter === dc ? "" : "secondary"} sm" data-dc="${esc(d.datacenter)}">${esc(d.datacenter)}${d.tenant ? ` · ${esc(d.tenant)}` : ""}</button>`).join("");
    $$("#dcChips [data-dc]").forEach(b => b.onclick = () => { dc = b.dataset.dc; chips(); vaults(); }); };
  const pod = async (v, pId) => {
    $$(".podtile").forEach(t => t.classList.toggle("on", t.dataset.v === v && t.dataset.p === pId));
    $("#podH").textContent = `${dc} › vault ${v} › pod ${pId}`; $("#podGrid").innerHTML = `<div class="skel"></div>`;
    const out = await api(`/api/fleet/map?datacenter=${encodeURIComponent(dc)}&vault_id=${encodeURIComponent(v)}&pod_id=${encodeURIComponent(pId)}`);
    const slots = (out && out.slots) || [];
    $("#podGrid").classList.remove("faint");
    $("#podGrid").innerHTML = `<div class="slots" style="grid-template-columns:repeat(10,minmax(0,1fr))">${slots.map(x =>
      `<a class="slot ${esc(x.status)}" href="/app/drives/${encodeURIComponent(x.serial)}" title="Slot ${+x.slot} · ${esc(x.serial)} · ${esc(x.status)}"><span style="background:${x.status === "failed" ? "var(--danger)" : x.status === "warned" ? "var(--warn)" : "transparent"}"></span></a>`).join("")}</div>
      <div class="legend"><span><span class="dot danger"></span>Failed</span><span><span class="dot warn"></span>Warning</span><span><span class="dot off"></span>Healthy</span></div>`;
  };
  const vaults = async () => {
    $("#vaults").innerHTML = `<div class="skel"></div>`;
    const out = await api(`/api/fleet/map?datacenter=${encodeURIComponent(dc)}`), pods = (out && out.pods) || [], byV = {};
    pods.forEach(x => (byV[x.vault_id] ||= []).push(x));
    const order = Object.entries(byV).sort((a, b) => b[1].reduce((s2, x) => s2 + x.failed * 3 + x.warned, 0) - a[1].reduce((s2, x) => s2 + x.failed * 3 + x.warned, 0));
    $("#vaults").innerHTML = order.slice(0, 12).map(([v, list]) => `<div class="vault"><div class="k">Vault ${esc(v)} · ${fmt(list.reduce((a, x) => a + x.drives, 0))} drives</div><div class="podtiles">${
      list.sort((a, b) => String(a.pod_id).localeCompare(String(b.pod_id))).map(x => `<button class="podtile ${x.failed >= 3 ? "h2" : x.failed || x.warned >= 3 ? "h1" : ""}" data-v="${esc(v)}" data-p="${esc(x.pod_id)}" title="${fmt(x.drives)} drives">
        <b>Pod ${esc(x.pod_id)}</b><span style="color:var(--danger)">${fmt(x.failed)}</span> · <span style="color:var(--warn-ink)">${fmt(x.warned)}</span></button>`).join("")}</div></div>`).join("") +
      (order.length > 12 ? `<p class="faint" style="font-size:13px;margin:4px 0 0">Showing the 12 vaults with the most trouble of ${order.length}.</p>` : "");
    $$("#vaults .podtile").forEach(b => b.onclick = () => pod(b.dataset.v, b.dataset.p));
    const first = $("#vaults .podtile.h2") || $("#vaults .podtile.h1"); if (first) pod(first.dataset.v, first.dataset.p);
  };
  chips(); vaults();
}

const nm =(name, num) => String(name || "").replace(/\s*\(Agent [AB]\)/, "") || (num ? nameFor(num) : "");
function commHTML(c, openAll) {
  c = {...c, from: nm(c.from_name, c.from) || c.from, to: nm(c.to_name, c.to) || c.to};
  if (typeof c.transcript === "string" && /^\s*\[/.test(c.transcript)) { try { c.transcript = JSON.parse(c.transcript); } catch (e) {} }
  if (Array.isArray(c.transcript)) { c.turns = c.transcript.map(t => ({role: /agent|assistant|precedent/i.test(t.role || t.speaker || "") ? "Precedent" : (c.to || "On-call"), text: t.text || t.content || ""})); c.transcript = ""; }
  const hms = t => new Date(t).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
  if (c.kind === "call") {
    const turns = (c.turns && c.turns.length ? c.turns : parseTranscript(c.transcript)).filter(t => t.text);
    const st = String(c.state || "placed").replace(/dry.?run/i, "practice run").replace(/[_-]/g, " ");
    return `<div class="comm"><div class="meta"><time>${hms(c.ts)}</time><span class="ic">${icon("phone")}</span><b>${esc(c.from || "Precedent")} → ${esc(c.to || PEOPLE.oncall)}</b>
      <span class="faint">Call${+c.duration_s > 0 ? ` · ${fmt(+c.duration_s)} s` : ""} · ${esc(st)}</span>${c.serial ? `<a class="mono faint" style="text-decoration:none;font-size:12.5px" href="/app/drives/${encodeURIComponent(c.serial)}">${esc(c.serial)}</a>` : ""}</div>
      ${turns.length ? `<details ${openAll ? "open" : ""} style="margin-top:6px"><summary class="faint" style="cursor:pointer;font-size:13px">Transcript (${turns.length} turns)</summary><div class="convo">${turns.map(t =>
        `<div class="bub ${/precedent|agent/i.test(t.role) ? "p" : "h"}"><span class="faint" style="font-size:11.5px;display:block;color:inherit;opacity:.75">${esc(t.role)}</span>${esc(t.text)}</div>`).join("")}</div></details>` : ""}</div>`;
  }
  const sum = /PRECEDENT SUMMARY|^Summary for drive/i.test(c.body || ""), st = String(c.delivery || c.status || "delivered").replace(/^practice$/, "practice run");
  return `<div class="comm"><div class="meta"><time>${hms(c.ts)}</time><span class="ic">${icon("text")}</span><b>${esc(c.from)} → ${esc(c.to)}</b><span class="faint">Text · ${esc(st)}${c.error && c.error !== "None" ? ` · ${esc(c.error)}` : ""}</span>
      ${c.serial ? `<a class="mono faint" style="text-decoration:none;font-size:12.5px" href="/app/drives/${encodeURIComponent(c.serial)}">${esc(c.serial)}</a>` : ""}</div>
    <details ${openAll && !sum ? "open" : ""} style="margin-top:6px"><summary class="faint" style="cursor:pointer;font-size:13px">${sum ? "Full summary" : "Message"}</summary>
      <div class="convo"><div class="bub ${/^Precedent/.test(c.from) ? "p" : "h"}">${sum ? summaryCard(c.body) : esc(c.body)}</div></div></details></div>`;
}
async function commsInto(el, {serial} = {}) {
  if (!el) return;
  if (!el.children.length) el.innerHTML = `<div class="skel" style="margin-top:12px"></div>`;
  const out = await api(`/api/comms?limit=200${serial ? `&serial=${encodeURIComponent(serial)}` : ""}`);
  if (!out) { el.innerHTML = `<p class="muted" style="margin-top:14px">${loadError("calls and texts")}</p>`; return; }
  const rows = dedupeTexts(out.rows || []).sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  let lastDay = "";
  el.innerHTML = rows.length ? `<div>${rows.map(c => { const d = dayName(c.ts), sep = d !== lastDay ? `<div class="daysep">${d}</div>` : ""; lastDay = d; return sep + commHTML(c, !!serial); }).join("")}</div>` : `<p class="muted" style="margin-top:14px">No calls or texts${serial ? " about this drive" : ""} yet. When Precedent calls or texts someone, the conversation appears here.</p>`;
}
function pageComms() {
  crumbs([["Calls & texts"]]);
  view().innerHTML = purpose("comms", "Every call and text Precedent made through Dial, and every reply.") + `<h1 class="hello">Calls &amp; texts</h1><p class="sub2">Every call and text Precedent made or received, newest first. Open a line to read it.</p>
    <section class="card" style="padding:4px 20px" id="cmList"></section>`;
  let pend = null;
  onEvent(ev => { if (/message_|call_state|transcript_turn|alert_created/.test(ev.type)) { clearTimeout(pend); pend = setTimeout(() => commsInto($("#cmList")), 400); } });
  every(() => commsInto($("#cmList")), 8000);
}
async function reasoningInto(el, gq, p) {
  el.innerHTML = `<div class="skel" style="margin-top:12px"></div>`;
  const g = await api(`/api/graph?${gq}`);
  if (!g) { el.innerHTML = `<p class="muted">${loadError("the reasoning")}</p>`; return; }
  const nodes = g.nodes || [], by = t => nodes.filter(n => n.type === t);
  const SYS = {pattern: "SMART reading", precedent: "Precedent", network: "Precedent network", keewano: "Keewano", alert: "Dial", call: "Dial", decision: "Dial", action: "", channels: "Slack", playbook: "Precedent"};
  const order = ["pattern", "precedent", "network", "keewano", "playbook", "alert", "call", "decision", "action", "channels"];
  const steps = order.flatMap(t => by(t)).map(n => `<li><div><div class="sys">${esc(n.type === "action" ? n.label : SYS[n.type] || cap(n.type))}</div><b>${esc(n.label)}</b><p style="margin:4px 0 0;color:var(--ink-2)">${esc(human(n.summary).replace(/\b\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?/g, m => whenLabel(m)).replace(/\bon (\d{4}-\d{2}-\d{2})\b/g, (m, d) => `on ${dayLabel(d)}`).replace(/showed it at (Today|Yesterday) (.+?)\./g, (m, d, t) => `showed it ${d.toLowerCase()} at ${t}.`).replace(/\bat (Today|Yesterday)/g, "$1"))}</p></div></li>`);
  el.innerHTML = (steps.length ? `<ol class="steps" style="margin-top:8px">${steps.join("")}</ol>` : `<p class="muted">No reasoning trail yet.</p>`) +
    `<div class="part"><div class="k">SMART readings</div><svg class="chart" viewBox="0 0 900 240" height="200" role="img" aria-label="SMART readings over time"></svg></div>`;
  drawSmart($("svg.chart", el), null, p.smart_history || [], p.warnings || [], p.failed_on);
}

function pageSystems() {
  crumbs([["Systems"]]);
  view().innerHTML = purpose("systems", "What each partner did today: Dial calls and texts, Keewano stores and predicts, Sparta rehearses fixes, Darwin finds agents and parts.") + `<h1 class="hello">Systems</h1><p class="sub2">The services Precedent works through, and what each did today.</p><div class="syscards" id="sys"><div class="syscard"><div class="skel"></div></div></div>
    <p style="margin-top:22px"><a class="auto" href="/app/integrations?full=1" style="margin:0">Notification channels, the morning digest and how to connect another agent →</a></p>`;
  const load = async () => {
    const out = await api("/api/systems");  // [{name, status, today: {counts}, summary, last: {ts, text}}]
    if (!$("#sys")) return;
    if (!Array.isArray(out)) { $("#sys").innerHTML = `<p class="muted">${loadError("system status", "/api/systems")}</p>`; return; }
    const dot = st => st === "ok" ? "ok" : st === "degraded" ? "warn" : "off";
    const role = name => (SERVICES.find(s => s[1] === name) || [])[2] || (CHANNELS[String(name).toLowerCase()] || [])[1] || "";
    $("#sys").innerHTML = out.map(x => `<div class="syscard"><h3><span class="dot ${dot(x.status)}" title="${esc(x.status || "")}"></span>${esc(x.name)}</h3>
      <div class="did">${esc(x.summary || "")}</div><div class="what">${esc(role(x.name))}</div>
      ${x.last && x.last.text ? `<div class="last" style="margin-top:8px">Last: ${esc(human(x.last.text))} <span class="tnum">${esc(whenLabel(x.last.ts))}</span></div>` : ""}</div>`).join("")
      || `<p class="muted">No system has reported yet.</p>`;
  };
  every(load, 10000);
  onEvent(ev => { if (/message_|call_state|keewano|sparta|action_|notification/.test(ev.type)) load(); });
}

function activitySentence(e) {
  const t = e.type, s = e.serial || "", v = verdictKey(e.verdict), txt = String(e.text || "");
  if (t === "warning_triaged") return v === "harmless" ? `Checked a warning on ${s}: harmless${e.n ? `, ${e.died} of ${e.n} drives like it failed` : ""}.`
    : v === "swaplist" ? `Checked a warning on ${s}: added to tomorrow's swap list${e.n ? `, ${e.died} of ${e.n} drives like it failed` : ""}.`
    : v === "urgent" ? `Checked a warning on ${s}: needs a person${e.n ? `, ${e.died} of ${e.n} drives like it failed` : ""}.`
    : `Checked a warning on ${s}: a new kind of warning, kept for review.`;
  if (t === "drive_failed") return `Drive ${s} failed.${/no warning/i.test(txt) ? " It never warned." : ""}`;
  if (t === "alert_created" || (t === "incident_state" && /^Calling/i.test(txt))) return `Called ${say(PEOPLE.oncall)} about drive ${s}.`;
  if (t === "incident_opened") return `Opened an incident for drive ${s}.`;
  if (t === "decision") return `${cap(say(e.by || PEOPLE.oncall))} said ${e.choice === "swap" ? "replace" : e.choice === "wait" ? "wait" : e.choice || "something unclear"}.`;
  if (t === "incident_resolved") return `${cap(say(e.by || PEOPLE.tech))} fixed drive ${s}${e.note ? `: ${e.note}` : ""}.`;
  if (t === "message_sent") return /SUMMARY/i.test(e.body || txt) ? `Sent the full details to ${say(PEOPLE.tech)}.` : /Logged:/i.test(e.body || txt) ? `Confirmed the decision with ${say(PEOPLE.oncall)}.` : `Texted ${say(PEOPLE.tech)}.`;
  if (t === "message_received") return `${cap(say(nameFor(e.from || "")))} replied.`;
  if (t === "sparta_verified") return e.ok === false ? "Rehearsed the fix in Sparta: it failed, so nothing was changed." : "Rehearsed the fix in Sparta: it worked.";
  if (t === "action_result") return human(txt).replace(/^(\w+): would /, (m, a) => `${a} would `) || `${cap(e.sponsor)} finished.`;
  if (t === "playbook_suggested") return `Suggested last time's fix for drive ${s}.`;
  if (t === "call_state") return /end|complete/i.test(e.state || txt) ? "The call ended." : "";
  return "";
}
function pageActivity(q) {
  crumbs([["Activity"]]);
  view().innerHTML = purpose("activity", "Every check, call, text and fix, as it happens.") + `<h1 class="hello">What Precedent has been doing</h1><p class="sub2">Every check, call and fix, newest first. Click a line for the technical detail.</p>
    <div class="row" style="margin-bottom:12px;flex-wrap:wrap"><input class="field" id="aQ" placeholder="Search a drive or a word" style="flex:1;min-width:220px" aria-label="Search">
      <select class="field" id="aF" aria-label="Show"><option value="all">Everything</option><option value="person">Needs a person</option><option value="fail">Failures</option><option value="harmless">Harmless checks</option></select></div>
    <section class="card" style="overflow:hidden"><ul class="act-list" id="aRows"><li><span></span><span></span><div class="skel"></div></li></ul>
      <div style="padding:12px;text-align:center"><button class="btn ghost sm" id="aMore">Show older</button></div></section>
    <aside class="sidedrawer" id="aDrawer" aria-label="Technical detail"></aside>`;
  let rows = [], filt = q.get("f") || "all", query = "", open = new Set(), before = 0, fresh = new Set(), failed = false;
  $("#aF").value = filt;
  const KIND_ICON = e => e.type === "drive_failed" ? ["alert", "bad"] : e.type === "warning_triaged" ? (verdictKey(e.verdict) === "harmless" ? ["check", ""] : ["alert", "nd"])
    : e.type === "decision" || e.type === "incident_resolved" ? ["check", "ok"] : /message/.test(e.type) ? ["text", ""] : /alert|call|incident/.test(e.type) ? ["phone", "nd"] : ["activity", ""];
  const isPerson = e => /alert_created|incident_opened|decision|incident_resolved|message|call_state/.test(e.type) || (e.type === "warning_triaged" && verdictKey(e.verdict) === "urgent");
  const keep = e => { const s = activitySentence(e); if (!s) return false;
    if (filt === "person" && !isPerson(e)) return false; if (filt === "fail" && e.type !== "drive_failed") return false;
    if (filt === "harmless" && !(e.type === "warning_triaged" && verdictKey(e.verdict) === "harmless")) return false;
    return !query || (s + " " + (e.serial || "")).toLowerCase().includes(query); };
  const hms = t => { const d = new Date(t); return isNaN(d) ? "" : d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false}); };
  const li = (e, i) => { const [ic, tone] = KIND_ICON(e);
    return `<li data-i="${i}" tabindex="0" class="${fresh.has(e.id) ? "new" : ""}"><time>${hms(e.ts)}</time><span class="ic ${tone}">${icon(ic)}</span><span>${esc(activitySentence(e))}</span>
      ${e.serial ? `<a class="s" href="/app/drives/${encodeURIComponent(e.serial)}">${esc(e.serial)}</a>` : "<span></span>"}</li>`; };
  const paint = () => {
    const shown = rows.filter(keep), harm = e => e.type === "warning_triaged" && verdictKey(e.verdict) === "harmless";
    const byMin = {};  // all harmless checks of one minute become ONE expandable row, placed where the minute's first one was
    if (filt !== "harmless") shown.forEach(e => { if (harm(e)) (byMin[String(e.ts).slice(0, 16)] ||= []).push(e); });
    let html = ""; const done = new Set(); let lastDay = "";
    for (const e of shown) {
      const dn = dayName(e.ts); if (dn && dn !== lastDay) { html += `<li class="daysep" style="cursor:default"><span></span><span></span><span>${dn}</span><span></span></li>`; lastDay = dn; }
      const m = String(e.ts).slice(0, 16), grp = byMin[m];
      if (harm(e) && grp && grp.length >= 2) {
        if (done.has(m)) continue; done.add(m);
        const isOpen = open.has(m);
        html += `<li class="grp" data-grp="${esc(m)}" tabindex="0"><time>${hms(e.ts).slice(0, 5)}</time><span class="ic">${icon("check")}</span><span>${fmt(grp.length)} harmless checks ${isOpen ? "(hide)" : "(show)"}</span><span></span></li>` +
          (isOpen ? grp.map(x => li(x, rows.indexOf(x))).join("") : "");
      } else html += li(e, rows.indexOf(e));
    }
    $("#aRows").innerHTML = html || `<li><span></span><span></span><span class="faint">${failed ? loadError("activity") : "Nothing here yet. Precedent writes a line here every time it checks a drive."}</span></li>`;
    fresh.clear();
    $$("#aRows li[data-i]").forEach(el => onActivate(el, e => { if (!e.target.closest("a")) drawer(rows[+el.dataset.i], el); }));
    $$("#aRows li[data-grp]").forEach(el => onActivate(el, () => { const k = el.dataset.grp; open.has(k) ? open.delete(k) : open.add(k); paint(); }));
  };
  const drawer = (e, opener) => { const d = $("#aDrawer"), close = () => { d.classList.remove("on"); if (opener.isConnected) opener.focus(); }; d.classList.add("on");
    d.innerHTML = `<div class="row"><b>Technical detail</b><span class="spacer"></span><button class="btn ghost sm" id="aClose" aria-label="Close">${icon("x")}</button></div>
      <p style="margin:12px 0 4px">${esc(activitySentence(e))}</p><div class="faint tnum" style="font-size:12.5px;margin-bottom:12px">${new Date(e.ts).toLocaleString()}.${String(new Date(e.ts).getMilliseconds()).padStart(3, "0")}</div>
      <pre class="raw">${esc(JSON.stringify(e, null, 2))}</pre>`;
    $("#aClose").onclick = close; d.onkeydown = ev => { if (ev.key === "Escape") close(); }; $("#aClose").focus(); };
  const load = async more => {
    const out = await api(`/api/logs?limit=400${more && before ? `&before_id=${before}` : ""}`) || await api("/api/feed?limit=400");
    failed = !out; if (!$("#aRows")) return;
    const got = (out && (out.rows || out)) || [];
    rows = more ? rows.concat(got) : got; before = Math.min(...rows.map(r => +r.id).filter(Boolean), Infinity); if (!isFinite(before)) before = 0; paint();
  };
  $("#aF").onchange = e => { filt = e.target.value; paint(); };
  let t; $("#aQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { query = e.target.value.trim().toLowerCase(); paint(); }, 150); };
  $("#aMore").onclick = () => load(true);
  onEvent(ev => { const e = {...ev, ts: ev.ts || new Date().toISOString(), id: ev.id || Date.now()}; if (!activitySentence(e)) return; fresh.add(e.id); rows.unshift(e); if (rows.length > 3000) rows.length = 3000; paint(); });
  every(() => load(false), 6000);
}

function pageDrivesSimple(q) {
  crumbs([["Drives"]]);
  const TABS = [["urgent", "Needs you"], ["warning", "Watching"], ["failed", "Failed"], ["", "All"]];
  if (q.get("view") === "map") return pageDrivesMap(q);
  view().innerHTML = `<div class="tabs" style="margin-bottom:18px"><a class="on" href="/app/drives" aria-current="page">List</a><a href="/app/drives?view=map">Map</a></div>
    ${purpose("drives", "Find any drive, where it sits, and how likely it is to fail.")}<h1 class="hello">Find any drive</h1><p class="sub2">Search by serial or model. Drives that need you come first.</p>
    <input class="field" id="dQ" placeholder="Search a serial or model" style="width:100%;height:42px;font-size:15px;margin-bottom:14px" aria-label="Search drives">
    <div class="tabs" id="dTabs">${TABS.map(([k, n], i) => `<button data-s="${k}" class="${i ? "" : "on"}" aria-pressed="${!i}">${n}</button>`).join("")}</div>
    <div class="tscroll"><table><thead><tr><th>Drive</th><th>Where</th><th>Status</th><th>What's wrong</th><th class="r">Updated</th></tr></thead><tbody id="dRows"><tr><td colspan="5"><div class="skel"></div></td></tr></tbody></table></div>
    <div class="row" style="padding:12px 0"><span class="faint tnum" id="dPage"></span><span class="spacer"></span><button class="btn secondary sm" id="dPrev">Previous</button><button class="btn secondary sm" id="dNext">Next</button></div>`;
  const F = {status: "urgent", q: "", offset: 0, limit: 25};
  let rows = [], total = 0, failed = "";
  const PILL = {urgent: `<span class="pill warn"><i></i>Needs you</span>`, warning: `<span class="pill"><i></i>Watching</span>`, failed: `<span class="pill danger"><i></i>Failed</span>`, healthy: `<span class="pill ok"><i></i>Healthy</span>`};
  const paint = () => {
    $("#dRows").innerHTML = rows.length ? rows.map(r => { const slot = r.slot || r.pod_slot_num, upd = r.last_event_ts || r.failed_on || r.last_warn_date || r.warn_date;
      return `<tr class="click ${r._flash ? "flash" : ""}" tabindex="0" data-s="${esc(r.serial)}"><td class="mono">${esc(r.serial)}</td>
        <td class="faint" style="white-space:nowrap">${r.datacenter ? `${esc(r.datacenter)} › pod ${esc(r.pod_id)} › slot ${esc(String(+slot))}` : "–"}</td><td>${PILL[r.status] || esc(r.status || "")}</td>
        <td>${r.status === "failed" ? "Failed" : whatsWrong(r.last_pattern || r.pattern)}</td><td class="r faint">${upd ? whenLabel(upd) : "–"}</td></tr>`; }).join("")
      : `<tr><td colspan="5" class="empty">${failed ? loadError("drives", failed) : F.status === "urgent" ? "No drive needs you right now." : "No drives match."}</td></tr>`;
    rows.forEach(r => delete r._flash);
    $$("#dRows tr[data-s]").forEach(tr => onActivate(tr, () => go("/app/drives/" + encodeURIComponent(tr.dataset.s))));
    $("#dPage").textContent = total ? `${fmt(F.offset + 1)}–${fmt(Math.min(total, F.offset + rows.length))} of ${fmt(total)}` : "";
    $("#dPrev").disabled = F.offset === 0; $("#dNext").disabled = F.offset + F.limit >= total;
  };
  const load = async () => {
    const qs = new URLSearchParams({limit: F.limit, offset: F.offset}); if (F.status) qs.set("status", F.status); if (F.q) qs.set("q", F.q);
    const path = `/api/drives?${qs}`, out = await api(path); if (!$("#dRows")) return;
    failed = out ? "" : path; rows = (out && out.rows) || []; total = (out && out.total) || 0; paint();
  };
  $$("#dTabs button").forEach(b => b.onclick = () => { F.status = b.dataset.s; F.offset = 0; pressOne($$("#dTabs button"), b); load(); });
  let t; $("#dQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { F.q = e.target.value.trim(); F.offset = 0; if (F.q) { F.status = ""; pressOne($$("#dTabs button"), $('#dTabs [data-s=""]')); } load(); }, 200); };
  $("#dPrev").onclick = () => { F.offset = Math.max(0, F.offset - F.limit); load(); };
  $("#dNext").onclick = () => { F.offset += F.limit; load(); };
  load();
  let pend = null;
  onEvent(ev => { if (!ev.serial) return; const r = rows.find(x => x.serial === ev.serial);
    if (r) { r._flash = true; r.last_event_ts = ev.ts; if (ev.type === "drive_failed") r.status = "failed"; paint(); }
    else if (["warning_triaged", "drive_failed", "incident_opened"].includes(ev.type) && F.offset === 0) { clearTimeout(pend); pend = setTimeout(load, 800); } });
}

const CHOICE = {swap:"Replace", wait: "Wait", show: "Asked for details", unclear: "No clear answer"};
const STATUS = {open: ["info", "Awaiting decision"], swap: ["accent", "Replace"], wait: ["warn", "Wait"], unclear: ["warn", "Unclear"], show: ["info", "Reviewing"],
  resolved: ["ok", "Resolved"]};
const statusPill = s => { const [c, t] = STATUS[s || "open"] || STATUS.open; return `<span class="pill ${c}"><i></i>${t}</span>`; };
const kwPhrase = d => d && d.keewano_logged === true ? "Stored in Keewano" : d && d.keewano_logged === false ? "Saved locally" : "";
function cleanDetail(d) {  // "Sparta (dry-run): would open ..." -> "Would open ..."; never raw JSON in the main UI
  if (!d || typeof d !== "string") return "";
  return cap(d.replace(/^\s*\w+\s*(\([^)]*\))?\s*:\s*/, "").replace(/\s*\(dry-run\)/gi, ""));
}
function recommend(p) {
  if (!p || !p.n) return {h: "Keep an eye on this drive.", tone: "info"};
  if (p.act) return {h: "Replace this drive.", tone: "accent"};
  if ((p.rate || 0) >= 0.1) return {h: "Add this drive to the morning swap list.", tone: "warn"};
  return {h: "No action needed yet.", tone: "ok"};
}
const evidence = (p, H) => p && p.n ? `<b>${fmt(p.died)} of ${fmt(p.n)}</b> identical drives failed within ${fmt(H || 30)} days.` : "No identical drives with this warning yet.";
async function statusMap() {
  const [decs, call] = await Promise.all([api("/api/decisions?limit=500"), api("/api/call-status")]);
  const st = {};
  for (const d of ((decs && decs.rows) || []).slice().reverse()) st[d.alert_id] = d.choice;
  if (call && call.alert_id && call.decision === "unclear" && !st[call.alert_id]) st[call.alert_id] = "unclear";
  return st;
}
let backtestCache = null;
async function backtest() { return backtestCache || (backtestCache = await api("/api/backtest")); }

const verdictKey = v => { const k = String(v || "").toLowerCase().replace(/[\s-]+/g, "_");
  return k === "quiet" ? "harmless" : k === "watch" ? "swaplist" : k === "act" ? "urgent" : /not_enough|new/.test(k) ? "new_pattern" : k; };
function feedSentence(e) {
  if (e.type === "message_sent" && /SUMMARY/i.test(e.body || e.text || "")) return `Full summary texted to ${say(PEOPLE.tech)} about ${e.serial || "the drive"}.`;
  if (e.type === "message_sent" && /Logged:/i.test(e.body || e.text || "")) return `Confirmation texted to ${say(PEOPLE.oncall)}.`;
  if (e.type === "action_started") return `${cap(e.sponsor || e.channel || "Agent")} running for ${e.serial || "the drive"}…`;
  if (e.text || e.sentence || e.message) return human(e.text || e.sentence || e.message);
  const s = e.serial || (e.alert && e.alert.serial) || "a drive";
  switch (e.type) {
    case "fleet_heartbeat": return `${fmt(e.drives_reporting || e.drives || e.n)} drives reported${e.site || e.datacenter ? ` in ${e.site || e.datacenter}` : ""}; ${fmt(e.warnings || 0)} new warnings.`;
    case "warning_triaged": return `${s} showed ${e.pattern || "a warning"}: ${e.n ? `${fmt(e.died)} of ${fmt(e.n)} identical drives failed` : "no identical history yet"}.`;
    case "alert_created": return `On-call alerted about ${s}.`;
    case "call_state": return `Call about ${s}: ${String(e.state || "").replace(/[_-]/g, " ")}.`;
    case "decision": return `On-call chose ${CHOICE[e.choice] || e.choice} for ${s}.`;
    case "incident_resolved": return `${s} resolved${e.action ? `: ${String(e.action).replace(/_/g, " ")}` : ""}.`;
    case "drive_failed": return `${s} failed.`;
    case "action_result": return `${cap(e.sponsor)}: ${cleanDetail(e.detail) || e.status}.`;
    case "notification": return `${cap(e.channel)} notified${e.ok === false ? " (failed)" : ""}.`;
    default: return cap(String(e.type).replace(/_/g, " "));
  }
}
function pageIncidents() {
  crumbs([["Today", "/app"], ["Incidents"]]);
  view().innerHTML = `<div class="page-head"><div><h1>Incidents</h1><p>Every incident Precedent opened, newest first.</p></div></div>
    <div class="card tscroll"><table><thead><tr><th>Drive</th><th>Model</th><th>Evidence</th><th>Status</th><th class="r">Alerted</th></tr></thead>
      <tbody id="rows"><tr><td colspan="5"><div class="skel"></div></td></tr></tbody></table></div>`;
  const load = async () => {
    const [al, st] = await Promise.all([api("/api/alerts?limit=200&db=1"), statusMap()]);
    if (!$("#rows")) return;
    const rows = (al && al.rows) || [];
    $("#rows").innerHTML = rows.length ? rows.map(a => `
      <tr class="click" tabindex="0" data-id="${esc(a.alert_id)}">
        <td class="mono">${esc(a.serial)}</td><td>${esc(a.model)} <span class="faint mono">${esc(a.pattern)}</span></td>
        <td>${fmt(a.died)} of ${fmt(a.n)} failed</td><td>${st[a.alert_id] ? statusPill(st[a.alert_id]) : a.status && /resolv|verif/.test(a.status) ? statusPill("resolved") : `<span class="pill warn"><i></i>${esc(cap(String(a.status || "Paged").replace(/\s*\(.*\)/, "")))}</span>`}</td><td class="r faint">${tm(a.ts)}</td></tr>`).join("")
      : `<tr><td colspan="5" class="empty">${al ? "No incidents yet. When a warning's history says act, it lands here." : loadError("incidents")}</td></tr>`;
    $$("#rows tr[data-id]").forEach(tr => onActivate(tr, () => go("/app/incidents/" + encodeURIComponent(tr.dataset.id))));
  };
  every(load, 4000);
  onEvent(ev => { if (["alert_created", "decision", "incident_resolved"].includes(ev.type)) load(); });
}

// Verdict card, shared by /incidents/new and /incidents/{id}
function verdictCard({p, H, sc, serial, model, pattern, loc, actionHTML, statusHTML, stepper}) {
  const r = recommend(sc && sc.network ? {...p, ...sc.network} : p);
  const where = loc && loc.datacenter ? `${esc(loc.datacenter)} · pod ${esc(loc.pod_id)} · slot ${esc(String(+loc.pod_slot_num))}` : "";
  return `<section class="card verdict">
    <div>
      <div class="row" style="margin-bottom:8px">${statusHTML || ""}</div>
      <h1 id="vh">${r.h}</h1>
      <p class="lead" id="vlead">${evidence(sc && sc.network ? sc.network : p, H)}</p>
      <div class="meta"><a class="mono" href="/app/drives/${encodeURIComponent(serial)}">${esc(serial)}</a><span>${esc(model)}</span>
        <span class="mono">${esc(pattern)}</span>${where ? `<span>${where}</span>` : ""}</div>
    </div>
    <div class="act">${actionHTML || ""}</div>
    ${sc && sc.own && sc.network ? `<div class="scope"><div class="seg" role="group" aria-label="Whose history">
        <button class="on" data-sc="net" aria-pressed="true">Precedent network</button><button data-sc="own" aria-pressed="false">Your fleet</button></div>
      <span class="txt" id="sctxt"></span></div>` : ""}
    ${stepper ? `<div class="stepper" id="stepper" aria-label="Incident progress"></div>` : ""}
    <details class="why"><summary>Why? How this was decided ${icon("chevron")}</summary><dl class="why-grid" id="why"></dl></details>
  </section>`;
}
const STEPS = ["detected", "triaged", "paged", "acknowledged", "decided", "actioned", "resolved", "verified"];
function renderStepper(state, stamps) {
  const el = $("#stepper"); if (!el) return;
  const cur = STEPS.indexOf(state);
  el.innerHTML = STEPS.map((st, i) => {
    const t = stamps && stamps[st];
    return `<div class="step ${i < cur || (i === cur && i === STEPS.length - 1) ? "done" : i === cur ? "now" : ""}"><i></i><b>${st}</b><small>${t ? tm(typeof t === "number" ? t * (t < 1e12 ? 1000 : 1) : t) : "&nbsp;"}</small></div>`;
  }).join("");
}
function wireVerdict({p, H, sc, pattern, model}) {
  const own = sc && sc.own, net = sc && sc.network, by = (sc && sc.by_tenant) || {};
  const scTxt = k => k === "own"
    ? `<b>${esc(sc.tenant || "Your fleet")}</b> alone: ${fmt(own.n)} identical drives, ${fmt(own.died)} failed. ${own.enough ? (own.act ? "Enough to act." : "Below the bar to act.") : "Not enough history to decide."}`
    : `<b>${fmt(net.n)} drives</b> pooled across ${fmt(sc.tenants_contributing)} customers, ${fmt(net.died)} failed. ${net.act ? "Enough to act." : "Below the bar to act."}`;
  if (own && net) {
    $("#sctxt").innerHTML = scTxt("net");
    $$(".scope .seg button").forEach(b => b.onclick = () => {
      pressOne($$(".scope .seg button"), b);
      $("#sctxt").innerHTML = scTxt(b.dataset.sc);
      const use = b.dataset.sc === "own" ? own : net, r = recommend(use);
      $("#vh").textContent = r.h; $("#vlead").innerHTML = evidence(use, H);
    });
  }
  backtest().then(b => {
    const u = (b && b.urgent) || {}, base = u.N_checks_today ? u.L_failures / u.N_checks_today : null;
    const [attrs, sev] = String(pattern).split(":");
    const NAMES = {5: "reallocated sectors", 187: "reported uncorrectable", 188: "command timeouts", 197: "pending sectors", 198: "offline uncorrectable"};
    const use = net || p || {};
    const rows = [
      ["Warning pattern", `<code>${esc(pattern)}</code>: non-zero ${attrs.split("+").map(a => `SMART ${esc(a)} (${NAMES[a] || "attribute"})`).join(", ")}${sev ? `, severity ${esc(sev)}` : ""}.`],
      ["Identical drives", `Every ${esc(model)} that showed exactly this pattern. This drive is left out of its own history.`],
      ["Outcome window", `A drive counts as failed if it failed within ${fmt(H || 30)} days of its warning. Warnings still inside that window wait until the outcome is known.`],
      ["Result", `${fmt(use.died)} of ${fmt(use.n)} failed (${pct(use.rate)})${base != null ? `, against a ${pct(base, 1)} baseline for all warned drives` : ""}.`],
      own && net ? ["Network pool", `${esc(sc.tenant || "This customer")} has ${fmt(own.n)} identical drives on its own${own.enough ? "" : `, below the minimum of ${fmt(u.min_n || 15)}`}. Pooling ${fmt(sc.tenants_contributing)} customers gives ${fmt(net.n)}: ${(sc.contributors || []).map(t => `${esc(t)} ${by[t] ? fmt(by[t].died) + "/" + fmt(by[t].n) : ""}`).join(", ")}.`] : null,
      ["Rule", `Act when at least ${fmt(u.min_n || 15)} identical drives exist and ${pct(u.min_rate || 0.25)} or more of them failed. On data the rule never saw, ${u.M_checks_precedent ? `${pct(u.K_caught / u.M_checks_precedent)} of the drives it flagged failed` : "see Impact"}.`],
    ].filter(Boolean);
    $("#why") && ($("#why").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join(""));
  });
}

// New warning: the pinned drive, before anyone is alerted
async function pageNew() {
  const gen = routeGen;
  crumbs([["Today", "/app"], ["New warning"]]);
  view().innerHTML = `<div class="card" style="padding:24px"><div class="skel" style="width:50%;height:22px"></div><div class="skel" style="width:30%;margin-top:12px"></div></div>`;
  const d = await api("/api/demo-drive");
  if (gen !== routeGen) return;
  if (!d) { view().innerHTML = `<p class="empty">${loadError("the warned drive", "/api/demo-drive")}</p>`; return; }
  const prof = await api(`/api/drives/${encodeURIComponent(d.serial)}`);
  if (gen !== routeGen) return;
  const loc = prof && prof.location, H = d.horizon_days;
  view().innerHTML = verdictCard({p: d.precedent, H, sc: d.scoped, serial: d.serial, model: d.model, pattern: d.pattern, loc,
      statusHTML: `<span class="pill info"><i></i>Needs a decision</span>`,
      actionHTML: `<button class="btn lg" id="sendBtn">${icon("phone")}Call the on-call</button><span class="faint" style="font-size:12.5px" id="sendSt">Calls first, then texts the technician.</span>`}) + `
    <div class="grid3" style="margin-top:16px">
      <a class="card" href="/app/drives/${encodeURIComponent(d.serial)}"><div class="hd"><h2>Where it is</h2></div><div class="bd" id="sWhere"><div class="skel"></div></div></a>
      <a class="card" href="/app/graph?serial=${encodeURIComponent(d.serial)}"><div class="hd"><h2>Drives like it</h2></div><div class="bd">${(d.similar || []).length ? d.similar.map(x =>
        `<div class="row" style="justify-content:space-between;padding:3px 0"><span class="mono">${esc(x.serial)}</span>${x.died ? `<span class="pill danger">Failed ${dayLabel(x.failed_on)}</span>` : `<span class="pill ok">Survived</span>`}</div>`).join("")
        : `<span class="faint">No known outcomes yet.</span>`}</div></a>
      <a class="card" href="/app/drives/${encodeURIComponent(d.serial)}"><div class="hd"><h2>SMART trend</h2></div><div class="bd"><svg class="chart" id="sTrend" viewBox="0 0 260 70" height="70"></svg><div class="faint tnum" style="font-size:12px" id="sTrendL"></div></div></a>
    </div>`;
  wireVerdict({p: d.precedent, H, sc: d.scoped, pattern: d.pattern, model: d.model});
  $("#sendBtn").onclick = async () => {
    const b = $("#sendBtn"); b.disabled = true; b.innerHTML = `<span class="spin"></span>Calling…`;
    const out = await post("/alerts/send");
    if (!out || out.__status) { b.disabled = false; b.innerHTML = `${icon("phone")}Call the on-call`; $("#sendSt").textContent = errText(out) || "Couldn't place the call."; return toast("Couldn't place the call", "alert"); }
    go("/app/incidents/" + encodeURIComponent(out.alert.alert_id));
  };
  if (loc && loc.datacenter) {
    const pod = await api(`/api/fleet/map?datacenter=${encodeURIComponent(loc.datacenter)}&vault_id=${encodeURIComponent(loc.vault_id)}&pod_id=${encodeURIComponent(loc.pod_id)}`);
    const nb = ((pod && pod.slots) || []).filter(x => x.serial !== d.serial);
    const w = nb.filter(x => x.status === "warned").length, f = nb.filter(x => x.status === "failed").length;
    $("#sWhere") && ($("#sWhere").innerHTML = `<div style="font-weight:600">${esc(loc.datacenter)} › vault ${esc(loc.vault_id)} › pod ${esc(loc.pod_id)} › slot ${esc(String(+loc.pod_slot_num))}</div>
      <div class="muted" style="margin-top:4px">${w} neighbour${w === 1 ? "" : "s"} in this pod also warning${f ? `, ${f} failed` : ""}.</div>`);
  } else $("#sWhere") && ($("#sWhere").innerHTML = `<span class="faint">Location not known yet</span>`);
  const hist = (prof && prof.smart_history) || [];
  if (hist.length && $("#sTrend")) {
    const ks = [["s5", "var(--info)"], ["s197", "var(--warn)"], ["s198", "var(--danger)"]], ly = v => Math.log10(1 + Math.max(0, v || 0));
    const top = Math.max(1, ...hist.flatMap(r => ks.map(([k]) => ly(r[k]))));
    $("#sTrend").innerHTML = ks.map(([k, c]) => `<polyline fill="none" stroke="${c}" stroke-width="1.75" points="${hist.map((r, i) =>
      (i / Math.max(1, hist.length - 1) * 260).toFixed(1) + "," + (66 - ly(r[k]) / top * 62).toFixed(1)).join(" ")}"/>`).join("");
    const last = hist[hist.length - 1];
    $("#sTrendL").textContent = `Latest ${dayLabel(last.date)}: 5 = ${fmt(last.s5)}, 197 = ${fmt(last.s197)}, 198 = ${fmt(last.s198)}`;
  }
}

const CALL_LABEL = s => {
  s = String(s || "").toLowerCase();
  if (!s || /dry|queued|initiat|created|placed/.test(s)) return ["Calling the on-call", true];
  if (/ring/.test(s)) return ["Ringing", true];
  if (/progress|active|answer|connected/.test(s)) return ["On the call", true];
  if (/fail|busy|no.?answer|cancel/.test(s)) return ["No answer", false];
  return ["Call ended", false];
};
const RESOLVE_ACTIONS = [["replaced", "Replaced the drive"], ["reseated", "Reseated the drive"], ["firmware", "Updated firmware"], ["rma", "Sent for RMA"],
  ["no_fault_found", "No fault found"], ["other", "Other"]];
const guessAction = note => /reseat/i.test(note) ? "reseated" : /replac|swap/i.test(note) ? "replaced" : /firmware|update/i.test(note) ? "firmware"
  : /\brma\b|return/i.test(note) ? "rma" : /no fault|nff|nothing wrong/i.test(note) ? "no_fault_found" : "other";
async function pageIncident(id) {
  const gen = routeGen;
  crumbs([["Today", "/app"], ["Incident"]]);
  view().innerHTML = `<div class="card" style="padding:24px"><div class="skel" style="width:50%;height:22px"></div><div class="skel" style="width:30%;margin-top:12px"></div></div>`;
  const inc = await api(`/api/incident/${encodeURIComponent(id)}`);
  if (gen !== routeGen) return;
  if (!inc) { view().innerHTML = `<div class="empty">${loadError("this incident")}</div>`; return; }
  if (!inc.found) { view().innerHTML = `<div class="empty">This incident isn't in the current workspace. It may have been archived.<br><br><a class="btn secondary" href="/app/incidents">Back to incidents</a></div>`; return; }
  const a = inc.alert, H = inc.horizon_days;
  crumbs([["Today", "/app"], ["Incidents", "/app/incidents"], [`<span class="mono">${esc(a.serial)}</span>`]]);
  const [sc, prof] = await Promise.all([
    api(`/api/precedent/scoped?serial=${encodeURIComponent(a.serial)}&model=${encodeURIComponent(a.model)}&pattern=${encodeURIComponent(a.pattern)}`),
    api(`/api/drives/${encodeURIComponent(a.serial)}`)]);
  if (gen !== routeGen) return;
  const scoped = sc && sc.found ? sc : null;
  view().innerHTML = verdictCard({p: inc.precedent || a, H, sc: scoped, serial: a.serial, model: a.model, pattern: a.pattern, loc: prof && prof.location,
      statusHTML: `<span id="stPill">${statusPill(null)}</span><span class="faint" style="font-size:12.5px">Alerted ${tm(a.ts)}</span>`,
      actionHTML: `<div id="primary"></div>`, stepper: true}) + `
    <div class="banner" id="banner"></div>
    <div class="incident-grid">
      <div class="stack">
        <section class="card" id="playbook" hidden></section>
        <section class="card"><div class="hd"><h2>Timeline</h2><span class="sub">Everything that happened, as it happens</span></div><ul class="tl" id="tl"><li><span></span><div class="skel"></div></li></ul></section>
        <section class="card"><div class="hd"><h2>How this warning was handled before</h2></div><div class="bd" id="handling"><div class="skel"></div></div></section>
        <section class="card"><div class="hd"><h2>What did you do?</h2></div><div class="bd">
          <form id="resolve" autocomplete="off" style="display:flex;flex-direction:column;gap:10px">
            <input class="field" id="rNote" placeholder="e.g. Reseated the SATA cable, errors stopped" aria-label="What did you do?" style="height:38px">
            <div class="row" style="flex-wrap:wrap"><select class="field" id="rAction" aria-label="Type of fix (optional)" style="height:32px">
              <option value="">Type of fix (optional)</option>${RESOLVE_ACTIONS.map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select>
              <span class="faint" style="font-size:12.5px;flex:1;min-width:200px">Precedent will suggest this next time the same warning appears.</span>
              <button class="btn">Save</button></div></form>
          <div id="rDone" class="muted" style="margin-top:8px;font-size:13px"></div></div></section>
      </div>
      <div class="stack">
        <section class="card"><div class="hd"><h2>On-call</h2></div><div class="bd"><div id="callBox"></div><div class="transcript" id="tx"></div>
          <div class="row faint" style="font-size:12px;margin-top:10px;flex-wrap:wrap">Backup if the phone fails: <button class="chipbtn" data-sim="1">Replace</button><button class="chipbtn" data-sim="2">Wait</button></div></div></section>
        ${chatCard()}
        <section class="card"><div class="hd"><h2>Actions</h2><span class="sub">After a replace decision</span></div><div class="bd" id="acts"><span class="faint">Nothing has run yet.</span></div></section>
      </div>
    </div>`;
  wireVerdict({p: inc.precedent || a, H, sc: scoped, pattern: a.pattern, model: a.model});
  renderStepper(inc.state || "paged", inc.stamps);
  post(`/api/incidents/${encodeURIComponent(id)}/ack`, {by: PEOPLE.oncall}).then(r => { if (r && r.state) { inc.state = r.state; renderStepper(r.state, inc.stamps); } });
  $$("[data-sim]").forEach(b => b.onclick = async () => {
    const r = await post("/demo/simulate-reply", {choice: b.dataset.sim});
    if (!r || r.__status) toast(r && r.__status === 404 ? "Backup reply isn't available" : "Backup reply failed", "alert"); else refresh();
  });
  $("#resolve").onsubmit = async e => {
    e.preventDefault();
    const btn = $("#resolve button"); btn.disabled = true;
    const note = $("#rNote").value.trim();
    if (!note && !$("#rAction").value) { btn.disabled = false; $("#rNote").focus(); return toast("Describe what you did first", "alert"); }
    const r = await post(`/api/incidents/${encodeURIComponent(id)}/resolve`, {action: $("#rAction").value || guessAction(note), note, by: PEOPLE.tech});
    btn.disabled = false;
    if (!r || r.__status) return toast(r && r.__status === 404 ? "Saving a fix isn't available on this server" : `Not saved: ${errText(r) || "the server didn't answer"}`, "alert");
    $("#rDone").textContent = `Saved${note ? `: “${note}”` : ""}. Precedent will suggest this the next time ${a.model} shows ${a.pattern}.`;
    $("#rNote").value = ""; toast("Incident resolved", "check"); refresh(); loadHandling();
  };
  wireChat(a.ts);
  const loadHandling = async () => {
    const url = `/api/handling?model=${encodeURIComponent(a.model)}&pattern=${encodeURIComponent(a.pattern)}&exclude_serial=${encodeURIComponent(a.serial)}`;
    const h = await api(url), el = $("#handling"); if (!el) return;
    if (!h) { el.innerHTML = `<span class="faint">${loadError("the handling history", url)}</span>`; return; }
    const rows = h.rows || (Array.isArray(h) ? h : []);
    if (!rows.length) { el.innerHTML = `<span class="faint">No earlier warnings like this one yet.</span>`; return; }
    const own = rows.filter(r => /resolution|logged|engineer/i.test(r.source || "") || r.by), fleet = rows.filter(r => !own.includes(r));
    const outcome = r => {
      const o = r.outcome || "", bad = r.died === true || /fail|died/i.test(o);
      return `<span class="pill ${bad ? "danger" : "ok"}">${esc(cap(o) || (bad ? "Failed" : "Still running"))}</span>`;
    };
    const what = r => r.by || r.note || r.action
      ? `${esc(cap(String(r.handled || r.action || "Logged").replace(/_/g, " ")))}${r.by ? ` <span class="faint">by ${esc(r.by)}</span>` : ""}${r.note ? `<small class="faint" style="display:block">“${esc(r.note)}”</small>` : ""}`
      : esc(r.handled || "Kept in service");
    el.innerHTML = (h.exact === false && h.basis ? `<p class="muted" style="margin:0 0 10px">No identical history. Closest precedent: ${esc(h.basis)}.</p>` : "") +
      `<table style="margin:-4px -18px -8px;width:calc(100% + 36px)"><thead><tr><th>When</th><th>Drive</th><th>What happened</th><th>Outcome</th></tr></thead><tbody>` +
      own.concat(fleet).slice(0, 8).map(r => `<tr><td class="faint tnum" style="white-space:nowrap">${dayLabel(r.when || r.ts || r.warn_date)}</td>
        <td>${r.serial ? `<a class="mono" href="/app/drives/${encodeURIComponent(r.serial)}" style="text-decoration:none">${esc(r.serial)}</a>` : "–"}</td>
        <td>${what(r)}</td><td>${outcome(r)}${/fleet/i.test(r.source || "") ? recTag : ""}</td></tr>`).join("") + `</tbody></table>` +
      (fleet.length ? `<p class="faint" style="font-size:12px;margin:14px 0 0">Outcomes of other drives come from the fleet record.</p>` : "");
  };
  loadHandling();

  // Learned playbook: "Last time: Sam reseated the SATA cable · worked 2 of 2 times"
  const PB = {fix: null, run: null};  // run: {sparta: "running"|"ok"|"failed", darwin: "waiting"|"running"|"ok"|"blocked", ticket, checks}
  const pbSteps = () => {
    const r = PB.run; if (!r) return "";
    const st = (state, label, sub) => `<li><span class="ico ${state === "ok" ? "accent" : state === "failed" || state === "blocked" ? "danger" : state === "running" ? "info" : ""}">${
      state === "running" ? `<span class="spin" style="width:12px;height:12px;border-width:2px"></span>` : icon(state === "ok" ? "check" : state === "failed" || state === "blocked" ? "alert" : "activity")}</span>
      <div class="txt">${esc(label)}${sub ? `<small>${esc(sub)}</small>` : ""}</div><time></time></li>`;
    const ver = r.sparta === "ok" ? `Verified${r.ticket ? ` (${/^\d+$/.test(String(r.ticket)) ? "ticket #" + r.ticket : "1 ticket"}${r.checks ? `, ${r.checks}` : ", failure recovered"})` : " (1 ticket, failure recovered)"}` : r.sparta === "failed" ? "Rehearsal failed" : "Verifying…";
    return `<ul class="tl" style="padding:4px 0 0">${st(r.sparta === "running" ? "running" : "ok", "Rehearsing in Sparta", "A safe copy of the ticketing system")}
      ${r.sparta !== "running" ? st(r.sparta === "ok" ? "ok" : "failed", ver, r.sparta === "failed" ? "Nothing was changed in production." : "") : ""}
      ${r.sparta === "failed" ? st("blocked", "Blocked: rehearsal failed", "The fix was not carried out.") : r.sparta === "ok" ? st(r.darwin === "ok" ? "ok" : r.darwin === "blocked" ? "blocked" : "running", r.darwin === "ok" ? "Carried out via Darwin" : r.darwin === "blocked" ? "Blocked: no agent available" : "Handing to an agent via Darwin…", r.darwinText || "") : ""}</ul>`;
  };
  const renderPlaybook = () => {
    const el = $("#playbook"), f = PB.fix; if (!el) return;
    if (!f) { el.hidden = true; return; }
    el.hidden = false;
    const who = f.by || "An engineer", when = f.when ? ` (${dayLabel(f.when)})` : "", worked = f.times_used ? ` · worked ${fmt(f.times_worked ?? f.times_used)} of ${fmt(f.times_used)} time${f.times_used === 1 ? "" : "s"}` : "";
    const steps = String(f.steps_text || f.text || "").trim();
    el.innerHTML = `<div class="hd"><h2>Learned playbook</h2><span class="sub">${esc(f.basis || "From the last time this warning appeared")}</span></div>
      <div class="bd"><div class="row" style="align-items:flex-start;gap:16px;flex-wrap:wrap"><div style="flex:1;min-width:240px">
        <div style="font-size:15px"><b>Last time:</b> ${esc(who)} ${esc(steps.charAt(0).toLowerCase() + steps.slice(1)).replace(/\.$/, "")}${esc(when)}<span class="muted">${worked}</span></div>
        <div class="faint" style="font-size:12.5px;margin-top:4px">How it runs: rehearsed in Sparta first, then carried out by an agent via Darwin.</div></div>
        ${PB.run ? "" : `<button class="btn" id="applyFix">${icon("wrench")}Apply last fix</button>`}</div>${pbSteps()}</div>`;
    const b = $("#applyFix"); if (b) b.onclick = async () => {
      b.disabled = true; b.innerHTML = `<span class="spin"></span>Starting…`;
      const r = await post(`/api/incidents/${encodeURIComponent(id)}/apply-playbook`, {by: PEOPLE.tech});
      if (!r || r.__status) { b.disabled = false; b.innerHTML = `${icon("wrench")}Apply last fix`; return toast(r && r.__status === 404 ? "Applying a fix isn't available on this server" : `Couldn't start: ${errText(r) || "the server didn't answer"}`, "alert"); }
      PB.run = {sparta: "running", darwin: "waiting"}; renderPlaybook(); refresh();
    };
  };
  const loadPlaybook = async () => {
    const d = await api(`/api/incident/${encodeURIComponent(id)}`);  // carries suggested_fix when a playbook exists
    const f = d && d.suggested_fix;
    if (f && !PB.fix) { PB.fix = f; renderPlaybook(); }
  };
  const playbookFromLog = rows => {  // fallback when SSE is down: read the run's progress from the incident log
    if (!PB.run || !rows) return;
    for (const r of rows) {
      const k = r.kind || r.type || "";
      if (k === "sparta_verified") { PB.run.sparta = r.data && r.data.ok === false ? "failed" : "ok"; PB.run.ticket = r.data && r.data.ticket; PB.run.checks = r.data && r.data.checks; }
      if (/^action_result$|darwin_act/.test(k) && /darwin/i.test(r.channel || r.actor || "") && PB.run.sparta === "ok") { PB.run.darwin = /error|fail|gap|blocked/i.test(r.text || "") ? "blocked" : "ok"; PB.run.darwinText = cleanDetail(r.text); }
    }
    renderPlaybook();
  };
  loadPlaybook();

  const S = {inc, call: null, thread: [], log: null, logMode: null, turns: [], seen: null, callSeen: [], lastChoice: undefined};
  const isCall = a.channel === "call" || a.channel === "both";
  const againLabel = `${icon("phone")}${isCall ? "Call again" : "Text again"}`;
  const setPrimary = choice => {
    $("#primary").innerHTML = choice
      ? `<a class="btn secondary" href="/app/graph?alert_id=${encodeURIComponent(id)}">${icon("layers")}Open memory graph</a>`
      : `<button class="btn" id="again">${againLabel}</button>`;
    const b = $("#again"); if (b) b.onclick = async () => {
      b.disabled = true; b.innerHTML = `<span class="spin"></span>${isCall ? "Calling…" : "Texting…"}`;
      const out = await post("/alerts/send", {serial: a.serial, model: a.model, pattern: a.pattern});
      if (!out || out.__status) { b.disabled = false; b.innerHTML = againLabel; return toast(isCall ? "Couldn't place the call" : "Couldn't send the text", "alert"); }
      go("/app/incidents/" + encodeURIComponent(out.alert.alert_id));
    };
  };
  setPrimary(null);
  async function refresh() {
    const [i2, call, th, lg] = await Promise.all([api(`/api/incident/${encodeURIComponent(id)}`), api("/api/call-status"),
      api("/api/tech/thread"), S.logMode === false ? null : api(`/api/incidents/${encodeURIComponent(id)}/log`)]);
    if (!$("#tl")) return;
    if (i2 && i2.found) { S.inc = i2; if (i2.state) renderStepper(i2.state, i2.stamps); if (i2.suggested_fix && !PB.fix) { PB.fix = i2.suggested_fix; renderPlaybook(); } }
    if (lg && Array.isArray(lg.rows)) { S.log = lg.rows; S.logMode = true; playbookFromLog(lg.rows); } else if (S.logMode === null) S.logMode = false;
    if (call && call.alert_id === id) S.call = call;
    if (S.call && S.call.state && !S.callSeen.some(c => c.state === S.call.state)) S.callSeen.push({state: S.call.state, ts: S.call.updated || new Date().toISOString()});
    if (th) S.thread = Array.isArray(th) ? th : th.rows || [];
    render();
  }
  function render() {
    const d = S.inc.decisions[0];
    const choice = d ? d.choice : S.call && S.call.decision === "unclear" ? "unclear" : null;
    $("#stPill").innerHTML = statusPill(S.inc.resolved || S.inc.resolution ? "resolved" : choice);
    if (choice !== S.lastChoice) {
      const b = $("#banner");
      if (choice) {
        b.className = "banner on " + choice;
        const VIA = {web: "from the console", call: "on the call", text: "by text", sms: "by text", slack: "in Slack", api: "via the API"};
        const via = d ? `, by ${say(d.by || PEOPLE.oncall)}${d.via ? ` ${VIA[d.via] || "via " + String(d.via).replace(/_/g, " ")}` : ""}` : "";
        b.innerHTML = icon(choice === "unclear" ? "alert" : "check") + (choice === "unclear"
          ? `<span>No clear answer on the call. The details went to the technician.</span>`
          : `<span>${esc(`Decision: ${CHOICE[choice] || choice}${via}${kwPhrase(d) ? ` · ${kwPhrase(d)}` : ""}`)}</span><span class="spacer"></span><span class="tnum" style="font-weight:400">${tm(d.ts)}</span>`);
      } else b.className = "banner";
      setPrimary(choice);
      S.lastChoice = choice;
    }
    renderCall(); renderActs(); renderTimeline();
  }
  function renderCall() {
    if (!isCall) {
      $("#callBox").innerHTML = `<div class="callbox"><span class="ico">${icon("text")}</span><div><div style="font-weight:600">Text sent to the on-call</div><div class="faint" style="font-size:12.5px">${tm(a.ts)}</div></div></div>`;
      return;
    }
    const d = S.inc.decisions[0];
    let [label, live] = d ? ["Call ended", false] : S.call ? CALL_LABEL(S.call.state) : ["Calling the on-call", true];
    label = label.replace("the on-call", say(PEOPLE.oncall));
    $("#callBox").innerHTML = `<div class="callbox"><span class="ico ${live && !d ? "live" : ""}">${icon("phone")}</span><div><div style="font-weight:600">${esc(label)}</div>
      <div class="faint" style="font-size:12.5px">${esc(cap(PEOPLE.oncall))} · voice call by Dial${S.call && S.call.updated ? ` · ${tm(S.call.updated)}` : ""}</div></div></div>`;
    const turns = S.turns.length ? S.turns : parseTranscript(S.call && S.call.transcript);
    const tx = $("#tx"), prev = tx.childElementCount;
    tx.innerHTML = turns.map(t => `<div class="turn"><b>${esc(t.role)}</b><span>${esc(t.text)}</span></div>`).join("");
    if (turns.length !== prev) tx.scrollTop = tx.scrollHeight;
  }
  function renderActs() {
    const latest = Object.values(Object.fromEntries(S.inc.actions.map(r => [r.sponsor, r])));
    if (!latest.length) return;
    $("#acts").innerHTML = latest.map(r => {
      const failed = /fail|error/i.test(r.status || "");
      const title = {darwin: "Warranty return", sparta: "Remote-hands ticket", slack: "Slack", webhook: "Webhook"}[r.sponsor] || cap(r.sponsor);
      return `<div class="actrow"><span class="ico">${icon(CH_ICON[r.sponsor] || "check")}</span><div><b>${esc(title)}</b> <span class="faint" style="font-size:12.5px">${esc(cap(r.sponsor))}</span>
        <p>${esc(cleanDetail(r.detail) || cap(r.status))}</p>${failed ? `<p style="color:var(--danger)">Failed. It will retry without duplicating.</p>` : ""}</div></div>`;
    }).join("");
  }
  function timelineRows() {
    if (S.logMode && S.log) return tidyLog(S.log);
    const i = S.inc, rows = [], al = i.alert, Pp = i.precedent || al;
    rows.push({ts: al.ts, ch: "server", tone: "warn", text: `Warning matched: ${al.pattern}`, sub: `${fmt(Pp.died)} of ${fmt(Pp.n)} identical ${al.model} drives failed within ${H || 30} days`});
    rows.push({ts: al.ts, ch: isCall ? "call" : "text", text: isCall ? "Calling the on-call" : "Alert texted to the on-call", sub: "Dial"});
    for (const c of S.callSeen) { const [l] = CALL_LABEL(c.state); if (!/^Calling/.test(l)) rows.push({ts: c.ts, ch: "call", text: l, sub: "Dial"}); }
    for (const m of S.thread.filter(m => !al.ts || String(m.ts) >= String(al.ts))) {
      const mine = fromTech(m), body = String(m.body || "").trim(), first = body.split("\n")[0];
      rows.push({ts: m.ts, ch: "text", tone: mine ? "info" : "", text: mine ? `Technician replied “${body.slice(0, 40)}”` : /SUMMARY/i.test(first) ? "Full summary sent to the technician" : "Message to the technician", sub: mine ? "" : first.slice(0, 90)});
    }
    for (const d of i.decisions.slice().reverse()) {
      rows.push({ts: d.ts, ch: d.via && CH_ICON[d.via] ? d.via : isCall ? "call" : "text", tone: "accent", text: `Decision: ${CHOICE[d.choice] || d.choice}`, sub: d.via ? `via ${String(d.via).replace(/_/g, " ")}` : ""});
      if (d.keewano_logged === true) rows.push({ts: d.ts, ch: "keewano", text: "Decision stored in Keewano", sub: "Drive memory updated"});
    }
    for (const r of i.actions) rows.push({ts: r.ts, ch: r.sponsor, tone: /fail|error/i.test(r.status || "") ? "danger" : "", text: `${cap(r.sponsor)}: ${cleanDetail(r.detail) || r.status}`});
    return rows.sort((x, y) => String(x.ts).localeCompare(String(y.ts)));
  }
  function renderTimeline() {
    const rows = timelineRows(), key = r => r.ts + r.ch + r.text;
    const first = S.seen === null; S.seen = S.seen || new Set();
    $("#tl").innerHTML = rows.map(r => `<li class="${!first && !S.seen.has(key(r)) ? "new" : ""}"><span class="ico ${r.tone || ""}">${icon(CH_ICON[r.ch] || "activity")}</span>
        <div class="txt">${esc(r.text)}${r.sub ? `<small>${esc(r.sub)}</small>` : ""}</div><time>${tm(r.ts)}</time></li>`).join("")
      || `<li><span></span><div class="faint">Waiting for the first event…</div></li>`;
    rows.forEach(r => S.seen.add(key(r)));
  }
  onEvent(ev => {
    if (ev.alert_id && ev.alert_id !== id) return;
    if (ev.type === "playbook_suggested" && ev.suggested_fix) { PB.fix = ev.suggested_fix; renderPlaybook(); return; }
    if (ev.type === "sparta_verified" && PB.run) { PB.run.sparta = ev.ok === false ? "failed" : "ok"; PB.run.ticket = ev.ticket; PB.run.checks = ev.checks; if (ev.ok === false) PB.run.darwin = "blocked"; renderPlaybook(); return; }
    if (ev.type === "action_result" && ev.sponsor === "darwin" && PB.run && PB.run.sparta === "ok") { PB.run.darwin = /error|fail|gap/i.test(ev.status || "") ? "blocked" : "ok"; PB.run.darwinText = cleanDetail(ev.detail); renderPlaybook(); }
    if (ev.type === "incident_state" && ev.state) { S.inc.state = ev.state; S.inc.stamps = {...(S.inc.stamps || {}), [ev.state]: ev.ts}; renderStepper(ev.state, S.inc.stamps); refresh(); return; }
    if (ev.type === "transcript_turn") { S.turns.push({role: /agent|assistant|precedent/i.test(ev.role || "") ? "Precedent" : "On-call", text: ev.text || ""}); renderCall(); return; }
    if (ev.type === "call_state" && ev.state) { S.call = {...(S.call || {}), alert_id: id, state: ev.state, updated: ev.ts}; S.callSeen.push({state: ev.state, ts: ev.ts || new Date().toISOString()}); render(); }
    if (["decision", "action_started", "action_result", "message_sent", "message_received", "keewano_logged", "call_state", "notification", "incident_resolved"].includes(ev.type)) refresh();
    if (ev.type === "message_sent" || ev.type === "message_received") pollThread();
  });
  every(refresh, 1500);
}
const RANK = r => { const t = r.text || "", k = r.kind || "";
  return /detected/i.test(t) ? 0 : /^Triaged/i.test(t) ? 1 : k === "alert" ? 2 : /^Calling|^Texting/i.test(t) ? 3 : k === "call_state" ? 4 : k === "message_received" ? 5 : k === "decision" ? 6 : k.startsWith("action") ? 7 : 8; };
function tidyLog(log) {
  const rows = log.slice().sort((a, b) => String(a.ts).localeCompare(String(b.ts)) || RANK(a) - RANK(b));
  const decisions = rows.filter(r => r.kind === "decision"), kwLogged = rows.some(r => r.kind === "keewano" && !/not logged/i.test(r.text || ""));
  const hasTriage = rows.some(r => /^Triaged/i.test(r.text || "")), hasCalling = rows.some(r => /^Calling|^Texting/i.test(r.text || ""));
  const actions = {};  // service -> latest row (started is replaced by its result in place)
  const out = [];
  for (const r of rows) {
    const t = r.text || "", k = r.kind || "";
    if (/^Status:/i.test(t) || / replied$/i.test(t) && k === "state") continue;                   // the stepper shows state
    if (k === "keewano") continue;                                                                  // shown as an icon on the decision row
    if (k === "alert" && hasTriage) continue;                                                       // same fact as the triage row
    if (/incident opened, on-call paged/i.test(t) && hasCalling) continue;                          // same fact as "Calling …"
    if (k === "call_state" && /dry|placed|queued|initiat/i.test(t) && hasCalling) continue;         // "Calling …" already says it
    if (k === "message_received" && decisions.some(d => Math.abs(new Date(d.ts) - new Date(r.ts)) < 15000)) continue;  // one human reply = one row
    if (k.startsWith("action_")) {
      const sp = String(r.channel || r.actor || "").toLowerCase(), prev = actions[sp];
      const row = {ts: r.ts, ch: sp, tone: /error|fail/i.test(t) ? "danger" : "", text: k === "action_started" ? `${cap(sp)} running…` : `${cap(sp)}: ${cleanDetail(t) || "done"}`, sub: actorName(r.actor)};
      if (prev) Object.assign(prev, row, {ts: prev.ts}); else { actions[sp] = row; out.push(row); }
      continue;
    }
    let text = human(t);
    if (!text) continue;
    if (k === "message_sent" && /SUMMARY/i.test(t)) text = `Full summary texted to ${say(PEOPLE.tech)}`;
    else if (k === "message_sent" && /Logged:/i.test(t)) text = `Confirmation texted to ${say(PEOPLE.oncall)}`;
    out.push({ts: r.ts, ch: String(r.channel || "server").toLowerCase(), kind: k,
      tone: k === "decision" ? "accent" : /fail|error/.test(k) ? "danger" : /^Triaged|detected/i.test(t) ? "warn" : "",
      text, sub: k === "decision" && kwLogged ? `${actorName(r.actor)} · stored in Keewano` : actorName(r.actor)});
  }
  return out;
}
function parseTranscript(t) {
  if (!t) return [];
  const parts = String(t).split(/\b(agent|assistant|precedent|user|human|on-?call|caller)\s*:\s*/i).filter(Boolean);
  const turns = [];
  for (let i = 0; i < parts.length; i++) {
    if (/^(agent|assistant|precedent|user|human|on-?call|caller)$/i.test(parts[i]) && parts[i + 1]) {
      turns.push({role: /agent|assistant|precedent/i.test(parts[i]) ? "Precedent" : "On-call", text: parts[i + 1].trim()}); i++;
    }
  }
  return turns.length ? turns : [{role: "Call", text: String(t).trim()}];
}

let techSeen = null, techSince = null;
const digits = s => String(s || "").replace(/\D/g, "");
const fromTech = r => PEOPLE.techNumber ? digits(r.from) === digits(PEOPLE.techNumber) : /^(in|inbound|tech|from_tech)$/i.test(r.direction || "");
function chatCard() {
  return `<section class="card chat"><div class="hd"><h2>Technician</h2><span class="sub">Text thread</span></div>
    <div class="thread" id="thread"><div class="empty">No messages yet. The summary arrives here after the call.</div></div>
    <div class="foot"><div class="quick"><button class="chipbtn" data-t="1">1 · Replace</button><button class="chipbtn" data-t="2">2 · Wait</button><button class="chipbtn" data-t="3">3 · Similar drives</button><button class="chipbtn" data-t="details">Details</button></div>
    <form class="compose" id="compose" autocomplete="off"><input class="field" id="composeIn" placeholder="Reply as the technician…" aria-label="Reply as the technician"><button class="btn sm">Send</button></form></div></section>`;
}
function summaryCard(body) {
  const lines = String(body).split("\n").map(l => l.replace(/\s+$/, ""));
  const get = re => (lines.find(l => re.test(l)) || "").replace(re, "").trim();
  const head = lines[1] || "", m = head.match(/Drive (\S+) \(([^)]+)\), warning (\S+)/);
  const ev = get(/^Evidence:\s*/).replace(/died/g, "failed"), dec = get(/^Decision:\s*/);
  const dm = !/^none\b/i.test(dec) && dec.match(/^(\w+)(?: at (\S+))?/), section = name => { const i = lines.findIndex(l => l.startsWith(name)); if (i < 0) return [];
    const out = []; for (let j = i + 1; j < lines.length && /^\s/.test(lines[j]); j++) out.push(lines[j].trim()); return out; };
  const sims = section("Most recent identical drives").map(l => { const x = l.match(/^(\S+): warned (\S+), (died (\S+)|.*)$/); return x ? {s: x[1], w: x[2], d: x[4], rest: x[3]} : {s: l}; });
  const acts = section("Actions").map(cleanDetail).filter(Boolean);
  const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 864e5);
  return `<div class="sumcard"><div class="t">Summary${m ? ` · <span class="mono">${esc(m[1])}</span>` : ""}</div>
    ${m ? `<div class="faint">${esc(m[2])} · <span class="mono">${esc(m[3])}</span></div>` : ""}
    ${ev ? `<div class="e">${esc(ev)}.</div>` : ""}
    ${dm ? `<div><span class="pill accent" style="height:20px">${esc(CHOICE[dm[1].toLowerCase()] || cap(dm[1].toLowerCase()))}</span>${dm[2] ? ` <span class="faint tnum">${tm(dm[2])}</span>` : ""}</div>` : ""}
    ${sims.length ? `<div class="h">Identical drives</div>${sims.map(x => `<div class="r"><span class="mono">${esc(x.s)}</span><span>${x.d ? `failed ${daysBetween(x.w, x.d)} day${daysBetween(x.w, x.d) === 1 ? "" : "s"} after warning` : esc(x.rest || "")}</span></div>`).join("")}` : ""}
    ${acts.length ? `<div class="h">Actions</div>${acts.map(x => `<div class="r"><span>${esc(x)}</span></div>`).join("")}` : ""}</div>`;
}
function msgBody(body) {
  if (/^(PRECEDENT SUMMARY|Summary for drive)/i.test(String(body || "").trim())) return summaryCard(body);
  return String(body || "").split("\n").map(l =>
    /^(\s{2,}|[-•*|>])|\b\d+ of \d+\b|[A-Z0-9]{8,}/.test(l) && l.length < 120 ? `<span class="ev">${esc(l)}</span>` : esc(l)).join("\n");
}
function wireChat(since) {
  techSeen = null; techSince = since || null;
  const send = async body => {
    body = String(body || "").trim(); if (!body) return;
    const r = await post("/api/tech/send", {body});
    if (!r || r.__status) return toast(r && r.__status === 404 ? "Technician inbox isn't connected" : "Message not sent", "alert");
    $("#composeIn").value = ""; pollThread();
  };
  $$(".quick .chipbtn").forEach(b => b.onclick = () => send(b.dataset.t));
  $("#compose").onsubmit = e => { e.preventDefault(); send($("#composeIn").value); };
  every(pollThread, 1500);
}
async function pollThread() {
  const el = $("#thread"); if (!el) return;
  const out = await api("/api/tech/thread");
  if (!out) return;
  let rows = (Array.isArray(out) ? out : out.rows || []).slice().sort((x, y) => String(x.ts).localeCompare(String(y.ts)));
  if (techSince) { const r2 = rows.filter(m => String(m.ts) >= String(techSince)); if (r2.length) rows = r2; }
  if (!PEOPLE.techNumber && (out.number || out.tech_number)) PEOPLE.techNumber = out.number || out.tech_number;
  const key = m => `${m.ts}|${m.from}|${m.body}`;
  if (techSeen && rows.length === techSeen.size && rows.every(m => techSeen.has(key(m)))) return;
  techSeen = new Set(rows.map(key));
  el.innerHTML = rows.length ? rows.slice(-40).map(m => `<div class="msg ${fromTech(m) ? "me" : "them"} ${/^(PRECEDENT SUMMARY|Summary for drive)/i.test(String(m.body || "").trim()) ? "sum" : ""}">${msgBody(m.body)}<time>${tm(m.ts)}</time></div>`).join("")
    : `<div class="empty">No messages yet. The summary arrives here after the call.</div>`;
  const last = el.lastElementChild;
  el.scrollTop = last ? Math.max(0, last.offsetTop - 8) : el.scrollHeight;
}

function drawSmart(svg, legend, hist, warnings, failedOn) {
  if (!svg) return;
  const series = [["s5", "5 · reallocated", "var(--info)"], ["s197", "197 · pending", "var(--warn)"], ["s198", "198 · uncorrectable", "var(--danger)"]];
  if (!hist.length) { svg.innerHTML = `<text x="450" y="120" text-anchor="middle">No SMART readings yet</text>`; return; }
  const W = 900, H = 240, l = 44, r = 14, t = 12, b = 26, w = W - l - r, h = H - t - b;
  const T = d => new Date(String(d).slice(0, 10) + "T00:00:00Z").getTime();
  const t0 = T(hist[0].date), t1 = Math.max(t0 + 864e5, T(hist[hist.length - 1].date));
  const ly = v => Math.log10(1 + Math.max(0, v || 0));
  const top = Math.max(2, ...hist.flatMap(p => series.map(([k]) => ly(p[k]))));
  const x = d => l + (T(d) - t0) / (t1 - t0) * w, y = v => t + (1 - ly(v) / top) * h;
  let s = "";
  for (const v of [0, 1, 10, 100, 1000, 10000].filter(v => ly(v) <= top + 0.01))
    s += `<line x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${l - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  const months = [...new Set(hist.map(p => String(p.date).slice(0, 7)))];
  if (months.length > 1) for (const m of months) s += `<text x="${x(m + "-01")}" y="${H - 6}">${"JanFebMarAprMayJunJulAugSepOctNovDec".substr((+m.slice(5, 7) - 1) * 3, 3)}</text>`;
  else if (hist.length > 1) s += `<text x="${l}" y="${H - 6}">${dayLabel(hist[0].date)}</text><text x="${W - r}" y="${H - 6}" text-anchor="end">${dayLabel(hist[hist.length - 1].date)}</text>`;
  for (const wn of warnings) s += `<line x1="${x(wn.warn_date)}" x2="${x(wn.warn_date)}" y1="${t}" y2="${t + h}" stroke="var(--warn)" stroke-dasharray="3 3"/><text x="${x(wn.warn_date) - 6}" y="${t + h - 6}" text-anchor="end" style="fill:var(--warn-ink)">warning</text>`;
  if (failedOn) s += `<line x1="${x(failedOn)}" x2="${x(failedOn)}" y1="${t}" y2="${t + h}" stroke="var(--danger)" stroke-width="1.5"/><text x="${x(failedOn) - 6}" y="${t + 12}" text-anchor="end" style="fill:var(--danger)">failed</text>`;
  for (const [k, , c] of series) s += `<polyline fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round" points="${hist.filter(p => p[k] != null).map(p => x(p.date).toFixed(1) + "," + y(p[k]).toFixed(1)).join(" ")}"/>`;
  svg.innerHTML = s;
  const last = hist[hist.length - 1];
  if (legend) legend.innerHTML = series.map(([k, n, c]) => `<span><span class="dot" style="background:${c}"></span>${n} <b class="tnum" style="color:var(--ink)">${fmt(last[k])}</b></span>`).join("");
}

const GPOS = {similar_group: [0, 5], playbook: [0, 7], drive: [0, 0], model: [0, 1], pattern: [0, 2], precedent: [0, 3], network: [0, 4], similar: [0, 6],
  alert: [1, 0], call: [1, 1], decision: [1, 2], action: [1, 3], channels: [1, 4], keewano: [1, 5]};
const GICON = {similar_group: "drive", playbook: "wrench", network: "users", drive: "drive", model: "layers", pattern: "alert", precedent: "sigma", similar: "drive", alert: "bell", call: "phone",
  decision: "check", action: "check", channels: "slack", keewano: "keewano"};
const GTYPE = {similar_group: "Identical drives", playbook: "Playbook", network: "Network", drive: "Drive", model: "Model", pattern: "Warning", precedent: "Precedent", similar: "Identical drive", alert: "Alert",
  call: "Call", decision: "Decision", action: "Action", channels: "Channels", keewano: "Memory"};
async function pageGraph(alertId, serial) {
  crumbs([["Memory graph"]]);
  const qs = alertId ? `alert_id=${encodeURIComponent(alertId)}` : serial ? `serial=${encodeURIComponent(serial)}` : "";
  view().innerHTML = `<div class="page-head"><div><h1>Memory graph</h1><p id="gsub">How one warning became a decision, and what Precedent remembers. Click any step.</p></div>
      <span class="spacer"></span><button class="btn secondary sm" id="gfit">Fit to view</button></div>
    <section class="card graph-wrap"><svg id="graph"><g id="vp"></g></svg><div class="drawer" id="gpanel"></div>
      <div class="faint" style="position:absolute;left:16px;bottom:12px;font-size:12px">Scroll to zoom · drag to pan · grows live as the incident moves</div></section>`;
  const gen = routeGen;
  let g = await api(`/api/graph${qs ? "?" + qs : ""}`);
  if (gen !== routeGen) return;
  if (!g || !g.found || !g.nodes.length) {
    $("#gfit").remove();
    $(".graph-wrap").outerHTML = `<div class="card empty">${g ? `Nothing to graph for this ${alertId ? "incident" : "drive"} yet.` : loadError("the memory graph")}</div>`;
    return;
  }
  const NW = 200, NH = 64, CW = 248, RH = 84, MIN_K = 12 / 14;  // never zoom out past a 12 px label
  const tone = n => n.type === "playbook" ? "var(--accent)" : n.type === "similar" ? (n.data.died ? "var(--danger)" : "var(--ok)") : ["precedent", "network", "decision"].includes(n.type) ? "var(--accent)"
    : n.type === "keewano" ? "var(--info)" : "var(--ink-3)";
  let pos = {}, known = new Set(), byId = {}, k = 1, tx = 0, ty = 0, sel = null, simOpen = false, V = {nodes: [], edges: []};
  const visible = () => {  // identical drives collapse into one node so the main path reads left to right
    const sims = g.nodes.filter(n => n.type === "similar");
    if (sims.length < 2) return {nodes: g.nodes, edges: g.edges};
    const died = sims.filter(n => n.data && n.data.died).length;
    const grp = {id: "simgroup", type: "similar_group", label: `${sims.length} identical drives (${died} failed)`,
      summary: `${sims.length} identical drives with the same warning, shown as examples: ${died} failed and ${sims.length - died} survived. ${simOpen ? "Click again to collapse." : "Click to expand them."}`, data: {}};
    const src = g.edges.find(e => sims.some(n => n.id === e.to));
    const nodes = g.nodes.filter(n => n.type !== "similar" || simOpen).concat([grp]);
    const edges = g.edges.filter(e => !sims.some(n => n.id === e.to)).concat(src ? [{from: src.from, to: "simgroup"}] : [])
      .concat(simOpen ? sims.map(n => ({from: "simgroup", to: n.id})) : []);
    return {nodes, edges};
  };
  const svg = $("#graph");
  const apply = () => $("#vp") && $("#vp").setAttribute("transform", `translate(${tx},${ty}) scale(${k})`);
  const layout = () => {
    pos = {}; const cols = {}; V = visible();
    for (const n of V.nodes) { const [ln, c] = GPOS[n.type] || [1, 5]; (cols[ln + ":" + c] ||= []).push(n); }
    const laneH = ln => Math.max(1, ...Object.entries(cols).filter(([kk]) => kk.startsWith(ln + ":")).map(([, l]) => l.length)) * RH;
    const laneY = [0, laneH(0) / 2 + 80 + laneH(1) / 2];
    for (const [key, list] of Object.entries(cols)) { const [ln, c] = key.split(":").map(Number);
      list.forEach((n, i) => pos[n.id] = {x: c * CW + (ln ? 60 : 0), y: laneY[ln] + (i - (list.length - 1) / 2) * RH - NH / 2}); }
  };
  const render = () => {
    layout(); byId = Object.fromEntries(V.nodes.map(n => [n.id, n]));
    let s2 = "";
    for (const e of V.edges) {
      const a = pos[e.from], b = pos[e.to]; if (!a || !b) continue;
      const crossLane = Math.abs(b.y - a.y) > RH * 2, skips = b.x - a.x > CW * 1.5;
      let d, x2, y2;
      if (!crossLane && skips) { const x1 = a.x + NW / 2, y1 = a.y + NH; x2 = b.x + NW / 2; y2 = b.y + NH; const dy = Math.max(y1, y2) + 110; d = `M${x1},${y1} C${x1},${dy} ${x2},${dy} ${x2},${y2}`; }
      else if (crossLane && b.y > a.y) { const x1 = a.x + NW / 2, y1 = a.y + NH, my = (y1 + b.y) / 2; x2 = b.x + NW / 2; y2 = b.y; d = `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`; }
      else { const x1 = a.x + NW, y1 = a.y + NH / 2, mx = (x1 + (x2 = b.x)) / 2; y2 = b.y + NH / 2; d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`; }
      s2 += `<path d="${d}" fill="none" stroke="var(--line-strong)" stroke-width="1.5"/><circle cx="${x2}" cy="${y2}" r="2.5" fill="var(--ink-3)"/>`;
    }
    for (const n of V.nodes) {
      const {x, y} = pos[n.id], isNew = known.size && !known.has(n.id);
      s2 += `<g class="gnode ${isNew ? "gnew" : ""} ${sel === n.id ? "sel" : ""}" data-id="${esc(n.id)}" transform="translate(${x},${y})" style="cursor:pointer" tabindex="0" role="button" aria-label="${esc((GTYPE[n.type] || n.type) + ": " + n.label)}">
        <rect class="bg" width="${NW}" height="${NH}" rx="10"/>
        <circle cx="24" cy="${NH / 2}" r="14" fill="${tone(n)}" fill-opacity="0.14"/>
        <g transform="translate(16,${NH / 2 - 8})" style="color:${tone(n)}"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${P[GICON[n.type]] || P.activity}</svg></g>
        <foreignObject x="46" y="6" width="${NW - 52}" height="${NH - 12}"><div xmlns="http://www.w3.org/1999/xhtml" style="font:11px/1.25 var(--font);color:var(--ink-3)">${esc(GTYPE[n.type] || n.type)}${n.type === "similar_group" ? (simOpen ? " · hide" : " · expand") : ""}</div>
          <div xmlns="http://www.w3.org/1999/xhtml" style="font:600 14px/1.25 var(--font);color:var(--ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word">${esc(n.label)}</div></foreignObject></g>`;
    }
    $("#vp").innerHTML = s2; apply();
    V.nodes.forEach(n => known.add(n.id));
    $$(".gnode").forEach(el => {
      const act = () => { if (el.dataset.id === "simgroup") { simOpen = !simOpen; render(); } select(el.dataset.id); };
      el.onclick = () => { if (!moved) act(); };  // a drag that ends on a node is a pan, not a click
      el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); } }; });
  };
  const fit = () => {
    const xs = Object.values(pos).map(p => p.x), ys = Object.values(pos).map(p => p.y), R = svg.getBoundingClientRect();
    const minX = Math.min(...xs) - 30, maxX = Math.max(...xs) + NW + 30, minY = Math.min(...ys) - 40, maxY = Math.max(...ys) + NH + 150;
    k = Math.max(MIN_K, Math.min(R.width / (maxX - minX), R.height / (maxY - minY), 1.2));
    const w = (maxX - minX) * k;  // wider than the panel: start at the drive and let the user pan right instead of shrinking
    tx = w <= R.width ? (R.width - w) / 2 - minX * k : 16 - minX * k; ty = (R.height - (maxY - minY) * k) / 2 - minY * k; apply();
  };
  const select = id => {
    sel = id; $$(".gnode").forEach(el => el.classList.toggle("sel", el.dataset.id === id));
    const n = byId[id]; if (!n) return;
    const data = Object.entries(n.data || {}).filter(([kk, v]) => v != null && v !== "" && typeof v !== "object" && !/^(alert_id|call_id|phone|message_id)$/.test(kk));
    $("#gpanel").classList.add("on");
    $("#gpanel").innerHTML = `<div class="row"><span class="pill">${icon(GICON[n.type] || "activity")}${esc(GTYPE[n.type] || n.type)}</span><span class="spacer"></span>
      <button class="btn ghost sm" id="gclose" aria-label="Close">${icon("x")}</button></div>
      <h2 style="font-size:17px;font-weight:650;margin:12px 0 8px;word-break:break-word">${esc(n.label)}</h2><p style="margin:0 0 14px;line-height:1.6;color:var(--ink-2)">${esc(human(n.summary))}</p>` +
      (data.length ? `<dl class="kv">${data.slice(0, 8).map(([kk, v]) => `<dt>${esc(kk.replace(/_/g, " "))}</dt><dd>${esc(typeof v === "number" && v > 0 && v < 1 ? pct(v, 1) : v)}</dd>`).join("")}</dl>` : "") +
      (n.type === "drive" || n.type === "similar" ? `<p style="margin-top:14px"><a class="btn secondary sm" href="/app/drives/${encodeURIComponent(n.label)}">Open drive ${icon("arrow")}</a></p>` : "") +
      (n.type === "alert" && g.alert_id ? `<p style="margin-top:14px"><a class="btn secondary sm" href="/app/incidents/${encodeURIComponent(g.alert_id)}">Open incident ${icon("arrow")}</a></p>` : "");
    $("#gclose").onclick = () => { sel = null; $("#gpanel").classList.remove("on"); $$(".gnode").forEach(el => el.classList.remove("sel")); };
  };
  const sub = () => { $("#gsub").innerHTML = `Drive <a class="mono" href="/app/drives/${encodeURIComponent(g.serial)}">${esc(g.serial)}</a>` +
    (g.alert_id ? ` · <a href="/app/incidents/${encodeURIComponent(g.alert_id)}">open incident</a>` : " · no alert yet") + `. Click any step for a plain-English summary.`; };
  let moved = false;
  sub(); render(); fit(); $("#gfit").onclick = fit;
  svg.addEventListener("wheel", e => { e.preventDefault(); const R = svg.getBoundingClientRect(), px = e.clientX - R.left, py = e.clientY - R.top;
    if (!e.ctrlKey && Math.abs(e.deltaX) > Math.abs(e.deltaY)) { tx -= e.deltaX; apply(); return; }  // trackpad sideways = pan
    const nk = Math.min(3, Math.max(MIN_K * 0.7, k * Math.exp(-e.deltaY * 0.0015))); tx = px - (px - tx) * nk / k; ty = py - (py - ty) * nk / k; k = nk; apply(); }, {passive: false});
  let drag = null;
  svg.addEventListener("pointerdown", e => { drag = {x: e.clientX, y: e.clientY, tx, ty}; moved = false; svg.style.cursor = "grabbing"; });
  const mv = e => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) moved = true; tx = drag.tx + dx; ty = drag.ty + dy; apply(); };
  const up = () => { drag = null; if ($("#graph")) $("#graph").style.cursor = "grab"; };
  window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  pageCleanup.push(() => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); });
  // live growth: alert -> call -> decision -> actions -> playbook nodes appear as their events arrive
  let pend = null;
  onEvent(ev => {
    const mine = (g.alert_id && ev.alert_id === g.alert_id) || (ev.serial && ev.serial === g.serial);
    if (!mine || ["transcript_turn", "telemetry_received"].includes(ev.type)) return;
    clearTimeout(pend);
    pend = setTimeout(async () => {
      const g2 = await api(`/api/graph?${g.alert_id ? `alert_id=${encodeURIComponent(g.alert_id)}` : `serial=${encodeURIComponent(g.serial)}`}`);
      if (!g2 || !g2.found || !$("#vp")) return;
      const grew = g2.nodes.length !== g.nodes.length; g = g2; render(); if (sel) select(sel);
      if (grew) toast("Memory graph updated", "layers");
    }, 250);
  });
  every(async () => { const g2 = await api(`/api/graph?${qs}`); if (g2 && g2.found && g2.nodes.length !== g.nodes.length && $("#vp")) { g = g2; render(); } }, 5000);
}

const CHANNELS = {slack: ["Slack", "Alerts and decisions in a channel, with Replace and Wait buttons."], discord: ["Discord", "Alerts and decisions in a channel."],
  teams: ["Microsoft Teams", "Alerts and decisions as cards."], webhook: ["Webhook", "JSON for every alert and decision, sent to your URL."]};
const SERVICES = [["dial", "Dial", "Voice calls to the on-call and the technician text thread."], ["keewano", "Keewano", "Drive memory: every warning, alert and decision is stored and queried live."],
  ["darwin", "Darwin", "Finds the agent to act after a replace (warranty returns)."], ["sparta", "Sparta", "Verifies the action agent: one remote-hands ticket per incident, no duplicates on retry."]];
async function pageIntegrations() {
  crumbs([["Integrations"]]);
  view().innerHTML = `<div class="page-head"><div><h1>Integrations</h1><p>Where Precedent delivers its answers, and how other agents connect.</p></div></div>
    <section class="card" style="margin-bottom:16px"><div class="hd"><h2>Morning digest</h2><span class="sub">Today's swap list and open incidents, to every connected channel</span><span class="spacer"></span><button class="btn sm" id="digestSend">Send now</button></div>
      <div class="bd"><pre class="code" id="digest" style="max-height:240px;overflow:auto;margin:0">Loading preview…</pre></div></section>
    <div class="grid2">
      <section class="card"><div class="hd"><h2>Channels</h2></div><div class="bd" id="chans"><div class="skel"></div></div></section>
      <section class="card"><div class="hd"><h2>Services</h2></div><div class="bd" id="svcs"><div class="skel"></div></div></section>
    </div>
    <section class="card" style="margin-top:16px"><div class="hd"><h2>Connect another agent</h2><span class="sub">MCP tools: check_warning, report_telemetry, get_drive, log_decision</span></div><div class="bd" id="connect"></div></section>`;
  const [ig, kw, acts, dg, lua, d, call] = await Promise.all([api("/api/integrations"), api("/api/keewano"), api("/api/actions?limit=200"), api("/api/digest/preview"),
    api("/api/keewano/lua"), api("/api/demo-drive"), api("/api/call-status")]);
  if (!$("#digest")) return;
  const dText = dg && (typeof dg === "string" ? dg : dg.text || dg.body || dg.preview || "");
  $("#digest").textContent = dText || cap(failedGet["/api/digest/preview"] || "the digest preview isn't available yet.");
  $("#digestSend").onclick = async () => {
    const b = $("#digestSend"); b.disabled = true; b.innerHTML = `<span class="spin"></span>Sending…`;
    const r = await post("/api/digest/send"); b.disabled = false; b.textContent = "Send now";
    if (!r || r.__status) return toast(r && r.__status === 404 ? "Sending the digest isn't available on this server" : `Not sent: ${errText(r) || "the server didn't answer"}`, "alert");
    toast("Morning digest sent", "check");
  };
  const ch = (ig && ig.channels) || {}, row = (dot, name, desc, right) => `<div class="row" style="padding:10px 0;border-bottom:1px solid var(--line);align-items:flex-start">
    <span class="dot ${dot}" style="margin-top:6px"></span><div style="flex:1;min-width:0"><div style="font-weight:600">${name}</div><div class="muted" style="font-size:13px">${desc}</div></div>${right || ""}</div>`;
  $("#chans").innerHTML = Object.keys(CHANNELS).map(k => {
    const c = ch[k] || {}, last = c.last;
    const dot = !c.configured ? "off" : last && last.ok === false ? "danger" : "ok";
    const note = !c.configured ? "Not connected" : last ? (last.ok ? `Last delivered ${tm(last.ts)}` : "Last delivery failed") : "Connected";
    return row(dot, CHANNELS[k][0], `${CHANNELS[k][1]} <span class="faint">· ${note}</span>`,
      `<button class="btn secondary sm" data-test="${k}" ${c.configured ? "" : "disabled title='Add its webhook URL to connect'"}>Send test</button>`);
  }).join("");
  $$("[data-test]").forEach(b => b.onclick = async () => {
    b.disabled = true; const r = await post(`/api/integrations/test/${b.dataset.test}`); b.disabled = false;
    if (!r || r.__status) return toast(r && r.__status === 404 ? "Test messages aren't available on this server" : `Not sent: ${errText(r) || "the server didn't answer"}`, "alert");
    toast(r.result && r.result.ok === false ? "Test delivery failed" : `Test sent to ${CHANNELS[b.dataset.test][0]}`, "check");
  });
  const rows = (acts && acts.rows) || [], lastOf = sp => rows.find(r => r.sponsor === sp);
  const dryAct = sp => lastOf(sp) && /dry/i.test(lastOf(sp).status || "");
  const status = {
    dial: call && /dry/i.test(call.state || "") ? ["warn", "Simulated (dry-run): no Dial key on this server"] : ["ok", "Connected"],
    keewano: (lua && lua.connected) ? ["ok", `Live · Lua precedent table, ${fmt(lua.patterns)} patterns in ${lua.seconds} s`] : (kw && kw.connected) ? ["ok", "Live"] : ["off", "Not connected on this server"],
    darwin: !lastOf("darwin") ? ["off", "Runs after the first replace decision"] : dryAct("darwin") ? ["warn", "Simulated (dry-run)"] : ["ok", "Connected"],
    sparta: !lastOf("sparta") ? ["off", "Runs after the first replace decision"] : dryAct("sparta") ? ["warn", "Simulated (dry-run)"] : ["ok", "Connected"]};
  $("#svcs").innerHTML = SERVICES.map(([k, n, desc]) => row(status[k][0], n, `${desc} <span class="faint">· ${esc(status[k][1])}</span>`)).join("");
  const app = (ig && ig.app_url) || location.origin, serial = (d && d.serial) || "SERIAL", model = (d && d.model) || "MODEL";
  const mcp = `claude mcp add --transport http precedent ${app}/mcp-public/ --header "X-Precedent-Key: <key>"`;
  const curl = `curl -X POST ${app}/v1/telemetry \\\n  -H "Content-Type: application/json" -H "X-Precedent-Key: <key>" \\\n  -d '{"serial": "EXAMPLE01", "model": "${model}", "smart": {"5": 2, "197": 0, "198": 0}, "site": "your-dc"}'`;
  const drive = `curl ${app}/v1/drives/${serial} -H "X-Precedent-Key: <key>"`;
  const block = (title, code, i) => `<div class="row" style="margin-top:${i ? 16 : 0}px"><b style="font-weight:600">${title}</b><span class="spacer"></span><button class="btn ghost sm" data-copy="${i}">${icon("copy")}Copy</button></div><pre class="code">${esc(code)}</pre>`;
  $("#connect").innerHTML = block("Claude Code (MCP)", mcp, 0) + block("Report a SMART reading (REST)", curl, 1) + block("Look up a drive", drive, 2) +
    `<p class="faint" style="font-size:12.5px;margin:12px 0 0">A reading whose history says act starts the same call flow, at most once per drive and warning every 24 hours.</p>`;
  const texts = [mcp, curl, drive];
  $$("[data-copy]").forEach(b => b.onclick = async () => { try { await navigator.clipboard.writeText(texts[+b.dataset.copy]); toast("Copied", "check"); } catch (e) { toast("Select the text to copy it", "alert"); } });
}

async function pageImpact() {
  crumbs([["Impact"]]);
  view().innerHTML = `<div class="page-head"><div><h1>Impact</h1><p>Rules learned only from history before the cutoff, then scored on every warning after it.</p></div></div>
    <section class="card" style="margin-bottom:16px;padding:20px 22px" id="impactLead"><div class="skel" style="width:60%;height:20px"></div></section>
    <section class="card" style="margin-bottom:16px"><table><thead><tr><th>Approach</th><th class="r">Checks a human does</th><th class="r">Failures caught</th><th class="r">Share that failed</th></tr></thead>
      <tbody id="bt"><tr><td colspan="4"><div class="skel"></div></td></tr></tbody></table></section>
    <div class="grid2">
      <section class="card"><div class="hd"><h2>Engineer time back</h2><span class="sub">Morning swap list vs checking every warning</span></div><div class="bd">
        <div class="row" style="gap:32px;align-items:flex-end"><div><div class="stat" id="hrs">–</div><div class="muted">hours</div></div><div><div class="stat" id="usd" style="color:var(--accent-ink)">–</div><div class="muted">remote hands at $100/hr</div></div></div>
        <label class="row muted" style="margin-top:18px;font-size:13px">Minutes per check <input type="range" id="mins" min="5" max="60" value="15" style="flex:1"><b class="tnum" id="minsV" style="color:var(--ink);min-width:24px">15</b></label></div></section>
      <section class="card"><div class="hd"><h2>Calibration</h2><span class="sub">Predicted failure rate vs what happened</span></div><div class="bd"><svg class="chart" id="calib" viewBox="0 0 520 280"></svg></div></section>
    </div>`;
  const b = await backtest();
  if (!$("#bt")) return;
  if (!b) { $("#impactLead").innerHTML = loadError("the backtest"); $("#bt").innerHTML = ""; return; }
  const u = b.urgent, s = b.swaplist;
  const cut = 1 - s.M_checks_precedent / s.N_checks_today, caught = s.K_caught / s.L_failures;
  const caughtWords = caught >= 0.45 && caught <= 0.55 ? "half the failures" : `${pct(caught)} of the failures`;
  $("#impactLead").innerHTML = `<h2 style="font-size:20px;font-weight:650;letter-spacing:-0.015em">Precedent cut checks by ${pct(cut)} and still caught ${caughtWords}.</h2>
    <p class="muted" style="margin:6px 0 0;max-width:72ch">On ${fmt(s.N_checks_today)} warnings it had never seen, the morning swap list asked for ${fmt(s.M_checks_precedent)} checks instead of ${fmt(s.N_checks_today)}, and ${fmt(s.K_caught)} of the ${fmt(s.L_failures)} drives that failed were on it. Urgent alerts are stricter: ${fmt(u.M_checks_precedent)} alerts, ${pct(u.K_caught / u.M_checks_precedent)} of them for drives that really failed.</p>`;
  const row = (label, sub, M, K, share, strong) => `<tr><td><div style="font-weight:${strong ? 600 : 500}">${label}</div><div class="faint" style="font-size:12.5px">${sub}</div></td>
    <td class="r">${fmt(M)}</td><td class="r">${fmt(K)}</td><td class="r" style="font-weight:650;color:${strong ? "var(--accent-ink)" : "var(--ink-2)"}">${share}</td></tr>`;
  $("#bt").innerHTML = row("Check every warning", "What happens today", u.N_checks_today, u.L_failures, pct(u.L_failures / u.N_checks_today, 1), false) +
    row("Precedent urgent alert", `At least ${fmt(u.min_n)} identical drives, ${pct(u.min_rate)} or more failed`, u.M_checks_precedent, u.K_caught, pct(u.K_caught / u.M_checks_precedent), true) +
    row("Precedent morning swap list", `At least ${fmt(s.min_n)} identical drives, ${pct(s.min_rate)} or more failed`, s.M_checks_precedent, s.K_caught, pct(s.K_caught / s.M_checks_precedent), true);
  const upd = () => { const m = +$("#mins").value, h = Math.max(0, s.N_checks_today - s.M_checks_precedent) * m / 60;
    $("#minsV").textContent = m; $("#hrs").textContent = fmt(Math.round(h)); $("#usd").textContent = "$" + fmt(Math.round(h * 100)); };
  $("#mins").oninput = upd; upd();
  const rows = s.calibration || [], svg = $("#calib");
  const W = 520, H = 280, l = 48, r = 12, t = 10, bm = 40, w = W - l - r, h = H - t - bm;
  const top = Math.max(0.6, ...rows.map(d => Math.min(1, d.bucket + 0.1)), ...rows.map(d => d.actual));
  const x = v => l + v / top * w, y = v => t + (1 - v / top) * h, maxN = Math.max(1, ...rows.map(d => d.n));
  let g = "";
  for (let v = 0; v <= top + 1e-9; v += 0.1) g += `<line x1="${x(0)}" x2="${x(top)}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${l - 8}" y="${y(v) + 4}" text-anchor="end">${Math.round(v * 100)}%</text><text x="${x(v)}" y="${H - bm + 18}" text-anchor="middle">${Math.round(v * 100)}%</text>`;
  g += `<line x1="${x(0)}" y1="${y(0)}" x2="${x(top)}" y2="${y(top)}" stroke="var(--ink-3)" stroke-dasharray="4 4"/>`;
  const pts = rows.map(d => [x(Math.min(top, d.bucket + 0.05)), y(d.actual), d]);
  if (pts.length > 1) g += `<polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${pts.map(p => p[0] + "," + p[1]).join(" ")}"/>`;
  for (const [cx, cy, d] of pts) g += `<circle cx="${cx}" cy="${cy}" r="${4 + 10 * Math.sqrt(d.n / maxN)}" fill="var(--accent)" fill-opacity=".18" stroke="var(--accent)" stroke-width="1.5"><title>Predicted ${pct(d.bucket)}–${pct(d.bucket + 0.1)}: ${pct(d.actual)} failed (${fmt(d.n)} warnings)</title></circle>`;
  g += `<text x="${l + w / 2}" y="${H - 4}" text-anchor="middle">Predicted from identical drives</text><text transform="translate(12 ${t + h / 2}) rotate(-90)" text-anchor="middle">Actually failed</text>`;
  svg.innerHTML = g;
}

// Both Dial numbers are ours, so each text shows up twice (A's "sent" + B's "received"): keep one, prefer "received".
function dedupeTexts(rows) {
  const who = (n, num) => String(n || num || "").replace(/\s*\(Agent [AB]\)/, "").trim().toLowerCase();
  const out = [];
  for (const c of rows.slice().sort((a, b) => String(a.ts).localeCompare(String(b.ts)))) {
    if (c.kind !== "text") { out.push(c); continue; }
    const k = who(c.from_name, c.from) + "|" + who(c.to_name, c.to) + "|" + String(c.body || "").trim();
    const twin = out.find(x => x.kind === "text" && x._k === k && Math.abs(new Date(x.ts) - new Date(c.ts)) <= 5000);
    if (!twin) { out.push({...c, _k: k}); continue; }
    if (/received/i.test(c.delivery || c.status || "")) Object.assign(twin, c, {_k: k, delivery: "delivered", _proven: true});
    else twin._proven = twin._proven || /received/i.test(twin.delivery || "");
  }
  out.forEach(c => { if (c._proven) c.delivery = "delivered"; });
  return out;
}

// Phone dock: the on-call's real conversation, live (Today and drive pages)
const Phone = {rows: [], timer: null, loaded: false, min: false};
const isPrecedent = name => /^precedent/i.test(String(name || ""));
const isOnCall = name => !!name && String(name).toLowerCase().replace(/^the /, "") === String(PEOPLE.oncall).toLowerCase().replace(/^the /, "");
function phoneRender() {
  const el = $("#pThread"); if (!el) return;
  const hm = t => new Date(t).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  const rows = dedupeTexts(Phone.rows).slice(-40);
  let html = "", lastMin = "";
  for (const c of rows) {
    const m = (dayName(c.ts) === "Today" ? "" : dayName(c.ts) + " ") + hm(c.ts); if (m !== lastMin) { html += `<div class="ptime">${m}</div>`; lastMin = m; }
    if (c.kind === "call") {
      let turns = c.turns || [];
      if (!turns.length && c.transcript) { let t = c.transcript; if (typeof t === "string" && /^\s*\[/.test(t)) { try { t = JSON.parse(t); } catch (e) {} }
        turns = Array.isArray(t) ? t.map(x => ({role: /agent|assistant|precedent/i.test(x.role || "") ? "Precedent" : "You", text: x.text || x.content || ""})) : parseTranscript(t); }
      turns = turns.filter(x => x.text);
      html += `<details class="pcallb"><summary>📞 Call from Precedent${+c.duration_s > 0 ? ` · ${fmt(+c.duration_s)} s` : ""}${turns.length ? " · transcript" : ""}</summary>
        ${turns.length ? `<div class="tr">${turns.map(x => `<div class="pb ${/precedent/i.test(x.role) ? "in" : "out"}" style="font-size:12px">${esc(x.text)}</div>`).join("")}</div>` : ""}</details>`;
      continue;
    }
    const mine = c.mine ?? !(isPrecedent(c.from_name || c.from) || isOnCall(c.to_name));  // the phone's owner replying
    const body = String(c.body || ""), sum = /^(PRECEDENT SUMMARY|Summary for drive)/i.test(body.trim());
    const lines = body.split("\n"), items = lines.filter(l => /^\s*([-•*]|\d+[.)])\s+/.test(l));
    const listy = !sum && !mine && items.length >= 2;  // e.g. Darwin's agents: a compact list inside the bubble
    const inner = sum ? summaryCard(body) : listy ? `${esc(lines.filter(l => !items.includes(l)).join("\n").trim())}<ul style="margin:4px 0 0;padding-left:16px">${items.map(l => `<li>${esc(l.replace(/^\s*([-•*]|\d+[.)])\s+/, ""))}</li>`).join("")}</ul>` : esc(body);
    html += `<div class="pb ${mine ? "out" : "in"}" ${sum || listy ? 'style="white-space:normal"' : ""}>${inner}</div>` +
      (mine || c._proven ? `<div class="pmeta ${mine ? "" : "l"}">${/fail|error/i.test(c.delivery || "") ? "Not delivered" : "Delivered ✓"}</div>` : "");
  }
  el.innerHTML = html || `<div class="pempty">No messages yet. When Precedent calls or texts, it shows up here.</div>`;
  el.scrollTop = el.scrollHeight;
}
function phoneCall(state, ts) {
  const box = $("#pCall"), st = String(state || "").toLowerCase();
  clearInterval(Phone.timer);
  if (/ring|queued|initiat|dial/.test(st)) { box.hidden = false; box.className = "pcall ringing"; $("#pCallState").textContent = "Incoming call…"; return; }
  if (/progress|answer|active|connected/.test(st)) {
    box.hidden = false; box.className = "pcall"; const t0 = Date.now();
    const tick = () => { const s2 = Math.floor((Date.now() - t0) / 1000); $("#pCallState").textContent = `On call ${Math.floor(s2 / 60)}:${String(s2 % 60).padStart(2, "0")}`; };
    tick(); Phone.timer = setInterval(tick, 1000); return;
  }
  box.hidden = true;  // ended / dry-run / failed: collapse into the thread as a call bubble
}
async function phoneLoad() {
  const out = await api("/api/comms?limit=50");
  Phone.rows = ((out && out.rows) || []).filter(c => c.kind === "call" || c.kind === "text");
  Phone.loaded = true; phoneRender();
}
function phoneShow(on) {
  const dock = $("#phoneDock"); if (!dock) return;
  dock.hidden = !on; document.body.classList.toggle("withphone", on && !Phone.min);
  if (on && !Phone.loaded) phoneLoad();
}
(function phoneInit() {
  const clock = () => { const el = $("#pTime"); if (el) el.textContent = new Date().toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}).replace(/\s?[AP]M/, ""); };
  clock(); setInterval(clock, 15000);
  $("#phoneToggle").onclick = () => { Phone.min = !Phone.min; $("#phoneDock").classList.toggle("min", Phone.min); $("#phoneToggle").textContent = Phone.min ? "Show phone" : "Hide phone";
    $("#phoneToggle").setAttribute("aria-expanded", String(!Phone.min)); document.body.classList.toggle("withphone", !Phone.min); };
  const send = async body => { body = String(body || "").trim(); if (!body) return;
    Phone.rows.push({kind: "text", ts: new Date().toISOString(), from_name: PEOPLE.oncall, body, delivery: "sending", mine: true}); phoneRender();
    const r = await post("/api/tech/send", {body}); if (!r || r.__status) toast("Message not sent", "alert"); $("#pIn").value = ""; };
  $$("#phoneDock [data-pb]").forEach(b => b.onclick = () => send(b.dataset.pb));
  $("#pForm").onsubmit = e => { e.preventDefault(); send($("#pIn").value); };
  Live.subs.add(ev => {  // global: the phone listens on every page
    if (ev.type === "call_state" && !simulated(ev)) { phoneCall(ev.state, ev.ts); if (!/ring|progress|answer|active|queued|initiat/i.test(ev.state || "")) phoneLoad(); return; }
    if (ev.type === "transcript_turn" && !simulated(ev)) { const c = Phone.rows.filter(x => x.kind === "call").pop(); if (c) { (c.turns ||= []).push({role: /agent|assistant|precedent/i.test(ev.role || "") ? "Precedent" : "You", text: ev.text || ""}); phoneRender(); } return; }
    if ((ev.type === "message_sent" || ev.type === "message_received") && !simulated(ev)) {
      // replace the optimistic "sending" bubble with the real one
      const i = Phone.rows.findIndex(x => x.delivery === "sending" && String(x.body).trim() === String(ev.body || "").trim()); if (i >= 0) Phone.rows.splice(i, 1);
      Phone.rows.push({kind: "text", ts: ev.ts || new Date().toISOString(), from_name: ev.from_name || nameFor(ev.from), to_name: ev.to_name, body: ev.body || ev.text || "",
        delivery: ev.delivery || (ev.type === "message_received" ? "received" : "delivered"), mine: ev.type === "message_received"});
      phoneRender();
    }
  });
})();

async function pollHealth() {
  const h = await api("/api/health"), el = $("#health"); if (!el) return;
  if (!h) { el.innerHTML = `<span class="dot off"></span><span>Status unavailable</span>`; return; }
  const svc = Object.entries(h).filter(([, v]) => v && typeof v === "object" && v.status);
  const bad = svc.filter(([, v]) => v.status === "degraded").map(([k]) => ACTOR[k] || cap(k));
  el.title = svc.map(([k, v]) => `${ACTOR[k] || cap(k)}: ${v.status}`).join("\n");
  el.innerHTML = bad.length ? `<span class="dot warn"></span><span>${esc(bad.join(", "))} degraded</span>` : `<span class="dot ok"></span><span>All services healthy</span>`;
}
if (new URLSearchParams(location.search).has("snapshot")) setLive("poll"); else connectStream();
pollHealth(); setInterval(pollHealth, 30000);
route();
