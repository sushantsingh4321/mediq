// callback.js: the "Request a call back" form (callback.html).
// Uses api() from site.js (window.mediq). The server does all the real checks:
// valid Indian number, consent, and one request per number every 10 minutes.

const callbackForm = document.getElementById("callback-form");
const callbackMsg = document.getElementById("callback-msg");

callbackForm.addEventListener("submit", async e => {
  e.preventDefault();
  const f = new FormData(callbackForm);
  const button = callbackForm.querySelector("button");
  button.disabled = true; // stop double clicks while we wait
  try {
    const r = await window.mediq.api("/callback", {
      method: "POST",
      body: JSON.stringify({
        name: f.get("name"),
        mobile: f.get("mobile"),              // the server turns it into +91XXXXXXXXXX
        consent: f.get("consent") === "on",
      }),
    });
    callbackMsg.className = r.status === "failed" ? "warn full" : "ok full";
    callbackMsg.textContent = `${r.message} We'll call ${r.mobile} (request #${r.id}).`;
    callbackForm.reset();
  } catch (err) {
    callbackMsg.className = "warn full";
    callbackMsg.textContent = err.message; // e.g. "Please try again in 7 min."
  } finally {
    button.disabled = false;
  }
});
