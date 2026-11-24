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

let currentScreen = "doctor";
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
  if (canAct) rxFillCurrentPatient(queue);
  document.getElementById("doctor-queue").innerHTML = queue.length
    ? queue.map(t => `<tr>
        <td>${esc(t.number)}</td><td>${esc(t.patient_name)}</td>
        <td>${t.status === "waiting" ? "Waiting" : "Room " + t.room}</td>
        <td>${t.status === "waiting" ? fmtMin(t.estimated_wait_minutes) : "–"}</td></tr>`).join("")
    : `<tr><td colspan="4" class="muted">Nobody in the queue</td></tr>`;
}

// ---------- 2b. Doctor: Add prescription (Module 4) ----------
// The doctor picks medicines, the list is saved as one prescription, and the
// pharmacy sees it on its Dispense screen.

const rxForm = document.getElementById("rx-form");
const rxMsg = document.getElementById("rx-msg");
const rxLines = [];                 // [{ med, dose, duration_days, quantity, instructions }]
let rxTokenId = null;               // the OPD token of the patient in the room, if any
let rxAutoName = "";                // the name we filled in automatically (so we don't overwrite typing)
const rxPicker = PH.medicinePicker(document.getElementById("rx-med"), { onPick: rxSuggestQuantity });

// "1-0-1" for 5 days = 2 a day × 5 = 10 tablets. Syrups, inhalers... = 1 pack.
function rxSuggestQuantity() {
  const med = rxPicker.selected;
  if (!med) return;
  const perDay = document.getElementById("rx-dose").value.split("-").reduce((sum, x) => sum + (parseFloat(x) || 0), 0);
  const days = Number(document.getElementById("rx-days").value) || 0;
  const countable = ["tablet", "capsule"].includes(med.unit);
  document.getElementById("rx-qty").value = countable && perDay && days ? Math.ceil(perDay * days) : 1;
}
document.getElementById("rx-dose").addEventListener("input", rxSuggestQuantity);
document.getElementById("rx-days").addEventListener("input", rxSuggestQuantity);

function drawRxLines() {
  document.getElementById("rx-items").innerHTML = rxLines.map((l, i) => `<tr>
    <td>${esc(l.med.display_name)} ${l.med.schedule !== "OTC" ? `<small>(Schedule ${esc(l.med.schedule)})</small>` : ""}</td>
    <td>${esc(l.dose)}</td><td>${l.duration_days}</td><td>${l.quantity} ${esc(l.med.unit)}${l.quantity === 1 ? "" : "s"}</td>
    <td>${esc(l.instructions || "–")}</td>
    <td><button type="button" class="secondary" data-remove="${i}">Remove</button></td></tr>`).join("");
}

document.getElementById("rx-add-btn").addEventListener("click", () => {
  const med = rxPicker.selected;
  const dose = document.getElementById("rx-dose").value.trim();
  const days = Number(document.getElementById("rx-days").value);
  const qty = Number(document.getElementById("rx-qty").value);
  if (!med) return showMsg(rxMsg, "Pick the medicine from the suggestions under the box (type 2 or more letters).", true);
  if (!dose) return showMsg(rxMsg, "Enter the dose, for example 1-0-1 (morning-afternoon-night).", true);
  if (!(days >= 1)) return showMsg(rxMsg, "Enter how many days, 1 or more.", true);
  if (!(qty >= 1)) return showMsg(rxMsg, "Enter the total quantity, 1 or more.", true);
  rxLines.push({ med, dose, duration_days: days, quantity: qty,
                 instructions: document.getElementById("rx-instr").value });
  drawRxLines();
  rxMsg.textContent = "";
  rxPicker.clear();
  document.getElementById("rx-qty").value = "";
  document.getElementById("rx-med").focus();
});

document.getElementById("rx-items").addEventListener("click", e => {
  const b = e.target.closest("[data-remove]");
  if (b) { rxLines.splice(Number(b.dataset.remove), 1); drawRxLines(); }
});

