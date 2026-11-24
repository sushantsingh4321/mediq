# Learning mediQ, step by step

This guide assumes you know nothing yet. Read it top to bottom once, then keep
the code open next to it. Every part points to the exact file it explains.

- Part 0. Get it running (10 minutes)
- Part 1. Queuing theory, in plain language
- Part 2. The backend: Python + FastAPI
- Part 3. The frontend: HTML + CSS + JavaScript
- Part 4. How a request travels through the whole system
- Part 5. Exercises to make it yours
- Part 6. Where this goes next (city-wide module)
- Part 7. Module 1: Bed availability
- Part 8. Frontend design (the mediQ Health website)
- Part 9. Request Call Back with Twilio
- Part 10. Accounts and database (tables, password hashing, JWT, roles)
- Part 11. Module 2: Doctor schedule
- Part 12. Admin console
- Part 13. Everything in the database
- Part 14. Module 3: Ambulance dispatch

---

## Part 0. Get it running

You need Python 3.10 or newer. Check with `python --version` (on some machines `python3`).

```bash
cd mediq
python -m venv .venv                 # make an isolated box for this project's libraries
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt      # install FastAPI, uvicorn, pytest
cp .env.example .env                 # your settings file: fill in SECRET_KEY and ADMIN_PASSWORD
uvicorn backend.app.main:app --reload --reload-dir backend --reload-dir migrations
```

Now open two tabs:

- http://localhost:8000 is the app. Register a few patients, go to Doctor and press "Call next patient".
- http://localhost:8000/docs is FastAPI's free interactive API page. Click any endpoint, press "Try it out", then "Execute".

`--reload` means: whenever you save a Python file, the server restarts by itself.
`--reload-dir backend --reload-dir migrations` limits that to the server's own code, so
editing tests or docs doesn't restart it. Every restart prints

```
WARNING:  WatchFiles detected changes in 'backend/app/...py'. Reloading...
INFO:     Application startup complete.
```

That `WARNING` is normal: it only says "a file changed, restarting". A real problem
looks different: a red `Traceback` / `Error`, and the site stops loading. When you're
only using the app (not editing code), leave out the `--reload...` options.

Everything is saved in a database file, `mediq.db`, so restarting keeps your data (Part 10 and Part 13).
`.env` holds your settings and secrets (Part 10.11); log in at http://localhost:8000/login.html
with the `ADMIN_EMAIL` and `ADMIN_PASSWORD` from it.

Run the tests with `pytest`. Every test should pass (over 90 of them by now).

---

## Part 1. Queuing theory, in plain language

### 1.1 What is a queue, really?

Any queue has three ingredients:

| Ingredient | In an OPD | Symbol |
|---|---|---|
| People arriving | Patients walking in to register | **λ** (lambda) = arrivals per hour |
| Being served | A doctor consulting a patient | **μ** (mu) = patients ONE doctor sees per hour |
| Servers | Doctors working in parallel | **c** |

If a consultation takes 10 minutes on average, one doctor sees 60/10 = **6 patients per hour**, so μ = 6.

### 1.2 Why do queues form even when doctors "should" cope?

Suppose 5 patients arrive per hour and one doctor can see 6. On paper the doctor
has spare time, so why is anyone waiting? Because arrivals are **random**. Three
people might come in the same five minutes, then nobody for twenty. The doctor
can't "bank" the idle twenty minutes to use later. Randomness alone creates queues.

### 1.3 The most important number: utilization ρ (rho)

```
ρ = λ / (c × μ)      "what fraction of the doctors' time is busy"
```

- ρ = 0.5: doctors busy half the time, short waits.
- ρ = 0.8: busy 80%, waits are noticeable.
- ρ = 0.95: busy 95%, waits explode.
- ρ ≥ 1: patients arrive faster than they can be seen. The queue grows forever.

The key lesson of queuing theory: **wait time does not grow in a straight line.**
Going from 80% to 95% busy can make waits 4 to 5 times longer. Try it on the
Dashboard screen: raise "Arrivals/hr" step by step and watch "Avg wait".

### 1.4 What does "M/M/c" mean?

This is Kendall's notation, a short code for the type of queue:

- First **M**: arrivals are random ("Markovian", technically a Poisson process). A good fit for walk-in OPD patients.
- Second **M**: consultation times are random with an exponential shape (many short visits, a few long ones).
- **c**: the number of doctors.

M/M/1 is the special case with one doctor. There are other models (M/D/1 for fixed
service times, models with appointments, and so on), but M/M/c is the standard
starting point for an OPD and what most papers use.

### 1.5 The formulas (code: `backend/app/queueing.py`)

You don't need to memorise these, but you should know what each answers.

**Erlang C**: the chance that a new patient has to wait at all (every doctor busy).

```
a = λ / μ                     (how many doctors' worth of work arrives)

             a^c / c!  ×  1/(1−ρ)
P(wait) = ─────────────────────────────────────────
           Σ(k=0..c−1) a^k / k!  +  a^c / c! × 1/(1−ρ)
```

**Average waiting time in the queue:**

```
Wq = P(wait) / (c×μ − λ)
```

**Little's Law**, one of the most useful ideas in all of operations research:

```
L = λ × W      average number of people = arrival rate × average time each spends
```

So the average number waiting is `Lq = λ × Wq`. Little's Law works for almost any
queue, not just M/M/c.

**Worked example (single doctor).** λ = 4/hr, μ = 6/hr, c = 1.
ρ = 4/6 = 0.67. For one doctor the formula simplifies to Wq = ρ / (μ − λ) = 0.67 / 2 = 0.33 h = **20 minutes**.
Lq = 4 × 0.33 = 1.33 people waiting on average. The test `test_single_doctor_matches_mm1_formula` checks exactly this.

### 1.6 Two different "wait" numbers in mediQ

1. **Model average (Dashboard)**: from M/M/c. "Over a typical day, how long does a patient wait?" Good for **planning**: how many doctors to roster.
2. **Live estimate (token slip, Doctor screen)**: "6 people ahead of you, 3 doctors, ~8 minutes each, so about 16 minutes." Good for **telling a patient** what to expect right now. Code: `estimate_wait_for_position`.

Both are useful. Hospitals use the first to plan and the second to inform.

### 1.7 Queue discipline

mediQ v1 is **FCFS** (First-Come-First-Served): the oldest waiting token goes next
(`call_next` in `main.py`). Real OPDs often add priority (emergencies, elderly,
pregnant women). That is a planned next step.

---

## Part 2. The backend: Python + FastAPI

### 2.1 What is a backend?

The backend is a program running on a server that **holds the data and the rules**.
The frontend (the web page) never stores the queue itself. It asks the backend.

