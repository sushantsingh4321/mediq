// schedule.js: the weekly OPD timetable (schedule.html), Module 2.
// Anyone can view it. Admins also see a form to add sessions and a × to remove one.

const { api, esc, user } = window.mediq;

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const hhmm = t => t.slice(0, 5);                 // "09:00:00" -> "09:00"

const deptFilter = document.getElementById("dept-filter");
const slotForm = document.getElementById("slot-form");
const slotMsg = document.getElementById("slot-msg");
let isAdmin = false;
let departments = [];

// ---------- draw the page ----------

async function render() {
  const dept = deptFilter.value;
  const q = dept ? `?department_id=${dept}` : "";
  const [slots, duty] = await Promise.all([api(`/schedule${q}`), api(`/schedule/on-duty${q}`)]);

  // "Hospital time: Monday 10:32 (Asia/Kolkata)". Read the parts straight from
  // the text, so the browser's own time zone can't shift it.
  const [date, clock] = duty.hospital_time.split("T");
  const today = (new Date(date + "T12:00:00").getDay() + 6) % 7;   // JS Sunday=0 -> our Monday=0
  document.getElementById("hospital-time").textContent =
    `Hospital time: ${DAYS[today]} ${clock.slice(0, 5)} (${duty.timezone}).`;

  // On duty now
  const onDutyIds = new Set(duty.on_duty.map(s => s.id));
  document.getElementById("on-duty-list").innerHTML = duty.on_duty.length
    ? duty.on_duty.map(s => `<span class="chip on">${esc(s.doctor_name)}
        <small>${esc(s.department_code)} · Room ${s.room} · until ${hhmm(s.end_time)}</small></span>`).join("")
    : `<span class="muted">No doctor is in OPD right now.</span>`;

  // Weekly grid: one column per day
  document.getElementById("timetable").innerHTML = DAYS.map((day, i) => {
    const todays = slots.filter(s => s.weekday === i);
    return `
      <div class="day ${i === today ? "today" : ""}">
        <h3>${day}${i === today ? ' <span class="badge calling">today</span>' : ""}</h3>
        ${todays.length ? todays.map(s => `
          <div class="slot ${onDutyIds.has(s.id) ? "now" : ""}">
            <b>${hhmm(s.start_time)}–${hhmm(s.end_time)}</b>
            <span>${esc(s.doctor_name)}</span>
            <small>${esc(s.department_name)} · Room ${s.room}</small>
            ${isAdmin ? `<button type="button" class="slot-del" data-id="${s.id}"
                 aria-label="Remove this session" title="Remove">×</button>` : ""}
          </div>`).join("") : `<p class="muted">No OPD</p>`}
      </div>`;
  }).join("");
}

// ---------- admin: add / remove sessions ----------

async function setUpAdminForm() {
  document.getElementById("admin-panel").hidden = false;
  const doctors = await api("/schedule/doctors");
  slotForm.elements.doctor_id.innerHTML = doctors.map(d =>
    `<option value="${d.id}">${esc(d.full_name)}</option>`).join("");
  document.getElementById("no-doctors").hidden = doctors.length > 0;
  slotForm.elements.department_id.innerHTML = departments.map(d =>
    `<option value="${d.id}">${esc(d.name)} (${d.doctors} rooms)</option>`).join("");
  slotForm.elements.weekday.innerHTML = DAYS.map((d, i) => `<option value="${i}">${d}</option>`).join("");
}

slotForm.addEventListener("submit", async e => {
  e.preventDefault();
  const f = new FormData(slotForm);
  try {
    const s = await api("/schedule", {
      method: "POST",
      body: JSON.stringify({
        doctor_id: Number(f.get("doctor_id")),
        department_id: Number(f.get("department_id")),
        weekday: Number(f.get("weekday")),
        start_time: f.get("start_time"),
        end_time: f.get("end_time"),
        room: Number(f.get("room")),
      }),
    });
    slotMsg.className = "ok";
    slotMsg.textContent = `Added: ${s.doctor_name}, ${s.weekday_name} ${hhmm(s.start_time)}–${hhmm(s.end_time)}, ${s.department_name} Room ${s.room}.`;
    render();
  } catch (err) {
    slotMsg.className = "warn";
    slotMsg.textContent = err.message;   // e.g. "Room 1 in General Medicine is already used then by ..."
  }
});

// One listener for every × button (event delegation, LEARN.md 7.6)
document.getElementById("timetable").addEventListener("click", async e => {
  const btn = e.target.closest(".slot-del");
  if (!btn || !confirm("Remove this OPD session?")) return;
  try {
    await api(`/schedule/${btn.dataset.id}`, { method: "DELETE" });
    render();
  } catch (err) {
    alert(err.message);
  }
});

// ---------- start ----------

async function start() {
  departments = await api("/departments");
  deptFilter.innerHTML += departments.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join("");
  deptFilter.addEventListener("change", render);

  isAdmin = (await user)?.role === "admin";
  if (isAdmin) await setUpAdminForm();

  await render();
  setInterval(render, 60000);   // "on duty now" changes slowly: once a minute is enough
}

start().catch(err => console.error(err));
