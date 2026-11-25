// home.js: the home page (home.html).
// It reuses the helpers that site.js shares on window.mediq:
//   api(path)  call the backend      esc(text)  make text safe for HTML
//   data       the site data from GET /api/site (a Promise)

const { api, esc, data } = window.mediq;

// Line icons (24x24, drawn in the text colour) for the speciality cards and hospital pins
const icon = (paths, size = 26) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const SPEC_ICON = {
  "Cardiology": '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/><path d="M6 12h2.5l1.5-2.5 2 5 1.5-2.5H18"/>',
  "Neurology": '<path d="M12 5a3 3 0 0 0-5.5 1.5A3 3 0 0 0 4.5 11a3 3 0 0 0 1 5A3 3 0 0 0 9 19.5a3 3 0 0 0 3-1.5"/><path d="M12 5a3 3 0 0 1 5.5 1.5A3 3 0 0 1 19.5 11a3 3 0 0 1-1 5 3 3 0 0 1-3.5 3.5A3 3 0 0 1 12 18V5z"/>',
  "Orthopaedics": '<path d="M8 4.5a2.1 2.1 0 0 0-3.3 2.6A2.1 2.1 0 0 0 6.5 10l7.5 7.5a2.1 2.1 0 0 0 2.9 1.8 2.1 2.1 0 0 0 2.6-3.3 2.1 2.1 0 0 0-1.8-2.9L10.2 5.6A2.1 2.1 0 0 0 8 4.5z"/>',
  "Oncology": '<path d="M12 3c-1.8 0-3 1.4-3 3.2 0 2.3 3 6.3 3 6.3s3-4 3-6.3C15 4.4 13.8 3 12 3z"/><path d="M10.5 11L6 21l3-1.2L10.6 22 13.5 15M13.5 11L18 21l-3-1.2-1.6 2.2"/>',
  "Paediatrics": '<circle cx="12" cy="8" r="4"/><path d="M10.5 7.5h.01M13.5 7.5h.01M10.6 9.6a2 2 0 0 0 2.8 0"/><path d="M5.5 21a6.5 6.5 0 0 1 13 0"/>',
  default: '<path d="M6 3v5a4 4 0 0 0 8 0V3"/><path d="M10 12v2a5 5 0 0 0 10 0v-2"/><circle cx="20" cy="10" r="2"/>',
};
const PIN = '<path d="M12 21s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="9" r="2.5"/>';

// ---------- 1. lists from the data file ----------