They talk using **HTTP**, the same language as the web, and send data as **JSON**
(text that looks like a Python dict: `{"patient_name": "Asha", "department_id": 1}`).

A backend that answers JSON requests at fixed URLs is called an **API**.

### 2.2 HTTP in 60 seconds

Every request has a **method** and a **path**:

| Method | Meaning | mediQ example |
|---|---|---|
| GET | Read something | `GET /api/departments` lists departments |
| POST | Create or do something | `POST /api/tokens` registers a patient |
| PUT | Replace/update something | `PUT /api/departments/1` changes doctors |

Every response has a **status code**: `200` OK, `201` Created, `400` bad request,
`404` not found, `422` your data had the wrong shape.

### 2.3 Why FastAPI?

- You write normal Python functions; FastAPI turns them into URLs.
- It checks incoming data for you using type hints.
- It writes the documentation page `/docs` for free.
- It is fast and widely used, so help is easy to find.

### 2.4 The files

```
backend/app/
  queueing.py   pure maths, no web code (Part 1)
  models.py     the SHAPE of data (Pydantic models)
  store.py      where queue data is kept (the database since Part 13)
  main.py       the FastAPI app and all endpoints
```

Keeping these apart is a habit worth learning early: you can test the maths
without a server, and swap the storage for a database without touching endpoints.

### 2.5 Your first endpoint, line by line (`main.py`)

```python
app = FastAPI(title="mediQ")          # create the application

@app.get("/api/departments")           # "when someone GETs this URL..."
def list_departments():                # "...run this function..."
    return list(store.departments.values())   # "...and send this back as JSON"
```

The line starting with `@` is a **decorator**: it registers the function under that URL.

### 2.6 Receiving data: Pydantic models (`models.py`)

```python
class TokenCreate(BaseModel):
    patient_name: str = Field(..., min_length=1)
    department_id: int
```

```python
@app.post("/api/tokens", status_code=201)
def register_patient(data: TokenCreate):
    ...
```

Because the parameter is typed `TokenCreate`, FastAPI will:
1. read the JSON body,
2. check `patient_name` is a non-empty string and `department_id` is a whole number,
3. reply `422` with a helpful message if not, without your function ever running.

Try it in `/docs`: send `"department_id": "abc"` and see the error.

### 2.7 Path and query parameters

```python
@app.post("/api/departments/{dept_id}/call-next")
def call_next(dept_id: int, room: int):
```

- `{dept_id}` in the path becomes the `dept_id` argument: `/api/departments/1/call-next`.
- `room` is not in the path, so FastAPI reads it from the **query string**: `...?room=2`.

### 2.8 Errors

```python
raise HTTPException(status_code=404, detail="Department 9 not found")
```

This stops the function and sends that status and message to the caller.

### 2.9 Serving the frontend

The last lines of `main.py` mount the `frontend/` folder, so one command runs
both. This avoids a second server and avoids "CORS" errors (a browser safety rule
about pages calling a different server), which trips up a lot of beginners.

### 2.10 Tests (`tests/test_mediq.py`)

`TestClient` pretends to be a browser and calls your API without starting a server.
`test_full_patient_journey` registers two patients, calls next twice, and checks
the order and statuses. Run `pytest` after every change.

---

## Part 3. The frontend: HTML + CSS + JavaScript

### 3.1 Why plain HTML/JS and not React (for now)?

- **Nothing to install**: no Node.js, no build step. Save the file, refresh the browser.
- **You learn the real foundations.** React is built on exactly these pieces (HTML, the DOM, `fetch`). Learning them first makes React far easier later.
- The app is small (4 screens). React pays off when you have many interacting components. When mediQ grows (city-wide map, logins), moving to **React + Vite** is a sensible step, and the backend won't change at all.

### 3.2 The three languages

| File | Language | Job |
|---|---|---|
| `index.html` | HTML | **Structure**: what is on the page (forms, tables, buttons) |
| `style.css` | CSS | **Looks**: colours, spacing, layout |
| `app.js` | JavaScript | **Behaviour**: react to clicks, talk to the backend, update the page |

### 3.3 HTML: one page, four screens

`index.html` has four `<section class="screen">` blocks. Only the one with class
`active` is visible (see `.screen.active` in `style.css`). Clicking a nav button
moves the `active` class. That's all "switching screens" is.

### 3.4 JavaScript: the one function that matters

```js
async function api(path, options = {}) {
  const res = await fetch(API + path, { headers: {...}, ...options });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail);
  return data;
}
```

- `fetch` sends an HTTP request to the backend (Part 2.2).
- `await` means "wait for the answer before continuing". Functions that use it are marked `async`.
- If the status is not OK, we throw an error with FastAPI's message.

### 3.5 Following one click: "Give token"

1. The form fires a `submit` event. `e.preventDefault()` stops the browser reloading the page.
2. `FormData` reads the name and department from the inputs.
3. `api("/tokens", {method: "POST", body: JSON.stringify(...)})` sends it to `register_patient` in `main.py`.
4. The backend answers with the token (number, people ahead, estimated wait).
5. We build some HTML with that data and put it in `#token-slip` with `innerHTML`.

Every screen follows the same pattern: **read input, call API, draw result.**

### 3.6 Keeping screens live

`setInterval(refresh, 5000)` re-asks the backend every 5 seconds, so the
waiting-room board updates by itself. This is called **polling**. A later
upgrade is **WebSockets**, where the server pushes changes instantly.

### 3.7 Safety: `esc()`

Patient names are typed by people. If someone types `<script>`, putting it
straight into `innerHTML` would run it. `esc()` turns `<` into `&lt;` and so on.
Always escape user text before inserting it as HTML.

---

## Part 4. A request's full journey

```
[Reception page] --POST /api/tokens {"patient_name":"Asha","department_id":1}-->
   [FastAPI] checks data with TokenCreate (models.py)
   [register_patient] asks store.add_token  -> "GEN-006"
   [to_view] counts people ahead, calls estimate_wait_for_position (queueing.py)
<--201 {"number":"GEN-006","people_ahead":4,"estimated_wait_minutes":10.7,...}--
[Reception page] shows the token slip
```

---

## Part 5. Exercises (do them in order)

1. **Change the demo data.** In `seed_demo_data()` add a "Dermatology" department. Restart and check it appears.
2. **Feel the maths.** On the Dashboard, set General Medicine to 3 doctors, 8 min, then try 18, 20, 22 arrivals/hr. Write down Avg wait each time. Where does it explode, and why (hint: ρ)?
3. **Add a field.** Give `TokenCreate` an optional `age: int | None = None`. Show it on the Doctor screen.
4. **Add an endpoint.** `GET /api/departments/{id}/average-actual-wait` that averages `called_at − created_at` for done tokens. Compare it with the model's Wq.
5. **Write a test** for exercise 4.

