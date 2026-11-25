// Shared helpers for the pharmacy pages (Module 4). Load after core.js.
//
//   const { u, allowed } = await PH.start({ roles: ["pharmacist"] });
//       draws the blue app bar + the pharmacy sub-menu, and checks the login.
//       roles: who may use the page (admins always may); null = everyone.
//   PH.money(12.5)        -> "₹12.50"
//   PH.date("2027-03-01") -> "01 Mar 2027"
//   PH.schedulePill("H"), PH.stockPill(med), PH.expiryPill(daysLeft)
//   PH.medicinePicker(input, { onPick })   search-as-you-type box for medicines
//
// Everything the server sends is passed through esc() before it goes into HTML.

(function () {
  const m = window.mediq;
  const { esc, svg } = m;

  // The pharmacy sub-menu. roles: who sees the link (null = everyone).
  const PAGES = [
    { href: "/pharmacy.html", label: "Catalogue", roles: null },
    { href: "/pharmacy-dispense.html", label: "Dispense", roles: ["pharmacist"] },
    { href: "/pharmacy-stock.html", label: "Stock", roles: ["pharmacist"] },
    { href: "/pharmacy-alerts.html", label: "Alerts", roles: ["pharmacist", "doctor"], badge: true },
    { href: "/pharmacy-suppliers.html", label: "Suppliers", roles: ["pharmacist"] },
  ];

  // Small line drawings (16×16, in the text colour) for the pills
  const ICON = {
    rx: '<path d="M4 1.5h5.5L12 4v10.5H4z"/><path d="M6 7h4M6 9.5h4"/>',          // a prescription sheet
    ok: '<path d="M3 8.5l3 3 7-7"/>',                                              // tick
    alert: '<path d="M8 2l6.5 11.5h-13z"/><path d="M8 6.5v3M8 11.5h.01"/>',          // warning triangle
    clock: '<circle cx="8" cy="8" r="6.25"/><path d="M8 4.5V8l2.5 1.5"/>',
    cross: '<path d="M4 4l8 8M12 4l-8 8"/>',
    cold: '<path d="M8 1.5v13M2.5 4.75l11 6.5M13.5 4.75l-11 6.5"/>',                  // snowflake
  };
  const pillHTML = (kind, icon, word, title = "") =>
    `<span class="ui-pill ui-pill--${kind}"${title ? ` title="${esc(title)}"` : ""}>${svg(ICON[icon], 14)}${esc(word)}</span>`;

  // ---------------------------------------------------------------- formats
  const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
  const money = n => (n === null || n === undefined ? "–" : inr.format(n));
  // "2027-03-01" is read as LOCAL midnight (adding T00:00), so the day never shifts
  const date = d => (d ? new Date(d.length === 10 ? d + "T00:00" : d)
    .toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "–");
  const dateTime = d => (d ? new Date(d).toLocaleString("en-GB", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "–");
  const isoDate = d => {          // a Date -> "2027-03-01" for <input type="date">
    const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
    return z.toISOString().slice(0, 10);
  };
  const medName = med => med.display_name;          // "Dolo 650", "Crocin Advance 500 mg" (from the server)

  // ---------------------------------------------------------------- pills
  function schedulePill(schedule) {
    if (schedule === "OTC") return pillHTML("good", "ok", "OTC", "Over the counter: no prescription needed");
    return pillHTML(schedule === "X" ? "bad" : "warn", "rx", `Schedule ${schedule}`,
      "Prescription needed (Drugs & Cosmetics Rules)");
  }
  function stockPill(med) {
    if (med.stock === 0) return pillHTML("bad", "cross", "Out of stock");
    if (med.low_stock) return pillHTML("warn", "alert", "Low", `At or below the reorder level of ${med.reorder_level}`);
    return "";
  }
  function expiryPill(daysLeft) {
    if (daysLeft <= 0) return pillHTML("bad", "cross", "Expired");
    if (daysLeft <= 30) return pillHTML("bad", "clock", `${daysLeft} days left`);
    if (daysLeft <= 90) return pillHTML("warn", "clock", `${daysLeft} days left`);
    return "";
  }
  const coldPill = () => pillHTML("info", "cold", "2–8 °C", "Keep in the fridge");

  // ---------------------------------------------------------------- page start
  async function start({ roles = null } = {}) {
    m.appBar({ role: "Pharmacy", place: "Main counter" });
    const u = await m.user;

    const nav = document.getElementById("ph-nav");
    const here = location.pathname;
    nav.innerHTML = PAGES.filter(p => m.checkAccess(u, p.roles) === "ok").map(p => `
      <a href="${p.href}" ${p.href === here ? 'aria-current="page"' : ""}>${esc(p.label)}
        ${p.badge ? '<span class="ph-badge" id="ph-alert-badge" hidden></span>' : ""}</a>`).join("");
    nav.setAttribute("aria-label", "Pharmacy");

    // Red number on "Alerts": low stock + expiring in 30 days + expired
    if (document.getElementById("ph-alert-badge")) refreshBadge();

    const access = m.checkAccess(u, roles);
    if (access === "offline") return { u, allowed: false };   // still logged in; core.js shows "Can't reach..."
    if (access !== "ok") {
      const main = document.querySelector("main");
      const who = roles.map(r => (r === "pharmacist" ? "pharmacist" : r)).join(" or ");
      main.innerHTML = `<div id="ph-locked"></div>`;
      m.message(document.getElementById("ph-locked"), {
        type: "error",
        title: access === "login" ? "Please log in" : "Pharmacy staff only",
        text: access === "login"
          ? `This page is for hospital staff. Log in with a ${who} account.`
          : `This page needs a ${who} account. You're signed in as ${u.full_name} (${u.role}).`,
      });
      if (access === "login") {
        main.insertAdjacentHTML("beforeend",
          `<a class="ui-button ui-button--action" href="/login.html?next=${encodeURIComponent(here)}">Log in</a>`);
      }
      return { u, allowed: false };
    }
    return { u, allowed: true };
  }

  async function refreshBadge() {
    const badge = document.getElementById("ph-alert-badge");
    if (!badge) return;
    try {
      const { counts } = await m.api("/pharmacy/alerts");
      const n = counts.low_stock + counts.expiring_30 + counts.expired;
      badge.textContent = n;
      badge.hidden = n === 0;
      badge.setAttribute("aria-label", `${n} urgent`);
    } catch { /* the badge is optional */ }
  }

  // ---------------------------------------------------------------- medicine search box
  // Uses a <datalist>: the browser shows suggestions under the box and they
  // work with the keyboard (arrow keys + Enter) with no extra code.
  // Each suggestion's text is unique (brand + strength + form), so we can map
  // the chosen text back to the medicine.
  function medicinePicker(input, { onPick = () => {}, inStockOnly = false } = {}) {
    const list = document.createElement("datalist");
    list.id = `${input.id}-options`;
    input.setAttribute("list", list.id);
    input.setAttribute("autocomplete", "off");
    input.after(list);

    let options = new Map();       // suggestion text -> medicine
    let timer;
    const label = x => `${x.display_name} ${x.dosage_form} · ${x.generic_name}`;

    input.addEventListener("input", () => {
      const chosen = options.get(input.value);
      if (chosen) { onPick(chosen); return; }
      clearTimeout(timer);
      timer = setTimeout(async () => {           // wait until typing pauses (200 ms)
        const q = input.value.trim();
        if (q.length < 2) return;
        try {
          const meds = await m.api(`/pharmacy/medicines?q=${encodeURIComponent(q)}&limit=20${inStockOnly ? "&in_stock_only=true" : ""}`);
          options = new Map(meds.map(x => [label(x), x]));
          list.innerHTML = meds.map(x =>
            `<option value="${esc(label(x))}">${x.stock} in stock${x.schedule !== "OTC" ? " · Rx" : ""}</option>`).join("");
        } catch { /* leave the old suggestions */ }
      }, 200);
    });
    return {
      get selected() { return options.get(input.value) || null; },
      clear() { input.value = ""; },
    };
  }

  // Turn a <form> into a plain object: { name: value }. Empty strings become null.
  function formData(form) {
    const out = {};
    for (const [k, v] of new FormData(form).entries()) out[k] = v === "" ? null : v;
    return out;
  }

  window.PH = {
    start, refreshBadge, money, date, dateTime, isoDate, medName,
    schedulePill, stockPill, expiryPill, coldPill, medicinePicker, formData,
  };
})();
