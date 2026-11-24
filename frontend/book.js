// Booking page (book.html): department -> doctor -> day -> time -> reason -> book.
// Each choice is a real radio button, so it works with a keyboard and a screen reader.
(async function () {
  const m = window.mediq, { esc } = m;
  const { allowed } = await PT.start({ place: "Book an appointment" });
  if (!allowed) return;

  const $ = id => document.getElementById(id);
  const WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const pick = { dept: null, doctor: null, day: null, slot: null };
  let departments = [], doctors = [];

  // One radio "card": <div class="pt-choice"><input type=radio><label>...</label></div>
  const choice = (name, value, html, { disabled = false, checked = false } = {}) => {
    const id = `${name}-${String(value).replace(/[^a-z0-9]/gi, "")}`;
    return `<div class="pt-choice"><input type="radio" name="${name}" id="${id}" value="${esc(value)}"
              ${disabled ? "disabled" : ""} ${checked ? "checked" : ""}><label for="${id}">${html}</label></div>`;
  };
  const show = (id, on = true) => { $(id).hidden = !on; };

  // Sessions with the same hours share one line: "Every day 09:00–13:00", "Mon, Thu 14:00–17:00"
  function hours(sessions) {
    const byTime = new Map();
    for (const s of sessions) {
      const key = `${PT.time(s.start_time)}–${PT.time(s.end_time)}`;
      byTime.set(key, [...(byTime.get(key) || []), s.weekday]);
    }
    return [...byTime].map(([time, days]) => {
      const unique = [...new Set(days)].sort();
      return `${unique.length === 7 ? "Every day" : unique.map(d => WEEKDAY[d]).join(", ")} ${time}`;
    }).join(" · ");
  }
  const reveal = id => { show(id); $(id).scrollIntoView({ behavior: "smooth", block: "nearest" }); };

  // ---------------------------------------------------------------- 1. department
  departments = await m.api("/departments");
  $("depts").innerHTML = departments.map(d => choice("dept", d.id, esc(d.name))).join("");
  $("depts").addEventListener("change", e => { pick.dept = Number(e.target.value); loadDoctors(); });

  // ---------------------------------------------------------------- 2. doctor
  async function loadDoctors() {
    pick.doctor = pick.day = pick.slot = null;
    ["step-day", "step-time", "step-reason"].forEach(id => show(id, false));
    m.loading($("doctors"), "Finding doctors…");
    reveal("step-doctor");
    doctors = await m.api(`/doctors?department_id=${pick.dept}`);
    $("doctors").innerHTML = doctors.length ? doctors.map(d => choice("doctor", d.id, `${esc(d.full_name)}
        <small>${esc(hours(d.sessions))}</small>`)).join("")
      : `<div class="ui-empty">No doctors take bookings in this department yet. Please try another department or call us.</div>`;
  }
  $("doctors").addEventListener("change", e => { pick.doctor = doctors.find(d => d.id === Number(e.target.value)); loadDays(); });

  // ---------------------------------------------------------------- 3. day
  // The next 30 days on which this doctor works (from their weekly sessions), up to 10 of them
  function loadDays() {
    pick.day = pick.slot = null;
    ["step-time", "step-reason"].forEach(id => show(id, false));
    const works = new Set(pick.doctor.sessions.map(s => s.weekday));
    const days = [];
    for (let i = 0; i <= 30 && days.length < 10; i++) {
      const d = new Date();
      d.setDate(d.getDate() + i);
      if (works.has((d.getDay() + 6) % 7)) days.push(d);    // JS: Sunday = 0; ours: Monday = 0
    }
    const today = PT.isoDate(new Date());
    $("days").innerHTML = days.map(d => choice("day", PT.isoDate(d),
      `${PT.isoDate(d) === today ? "Today" : WEEKDAY[(d.getDay() + 6) % 7]}
       <small>${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</small>`)).join("");
    reveal("step-day");
  }
  $("days").addEventListener("change", e => { pick.day = e.target.value; loadTimes(); });

  // ---------------------------------------------------------------- 4. time
  async function loadTimes() {
    pick.slot = null;
    show("step-reason", false);
    m.loading($("times"), "Checking free times…");
    reveal("step-time");
    const day = await m.api(`/doctors/${pick.doctor.id}/slots?date=${pick.day}&department_id=${pick.dept}`);
    const free = day.slots.filter(s => s.free).length;
    $("time-hint").textContent = free
      ? `${free} free ${day.slot_minutes}-minute slot${free === 1 ? "" : "s"}. Dashed times are taken or already past.`
      : "";
    $("times").innerHTML = free ? day.slots.map(s => choice("slot", s.start, PT.time(s.start), { disabled: !s.free })).join("")
      : `<div class="ui-empty">No free times on this day. Please pick another day.</div>`;
    pick.slots = day.slots;
  }
  $("times").addEventListener("change", e => {
    pick.slot = pick.slots.find(s => s.start === e.target.value);
    drawSummary();
    reveal("step-reason");
    $("reason").focus({ preventScroll: true });
  });

  // ---------------------------------------------------------------- 5. reason + book
  const deptName = () => departments.find(d => d.id === pick.dept).name;
  function drawSummary() {
    $("summary").innerHTML = `<strong>${esc(pick.doctor.full_name)}</strong>, ${esc(deptName())}<br>
      ${esc(PT.day(pick.day))} at <strong>${PT.time(pick.slot.start)}</strong>, Room ${pick.slot.room}`;
  }
  $("reason").addEventListener("input", () => { $("reason-count").textContent = $("reason").value.length; });

  $("book-form").addEventListener("submit", async e => {
    e.preventDefault();
    const msg = $("book-msg"), reason = $("reason").value.trim();
    if (reason.length < 3) {
      $("reason").setAttribute("aria-invalid", "true");
      m.message(msg, { type: "error", title: "Tell us briefly what's wrong",
        text: "Write a few words about your symptoms, for example \"fever for 3 days\"." });
      return $("reason").focus();
    }
    $("reason").removeAttribute("aria-invalid");
    $("book-btn").disabled = true;
    try {
      const a = await m.api("/appointments", { method: "POST", body: JSON.stringify({
        doctor_id: pick.doctor.id, department_id: pick.dept, date: pick.day, slot_start: pick.slot.start, reason }) });
      m.message(msg, { type: "success",
        title: a.status === "accepted" ? "Booked and confirmed" : "Booking sent: waiting for the doctor to accept",
        text: `${a.doctor_name}, ${PT.day(a.date)} at ${PT.time(a.slot_start)}, Room ${a.room}. You'll find it under My appointments.` });
      msg.insertAdjacentHTML("beforeend", `<p><a class="ui-button ui-button--secondary" href="/my-appointments.html">See my appointments</a></p>`);
    } catch (err) {
      m.message(msg, { type: "error", title: "Not booked", text: err.message });
      $("book-btn").disabled = false;
      if (/someone has just booked/.test(err.message)) loadTimes();     // show the fresh free times
    }
  });
})();