---

## Part 6. Where this goes next

Planned growth, roughly in this order (we'll check scope together):

1. **Save data in a database** (SQLite with SQLModel) so a restart doesn't wipe the queue. Only `store.py` changes.
2. **Priority queue**: emergency / elderly / pregnant patients jump ahead, with a note on how that changes the maths.
3. **No-show / skip** a token, and **recall** it.
4. **Logins** for reception and doctors.
5. **City-wide module**: a separate small FastAPI service that calls `GET /api/hospital/summary` on every hospital and shows "shortest OPD wait near you". mediQ is ready for this already: each hospital copy has its own `MEDIQ_HOSPITAL_ID` and the summary contains numbers only, never patient names.
6. **Move the frontend to React + Vite** once screens multiply.

---

## Part 7. Module 1: Bed availability

**What it does:** shows how many beds are free in each ward (General, ICU,
Emergency...), lets staff admit a patient to a bed and discharge them.

### 7.1 The files

```
backend/app/routers/beds.py   models + storage + endpoints for beds (all in one file)
tests/test_beds.py            the tests
frontend/                     "Beds" screen (index.html, app.js section 5, style.css)
```

### 7.2 New idea: routers

Until now every endpoint lived in `main.py`. With four new modules that file would
get huge. FastAPI's answer is the **APIRouter**, a "mini app":

```python
router = APIRouter(prefix="/api/wards", tags=["beds"])

@router.get("")                 # becomes GET /api/wards
def list_wards(): ...
```

`main.py` then plugs it in with one line:

```python
app.include_router(beds.router)
```

Each module is now one file you can read on its own, and `/docs` shows a "beds" group.

### 7.3 How beds are stored

A ward holds a list of `Bed` objects numbered 1, 2, 3... Each bed has
`occupied`, `patient_name` and `admitted_at`. We store individual beds (not just
a "free = 5" counter) so staff can see **who** is in **which** bed. The counts
(total / occupied / free) are worked out from the list in `count()`, so they can
never get out of step with the real beds.

### 7.4 The endpoints

| Method + path | What it does |
|---|---|
| `GET /api/wards` | All wards with all beds (staff screen, includes names) |
| `GET /api/wards/availability` | Counts per ward, **no names** |
| `POST /api/wards` | Create a ward: `{"name": "ICU", "total_beds": 6}` |
| `POST /api/wards/{id}/admit` | `{"patient_name": "Asha"}` takes the lowest free bed; add `"bed_number": 3` to pick one |
| `POST /api/wards/{id}/discharge?bed=3` | Free bed 3 |

New status code: **409 Conflict** means "your request is fine, but it clashes
with the current state", e.g. admitting to a full ward or an occupied bed.

### 7.5 Privacy and the city-wide summary

`GET /api/hospital/summary` now has a `facilities` part: `{"free_beds": 31}`.
Only the number travels outside the hospital, never a name. The test
`test_availability_and_city_summary_have_counts_but_no_names` admits
"Secret Name" and checks it never appears in the summary.

### 7.6 The screen

Green squares are free beds, red are occupied. Hover a red square to see who is in
it, click it to discharge. The JavaScript uses **event delegation**: one click
listener on the whole ward area that checks *what* was clicked
(`e.target.closest(".bed.occupied")`). Because the beds are redrawn every 5
seconds, adding a listener to each bed button would be lost on every redraw.

### 7.7 Exercises

1. Add a "Paediatric" ward with 10 beds in `seed_demo_wards()`.
2. Show how long each patient has been admitted (use `admitted_at`) in the bed's tooltip.
3. Add `POST /api/wards/{id}/transfer` that moves a patient to a bed in another ward. Write a test for it.

---

## Part 8. Frontend design (the mediQ Health website)

mediQ now looks like a hospital-network website for a **fictional** brand,
"mediQ Health". Every name, address and phone number is made up (see the footer).

### 8.1 Page map

| Address | File | What it is |
|---|---|---|
| `/` | `home.html` + `home.js` | Website home: hero, service cards, live "Now serving", specialities, hospitals, enquiry form |
| `/index.html` | `index.html` + `app.js` | The OPD system you already had (Reception, Doctor, Waiting room, Dashboard, Beds) |
| `/index.html#doctor` | same | Opens the Doctor screen directly (also `#reception`, `#display`, `#dashboard`, `#beds`) |

`/` used to show `index.html`. A small route in `main.py` (`home_page`) now sends
`home.html` instead; `index.html` still works at its own address.

### 8.2 One header and footer for every page (`site.js`)

Copying the same header into every HTML file means fixing every bug several
times. Instead each page has two empty boxes:

```html
<div id="site-header"></div>  ...page...  <div id="site-footer"></div>
<script src="site.js"></script>
```

`site.js` puts the header/footer HTML into those boxes with `innerHTML`. Add a
new page later? Add the two boxes and the script tag, done.

`site.js` wraps all its code in `(function () { ... })();`. In the browser, every
plain `<script>` shares one set of global names, and both `site.js` and `app.js`
want a function called `api`. The wrapper keeps `site.js`'s names private so
they don't clash. What other files need, it shares on purpose: `window.mediq`.

### 8.3 Content lives in a data file, served by an API

Hospitals, emergency numbers, specialities, helplines and country codes are in
**`backend/app/data/site_content.json`**, not in the HTML:

```
site_content.json  --read by-->  GET /api/site (routers/website.py)  --fetched by-->  site.js / home.js
```

- To add a hospital, add one line to the JSON file and refresh the browser. No code change.
- Pydantic models (`SiteContent`, `Hospital`...) check the file's shape, so a typo gives a clear error.
- The same list is used everywhere: the menu, the search, the home page, the footer and the
  enquiry form's backend check ("is this a real speciality?").

### 8.4 One shared CSS file

Everything is still in `style.css`. The top half styles the OPD screens with plain
tags (`header`, `form`, `button`). The new bottom half uses **classes**
(`.site-header`, `.btn-book`, `.service-card`...). Where a plain-tag rule gets in
the way, a more specific rule wins, e.g. `form.site-search` (tag + class) beats
`form` (tag only), so the search box doesn't get the card look. This "which rule
wins" idea is called **specificity**.

Colours are **CSS variables** (`--accent`, `--danger`, `--book`...) set once in
`:root` and again inside `@media (prefers-color-scheme: dark)`, so the whole site
follows the computer's light/dark setting automatically.

### 8.5 Dropdown menus

Each dropdown is:

```html
<div class="dropdown">
  <button data-toggle aria-expanded="false">Hospitals ▾</button>
  <div class="panel">...links...</div>
</div>
```

- The CSS hides `.panel` and shows it when the dropdown has the class `open`.
- `site.js` adds or removes `open` when the button is clicked, closes the others,
  and closes everything on Escape or a click elsewhere.
- `aria-expanded` tells screen-reader users whether the menu is open.
- On big screens the menus also open on mouse hover (`.dropdown:hover > .panel`).

### 8.6 Mobile-friendly: media queries and the hamburger

```css
@media (max-width: 900px) { ...rules only for screens 900px wide or less... }
```

Under 900px:
- the main menu is hidden until the **hamburger** button (☰) adds `open` to it;
- dropdown panels stop floating and open underneath their button instead;
- the search box moves onto its own row and "Request Call Back" moves into the menu;
- the hero drawing is hidden, and card grids drop to one column by themselves
  (`grid-template-columns: repeat(auto-fit, minmax(200px, 1fr))` fits as many
  200px+ columns as there is room for).

The `<meta name="viewport" ...>` tag in each page's `<head>` is what makes phones
use their real width instead of pretending to be a desktop.

### 8.7 The quick enquiry form: three layers of checking

1. **Browser**: `required` on inputs and on the consent checkbox stops an empty submit.
2. **JavaScript** (`home.js`): removes spaces from the mobile number (`98765 43210` → `9876543210`).
3. **Backend** (`routers/website.py`), the one that really counts, because anyone can
   call an API without your page:
   - Pydantic: mobile must be 6–15 digits (otherwise **422**).
   - Our code: consent must be ticked, country code and speciality must exist in the
     data file, the name can't be blank (otherwise **400**).

Saved enquiries are listed at `GET /api/enquiries` for staff. They contain names
and phone numbers, so they are **never** added to the city-wide summary; the test
`test_enquiries_never_reach_the_city_summary` guards this.

### 8.8 Honest placeholders

Doctor Schedule, Ambulance, Inventory and My Reports aren't built yet. Their links
have `data-soon="..."`, and `site.js` shows "coming soon" instead of a broken page.
When a module is built, swap its `data-soon` link for the real page address.

Phone numbers are shown as plain text, not tap-to-call `tel:` links, because they
are fake and could belong to a real person. The Emergency menu and footer say
"In a real emergency in India, dial 112".

### 8.9 Exercises

1. Add a hospital in Gujarat to `site_content.json`. Refresh: it should appear in the menu, the home page and the search.
2. Add "Dermatology" with three conditions. Check you can now send an enquiry for it.
3. Change `--book` in `style.css` to another colour and see every "Book Appointment" button change.
4. Build a small staff page that lists `GET /api/enquiries` in a table (hint: copy the pattern of `renderDoctorQueue` in `app.js`).

---

## Part 9. Request Call Back with Twilio

**What it does:** a patient types their name and mobile number on
`/callback.html`. mediQ rings the **hospital desk** first; when someone there
picks up, Twilio rings the **patient** and joins the two calls. Staff watch the
progress on `/staff-callbacks.html`.

### 9.1 The files

```
backend/app/config.py              reads settings from .env
backend/app/services/telephony.py  the ONLY file that talks to Twilio
backend/app/routers/callback.py    the API + the webhooks Twilio calls
frontend/callback.html + .js       patient form
frontend/staff-callbacks.html + .js staff list
tests/conftest.py                  forces DRY_RUN=true for every test
tests/test_callback.py             the tests
.env.example                       which settings exist (copy to .env)
```

### 9.2 Secrets and the .env file

Twilio's auth token works like a password to your Twilio account (and your
money). It must never be in the code or on GitHub. So:

