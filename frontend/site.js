// site.js: the shared website "shell": top strip, header, main menu, footer.
//
// Every page has two empty boxes:
//     <div id="site-header"></div>   ...page content...   <div id="site-footer"></div>
// and loads <script src="site.js"></script>. This file fills both boxes, so the
// header and footer are written ONCE and every page stays the same.
//
// The lists (hospitals, cities, specialities, helplines) are NOT typed here.
// They come from GET /api/site, which reads backend/app/data/site_content.json.
//
// Needs core.js first (in <head>). Everything is wrapped in (function () { ... })();
// so the names inside don't clash with app.js, which has its own `api`.

(function () {
  // ---------------------------------------------------------- helpers
  // The login/API helpers live in core.js (loaded in every page's <head>).
  const { api, esc, user, clearToken, goToLogin, checkAccess } = window.mediq;

  // Ask for the site data ONCE. Other scripts (home.js) reuse it as window.mediq.data.
  const data = api("/site");
  window.mediq.data = data;

  // The existing OPD screens inside index.html. "#doctor" opens that screen.
  const OPD_PAGES = [
    { name: "Book an appointment", href: "/book.html" },
    { name: "My appointments", href: "/my-appointments.html" },
    { name: "Doctor's desk", href: "/index.html#doctor" },
    { name: "Doctor: my appointments", href: "/doctor-appointments.html" },
    { name: "Doctor schedule (timetable)", href: "/schedule.html" },
    { name: "Waiting room display", href: "/index.html#display" },
    { name: "Department dashboard", href: "/index.html#dashboard" },
    { name: "Bed availability", href: "/index.html#beds" },
    { name: "Ambulance dispatch", href: "/ambulance.html" },
    { name: "Pharmacy: medicine catalogue", href: "/pharmacy.html" },
    { name: "Pharmacy: dispense (staff)", href: "/pharmacy-dispense.html" },
    { name: "Call-back requests (staff)", href: "/staff-callbacks.html" },
    { name: "Hospital overview (admin)", href: "/dashboard.html" },
    { name: "Admin console", href: "/admin.html" },
  ];

  const speciality_link = name => `/?speciality=${encodeURIComponent(name)}#enquiry`;

  // ---------------------------------------------------------- 1. the HTML

  // A simple logo: a teal tile with a heartbeat line, plus the name.
  const LOGO = `
    <a class="logo" href="/" aria-label="mediQ Health home">
      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
        <rect class="logo-bg" width="34" height="34" rx="9"/>
        <path d="M5 18h6l3-7 4 13 3-6h8" fill="none" stroke="#fff" stroke-width="2.6"
              stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span>medi<span class="q">Q</span></span><small>Health</small>
    </a>`;

  // Small drawn icons (SVG, in the text colour). Never "▾" or "☰" characters.
  const ICON = {
    chevron: `<svg class="chev" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>`,
    search: `<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7"
               stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.75"/><path d="M10.5 10.5L14 14"/></svg>`,
    menu: `<svg width="20" height="20" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7"
             stroke-linecap="round" aria-hidden="true"><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11"/></svg>`,
  };

  // One bar: logo · menu · search · Emergency · account · Book an appointment
  const HEADER = `
    <a class="skip-link" href="#main">Skip to content</a>
    <header class="site-header">
      <div class="wrap header-inner">
        ${LOGO}

        <nav class="site-menu" id="site-menu" aria-label="Main menu">
          <div class="dropdown">
            <button type="button" data-toggle aria-expanded="false">Hospitals ${ICON.chevron}</button>
            <div class="panel mega" id="sh-hospitals"><p class="note">Loading…</p></div>
          </div>
          <div class="dropdown">
            <button type="button" data-toggle aria-expanded="false">Specialities ${ICON.chevron}</button>
            <div class="panel mega" id="sh-specialities"><p class="note">Loading…</p></div>
          </div>
          <div class="dropdown">
            <button type="button" data-toggle aria-expanded="false">Services ${ICON.chevron}</button>
            <div class="panel">
              <a href="/book.html">Book an appointment</a>
              <a href="/my-appointments.html">My appointments</a>
              <a href="/schedule.html">Doctor timetable</a>
              <a href="/pharmacy.html">Find a medicine</a>
              <a href="/index.html#beds">Bed availability</a>
              <a href="/callback.html">Request a call back</a>
            </div>
          </div>
          <div class="dropdown">
            <button type="button" data-toggle aria-expanded="false">For staff ${ICON.chevron}</button>
            <div class="panel">
              ${OPD_PAGES.map(p => `<a href="${p.href}">${p.name}</a>`).join("")}
            </div>
          </div>
          <div class="menu-lang"><button type="button" class="icon-btn theme-btn"></button><button type="button" class="lang-btn notranslate" data-switch-lang
                  lang="${window.mediq.getLang() === "hi" ? "en" : "hi"}"
                  aria-label="${window.mediq.getLang() === "hi" ? "Switch to English" : "हिन्दी में देखें (Switch to Hindi)"}"
          >${window.mediq.getLang() === "hi" ? "English" : "हिन्दी"}</button></div>
          <div class="menu-account" id="sh-account-menu"></div>
        </nav>

        <div class="header-actions">
          <div class="dropdown search-dd">
            <button type="button" class="icon-btn" data-toggle aria-expanded="false" aria-label="Search the site">${ICON.search}</button>
            <div class="panel search-panel">
              <form class="site-search" role="search">
                <input type="search" name="q" placeholder="Hospital, speciality or condition"
                       aria-label="Search the site" autocomplete="off">
                <div class="search-results" hidden></div>
              </form>
            </div>
          </div>
          <button type="button" class="lang-btn notranslate" data-switch-lang
                  lang="${window.mediq.getLang() === "hi" ? "en" : "hi"}"
                  aria-label="${window.mediq.getLang() === "hi" ? "Switch to English" : "हिन्दी में देखें (Switch to Hindi)"}"
          >${window.mediq.getLang() === "hi" ? "English" : "हिन्दी"}</button>
          <button type="button" class="icon-btn theme-btn" id="sh-theme"></button>
          <div class="dropdown emergency">
            <button type="button" class="btn btn-emergency" data-toggle aria-expanded="false">Emergency ${ICON.chevron}</button>
            <div class="panel" id="sh-emergency"><p class="note">Loading…</p></div>
          </div>
          <div class="account" id="sh-account"></div>
          <a class="btn btn-book" href="/book.html">Book an appointment</a>
          <button type="button" class="icon-btn hamburger" aria-label="Open menu" aria-expanded="false"
                  aria-controls="site-menu">${ICON.menu}</button>
        </div>
      </div>
    </header>`;

  const FOOTER = `
    <footer class="site-footer">
      <div class="wrap footer-grid">
        <div class="footer-brand">
          ${LOGO}
          <p id="sf-tagline"></p>
          <address id="sf-office"></address>
        </div>
        <div>
          <h2>Hospitals</h2>
          <ul id="sf-hospitals"></ul>
        </div>
        <div>
          <h2>In an emergency</h2>
          <ul id="sf-helplines"></ul>
          <p id="sf-email"></p>
        </div>
        <div>
          <h2>Patients</h2>
          <ul>
            <li><a href="/book.html">Book an appointment</a></li>
            <li><a href="/my-appointments.html">My appointments</a></li>
            <li><a href="/schedule.html">Doctor timetable</a></li>
            <li><a href="/pharmacy.html">Find a medicine</a></li>
            <li><a href="/callback.html">Request a call back</a></li>
          </ul>
          <h2>Staff</h2>
          <ul>
            <li><a href="/login.html">Staff log in</a></li>
            <li><a href="/index.html#doctor">Doctor's desk</a></li>
            <li><a href="/pharmacy-dispense.html">Pharmacy counter</a></li>
            <li><a href="/admin.html">Admin console</a></li>
          </ul>
        </div>
      </div>
      <div class="wrap footer-bottom">
        <span>© 2026 mediQ Health, a fictional demo. Names, hospitals and addresses are made up.</span>
        <span id="sf-credits"></span>
      </div>
    </footer>`;

  const headerBox = document.getElementById("site-header");
  const footerBox = document.getElementById("site-footer");
  if (headerBox) headerBox.innerHTML = HEADER;
  // The "Skip to content" link jumps here
  const mainEl = document.querySelector("main");
  if (mainEl && !mainEl.id) mainEl.id = "main";
  if (footerBox) footerBox.innerHTML = FOOTER;

  // ---------------------------------------------------------- 2. fill lists from the API

  const fill = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };

  // Numbers are shown as plain text, NOT clickable tel: links, because they are fake
  // and might belong to a real person.
  data.then(d => {
    fill("sh-emergency", `
      <p class="panel-lead">In a medical emergency, call:</p>
      ${d.emergency_numbers.map(e =>
        `<div class="row"><span>${esc(e.label)}</span><b class="mono">${esc(e.number)}</b></div>`).join("")}
      <p class="note">Every mediQ hospital has a 24-hour emergency department.</p>`);

    // Group hospitals by state: { "Maharashtra": [h1, h2], "Kerala": [h3] }
    const byState = {};
    for (const h of d.hospitals) (byState[h.state] ||= []).push(h);
    fill("sh-hospitals", Object.entries(byState).map(([state, list]) => `
      <div class="group">
        <h4>${esc(state)}</h4>
        ${list.map(h => `<a href="/#hospitals">${esc(h.name)}<small>${esc(h.area)}, ${esc(h.city)}</small></a>`).join("")}
      </div>`).join(""));

    fill("sh-specialities", d.specialities.map(s => `
      <a href="${speciality_link(s.name)}">${esc(s.name)}<small>${s.conditions.slice(0, 3).map(esc).join(" · ")}</small></a>`).join(""));

    // Footer
    fill("sf-tagline", esc(d.tagline));
    fill("sf-office", esc(d.head_office));
    fill("sf-hospitals", d.hospitals.map(h =>
      `<li>${esc(h.name.replace(/^mediQ /, ""))} <small>${esc(h.city)}</small></li>`).join(""));
    fill("sf-helplines", d.helplines.map(h => `<li>${esc(h.label)} <b class="mono">${esc(h.number)}</b></li>`).join(""));
    fill("sf-email", `Not urgent? <a href="mailto:${esc(d.email)}">${esc(d.email)}</a>`);

    buildSearchIndex(d);
  }).catch(err => console.error("Could not load site data:", err));

  // ---------------------------------------------------------- 2b. account area + page protection

  const ROLE_LABEL = { admin: "Admin", doctor: "Doctor", pharmacist: "Pharmacy", patient: "Patient" };

  // Each role's own page, for the account menu
  const MY_PAGE = { patient: "My appointments", doctor: "Doctor's desk", pharmacist: "Pharmacy", admin: "Hospital overview" };
  // "Asha Patel" -> "AP"; "Dr. Meera Rao" -> "MR"
  const initials = name => name.replace(/^(dr|mr|mrs|ms)\.?\s+/i, "").split(/\s+/).filter(Boolean)
    .slice(0, 2).map(w => w[0].toUpperCase()).join("") || "?";

  user.then(u => {
    // In the bar: "Log in", or (signed in) a small round button with your initials that opens
    // your name, your page and "Log out". A full name here pushed the header off the screen.
    fill("sh-account", u
      ? `<div class="dropdown account-dd">
           <button type="button" class="avatar" data-toggle aria-expanded="false"
                   aria-label="Your account: ${esc(u.full_name)}" title="${esc(u.full_name)}">${esc(initials(u.full_name))}</button>
           <div class="panel account-panel">
             <p class="panel-lead">${esc(u.full_name)}<small>${esc(ROLE_LABEL[u.role] || u.role)}</small></p>
             <a href="${window.mediq.ROLE_HOME[u.role] || "/"}">${esc(MY_PAGE[u.role] || "My page")}</a>
             <button type="button" class="panel-btn" data-logout>Log out</button>
           </div>
         </div>`
      : `<a href="/login.html">Log in</a>`);
    // In the phone menu there is room for the full text
    fill("sh-account-menu", u
      ? `<span class="who">${esc(u.full_name)} <small>${esc(ROLE_LABEL[u.role] || u.role)}</small></span>
         <button type="button" class="link-btn" data-logout>Log out</button>`
      : `<a href="/login.html">Log in</a><a href="/signup.html">Create an account</a>`);

    // Pages that need a role say so on <body>, e.g. <body data-require-roles="doctor">.
    // (The SERVER checks again on every request; this only gives people a friendly page.)
    const needed = (document.body.dataset.requireRoles || "").split(",").filter(Boolean);
    const access = checkAccess(u, needed);
    if (access === "login") goToLogin();
    if (access === "offline") return;                       // still logged in; core.js shows "Can't reach..."
    if (access === "forbidden") {
      const main = document.querySelector("main");
      if (main) main.innerHTML = `
        <h1 class="page-title">No access</h1>
        <p class="lead">This page needs a ${needed.map(r => esc(ROLE_LABEL[r] || r)).join(" or ")} account.
          You're signed in as ${esc(u.full_name)} (${esc(ROLE_LABEL[u.role] || u.role)}).</p>
        <p><a class="btn btn-outline" href="/">Go to the home page</a></p>`;
    }
  });

  // Logout: tell the server to cancel the token, forget it here, go home.
  document.addEventListener("click", async e => {
    if (!e.target.closest("[data-logout]")) return;
    try { await api("/auth/logout", { method: "POST", quiet401: true }); } catch { /* already invalid */ }
    clearToken();
    location.href = "/";
  });

  if (!headerBox) return; // a page without the header: nothing more to wire up

  // ---------------------------------------------------------- 2c. English / हिन्दी (core.js does the work)
  headerBox.querySelectorAll("[data-switch-lang]").forEach(b => b.addEventListener("click", () =>
    window.mediq.setLang(window.mediq.getLang() === "hi" ? "en" : "hi")));

  // ---------------------------------------------------------- 2c. light / dark switch
  // Moon in light mode ("go dark"), sun in dark mode ("go light"). core.js does the switching.
  // Two copies: one in the bar, one in the phone menu (very small phones have no room in the bar)
  const themeBtns = headerBox.querySelectorAll(".theme-btn");
  const drawThemeButton = () => {
    const dark = window.mediq.getTheme() === "dark";
    const label = dark ? "Switch to light mode" : "Switch to dark mode";
    themeBtns.forEach(b => {
      b.innerHTML = window.mediq.svg(dark ? window.mediq.ICONS.sun : window.mediq.ICONS.moon, 18);
      b.setAttribute("aria-label", label);
      b.title = label;
    });
  };
  drawThemeButton();
  themeBtns.forEach(b => b.addEventListener("click", () => window.mediq.toggleTheme(b)));
  document.addEventListener("mediq:theme", drawThemeButton);

  // ---------------------------------------------------------- 3. dropdowns and hamburger

  const menu = headerBox.querySelector(".site-menu");
  const hamburger = headerBox.querySelector(".hamburger");

  function closeDropdowns() {
    headerBox.querySelectorAll(".dropdown.open").forEach(dd => {
      dd.classList.remove("open");
      dd.querySelector("[data-toggle]").setAttribute("aria-expanded", "false");
    });
  }

  function closeMobileMenu() {
    menu.classList.remove("open");
    hamburger.setAttribute("aria-expanded", "false");
  }

  // One click listener for the whole header ("event delegation", see LEARN.md 7.6).
  headerBox.addEventListener("click", e => {
    const toggle = e.target.closest("[data-toggle]");
    if (toggle) {
      const dd = toggle.parentElement;
      const willOpen = !dd.classList.contains("open");
      closeDropdowns();                       // only one dropdown open at a time
      if (willOpen) {
        dd.classList.add("open");
        toggle.setAttribute("aria-expanded", "true"); // tells screen readers it's open
        dd.querySelector('input[type="search"]')?.focus();
      }
      return;
    }
    // Clicking a link inside a menu closes the menus (matters for #links on the same page).
    if (e.target.closest(".panel a, .menu-account a")) {
      closeDropdowns();
      closeMobileMenu();
    }
  });

  hamburger.addEventListener("click", () => {
    const open = menu.classList.toggle("open");
    hamburger.setAttribute("aria-expanded", String(open));
    hamburger.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  });

  // Click anywhere else, or press Escape: close everything.
  document.addEventListener("click", e => {
    if (!e.target.closest(".dropdown")) closeDropdowns();
    if (!e.target.closest(".site-search")) results.hidden = true;
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { closeDropdowns(); results.hidden = true; }
  });

  // ---------------------------------------------------------- 4. search

  // Searches the site data in the browser (no server call needed):
  // hospitals, specialities AND their conditions ("knee pain" finds Orthopaedics).
  const searchForm = headerBox.querySelector(".site-search");
  const input = searchForm.q;
  const results = searchForm.querySelector(".search-results");
  let searchIndex = [];

  function buildSearchIndex(d) {
    searchIndex = [
      ...d.specialities.map(s => ({ title: s.name, sub: s.conditions.join(", "), href: speciality_link(s.name) })),
      ...d.hospitals.map(h => ({ title: h.name, sub: `${h.area}, ${h.city}, ${h.state}`, href: "/#hospitals" })),
      ...OPD_PAGES.map(p => ({ title: p.name, sub: "OPD system", href: p.href })),
    ];
  }

  function search(text) {
    const q = text.trim().toLowerCase();
    if (!q) { results.hidden = true; return []; }
    // Match the English AND the Hindi names, so "हृदय" finds Cardiology (t() = no change in English mode)
    const t = window.mediq.t;
    const hits = searchIndex.filter(i => `${i.title} ${i.sub} ${t(i.title)} ${t(i.sub)}`.toLowerCase().includes(q)).slice(0, 8);
    results.innerHTML = hits.length
      ? hits.map(h => `<a href="${h.href}">${esc(h.title)}<small>${esc(h.sub)}</small></a>`).join("")
      : `<p class="note">No results for "${esc(text.trim())}"</p>`;
    results.hidden = false;
    return hits;
  }

  input.addEventListener("input", () => search(input.value));
  searchForm.addEventListener("submit", e => {
    e.preventDefault();
    const hits = search(input.value);
    if (hits.length) location.href = hits[0].href; // Enter = go to the best match
  });

  // ---------------------------------------------------------- 5. "coming soon" links

  // Features not built yet (Ambulance, Inventory, My Reports...) have data-soon="Name".
  // Listening on the whole document also catches the cards on the home page.
  document.addEventListener("click", e => {
    const soon = e.target.closest("[data-soon]");
    if (!soon) return;
    e.preventDefault();
    alert(`${soon.dataset.soon} is coming soon to mediQ.`);
  });
})();
