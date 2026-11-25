// shell.js: the floating sidebar on every signed-in page (patients, doctors, pharmacy, admin).
//
// What it does
//   1. Draws <aside class="sidebar"> with the pages YOU can open (based on your role).
//   2. The "Collapse" button folds it down to icons only. The choice is remembered.
//   3. On phones it is hidden; the menu button in the app bar slides it in as a drawer.
//   4. If the page has an empty <header id="app-bar">, it draws the app bar too
//      (role text from <body data-appbar-role="Admin">).
//
// Load it after core.js, before the page's own script:  <script src="shell.js"></script>
// Pages only SHOW or HIDE links here. The server still checks every request.

(function () {
  const m = window.mediq;
  if (!m) return;

  // Line drawings, 16×16, in the text colour (same style as core.js ICONS)
  const I = {
    book: '<rect x="2" y="3" width="12" height="11" rx="1.5"/><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3M8 8.5v3.5M6.25 10.25h3.5"/>',
    calendar: '<rect x="2" y="3" width="12" height="11" rx="1.5"/><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3M5 9.5h2M9 9.5h2M5 12h2"/>',
    desk: '<path d="M3.5 1.5V6a3 3 0 0 0 6 0V1.5"/><path d="M6.5 9v1.5a3.25 3.25 0 0 0 6.5 0V9"/><circle cx="13" cy="7.25" r="1.5"/>',
    chart: '<path d="M2 14h12"/><path d="M4 11.5V8M8 11.5V3.5M12 11.5V6"/>',
    bed: '<path d="M1.5 3.5V13M1.5 10.5h13V13M14.5 10.5V9a2 2 0 0 0-2-2H7v3.5"/><circle cx="4.25" cy="8.25" r="1.25"/>',
    screen: '<rect x="1.5" y="2.5" width="13" height="9" rx="1.5"/><path d="M5.5 14h5M8 11.5V14"/>',
    ambulance: '<path d="M1.5 11.5V4h8v7.5M9.5 6.5h3l2 2.5v2.5"/><circle cx="4.5" cy="12" r="1.5"/><circle cx="11.5" cy="12" r="1.5"/><path d="M5.5 5.5v3M4 7h3"/>',
    clock: '<circle cx="8" cy="8" r="6.25"/><path d="M8 4.5V8l2.5 1.5"/>',
    pill: '<path d="M3.2 9.3l6.1-6.1a2.6 2.6 0 0 1 3.6 3.6l-6.1 6.1a2.6 2.6 0 0 1-3.6-3.6z"/><path d="M6.2 6.2l3.6 3.6"/>',
    bag: '<path d="M3 5.5h10l-.8 8.5H3.8z"/><path d="M6 5.5V4a2 2 0 0 1 4 0v1.5M8 8v3.5M6.25 9.75h3.5"/>',
    box: '<path d="M2 5l6-3 6 3v6.5l-6 3-6-3z"/><path d="M2 5l6 3 6-3M8 8v6.5"/>',
    alert: '<path d="M8 2l6.5 11.5h-13z"/><path d="M8 6.5v3M8 11.5h.01"/>',
    truck: '<path d="M1.5 3.5h8V11h-8zM9.5 6h3l2 2.5V11h-5"/><circle cx="4.5" cy="12" r="1.5"/><circle cx="11.5" cy="12" r="1.5"/>',
    shield: '<path d="M8 1.5l5.5 2V8c0 3.2-2.4 5.6-5.5 6.5C4.9 13.6 2.5 11.2 2.5 8V3.5z"/><path d="M5.75 8l1.5 1.5 3-3"/>',
    phone: '<path d="M3 1.75h2.5L7 5.25 5.25 6.5a8 8 0 0 0 4.25 4.25L10.75 9l3.5 1.5V13a1.25 1.25 0 0 1-1.25 1.25A11.25 11.25 0 0 1 1.75 3 1.25 1.25 0 0 1 3 1.75z"/>',
    login: '<path d="M9.5 2.5h3v11h-3M2 8h8M7 5l3 3-3 3"/>',
    fold: '<rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><path d="M6 2.5v11M11 6l-2 2 2 2"/>',
    unfold: '<rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><path d="M6 2.5v11M9 6l2 2-2 2"/>',
    close: '<path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/>',
  };

  // Every page, grouped. roles: who may open it (admins may open everything unless notAdmin).
  // public: also shown when nobody is signed in.
  const GROUPS = [
    { title: "My care", items: [
      { label: "Book an appointment", href: "/book.html", icon: "book", roles: ["patient"], public: true, notAdmin: true },
      { label: "My appointments", href: "/my-appointments.html", icon: "calendar", roles: ["patient"], notAdmin: true },
    ] },
    { title: "Doctor", items: [
      { label: "Doctor's desk", href: "/index.html#doctor", icon: "desk", roles: ["doctor"] },
      { label: "My appointments", href: "/doctor-appointments.html", icon: "calendar", roles: ["doctor"], notAdmin: true },
    ] },
    { title: "Hospital", items: [
      { label: "Department dashboard", href: "/index.html#dashboard", icon: "chart", roles: ["doctor"] },
      { label: "Beds", href: "/index.html#beds", icon: "bed", roles: ["doctor"] },
      { label: "Waiting-room display", href: "/index.html#display", icon: "screen", roles: ["doctor"] },
      { label: "Ambulance", href: "/ambulance.html", icon: "ambulance", roles: ["doctor"] },
      { label: "Doctor timetable", href: "/schedule.html", icon: "clock", roles: null, public: true },
    ] },
    { title: "Pharmacy", items: [
      { label: "Medicines", href: "/pharmacy.html", icon: "pill", roles: null, public: true },
      { label: "Dispense", href: "/pharmacy-dispense.html", icon: "bag", roles: ["pharmacist"] },
      { label: "Stock", href: "/pharmacy-stock.html", icon: "box", roles: ["pharmacist"] },
      { label: "Alerts", href: "/pharmacy-alerts.html", icon: "alert", roles: ["pharmacist", "doctor"], badge: true },
      { label: "Suppliers", href: "/pharmacy-suppliers.html", icon: "truck", roles: ["pharmacist"] },
    ] },
    { title: "Admin", items: [
      { label: "Overview", href: "/dashboard.html", icon: "chart", roles: ["admin"] },
      { label: "Admin console", href: "/admin.html", icon: "shield", roles: ["admin"] },
      { label: "Call-back requests", href: "/staff-callbacks.html", icon: "phone", roles: ["admin"] },
    ] },
  ];

  function canSee(item, u) {
    if (!u) return Boolean(item.public);
    if (item.roles === null) return true;
    if (u.role === "admin") return !item.notAdmin;
    return item.roles.includes(u.role);
  }

  // ---------- 1. draw it ----------
  const FOLD_KEY = "mediq_sidebar";
  const body = document.body;
  body.classList.add("has-sidebar");                 // the page makes room on the left
  try { if (localStorage.getItem(FOLD_KEY) === "folded") body.classList.add("sb-folded"); } catch { /* ignore */ }

  const aside = document.createElement("aside");
  aside.className = "sidebar";
  aside.id = "sidebar";
  aside.setAttribute("aria-label", "Main menu");
  aside.innerHTML = `
    <div class="sb-top">
      <a class="sb-brand" href="/" title="mediQ home">${m.svg(m.ICONS.logo, 20)}<span class="sb-label">medi<b>Q</b></span></a>
      <button type="button" class="sb-icon sb-close" data-sidebar-close aria-label="Close menu">${m.svg(I.close, 18)}</button>
    </div>
    <nav class="sb-nav" id="sb-nav"></nav>
    <div class="sb-bottom">
      <button type="button" class="sb-link sb-fold" id="sb-fold"></button>
    </div>`;
  body.prepend(aside);

  const backdrop = document.createElement("div");
  backdrop.className = "sb-backdrop";
  backdrop.dataset.sidebarClose = "";
  body.append(backdrop);

  const nav = aside.querySelector("#sb-nav");

  function drawLinks(u) {
    nav.innerHTML = GROUPS.map(g => {
      const items = g.items.filter(it => canSee(it, u));
      if (!items.length) return "";
      return `<div class="sb-group">
        <p class="sb-title">${m.esc(g.title)}</p>
        ${items.map(it => `<a class="sb-link" href="${it.href}" data-label="${m.esc(it.label)}">
          ${m.svg(I[it.icon], 18)}<span class="sb-label">${m.esc(it.label)}</span>
          ${it.badge ? '<span class="sb-badge" id="sb-alert-badge" hidden></span>' : ""}</a>`).join("")}
      </div>`;
    }).join("") + (u ? "" : `<div class="sb-group"><a class="sb-link" href="/login.html" data-label="Log in">
      ${m.svg(I.login, 18)}<span class="sb-label">Log in</span></a></div>`);
    markCurrent();
    labelForFolded();
    refreshAlerts();
  }

  // Red number on "Alerts": low stock + expiring in 30 days + expired (pharmacy pages call this again after a change)
  async function refreshAlerts() {
    const badge = document.getElementById("sb-alert-badge");
    if (!badge) return;
    try {
      const { counts } = await m.api("/pharmacy/alerts");
      const n = counts.low_stock + counts.expiring_30 + counts.expired;
      badge.textContent = n;
      badge.hidden = n === 0;
      badge.closest(".sb-link").setAttribute("aria-label", `Alerts, ${n} need action`);
      badge.closest(".sb-link").dataset.label = `Alerts (${n})`;
    } catch { /* the count is optional */ }
  }
  window.mediqSidebar = { refreshAlerts };

  // Highlight the page you are on. /index.html has screens: no hash means the doctor's desk.
  function markCurrent(screen) {
    const path = location.pathname === "/" ? "/index.html" : location.pathname;
    const hash = screen ? `#${screen}` : (path === "/index.html" ? (location.hash || "#doctor") : "");
    nav.querySelectorAll(".sb-link").forEach(a => {
      const url = new URL(a.href);
      const here = url.pathname === path && (!url.hash || url.hash === hash);
      if (here) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }
  window.addEventListener("hashchange", () => markCurrent());
  // The doctor's desk also switches screens with its own tab buttons
  document.addEventListener("click", e => {
    const tab = e.target.closest("nav.app-tabs button[data-screen]");
    if (tab) markCurrent(tab.dataset.screen);
  });

  // ---------- 2. fold / unfold ----------
  const foldBtn = aside.querySelector("#sb-fold");
  function labelForFolded() {
    const folded = body.classList.contains("sb-folded");
    foldBtn.innerHTML = `${m.svg(folded ? I.unfold : I.fold, 18)}<span class="sb-label">Collapse</span>`;
    foldBtn.setAttribute("aria-label", folded ? "Expand menu" : "Collapse menu");
    foldBtn.setAttribute("aria-expanded", String(!folded));
    // Folded: the names become tooltips, so the icons still say what they are
    aside.querySelectorAll(".sb-link[data-label]").forEach(a => {
      if (folded) a.title = a.dataset.label; else a.removeAttribute("title");
    });
    foldBtn.title = folded ? "Expand menu" : "";
  }
  foldBtn.addEventListener("click", () => {
    const folded = body.classList.toggle("sb-folded");
    try { localStorage.setItem(FOLD_KEY, folded ? "folded" : "open"); } catch { /* ignore */ }
    labelForFolded();
  });

  // ---------- 3. phones: a drawer ----------
  let opener = null;
  function openDrawer(btn) {
    opener = btn;
    body.classList.add("sb-open");
    aside.querySelector(".sb-link, .sb-close")?.focus();
  }
  function closeDrawer() {
    if (!body.classList.contains("sb-open")) return;
    body.classList.remove("sb-open");
    opener?.focus();
  }
  document.addEventListener("click", e => {
    const open = e.target.closest("[data-sidebar-open]");
    if (open) return openDrawer(open);
    if (e.target.closest("[data-sidebar-close]")) return closeDrawer();
    if (e.target.closest(".sidebar .sb-link[href]")) closeDrawer();
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

  // ---------- 4. fill in ----------
  drawLinks(null);
  m.user.then(drawLinks);

  // Pages that used the website header get the app bar instead (role from <body>)
  document.addEventListener("DOMContentLoaded", () => {
    const bar = document.getElementById("app-bar");
    if (bar && !bar.innerHTML.trim()) m.appBar({ role: body.dataset.appbarRole || "" });
  });
})();