1. `cp .env.example .env` and put your real values in `.env`.
2. `.env` is in `.gitignore`, so git ignores it.
3. `config.py` uses `python-dotenv` to load `.env` into environment variables,
   and `get_settings()` reads them.

`DRY_RUN` is **on unless you write exactly `DRY_RUN=false`**. A typo or a missing
`.env` can therefore never ring a real phone.

### 9.3 A bridged call, step by step

```
Patient form --POST /api/callback--> mediQ  (status: pending -> calling)
mediQ --"ring DESK_NUMBER"--> Twilio  ------------------------> desk phone rings
desk answers;  Twilio --POST /api/callback/1/twiml--> mediQ
mediQ answers with TwiML:  <Say>Call back request from Asha</Say>
                           <Dial><Number>+919876543210</Number></Dial>
Twilio rings the patient and connects the two calls
Twilio --POST /api/callback/1/dial-status (DialCallStatus=completed)--> mediQ   (status: done)
Twilio --POST /api/callback/1/status      (CallStatus=completed)-------> mediQ   (desk call ended)
```

**TwiML** is a small XML language that tells Twilio what to do on a call. We
build it with Twilio's `VoiceResponse` class instead of typing XML by hand, so a
name like `<Asha & Co>` can't break it.

### 9.4 Webhooks, and why we check signatures

A **webhook** is the reverse of an API call: *Twilio* calls *our* server to
report something. Two consequences:

- Twilio must be able to reach your server from the internet, so `localhost`
  won't do. For testing, run `ngrok http 8000` and put the https address in
  `PUBLIC_BASE_URL`.
- Anyone on the internet could also POST "call completed" to that address. So
  Twilio signs each webhook with your auth token (`X-Twilio-Signature`) and
  `read_webhook()` refuses anything with a wrong signature (**403**).

### 9.5 Phone numbers

`normalize_indian_mobile()` accepts what people really type (`98765 43210`,
`+91 98765-43210`, `09876543210`) and stores one form: `+919876543210` (the
international "E.164" format Twilio needs). Indian mobiles have 10 digits and
start with 6, 7, 8 or 9; anything else is refused with **400**.

### 9.6 Rate limiting

One request per number every 10 minutes. A second one gets **429 Too Many
Requests** with a `Retry-After` header (seconds to wait). This stops
double-clicks and stops someone using the hospital to ring a stranger again and
again. The form also needs a ticked **consent** box: we're about to phone someone.

### 9.7 Swapping Twilio for Exotel later

Routers only call four methods: `start_bridge_call`, `bridge_twiml`,
`hangup_twiml`, `is_valid_webhook`. Write an `ExotelProvider` class with the same
four methods and return it from `get_provider()`. Exotel is common in India because
calling Indian numbers through an international provider needs extra
registration.

### 9.8 Testing without phones