data.then(d => {
  // Specialities: one card each, with its icon and a few of the conditions it treats.
  document.getElementById("spec-list").innerHTML = d.specialities.map(s => `
    <li><a class="spec-card" href="?speciality=${encodeURIComponent(s.name)}#enquiry">
      <span class="spec-icon">${icon(SPEC_ICON[s.name] || SPEC_ICON.default)}</span>
      <strong>${esc(s.name)}</strong>
      <small>${s.conditions.slice(0, 3).map(esc).join(", ")}</small>
      <span class="go">Ask us</span>
    </a></li>`).join("");

  // The three facts in the hero, counted from the data (never typed in by hand)
  document.getElementById("fact-hospitals").textContent = d.hospitals.length;
  document.getElementById("fact-states").textContent = new Set(d.hospitals.map(h => h.state)).size;
  document.getElementById("fact-specialities").textContent = d.specialities.length;

  // Hospitals grouped by state.
  const byState = {};
  for (const h of d.hospitals) (byState[h.state] ||= []).push(h);
  document.getElementById("hospital-list").innerHTML = Object.entries(byState).map(([state, list]) => `
    <div>
      <h3>${esc(state)}</h3>
      <ul>${list.map(h => `<li>${icon(PIN, 18)}<span><b>${esc(h.name)}</b><small>${esc(h.area)}, ${esc(h.city)}</small></span></li>`).join("")}</ul>
    </div>`).join("");

  // Enquiry form dropdowns.
  const form = document.getElementById("enquiry-form");
  const cc = form.elements.country_code;
  cc.innerHTML = d.country_codes.map(c =>
    `<option value="${esc(c.code)}" ${c.code === d.default_country_code ? "selected" : ""}>${esc(c.code)} ${esc(c.country)}</option>`).join("");
  form.elements.speciality.innerHTML += d.specialities.map(s =>
    `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join("");

  // Links like /?speciality=Cardiology#enquiry pre-select the speciality.
  const wanted = new URLSearchParams(location.search).get("speciality");
  if (wanted) form.elements.speciality.value = wanted;
}).catch(err => console.error(err));

// ---------- 2. the enquiry form ----------

const enquiryForm = document.getElementById("enquiry-form");
const enquiryMsg = document.getElementById("enquiry-msg");

enquiryForm.addEventListener("submit", async e => {
  e.preventDefault();          // stop the browser reloading the page
  const f = new FormData(enquiryForm);
  try {
    const saved = await api("/enquiries", {
      method: "POST",
      body: JSON.stringify({
        name: f.get("name"),
        country_code: f.get("country_code"),
        mobile: String(f.get("mobile")).replace(/\D/g, ""), // keep digits only: "98765 43210" -> "9876543210"
        speciality: f.get("speciality"),
        consent: f.get("consent") === "on",                 // a ticked checkbox sends "on"
      }),
    });
    enquiryMsg.className = "ok full";
    enquiryMsg.textContent = `Thank you, ${saved.name}. We'll call you on ${saved.country_code} ${saved.mobile} soon (enquiry #${saved.id}).`;
    enquiryForm.reset();
  } catch (err) {
    enquiryMsg.className = "warn full";
    enquiryMsg.textContent = err.message;
  }
});

// ---------- 3. live numbers: the hero list and the navy band ----------

async function renderLive() {
  try {
    const depts = await api("/departments");
    const stats = await Promise.all(depts.map(d => api(`/departments/${d.id}/stats`)));
    drawHeroWaits(stats);

    const waiting = stats.reduce((sum, s) => sum + s.waiting, 0);
    document.getElementById("stat-opd").textContent = String(waiting);

    const wards = await api("/wards/availability");
    const free = wards.reduce((sum, w) => sum + w.free, 0);
    document.getElementById("stat-beds").textContent = String(free);

    const duty = await api("/schedule/on-duty");   // Module 2
    document.getElementById("stat-duty").textContent = String(duty.on_duty.length);

    const amb = await api("/ambulances/availability");   // Module 3 (counts only)
    document.getElementById("stat-amb").textContent = String(amb.available);
  } catch (err) {
    console.error(err);
  }
}

// The hero's live list: the wait a NEW patient would have now, per department
function drawHeroWaits(stats) {
  const list = document.getElementById("hero-waits");
  if (!list) return;
  if (!stats.length) {
    list.innerHTML = `<li class="hero-waits-empty">No OPD departments yet.</li>`;
    return;
  }
  list.innerHTML = stats.map(s => {
    const mins = Math.round(s.wait_for_new_patient_minutes || 0);
    const wait = mins <= 0 ? "No wait" : `${mins} min`;
    const queue = s.waiting === 0 ? "Nobody waiting" : `${s.waiting} waiting`;
    return `<li><span class="dept">${esc(s.department.name)}</span><span class="wait">${wait}</span>
      <span class="queue">${queue}${s.now_serving.length ? ` · now serving ${s.now_serving.map(esc).join(", ")}` : ""}</span></li>`;
  }).join("");
}


// The photos are borrowed under free licences; their authors are named in the footer.
const credits = document.getElementById("sf-credits");
if (credits) credits.textContent =
  "Photos: Shixart1985 (CC BY 2.0), via Wikimedia Commons";

renderLive();
setInterval(renderLive, 5000); // same 5-second polling as the OPD screens
