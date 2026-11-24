// Dispense page (pharmacy-dispense.html): the pharmacy counter.
//   1. pick a prescription (or start a walk-in OTC sale)
//   2. see, per medicine, which batches will be used (FEFO preview)
//   3. dispense -> the server applies every rule again and returns the bill
//   4. print the bill
(async function () {
  const m = window.mediq, { esc } = m;
  const { allowed } = await PH.start({ roles: ["pharmacist"] });
  if (!allowed) return;

  const $ = id => document.getElementById(id);
  const work = $("work"), billArea = $("bill-area");
  let current = null;                  // the open prescription
  const batchCache = new Map();        // medicine_id -> medicine with batches (for the FEFO preview)

  // ---------------------------------------------------------------- the prescription list
  async function loadList() {
    const params = new URLSearchParams({ q: $("rx-q").value.trim(), open_only: $("rx-open").checked, limit: 30 });
    try {
      const list = await m.api(`/pharmacy/prescriptions?${params}`);
      $("rx-list").innerHTML = list.length ? list.map(p => `<li>
          <button type="button" data-id="${p.id}" aria-pressed="${current && current.id === p.id}">
            <strong>${esc(p.patient_name)}</strong>
            <span class="ph-sub">#${p.id} · ${esc(p.doctor_name)} · ${PH.dateTime(p.created_at)}
              ${p.token_number ? ` · ${esc(p.token_number)}` : ""}</span>
            ${p.status === "partly_dispensed" ? '<span class="ui-pill ui-pill--warn">Partly given</span>'
              : p.status === "dispensed" ? '<span class="ui-pill ui-pill--good">Done</span>' : ""}
          </button></li>`).join("")
        : `<li class="ui-empty">${$("rx-q").value ? "No prescriptions for that name." : "No prescriptions waiting."}</li>`;
    } catch (err) {
      $("rx-list").innerHTML = `<li class="ui-empty">Couldn't load prescriptions: ${esc(err.message)}</li>`;
    }
  }
  let timer;
  $("rx-q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(loadList, 250); });
  $("rx-open").addEventListener("change", loadList);
  $("rx-search").addEventListener("submit", e => { e.preventDefault(); loadList(); });
  $("rx-list").addEventListener("click", e => {
    const b = e.target.closest("button[data-id]");
    if (b) openPrescription(Number(b.dataset.id));
  });

  // ---------------------------------------------------------------- FEFO preview
  async function batchesOf(medicineId) {
    if (!batchCache.has(medicineId)) batchCache.set(medicineId, await m.api(`/pharmacy/medicines/${medicineId}`));
    return batchCache.get(medicineId);
  }

  // Same rule as the server: in-date batches with stock, soonest expiry first
  function fefo(med, quantity) {
    const usable = med.batches.filter(b => b.quantity > 0 && b.days_to_expiry > 0);
    const picks = [];
    let need = quantity;
    for (const b of usable) {
      if (need <= 0) break;
      const take = Math.min(b.quantity, need);
      picks.push({ b, take });
      need -= take;
    }
    const expiredUnits = med.batches.filter(b => b.quantity > 0 && b.days_to_expiry <= 0).reduce((s, b) => s + b.quantity, 0);
    return { picks, short: need > 0 ? need : 0, expiredUnits,
             estimate: picks.reduce((s, p) => s + p.take * p.b.selling_price * (1 + med.gst_percent / 100), 0) };
  }

  function fefoLine(med, quantity) {
    if (!quantity) return `<p class="ph-fefo">Not giving this one now.</p>`;
    const f = fefo(med, quantity);
    const used = f.picks.map(p => `<b>${esc(p.b.batch_no)}</b> × ${p.take} (exp ${PH.date(p.b.expiry_date)}${p.b.rack_location ? `, rack ${esc(p.b.rack_location)}` : ""})`).join(", ");
    if (f.short) {
      return `<p class="ph-fefo ui-field-error">Only ${quantity - f.short} in date${f.expiredUnits ? ` (${f.expiredUnits} more are expired)` : ""}.
        Give fewer, or receive new stock.${used ? ` Would use: ${used}` : ""}</p>`;
    }
    return `<p class="ph-fefo">Take from: ${used}</p>`;
  }

  // ---------------------------------------------------------------- a prescription
  async function openPrescription(id) {
    billArea.hidden = true;
    m.loading(work, "Loading the prescription…");
    batchCache.clear();                                 // fresh stock numbers every time
    current = await m.api(`/pharmacy/prescriptions/${id}`);
    $("rx-list").querySelectorAll("button[data-id]").forEach(b => b.setAttribute("aria-pressed", String(Number(b.dataset.id) === id)));
    const meds = await Promise.all(current.items.map(i => batchesOf(i.medicine_id)));

    work.innerHTML = `
      <h2>${esc(current.patient_name)} <span class="ph-sub">Prescription #${current.id}</span></h2>
      <p class="ui-lead">${esc(current.doctor_name)} · ${PH.dateTime(current.created_at)}
        ${current.token_number ? ` · token ${esc(current.token_number)}` : ""}${current.notes ? `<br>Note: ${esc(current.notes)}` : ""}</p>
      <div id="work-msg" hidden></div>
      <form class="ph-form" id="give-form">
        <div class="ui-table-wrap"><table class="ui-table">
          <caption class="ui-sr-only">Medicines on prescription #${current.id}</caption>
          <thead><tr><th scope="col">Medicine</th><th scope="col" class="num">Prescribed</th>
            <th scope="col" class="num">Given</th><th scope="col" class="num">Give now</th></tr></thead>
          <tbody>${current.items.map((it, i) => {
            const med = meds[i];
            const give = Math.min(it.remaining, med.stock);
            return `<tr>
              <td><strong>${esc(it.medicine_name)}</strong> ${PH.schedulePill(it.schedule)}
                <small>${esc(it.dose)}${it.frequency ? `, ${esc(it.frequency)}` : ""}, ${it.duration_days} days${it.instructions ? `, ${esc(it.instructions)}` : ""}</small>
                <div id="fefo-${i}">${fefoLine(med, give)}</div></td>
              <td class="num">${it.quantity}</td><td class="num">${it.dispensed}</td>
              <td class="num"><label class="ui-sr-only" for="give-${i}">Give now: ${esc(it.medicine_name)}</label>
                <input class="ui-input" id="give-${i}" type="number" min="0" max="${it.remaining}" value="${give}"
                       data-i="${i}" ${it.remaining ? "" : "disabled"}>
                <small>${it.remaining} left · ${med.stock} in stock</small></td></tr>`;
          }).join("")}</tbody></table></div>
        <dl class="ph-totals"><dt>Estimated total (incl. GST)</dt><dd class="ph-grand" id="estimate"></dd></dl>
        <div class="ph-actions">
          <button class="ui-button ui-button--action ui-button--large" type="submit" id="give-btn">Dispense and make bill</button>
        </div>
      </form>`;

    const inputs = [...work.querySelectorAll("input[data-i]")];
    const update = () => {
      let total = 0;
      inputs.forEach(inp => {
        const i = Number(inp.dataset.i), q = Math.max(0, Number(inp.value) || 0);
        $(`fefo-${i}`).innerHTML = fefoLine(meds[i], q);
        total += fefo(meds[i], q).estimate;
      });
      $("estimate").textContent = PH.money(total);
      $("give-btn").disabled = inputs.every(inp => !Number(inp.value));
    };
    inputs.forEach(inp => inp.addEventListener("input", update));
    update();

    $("give-form").addEventListener("submit", async e => {
      e.preventDefault();
      const items = inputs.map(inp => ({ medicine_id: current.items[Number(inp.dataset.i)].medicine_id,
                                         quantity: Number(inp.value) || 0 })).filter(x => x.quantity > 0);
      await dispense({ prescription_id: current.id, items }, $("work-msg"));
    });
  }

  // ---------------------------------------------------------------- walk-in OTC sale
  $("otc-btn").addEventListener("click", openOtc);

  function openOtc() {
    current = null;
    billArea.hidden = true;
    $("rx-list").querySelectorAll("button[data-id]").forEach(b => b.setAttribute("aria-pressed", "false"));
    const lines = [];                                   // [{ med, quantity }]
    work.innerHTML = `
      <h2>Walk-in sale</h2>
      <p class="ui-lead">Over-the-counter medicines only. Schedule H, H1 and X need the patient's prescription.</p>
      <div id="work-msg" hidden></div>
      <form class="ph-form" id="otc-add">
        <div class="ui-row">
          <div class="ui-field" style="flex-basis: 320px">
            <label for="otc-med">Medicine</label>
            <input class="ui-input" id="otc-med" type="search" placeholder="Type a brand or generic name">
          </div>
          <div class="ui-field" style="flex: 0 1 140px">
            <label for="otc-qty">Quantity</label>
            <input class="ui-input" id="otc-qty" type="number" min="1" value="10">
          </div>
        </div>
        <button class="ui-button ui-button--secondary" type="submit">Add to bill</button>
      </form>
      <div class="ui-table-wrap" style="margin-top: var(--s4)"><table class="ui-table">
        <caption class="ui-sr-only">Medicines on this sale</caption>
        <thead><tr><th scope="col">Medicine</th><th scope="col" class="num">Quantity</th><th scope="col"><span class="ui-sr-only">Remove</span></th></tr></thead>
        <tbody id="otc-lines"></tbody></table></div>
      <dl class="ph-totals"><dt>Estimated total (incl. GST)</dt><dd class="ph-grand" id="estimate">${PH.money(0)}</dd></dl>
      <div class="ph-actions">
        <button class="ui-button ui-button--action ui-button--large" type="button" id="otc-sell" disabled>Dispense and make bill</button>
      </div>`;
    const picker = PH.medicinePicker($("otc-med"), { inStockOnly: true });
    $("otc-med").focus();

    const draw = async () => {
      const meds = await Promise.all(lines.map(l => batchesOf(l.med.id)));
      $("otc-lines").innerHTML = lines.length ? lines.map((l, i) => `<tr>
          <td><strong>${esc(PH.medName(l.med))}</strong> ${PH.schedulePill(l.med.schedule)}${fefoLine(meds[i], l.quantity)}</td>
          <td class="num">${l.quantity}</td>
          <td><button class="ui-button ui-button--secondary" type="button" data-remove="${i}">Remove</button></td></tr>`).join("")
        : `<tr><td colspan="3"><div class="ui-empty">Nothing on this sale yet.</div></td></tr>`;
      $("estimate").textContent = PH.money(lines.reduce((s, l, i) => s + fefo(meds[i], l.quantity).estimate, 0));
      $("otc-sell").disabled = !lines.length;
    };
    draw();

    $("otc-add").addEventListener("submit", e => {
      e.preventDefault();
      const med = picker.selected, quantity = Number($("otc-qty").value);
      const msg = $("work-msg");
      if (!med) {
        m.message(msg, { type: "error", title: "Pick a medicine", text: "Type part of the name and choose it from the suggestions." });
        return $("otc-med").focus();
      }
      if (med.schedule !== "OTC" || med.prescription_required) {
        m.message(msg, { type: "error", title: `${PH.medName(med)} needs a prescription`,
          text: `It is Schedule ${med.schedule}. Find the patient's prescription on the left instead.` });
        return;
      }
      if (!(quantity >= 1)) {
        m.message(msg, { type: "error", title: "Check the quantity", text: "Enter 1 or more." });
        return $("otc-qty").focus();
      }
      m.clearMessage(msg);
      const same = lines.find(l => l.med.id === med.id);
      if (same) same.quantity += quantity; else lines.push({ med, quantity });
      picker.clear();
      $("otc-med").focus();
      draw();
    });
    $("otc-lines").addEventListener("click", e => {
      const b = e.target.closest("[data-remove]");
      if (b) { lines.splice(Number(b.dataset.remove), 1); draw(); }
    });
    $("otc-sell").addEventListener("click", () =>
      dispense({ items: lines.map(l => ({ medicine_id: l.med.id, quantity: l.quantity })) }, $("work-msg")));
  }

  // ---------------------------------------------------------------- dispense + bill
  async function dispense(body, msgEl) {
    const btn = work.querySelector(".ui-button--large");
    btn.disabled = true;
    try {
      const bill = await m.api("/pharmacy/dispense", { method: "POST", body: JSON.stringify(body) });
      showBill(bill);
      m.toast(`Bill ${bill.bill_number} made: ${PH.money(bill.total)}`);
      work.innerHTML = `<div class="ui-empty">Done. Choose the next prescription, or start a walk-in sale.</div>`;
      current = null;
      batchCache.clear();
      loadList();
      PH.refreshBadge();
    } catch (err) {
      m.message(msgEl, { type: "error", title: "Nothing was dispensed", text: err.message });
      btn.disabled = false;
    }
  }

  function showBill(b) {
    billArea.innerHTML = `
      <h2 id="h-bill">Bill ${esc(b.bill_number)}</h2>
      <p>${esc(document.getElementById("ab-hospital")?.textContent || "mediQ")} Pharmacy
        · ${PH.dateTime(b.dispensed_at)} · Dispensed by ${esc(b.dispensed_by)}<br>
        ${b.patient_name ? `Patient: <strong>${esc(b.patient_name)}</strong> · Prescription #${b.prescription_id} · ${esc(b.doctor_name)}`
                         : "Walk-in sale (over the counter)"}</p>
      <div class="ui-table-wrap"><table class="ui-table">
        <caption class="ui-sr-only">Bill lines</caption>
        <thead><tr><th scope="col">Medicine</th><th scope="col">Batch / expiry</th><th scope="col" class="num">Qty</th>
          <th scope="col" class="num">Rate</th><th scope="col" class="num">Amount</th><th scope="col" class="num">GST</th>
          <th scope="col" class="num">Total</th></tr></thead>
        <tbody>${b.lines.map(l => `<tr>
          <td>${esc(l.medicine_name)}<small>HSN ${esc(l.hsn_code)} · MRP ${PH.money(l.mrp)}</small></td>
          <td>${esc(l.batch_no)}<small>${PH.date(l.expiry_date)}</small></td>
          <td class="num">${l.quantity}</td><td class="num">${PH.money(l.price)}</td>
          <td class="num">${PH.money(l.amount)}</td>
          <td class="num">${PH.money(l.gst)}<small>${l.gst_percent}%</small></td>
          <td class="num">${PH.money(l.total)}</td></tr>`).join("")}</tbody></table></div>
      <dl class="ph-totals">
        <dt>Subtotal</dt><dd>${PH.money(b.subtotal)}</dd>
        <dt>GST</dt><dd>${PH.money(b.gst_amount)}</dd>
        <dt class="ph-grand">Total</dt><dd class="ph-grand">${PH.money(b.total)}</dd>
      </dl>
      <div class="ph-actions no-print">
        <button class="ui-button ui-button--action" type="button" id="print-btn">Print bill</button>
        <button class="ui-button ui-button--secondary" type="button" id="close-bill">Close</button>
      </div>`;
    billArea.hidden = false;
    billArea.classList.remove("ui-appear"); void billArea.offsetWidth; billArea.classList.add("ui-appear");
    billArea.scrollIntoView({ behavior: "smooth", block: "start" });
    $("print-btn").focus();
    // While a bill is open, style.css prints ONLY the bill, in black on white
    $("print-btn").addEventListener("click", () => window.print());
    $("close-bill").addEventListener("click", () => { billArea.hidden = true; });
  }

  // ---------------------------------------------------------------- start
  // Links straight to a prescription (?rx=12) or an old bill to reprint (?bill=5)
  const params = new URLSearchParams(location.search);
  if (params.get("rx")) openPrescription(Number(params.get("rx"))).catch(err =>
    m.message(work, { type: "error", title: "Prescription not found", text: err.message }));
  if (params.get("bill")) m.api(`/pharmacy/dispensations/${Number(params.get("bill"))}`).then(showBill)
    .catch(err => m.message(work, { type: "error", title: "Bill not found", text: err.message }));
  loadList();
  setInterval(() => { if (!document.hidden) loadList(); }, 15000);   // new prescriptions from doctors
})();
