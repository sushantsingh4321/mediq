// home.js: the home page (home.html).
// It reuses the helpers that site.js shares on window.mediq:
//   api(path)  call the backend      esc(text)  make text safe for HTML
//   data       the site data from GET /api/site (a Promise)

const { api, esc, data } = window.mediq;

// ---------- 1. lists from the data file ----------

data.then(d => {
  // Specialities: one row each, with a few of the conditions it treats.
  document.getElementById("spec-list").innerHTML = d.specialities.map(s => `
    <li><a href="?speciality=${encodeURIComponent(s.name)}#enquiry">
      <strong>${esc(s.name)}</strong>
      <small>${s.conditions.slice(0, 3).map(esc).join(", ")}</small>
      <span class="go">Ask us</span>
    </a></li>`).join("");

  // Hospitals grouped by state.
  const byState = {};
  for (const h of d.hospitals) (byState[h.state] ||= []).push(h);
  document.getElementById("hospital-list").innerHTML = Object.entries(byState).map(([state, list]) => `
    <div>
      <h3>${esc(state)}</h3>
      <ul>${list.map(h => `<li><b>${esc(h.name)}</b><small>${esc(h.area)}, ${esc(h.city)}</small></li>`).join("")}</ul>
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

// The hero's moving background (gradient-ascii.js). Your settings, unchanged.
window.GradientASCII?.mount(document.getElementById("hero-ascii"), {
  colors: ["#1e3fd8", "#f6f8ff", "#a5d8ff", "#38bdf8"],
  shape: "horizon",
  characters: " =+xX0S8#@",
  cellSize: 18,
  density: 0.8,
  glyphOpacity: 0.85,
  glow: 0.2,
  depthOfField: 0,
  flicker: 0.2,
  softness: 0.5,
  scale: 1,
  flow: 0.5,
  speed: 1,
  gradientOpacity: 0.9,
  grain: 0.08,
  variation: 0,
  mouseInteraction: true,
  scrambleRadius: 0.1,
  clickEffect: "wave",
  intro: true,
  lightMode: false,
});

// The photos are borrowed under free licences; their authors are named in the footer.
const credits = document.getElementById("sf-credits");
if (credits) credits.textContent =
  "Photos: Legend1306 (CC BY-SA 4.0) and Harrison Keely (CC BY 4.0), via Wikimedia Commons";

renderLive();
setInterval(renderLive, 5000); // same 5-second polling as the OPD screens
