// Doctor's appointments (doctor-appointments.html): own bookings by day,
// accept / reject with a reason, and the auto-accept switch.
(async function () {
  const m = window.mediq, { esc, svg } = m;
  m.appBar({ role: "Doctor", place: "Appointments" });
  const $ = id => document.getElementById(id);

  // Doctors only (admins may look too)
  const u = await m.user;
  const access = m.checkAccess(u, ["doctor"]);
  if (access !== "ok") {
    if (access === "login") return m.goToLogin();
    document.querySelector("main").innerHTML = `<div id="locked"></div>`;
    return m.message($("locked"), { type: "error", title: "Doctors only",
      text: `This page lists a doctor's own bookings. You're signed in as ${u.full_name} (${u.role}).` });
  }

  const ICON = { clock: '<circle cx="8" cy="8" r="6.25"/><path d="M8 4.5V8l2.5 1.5"/>', ok: '<path d="M3 8.5l3 3 7-7"/>',
                 cross: '<path d="M4 4l8 8M12 4l-8 8"/>', pin: '<path d="M8 14.5s4.5-4.2 4.5-8a4.5 4.5 0 0 0-9 0c0 3.8 4.5 8 4.5 8z"/>' };
  const STATUS = {
    requested: ["warn", "clock", "Needs your answer"], accepted: ["good", "ok", "Accepted"],
    rejected: ["bad", "cross", "Rejected"], cancelled: ["waiting", "cross", "Cancelled by patient"],
    checked_in: ["info", "pin", "Arrived"], completed: ["good", "ok", "Seen"], no_show: ["bad", "cross", "No-show"],
  };
  const pill = s => { const [k, i, w] = STATUS[s]; return `<span class="ui-pill ui-pill--${k}">${svg(ICON[i], 14)}${esc(w)}</span>`; };
  const time = t => t.slice(0, 5);
  const isoDate = d => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const dayTitle = iso => {
    const today = isoDate(new Date()), tomorrow = isoDate(new Date(Date.now() + 864e5));
    const label = new Date(`${iso}T00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
    return iso === today ? `Today, ${label}` : iso === tomorrow ? `Tomorrow, ${label}` : label;
  };

  // ---------------------------------------------------------------- walk-ins
  // Departments this doctor works in (from their OPD sessions); today's first
  const sessions = await m.api(`/schedule?doctor_id=${u.id}`).catch(() => []);
  const depts = new Map();
  const todayWeekday = (new Date().getDay() + 6) % 7;                 // Monday = 0
  for (const s of [...sessions].sort((a, b) => (b.weekday === todayWeekday) - (a.weekday === todayWeekday)))
    depts.set(s.department_id, s.department_name);
  $("w-dept").innerHTML = depts.size ? [...depts].map(([id, name]) => `<option value="${id}">${esc(name)}</option>`).join("")
    : `<option value="">No OPD sessions yet</option>`;

  $("walkin-form").addEventListener("submit", async e => {
    e.preventDefault();
    const msg = $("walkin-msg"), name = $("w-name").value.trim();
    $("w-name").removeAttribute("aria-invalid");
    if (!name) {
      $("w-name").setAttribute("aria-invalid", "true");
      m.message(msg, { type: "error", title: "Enter the patient's name", text: "The name is shown in the queue and on the display." });
      return $("w-name").focus();
    }
    if (!$("w-dept").value) {
      return m.message(msg, { type: "error", title: "No department",
        text: "You have no OPD sessions yet. Ask an admin to add yours on the Doctor schedule page." });
    }
    try {
      const a = await m.api("/doctor/walk-ins", { method: "POST", body: JSON.stringify({
        patient_name: name, department_id: Number($("w-dept").value), reason: $("w-reason").value.trim() }) });
      const ahead = a.people_ahead ? `${a.people_ahead} ${a.people_ahead === 1 ? "person" : "people"} ahead` : "next in line";
      m.message(msg, { type: "success", title: `${a.patient_name}: token ${a.token_number}`,
        text: `Checked in and in the queue (${ahead}). Tell the patient their token number.` });
      $("w-name").value = $("w-reason").value = "";
      $("w-name").focus();
      load();
    } catch (err) {
      m.message(msg, { type: "error", title: "Walk-in not added", text: err.message });
    }
  });

  // ---------------------------------------------------------------- the auto-accept switch
  const drawHint = on => {
    $("auto-hint").textContent = on
      ? "On: every booking in a free slot is accepted and gets a queue token at once."
      : "Off: new bookings wait as \"Needs your answer\" until you accept or reject them.";
  };
  const settings = await m.api("/doctor/settings").catch(() => ({ auto_accept: true }));
  $("auto-accept").checked = settings.auto_accept;
  drawHint(settings.auto_accept);
  $("auto-accept").addEventListener("change", async e => {
    try {
      const s = await m.api("/doctor/settings", { method: "PATCH", body: JSON.stringify({ auto_accept: e.target.checked }) });
      drawHint(s.auto_accept);
      m.toast(s.auto_accept ? "New bookings are accepted automatically" : "New bookings will wait for your answer");
    } catch (err) {
      e.target.checked = !e.target.checked;
      m.message($("msg"), { type: "error", title: "Setting not saved", text: err.message });
    }
  });

  // ---------------------------------------------------------------- the list
  $("from").value = isoDate(new Date());
  let rejecting = null;                      // id of the booking whose reject form is open

  async function load() {
    if (rejecting) return;                   // don't wipe a reason being typed
    const params = new URLSearchParams({ start: $("from").value, days: 14, include_closed: $("show-closed").checked });
    try {
      const days = await m.api(`/doctor/appointments?${params}`);
      const waiting = days.flatMap(d => d.appointments).filter(a => a.status === "requested").length;
      $("requests-note").hidden = !waiting;
      if (waiting) m.message($("requests-note"), { type: "info", title: `${waiting} booking${waiting === 1 ? "" : "s"} need${waiting === 1 ? "s" : ""} your answer`,
        text: "Accept to give the patient a token, or reject with a short reason." });
      $("days").innerHTML = days.length ? days.map(d => `
        <section class="pt-step" aria-labelledby="day-${d.date}">
          <h2 id="day-${d.date}">${esc(dayTitle(d.date))} <span class="ph-sub">${d.appointments.length} booking${d.appointments.length === 1 ? "" : "s"}</span></h2>
          <div class="ui-table-wrap"><table class="ui-table">
            <caption class="ui-sr-only">Bookings on ${esc(dayTitle(d.date))}</caption>
            <thead><tr><th scope="col">Time</th><th scope="col">Patient</th><th scope="col">Reason</th>
              <th scope="col">Token</th><th scope="col">Status</th><th scope="col"><span class="ui-sr-only">Actions</span></th></tr></thead>
            <tbody>${d.appointments.map(row).join("")}</tbody></table></div>
        </section>`).join("")
        : `<div class="ui-empty">No bookings in these two weeks.</div>`;
    } catch (err) {
      m.message($("msg"), { type: "error", title: "Couldn't load your appointments", text: err.message });
    }
  }

  const TOKEN_WORD = { booked: "not here yet", waiting: "waiting", in_consultation: "with a doctor", done: "seen", cancelled: "cancelled" };
  const todayIso = () => isoDate(new Date());

  function row(a) {
    const actions = [];
    if (a.date === todayIso() && (a.status === "accepted" || a.status === "no_show"))
      actions.push(`<button class="ui-button ui-button--secondary" type="button" data-checkin="${a.id}">${a.status === "no_show" ? "Check in anyway" : "Check in"}</button>`);
    if (a.status === "requested") actions.push(`<button class="ui-button ui-button--action" type="button" data-accept="${a.id}">Accept</button>`);
    if (a.status === "requested" || a.status === "accepted")
      actions.push(`<button class="ui-button ui-button--danger" type="button" data-reject="${a.id}">Reject</button>`);
    return `<tr id="appt-${a.id}">
      <td><strong>${time(a.slot_start)}</strong><small>Room ${a.room ?? "–"}</small></td>
      <td>${esc(a.patient_name)}${a.source === "walk_in" ? "<small>Walk-in</small>" : ""}</td>
      <td>${esc(a.reason)}${a.reject_reason ? `<small>Your reason: ${esc(a.reject_reason)}</small>` : ""}</td>
      <td>${a.token_number ? `<strong>${esc(a.token_number)}</strong><small>${esc(TOKEN_WORD[a.token_status] || "")}</small>` : "–"}</td>
      <td>${pill(a.status)}</td>
      <td><div class="ph-actions" style="margin: 0">${actions.join("")}</div></td></tr>`;
  }

  // ---------------------------------------------------------------- accept / reject
  $("days").addEventListener("click", async e => {
    const acc = e.target.closest("[data-accept]"), rej = e.target.closest("[data-reject]");
    const chk = e.target.closest("[data-checkin]");
    if (chk) {
      chk.disabled = true;
      try {
        const a = await m.api(`/appointments/${chk.dataset.checkin}/checkin`, { method: "POST" });
        m.toast(`${a.patient_name} checked in: ${a.token_number} is in the queue`);
      } catch (err) { m.message($("msg"), { type: "error", title: "Not checked in", text: err.message }); }
      return load();
    }
    if (acc) {
      acc.disabled = true;
      try {
        const a = await m.api(`/appointments/${acc.dataset.accept}/accept`, { method: "POST" });
        m.toast(`Accepted: ${a.patient_name}, ${time(a.slot_start)}, token ${a.token_number}`);
      } catch (err) { m.message($("msg"), { type: "error", title: "Not accepted", text: err.message }); }
      load();
    }
    if (rej) openReject(Number(rej.dataset.reject));
  });

  function openReject(id) {
    closeReject();
    rejecting = id;
    $(`appt-${id}`).insertAdjacentHTML("afterend", `<tr id="reject-row"><td colspan="6">
      <form class="ph-form" id="reject-form">
        <div class="ui-field"><label for="reject-reason">Reason for the patient (they will see this)</label>
          <textarea class="ui-input" id="reject-reason" maxlength="300" rows="2"
            placeholder="For example: I'm in surgery that morning. Please book Tuesday or Dr. Patel."></textarea></div>
        <div class="ph-actions" style="margin: 0">
          <button class="ui-button ui-button--danger" type="submit">Reject booking</button>
          <button class="ui-button ui-button--secondary" type="button" id="reject-cancel">Keep booking</button></div>
      </form></td></tr>`);
    $("reject-reason").focus();
    $("reject-cancel").addEventListener("click", () => { closeReject(); load(); });
    $("reject-form").addEventListener("submit", async e => {
      e.preventDefault();
      const reason = $("reject-reason").value.trim();
      if (reason.length < 3) {
        $("reject-reason").setAttribute("aria-invalid", "true");
        return m.message($("msg"), { type: "error", title: "Write a short reason",
          text: "The patient sees it, so say why and what they can do instead." });
      }
      try {
        const a = await m.api(`/appointments/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
        m.toast(`Rejected: ${a.patient_name}, ${time(a.slot_start)}. The patient has been told.`);
        m.clearMessage($("msg"));
      } catch (err) { m.message($("msg"), { type: "error", title: "Not rejected", text: err.message }); }
      closeReject();
      load();
    });
  }
  function closeReject() { $("reject-row")?.remove(); rejecting = null; }

  $("from").addEventListener("change", load);
  $("show-closed").addEventListener("change", load);
  $("filters").addEventListener("submit", e => { e.preventDefault(); load(); });

  m.loading($("days"), "Loading your appointments…");
  await load();
  setInterval(() => { if (!document.hidden) load(); }, 20000);   // new bookings arrive by themselves
})();
