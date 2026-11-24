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
// Everything is wrapped in (function () { ... })(); so the names inside
// (api, esc, ...) don't clash with app.js, which has its own `api` and `esc`.

(function () {
  // ---------------------------------------------------------- helpers

  // ---------- the login token (step 5) ----------
  // After login the token is kept in localStorage, so it survives page changes
  // and browser restarts until it expires (60 min) or you log out.
  // try/catch: some private-browsing modes block localStorage.
  const TOKEN_KEY = "mediq_token";
  function getToken() { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } }
  function setToken(t) { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* ignore */ } }
  function clearToken() { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } }

  // { Authorization: "Bearer eyJ..." } when logged in, {} when not.
  function authHeader() {
    const t = getToken();
    return t ? { Authorization: `Bearer ${t}` } : {};
  }

  // Send the user to the login page, remembering where they wanted to go.
  function goToLogin() {
    const here = location.pathname + location.search + location.hash;
    location.href = "/login.html?next=" + encodeURIComponent(here);
  }

  // Call the backend and return JSON (same idea as api() in app.js).
  // It sends the login token automatically. A 401 ("not logged in / token
  // expired") forgets the token and goes to the login page, unless the caller
  // passes { quiet401: true } (used where being logged out is normal).
  async function api(path, options = {}) {
    const { quiet401, ...fetchOptions } = options;
    const res = await fetch("/api" + path, {
      headers: { "Content-Type": "application/json", ...authHeader() },
      ...fetchOptions,
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && !quiet401 && !path.startsWith("/auth/login") && !path.startsWith("/auth/signup")) {
      clearToken();
      goToLogin();
    }
    if (!res.ok) {
      const d = data.detail;
      // 422 errors give a list of problems; turn them into readable text.
      const msg = Array.isArray(d) ? d.map(x => x.msg).join("; ") : d || res.statusText;
      throw new Error(msg);
    }
    return data;
  }

  // Escape text before putting it into HTML (see LEARN.md 3.7).
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Ask for the site data ONCE. Other scripts (home.js) reuse it through window.mediq.
  const data = api("/site");

  // ---------- who is logged in? (step 5) ----------
  // A Promise of the user ({full_name, role, ...}), or null when logged out.
  // quiet401: an expired token on a PUBLIC page just means "logged out", no redirect.
  const user = getToken()
    ? api("/auth/me", { quiet401: true }).catch(() => { clearToken(); return null; })
    : Promise.resolve(null);

  // Can this user see something that needs one of `roles`? Admins can see everything.
  //   "ok"         yes
  //   "login"      nobody is logged in
  //   "forbidden"  logged in, but the wrong role
  function checkAccess(u, roles) {
    if (!roles || roles.length === 0) return "ok";
    if (!u) return "login";
    return u.role === "admin" || roles.includes(u.role) ? "ok" : "forbidden";
  }

  // Where each role lands after logging in.
  const ROLE_HOME = {
    admin: "/admin.html",
    doctor: "/index.html#doctor",
    receptionist: "/index.html#reception",
    patient: "/",
  };

  window.mediq = { api, esc, data, user, getToken, setToken, clearToken, authHeader,
                   goToLogin, checkAccess, ROLE_HOME };

  // The existing OPD screens inside index.html. "#doctor" opens that screen.
  const OPD_PAGES = [
    { name: "Reception (get a token)", href: "/index.html#reception" },
    { name: "Doctor's desk", href: "/index.html#doctor" },
    { name: "Doctor schedule (timetable)", href: "/schedule.html" },
    { name: "Waiting room display", href: "/index.html#display" },
    { name: "Department dashboard", href: "/index.html#dashboard" },
    { name: "Bed availability", href: "/index.html#beds" },
    { name: "Ambulance dispatch", href: "/ambulance.html" },
    { name: "Call-back requests (staff)", href: "/staff-callbacks.html" },
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

  const HEADER = `
    <div class="topstrip">
      <div class="wrap topstrip-inner">
        <div class="quick-links">
          <a href="/#specialities">Find a Doctor</a>
          <a href="#" data-soon="My Reports">My Reports</a>
          <a href="#site-footer">Contact Us</a>
        </div>
        <div class="helplines" id="sh-helplines"></div>
        <!-- "Log in / Sign up", or "Asha Patel · Logout" (filled in below) -->
        <div class="account" id="sh-account"></div>
      </div>
    </div>

    <header class="site-header">
      <div class="wrap header-inner">
        ${LOGO}

        <form class="site-search" role="search">
          <input type="search" name="q" placeholder="Search hospitals, specialities, conditions"
                 aria-label="Search the site" autocomplete="off">
          <button type="submit">Search</button>
          <div class="search-results" hidden></div>
        </form>

        <div class="header-actions">
          <div class="dropdown emergency">
            <button type="button" class="btn btn-danger" data-toggle aria-expanded="false">Emergency ▾</button>
            <div class="panel" id="sh-emergency"><p class="note">Loading…</p></div>
          </div>
          <a class="btn btn-outline callback" href="/callback.html">Request Call Back</a>
          <button type="button" class="hamburger" aria-label="Open menu" aria-expanded="false">☰</button>
        </div>
      </div>

      <nav class="site-menu" aria-label="Main menu">
        <div class="wrap menu-inner">
          <div class="dropdown">
            <button type="button" data-toggle aria-expanded="false">Hospitals ▾</button>
            <div class="panel mega" id="sh-hospitals"><p class="note">Loading…</p></div>
          </div>
          <div class="dropdown">
            <button type="button" data-toggle aria-expanded="false">Specialities ▾</button>
            <div class="panel mega" id="sh-specialities"><p class="note">Loading…</p></div>
          </div>
          <div class="dropdown">
            <button type="button" data-toggle aria-expanded="false">Services ▾</button>
            <div class="panel">
              <a href="/ambulance.html">Ambulance (staff dispatch)</a>
              <a href="/index.html#beds">Bed Availability</a>
              <a href="#" data-soon="Pharmacy / Inventory">Pharmacy / Inventory <span class="soon">Soon</span></a>
              <a href="/#enquiry">Health Checkups</a>
            </div>
          </div>
          <div class="dropdown">
            <button type="button" data-toggle aria-expanded="false">OPD System ▾</button>
            <div class="panel">
              ${OPD_PAGES.map(p => `<a href="${p.href}">${p.name}</a>`).join("")}
            </div>
          </div>
          <a class="mobile-only menu-link" href="/callback.html">Request Call Back</a>
          <a class="btn btn-book" href="/index.html#reception">Book Appointment</a>
        </div>
      </nav>
    </header>`;

  const FOOTER = `
    <footer class="site-footer">
      <div class="wrap footer-grid">
        <div>
          ${LOGO}
          <p id="sf-tagline"></p>
          <address id="sf-office"></address>
        </div>
        <div>
          <h4>Our hospitals</h4>
          <ul id="sf-hospitals"></ul>
        </div>
        <div>
          <h4>Helplines</h4>
          <ul id="sf-helplines"></ul>
          <p id="sf-email"></p>
        </div>
        <div>
          <h4>Quick links</h4>
          <ul>
            <li><a href="/#specialities">Find a Doctor</a></li>
            <li><a href="/callback.html">Request Call Back</a></li>
            ${OPD_PAGES.map(p => `<li><a href="${p.href}">${p.name}</a></li>`).join("")}
          </ul>
        </div>
      </div>
      <div class="wrap footer-bottom">
        <span>© 2026 mediQ Health. A fictional demo project.</span>
        <span>All names, numbers and addresses are made up. In a real emergency in India, dial 112.</span>
      </div>
    </footer>`;

  const headerBox = document.getElementById("site-header");
  const footerBox = document.getElementById("site-footer");
  if (headerBox) headerBox.innerHTML = HEADER;
  if (footerBox) footerBox.innerHTML = FOOTER;

  // ---------------------------------------------------------- 2. fill lists from the API

  const fill = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };

  // Numbers are shown as plain text, NOT clickable tel: links, because they are fake
  // and might belong to a real person.
  data.then(d => {
    fill("sh-helplines", d.helplines.map(h =>
      `<span>${esc(h.label)} <b>${esc(h.number)}</b></span>`).join(""));

    fill("sh-emergency", `
      <h4>24/7 emergency numbers</h4>
      ${d.emergency_numbers.map(e =>
        `<div class="row"><span>${esc(e.city)}</span><b>${esc(e.number)}</b></div>`).join("")}
      <p class="note">Demo site: these numbers are fictional.<br>In a real emergency in India, dial <b>112</b>.</p>`);

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
    fill("sf-hospitals", d.hospitals.slice(0, 4).map(h =>
      `<li>${esc(h.name)}<br><small>${esc(h.area)}, ${esc(h.city)}</small></li>`).join(""));
    fill("sf-helplines", d.helplines.map(h => `<li>${esc(h.label)}: <b>${esc(h.number)}</b></li>`).join(""));
    fill("sf-email", `Email: ${esc(d.email)}`);

    buildSearchIndex(d);
  }).catch(err => console.error("Could not load site data:", err));

  // ---------------------------------------------------------- 2b. account area + page protection

  const ROLE_LABEL = { admin: "Admin", doctor: "Doctor", receptionist: "Reception", patient: "Patient" };

  user.then(u => {
    const box = document.getElementById("sh-account");
    if (box) {
      box.innerHTML = u
        ? `<span class="who">${esc(u.full_name)} <small>(${esc(ROLE_LABEL[u.role] || u.role)})</small></span>
           <button type="button" class="link-btn" id="logout-btn">Logout</button>`
        : `<a href="/login.html">Log in</a><a href="/signup.html">Sign up</a>`;
    }

    // Pages that need a role say so on <body>, e.g. <body data-require-roles="receptionist">.
    // (The SERVER checks again on every request; this only gives people a friendly page.)
    const needed = (document.body.dataset.requireRoles || "").split(",").filter(Boolean);
    const access = checkAccess(u, needed);
    if (access === "login") goToLogin();
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
    if (!e.target.closest("#logout-btn")) return;
    try { await api("/auth/logout", { method: "POST", quiet401: true }); } catch { /* already invalid */ }
    clearToken();
    location.href = "/";
  });

  if (!headerBox) return; // a page without the header: nothing more to wire up

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
      }
      return;
    }
    // Clicking a link inside a menu closes the menus (matters for #links on the same page).
    if (e.target.closest(".panel a, .menu-link, .menu-inner .btn-book")) {
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
    const hits = searchIndex.filter(i => `${i.title} ${i.sub}`.toLowerCase().includes(q)).slice(0, 8);
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