rxForm.addEventListener("submit", async e => {
  e.preventDefault();
  const name = rxForm.patient_name.value.trim();
  if (!name) { rxForm.patient_name.focus(); return showMsg(rxMsg, "Enter the patient's name.", true); }
  if (!rxLines.length) return showMsg(rxMsg, "Add at least one medicine first (\"Add medicine\").", true);
  try {
    const rx = await api("/pharmacy/prescriptions", {
      method: "POST",
      body: JSON.stringify({
        patient_name: name,
        token_id: name === rxAutoName ? rxTokenId : null,   // only link the token if it's the same patient
        notes: rxForm.notes.value.trim(),
        items: rxLines.map(l => ({ medicine_id: l.med.id, dose: l.dose, duration_days: l.duration_days,
                                   quantity: l.quantity, instructions: l.instructions })),
      }),
    });
    showMsg(rxMsg, `Prescription #${rx.id} saved for ${rx.patient_name} (${rx.items.length} medicine${rx.items.length === 1 ? "" : "s"}). The pharmacy can dispense it now.`, false);
    rxLines.length = 0;
    drawRxLines();
    rxForm.notes.value = "";
  } catch (err) {
    showMsg(rxMsg, `Prescription not saved: ${err.message}`, true);
  }
});

// Called after the queue is drawn: fill in the patient who is in this doctor's room now.
function rxFillCurrentPatient(queue) {
  const room = Number(doctorForm.room.value);
  const inRoom = queue.find(t => t.status === "in_consultation" && t.room === room);
  const box = rxForm.patient_name;
  if (inRoom && (box.value === "" || box.value === rxAutoName)) {
    box.value = rxAutoName = inRoom.patient_name;
    rxTokenId = inRoom.id;
    document.getElementById("rx-token-note").textContent = `Token ${inRoom.number}, in room ${room} now`;
  } else if (!inRoom && box.value === rxAutoName) {
    document.getElementById("rx-token-note").textContent = "";
    rxTokenId = null;
  }
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
      <form data-id="${d.id}" class="dept-edit" data-action>
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

  // Ward dropdown, with the free count so staff can see it at a glance.
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
        ${w.beds.map(b => b.occupied && canAct
          ? `<button type="button" class="bed occupied" data-ward="${w.id}" data-bed="${b.number}"
               data-name="${esc(b.patient_name)}" title="Bed ${b.number}: ${esc(b.patient_name)}">${b.number}</button>`
          : b.occupied   // view only: show the bed, but it can't be clicked
            ? `<div class="bed occupied" title="Bed ${b.number}: occupied (${esc(b.patient_name)})">${b.number}</div>`
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

// ---------- who may USE which screen ----------
// Everyone can LOOK at every screen. Only these roles can press its buttons
// (admins can press everything). The SERVER enforces this too (deps.py), and
// hides full patient names from non-staff, so this is only for a friendly page.
const SCREEN_ROLES = {
  doctor: ["doctor"],
  dashboard: [],                         // empty list = admin only
  beds: ["doctor"],
  display: null,                         // null = nothing to press (waiting-room TV)
};

// Can the current user press this screen's buttons?
let canAct = false;

// Turn the staff-only controls on or off. A <form data-action> means every control inside it.
// Called again after each redraw, because the Dashboard draws new forms every 5 seconds.
function setActionControls(section) {
  section.querySelectorAll("[data-action]").forEach(el => {
    const controls = el.tagName === "FORM" ? [...el.elements] : [el];
    controls.forEach(c => { c.disabled = !canAct; });
  });
}

// Always shows the screen. If the user may not act on it, turns off every
// [data-action] control and shows a short "view only" note instead.
async function screenAllowed() {
  const section = document.getElementById(currentScreen);
  const roles = SCREEN_ROLES[currentScreen];
  const u = await window.mediq.user;
  canAct = roles === null || window.mediq.checkAccess(u, roles.length ? roles : ["admin"]) === "ok";

  setActionControls(section);

  let note = section.querySelector(".view-note");
  if (canAct) { note?.remove(); return true; }
  if (!note) {
    note = document.createElement("p");
    note.className = "view-note hint";
    section.querySelector("h2").after(note);   // right under the screen title
  }
  const needed = roles.length ? roles.join(" or ") : "admin";
  const a = /^[aeiou]/i.test(needed) ? "an" : "a";   // "an admin", "a doctor"
  note.innerHTML = u
    ? `View only. The buttons need ${a} ${needed} account (you're signed in as ${window.mediq.esc(u.role)}).`
    : `View only. Patient names show as initials. <a href="/login.html">Staff log in</a> to use the buttons.`;
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
    setActionControls(document.getElementById(currentScreen));
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
