// ambulance.js: the ambulance dispatch page (ambulance.html), Module 3.
// Refreshes every 5 seconds so every dispatcher sees the same picture.

const { api, esc, user } = window.mediq;

const STATUS_LABEL = { available: "available", on_trip: "on trip", maintenance: "maintenance" };
const fmtTime = iso => iso ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : "–";
const minutesAgo = iso => Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));

let fleet = [];

function show(id, text, isError) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = isError ? "warn" : "ok";
}

// ---------- drawing ----------

function freeAmbulanceOptions() {
  const free = fleet.filter(a => a.status === "available");
  return free.length
    ? free.map(a => `<option value="${a.id}">${esc(a.code)} · ${esc(a.location)}</option>`).join("")
    : `<option value="">No ambulance free</option>`;
}

function drawOpenTrips(trips) {
  document.getElementById("open-trips").innerHTML = trips.length ? trips.map(t => `
    <div class="trip ${t.status}">
      <div class="trip-main">
        <div><b>#${t.id} ${esc(t.patient_name)}</b> <span class="badge ${t.status === "requested" ? "failed" : "calling"}">${t.status}</span></div>
        <div>${esc(t.pickup)} → ${esc(t.destination)}</div>
        <small class="muted">Call ${esc(t.contact_phone)} · requested ${minutesAgo(t.requested_at)} min ago
          ${t.notes ? " · " + esc(t.notes) : ""}</small>
      </div>
      <div class="trip-actions">
        ${t.status === "requested" ? `
          <select class="pick" data-id="${t.id}" aria-label="Ambulance for trip ${t.id}">${freeAmbulanceOptions()}</select>
          <button type="button" data-act="assign" data-id="${t.id}">Send</button>` : `
          <span><b>${esc(t.ambulance_code)}</b> since ${fmtTime(t.assigned_at)}</span>
          <button type="button" data-act="complete" data-id="${t.id}">Arrived / complete</button>`}
        <button type="button" class="secondary" data-act="cancel" data-id="${t.id}">Cancel</button>
      </div>
    </div>`).join("") : `<p class="muted">No open trips.</p>`;
}

function drawFleet() {
  const n = s => fleet.filter(a => a.status === s).length;
  document.getElementById("fleet-summary").textContent =
    `${n("available")} available · ${n("on_trip")} on trip · ${n("maintenance")} in maintenance. Updates every 5 seconds.`;

  document.getElementById("fleet").innerHTML = fleet.map(a => `
    <div class="tile amb ${a.status}">
      <h3>${esc(a.code)} <span class="badge amb-${a.status}">${STATUS_LABEL[a.status]}</span></h3>
      <div class="muted">${esc(a.vehicle_number)}</div>
      <div>Driver: ${esc(a.driver_name)} · ${esc(a.driver_phone)}</div>
      <div>At: ${esc(a.location)} <small class="muted">(${minutesAgo(a.updated_at)} min ago)</small></div>
      ${a.current_trip ? `<div class="on-trip">Trip #${a.current_trip.id}: ${esc(a.current_trip.patient_name)},
                           ${esc(a.current_trip.pickup)} → ${esc(a.current_trip.destination)}</div>` : ""}
      <div class="amb-actions">
        <button type="button" class="secondary" data-act="move" data-amb="${a.id}">Update location</button>
        ${a.status === "available" ? `<button type="button" class="secondary" data-act="service-out" data-amb="${a.id}">Maintenance</button>` : ""}
        ${a.status === "maintenance" ? `<button type="button" class="secondary" data-act="service-in" data-amb="${a.id}">Back in service</button>` : ""}
      </div>
    </div>`).join("");
}

function drawPast(trips) {
  document.getElementById("past-trips").innerHTML = trips.length ? trips.map(t => `<tr>
      <td>${t.id}</td><td>${esc(t.patient_name)}</td>
      <td>${esc(t.pickup)} → ${esc(t.destination)}</td><td>${esc(t.ambulance_code || "–")}</td>
      <td><span class="badge ${t.status === "completed" ? "done" : "pending"}">${t.status}</span></td>
      <td>${fmtTime(t.finished_at)}</td></tr>`).join("")
    : `<tr><td colspan="6" class="muted">Nothing yet</td></tr>`;
}

