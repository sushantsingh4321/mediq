// mediQ frontend: plain JavaScript, no frameworks, no build step.
// The whole idea: call the FastAPI backend with fetch(), then put the
// results into the page. Read LEARN.md, Part 3, for a walk-through.

const API = "/api"; // same server that serves this page

// ---------- small helpers ----------
 
// Call the backend and return JSON. Throws an Error with the server's message on failure.
async function api(path, options = {}) {
  const res = await fetch(API + path, {
    // authHeader() (from site.js) adds "Authorization: Bearer <token>" when logged in
    headers: { "Content-Type": "application/json", ...window.mediq.authHeader() },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {          // not logged in, or the 60-minute login ran out
    window.mediq.clearToken();
    window.mediq.goToLogin();
  }
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : res.statusText);
  }
  return data;
}

// Escape text before putting it into HTML (stops a name like "<b>" breaking the page).
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const fmtMin = m => (m === null || m === undefined ? "–" : `${Math.round(m)} min`);

// ---------- screen switching ----------

let currentScreen = "reception";
document.querySelectorAll("nav.app-tabs button").forEach(btn => {
  btn.addEventListener("click", () => {
    currentScreen = btn.dataset.screen;
    document.querySelectorAll("nav.app-tabs button").forEach(b => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".screen").forEach(s => s.classList.toggle("active", s.id === currentScreen));
    refresh();
  });
});

// ---------- departments dropdowns ----------

let departments = [];

async function loadDepartments() {
  departments = await api("/departments");
  document.querySelectorAll(".dept-select").forEach(sel => {
    const keep = sel.value;
    sel.innerHTML = departments.map(d => `<option value="${d.id}">${esc(d.name)} (${esc(d.code)})</option>`).join("");
    if (keep) sel.value = keep;
  });
  fillRooms();
}

// Room dropdown on the Doctor screen: only rooms 1..doctors for the chosen department.
function fillRooms() {
  const roomSel = document.getElementById("room-select");
  const dept = departments.find(d => d.id === Number(doctorForm.department_id.value));
  if (!dept) return;
  const keep = Number(roomSel.value);
  roomSel.innerHTML = Array.from({ length: dept.doctors }, (_, i) =>
    `<option value="${i + 1}">Room ${i + 1}</option>`).join("");
  roomSel.value = keep >= 1 && keep <= dept.doctors ? keep : 1;
}

// ---------- 1. Reception ----------

document.getElementById("register-form").addEventListener("submit", async e => {
  e.preventDefault(); // stop the browser reloading the page
  const form = new FormData(e.target);
  try {
    const token = await api("/tokens", {
      method: "POST",
      body: JSON.stringify({
        patient_name: form.get("patient_name"),
        department_id: Number(form.get("department_id")),
      }),
    });
    const dept = departments.find(d => d.id === token.department_id);
    const slip = document.getElementById("token-slip");
    slip.innerHTML = `
      <div class="muted">${esc(dept.name)}</div>
      <div class="num">${esc(token.number)}</div>
      <div>${esc(token.patient_name)}</div>
      <div class="muted">${token.people_ahead} ahead of you · about ${fmtMin(token.estimated_wait_minutes)} wait</div>`;
    slip.classList.remove("hidden");
    e.target.patient_name.value = "";
  } catch (err) {
    alert("Could not register: " + err.message);
  }
});

// ---------- 2. Doctor ----------

const doctorForm = document.getElementById("doctor-form");
const doctorMsg = document.getElementById("doctor-msg");

// Show a status line under the doctor buttons: green for success, red for errors.
function showDoctorMsg(text, isError) {
  doctorMsg.textContent = text;
  doctorMsg.className = isError ? "warn" : "ok";
}

doctorForm.addEventListener("submit", async e => {
  e.preventDefault();
  const f = new FormData(doctorForm);
  try {
    const t = await api(`/departments/${f.get("department_id")}/call-next?room=${f.get("room")}`, { method: "POST" });
    showDoctorMsg(`Calling ${t.number} (${t.patient_name}) to room ${t.room}`, false);
  } catch (err) {
    showDoctorMsg(err.message, true);
  }
  refresh();
});

document.getElementById("finish-btn").addEventListener("click", async () => {
  const f = new FormData(doctorForm);
  try {
    const r = await api(`/departments/${f.get("department_id")}/finish?room=${f.get("room")}`, { method: "POST" });
    showDoctorMsg(`Finished ${r.finished}`, false);
  } catch (err) {
    showDoctorMsg(err.message, true);
  }
  refresh();
});

doctorForm.department_id.addEventListener("change", () => {
  fillRooms();
  doctorMsg.textContent = "";
  refresh();
});

