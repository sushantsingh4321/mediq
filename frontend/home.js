// home.js: the home page (home.html).
// It reuses the helpers that site.js shares on window.mediq:
//   api(path)  call the backend      esc(text)  make text safe for HTML
//   data       the site data from GET /api/site (a Promise)

const { api, esc, data } = window.mediq;

// ---------- 1. lists from the data file ----------

data.then(d => {
  // Specialities: one card each, with its conditions.
  document.getElementById("spec-grid").innerHTML = d.specialities.map(s => `
    <div class="spec">
      <h3>${esc(s.name)}</h3>
      <ul>${s.conditions.map(c => `<li>${esc(c)}</li>`).join("")}</ul>
      <a href="?speciality=${encodeURIComponent(s.name)}#enquiry">Enquire about ${esc(s.name)} →</a>
    </div>`).join("");

  // Hospitals grouped by state.
  const byState = {};
  for (const h of d.hospitals) (byState[h.state] ||= []).push(h);
  document.getElementById("hospital-list").innerHTML = Object.entries(byState).map(([state, list]) => `
    <div class="hospital-group">
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

// ---------- 3. live numbers: "Now serving" strip and service cards ----------

async function renderLive() {
  try {
    const depts = await api("/departments");
    const stats = await Promise.all(depts.map(d => api(`/departments/${d.id}/stats`)));
    document.getElementById("ns-items").innerHTML = stats.length
      ? stats.map(s => `<span class="ns-item">${esc(s.department.name)}
          <b>${s.now_serving.length ? s.now_serving.map(esc).join(", ") : "–"}</b></span>`).join("")
      : `<span class="muted">No OPD departments yet</span>`;

    const waiting = stats.reduce((sum, s) => sum + s.waiting, 0);
    document.getElementById("stat-opd").textContent = `${waiting} waiting now`;

    const wards = await api("/wards/availability");
    const free = wards.reduce((sum, w) => sum + w.free, 0);
    document.getElementById("stat-beds").textContent = `${free} beds free now`;

    const duty = await api("/schedule/on-duty");   // Module 2
    const n = duty.on_duty.length;
    document.getElementById("stat-duty").textContent = `${n} doctor${n === 1 ? "" : "s"} on duty now`;

    const amb = await api("/ambulances/availability");   // Module 3 (counts only)
    document.getElementById("stat-amb").textContent =
      `${amb.available} ambulance${amb.available === 1 ? "" : "s"} available`;
  } catch (err) {
    console.error(err);
  }
}

renderLive();
setInterval(renderLive, 5000); // same 5-second polling as the OPD screens
