// Stock page (pharmacy-stock.html): receive a delivery, stock report, stock diary.
(async function () {
  const m = window.mediq, { esc } = m;
  const { allowed } = await PH.start({ roles: ["pharmacist"] });
  if (!allowed) return;

  const $ = id => document.getElementById(id);
  const form = $("receive-form");
  let medicine = null;                                    // the medicine picked in the search box

  // ---------------------------------------------------------------- receive stock
  const picker = PH.medicinePicker($("r-medicine"), { onPick: pick });

  function pick(med) {
    medicine = med;
    $("r-medicine").removeAttribute("aria-invalid");
    $("r-medicine-hint").textContent =
      `${med.generic_name} · ${med.stock} ${med.unit}s in stock · GST ${med.gst_percent}%`;
    $("r-unit").textContent = `(${med.unit}s)`;
    checkPrice();
  }

  // Coming from the catalogue's "Receive stock" button: ?medicine=12
  const fromUrl = new URLSearchParams(location.search).get("medicine");
  if (fromUrl) {
    try {
      const med = await m.api(`/pharmacy/medicines/${Number(fromUrl)}`);
      $("r-medicine").value = `${med.display_name} ${med.dosage_form} · ${med.generic_name}`;
      pick(med);
      $("r-batch").focus();
    } catch { /* unknown id: just leave the box empty */ }
  }

  // Sensible default dates: made today, expires in 2 years (the user changes them)
  $("r-mfg").max = PH.isoDate(new Date());

  // Live check: selling price + GST must not be above the MRP (same rule as the server)
  function checkPrice() {
    const hint = $("r-sell-hint");
    const sell = Number($("r-sell").value), mrp = Number($("r-mrp").value);
    if (!medicine || !sell) { hint.textContent = "With GST it must not be above the MRP."; return; }
    const withGst = Math.round(sell * (1 + Number(medicine.gst_percent) / 100) * 100) / 100;
    const over = mrp && withGst > mrp;
    hint.textContent = `With ${medicine.gst_percent}% GST: ${PH.money(withGst)}${over ? ` (above the MRP of ${PH.money(mrp)})` : ""}`;
    hint.className = over ? "ui-field-error" : "ui-hint";
    $("r-sell").setAttribute("aria-invalid", String(Boolean(over)));
  }
  $("r-sell").addEventListener("input", checkPrice);
  $("r-mrp").addEventListener("input", checkPrice);

  async function loadSuppliers() {
    const list = await m.api("/pharmacy/suppliers");
    $("r-supplier").innerHTML = `<option value="">Not recorded</option>` +
      list.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
  }

  form.addEventListener("submit", async e => {
    e.preventDefault();
    const msg = $("receive-msg");
    form.querySelectorAll(".ui-input").forEach(el => el.removeAttribute("aria-invalid"));
    const chosen = picker.selected || medicine;
    const missing = [...form.querySelectorAll("[required]")].filter(el => !el.value);
    if (!chosen) $("r-medicine").setAttribute("aria-invalid", "true");
    missing.forEach(el => el.setAttribute("aria-invalid", "true"));
    if (!chosen || missing.length) {
      const names = missing.map(el => form.querySelector(`label[for="${el.id}"]`).textContent.split(",")[0].trim());
      if (!chosen) names.unshift("Medicine (pick it from the suggestions)");
      m.message(msg, { type: "error", title: "Stock not received", text: `Fill in: ${names.join(", ")}.` });
      (chosen ? missing[0] : $("r-medicine")).focus();
      return;
    }
    const d = PH.formData(form);
    const body = {
      ...d, medicine_id: chosen.id, supplier_id: d.supplier_id ? Number(d.supplier_id) : null,
      quantity: Number(d.quantity), purchase_price: Number(d.purchase_price), mrp: Number(d.mrp),
      selling_price: Number(d.selling_price),
    };
    try {
      const b = await m.api("/pharmacy/stock/receive", { method: "POST", body: JSON.stringify(body) });
      m.message(msg, { type: "success", title: `Batch ${b.batch_no} received`,
        text: `${b.quantity} ${chosen.unit}s of ${chosen.display_name}, expires ${PH.date(b.expiry_date)}${b.rack_location ? `, rack ${b.rack_location}` : ""}.` });
      // Keep the medicine and supplier (deliveries often bring several batches); clear the rest
      for (const name of ["batch_no", "mfg_date", "expiry_date", "quantity", "purchase_price", "mrp", "selling_price", "rack_location"]) {
        form.elements[name].value = "";
      }
      checkPrice();
      $("r-batch").focus();
      refresh();
      PH.refreshBadge();
    } catch (err) {
      m.message(msg, { type: "error", title: "Stock not received", text: err.message });
    }
  });

  // ---------------------------------------------------------------- report and diary
  async function loadReport() {
    const r = await m.api("/pharmacy/stock/report");
    $("report-tiles").innerHTML = `
      <div class="ph-tile ph-tile--good"><strong>${PH.money(r.total_value_at_cost)}</strong><span>Stock value at cost</span></div>
      <div class="ph-tile ph-tile--good"><strong>${PH.money(r.total_value_at_selling)}</strong><span>At selling price (before GST)</span></div>
      <div class="ph-tile ${r.low_stock_count ? "ph-tile--warn" : ""}"><strong>${r.low_stock_count}</strong><span>Medicines low on stock</span></div>
      <div class="ph-tile ${r.expired_value_at_cost > 0 ? "ph-tile--bad" : ""}"><strong>${PH.money(r.expired_value_at_cost)}</strong><span>Expired, still on the shelf</span></div>`;
    $("report-rows").innerHTML = r.rows.length ? r.rows.map(x => `<tr>
        <td><strong>${esc(x.display_name)}</strong><small>${esc(x.generic_name)}</small></td>
        <td class="num">${x.in_date_units}${x.low_stock ? ` ${PH.stockPill({ stock: x.in_date_units, low_stock: true, reorder_level: x.reorder_level })}` : ""}</td>
        <td class="num">${x.expired_units || "–"}</td>
        <td>${PH.date(x.nearest_expiry)}</td>
        <td class="num">${PH.money(x.value_at_cost)}</td><td class="num">${PH.money(x.value_at_selling)}</td></tr>`).join("")
      : `<tr><td colspan="6"><div class="ui-empty">No medicines in the catalogue yet.</div></td></tr>`;
  }

  const TYPE_PILL = {
    in: ["good", "Received"], out: ["info", "Dispensed"], adjust: ["warn", "Adjusted"],
    expired: ["bad", "Expired"], returned: ["good", "Returned"],
  };
  async function loadMoves() {
    const moves = await m.api("/pharmacy/stock/movements?limit=30");
    $("moves").innerHTML = moves.length ? moves.map(x => {
      const [kind, word] = TYPE_PILL[x.type];
      return `<tr><td>${PH.dateTime(x.created_at)}</td><td>${esc(x.medicine_name)}</td>
        <td>${esc(x.batch_no || "–")}</td><td><span class="ui-pill ui-pill--${kind}">${esc(word)}</span></td>
        <td class="num">${x.quantity > 0 ? "+" : ""}${x.quantity}</td><td>${esc(x.reason)}</td>
        <td>${esc(x.user_name || "System")}</td></tr>`;
    }).join("") : `<tr><td colspan="7"><div class="ui-empty">No stock changes yet.</div></td></tr>`;
  }

  function refresh() {
    loadReport().catch(err => m.toast(`Report: ${err.message}`));
    loadMoves().catch(err => m.toast(`Stock changes: ${err.message}`));
  }

  loadSuppliers().catch(() => {});
  refresh();
})();
