// Suppliers page (pharmacy-suppliers.html): list, add, edit, delete.
(async function () {
  const m = window.mediq, { esc } = m;
  const { allowed } = await PH.start({ roles: ["pharmacist"] });
  if (!allowed) return;

  const $ = id => document.getElementById(id);
  const form = $("sup-form"), msg = $("sup-msg");
  let suppliers = [];
  let editingId = null;

  async function load() {
    suppliers = await m.api("/pharmacy/suppliers");
    $("sup-rows").innerHTML = suppliers.length ? suppliers.map(s => `<tr>
        <td><strong>${esc(s.name)}</strong>${s.address ? `<small>${esc(s.address)}</small>` : ""}</td>
        <td>${esc(s.gstin || "–")}<small>${esc(s.drug_license_no || "No licence number")}</small></td>
        <td>${esc(s.phone || "–")}${s.email ? `<small>${esc(s.email)}</small>` : ""}</td>
        <td><div class="ph-actions" style="margin: 0">
          <button class="ui-button ui-button--secondary" type="button" data-edit="${s.id}">Edit</button>
          <button class="ui-button ui-button--danger" type="button" data-delete="${s.id}">Delete</button></div></td></tr>`).join("")
      : `<tr><td colspan="4"><div class="ui-empty">No suppliers yet. Add the first one with the form.</div></td></tr>`;
  }

  function startEdit(s) {
    editingId = s ? s.id : null;
    form.reset();
    for (const el of form.elements) if (el.name && s) el.value = s[el.name] ?? "";
    $("h-form").textContent = s ? `Edit ${s.name}` : "Add a supplier";
    $("s-save").textContent = s ? "Save changes" : "Add supplier";
    $("s-cancel").hidden = !s;
    m.clearMessage(msg);
    $("s-name").focus();
  }
  $("s-cancel").addEventListener("click", () => startEdit(null));

  $("sup-rows").addEventListener("click", async e => {
    const edit = e.target.closest("[data-edit]"), del = e.target.closest("[data-delete]");
    if (edit) startEdit(suppliers.find(s => s.id === Number(edit.dataset.edit)));
    if (del) {
      const s = suppliers.find(x => x.id === Number(del.dataset.delete));
      if (!confirm(`Delete ${s.name}?`)) return;
      try {
        await m.api(`/pharmacy/suppliers/${s.id}`, { method: "DELETE" });
        m.toast(`${s.name} deleted`);
        if (editingId === s.id) startEdit(null);
        load();
      } catch (err) {
        m.message(msg, { type: "error", title: `${s.name} was not deleted`, text: err.message });
      }
    }
  });

  form.addEventListener("submit", async e => {
    e.preventDefault();
    $("s-name").removeAttribute("aria-invalid");
    $("s-gstin").removeAttribute("aria-invalid");
    const d = PH.formData(form);
    if (!d.name) {
      $("s-name").setAttribute("aria-invalid", "true");
      m.message(msg, { type: "error", title: "Enter the supplier's name", text: "The name is the only required box." });
      return $("s-name").focus();
    }
    if (d.gstin && !/^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(d.gstin.toUpperCase())) {
      $("s-gstin").setAttribute("aria-invalid", "true");
      m.message(msg, { type: "error", title: "Check the GSTIN",
        text: "It has 15 characters: 2 digits, 5 letters, 4 digits, a letter, a character, Z, a character. For example 27ABCDE1234F1Z5." });
      return $("s-gstin").focus();
    }
    try {
      const saved = await m.api(editingId ? `/pharmacy/suppliers/${editingId}` : "/pharmacy/suppliers",
        { method: editingId ? "PUT" : "POST", body: JSON.stringify(d) });
      m.toast(`${saved.name} ${editingId ? "saved" : "added"}`);
      startEdit(null);
      load();
    } catch (err) {
      m.message(msg, { type: "error", title: editingId ? "Changes not saved" : "Supplier not added", text: err.message });
    }
  });

  load().catch(err => m.message(msg, { type: "error", title: "Couldn't load suppliers", text: err.message }));
})();
