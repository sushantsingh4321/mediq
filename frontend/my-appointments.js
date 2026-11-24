// My appointments (my-appointments.html): the patient's bookings, live.
(async function () {
  const m = window.mediq, { esc } = m;
  const { allowed } = await PT.start({ place: "My appointments" });
  if (!allowed) return;

  const $ = id => document.getElementById(id);
  const ACTIVE = new Set(["requested", "accepted", "checked_in"]);

  const hhmm = iso => iso.slice(11, 16);           // "2026-11-30T09:15:00" -> "09:15"
  const minutes = n => `about ${Math.round(n)} minute${Math.round(n) === 1 ? "" : "s"}`;
  const ahead = n => `${n} ${n === 1 ? "person" : "people"} ahead of you`;
  // "You're next." / "2 people ahead of you, about 7 minutes."
  const waitLine = (n, mins) => (!n ? "You're next." : `${ahead(n)}, ${minutes(mins ?? 0)}.`);

  // The "on the day" part of a card: arrive, wait, get called
  function today(a) {
    if (a.token_status === "in_consultation") {
      return `<div class="pt-turn" role="status"><strong>It's your turn.</strong> Please go to Room ${a.token_room}.</div>`;
    }
    if (a.status === "checked_in") {
      return `<div class="pt-live"><p><strong>You're checked in.</strong> ${waitLine(a.people_ahead, a.estimated_wait_minutes)}</p>
        <p class="ui-hint">Keep this page open: it will show your room when the doctor calls you.</p></div>`;
    }
    if (a.status === "no_show") {
      return `<p>You didn't check in by ${hhmm(a.missed_after)}, so this booking was marked as missed.
        If you're at the hospital, speak to the doctor's assistant, or <a href="/book.html">book again</a>.</p>`;
    }
    if (a.status !== "accepted" || a.date !== PT.isoDate(new Date())) return "";
    const estimate = a.people_ahead !== null
      ? `<p class="ui-hint">If you checked in now: ${waitLine(a.people_ahead, a.estimated_wait_minutes)}</p>` : "";
    return a.can_check_in
      ? `<div class="pt-live"><button class="ui-button ui-button--action ui-button--large" type="button" data-checkin="${a.id}">I've arrived</button>
          <p class="ui-hint">Press this when you are at the hospital. Check-in closes at ${hhmm(a.missed_after)}.</p>${estimate}</div>`
      : `<p class="ui-hint">Check-in opens at ${hhmm(a.check_in_opens_at)}, 1 hour before your appointment.</p>${estimate}`;
  }

  function card(a) {
    const when = `${PT.day(a.date)}, ${PT.time(a.slot_start)}`;
    const cancel = a.can_cancel
      ? `<button class="ui-button ui-button--danger" type="button" data-cancel="${a.id}">Cancel booking</button>`
      : ACTIVE.has(a.status) && a.status !== "checked_in"
        ? `<p class="ui-hint">Cancelling closed 1 hour before the appointment. Please call the hospital to change it.</p>` : "";
    return `<li class="pt-card ${ACTIVE.has(a.status) ? "" : "pt-card--past"}">
      <p class="pt-when">${esc(when)}</p>
      <h3>${esc(a.doctor_name)} <span class="ph-sub">${esc(a.department_name)}${a.room ? `, Room ${a.room}` : ""}</span></h3>
      <p>${PT.statusPill(a.status)}</p>
      ${a.token_number && ACTIVE.has(a.status) ? `<p>Your token: <strong class="pt-token">${esc(a.token_number)}</strong></p>` : ""}
      ${today(a)}
      ${a.status === "rejected" && a.reject_reason ? `<p><strong>The doctor's reason:</strong> ${esc(a.reject_reason)}</p>` : ""}
      ${a.status === "requested" ? `<p class="ui-hint">The doctor accepts bookings one by one. This page will show the answer.</p>` : ""}
      <p class="ui-hint">You wrote: "${esc(a.reason)}"</p>
      ${cancel ? `<div class="ph-actions">${cancel}</div>` : ""}
    </li>`;
  }

  async function load() {
    try {
      const list = await m.api("/appointments/me");
      const today = PT.isoDate(new Date());
      const upcoming = list.filter(a => a.date >= today && (ACTIVE.has(a.status) || a.date === today));
      const past = list.filter(a => !upcoming.includes(a));
      $("upcoming").innerHTML = upcoming.length ? upcoming.map(card).join("")
        : `<li class="ui-empty">No upcoming appointments. <a href="/book.html">Book one</a>.</li>`;
      $("past").innerHTML = past.map(card).join("");
      $("past-section").hidden = !past.length;

    } catch (err) {
      m.message($("msg"), { type: "error", title: "Couldn't load your appointments", text: err.message });
    }
  }

  document.querySelector("main").addEventListener("click", async e => {
    const arrived = e.target.closest("[data-checkin]");
    if (arrived) {
      arrived.disabled = true;
      try {
        const a = await m.api(`/appointments/${arrived.dataset.checkin}/checkin`, { method: "POST" });
        m.message($("msg"), { type: "success", title: `Checked in. Your token is ${a.token_number}`,
          text: `${waitLine(a.people_ahead, a.estimated_wait_minutes)} Please wait near Room ${a.room}.` });
      } catch (err) {
        m.message($("msg"), { type: "error", title: "Not checked in", text: err.message });
      }
      return load();
    }
    const b = e.target.closest("[data-cancel]");
    if (!b || !confirm("Cancel this appointment? The time will be offered to someone else.")) return;
    b.disabled = true;
    try {
      const a = await m.api(`/appointments/${b.dataset.cancel}/cancel`, { method: "POST" });
      m.message($("msg"), { type: "success", title: "Booking cancelled",
        text: `${a.doctor_name}, ${PT.day(a.date)} at ${PT.time(a.slot_start)}.` });
      load();
    } catch (err) {
      m.message($("msg"), { type: "error", title: "Not cancelled", text: err.message });
      b.disabled = false;
    }
  });

  m.loading($("upcoming"), "Loading your appointments…");
  await load();
  setInterval(() => { if (!document.hidden) load(); }, 15000);          // "live" status
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
  document.addEventListener("mediq:notification", load);          // a banner arrived: show the new status too
})();
