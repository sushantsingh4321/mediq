// staff-callbacks.js: staff list of call-back requests (staff-callbacks.html).

const { api, esc } = window.mediq;

// "2026-11-23T20:41:05.123" -> "23 Nov, 20:41"
const fmtTime = iso => new Date(iso).toLocaleString("en-IN",
  { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

async function renderCallbacks() {
  try {
    const rows = await api("/callback");
    document.getElementById("callback-rows").innerHTML = rows.length
      ? rows.map(c => `<tr>
          <td>${c.id}</td>
          <td>${fmtTime(c.created_at)}</td>
          <td>${esc(c.name)}</td>
          <td>${esc(c.mobile)}</td>
          <td><span class="badge ${esc(c.status)}">${esc(c.status)}</span>
              ${c.dry_run ? `<span class="badge dry">dry run</span>` : ""}</td>
          <td class="muted">${esc(c.note)}</td>
        </tr>`).join("")
      : `<tr><td colspan="6" class="muted">No call-back requests yet</td></tr>`;
  } catch (err) {
    console.error(err);
  }
}

renderCallbacks();
setInterval(renderCallbacks, 5000);
