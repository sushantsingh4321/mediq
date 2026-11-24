// auth.js: the login and signup forms (login.html, signup.html).
//
// 1. Check the form in the browser and show a message next to each wrong field.
// 2. Send it to the server (which checks everything again: never trust the browser).
// 3. Save the token the server returns, then go to the right page.

const { api, setToken, user, ROLE_HOME } = window.mediq;

// ---------- where to go after logging in ----------

// login.html?next=/index.html%23doctor  ->  "/index.html#doctor"
// Only paths on THIS site are allowed ("/..."), never "https://evil.example"
// or "//evil.example", so nobody can send a link that logs you in and then
// bounces you to a fake site.
function safeNext() {
  const next = new URLSearchParams(location.search).get("next");
  if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")) return next;
  return null;
}

function goOn(u) {
  location.href = safeNext() || ROLE_HOME[u.role] || "/";
}

// Already logged in? Skip the form.
user.then(u => { if (u) goOn(u); });

// ---------- showing errors ----------

function showFieldError(form, name, message) {
  const input = form.elements[name];
  const box = document.getElementById(`${name}-error`);
  if (input) input.setAttribute("aria-invalid", message ? "true" : "false");
  if (box) box.textContent = message || "";
}

function clearErrors(form) {
  form.querySelectorAll(".field-error").forEach(el => (el.textContent = ""));
  form.querySelectorAll("[aria-invalid]").forEach(el => el.setAttribute("aria-invalid", "false"));
  document.getElementById("form-error").textContent = "";
}

// Run the checks; show every problem at once; focus the first wrong field.
function validate(form, checks) {
  clearErrors(form);
  let first = null;
  for (const [name, message] of checks) {
    if (message) {
      showFieldError(form, name, message);
      first = first || form.elements[name];
    }
  }
  if (first) first.focus();
  return !first;
}

const looksLikeEmail = v => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
const digitsOnly = v => v.replace(/\D/g, "");

// Sends the form, handles errors, saves the token.
async function submit(form, path, body) {
  const button = form.querySelector("button[type=submit]");
  button.disabled = true; // no double clicks
  try {
    const r = await api(path, { method: "POST", body: JSON.stringify(body) });
    setToken(r.access_token);
    goOn(r.user);
  } catch (err) {
    // Put the server's message next to the field it's about, if we can tell.
    const msg = err.message;
    // "Incorrect email or password." is about both fields, so it goes on top.
    if (msg.startsWith("Incorrect email or password")) document.getElementById("form-error").textContent = msg;
    else if (/email/i.test(msg) && form.elements.email) showFieldError(form, "email", msg);
    else if (/password/i.test(msg) && form.elements.password) showFieldError(form, "password", msg);
    else if (/mobile/i.test(msg) && form.elements.phone) showFieldError(form, "phone", msg);
    else document.getElementById("form-error").textContent = msg;
  } finally {
    button.disabled = false;
  }
}

// ---------- login form ----------

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", e => {
    e.preventDefault();
    const email = loginForm.elements.email.value.trim();
    const password = loginForm.elements.password.value;
    const ok = validate(loginForm, [
      ["email", !email ? "Please enter your email." : !looksLikeEmail(email) ? "That doesn't look like an email address." : ""],
      ["password", !password ? "Please enter your password." : ""],
    ]);
    if (!ok) return;
    submit(loginForm, "/auth/login", { email, password });
  });
}

// ---------- signup form ----------

const signupForm = document.getElementById("signup-form");
if (signupForm) {
  signupForm.addEventListener("submit", e => {
    e.preventDefault();
    const f = signupForm.elements;
    const name = f.full_name.value.trim();
    const email = f.email.value.trim();
    const phone = f.phone.value.trim();
    const password = f.password.value;
    const ok = validate(signupForm, [
      ["full_name", !name ? "Please enter your full name." : ""],
      ["email", !email ? "Please enter your email." : !looksLikeEmail(email) ? "That doesn't look like an email address." : ""],
      ["phone", phone && !/^(91|0)?[6-9]\d{9}$/.test(digitsOnly(phone))
        ? "Please enter a 10-digit Indian mobile number, or leave it empty." : ""],
      ["password", password.length < 8 ? "Password must be at least 8 characters." : ""],
      ["confirm", f.confirm.value !== password ? "The two passwords don't match." : ""],
    ]);
    if (!ok) return;
    submit(signupForm, "/auth/signup", { full_name: name, email, phone: phone || null, password });
  });
}
