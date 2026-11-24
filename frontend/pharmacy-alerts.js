// Alerts page (pharmacy-alerts.html): low stock, expiring in 30/60/90 days, expired.
(async function () {
  const m = window.mediq, { esc } = m;
  const { u, allowed } = await PH.start({ roles: ["pharmacist", "doctor"] });
  if (!allowed) return;
  const canWriteOff = m.checkAccess(u, ["pharmacist"]) === "ok";

  const $ = id => document.getElementById(id);
  let data = null;
  let view = "low";                     // which tile is chosen

  const VIEWS = {
    low:  { label: "Low on stock", tone: "warn", count: c => c.low_stock },
    e30:  { label: "Expire within 30 days", tone: "bad", count: c => c.expiring_30 },
    e60:  { label: "Expire within 60 days", tone: "warn", count: c => c.expiring_60 },
    e90:  { label: "Expire within 90 days", tone: "warn", count: c => c.expiring_90 },
    gone: { label: "Expired, still on the shelf", tone: "bad", count: c => c.expired },
  };

  async function load() {
    try {
      data = await m.api("/pharmacy/alerts");
      draw();
    } catch (err) {
      m.message($("alert-msg"), { type: "error", title: "Couldn't load alerts", text: err.message });
    }
  }

  function draw() {
    const c = data.counts;
    $("tiles").innerHTML = Object.entries(VIEWS).map(([key, v]) => {
      const n = v.count(c);
      return `<button type="button" class="ph-tile ${n ? `ph-tile--${v.tone}` : "ph-tile--good"}" data-view="${key}"
                aria-pressed="${key === view}"><strong>${n}</strong><span>${esc(v.label)}</span></button>`;
    }).join("");
    $("list-title").textContent = VIEWS[view].label;
    if (view === "low") return drawLow();
    if (view === "gone") return drawBatches(data.expired, true);
    const days = { e30: 30, e60: 60, e90: 90 }[view];
    drawBatches(data.expiring.filter(a => a.days_left <= days), false);
  }

  function drawLow() {
    $("list").innerHTML = data.low_stock.length ? `<div class="ui-table-wrap"><table class="ui-table">
      <caption class="ui-sr-only">Medicines low on stock</caption>
      <thead><tr><th scope="col">Medicine</th><th scope="col" class="num">In stock</th>
        <th scope="col" class="num">Reorder level</th><th scope="col"><span class="ui-sr-only">Action</span></th></tr></thead>
      <tbody>${data.low_stock.map(a => `<tr><td><strong>${esc(a.medicine_name)}</strong></td>
        <td class="num">${a.stock} ${PH.stockPill({ stock: a.stock, low_stock: true, reorder_level: a.reorder_level })}</td>
        <td class="num">${a.reorder_level}</td>
        <td>${canWriteOff ? `<a href="/pharmacy-stock.html?medicine=${a.medicine_id}">Receive stock</a>` : ""}</td></tr>`).join("")}
      </tbody></table></div>`
      : `<div class="ui-empty">Every medicine is above its reorder level.</div>`;
  }

  function drawBatches(list, expired) {
    const value = list.reduce((s, a) => s + a.value_at_cost, 0);
    $("list").innerHTML = list.length ? `
      <p>${list.length} batch${list.length === 1 ? "" : "es"}, worth ${PH.money(value)} at cost.
        ${expired ? "These can't be handed out. Take them off the shelf and return them to the supplier or destroy them as the rules say."
                  : "Hand these out first (the dispense screen already does), or ask the supplier about returns."}</p>
      <div class="ui-table-wrap"><table class="ui-table">
        <caption class="ui-sr-only">${expired ? "Expired batches" : "Batches expiring soon"}</caption>
        <thead><tr><th scope="col">Medicine</th><th scope="col">Batch</th><th scope="col">Expiry</th>
          <th scope="col" class="num">Units</th><th scope="col">Rack</th><th scope="col" class="num">Value at cost</th></tr></thead>
        <tbody>${list.map(a => `<tr><td><strong>${esc(a.medicine_name)}</strong></td><td>${esc(a.batch_no)}</td>
          <td>${PH.date(a.expiry_date)} ${PH.expiryPill(a.days_left)}</td><td class="num">${a.quantity}</td>
          <td>${esc(a.rack_location || "–")}</td><td class="num">${PH.money(a.value_at_cost)}</td></tr>`).join("")}
        </tbody></table></div>
      ${expired && canWriteOff ? `<div class="ph-actions">
        <button class="ui-button ui-button--danger" type="button" id="write-off">Write off all expired stock</button>
        <span class="ui-hint">Sets these batches to 0 and records each one in the stock diary.</span></div>` : ""}`
      : `<div class="ui-empty">${expired ? "No expired stock on the shelf." : "Nothing expires in this period."}</div>`;
    $("write-off")?.addEventListener("click", writeOff);
  }

  async function writeOff() {
    if (!confirm("Write off every expired batch? Their stock becomes 0. This is recorded in the stock diary.")) return;
    try {
      const removed = await m.api("/pharmacy/stock/write-off-expired", { method: "POST" });
      const units = removed.reduce((s, b) => s + b.quantity, 0);
      m.message($("alert-msg"), { type: "success", title: `${removed.length} expired batch${removed.length === 1 ? "" : "es"} written off`,
        text: `${units} units taken off the shelf.` });
      await load();
      PH.refreshBadge();
    } catch (err) {
      m.message($("alert-msg"), { type: "error", title: "Nothing was written off", text: err.message });
    }
  }

  $("tiles").addEventListener("click", e => {
    const b = e.target.closest("[data-view]");
    if (b) { view = b.dataset.view; draw(); }
  });

  // Open the most urgent list first
  m.loading($("list"), "Loading alerts…");
  await load();
  if (data) {
    const c = data.counts;
    view = c.expired ? "gone" : c.expiring_30 ? "e30" : "low";
    draw();
  }
})();