`tests/conftest.py` sets `DRY_RUN=true` before the app loads. The tests then
*pretend to be Twilio* by POSTing to the webhooks themselves. One test switches to
real mode with a fake auth token, computes a correct signature the way Twilio
does, and checks that unsigned or wrongly-signed webhooks get 403.

### 9.9 Trying it for real (costs money; Twilio trial accounts can only call verified numbers)

1. Create a Twilio account, buy or get a trial number, verify your own phone.
2. `cp .env.example .env`, fill in the values, set `DRY_RUN=false`.
3. `ngrok http 8000`, put the https address in `PUBLIC_BASE_URL`, restart uvicorn.
4. Use your own phone as `DESK_NUMBER`, request a call back to a second phone you own.

### 9.10 Exercises

1. Add a "Mark done" button on the staff page for calls staff made by hand (hint: a new `POST /api/callback/{id}/done`).
2. Show "requested 3 min ago" instead of the clock time.
3. Write a test: a request made in real mode where Twilio refuses the call (hint: `monkeypatch` `TwilioProvider.start_bridge_call` to raise `TelephonyError`).

---

## Part 10. Accounts and database

**What it does:** people sign up and log in. Each account has a **role**
(patient, receptionist, doctor, admin) and the server only lets each role do
its own job. Accounts are kept in a real **database**, so they survive restarts.

### 10.1 The files

```
backend/app/config.py         settings from .env (DATABASE_URL, SECRET_KEY, ADMIN_...)
backend/app/database.py       connection to the database + run_migrations()
backend/app/db_models.py      the TABLES (users, revoked_tokens) as Python classes
backend/app/security.py       password hashing (bcrypt) + login tokens (JWT)
backend/app/deps.py           "who is logged in?" + role checks, shared by all routers
backend/app/routers/auth.py   signup, login, me, logout, admin: create staff
alembic.ini, migrations/      Alembic: versioned changes to the tables
frontend/login.html, signup.html, auth.js     the forms
frontend/site.js              stores the token, sends it, shows your name + Logout
tests/test_database.py, test_security.py, test_auth.py, test_roles.py, test_auth_pages.py
```

### 10.2 Why a database? Tables, rows and columns

Until now mediQ kept everything in Python dicts: restart the server and it's
gone. Fine for a demo queue, not for accounts. A **database** stores data on
disk and is built for many people reading and writing at once.

A database holds **tables**. A table is like a spreadsheet:

```
users
 id | full_name     | email               | phone         | hashed_password | role    | created_at
----+---------------+---------------------+---------------+-----------------+---------+-----------
  1 | mediQ Admin   | admin@mediq.example | NULL          | $2b$12$Qx0...   | admin   | 2026-11-23
  2 | Dr. Meera Rao | meera@mediq.example | +919876543210 | $2b$12$8fK...   | doctor  | 2026-11-23
```

- A **row** is one thing (one user). A **column** is one fact about it.
- `id` is the **primary key**: a number the database gives each row, never reused.
- `email` is **unique**: the database itself refuses a second row with the same
  email, even if our Python check were somehow skipped.
- `NULL` means "no value" (phone is optional).

Databases speak **SQL**. Finding a user by email is:

```sql
SELECT * FROM users WHERE email = 'meera@mediq.example';
```

You can look inside your own database with `sqlite3 mediq.db` then
`.tables`, `SELECT id, email, role FROM users;` and `.quit`.

### 10.3 SQLAlchemy: tables as Python classes

Instead of writing SQL by hand, **SQLAlchemy** lets us describe a table as a class
(`db_models.py`) and work with objects:

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    ...

# save
db.add(User(full_name="Asha", email="asha@x.example", hashed_password=...))
db.commit()
# find
user = db.scalar(select(User).where(User.email == "asha@x.example"))
```

This is called an **ORM** (Object-Relational Mapper). Two words to know:

- **Session** (`db`): one conversation with the database. Changes are only saved
  when you call `db.commit()`.
- **`get_db()`**: a FastAPI *dependency* that gives each request its own session
  and always closes it: `def me(db: Session = Depends(get_db))`.

Don't mix up the two kinds of "model": `models.py` (Pydantic) is the shape of
**JSON** in and out of the API; `db_models.py` (SQLAlchemy) is the shape of the
**tables**. `UserOut` in `routers/auth.py` turns a database `User` into JSON and
deliberately leaves out `hashed_password`.

### 10.4 Migrations: changing tables safely (Alembic)

Changing a Python class does **not** change the database. Real databases are
full of data, so you can't just delete and recreate the tables. A **migration**
is a small script that changes the tables one step at a time, and **Alembic**
keeps them in order:

```
migrations/versions/0001_create_users_table.py
migrations/versions/0002_create_revoked_tokens_table.py
```

The database remembers which step it's at (table `alembic_version`). Commands
(run in the `mediq/` folder, with the venv active):

```bash
alembic upgrade head        # apply every migration not yet applied
alembic current             # which step is this database at?
alembic history             # list all migrations
alembic downgrade -1        # undo the last one
```

**Adding a column, step by step** (for example `last_login_at` on users):

1. Add the attribute to `User` in `db_models.py`.
2. `alembic revision --autogenerate -m "add last_login_at to users"`: Alembic
   compares your classes with the database and writes the migration for you.
3. **Read the new file** in `migrations/versions/` and check it (autogenerate is
   good, not perfect).
4. Restart the app: `run_migrations()` in `database.py` applies it on start-up,
   the same as `alembic upgrade head`.

The test `test_migrations_match_the_models` fails if you change `db_models.py`
and forget step 2. SQLite can't change a column in place, so `migrations/env.py`
sets `render_as_batch=True` (Alembic copies the table instead).

### 10.5 Moving to PostgreSQL later

SQLite is one file and needs nothing installed: perfect for learning. For a real
hospital with many users at once you'd use **PostgreSQL**. Only one line in
`.env` changes (plus installing a driver: `pip install "psycopg[binary]"`):

```
DATABASE_URL=postgresql+psycopg://mediq:password@localhost:5432/mediq
```

Run the app (or `alembic upgrade head`) and the same migrations build the same tables there.

### 10.6 Passwords: hashing, never storing

**Never store passwords.** If the database is ever copied, every password would
be exposed, and people reuse passwords on other sites. We store a **hash**:

```python
hash_password("good-password-1")
# -> "$2b$12$J3x9q1lZf8R...k0uE2"   (60 characters)
```

A hash is a **one-way** scramble: easy to make, impossible to turn back. To check
a login, bcrypt hashes what the user typed the same way and compares.

| Word | Meaning |
|---|---|
| **Hashing** | One-way. You can check a password against it, never read it back. Used for passwords. |
| **Encryption** | Two-way, with a key. You CAN get the original back. Not what we want for passwords. |
| **Salt** | Random text mixed in before hashing, stored inside the hash. Two users with the same password get different hashes, so one cracked hash doesn't reveal the other. |
| **Slow on purpose** | `$2b$12$` means 2¹² rounds, about 0.2 s per check. Nothing for one login; it makes trying billions of guesses on a stolen database impractical. |

Two more details in `security.py`:

- bcrypt only reads the first **72 bytes** of a password, so longer passwords are
  refused instead of silently cut.
- `DUMMY_HASH`: if the email doesn't exist, login still runs one bcrypt check.
  Otherwise "unknown email" would answer faster than "wrong password", and the
  speed would reveal who has an account. That's also why both get the same
  message: "Incorrect email or password."

### 10.7 Login tokens: JWT

HTTP has no memory: every request arrives on its own. So after you log in, the
server gives you a **token** and the browser sends it with every request:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI3Iiwicm9sZSI...
```

