// dashboard.js: the hospital overview (dashboard.html). Admins only.
//
// 1. Fetch the live numbers (every 15 seconds)        -> load()
// 2. KPI cards along the top                           -> drawKpis()
// 3. Charts, drawn as plain SVG / HTML (no library):
//      columns()   arrivals by hour, bookings per day   (one colour, the axis carries the values)
//      segments()  patients right now, call-backs       (one whole split into parts, with a legend)
//      rows()      waits per department, beds per ward, pharmacy alerts (a name, a bar, a number)
// Colours come from CSS (--c-*), so light/dark mode switches them with no redraw.
// Every chart has a table version ("Show as a table") for screen readers and exact numbers.

(function () {
  const m = window.mediq;
  const { api, esc } = m;

  // ---------------------------------------------------------- small helpers
  const $ = id => document.getElementById(id);
  const sum = list => list.reduce((a, b) => a + b, 0);
  const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
  const fmt = n => Number(n).toLocaleString("en-IN");
  const NS = "http://www.w3.org/2000/svg";

  // A "nice" top for an axis: 0-4 -> 4, 7 -> 8, 13 -> 15, 42 -> 50
  function niceMax(v) {
    if (v <= 4) return 4;
    const p = 10 ** Math.floor(Math.log10(v));
    for (const s of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (s * p >= v) return s * p;
    return 10 * p;
  }

  // One tooltip for the whole page. Shown on hover AND on keyboard focus.
  const tip = $("chart-tip");
  function showTip(target, html) {
    tip.innerHTML = html;
    tip.hidden = false;
    const r = target.getBoundingClientRect();
    const t = tip.getBoundingClientRect();
    let x = r.left + r.width / 2 - t.width / 2;
    x = Math.max(8, Math.min(x, innerWidth - t.width - 8));
    let y = r.top - t.height - 10;
    if (y < 8) y = r.bottom + 10;
    tip.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }
  const hideTip = () => { tip.hidden = true; };
  function withTip(el, html) {
    el.addEventListener("mouseenter", () => showTip(el, html));
    el.addEventListener("mouseleave", hideTip);
    el.addEventListener("focus", () => showTip(el, html));
    el.addEventListener("blur", hideTip);
  }
  addEventListener("scroll", hideTip, { passive: true });

  function table(el, head, rows) {
    el.innerHTML = `<table class="ui-table"><thead><tr>${head.map(h => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(r => `<tr>${r.map((c, i) => i ? `<td class="num">${esc(c)}</td>` : `<th scope="row">${esc(c)}</th>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  // ---------------------------------------------------------- chart 1: columns
  // data: [{ label, value, tip, now }]. One hue; the "now" column is marked with a label.
  function columns(el, data, { unit, unitOne }) {
    el.innerHTML = "";
    const W = Math.max(280, el.clientWidth), H = 220;
    const pad = { top: 22, right: 8, bottom: 28, left: 32 };
    const iw = W - pad.left - pad.right, ih = H - pad.top - pad.bottom;
    const top = niceMax(Math.max(1, ...data.map(d => d.value)));
    const band = iw / data.length;
    const bw = Math.min(24, Math.max(6, band - 6));          // thin bars; the rest of the band is air
    const y = v => pad.top + ih - (v / top) * ih;

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${data.map(d => `${d.label}: ${plural(d.value, unitOne, unit)}`).join(", ")}`);

    let out = "";
    // Gridlines and ticks: 0, half, top. Hairlines, recessive.
    for (const v of [0, top / 2, top]) {
      out += `<line class="ch-grid${v === 0 ? " ch-base" : ""}" x1="${pad.left}" x2="${W - pad.right}" y1="${y(v)}" y2="${y(v)}"/>
              <text class="ch-tick" x="${pad.left - 8}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`;
    }
    // Label every column if they fit, else every 2nd / 3rd
    const every = Math.ceil(36 / band);
    data.forEach((d, i) => {
      const cx = pad.left + band * i + band / 2;
      const h = Math.max(0, y(0) - y(d.value));
      const x = cx - bw / 2, r = Math.min(4, h / 2, bw / 2);
      if (h > 0) {   // 4px rounded data end, square at the baseline
        out += `<path class="ch-bar${d.now ? " ch-bar--now" : ""}" d="M${x},${y(0)} V${y(d.value) + r} Q${x},${y(d.value)} ${x + r},${y(d.value)}
                H${x + bw - r} Q${x + bw},${y(d.value)} ${x + bw},${y(d.value) + r} V${y(0)} Z"/>`;
      }
      if (d.now || i % every === 0) {
        out += `<text class="ch-tick${d.now ? " ch-tick--now" : ""}" x="${cx}" y="${H - 8}" text-anchor="middle">${esc(d.short || d.label)}</text>`;
      }
      if (d.now && d.value > 0) {
        out += `<text class="ch-value" x="${cx}" y="${y(d.value) - 6}" text-anchor="middle">${fmt(d.value)}</text>`;
      }
    });
    svg.innerHTML = out;

    // Hit targets: the whole band, full height (bigger than the bar), focusable
    data.forEach((d, i) => {
      const hit = document.createElementNS(NS, "rect");
      hit.setAttribute("class", "ch-hit");
      hit.setAttribute("x", pad.left + band * i);
      hit.setAttribute("y", pad.top);
      hit.setAttribute("width", band);
      hit.setAttribute("height", ih);
      hit.setAttribute("tabindex", "0");
      hit.setAttribute("aria-label", `${d.label}: ${plural(d.value, unitOne, unit)}`);
      withTip(hit, `<b>${esc(d.label)}</b>${esc(plural(d.value, unitOne, unit))}`);
      svg.appendChild(hit);
    });
    el.appendChild(svg);
  }

  // ---------------------------------------------------------- chart 2: one whole, split into parts
  // parts: [{ name, value, cls }]  -> a tall segmented bar + a legend that gives the numbers
  function segments(el, parts, { total, emptyText, thin = false }) {
    const whole = sum(parts.map(p => p.value));
    if (!whole) { el.innerHTML = `<div class="ui-empty">${esc(emptyText)}</div>`; return; }
    const shown = parts.filter(p => p.value > 0);
    el.innerHTML = `
      ${total ? `<p class="seg-total"><span class="seg-total__n">${fmt(whole)}</span> ${esc(whole === 1 ? total[0] : total[1])}</p>` : ""}
      <div class="seg ${thin ? "seg--thin" : ""}" role="img"
           aria-label="${esc(parts.map(p => `${p.name}: ${p.value}`).join(", "))}">
        ${shown.map(p => {
          const pct = Math.round((p.value / whole) * 100);
          return `<span class="seg__part ${p.cls}" style="flex-grow:${p.value}" tabindex="0"
                        data-tip="${esc(p.name)}|${p.value}|${pct}">${!thin && pct >= 12 ? `${pct}%` : ""}</span>`;
        }).join("")}
      </div>
      <ul class="seg-legend">
        ${parts.map(p => `<li><span class="key ${p.cls}"></span><span class="seg-legend__name">${esc(p.name)}</span>
          <b>${fmt(p.value)}</b></li>`).join("")}
      </ul>`;
    el.querySelectorAll("[data-tip]").forEach(s => {
      const [name, value, pct] = s.dataset.tip.split("|");
      withTip(s, `<b>${esc(name)}</b>${fmt(value)} · ${pct}%`);
    });
  }

  // ---------------------------------------------------------- chart 3: rows (name, bar, number)
  // rows: [{ name, value, max, cls, figure, note, icon }]  bars share one scale unless max is given
  function rows(el, list, { emptyText } = {}) {
    if (!list.length) { el.innerHTML = `<div class="ui-empty">${esc(emptyText || "Nothing yet.")}</div>`; return; }
    const scale = Math.max(1, ...list.map(r => r.value));
    el.innerHTML = `<ul class="rows">${list.map(r => {
      const pct = r.value == null ? 0 : Math.min(100, (r.value / (r.max || scale)) * 100);
      return `<li class="rows__item">
        <span class="rows__name">${r.icon || ""}${esc(r.name)}</span>
        <span class="rows__figure">${r.figure}</span>
        <span class="rows__track${r.max ? " rows__track--meter" : ""}" aria-hidden="true">
          <span class="rows__bar ${r.cls || ""}" style="width:${pct}%"></span></span>
        ${r.note ? `<span class="rows__note">${r.note}</span>` : ""}
      </li>`;
    }).join("")}</ul>`;
  }

  // ---------------------------------------------------------- KPI cards
  const ICON = {
    people: '<circle cx="6" cy="5" r="2.5"/><path d="M1.5 14v-1a4.5 4.5 0 0 1 9 0v1"/><path d="M11 2.75a2.5 2.5 0 0 1 0 4.5M12.5 9.5a4.5 4.5 0 0 1 2 3.75V14"/>',
    clock: '<circle cx="8" cy="8" r="6.25"/><path d="M8 4.5V8l2.5 1.5"/>',
    bed: '<path d="M1.5 3.5V13M1.5 10.5h13V13M14.5 10.5V9a2 2 0 0 0-2-2H7v3.5"/><circle cx="4.25" cy="8.25" r="1.25"/>',
    desk: '<path d="M3.5 1.5V6a3 3 0 0 0 6 0V1.5"/><path d="M6.5 9v1.5a3.25 3.25 0 0 0 6.5 0V9"/><circle cx="13" cy="7.25" r="1.5"/>',
    ambulance: '<path d="M1.5 11.5V4h8v7.5M9.5 6.5h3l2 2.5v2.5"/><circle cx="4.5" cy="12" r="1.5"/><circle cx="11.5" cy="12" r="1.5"/><path d="M5.5 5.5v3M4 7h3"/>',
    alert: '<path d="M8 2l6.5 11.5h-13z"/><path d="M8 6.5v3M8 11.5h.01"/>',
    ok: '<path d="M3 8.5l3 3 7-7"/>',
  };

  function kpi({ icon, label, value, unit = "", sub, meter, state }) {
    return `<article class="kpi${state ? ` kpi--${state}` : ""}">
      <p class="kpi__label">${m.svg(ICON[icon], 16)}${esc(label)}</p>
      <p class="kpi__value">${value}${unit ? `<span class="kpi__unit">${esc(unit)}</span>` : ""}</p>
      ${meter != null ? `<span class="kpi__meter" aria-hidden="true"><span style="width:${Math.round(meter * 100)}%"></span></span>` : ""}
      <p class="kpi__sub">${sub}</p>
    </article>`;
  }

  function drawKpis(d) {
    const waiting = sum(d.stats.map(s => s.waiting));
    const withDoctor = sum(d.stats.map(s => s.in_consultation));
    const seen = d.activity.waits_today.filter(w => w.avg_wait_minutes != null);
    const seenCount = sum(seen.map(w => w.seen));
    const avgWait = seenCount ? sum(seen.map(w => w.avg_wait_minutes * w.seen)) / seenCount : null;
    const beds = d.overview.beds;
    const amb = d.overview.ambulances;
    const ambTotal = amb.available + amb.on_trip + amb.maintenance;
    const c = d.alerts.counts;
    const alerts = c.low_stock + c.expiring_30 + c.expired;

    $("kpis").innerHTML = [
      kpi({ icon: "people", label: "Waiting now", value: fmt(waiting),
            sub: `${fmt(withDoctor)} with a doctor · ${plural(d.stats.length, "queue")}` }),
      kpi({ icon: "clock", label: "Average wait", value: avgWait == null ? "–" : fmt(Math.round(avgWait)),
            unit: avgWait == null ? "" : "min",
            sub: seenCount ? `Today, ${plural(seenCount, "patient")} seen` : "Nobody seen yet today" }),
      kpi({ icon: "bed", label: "Beds free", value: fmt(beds.free), unit: `/ ${fmt(beds.total)}`,
            meter: beds.total ? beds.occupied / beds.total : 0,
            sub: `${beds.total ? Math.round((beds.occupied / beds.total) * 100) : 0}% occupied`,
            state: beds.total && beds.free === 0 ? "critical" : null }),
      kpi({ icon: "desk", label: "Doctors in", value: fmt(d.overview.doctors_on_duty), sub: "On OPD duty right now" }),
      kpi({ icon: "ambulance", label: "Ambulances", value: fmt(amb.available), unit: `/ ${fmt(ambTotal)}`,
            meter: ambTotal ? amb.available / ambTotal : 0,
            sub: `Ready · ${fmt(amb.on_trip)} on a trip · ${fmt(amb.maintenance)} in service`,
            state: ambTotal && amb.available === 0 ? "critical" : null }),
      kpi({ icon: alerts ? "alert" : "ok", label: "Stock alerts", value: fmt(alerts),
            sub: alerts ? `${fmt(c.low_stock)} low · ${fmt(c.expiring_30)} expiring · ${fmt(c.expired)} expired` : "All stock is fine",
            state: c.expired ? "critical" : alerts ? "warning" : null }),
    ].join("");
  }

  // ---------------------------------------------------------- the charts
  const hourLabel = h => `${String(h).padStart(2, "0")}:00`;
  const DAY = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric" });

  function drawCharts(d) {
    // Arrivals by hour: show OPD hours (08:00-20:00), widened if patients came earlier or later
    const byHour = d.activity.arrivals_by_hour;
    const nowHour = d.nowHour;
    const busy = byHour.filter(h => h.arrivals > 0).map(h => h.hour);
    const from = Math.min(8, ...busy), to = Math.max(20, nowHour, ...busy);
    const hours = byHour.filter(h => h.hour >= from && h.hour <= to).map(h => ({
      label: `${hourLabel(h.hour)}–${hourLabel((h.hour + 1) % 24)}`, short: h.hour === nowHour ? "Now" : hourLabel(h.hour),
      value: h.hour > nowHour ? 0 : h.arrivals, now: h.hour === nowHour,
    }));
    columns($("chart-arrivals"), hours, { unit: "arrivals", unitOne: "arrival" });
    table($("table-arrivals"), ["Hour", "Arrivals"], hours.filter((_, i) => byHour[from + i].hour <= nowHour)
      .map(h => [h.label, fmt(h.value)]));

    // Patients right now: waiting -> with a doctor -> seen today
    segments($("chart-flow"), [
      { name: "Waiting", value: sum(d.stats.map(s => s.waiting)), cls: "c-amber" },
      { name: "With a doctor", value: sum(d.stats.map(s => s.in_consultation)), cls: "c-blue" },
      { name: "Seen today", value: sum(d.stats.map(s => s.done_today)), cls: "c-green" },
    ], { total: ["patient today", "patients today"], emptyText: "No patients in the OPD yet today." });

    // Average wait per department (one hue); the estimate for a newcomer is the note
    const est = Object.fromEntries(d.stats.map(s => [s.department.name, s.wait_for_new_patient_minutes]));
    rows($("chart-waits"), d.activity.waits_today.map(w => ({
      name: w.department,
      value: w.avg_wait_minutes ?? 0,
      cls: "c-blue",
      figure: w.avg_wait_minutes == null ? `<span class="muted">–</span>` : `${fmt(Math.round(w.avg_wait_minutes))} min`,
      note: `${w.seen ? plural(w.seen, "patient") + " seen" : "Nobody seen yet"} · a new patient waits about ${fmt(Math.round(est[w.department] || 0))} min`,
    })), { emptyText: "No departments yet." });
    table($("table-waits"), ["Department", "Average wait (min)", "Seen today"], d.activity.waits_today.map(w =>
      [w.department, w.avg_wait_minutes == null ? "–" : String(Math.round(w.avg_wait_minutes)), String(w.seen)]));

    // Beds: a meter per ward. 85%+ turns amber, full turns red (with a word, never colour alone)
    rows($("chart-beds"), d.wards.map(w => {
      const share = w.total ? w.occupied / w.total : 0;
      const state = w.free === 0 ? "full" : share >= 0.85 ? "busy" : null;
      return {
        name: w.ward, value: w.occupied, max: Math.max(1, w.total),
        cls: state === "full" ? "c-red" : state === "busy" ? "c-amber" : "c-blue",
        figure: `${fmt(w.occupied)}<span class="muted"> / ${fmt(w.total)}</span>`,
        note: state === "full" ? `${m.svg(ICON.alert, 14)} Full` : state === "busy" ? `${m.svg(ICON.alert, 14)} ${plural(w.free, "bed")} left`
                                : `${plural(w.free, "bed")} free`,
      };
    }), { emptyText: "No wards yet." });

    // Bookings for the next 7 days
    const days = d.activity.bookings_next_7_days.map((b, i) => {
      const dt = new Date(b.date + "T00:00:00");
      return { label: i === 0 ? `Today (${DAY.format(dt)})` : DAY.format(dt), short: i === 0 ? "Today" : DAY.format(dt),
               value: b.bookings, now: i === 0 };
    });
    columns($("chart-bookings"), days, { unit: "bookings", unitOne: "booking" });
    table($("table-bookings"), ["Day", "Bookings"], days.map(x => [x.label, fmt(x.value)]));

    // Pharmacy: what needs action, worst first; status colours always with an icon and a word
    const c = d.alerts.counts;
    rows($("chart-pharmacy"), [
      { name: "Expired", value: c.expired, cls: "c-red", icon: m.svg(ICON.alert, 14), figure: fmt(c.expired), note: "Remove from the shelf" },
      { name: "Expiring in 30 days", value: c.expiring_30, cls: "c-amber", icon: m.svg(ICON.clock, 14), figure: fmt(c.expiring_30), note: "Use first or return" },
      { name: "Low stock", value: c.low_stock, cls: "c-amber", icon: m.svg(ICON.alert, 14), figure: fmt(c.low_stock), note: "Reorder soon" },
    ]);

    // Call-backs: done, calling, waiting to be called, failed (this order keeps red away from green)
    const cb = d.overview.callbacks;
    segments($("chart-calls"), [
      { name: "Done", value: cb.done || 0, cls: "c-green" },
      { name: "Calling now", value: cb.calling || 0, cls: "c-blue" },
      { name: "Waiting for a call", value: cb.pending || 0, cls: "c-amber" },
      { name: "Couldn't reach", value: cb.failed || 0, cls: "c-red" },
    ], { thin: true, total: ["request", "requests"], emptyText: "No call-back requests yet." });
  }

  // ---------------------------------------------------------- load + refresh
  let last = null;
  async function load() {
    try {
      const [overview, activity, depts, wards, alerts] = await Promise.all([
        api("/admin/overview"), api("/admin/activity"), api("/departments"),
        api("/wards/availability"), api("/pharmacy/alerts"),
      ]);
      const stats = await Promise.all(depts.map(x => api(`/departments/${x.id}/stats`)));
      // The hospital's hour now (the server already worked out "today" in hospital time)
      const tz = await hospitalZone();
      const nowHour = Number(new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hour12: false, timeZone: tz }).format(new Date())) % 24;
      last = { overview, activity, stats, wards, alerts, nowHour };
      draw();
      m.clearMessage($("dash-msg"));
      $("dash-updated").textContent = `Updated ${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}.`;
    } catch (err) {
      m.message($("dash-msg"), { type: "error", title: "Couldn't load the numbers", text: err.message });
    }
  }
  function draw() { if (last) { drawKpis(last); drawCharts(last); } }

  let zone = null;
  async function hospitalZone() {
    if (zone) return zone;
    try { zone = (await api("/schedule/on-duty")).timezone || "Asia/Kolkata"; } catch { zone = "Asia/Kolkata"; }
    return zone;
  }

  // Redraw the SVG charts when their width changes (sidebar folded, window resized)
  let resizeTimer;
  new ResizeObserver(() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(draw, 120); }).observe($("main"));

  // ---------------------------------------------------------- who may see it
  m.user.then(u => {
    const access = m.checkAccess(u, ["admin"]);
    if (access === "login") return m.goToLogin();
    if (access === "forbidden") {
      $("main").innerHTML = `<h1>No access</h1><p class="ui-lead">The hospital overview is for admin accounts.</p>`;
      return;
    }
    load();
    setInterval(load, 15000);
  });
})();
