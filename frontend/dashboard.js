// dashboard.js: the hospital overview (dashboard.html). Admins only.
//
// Main view (the highest-priority numbers only):
//   drawKpis()     4 key numbers
//   lineChart()    arrivals across the day         (a trend over time -> a line)
//   sortedBars()   average wait by department      (a comparison -> bars, longest first)
// Tabs (details, one at a time):
//   Queues, Beds (sorted bars + table), Bookings (columns + table), Pharmacy, Staff and fleet
//
// Colour: neutral greys for most marks; cobalt marks the ONE key point (now, the longest wait);
// amber/red only for a problem, and always with an icon and a word.
// Numbers: whole minutes and whole percents everywhere; right-aligned in tables.

(function () {
  const m = window.mediq;
  const { api, esc } = m;

  // ---------------------------------------------------------- helpers
  const $ = id => document.getElementById(id);
  const sum = list => list.reduce((a, b) => a + b, 0);
  const fmt = n => Math.round(Number(n)).toLocaleString("en-IN");   // whole numbers, Indian grouping
  const pct = (part, whole) => (whole ? Math.round((part / whole) * 100) : 0);
  const plural = (n, one, many = one + "s") => `${fmt(n)} ${Number(n) === 1 ? one : many}`;
  const NS = "http://www.w3.org/2000/svg";
  const ICON = {
    alert: '<path d="M8 2l6.5 11.5h-13z"/><path d="M8 6.5v3M8 11.5h.01"/>',
    ok: '<path d="M3 8.5l3 3 7-7"/>',
  };

  // Top of an axis: a round number just above the largest value
  function niceMax(v) {
    if (v <= 4) return 4;
    const p = 10 ** Math.floor(Math.log10(v));
    for (const s of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (s * p >= v) return s * p;
    return 10 * p;
  }

  // One tooltip for the page, on hover and on keyboard focus
  const tip = $("chart-tip");
  function showTip(target, html) {
    tip.innerHTML = html;
    tip.hidden = false;
    const r = target.getBoundingClientRect(), t = tip.getBoundingClientRect();
    const x = Math.max(8, Math.min(r.left + r.width / 2 - t.width / 2, innerWidth - t.width - 8));
    const y = r.top - t.height - 10 < 8 ? r.bottom + 10 : r.top - t.height - 10;
    tip.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }
  const hideTip = () => { tip.hidden = true; };
  addEventListener("scroll", hideTip, { passive: true });

  // A table: first column is the name (left), the rest are numbers (right-aligned)
  function table(el, caption, head, rows, foot) {
    el.innerHTML = `<div class="tbl-scroll"><table class="ui-table dash-tbl">
      <caption>${esc(caption)}</caption>
      <thead><tr>${head.map((h, i) => `<th scope="col"${i ? ' class="num"' : ""}>${esc(h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(r => `<tr>${r.map((c, i) => i ? `<td class="num">${c}</td>` : `<th scope="row">${c}</th>`).join("")}</tr>`).join("")}</tbody>
      ${foot ? `<tfoot><tr>${foot.map((c, i) => i ? `<td class="num">${c}</td>` : `<th scope="row">${c}</th>`).join("")}</tr></tfoot>` : ""}
    </table></div>`;
  }

  // A status word with its icon: never colour alone
  const status = (kind, word) => `<span class="st st--${kind}">${m.svg(kind === "ok" ? ICON.ok : ICON.alert, 14)}${esc(word)}</span>`;

  // ---------------------------------------------------------- 1. KPIs
  function drawKpis(d) {
    const waiting = sum(d.stats.map(s => s.waiting));
    const withDoctor = sum(d.stats.map(s => s.in_consultation));
    const seen = d.activity.waits_today.filter(w => w.avg_wait_minutes != null);
    const seenCount = sum(seen.map(w => w.seen));
    const avg = seenCount ? sum(seen.map(w => w.avg_wait_minutes * w.seen)) / seenCount : null;
    const beds = d.overview.beds;
    const c = d.alerts.counts;
    const alerts = c.low_stock + c.expiring_30 + c.expired;

    const card = (label, value, unit, context, state) => `
      <article class="span-3 kpi${state ? ` kpi--${state}` : ""}">
        <h2 class="kpi__label">${esc(label)}</h2>
        <p class="kpi__value">${value}${unit ? `<span class="kpi__unit">${esc(unit)}</span>` : ""}</p>
        <p class="kpi__context">${context}</p>
      </article>`;

    $("kpis").innerHTML = [
      card("Waiting now", fmt(waiting), "", `${plural(withDoctor, "patient")} with a doctor`),
      card("Average wait today", avg == null ? "–" : fmt(avg), avg == null ? "" : "min",
           seenCount ? `${plural(seenCount, "patient")} seen` : "Nobody seen yet today"),
      card("Beds free", fmt(beds.free), `of ${fmt(beds.total)}`,
           beds.total && beds.free === 0 ? status("critical", "Hospital full") : `${pct(beds.occupied, beds.total)}% occupied`,
           beds.total && beds.free === 0 ? "critical" : null),
      card("Stock alerts", fmt(alerts), "",
           c.expired ? status("critical", `${plural(c.expired, "batch", "batches")} expired`)
             : alerts ? status("warning", "Needs action") : status("ok", "All stock is fine"),
           c.expired ? "critical" : alerts ? "warning" : null),
    ].join("");
  }

  // ---------------------------------------------------------- 2. the trend: a line chart
  // points: [{ hour, value }] up to now. Area wash + 2px line; the "now" point is the accent.
  function lineChart(el, points, { fromHour, toHour }) {
    el.innerHTML = "";
    const W = Math.max(280, el.clientWidth), H = el.clientWidth < 480 ? 200 : 240;
    const pad = { top: 24, right: 16, bottom: 28, left: 32 };
    const iw = W - pad.left - pad.right, ih = H - pad.top - pad.bottom;
    const top = niceMax(Math.max(1, ...points.map(p => p.value)));
    const x = h => pad.left + ((h - fromHour) / Math.max(1, toHour - fromHour)) * iw;
    const y = v => pad.top + ih - (v / top) * ih;

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    svg.setAttribute("role", "img");
    const busiest = points.reduce((a, b) => (b.value > a.value ? b : a), points[0] || { value: 0 });
    svg.setAttribute("aria-label", points.length
      ? `Arrivals by hour today. Busiest: ${hourLabel(busiest.hour)} with ${plural(busiest.value, "arrival")}. ` +
        points.map(p => `${hourLabel(p.hour)}: ${p.value}`).join(", ")
      : "No arrivals yet today");

    let out = "";
    for (const v of [top / 2, top]) out += `<line class="ch-grid" x1="${pad.left}" x2="${W - pad.right}" y1="${y(v)}" y2="${y(v)}"/>
      <text class="ch-tick" x="${pad.left - 8}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`;
    out += `<line class="ch-base" x1="${pad.left}" x2="${W - pad.right}" y1="${y(0)}" y2="${y(0)}"/>
            <text class="ch-tick" x="${pad.left - 8}" y="${y(0) + 4}" text-anchor="end">0</text>`;
    const step = iw / Math.max(1, toHour - fromHour) < 44 ? 3 : 2;              // hour labels that fit
    for (let h = fromHour; h <= toHour; h += step) {
      out += `<text class="ch-tick" x="${x(h)}" y="${H - 8}" text-anchor="middle">${hourLabel(h)}</text>`;
    }
    if (points.length) {
      const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.hour)},${y(p.value)}`).join(" ");
      const last = points[points.length - 1];
      // The current hour isn't over yet: its segment is dashed and labelled "so far"
      const done = points.slice(0, -1);
      const solid = done.map((p, i) => `${i ? "L" : "M"}${x(p.hour)},${y(p.value)}`).join(" ");
      const prev = done[done.length - 1];
      out += `<path class="ch-area" d="${line} L${x(last.hour)},${y(0)} L${x(points[0].hour)},${y(0)} Z"/>
              ${done.length > 1 ? `<path class="ch-line" d="${solid}"/>` : ""}
              ${prev ? `<path class="ch-line ch-line--partial" d="M${x(prev.hour)},${y(prev.value)} L${x(last.hour)},${y(last.value)}"/>` : ""}
              <circle class="ch-dot ch-dot--now" cx="${x(last.hour)}" cy="${y(last.value)}" r="5"/>
              <text class="ch-value" x="${x(last.hour) + 10}" y="${y(last.value) - 8}" text-anchor="start">${fmt(last.value)} so far</text>`;
      if (busiest !== last && busiest.value > 0) {
        out += `<circle class="ch-dot" cx="${x(busiest.hour)}" cy="${y(busiest.value)}" r="4"/>
                <text class="ch-label" x="${x(busiest.hour)}" y="${y(busiest.value) - 12}" text-anchor="middle">Busiest ${fmt(busiest.value)}</text>`;
      }
    } else {
      out += `<text class="ch-label" x="${pad.left + iw / 2}" y="${pad.top + ih / 2}" text-anchor="middle">No arrivals yet today</text>`;
    }
    // Crosshair, moved by hover or keyboard focus
    out += `<g class="ch-cross" hidden><line y1="${pad.top}" y2="${y(0)}"/><circle r="4"/></g>`;
    svg.innerHTML = out;

    const cross = svg.querySelector(".ch-cross");
    const band = iw / Math.max(1, toHour - fromHour);
    points.forEach(p => {
      const hit = document.createElementNS(NS, "rect");
      hit.setAttribute("class", "ch-hit");
      hit.setAttribute("x", x(p.hour) - band / 2);
      hit.setAttribute("y", pad.top);
      hit.setAttribute("width", band);
      hit.setAttribute("height", ih);
      hit.setAttribute("tabindex", "0");
      hit.setAttribute("aria-label", `${hourLabel(p.hour)} to ${hourLabel(p.hour + 1)}: ${plural(p.value, "arrival")}`);
      const on = () => {
        cross.hidden = false;
        cross.querySelector("line").setAttribute("x1", x(p.hour));
        cross.querySelector("line").setAttribute("x2", x(p.hour));
        cross.querySelector("circle").setAttribute("cx", x(p.hour));
        cross.querySelector("circle").setAttribute("cy", y(p.value));
        showTip(cross.querySelector("circle"), `<b>${hourLabel(p.hour)}–${hourLabel(p.hour + 1)}</b>${plural(p.value, "arrival")}`);
      };
      const off = () => { cross.hidden = true; hideTip(); };
      hit.addEventListener("mouseenter", on); hit.addEventListener("focus", on);
      hit.addEventListener("mouseleave", off); hit.addEventListener("blur", off);
      svg.appendChild(hit);
    });
    el.appendChild(svg);
  }

  // ---------------------------------------------------------- 3. comparisons: sorted bars
  // items: [{ name, value, label, max?, state?, tip }]. Sorted largest first.
  // The first (key) bar is the accent; a problem is amber/red WITH a word in its label.
  function sortedBars(el, items, { emptyText, accentFirst = true }) {
    const list = items.filter(i => i.value != null).sort((a, b) => b.value - a.value);
    const missing = items.filter(i => i.value == null);
    if (!list.length && !missing.length) { el.innerHTML = `<p class="empty-note">${esc(emptyText)}</p>`; return; }
    const scale = Math.max(1, ...list.map(i => i.max || i.value));
    el.innerHTML = `<ul class="bars">${list.map((i, n) => `
      <li class="bars__row" tabindex="0" data-n="${n}">
        <span class="bars__name">${esc(i.name)}</span>
        <span class="bars__value">${i.label}</span>
        <span class="bars__track" aria-hidden="true"><span class="bars__bar${i.state ? ` bars__bar--${i.state}` : n === 0 && accentFirst ? " bars__bar--key" : ""}"
          style="width:${i.value > 0 ? Math.max(1, (i.value / (i.max || scale)) * 100) : 0}%"></span></span>
      </li>`).join("")}
      ${missing.map(i => `<li class="bars__row bars__row--none"><span class="bars__name">${esc(i.name)}</span>
        <span class="bars__value">${i.label}</span></li>`).join("")}
    </ul>`;
    el.querySelectorAll(".bars__row[data-n]").forEach(row => {
      const i = list[Number(row.dataset.n)];
      const on = () => showTip(row.querySelector(".bars__track"), i.tip);
      row.addEventListener("mouseenter", on); row.addEventListener("focus", on);
      row.addEventListener("mouseleave", hideTip); row.addEventListener("blur", hideTip);
    });
  }

  // Columns for the 7 days (a comparison between days). Today is the accent.
  function columns(el, data) {
    el.innerHTML = "";
    const W = Math.max(260, el.clientWidth), H = 200;
    const pad = { top: 22, right: 4, bottom: 28, left: 28 };
    const iw = W - pad.left - pad.right, ih = H - pad.top - pad.bottom;
    const top = niceMax(Math.max(1, ...data.map(d => d.value)));
    const band = iw / data.length, bw = Math.min(24, band - 8);
    const y = v => pad.top + ih - (v / top) * ih;
    let out = `<line class="ch-grid" x1="${pad.left}" x2="${W - pad.right}" y1="${y(top)}" y2="${y(top)}"/>
      <text class="ch-tick" x="${pad.left - 6}" y="${y(top) + 4}" text-anchor="end">${fmt(top)}</text>
      <line class="ch-base" x1="${pad.left}" x2="${W - pad.right}" y1="${y(0)}" y2="${y(0)}"/>
      <text class="ch-tick" x="${pad.left - 6}" y="${y(0) + 4}" text-anchor="end">0</text>`;
    data.forEach((d, i) => {
      const cx = pad.left + band * i + band / 2, h = y(0) - y(d.value), bx = cx - bw / 2, r = Math.min(4, h / 2);
      if (h > 0) out += `<path class="${i === 0 ? "ch-bar ch-bar--key" : "ch-bar"}" d="M${bx},${y(0)} V${y(d.value) + r}
        Q${bx},${y(d.value)} ${bx + r},${y(d.value)} H${bx + bw - r} Q${bx + bw},${y(d.value)} ${bx + bw},${y(d.value) + r} V${y(0)} Z"/>`;
      out += `<text class="ch-value" x="${cx}" y="${y(d.value) - 6}" text-anchor="middle">${fmt(d.value)}</text>
              <text class="ch-tick${i === 0 ? " ch-tick--now" : ""}" x="${cx}" y="${H - 8}" text-anchor="middle">${esc(d.short)}</text>`;
    });
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img"
      aria-label="${esc(data.map(d => `${d.label}: ${d.value}`).join(", "))}">${out}</svg>`;
  }

  // ---------------------------------------------------------- 4. draw everything
  function hourLabel(h) { return `${String(h % 24).padStart(2, "0")}:00`; }
  const DAY = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric" });

  function drawMain(d) {
    const byHour = d.activity.arrivals_by_hour;
    const busy = byHour.filter(h => h.arrivals > 0).map(h => h.hour);
    const fromHour = Math.min(8, ...busy), toHour = Math.max(20, d.nowHour + 1, ...busy.map(h => h + 1));
    const points = byHour.filter(h => h.hour >= fromHour && h.hour <= d.nowHour).map(h => ({ hour: h.hour, value: h.arrivals }));
    lineChart($("chart-arrivals"), points, { fromHour, toHour });

    sortedBars($("chart-waits"), d.activity.waits_today.map(w => ({
      name: w.department,
      value: w.avg_wait_minutes,
      label: w.avg_wait_minutes == null ? `<span class="muted-num">No one seen</span>` : `${fmt(w.avg_wait_minutes)} min`,
      tip: `<b>${esc(w.department)}</b>${w.avg_wait_minutes == null ? "" : `${fmt(w.avg_wait_minutes)} min average · `}${plural(w.seen, "patient")} seen`,
    })), { emptyText: "No departments yet." });
  }

  function drawTabs(d) {
    // Queues: one row per department
    const est = s => fmt(s.wait_for_new_patient_minutes || 0);
    table($("queues-table"), "Every OPD queue right now",
      ["Department", "Waiting", "With a doctor", "Seen today", "New patient waits (min)"],
      d.stats.map(s => [esc(s.department.name), fmt(s.waiting), fmt(s.in_consultation), fmt(s.done_today), est(s)]),
      ["All departments", fmt(sum(d.stats.map(s => s.waiting))), fmt(sum(d.stats.map(s => s.in_consultation))),
       fmt(sum(d.stats.map(s => s.done_today))), ""]);

    // Beds: sorted bars (fullest first) + table
    const wardState = w => (w.total && w.free === 0 ? "critical" : pct(w.occupied, w.total) >= 85 ? "warning" : null);
    sortedBars($("chart-beds"), d.wards.map(w => ({
      name: w.ward, value: pct(w.occupied, w.total), max: 100, state: wardState(w),
      label: wardState(w) === "critical" ? status("critical", "Full") : `${pct(w.occupied, w.total)}%`,
      tip: `<b>${esc(w.ward)}</b>${fmt(w.occupied)} of ${fmt(w.total)} beds occupied`,
    })), { emptyText: "No wards yet.", accentFirst: false });
    table($("beds-table"), "Beds per ward", ["Ward", "Occupied", "Free", "Total"],
      d.wards.map(w => [esc(w.ward), fmt(w.occupied), fmt(w.free), fmt(w.total)]),
      ["All wards", fmt(d.overview.beds.occupied), fmt(d.overview.beds.free), fmt(d.overview.beds.total)]);

    // Bookings: columns + table
    const days = d.activity.bookings_next_7_days.map((b, i) => {
      const dt = new Date(b.date + "T00:00:00");
      return { label: i === 0 ? "Today" : DAY.format(dt), short: i === 0 ? "Today" : DAY.format(dt), value: b.bookings };
    });
    columns($("chart-bookings"), days);
    table($("bookings-table"), "Bookings per day", ["Day", "Bookings"], days.map(x => [esc(x.label), fmt(x.value)]),
      ["Next 7 days", fmt(sum(days.map(x => x.value)))]);

    // Pharmacy
    const c = d.alerts.counts;
    table($("pharmacy-table"), "Batches that need action", ["Alert", "Batches"], [
      [status(c.expired ? "critical" : "ok", "Expired"), fmt(c.expired)],
      [status(c.expiring_30 ? "warning" : "ok", "Expiring in 30 days"), fmt(c.expiring_30)],
      [status(c.low_stock ? "warning" : "ok", "Low stock"), fmt(c.low_stock)],
      ["Expiring in 31–60 days", fmt(c.expiring_60 || 0)],
      ["Expiring in 61–90 days", fmt(c.expiring_90 || 0)],
    ]);

    // Staff and fleet + call-backs
    const amb = d.overview.ambulances;
    table($("ops-table"), "Staff and ambulances", ["", "Now"], [
      ["Doctors on OPD duty", fmt(d.overview.doctors_on_duty)],
      ["Ambulances ready", fmt(amb.available)],
      ["Ambulances on a trip", fmt(amb.on_trip)],
      ["Ambulances in service", fmt(amb.maintenance)],
      ["Open ambulance requests", fmt(d.overview.open_trips)],
    ]);
    const cb = d.overview.callbacks;
    table($("calls-table"), "Call-back requests from the website", ["Status", "Requests"], [
      ["Waiting for a call", fmt(cb.pending || 0)],
      ["Calling now", fmt(cb.calling || 0)],
      ["Done", fmt(cb.done || 0)],
      [cb.failed ? status("warning", "Couldn't reach") : "Couldn't reach", fmt(cb.failed || 0)],
    ], ["All time", fmt(sum(Object.values(cb)))]);
  }

  // ---------------------------------------------------------- 5. tabs (keyboard: arrows, Home, End)
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function selectTab(tab, focus = true) {
    tabs.forEach(t => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute("aria-controls")).hidden = !on;
    });
    if (focus) tab.focus();
    draw();                                   // charts need their panel visible to measure width
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => selectTab(t, false));   // a click already focuses it
    t.addEventListener("keydown", e => {
      const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
      if (next === undefined) return;
      e.preventDefault();
      selectTab(tabs[(next + tabs.length) % tabs.length]);
    });
  });

  // ---------------------------------------------------------- 6. load + refresh
  let last = null;
  function draw() { if (last) { drawKpis(last); drawMain(last); drawTabs(last); } }

  let zone = null;
  async function hospitalZone() {
    if (zone) return zone;
    try { zone = (await api("/schedule/on-duty")).timezone || "Asia/Kolkata"; } catch { zone = "Asia/Kolkata"; }
    return zone;
  }

  async function load() {
    try {
      const [overview, activity, depts, wards, alerts] = await Promise.all([
        api("/admin/overview"), api("/admin/activity"), api("/departments"),
        api("/wards/availability"), api("/pharmacy/alerts"),
      ]);
      const stats = await Promise.all(depts.map(x => api(`/departments/${x.id}/stats`)));
      const tz = await hospitalZone();
      const nowHour = Number(new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hour12: false, timeZone: tz }).format(new Date())) % 24;
      last = { overview, activity, stats, wards, alerts, nowHour };
      draw();
      m.clearMessage($("dash-msg"));
      $("dash-updated").textContent = `Live · updated ${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
    } catch (err) {
      m.message($("dash-msg"), { type: "error", title: "Couldn't load the numbers", text: err.message });
    }
  }

  // Redraw the SVG charts when the width changes (sidebar folded, window resized)
  let resizeTimer;
  new ResizeObserver(() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(draw, 120); }).observe($("main"));

  // ---------------------------------------------------------- who may see it
  m.user.then(u => {
    const access = m.checkAccess(u, ["admin"]);
    if (access === "login") return m.goToLogin();
    if (access === "offline") return;                       // still logged in; core.js shows "Can't reach..."
    if (access === "forbidden") {
      $("main").innerHTML = `<h1>No access</h1><p class="ui-lead">The hospital overview is for admin accounts.</p>`;
      return;
    }
    load();
    setInterval(load, 15000);
  });
})();
