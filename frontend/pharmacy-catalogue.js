// Catalogue page (pharmacy.html): search, view batches, add / edit / hide medicines.
(async function () {
  const m = window.mediq, { esc } = m;
  const { u } = await PH.start({ roles: null });        // everyone may search
  const canEdit = m.checkAccess(u, ["pharmacist"]) === "ok";
  const canSeeBatches = m.checkAccess(u, ["pharmacist", "doctor"]) === "ok";

  const $ = id => document.getElementById(id);
  const results = $("results"), detail = $("detail"), panel = $("med-panel"), form = $("med-form");
  let editingId = null;                                  // null = adding a new medicine
  let shownId = null;                                    // medicine whose batches are open

  // ---------------------------------------------------------------- search
  async function loadCategories() {
    const cats = await m.api("/pharmacy/categories");
    const keep = $("category").value;
    $("category").innerHTML = `<option value="">All categories</option>` +
      cats.map(c => `<option value="${esc(c)}">${esc(c[0].toUpperCase() + c.slice(1))}</option>`).join("");
    $("category").value = keep;
    $("category-options").innerHTML = cats.map(c => `<option value="${esc(c)}">`).join("");
  }

  async function search() {
    const params = new URLSearchParams({ q: $("q").value.trim(), limit: 200 });
    if ($("category").value) params.set("category", $("category").value);
    if ($("in-stock").checked) params.set("in_stock_only", "true");
    m.clearMessage($("list-msg"));
    try {
      const meds = await m.api(`/pharmacy/medicines?${params}`);
      results.innerHTML = meds.map(row).join("");
      if (!meds.length) {
        results.innerHTML = `<tr><td colspan="5"><div class="ui-empty">No medicines match
          "${esc($("q").value)}". Try the generic name, or fewer letters.</div></td></tr>`;
      }
      $("count").textContent = meds.length ? `${meds.length} medicine${meds.length === 1 ? "" : "s"}` : "";
    } catch (err) {
      m.message($("list-msg"), { type: "error", title: "Couldn't load the catalogue", text: err.message });
    }
  }

  function row(x) {
    const name = esc(x.display_name);
    // Staff can open the batches; for everyone else the name is plain text
    const title = canSeeBatches
      ? `<button type="button" class="ph-linkbtn" data-id="${x.id}" aria-expanded="${x.id === shownId}">${name}</button>`
      : `<strong>${name}</strong>`;
    return `<tr ${x.id === shownId ? 'aria-selected="true"' : ""}>
      <td>${title}<small>${esc(x.generic_name)} · ${esc(x.dosage_form)} · ${esc(x.manufacturer)}</small></td>
      <td>${esc(x.category)}</td>
      <td>${PH.schedulePill(x.schedule)} ${x.storage === "cold_chain_2_8C" ? PH.coldPill() : ""}</td>
      <td class="num">${x.stock} <small>${esc(x.unit)}s</small>${PH.stockPill(x)}</td>
      <td class="num">${PH.money(x.selling_price)}<small>MRP ${PH.money(x.mrp)}</small></td>
    </tr>`;
  }

  let timer;
  $("q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 250); });
  $("category").addEventListener("change", search);
  $("in-stock").addEventListener("change", search);
  $("search-form").addEventListener("submit", e => { e.preventDefault(); search(); });

  // ---------------------------------------------------------------- batches of one medicine
  results.addEventListener("click", e => {
    const btn = e.target.closest(".ph-linkbtn");
    if (btn) showDetail(Number(btn.dataset.id));
  });

  async function showDetail(id) {
    shownId = id;
    detail.hidden = false;
    m.loading(detail, "Loading batches…");
    results.querySelectorAll(".ph-linkbtn").forEach(b => {
      const open = Number(b.dataset.id) === id;
      b.setAttribute("aria-expanded", String(open));
      if (open) b.closest("tr").setAttribute("aria-selected", "true");
      else b.closest("tr").removeAttribute("aria-selected");
    });
    const x = await m.api(`/pharmacy/medicines/${id}`);
    const live = x.batches.filter(b => b.quantity > 0);
    detail.innerHTML = `
      <h2>${esc(x.display_name)} ${esc(x.dosage_form)}</h2>
      <p class="ui-lead">${esc(x.generic_name)} · ${esc(x.manufacturer)} · ${PH.schedulePill(x.schedule)}
        · GST ${x.gst_percent}% · HSN ${esc(x.hsn_code)} · pack of ${x.pack_size}
        ${x.is_active ? "" : " · <strong>Hidden from the catalogue</strong>"}</p>
      <h3>Batches on the shelf <span class="ph-sub">Soonest expiry first: this is the order they are handed out (FEFO).</span></h3>
      ${live.length ? `<div class="ui-table-wrap"><table class="ui-table">
        <caption class="ui-sr-only">Batches of ${esc(x.display_name)}</caption>
        <thead><tr><th scope="col">Batch</th><th scope="col">Expiry</th><th scope="col" class="num">Left</th>
          <th scope="col">Rack</th><th scope="col">Supplier</th><th scope="col" class="num">Cost</th>
          <th scope="col" class="num">Selling</th><th scope="col" class="num">MRP</th></tr></thead>
        <tbody>${live.map(b => `<tr>
          <td><strong>${esc(b.batch_no)}</strong></td>
          <td>${PH.date(b.expiry_date)} ${PH.expiryPill(b.days_to_expiry)}</td>
          <td class="num">${b.quantity}</td><td>${esc(b.rack_location || "–")}</td>
          <td>${esc(b.supplier_name || "–")}</td><td class="num">${PH.money(b.purchase_price)}</td>
          <td class="num">${PH.money(b.selling_price)}</td><td class="num">${PH.money(b.mrp)}</td></tr>`).join("")}
        </tbody></table></div>`
      : `<div class="ui-empty">No stock of this medicine.</div>`}
      ${canEdit ? `<div class="ph-actions">
        <a class="ui-button ui-button--action" href="/pharmacy-stock.html?medicine=${x.id}">Receive stock</a>
        <button class="ui-button ui-button--secondary" type="button" id="edit-btn">Edit details</button>
        <button class="ui-button ui-button--danger" type="button" id="hide-btn">${x.is_active ? "Hide from catalogue" : "Show in catalogue"}</button>
      </div>` : ""}`;
    if (canEdit) {
      $("edit-btn").addEventListener("click", () => openPanel(x));
      $("hide-btn").addEventListener("click", () => toggleActive(x));
    }
    detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function toggleActive(x) {
    try {
      if (x.is_active) {
        if (!confirm(`Hide ${x.display_name} from the catalogue? Old bills and prescriptions keep it.`)) return;
        await m.api(`/pharmacy/medicines/${x.id}`, { method: "DELETE" });
        m.toast(`${x.display_name} hidden`);
      } else {
        await m.api(`/pharmacy/medicines/${x.id}`, { method: "PUT", body: JSON.stringify({ ...x, is_active: true }) });
        m.toast(`${x.display_name} is back in the catalogue`);
      }
      showDetail(x.id);
      search();
    } catch (err) {
      m.toast(err.message);
    }
  }

  // ---------------------------------------------------------------- add / edit (pharmacists)
  if (canEdit) {
    $("add-btn").hidden = false;
    $("add-btn").addEventListener("click", () => openPanel(null));
  }

  function openPanel(x) {
    editingId = x ? x.id : null;
    form.reset();
    m.clearMessage($("med-msg"));
    $("med-panel-title").textContent = x ? `Edit ${x.display_name}` : "Add a medicine";
    $("med-save").textContent = x ? "Save changes" : "Add medicine";
    if (x) {
      for (const el of form.elements) {
        if (!el.name || !(el.name in x)) continue;
        if (el.type === "checkbox") el.checked = Boolean(x[el.name]);
        else el.value = String(x[el.name]);
      }
      form.gst_percent.value = String(Number(x.gst_percent));
    }
    panel.hidden = false;
    $("f-brand").focus();
  }
  $("med-cancel").addEventListener("click", () => { panel.hidden = true; editingId = null; });

  form.addEventListener("submit", async e => {
    e.preventDefault();
    // Check the required boxes ourselves so the message says exactly what is missing
    const missing = [...form.querySelectorAll("[required]")].filter(el => !el.value.trim());
    form.querySelectorAll(".ui-input").forEach(el => el.removeAttribute("aria-invalid"));
    if (missing.length) {
      missing.forEach(el => el.setAttribute("aria-invalid", "true"));
      m.message($("med-msg"), { type: "error", title: "Some details are missing",
        text: `Fill in: ${missing.map(el => form.querySelector(`label[for="${el.id}"]`).textContent).join(", ")}.` });
      missing[0].focus();
      return;
    }
    const d = PH.formData(form);
    const body = { ...d, prescription_required: form.prescription_required.checked,
                   pack_size: Number(d.pack_size), reorder_level: Number(d.reorder_level),
                   gst_percent: Number(d.gst_percent), is_active: true };
    try {
      const saved = await m.api(editingId ? `/pharmacy/medicines/${editingId}` : "/pharmacy/medicines",
        { method: editingId ? "PUT" : "POST", body: JSON.stringify(body) });
      panel.hidden = true;
      m.toast(`${saved.display_name} ${editingId ? "saved" : "added to the catalogue"}`);
      editingId = null;
      $("q").value = saved.brand_name;
      await loadCategories();
      await search();
      showDetail(saved.id);
    } catch (err) {
      m.message($("med-msg"), { type: "error", title: editingId ? "Changes not saved" : "Medicine not added",
        text: err.message });
    }
  });

  // ---------------------------------------------------------------- start
  results.innerHTML = `<tr><td colspan="5"><div class="ui-loading" role="status">Loading the catalogue…</div></td></tr>`;
  await loadCategories().catch(() => {});
  search();
})();
