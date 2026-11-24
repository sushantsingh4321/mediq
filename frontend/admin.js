// admin.js: the admin console (admin.html).
// Every request here needs an admin login; site.js sends the token for us.

const { api, esc, user } = window.mediq;

const fmtTime = iso => new Date(iso).toLocaleString("en-IN",
  { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const ROLES = ["patient", "receptionist", "doctor", "admin"];

// Lists downloaded from the server; the search boxes filter these in the browser.
let accounts = [], enquiries = [], callbacks = [];
let me = null;

// Does any of these values contain the search text? (case doesn't matter)
// plural(1, "doctor") -> "1 doctor", plural(3, "doctor") -> "3 doctors"
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const matches = (q, ...values) => !q || values.some(v => String(v ?? "").toLowerCase().includes(q));

// ---------- 1. overview tiles ----------

function tile(label, value, detail = "", link = "") {
  const inner = `<div class="tile-value">${value}</div><div class="tile-label">${label}</div>
                 ${detail ? `<div class="muted">${detail}</div>` : ""}`;
  return link ? `<a class="tile stat-tile" href="${link}">${inner}</a>` : `<div class="tile stat-tile">${inner}</div>`;
}

async function renderOverview() {
  const o = await api("/admin/overview");
  const cb = o.callbacks, acc = o.accounts;
  document.getElementById("tiles").innerHTML = [
    tile("Patients waiting", o.queue.waiting, `${o.queue.in_consultation} with doctors · ${o.queue.done} done`, "/index.html#dashboard"),
    tile("Beds free", `${o.beds.free}<small>/${o.beds.total}</small>`, `${o.beds.occupied} occupied`, "/index.html#beds"),
    tile("Doctors on duty", o.doctors_on_duty, "right now", "/schedule.html"),
    tile("Ambulances free", `${o.ambulances.available}<small>/${o.ambulances.available + o.ambulances.on_trip + o.ambulances.maintenance}</small>`,
         `${o.ambulances.on_trip} on trip · ${plural(o.open_trips, "open trip")}`, "/ambulance.html"),
    tile("Call-backs to handle", cb.pending + cb.calling + cb.failed,
         `${cb.failed} failed · ${cb.calling} calling · ${cb.done} done`, "#callbacks"),
    tile("Enquiries", o.enquiries_total, `${o.enquiries_today} today`, "#enquiries"),
    tile("Accounts", Object.values(acc).reduce((a, b) => a + b, 0),
         `${plural(acc.doctor, "doctor")} · ${plural(acc.receptionist, "receptionist")} · ` +
         `${plural(acc.admin, "admin")} · ${plural(acc.patient, "patient")}`, "#accounts"),
  ].join("");
  document.getElementById("updated").textContent = `Last updated ${new Date().toLocaleTimeString("en-IN")}.`;
}

// ---------- 2. accounts ----------

function drawAccounts() {
  const q = document.getElementById("user-search").value.trim().toLowerCase();
  const role = document.getElementById("role-filter").value;
  const rows = accounts.filter(u => (!role || u.role === role) && matches(q, u.full_name, u.email, u.phone));
  document.getElementById("user-rows").innerHTML = rows.length ? rows.map(u => `<tr>
      <td>${u.id}</td>
      <td>${esc(u.full_name)}${me && u.id === me.id ? ' <span class="badge dry">you</span>' : ""}</td>
      <td>${esc(u.email)}</td>
      <td>${esc(u.phone || "–")}</td>
      <td><select class="role-select" data-id="${u.id}" aria-label="Role of ${esc(u.full_name)}"
            ${me && u.id === me.id ? "disabled" : ""}>
            ${ROLES.map(r => `<option value="${r}" ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}
          </select></td>
      <td>${fmtTime(u.created_at)}</td>
    </tr>`).join("") : `<tr><td colspan="6" class="muted">No matching accounts</td></tr>`;
}

async function loadAccounts() {
  accounts = await api("/auth/users");
  drawAccounts();
}

const userMsg = document.getElementById("user-msg");
function say(text, isError) { userMsg.textContent = text; userMsg.className = isError ? "warn" : "ok"; }

// Changing a role: ask first, then PATCH /api/auth/users/{id}
document.getElementById("user-rows").addEventListener("change", async e => {
  const sel = e.target.closest(".role-select");
  if (!sel) return;
  const u = accounts.find(a => a.id === Number(sel.dataset.id));
  if (!confirm(`Change ${u.full_name} from ${u.role} to ${sel.value}?`)) { sel.value = u.role; return; }
  try {
    const updated = await api(`/auth/users/${u.id}`, { method: "PATCH", body: JSON.stringify({ role: sel.value }) });
    say(`${updated.full_name} is now ${updated.role}.`, false);
  } catch (err) {
    say(err.message, true);   // e.g. "still has 2 OPD session(s)"
  }
  loadAccounts();
  renderOverview();
});

// Creating an account: POST /api/auth/users
document.getElementById("new-user-form").addEventListener("submit", async e => {
  e.preventDefault();
  const form = e.target, f = new FormData(form);
  try {
    const u = await api("/auth/users", {
      method: "POST",
      body: JSON.stringify({
        full_name: f.get("full_name"), email: f.get("email"),
        phone: f.get("phone") || null, password: f.get("password"), role: f.get("role"),
      }),
    });
    say(`Created ${u.full_name} (${u.role}). They can log in with ${u.email}.`, false);
    form.reset();
    loadAccounts();
    renderOverview();
  } catch (err) {
    say(err.message, true);
  }
});

// ---------- 3. enquiries ----------

function drawEnquiries() {
  const q = document.getElementById("enquiry-search").value.trim().toLowerCase();
  const rows = [...enquiries].reverse().filter(x => matches(q, x.name, x.mobile, x.speciality));
  document.getElementById("enquiry-rows").innerHTML = rows.length ? rows.map(x => `<tr>
      <td>${x.id}</td><td>${fmtTime(x.created_at)}</td><td>${esc(x.name)}</td>
      <td>${esc(x.country_code)} ${esc(x.mobile)}</td><td>${esc(x.speciality)}</td>
    </tr>`).join("") : `<tr><td colspan="5" class="muted">No enquiries${q ? " match" : " yet"}</td></tr>`;
}

// ---------- 4. call-backs ----------

function drawCallbacks() {
  const q = document.getElementById("callback-search").value.trim().toLowerCase();
  const status = document.getElementById("callback-filter").value;
  const rows = callbacks.filter(c => (!status || c.status === status) && matches(q, c.name, c.mobile));
  document.getElementById("callback-rows").innerHTML = rows.length ? rows.map(c => `<tr>
      <td>${c.id}</td><td>${fmtTime(c.created_at)}</td><td>${esc(c.name)}</td><td>${esc(c.mobile)}</td>
      <td><span class="badge ${esc(c.status)}">${esc(c.status)}</span>
          ${c.dry_run ? '<span class="badge dry">dry run</span>' : ""}</td>
      <td class="muted">${esc(c.note)}</td>
    </tr>`).join("") : `<tr><td colspan="6" class="muted">No call-backs${q || status ? " match" : " yet"}</td></tr>`;
}

async function loadLists() {
  [enquiries, callbacks] = await Promise.all([api("/enquiries"), api("/callback")]);
  drawEnquiries();
  drawCallbacks();
}

// Search boxes and filters redraw from the lists we already have (no server call).
document.getElementById("user-search").addEventListener("input", drawAccounts);
document.getElementById("role-filter").addEventListener("change", drawAccounts);
document.getElementById("enquiry-search").addEventListener("input", drawEnquiries);
document.getElementById("callback-search").addEventListener("input", drawCallbacks);
document.getElementById("callback-filter").addEventListener("change", drawCallbacks);

// ---------- start ----------

async function start() {
  me = await user;
  if (!me || me.role !== "admin") return;   // site.js is already showing login / "No access"
  await Promise.all([renderOverview(), loadAccounts(), loadLists()]);
  // Keep counts and lists fresh. Accounts change rarely, so they only reload after an edit.
  setInterval(() => { renderOverview(); loadLists(); }, 10000);
}

start().catch(err => console.error(err));
