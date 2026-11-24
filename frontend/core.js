// core.js: small helpers shared by EVERY page. Loaded in each page's <head>:
//
//     <link rel="stylesheet" href="style.css">
//     <script src="core.js"></script>
//
// Because it runs in <head>, before the page is drawn, it can set the light or
// dark theme first, so dark-mode users never see a white flash.
//
// Everything is shared on one object, window.mediq:
//   login:   api, getToken, setToken, clearToken, authHeader, user, checkAccess, goToLogin, ROLE_HOME
//   text:    esc
//   theme:   getTheme, toggleTheme
//   UI:      pill, message, clearMessage, toast, loading, empty, appBar
//
// Wrapped in (function () { ... })(); so its inner names can't clash with other scripts.

(function () {
  // ======================================================================
  // 1. THEME (light / dark)
  // ======================================================================
  // The choice is saved in localStorage. With no saved choice we follow the
  // computer's setting (prefers-color-scheme), and keep following it if it changes.
  const THEME_KEY = "mediq_theme";
  const root = document.documentElement;
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  function savedTheme() { try { return localStorage.getItem(THEME_KEY); } catch { return null; } }
  function getTheme() { return root.dataset.theme === "dark" ? "dark" : "light"; }
  function applyTheme(theme) { root.dataset.theme = theme; }

  applyTheme(savedTheme() || (systemDark.matches ? "dark" : "light"));   // runs immediately, before paint
  systemDark.addEventListener("change", e => { if (!savedTheme()) applyTheme(e.matches ? "dark" : "light"); });

  // Switch theme. The new theme grows as a circle from the button that was clicked
  // (View Transitions API). Older browsers get a 0.35s colour fade; people who
  // asked for reduced motion get an instant switch.
  function toggleTheme(button) {
    const next = getTheme() === "dark" ? "light" : "dark";
    const change = () => {
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch { /* private mode: just don't remember */ }
      document.dispatchEvent(new CustomEvent("mediq:theme", { detail: next }));
    };

    if (reducedMotion.matches) { change(); return; }

    if (!document.startViewTransition) {
      root.classList.add("ui-theme-fade");
      change();
      setTimeout(() => root.classList.remove("ui-theme-fade"), 400);
      return;
    }

    // Circle centre = middle of the button; radius = far enough to cover the screen
    const r = button ? button.getBoundingClientRect() : { left: innerWidth / 2, top: 0, width: 0, height: 0 };
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    const transition = document.startViewTransition(change);
    transition.ready.then(() => {
      root.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 450, easing: "cubic-bezier(.2,.7,.2,1)", pseudoElement: "::view-transition-new(root)" },
      );
    });
  }

  // ======================================================================
  // 2. LOGIN TOKEN AND API CALLS (moved here from site.js)
  // ======================================================================
  // After login the token is kept in localStorage until it expires (60 min)
  // or you log out. try/catch: some private-browsing modes block localStorage.
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

  // Call the backend and return JSON. Sends the login token automatically.
  // A 401 ("not logged in / expired") forgets the token and goes to the login
  // page, unless the caller passes { quiet401: true }.
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

  // Escape text before putting it into HTML (LEARN.md 3.7).
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // The logged-in user ({full_name, role, ...}) as a Promise, or null when logged out.
  const user = getToken()
    ? api("/auth/me", { quiet401: true }).catch(() => { clearToken(); return null; })
    : Promise.resolve(null);

  // "ok" | "login" (nobody logged in) | "forbidden" (wrong role). Admins may do everything.
  function checkAccess(u, roles) {
    if (!roles || roles.length === 0) return "ok";
    if (!u) return "login";
    return u.role === "admin" || roles.includes(u.role) ? "ok" : "forbidden";
  }

  // Where each role lands after logging in.
  const ROLE_HOME = {
    admin: "/admin.html",
    doctor: "/index.html#doctor",
    pharmacist: "/pharmacy-dispense.html",
    patient: "/my-appointments.html",
  };

  // ======================================================================
  // 3. SMALL UI HELPERS
  // ======================================================================
  // Icons are tiny inline SVG drawings in the text colour (no image files, no emoji).
  const svg = (paths, size = 16) =>
    `<svg width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="currentColor"
          stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

  const ICONS = {
    waiting: '<circle cx="8" cy="8" r="6.25"/><path d="M8 4.5V8l2.5 1.5"/>',                 // clock
    called: '<path d="M4 11V7a4 4 0 0 1 8 0v4l1.25 1.5H2.75z"/><path d="M6.5 14a1.5 1.5 0 0 0 3 0"/>', // bell
    in_consultation: '<path d="M4 14V2.5h8V14"/><path d="M2.5 14h11"/><path d="M9.5 8.5h.01"/>',      // door
    done: '<path d="M3 8.5l3 3 7-7"/>',                                                    // tick
    skipped: '<path d="M3 3.5l6 4.5-6 4.5z"/><path d="M12 3v10"/>',                       // skip
    sun: '<circle cx="8" cy="8" r="3"/><path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1"/>',
    moon: '<path d="M13.5 9.5A6 6 0 0 1 6.5 2.5a6 6 0 1 0 7 7z"/>',
    logo: '<path d="M1.5 8.5h3l1.5-4 2.5 7 1.5-3h4.5"/>',
  };

  const STATUS_WORD = {
    waiting: "Waiting", called: "Called", in_consultation: "In consultation", done: "Done", skipped: "Skipped",
  };

  // pill("waiting") -> <span class="ui-pill ui-pill--waiting">[clock] Waiting</span>
  function pill(status, word) {
    const key = ICONS[status] ? status : "waiting";
    return `<span class="ui-pill ui-pill--${key}">${svg(ICONS[key], 14)}${esc(word || STATUS_WORD[key] || status)}</span>`;
  }

  // Show an inline message in `el` (replaces alert()).
  //   message(el, { type: "error", title: "Token not issued", text: "Enter a 10-digit mobile number." })
  function message(el, { type = "info", title, text = "" }) {
    el.className = `ui-message ui-message--${type}`;
    el.setAttribute("role", type === "error" ? "alert" : "status");
    el.innerHTML = `<strong>${esc(title)}</strong>${text ? `<p>${esc(text)}</p>` : ""}`;
    el.hidden = false;
    el.classList.remove("ui-appear"); void el.offsetWidth; el.classList.add("ui-appear");  // replay the slide-up
  }
  function clearMessage(el) { el.hidden = true; el.innerHTML = ""; }

  // A short note in the corner that disappears by itself (for "saved" type news).
  function toast(text, ms = 4000) {
    let area = document.querySelector(".ui-toast-area");
    if (!area) {
      area = document.createElement("div");
      area.className = "ui-toast-area";
      area.setAttribute("aria-live", "polite");
      document.body.append(area);
    }
    const t = document.createElement("div");
    t.className = "ui-toast ui-appear";
    t.textContent = text;
    area.append(t);
    setTimeout(() => t.remove(), ms);
  }

  const loading = (el, text = "Loading…") => { el.innerHTML = `<div class="ui-loading" role="status">${esc(text)}</div>`; };
  const empty = (el, text) => { el.innerHTML = `<div class="ui-empty">${esc(text)}</div>`; };

  // ======================================================================
  // 4. THE APP BAR (staff screens)
  // ======================================================================
  // Put <header id="app-bar"></header> at the top of the page, then call:
  //   mediq.appBar({ role: "Doctor", place: "Room 3" })
  // Shows: hospital name · role, place · clock · English/हिन्दी · theme toggle · user + sign out.
  const LANG_KEY = "mediq_lang";

  function appBar({ role = "", place = "" } = {}) {
    const bar = document.getElementById("app-bar");
    if (!bar) return;
    bar.className = "ui-appbar";
    bar.setAttribute("role", "banner");
    let lang = "en";
    try { lang = localStorage.getItem(LANG_KEY) || "en"; } catch { /* ignore */ }

    bar.innerHTML = `
      <a class="ui-appbar__hospital" href="/">${svg(ICONS.logo, 24)}<span id="ab-hospital">mediQ</span></a>
      <span class="ui-appbar__role" id="ab-role">${esc([role, place].filter(Boolean).join(", "))}</span>
      <span class="ui-appbar__spacer"></span>
      <div class="ui-appbar__tools">
        <time class="ui-appbar__clock" id="ab-clock" aria-label="Current time"></time>
        <div class="ui-segmented" role="group" aria-label="Language">
          <button type="button" class="ui-barbutton" data-lang="en" aria-pressed="${lang === "en"}">English</button>
          <button type="button" class="ui-barbutton" data-lang="hi" aria-pressed="${lang === "hi"}" lang="hi">हिन्दी</button>
        </div>
        <button type="button" class="ui-barbutton" id="ab-theme"></button>
        <span class="ui-appbar__user" id="ab-user"></span>
      </div>`;

    // Hospital name from the server (public endpoint)
    api("/hospital/summary").then(h => { document.getElementById("ab-hospital").textContent = h.hospital_name; })
      .catch(() => { /* keep "mediQ" */ });

    // Clock: HH:MM, updated every 10 seconds
    const clock = document.getElementById("ab-clock");
    const tick = () => {
      const now = new Date();
      clock.textContent = now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
      clock.dateTime = now.toISOString();
    };
    tick();
    setInterval(tick, 10000);

    // Language switch: a PLACEHOLDER for now. It remembers the choice and sets
    // <html lang>, but the screens are not translated yet.
    bar.querySelectorAll("[data-lang]").forEach(b => b.addEventListener("click", () => {
      const chosen = b.dataset.lang;
      bar.querySelectorAll("[data-lang]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
      try { localStorage.setItem(LANG_KEY, chosen); } catch { /* ignore */ }
      document.documentElement.lang = chosen;
      if (chosen === "hi") toast("हिन्दी अनुवाद जल्द आ रहा है। Hindi screens are coming soon.");
    }));

    // Theme toggle: shows the moon in light mode ("go dark") and the sun in dark mode ("go light")
    const themeBtn = document.getElementById("ab-theme");
    const drawThemeButton = () => {
      const dark = getTheme() === "dark";
      themeBtn.innerHTML = svg(dark ? ICONS.sun : ICONS.moon, 20);
      themeBtn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
      themeBtn.title = themeBtn.getAttribute("aria-label");
    };
    drawThemeButton();
    themeBtn.addEventListener("click", () => toggleTheme(themeBtn));
    document.addEventListener("mediq:theme", drawThemeButton);
    systemDark.addEventListener("change", drawThemeButton);

    // Signed-in user + sign out
    user.then(u => {
      if (!u) return;
      const box = document.getElementById("ab-user");
      box.innerHTML = `${esc(u.full_name)} <button type="button" class="ui-barbutton" id="ab-signout">Sign out</button>`;
      document.getElementById("ab-signout").addEventListener("click", async () => {
        try { await api("/auth/logout", { method: "POST", quiet401: true }); } catch { /* already invalid */ }
        clearToken();
        location.href = "/login.html";
      });
    });

    // Let a page change the role/place text later (e.g. the doctor picks a room)
    return { setPlace(newPlace) { document.getElementById("ab-role").textContent = [role, newPlace].filter(Boolean).join(", "); } };
  }

  // ======================================================================
  window.mediq = {
    api, esc, user, getToken, setToken, clearToken, authHeader, goToLogin, checkAccess, ROLE_HOME,
    getTheme, toggleTheme,
    pill, message, clearMessage, toast, loading, empty, appBar, svg, ICONS,
  };
})();