A **JWT** (JSON Web Token) has three parts separated by dots:
`header.payload.signature`. The first two are just JSON written in base64.
Decoded, a mediQ token says:

```json
header:  {"alg": "HS256", "typ": "JWT"}
payload: {"sub": "7", "role": "doctor", "iat": 1795448629,
          "exp": 1795452229, "jti": "5092fb1009134138bda19596de53ca35"}
```

| Field | Meaning |
|---|---|
| `sub` | "subject": which user (id 7) |
| `iat` / `exp` | issued at / expires at, in seconds. `exp` is 60 minutes after `iat` |
| `jti` | a unique id for this one token (used by logout) |

The third part, the **signature**, is made from the first two parts plus your
`SECRET_KEY`. Change one letter of the payload (say `"role": "admin"`) and the
signature no longer matches, so the server refuses it. Only someone with
`SECRET_KEY` can make a valid token, which is why it must stay secret.

Important: the payload is **signed, not encrypted**. Anyone can read it (paste a
token into jwt.io), so never put secrets in it.

`decode_access_token()` also insists on our algorithm (`algorithms=["HS256"]`),
which blocks the old trick of sending a token marked `"alg": "none"` with no
signature. `test_security.py` tries that trick and others.

### 10.8 Logging out a token

A JWT is valid until `exp` on its own; the server can't reach into your browser
and delete it. So on logout we write the token's `jti` into the
`revoked_tokens` table, and every request checks that list
(`get_token_payload` in `deps.py`). Once a token would have expired anyway, its
row is deleted.

### 10.9 Roles: 401 vs 403

```python
@app.post("/api/departments/{dept_id}/call-next",
          dependencies=[Depends(doctor_only)])
```

`doctor_only` (in `deps.py`) runs **before** the endpoint:

1. No token, bad token, expired, logged out → **401 Unauthorized**: "we don't know who you are".
2. Known user, wrong role → **403 Forbidden**: "we know you, but you can't do this".
3. Otherwise the endpoint runs. **Admins pass every check.**

| Role | Can |
|---|---|
| patient | Website, enquiries, call backs, own account (every new sign-up) |
| receptionist | Register patients for tokens, call-back and enquiry lists, beds |
| doctor | Call next / finish, see the queue, beds |
| admin | Everything, including the dashboard and creating staff accounts |

The role is read **from the database on every request**, not from the token.
So if an admin changes someone's role, it applies on their very next click.

**The server is what really protects data.** The browser also hides screens
you can't use (`SCREEN_ROLES` in `app.js`, `data-require-roles` on a page), but
that's only for friendliness: anyone can send requests without our page.

The first admin is created on start-up from `ADMIN_EMAIL` and `ADMIN_PASSWORD`
in `.env` (`seed_first_admin` in `routers/auth.py`), only if no admin exists.
That admin then creates doctors and receptionists with `POST /api/auth/users`.

### 10.10 The browser side

```
login.html --POST /api/auth/login--> server checks password --> {access_token, user}
auth.js saves the token in localStorage and goes to your page:
    admin -> Dashboard, doctor -> Doctor, receptionist -> Reception, patient -> home
every page: site.js sends "Authorization: Bearer <token>" with each API call
            and shows "Your Name (Role) · Logout" in the top strip
server answers 401 (expired / logged out) --> forget token --> login.html?next=<this page>
```

- `?next=` brings you back where you were after logging in. `safeNext()` only
  accepts paths on this site (`/...`), never `https://other-site` or
  `//other-site`, so nobody can use a mediQ login link to send people to a fake page.
- The forms check your input first (instant messages next to each field), then
  the **server checks everything again**.
- `localStorage` can be read by any script on the page, which is why every
  name we display goes through `esc()` (Part 3.7). A stronger later upgrade is an
  `HttpOnly` cookie, which scripts can't read at all.

### 10.11 Setting it up (.env)

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste after SECRET_KEY=
```

Then in `.env` set `ADMIN_PASSWORD=` (8+ characters) and restart uvicorn. You should
see `Created the first admin account`. Log in at http://localhost:8000/login.html.
Without `SECRET_KEY` the server uses a temporary key and everyone is logged out
on every restart (it warns you).

### 10.12 How the tests work

- `tests/conftest.py` runs first and points `DATABASE_URL` at a **brand-new
  temporary file**, so tests never touch `mediq.db`. It also sets a test-only
  `SECRET_KEY` and test admin.
- `tests/helpers.py` has `admin_headers()`: logs in as that admin once and
  returns the `Authorization` header. Older tests use it, since most endpoints
  now need a login.
- `test_roles.py` creates one account per role and checks the whole table in
  10.9: 401 when logged out, 403 for the wrong role, 200 for the right one.

### 10.13 Exercises

1. **Change password:** `POST /api/auth/change-password` with the old and new
   password. Check the old one with `verify_password`, save `hash_password(new)`.
2. **Your first migration:** add `last_login_at` to `User` (10.4), set it in `login()`, show it in `/me`.
3. **Slow down guessing:** allow 5 failed logins per email per 15 minutes
   (copy the idea from the call-back rate limit in Part 9.6). Return 429.
4. **Manage staff page:** an admin-only page that lists `GET /api/auth/users` and
   has a form for `POST /api/auth/users` (use `data-require-roles="admin"`).
5. Write a test for each of the above.

---

## Part 11. Module 2: Doctor schedule

**What it does:** each doctor has weekly **OPD sessions** ("Dr. Meera Rao,
General Medicine, Room 1, Mondays 09:00–13:00"). Anyone can see the timetable and
who is on duty right now at `/schedule.html`. Admins add and remove sessions there.
And it's linked to the queue: **a doctor can only call the next patient during
their own session, in its department and room.**

### 11.1 The files

```
backend/app/db_models.py          OpdSlot: the opd_slots table
migrations/versions/0003_...py    the migration that creates it
backend/app/routers/schedule.py   the API, plus check_on_duty() used by the queue
backend/app/main.py               call_next() now calls schedule.check_on_duty()
frontend/schedule.html + .js      the timetable page
tests/test_schedule.py            the tests
```

### 11.2 The table, and a new idea: foreign keys

```
opd_slots
 id | doctor_id | department_id | weekday | start_time | end_time | room