async function render() {
  // Don't redraw while someone has an ambulance dropdown open: it would close under them.
  if (document.activeElement?.matches("select.pick")) return;
  // Remember which ambulance was picked for each trip, to put it back after redrawing.
  const picked = {};
  document.querySelectorAll("select.pick").forEach(s => (picked[s.dataset.id] = s.value));

  const [amb, open, past] = await Promise.all([
    api("/ambulances"),
    api("/ambulances/trips?status=requested,assigned"),
    api("/ambulances/trips?status=completed,cancelled&limit=10"),
  ]);
  fleet = amb;
  drawFleet();
  drawOpenTrips([...open].reverse());   // oldest request first: it has waited longest
  drawPast(past);
  document.querySelectorAll("select.pick").forEach(s => {
    if (picked[s.dataset.id] && [...s.options].some(o => o.value === picked[s.dataset.id])) s.value = picked[s.dataset.id];
  });
}

// ---------- actions ----------

document.getElementById("trip-form").addEventListener("submit", async e => {
  e.preventDefault();
  const form = e.target, f = new FormData(form);
  try {
    const trip = await api("/ambulances/trips", {
      method: "POST",
      body: JSON.stringify({
        patient_name: f.get("patient_name"), contact_phone: f.get("contact_phone"),
        pickup: f.get("pickup"), destination: f.get("destination"), notes: f.get("notes"),
      }),
    });
    let msg = `Request #${trip.id} logged.`;
    if (f.get("send_now")) {
      try {
        const sent = await api(`/ambulances/trips/${trip.id}/assign`, { method: "POST", body: "{}" });
        msg += ` ${sent.ambulance_code} is on its way.`;
      } catch (err) {
        msg += ` Not sent yet: ${err.message}`;
      }
    }
    show("trip-msg", msg, false);
    form.reset();
  } catch (err) {
    show("trip-msg", err.message, true);
  }
  render();
});

// One listener for all buttons on the page (event delegation, LEARN.md 7.6)
document.querySelector("main").addEventListener("click", async e => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const { act, id, amb } = btn.dataset;
  try {
    if (act === "assign") {
      const chosen = document.querySelector(`select.pick[data-id="${id}"]`).value;
      if (!chosen) throw new Error("No ambulance is free right now.");
      const t = await api(`/ambulances/trips/${id}/assign`, { method: "POST", body: JSON.stringify({ ambulance_id: Number(chosen) }) });
      show("trip-msg", `${t.ambulance_code} sent to ${t.patient_name}.`, false);
    } else if (act === "complete") {
      await api(`/ambulances/trips/${id}/complete`, { method: "POST" });
      show("trip-msg", `Trip #${id} completed. The ambulance is free again.`, false);
    } else if (act === "cancel") {
      if (!confirm(`Cancel trip #${id}?`)) return;
      await api(`/ambulances/trips/${id}/cancel`, { method: "POST" });
      show("trip-msg", `Trip #${id} cancelled.`, false);
    } else if (act === "move") {
      const where = prompt("Where is this ambulance now?");
      if (!where || !where.trim()) return;
      await api(`/ambulances/${amb}`, { method: "PATCH", body: JSON.stringify({ location: where.trim() }) });
    } else if (act === "service-out" || act === "service-in") {
      const status = act === "service-out" ? "maintenance" : "available";
      await api(`/ambulances/${amb}`, { method: "PATCH", body: JSON.stringify({ status }) });
    }
  } catch (err) {
    show("trip-msg", err.message, true);
  }
  render();
});

// Admins: add an ambulance
document.getElementById("ambulance-form").addEventListener("submit", async e => {
  e.preventDefault();
  const form = e.target, f = new FormData(form);
  try {
    const a = await api("/ambulances", { method: "POST", body: JSON.stringify(Object.fromEntries(f)) });
    show("ambulance-msg", `${a.code} added.`, false);
    form.reset();
    render();
  } catch (err) {
    show("ambulance-msg", err.message, true);
  }
});

// ---------- start ----------

async function start() {
  const me = await user;
  if (!me || me.role === "patient") return;      // site.js shows login / "No access"
  if (me.role === "admin") document.getElementById("add-ambulance").hidden = false;
  await render();
  setInterval(render, 5000);
}

start().catch(err => console.error(err));