async function renderDoctorQueue() {
  const deptId = doctorForm.department_id.value;
  if (!deptId) return;
  const queue = await api(`/departments/${deptId}/queue`);
  document.getElementById("doctor-queue").innerHTML = queue.length
    ? queue.map(t => `<tr>
        <td>${esc(t.number)}</td><td>${esc(t.patient_name)}</td>
        <td>${t.status === "waiting" ? "Waiting" : "Room " + t.room}</td>
        <td>${t.status === "waiting" ? fmtMin(t.estimated_wait_minutes) : "–"}</td></tr>`).join("")
    : `<tr><td colspan="4" class="muted">Nobody in the queue</td></tr>`;
}

// ---------- 3. Waiting-room display ----------

async function renderBoard() {
  const stats = await Promise.all(departments.map(d => api(`/departments/${d.id}/stats`)));
  document.getElementById("board").innerHTML = stats.map(s => `
    <div class="tile">
      <h3>${esc(s.department.name)}</h3>
      <div class="big">${s.now_serving.length ? s.now_serving.map(esc).join(", ") : "–"}</div>
      <div class="muted">${s.waiting} waiting · new patients wait ~${fmtMin(s.wait_for_new_patient_minutes)}</div>
    </div>`).join("");
}

// ---------- 4. Dashboard ----------

async function renderDashboard() {
  const stats = await Promise.all(departments.map(d => api(`/departments/${d.id}/stats`)));
  document.getElementById("cards").innerHTML = stats.map(s => {
    const d = s.department, m = s.model;
    return `
    <div class="tile">
      <h3>${esc(d.name)}</h3>
      <dl>
        <dt>Waiting now</dt><dd>${s.waiting}</dd>
        <dt>With doctors</dt><dd>${s.in_consultation}</dd>
        <dt>Done today</dt><dd>${s.done_today}</dd>
        <dt>Arrivals last hour</dt><dd>${s.observed_arrivals_last_hour}</dd>
      </dl>
      <p class="muted"><b>Model (M/M/c)</b></p>
      ${m.stable ? `<dl>
        <dt>Doctor utilization ρ</dt><dd>${Math.round(m.utilization * 100)}%</dd>
        <dt>Chance a patient waits</dt><dd>${Math.round(m.prob_wait * 100)}%</dd>
        <dt>Avg people waiting Lq</dt><dd>${m.avg_queue_length}</dd>
        <dt>Avg wait Wq</dt><dd>${fmtMin(m.avg_wait_minutes)}</dd>
      </dl>` : `<p class="warn">Overloaded: patients arrive faster than ${d.doctors} doctor(s) can see them (ρ = ${m.utilization.toFixed(2)}). Add a doctor.</p>`}
      <form data-id="${d.id}" class="dept-edit">
        <label>Doctors <input name="doctors" type="number" min="1" value="${d.doctors}"></label>
        <label>Min/patient <input name="avg_consult_minutes" type="number" min="1" step="0.5" value="${d.avg_consult_minutes}"></label>
        <label>Arrivals/hr <input name="expected_patients_per_hour" type="number" min="0" step="0.5" value="${d.expected_patients_per_hour}"></label>
        <button type="submit">Update</button>
      </form>
    </div>`;
  }).join("");

  document.querySelectorAll(".dept-edit").forEach(form => form.addEventListener("submit", async e => {
    e.preventDefault();
    const d = departments.find(x => x.id === Number(form.dataset.id));
    const f = new FormData(form);
    await api(`/departments/${d.id}`, {
      method: "PUT",
      body: JSON.stringify({
        ...d,
        doctors: Number(f.get("doctors")),
        avg_consult_minutes: Number(f.get("avg_consult_minutes")),
        expected_patients_per_hour: Number(f.get("expected_patients_per_hour")),
      }),
    });
    await loadDepartments();
    refresh();
  }));
}

// ---------- 5. Beds ----------

const bedsMsg = document.getElementById("beds-msg");
const wardSelect = document.getElementById("ward-select");
let lastWardOptions = ""; // so we only rebuild the dropdown when it actually changes

// Show a green (ok) or red (error) message in any <p>.
function showMsg(el, text, isError) {
  el.textContent = text;
  el.className = isError ? "warn" : "ok";
}