----+-----------+---------------+---------+------------+----------+-----
  1 |         2 |             1 |       0 | 09:00      | 13:00    |    1
```

- `doctor_id` is a **foreign key**: it must be the `id` of a row in `users`. The
  database refuses a session for a doctor who doesn't exist, and
  `ondelete="CASCADE"` means deleting a doctor's account deletes their sessions
  too. (SQLite only enforces foreign keys when asked, so `database.py` switches
  them on with `PRAGMA foreign_keys=ON`.)
- `slot.doctor` is a **relationship**: SQLAlchemy fetches the `User` for you, so
  `slot.doctor.full_name` just works.
- `weekday` uses Python's numbering: 0 = Monday … 6 = Sunday.
- Two **check constraints** make the database itself refuse impossible rows
  (`weekday BETWEEN 0 AND 6`, `start_time < end_time`).
- `department_id` is a plain number, not a foreign key, because departments still
  lived in memory when this module was written. (They are in the database now, Part 13;
  making `department_id` a real foreign key is a nice exercise.)

### 11.3 The endpoints

| Method + path | Who | What |
|---|---|---|
| `GET /api/schedule` | anyone | Timetable; optional `?department_id=` / `?doctor_id=` |
| `GET /api/schedule/on-duty` | anyone | Sessions happening now, plus the hospital time |
| `GET /api/schedule/doctors` | anyone | Doctor names (never emails or phones) |
| `POST /api/schedule` | admin | Add a session |
| `DELETE /api/schedule/{id}` | admin | Remove a session (**204 No Content**: done, nothing to send back) |

Adding a session is refused when:
- the day isn't 0–6 (**422**), the end isn't after the start, the room doesn't exist in that department, or the account isn't a doctor (**400**);
- the **same doctor** already has an overlapping session, even in another room, or **another doctor** already uses that room then (**409 Conflict**).

Two sessions overlap when each starts before the other ends:
`a_start < b_end and b_start < a_end`. So 09:00–13:00 and 13:00–15:00 do **not**
overlap: a session includes its start minute but not its end minute.

### 11.4 What "now" means: time zones

Cloud servers usually run on UTC. At 09:30 in Pune it's 04:00 UTC, so using the
server's clock would put every doctor "off duty" all morning. `now_local()` asks
for the time in `HOSPITAL_TIMEZONE` (default `Asia/Kolkata`) using Python's
`zoneinfo`. The timetable page shows the hospital time it is using, so nobody has
to guess.

### 11.5 The link with the queue

```python
def call_next(dept_id, room, user = Depends(doctor_only), db = Depends(get_db)):
    ...
    if user.role == Role.DOCTOR:
        schedule.check_on_duty(db, user, dept_id, room)
```

Before, `doctor_only` sat in the decorator (`dependencies=[...]`) because we only
needed "is this a doctor?". Now we need **which** doctor, so it moved into the
parameters, where FastAPI hands us the `User`. `check_on_duty` then answers
**403** with a useful message, for example:

> You're not on OPD duty in Paediatrics right now (Monday 21:20 hospital time).
> Your next session there: Tuesday 14:00-17:00, Room 2.

Choices worth knowing:
- **Admins can always call next** (covering an emergency or a sick doctor).
- **"Finish current" is not limited**: a consultation that runs past the end of
  the session must still be closeable.

### 11.6 Testing time-based code

A test that depends on the real clock passes in the morning and fails at night.
So the tests **pin "now"** with pytest's `monkeypatch`:

```python
monkeypatch.setattr(schedule_module, "now_local",
                    lambda: datetime(2026, 11, 26, 9, 30, tzinfo=IST))   # a Thursday
