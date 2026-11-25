// Shared helpers for the patient pages (Module 5). Load after core.js.
//
//   const { u, allowed } = await PT.start({ place: "Book an appointment" });
//       draws the app bar + the "Book · My appointments" menu and checks that
//       a PATIENT is logged in (others get a friendly message instead).
//   PT.statusPill(status), PT.day("2026-11-30"), PT.time("09:20:00")
//
// Banners: once a patient is in, start() also shows their unread messages
// (GET /api/notifications/me) at the top of the page, checks for new ones every
// 15 seconds, and fires a "mediq:notification" event so the page can refresh.
(function () {
  const m = window.mediq, { esc, svg } = m;

  const PAGES = [
    { href: "/book.html", label: "Book an appointment" },
    { href: "/my-appointments.html", label: "My appointments" },
  ];

  async function start({ place = "" } = {}) {
    m.appBar({ role: "Patient", place });
    const nav = document.getElementById("pt-nav");
    nav.setAttribute("aria-label", "Appointments");
    nav.innerHTML = PAGES.map(p =>
      `<a href="${p.href}" ${p.href === location.pathname ? 'aria-current="page"' : ""}>${esc(p.label)}</a>`).join("");

    const u = await m.user;
    const access = m.checkAccess(u, ["patient"]);
    if (access === "ok") {
      startBanners();
      return { u, allowed: true };
    }

    if (access === "offline") return { u, allowed: false };       // still logged in; core.js shows "Can't reach..."
    const main = document.querySelector("main");
    const here = encodeURIComponent(location.pathname);
    main.innerHTML = `<h1>${access === "login" ? "Log in to book" : "This page is for patients"}</h1><div id="pt-locked"></div>`;
    m.message(document.getElementById("pt-locked"), access === "login"
      ? { type: "info", title: "You need a patient account",
          text: "Log in, or create a free account in a minute. Then you can book and follow your appointments here." }
      : { type: "error", title: "Booking is for patient accounts",
          text: `You're signed in as ${u.full_name} (${u.role}). Doctors see their bookings on the Doctor's desk.` });
    if (access === "login") {
      main.insertAdjacentHTML("beforeend", `<div class="ph-actions">
        <a class="ui-button ui-button--action" href="/login.html?next=${here}">Log in</a>
        <a class="ui-button ui-button--secondary" href="/signup.html?next=${here}">Create an account</a></div>`);
    }
    return { u, allowed: false };
  }

  // ---------------------------------------------------------------- banners
  const BANNER = {
    called: ["success", "It's your turn"], booked: ["success", "Booked"], accepted: ["success", "Booking accepted"],
    requested: ["info", "Request sent"], rejected: ["error", "Booking not accepted"], no_show: ["error", "Missed appointment"],
  };
  const shown = new Set();

  function startBanners() {
    const area = document.createElement("div");
    area.id = "pt-banners";
    area.setAttribute("aria-live", "polite");
    document.querySelector("main h1").after(area);
    // With 2 or more messages, one button hides them all
    const drawGotAll = () => {
      const boxes = area.querySelectorAll(".pt-banner").length;
      let all = area.querySelector("#pt-read-all");
      if (boxes >= 2 && !all) {
        area.insertAdjacentHTML("beforeend", `<button class="ui-button ui-button--secondary" type="button" id="pt-read-all">Got it, all ${boxes}</button>`);
      } else if (all) {
        if (boxes < 2) all.remove(); else all.textContent = `Got it, all ${boxes}`;
      }
    };
    area.addEventListener("click", async e => {
      if (e.target.closest("#pt-read-all")) {
        area.innerHTML = "";
        try { await m.api("/notifications/read-all", { method: "POST" }); } catch { /* shows again next time */ }
        return;
      }
      const b = e.target.closest("[data-read]");
      if (!b) return;
      b.closest(".pt-banner").remove();
      drawGotAll();
      try { await m.api(`/notifications/${b.dataset.read}/read`, { method: "POST" }); } catch { /* shows again next time */ }
    });
    const check = async () => {
      let notes = [];
      try { notes = await m.api("/notifications/me?unread_only=true"); } catch { return; }
      const fresh = notes.filter(n => !shown.has(n.id)).reverse();      // oldest first, so the newest ends on top
      for (const n of fresh) {
        shown.add(n.id);
        const [type, title] = BANNER[n.event] || ["info", "Update"];
        const box = document.createElement("div");
        box.className = `pt-banner${n.event === "called" ? " pt-banner--turn" : ""}`;
        box.innerHTML = `<div></div><button class="ui-button ui-button--secondary" type="button" data-read="${n.id}">Got it</button>`;
        // The title already says "Booked" / "It's your turn", so drop that start from the text
        const text = n.message.replace(/^(Booked|It's your turn): /, "").replace(/^./, c => c.toUpperCase());
        m.message(box.firstElementChild, { type, title, text });
        area.prepend(box);
        if (n.event === "called") navigator.vibrate?.([300, 150, 300]);   // phones: a buzz for "your turn"
      }
      if (fresh.length) document.dispatchEvent(new CustomEvent("mediq:notification"));
      drawGotAll();
    };
    check();
    setInterval(() => { if (!document.hidden) check(); }, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
  }

  // Status pill: always an icon + words, never colour alone
  const ICON = {
    clock: '<circle cx="8" cy="8" r="6.25"/><path d="M8 4.5V8l2.5 1.5"/>',
    ok: '<path d="M3 8.5l3 3 7-7"/>',
    cross: '<path d="M4 4l8 8M12 4l-8 8"/>',
    pin: '<path d="M8 14.5s4.5-4.2 4.5-8a4.5 4.5 0 0 0-9 0c0 3.8 4.5 8 4.5 8z"/><circle cx="8" cy="6.5" r="1.5"/>',
  };
  const STATUS = {
    requested: ["warn", "clock", "Waiting for the doctor to accept"],
    accepted: ["good", "ok", "Confirmed"],
    rejected: ["bad", "cross", "Not accepted"],
    cancelled: ["waiting", "cross", "Cancelled"],
    checked_in: ["info", "pin", "Checked in"],
    completed: ["good", "ok", "Completed"],
    no_show: ["bad", "cross", "Missed"],
  };
  function statusPill(status) {
    const [kind, icon, word] = STATUS[status] || ["waiting", "clock", status];
    return `<span class="ui-pill ui-pill--${kind}">${svg(ICON[icon], 14)}${esc(word)}</span>`;
  }

  // "2026-11-30" -> "Mon 30 Nov" (read as LOCAL midnight so the day never shifts)
  const day = d => new Date(`${d}T00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const time = t => t.slice(0, 5);                                     // "09:20:00" -> "09:20"
  const isoDate = d => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

  window.PT = { start, statusPill, day, time, isoDate };
})();