async function renderBeds() {
  const wards = await api("/wards");

  // Ward dropdown, with the free count so reception can see it at a glance.
  const options = wards.map(w =>
    `<option value="${w.id}">${esc(w.name)} (${w.free} free)</option>`).join("");
  if (options !== lastWardOptions) {
    const keep = wardSelect.value;
    wardSelect.innerHTML = options;
    if (keep) wardSelect.value = keep;
    lastWardOptions = options;
  }

  // One card per ward, one coloured square per bed.
  document.getElementById("wards").innerHTML = wards.map(w => `
    <div class="tile">
      <h3>${esc(w.name)}</h3>
      <div class="muted">${w.free} free · ${w.occupied} occupied · ${w.total} total</div>
      <div class="bed-grid">
        ${w.beds.map(b => b.occupied
          ? `<button type="button" class="bed occupied" data-ward="${w.id}" data-bed="${b.number}"
               data-name="${esc(b.patient_name)}" title="Bed ${b.number}: ${esc(b.patient_name)}">${b.number}</button>`
          : `<div class="bed free" title="Bed ${b.number}: free">${b.number}</div>`).join("")}
      </div>
    </div>`).join("");
}

document.getElementById("admit-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const r = await api(`/wards/${f.get("ward_id")}/admit`, {
      method: "POST",
      body: JSON.stringify({ patient_name: f.get("patient_name") }),
    });
    showMsg(bedsMsg, `Admitted ${r.patient_name} to ${r.ward_name}, bed ${r.bed_number}`, false);
    e.target.patient_name.value = "";
  } catch (err) {
    showMsg(bedsMsg, err.message, true);
  }
  refresh();
});

// One click listener on the whole ward area ("event delegation"): it works for
// bed buttons that are redrawn every 5 seconds, without re-adding listeners.
document.getElementById("wards").addEventListener("click", async e => {
  const bed = e.target.closest(".bed.occupied");
  if (!bed) return; // clicked something that isn't an occupied bed
  const { ward, name } = bed.dataset;
  if (!confirm(`Discharge ${name} from bed ${bed.dataset.bed}?`)) return;
  try {
    const r = await api(`/wards/${ward}/discharge?bed=${bed.dataset.bed}`, { method: "POST" });
    showMsg(bedsMsg, `Discharged ${r.discharged} from ${r.ward}, bed ${r.bed_number}`, false);
  } catch (err) {
    showMsg(bedsMsg, err.message, true);
  }
  refresh();
});

// ---------- who may use which screen (step 5) ----------
// The SERVER enforces this on every request (deps.py). Here we only show a
// friendly message instead of buttons that would fail. Admins may use every screen.
const SCREEN_ROLES = {
  reception: ["receptionist"],
  doctor: ["doctor"],
  dashboard: [],                         // empty list = admin only
  beds: ["receptionist", "doctor"],
  display: null,                         // null = public (waiting-room TV)
};

// Returns true if the current screen may be shown; otherwise shows a message
// (or goes to the login page) and returns false.
async function screenAllowed() {
  const section = document.getElementById(currentScreen);
  const roles = SCREEN_ROLES[currentScreen];
  const u = await window.mediq.user;
  const access = roles === null ? "ok" : window.mediq.checkAccess(u, roles.length ? roles : ["admin"]);
  if (access === "login") { window.mediq.goToLogin(); return false; }

  section.classList.toggle("locked", access === "forbidden");
  let msg = section.querySelector(".locked-msg");
  if (access === "forbidden") {
    if (!msg) {
      msg = document.createElement("p");
      msg.className = "locked-msg warn";
      section.append(msg);
    }
    const needed = roles.length ? roles.join(" or ") : "admin";
    const a = /^[aeiou]/i.test(needed) ? "an" : "a";   // "an admin", "a doctor"
    msg.textContent = `This screen needs ${a} ${needed} account. You're signed in as ${u.full_name} (${u.role}).`;
    return false;
  }
  return true;
}

// ---------- refresh loop ----------

async function refresh() {
  try {
    if (!(await screenAllowed())) return;
    if (currentScreen === "doctor") await renderDoctorQueue();
    if (currentScreen === "display") await renderBoard();
    if (currentScreen === "dashboard") await renderDashboard();
    if (currentScreen === "beds") await renderBeds();
  } catch (err) {
    console.error(err);
  }
}

// Open the screen named after "#" in the address, e.g. /index.html#doctor.
// The website menu (site.js) links to the OPD screens this way.
function openScreenFromHash() {
  const id = location.hash.slice(1); // "#doctor" -> "doctor"
  const btn = document.querySelector(`nav.app-tabs button[data-screen="${CSS.escape(id)}"]`);
  if (btn) btn.click(); // reuse the normal tab-switching code above
}
window.addEventListener("hashchange", openScreenFromHash); // menu clicked while already on this page

async function start() {
  const h = await api("/hospital/summary");
  document.getElementById("hospital-name").textContent = h.hospital_name;
  await loadDepartments();
  openScreenFromHash();
  refresh();
  // Poll every 5 seconds so screens stay up to date. (Later: WebSockets.)
  // The dashboard is skipped so it doesn't wipe a form while you type.
  setInterval(() => { if (currentScreen !== "dashboard") refresh(); }, 5000);
}

start();