```

During that test, `now_local()` returns that moment; afterwards it goes back to
normal. This is why `now_local` is its own little function: it gives tests one
place to swap.

### 11.7 Exercises

1. On the Doctor screen, show "You're on duty: General Medicine, Room 2 until 13:00"
   and pre-select that department and room (hint: `GET /api/schedule/on-duty`, match `doctor_id` to `/api/auth/me`).
2. Add `PUT /api/schedule/{id}` to edit a session (reuse the clash checks).
3. Allow "holiday" dates when a doctor is away even though their weekly session says otherwise (a new table and migration).
4. Show the number of doctors on duty on the waiting-room board.

---

## Part 12. Admin console

**What it does:** `/admin.html` is one admin-only page to see and manage
everything. Admins land here after logging in.

| Section | Shows | Uses |
|---|---|---|
| Overview | Live counts: patients waiting, beds free, doctors on duty, call-backs to handle, enquiries, accounts per role. Click a tile to jump to it. | `GET /api/admin/overview` (new, `routers/admin.py`) |
| Accounts | Every account, search and filter by role, create accounts, change a role from a dropdown | `GET` / `POST /api/auth/users`, `PATCH /api/auth/users/{id}` (new) |
| Enquiries | The home-page enquiry form, searchable | `GET /api/enquiries` |
| Call-backs | Every request with its status, search and filter | `GET /api/callback` |
| Other tools | Links to Dashboard, Doctor schedule, Beds, Waiting room, `/docs` | |

### 12.1 One endpoint that collects from every module

`overview()` asks each module for its numbers (the queue in `store.py`, beds,
doctors on duty, call-backs, enquiries) and counts accounts in the database with
one SQL query:

```sql
SELECT role, COUNT(*) FROM users GROUP BY role;
```

In SQLAlchemy: `select(User.role, func.count()).group_by(User.role)`. It returns
**counts only**: no names, so it's cheap to call every 10 seconds.

### 12.2 Changing roles safely

`PATCH` means "change part of something" (here, only the role). Three safety rules:

1. You can't remove **your own** admin role, so nobody locks every admin out by accident (**400**).
2. A doctor who still has OPD sessions can't stop being a doctor until those are
   removed on the schedule page (**409**). Otherwise the timetable would list a
   receptionist as "on duty".
3. The change applies on the person's **next click**, with no new login, because
   every request reads the role from the database (Part 10.9).

### 12.3 Searching in the browser

The page downloads each list once, then the search boxes filter it in JavaScript
(`matches()` in `admin.js`): instant, and no extra server calls. That's fine for
hundreds of rows. For tens of thousands you'd search on the server instead
(`?q=` on the API, and SQL `WHERE name LIKE ...`).

### 12.4 A time-zone bug worth remembering

We save account times in UTC, but SQLite stores them **without** a time zone. The
browser then read "15:55" as 15:55 India time: 5½ hours wrong. The fix
(`mark_as_utc` on `UserOut`) labels the time as UTC before sending it, and the
browser converts it to local time correctly. Rule of thumb: **store UTC, label
it, convert only when showing it.**

### 12.5 Exercises

1. Add a "Reset password" button for an account (a new admin endpoint that saves `hash_password(new)`).
2. Add a "Delete account" button, with a confirm box. What should happen to that doctor's sessions? (Hint: CASCADE, Part 11.2.)
3. Download the enquiries as a CSV file.

---

## Part 13. Everything in the database

**What changed:** the OPD queue, departments, beds, enquiries and call-back
requests used to live in Python dicts and lists, gone on every restart. Now they
are tables in `mediq.db`, like accounts and schedules already were.

| Data | Was | Now (table, class in `db_models.py`) |
|---|---|---|
| Departments | `store.departments` dict | `departments`, `DepartmentRow` |
| Queue tokens | `store.tokens` dict | `tokens`, `TokenRow` |
| Wards and beds | `bed_store.wards` | `wards` + `beds`, `WardRow` + `BedRow` |
| Enquiries | `website.enquiries` list | `enquiries`, `EnquiryRow` |
| Call-backs | `callback.callbacks` dict | `callback_requests`, `CallbackRow` |

All five arrived in one migration: `0004_move_queue_beds_enquiries_callbacks_...`.

### 13.1 The promise from Part 6 kept

Part 6 said "only `store.py` changes" when we add a database. That's (almost)
what happened: `store.py` kept its method names (`departments`, `tokens_in`,
`add_token`, `arrivals_since`...) but now reads and writes tables. Most of
`main.py` didn't change at all. This is why we put all storage behind one class
from the start; it's called the **repository pattern**.

Two things did change in `main.py`: "call next" and "finish" are now single store
methods (`store.call_next`, `store.finish_room`). They change several rows (finish
the old patient, call the new one) and save them **together** in one
`db.commit()`, so a crash halfway can't leave a room with two patients. That
"all or nothing" save is called a **transaction**.

### 13.2 "Row" vs Pydantic model

`DepartmentRow` is what's **saved**; `Department` (in `models.py`) is what the API
**sends**. `model_config = ConfigDict(from_attributes=True)` lets Pydantic build
one from the other: `Department.model_validate(row)`.

### 13.3 Token numbers without a counter

The old store kept a counter in memory (`GEN-` 1, 2, 3...). Now each token saves
its `seq`, and the next number is `MAX(seq) + 1` for that department. A
**unique constraint** on `(department_id, seq)` stops two receptionists getting
the same number at the same instant: the database refuses the second, and
`add_token` simply tries again.

### 13.4 Proving it: `tests/test_persistence.py`

Those tests do something through the API, then open a **brand-new** database
connection (like a server that has just restarted) and read the rows with plain
SQL. If the data had stayed in memory, the rows wouldn't be there.

Try it yourself: register a patient, stop uvicorn (Ctrl+C), start it again. The
token is still in the queue.

### 13.5 Exercises

1. Make `opd_slots.department_id` a real foreign key to `departments.id` (a new migration).
2. Token numbers keep growing forever. Restart them at 001 every morning (hint: count only today's tokens for `MAX(seq)`, and change the unique rule to include the date).
3. Add `GET /api/tokens?date=2026-11-23` for a day's history.

---

## Part 14. Module 3: Ambulance dispatch

**What it does:** staff log ambulance requests (usually from a phone call), send
an ambulance, and mark the trip done. Everyone sees the fleet live at
`/ambulance.html`. The public website and the city-wide summary only see
**how many** ambulances are available.

### 14.1 The files

```
backend/app/models.py               AmbulanceStatus, TripStatus (the allowed values)
backend/app/db_models.py            AmbulanceRow, TripRow
migrations/versions/0005_...py      creates ambulances and ambulance_trips
backend/app/routers/ambulance.py    the API
frontend/ambulance.html + .js       the dispatch page (staff only)
tests/test_ambulance.py             the tests
```

### 14.2 Two "state machines"

A **state machine** is a thing that can only be in certain states and only move
between them in certain ways. Writing them down first makes the code simple: each
endpoint checks "am I allowed to move from here?" and refuses otherwise (**409**).

```
Ambulance:   available <--> maintenance            (PATCH, only when not on a trip)
             available  --assign-->  on_trip  --complete / cancel-->  available

Trip:        requested --assign--> assigned --complete--> completed
                 \                     \
                  \---------------------\--cancel--> cancelled
```

Examples of refused moves: assigning a trip that's already assigned, sending an
ambulance that's on a trip or in maintenance, putting a busy ambulance into
maintenance, setting `on_trip` by hand (only "assign" may do that).

### 14.3 Changing two rows together

"Assign" changes the **trip** (assigned, which ambulance, when) and the
**ambulance** (on trip) in **one** `db.commit()`. Same for "complete" and
"cancel". If the server crashed between two separate saves, you could get an
ambulance marked "on trip" with no trip, and nobody would ever send it again.
One save = a **transaction** (Part 13.1).

After "complete", the ambulance's location becomes the trip's destination: it's
now wherever it dropped the patient. After "cancel", it stays where it was.

### 14.4 Who can do what

| Action | Who |
|---|---|
| See counts (`/availability`) | anyone; numbers only |
| See the fleet and trips, log and dispatch trips, update location / maintenance | receptionist, doctor, admin |
| Add an ambulance | admin |

Requests are logged by **staff**, not a public button. A public "send an
ambulance" form invites pranks that take ambulances away from real
emergencies; patients phone the ambulance helpline instead.

### 14.5 The page refreshes every 5 seconds, but not under your mouse

Several dispatchers may have the page open, so it reloads every 5 seconds. Redrawing
would close an open "which ambulance?" dropdown, so `render()` skips a refresh while
one is focused and puts back each trip's chosen ambulance after redrawing.

### 14.6 Exercises

1. Show how long each open trip has been waiting, in red after 10 minutes.
2. Add a `priority` (emergency / routine) to trips and list emergencies first (a new column and migration).
3. Instead of "first free", send the ambulance whose `location` matches the pickup area (start simple: same sector number).
4. A report: trips per day and average minutes from "requested" to "assigned".
