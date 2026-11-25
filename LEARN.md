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

(This was the journey when a reception desk handed out tokens. The desk was
removed in Part 17; bookings will follow the same path through `store.add_token`
and `to_view`.)

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
4. **Logins** for staff (done: Part 10).
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
| `/index.html` | `index.html` + `app.js` | The OPD system you already had (Doctor, Waiting room, Dashboard, Beds) |
| `/index.html#doctor` | same | Opens the Doctor screen directly (also `#display`, `#dashboard`, `#beds`) |

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
(patient, doctor, pharmacist, admin) and the server only lets each role do
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
| doctor | Call next / finish, see the queue, beds, ambulance dispatch, write prescriptions |
| pharmacist | The pharmacy (Part 16) |
| admin | Everything, including the dashboard, call-back and enquiry lists, and creating staff accounts |

The role is read **from the database on every request**, not from the token.
So if an admin changes someone's role, it applies on their very next click.

**The server is what really protects data.** The browser also hides screens
you can't use (`SCREEN_ROLES` in `app.js`, `data-require-roles` on a page), but
that's only for friendliness: anyone can send requests without our page.

The first admin is created on start-up from `ADMIN_EMAIL` and `ADMIN_PASSWORD`
in `.env` (`seed_first_admin` in `routers/auth.py`), only if no admin exists.
That admin then creates doctors and pharmacists with `POST /api/auth/users`.

### 10.10 The browser side

```
login.html --POST /api/auth/login--> server checks password --> {access_token, user}
auth.js saves the token in localStorage and goes to your page:
    admin -> Dashboard, doctor -> Doctor, pharmacist -> Dispense, patient -> home
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
   pharmacist as "on duty".
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
**unique constraint** on `(department_id, seq)` stops two people getting
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
| See the fleet and trips, log and dispatch trips, update location / maintenance | doctor, admin |
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

## Part 15. Everyone can look, only staff can act

Before, a patient who opened the Doctor or Beds screen saw "This screen needs a
doctor account". Now **every screen opens for everyone**, in one of two modes:

| Who | What they see | What they can press |
|---|---|---|
| Visitor or patient | Everything, but patient names as initials ("A. P.") | Nothing ("View only" note) |
| Doctor | Full names | Doctor and Beds buttons |
| Admin | Full names | Everything |

**Why initials?** A queue or bed list with full names would tell any stranger
who is in hospital. Initials keep the page useful without giving that away.

How it works:

1. **Backend, "optional login"** (`deps.py`, `get_optional_user`). Normal
   endpoints use `get_current_user`, which answers 401 if you're not logged in.
   The queue (`GET /api/departments/{id}/queue`) and beds (`GET /api/wards`) now
   use `get_optional_user` instead: it returns the user, or `None` for a visitor,
   and never refuses. Then `is_staff(user)` decides between full names and
   `initials(name)`.
2. **Backend, actions stay protected.** Issuing a token, calling the next
   patient, admitting to a bed and changing the dashboard still need the right
   role. This is the real lock: even if someone re-enables a button in the
   browser, the server still says 403.
3. **Frontend, `data-action`** (`index.html`, `app.js`). Staff-only controls carry
   a `data-action` attribute. `screenAllowed()` checks the role and sets
   `disabled` on them, then shows a "View only" note. A greyed-out button is
   clearer than a hidden one: people can see what the screen does.

Still staff-only: call-back requests and ambulance dispatch (they show phone
numbers) and the admin console.

## Part 16. Module 4: Pharmacy

**What it does:** a doctor writes a prescription on the Doctor's desk. The
pharmacist sees it on the **Dispense** screen. mediQ picks the batches, refuses
anything expired or not allowed, and prints a GST bill. The pharmacy also
receives deliveries, keeps a diary of every stock change, and warns about low
stock and expiry. Anyone can search the catalogue at `/pharmacy.html`.

### 16.1 The files

```
backend/app/models.py                   DosageForm, DrugSchedule, StorageType, MovementType...
backend/app/db_models.py                10 tables (MedicineRow ... StockMovementRow), Role.PHARMACIST
migrations/versions/0006_...py          creates the 10 pharmacy tables
migrations/versions/0007_...py          adds "pharmacist" to the allowed roles (written by hand, 16.8)
backend/app/services/pharmacy.py        THE RULES: FEFO, expiry, Schedule H, diary, bill, alerts
backend/app/services/pharmacy_seed.py   30 demo medicines, 2 suppliers, sample batches
backend/app/routers/pharmacy.py         the API (/api/pharmacy/...)
frontend/pharmacy.js                    shared page helpers (menu, pills, money, medicine search box)
frontend/pharmacy*.html + *.js          Catalogue, Dispense, Stock, Alerts, Suppliers
frontend/index.html + app.js            "Add prescription" on the Doctor's desk
tests/test_pharmacy_*.py                db, rules, api, pages, seed (5 files)
```

The rules live in `services/`, **not** in the router. A router is about the web
(URLs, JSON, logins). A service is plain Python, so the tests can call
`ph.dispense(...)` directly with a fixed "today", and the same rule is used by
every URL that needs it (receiving stock alone and receiving a purchase order).

### 16.2 How the tables fit together

```
suppliers ──< medicine_batches >── medicines        a batch = one delivery of one medicine
                     │                  │
                     │                  └──< prescription_items >── prescriptions   (doctor writes)
                     │                                                    │
                     └──< dispensation_items >── dispensations ───────────┘        (pharmacy hands out)

stock_movements: one diary line for EVERY change to a batch's quantity
purchase_orders ──< purchase_order_items: what we asked a supplier for
```
("──<" means "one ... has many ...")

Why **batches** and not just "stock: 500" on the medicine? Because each delivery
has its own **expiry date**, batch number and price. Without batches you can't
know which tablets go off first, and a recall ("batch DL2401 is faulty") is
impossible to trace.

### 16.3 The five rules

| Rule | Where | Plain words |
|---|---|---|
| **FEFO** | `pick_batches_fefo` | First Expiry, First Out: take from the batch that expires soonest. Same expiry? The older delivery first. Need 15, soonest batch has 10? Take 10 from it and 5 from the next. |
| **No expired stock** | `usable_batches` | A batch can be used only if it expires **after** today. Expiring today = already blocked. Expired stock is also refused when receiving. |
| **Schedule H / H1 / X** | `needs_prescription` | Indian Drugs & Cosmetics Rules: only OTC medicines may be sold without a prescription. With one, you can't give a medicine that isn't on it, or more than prescribed, even across several visits. |
| **Diary** | `log_movement` | Every change writes a line with a **signed** quantity: +100 received, −10 dispensed, −5 expired. Add up a batch's lines and you get what is on the shelf (a test checks this). |
| **GST bill** | `dispense`, `BillLine` | Per line: amount = price × quantity, GST = amount × GST%, rounded to the paisa. Also: selling price + GST may never be above the MRP (in India the MRP already includes tax). |

**All or nothing.** `dispense` first does **every** check and only then changes
stock. If the second medicine on a bill is short, the first isn't taken either.
Receiving a purchase order works the same way (one bad line = no batches saved).

**The bill keeps its own numbers.** A saved bill stores its totals and, per
line, the price and GST % *of that day*. If GST or prices change later, old
bills don't.

**Money is `Decimal`, not `float`.** `0.1 + 0.2` in a float is `0.30000000000000004`.
Bills must add up exactly, so prices are `Numeric(10, 2)` in the database and
`Decimal` in Python. The API sends them as plain JSON numbers for the browser.

### 16.4 Who can do what

| Who | Can |
|---|---|
| anyone (no login) | search the catalogue: name, strength, price, in stock or not (no cost prices) |
| doctor | write prescriptions; read prescriptions, batches and alerts |
| pharmacist | everything else: catalogue, suppliers, stock, dispensing, purchase orders, write-off |
| admin | everything |

The admin creates pharmacist accounts on the admin page. Pharmacists land on the
Dispense screen after logging in.

### 16.5 Alerts

`GET /api/pharmacy/alerts` returns three lists:
- **low stock**: in-date units at or below the medicine's `reorder_level` (expired units don't count; hidden medicines are skipped)
- **expiring**: batches with stock expiring within 90 days, each tagged with its window: 30, 60 or 90 (a batch expiring in exactly 30 days is in the 30 window)
- **expired**: batches past their date that still hold stock. "Write off expired stock" sets them to 0 and writes an "expired" diary line for each.

The red number on the "Alerts" menu item = low stock + expiring within 30 days + expired.

### 16.6 The screens

| Page | What to notice in the code |
|---|---|
| Catalogue | `medicine_out` adds live numbers (stock, next batch's price) to each medicine |
| Dispense | the **FEFO preview** in `pharmacy-dispense.js` repeats the server's rule so you see the batches *before* pressing the button; the server still decides |
| Stock | live "price + GST ≤ MRP" hint while you type |
| Alerts | the boxes are `<button aria-pressed>`: a filter you can use with the keyboard |
| Print | `@media print` + `body:has(#bill-area:not([hidden]))`: while a bill is open, printing shows only the bill, black on white, even in dark mode |

The medicine search box is a `<datalist>`: the browser shows suggestions and
handles the arrow keys and Enter for us.

### 16.7 The demo data

`pharmacy_seed.py` runs at start-up **only if there are no medicines**, so it
never touches a catalogue you filled in. Batches are dated **relative to today**,
so the alerts always have something to show: Mox 500 and Cetzine 10 expire
within 30 days, Shelcal within 60, Montair LC within 90, one Combiflam batch is
already expired, Galvus / Huminsulin / Asthalin are low, Addwize 10 (Schedule X)
is out of stock. Prices are examples; GST is 5%.

To start the pharmacy again from the demo data: stop the server, delete
`mediq.db` (this deletes **everything**, accounts too), start the server.

### 16.8 Lessons from building it

1. **Alembic doesn't notice a new value in an Enum.** Adding `PHARMACIST` to
   `Role` changed nothing in the database: its CHECK rule still only allowed
   four roles. Migration 0007 was written by hand.
2. **Rebuilding a table can delete other tables' rows.** SQLite changes a CHECK
   rule by copying `users` and dropping the old table. With foreign keys on,
   "drop users" counted as deleting every user, and `ON DELETE CASCADE` wiped
   their OPD sessions. `migrations/env.py` now switches foreign keys off while
   migrating and runs `PRAGMA foreign_key_check` afterwards. Found by testing
   the migration on a **copy** of the database first: always do that.
3. **`[hidden]` can lose to a class.** `.ui-button { display: inline-flex }`
   beat the `hidden` attribute, so a logged-out visitor saw "Add medicine".
   `style.css` now says `[hidden] { display: none !important; }`.

### 16.9 Try it

1. Admin page: create a **Pharmacist** and a **Doctor** account.
2. As the doctor, Doctor's desk → **Add prescription**: Mox 500, 1-0-1, 5 days (the quantity fills itself in: 10).
3. As the pharmacist, **Dispense** → pick it. The preview takes the batch expiring in ~20 days first. Dispense, then **Print bill**.
4. Try a walk-in sale of Mox 500: refused, it's Schedule H.
5. **Alerts** → "Expired, still on the shelf" → write off the Combiflam batch; see the line in **Stock → Recent stock changes**.
6. At `/docs`, try `POST /api/pharmacy/purchase-orders` (draft) → `/order` → `/receive`.

### 16.10 Exercises

1. Screens for purchase orders and stock adjustments (the APIs exist).
2. "Reorder": a button on a low-stock alert that starts a draft purchase order for that medicine.
3. A Schedule H1 register: a page listing every H1 sale with patient, doctor and quantity (the law requires it).
4. Returns: a patient brings back an unopened strip. Add it back to its batch (`adjust_stock` with `type: "returned"`) and refund on a credit note.
5. Hospital GSTIN and drug licence number on the printed bill (new settings in `.env`).


## Part 17. Goodbye reception desk: patients book for themselves

mediQ is moving from "a receptionist hands out tokens" to **patients booking
their own appointments** (the booking pages come in the next steps). Step one
was taking the reception desk out.

### 17.1 What was removed

| Removed | Was | Now |
|---|---|---|
| The **Reception** screen (`index.html#reception`, its code in `app.js`) | Type a name, pick a department, get a token | The OPD page opens on **Doctor**. "Book Appointment" says "coming soon" until booking exists |
| `POST /api/tokens` | Reception's "give token" route | Tokens now come from bookings (18.4) and from doctors adding walk-ins (18.7) |
| The **receptionist** role | `Role.RECEPTIONIST`, `reception_only` | Gone. Making an account with that role is refused (**422**) |

`GET /api/tokens/{id}` stays: it's how a patient checks their token's position and wait.

### 17.2 Who does reception's other jobs now

| Job | Before | Now |
|---|---|---|
| Call-back requests, website enquiries | receptionist | **admin** (`staff-callbacks.html` needs an admin) |
| Beds: admit / discharge | receptionist, doctor | doctor (`any_staff` now means "doctors, and admins") |
| Ambulance dispatch | receptionist, doctor | doctor |

### 17.3 Migration 0008: moving people before changing the rule

```python
op.execute("UPDATE users SET role = 'admin' WHERE role = 'receptionist'")   # 1. move the people
with op.batch_alter_table("users", recreate="always") as batch_op:          # 2. then the rule
    batch_op.alter_column("role", type_=role_type(WITHOUT_RECEPTIONIST), ...)
```

The **order matters**. If the CHECK rule changed first, every receptionist row
would break it and the migration would fail. Receptionists become **admins** so
those people keep their call-back and enquiry work. Undoing the migration allows
the role again but can't know which admins used to be receptionists, so it moves
nobody back.

Tested first on a **copy** of `mediq.db` with a pretend receptionist and an OPD
session: the receptionist became an admin and the session survived (thanks to
the foreign-key safety in `migrations/env.py`, Part 16.8).

### 17.4 Tests

Queue tests used to make tokens with `POST /api/tokens`. They now use
`queue_token(name, department_id)` in `tests/helpers.py`, which calls
`store.add_token`: the same thing bookings will do. Where a receptionist was
the "staff member who isn't allowed" in a test, a pharmacist or doctor plays
that part now. New test: the reception route and role are really gone.

## Part 18. Module 5: Patients book their own appointments

Built step by step. This part grows with each step.

### 18.1 The appointments table (migration 0009)

One row = one booked slot with one doctor: *Asha Patel with Dr. Rao, Tue 2 Dec,
10:20-10:30, "fever for 3 days"*.

| Column | Meaning |
|---|---|
| `patient_id` / `patient_name` | the patient's account, and their name. A walk-in may have no account, so `patient_id` can be empty; the name is always there |
| `doctor_id`, `department_id` | who and where |
| `date`, `slot_start`, `slot_end` | hospital-local date and times (10-minute slots by default) |
| `reason` | symptoms, in the patient's words |
| `status` | `requested`, `accepted`, `rejected`, `cancelled`, `checked_in`, `completed`, `no_show` |
| `source` | `online` (patient booked) or `walk_in` (doctor added them) |
| `priority` | higher = seen sooner among bookings at the same time |
| `token_id` | the queue token (e.g. GEN-012) made for it, once accepted |
| `reject_reason` | why the doctor said no |
| `checked_in_at` | when the patient said "I've arrived" (for the 15-minute no-show rule) |

```
requested --accept--> accepted --"I've arrived"--> checked_in --> completed
    |                    |  \--15 min after the slot, not arrived--> no_show
    |                    \--doctor rejects (with a reason)--> rejected
    \--patient cancels (up to 1 hour before)--> cancelled
```
With `auto_accept` on, a booking starts at `accepted`.

**`users.auto_accept`** (true by default) is the doctor's switch. It's a column
on `users` because doctors are users. Other roles simply ignore it. The
migration gave every existing account `true` through a **server default**: a
default the *database* fills in, which is how a new NOT NULL column gets a value
in rows that already exist.

### 18.2 Rules the database keeps by itself: partial unique indexes

A normal unique index says "no two rows may have the same values". We need
"no two **active** bookings":

```python
Index("uq_appointments_doctor_slot", "doctor_id", "date", "slot_start", unique=True,
      sqlite_where=text("status IN ('requested', 'accepted', 'checked_in')"))
```

This is a **partial index**: it only contains rows matching the WHERE, so
uniqueness is only checked among them. So:
- the same doctor + day + start time can't be booked twice (**no double booking**),
- but once a booking is cancelled or rejected it leaves the index, and the slot is free again.

A second one, `uq_appointments_patient_doctor_day`, allows **one active booking
per patient per doctor per day**. Walk-ins without an account have an empty
`patient_id`, and empty values never clash in a unique index, so several
walk-ins are fine.

Why in the database and not only in Python? Two patients pressing "Book" at the
same moment both pass a Python check ("is the slot free? yes"), then both save.
The database is the one place that sees both, so it refuses the second.

Two CHECK rules complete it: a slot must end after it starts, and a `rejected`
booking must have a `reject_reason`.

### 18.3 The patient side (step 3)

**Files:** `services/appointments.py` (the rules), `routers/appointments.py` (the
URLs), `frontend/book.html` + `book.js`, `frontend/my-appointments.html` +
`my-appointments.js`, `frontend/patient.js` (shared: app bar, menu, login
check, status pills), `tests/test_appointments_patient.py`.

| URL | Who | Does |
|---|---|---|
| `GET /api/doctors?department_id=1` | anyone | doctors with OPD sessions in that department, and their hours |
| `GET /api/doctors/{id}/slots?date=2026-11-30` | anyone | that day's slots, each `free` or not (`why_not`: "booked" / "past") |
| `POST /api/appointments` | patient | book a free slot |
| `GET /api/appointments/me` | patient | my bookings: upcoming first |
| `POST /api/appointments/{id}/cancel` | the patient who booked | cancel, up to 1 hour before |

**Where slots come from.** No slot is stored anywhere. They are **worked out**
each time from the doctor's weekly OPD sessions (Part 11): Monday 09:00-13:00
is cut into 10-minute pieces (09:00, 09:10 ... 12:50). A slot is free when no
active booking holds it and it hasn't started. Change the timetable and the
slots change with it, with nothing to keep in step.

**The rules when booking** (`book()` in the service), each with a message that says what to do:
- the date is today up to 30 days ahead; the time is a real slot of that doctor, in that department, not yet started;
- the slot is free (else **409** "someone has just booked that slot");
- you don't already have an active booking with this doctor that day (**409**);
- a reason of at least 3 characters.

The database also checks the last two (Part 18.2). If two people press "Book"
in the same instant, both pass the Python check, but the database lets only one
save. The other gets the same friendly 409 (`except IntegrityError`).

**auto_accept:** on, the booking starts as `accepted`. Off, it starts as
`requested` and the page says "Waiting for the doctor to accept".

**Cancelling** is allowed while the booking is requested or accepted, until 1
hour before the slot (exactly 1 hour before still counts). Someone else's
booking answers **404**, not 403, so nobody can probe which booking numbers exist.

**"Now" in one place.** The service asks `schedule.now_local()` for the time,
the same clock the OPD duty check uses. Tests replace that one function to
pretend it's "Monday 08:00", so they work on any day.

**The pages.** Each choice (department, doctor, day, time) is a real
`<input type="radio">` drawn as a card. So the keyboard (Tab, arrow keys,
Space) and screen readers work with no extra code. Taken or past times are
disabled radios, shown dashed. My appointments refreshes every 15 seconds and
when you come back to the tab, and shows a short note if a status changed
(for example the doctor accepted).

### 18.4 The doctor side (step 4)

**A token for every accepted booking.** The moment a booking is accepted
(automatically, or by the doctor), it gets a queue token, `GEN-012`, saved **in
the same `db.commit()`** as the booking. So there's never a booking without
its token, or a token without its booking. The patient sees it on My appointments.

**Two new token states** (migration 0010):

| Status | Means | In the live queue? |
|---|---|---|
| `booked` | made for a booking; the patient isn't here yet | **no**: "Call next" can't call someone who isn't in the building (step 5 adds "I've arrived") |
| `cancelled` | its booking was rejected or cancelled | no |

The department queue, the waiting count and the "arrivals per hour" (used by
the M/M/c maths) only count tokens that are really in the building.

**Queue order** (`QUEUE_ORDER` in `store.py`) is now: **slot time** (tokens
without a booking use the time they were made), then **priority** (higher
first), then token number. Note that token **numbers** follow booking order,
not slot order. Ravi booked second for 09:00 and got GEN-002, Asha booked
first for 09:20 and got GEN-001, but Ravi is still seen first. The number is
just a name for the token; the order comes from the slot.

**Two tokens, one number?** Token numbers are `MAX(seq) + 1`. If two bookings
are saved at the same instant they can pick the same number. The database's
unique rule refuses the second save, and `save_with_retry` builds it again
with the next number (up to 3 tries). If instead the refusal was a real rule
(the slot got taken), it says so with a 409.

| URL | Who | Does |
|---|---|---|
| `GET /api/doctor/appointments?start=&days=14&include_closed=` | doctor | my bookings, one group per date, in slot order |
| `POST /api/appointments/{id}/accept` | the booking's doctor | requested → accepted + token |
| `POST /api/appointments/{id}/reject` `{"reason": "..."}` | the booking's doctor | → rejected; token cancelled; the patient sees the reason |
| `GET` / `PATCH /api/doctor/settings` `{"auto_accept": false}` | doctor | the switch |

Another doctor gets **403** "This booking is with another doctor". The page is
`doctor-appointments.html` (linked from the Doctor's desk): the auto-accept
switch, a note when bookings need an answer, one table per day, and an inline
"reason for the patient" box when rejecting. It refreshes every 20 seconds, but
not while you're typing a reason.

**Lesson: the auto-reloading server runs a migration the moment its file
appears.** `uvicorn --reload` watches `migrations/`, and the app migrates on
start. Alembic first generated 0010 **without** the new statuses (it can't see
Enum changes). The server applied that version straight away, *before* the
hand edit. The fix: back up `mediq.db`, `alembic downgrade 0009`, then
`alembic upgrade head` with the corrected file. Next time, stop the server
while writing a hand-edited migration.

### 18.5 On the day: arrive, wait, get called (step 5)

```
booking accepted ──> token "booked"   (not in the live queue: the patient isn't here)
        │
        │  "I've arrived"  (patient: from 1 h before to 15 min after the slot;
        │                   doctor: any time that day, even after a no-show)
        ▼
checked_in ──> token "waiting"  ──Call next──>  "in_consultation" (Room 3)  ──next/finish──> "done"
                                                                                              │
                                                              booking "completed" <───────────┘
not checked in 15 minutes after the slot ──> booking "no_show", token "cancelled"
```

**Why check in at all?** Only people in the building should be called. Before,
the token sat in the queue from the moment it was made. Now "Call next" only
ever sees `waiting` tokens, and a booked token becomes `waiting` when the patient
says they've arrived.

**Expected wait** (`queue_view.py`, the old `to_view` moved out of `main.py`):
for a waiting token, the people ahead of it in queue order. For a booked one,
the people who would be ahead **if you checked in now**. Either number goes into
the same `estimate_wait_for_position` as before (Part 2). The patient's card
says "2 people ahead of you, about 7 minutes" or "You're next.", and once
called, **"It's your turn. Please go to Room 3."**

**No-shows without a timer.** mediQ has no background job that wakes up every
minute. Instead `sweep_no_shows()` runs **whenever someone looks**: My
appointments, the doctor's list, check-in, and Call next. Any accepted booking
whose check-in window closed more than a moment ago is marked `no_show` and
its token cancelled. Because Call next sweeps first, a no-show can never be
called. Same result as a timer, with nothing extra to run or keep alive.

**Completed** is set by the queue itself: when Call next or Finish marks a token
`done`, `store.complete_appointments` finds the booking with that token and
marks it `completed`, in the same save.

| URL | Who | Does |
|---|---|---|
| `POST /api/appointments/{id}/checkin` | the patient who booked, or the booking's doctor | "I've arrived": token → waiting |

Another patient or another doctor gets **404**. Booking responses now also
carry `people_ahead`, `estimated_wait_minutes`, `token_room`, `can_check_in`,
`check_in_opens_at` and `missed_after`.

### 18.6 Notifications: a banner now, SMS later (step 6)

```
something happens to a booking  ──>  notify(db, booking, "accepted")
                                        ├─ saves a NotificationRow  ──>  banner on the patient's pages
                                        └─ sms.send_sms(phone, text) ──>  STUB: one line in the server log
```

| Event | When | Banner |
|---|---|---|
| `booked` / `requested` | the patient books (auto-accepted / waiting for the doctor) | "Booked … your token is GEN-012" |
| `accepted` | the doctor accepts a request | "Booking accepted" |
| `rejected` | the doctor rejects | "Booking not accepted" + the doctor's reason |
| `called` | Call next picks them | **"It's your turn: please go to Room 1"** (phones also buzz) |
| `no_show` | not checked in 15 minutes after the slot | "Missed appointment" |

No message for what the patient just did themselves (cancel, "I've arrived").

**Saved in the same commit.** `notify()` doesn't commit; the change it describes
does. So a "rejected" message exists exactly when the booking really is rejected.

**Why a table, and not just "compare the status with last time" in the
browser?** A saved message survives a reload, works on a second phone, and
stays until the patient presses **Got it** (`read_at` is set). It's also the
one place to plug in SMS.

**The banner** is in `patient.js`, so every patient page has it. It checks
`GET /api/notifications/me` every 15 seconds and when you come back to the tab.
New ones appear at the top, and with 2 or more there's **Got it, all**. It also
fires a `mediq:notification` event, so My appointments refreshes the card at
the same moment.

**The SMS hook** (`services/sms.py`) is deliberately a stub. It logs
`SMS not sent (stub) to +91…: <text>` in the terminal and keeps the last 200 in
`OUTBOX` (the tests read it). To send real SMS later, only that one function
changes, for example using Twilio as `services/telephony.py` already does for
call-backs. Every caller stays the same.

| URL | Who | Does |
|---|---|---|
| `GET /api/notifications/me?unread_only=true` | any logged-in user | their own messages, newest first |
| `POST /api/notifications/{id}/read` | the owner | "Got it" (someone else's: **404**) |
| `POST /api/notifications/read-all` | the owner | hide all |


### 18.7 Walk-ins (step 7)

With no reception desk, someone who turns up without a booking is added by the
doctor: **Add a walk-in patient** at the top of `doctor-appointments.html`
(name, department, optional reason).

`POST /api/doctor/walk-ins` (doctor; an admin may pass `doctor_id`) creates a
booking with `source = walk_in` that is **already checked in**, because they
are standing right there, and its token goes straight into the live queue as
`waiting`. The doctor tells the patient their token number. A walk-in has no
mediQ account (`patient_id` is empty), so there are no banners for them.

**Where they go in the queue.** A walk-in's "slot" is the moment they arrived.
With the queue ordered by slot time (18.4), someone arriving at 10:23 goes
after checked-in bookings for 10:20 and before the one for 10:30. Nobody with
a booking is pushed back by people who came later.

**Two walk-ins in the same instant.** The "no double booking" index (18.2) also
covers walk-ins, so two people can't hold the exact same start time. If that
moment is taken, the walk-in's start moves 1 microsecond later: invisible to
people, unique for the database.

The doctor must have OPD sessions in the chosen department (otherwise **400**),
and patients can't add walk-ins (**403**).

This closes the gap from Part 17: patients join the queue by booking and
checking in, or as a walk-in added by the doctor.

### 18.8 Every route checked (step 8)

`tests/test_route_security.py` asks the app for **all** its routes (more than
80) and calls each one **without a login**:

- routes on the `PUBLIC` list (each with its reason: website, wait times,
  doctors and free slots, medicine search, sign-up / login, the public forms,
  Twilio's webhooks) may answer;
- **every other route must answer 401**, and must also check the **role**
  (`require_roles`), except a few that only touch your **own** data
  (`OWN_DATA`: your account, logout, your messages).

So a route added later without a login check fails this test immediately:
security by default, not by remembering.

**What the audit found:** `GET /api/tokens/{id}` showed the **full patient
name** to anyone. Token ids are just 1, 2, 3…, so a stranger could have read
every patient's name. Now visitors and other patients see initials; staff and
the token's own patient see the name. (Twilio's webhooks are public by
necessity and check Twilio's signature. In `DRY_RUN` practice mode there's no
Twilio, so no signature, which is why `DRY_RUN=false` is a must for real use.)

### 18.9 Edge cases, and a bug a test caught (step 9)

`tests/test_appointments_edge.py` fakes **two people pressing Book at the same
instant**: the second one's Python check "saw" the slot free, so only the
database's unique index (18.2) can stop it. The test found a real bug: the
refusal crashed with a 500 instead of the friendly 409. Step 6 had added
`db.flush()` inside the booking builder, so the database now said no *there*,
outside the `try` around `commit()`. `save_with_retry` now wraps both.
Lesson: a rule enforced by the database is only half done until a test makes
the database actually refuse.

### 18.10 The whole module on one page

| Who | Page | Can |
|---|---|---|
| Patient | `/book.html` | department → doctor → day → free 10-minute slot → reason → book |
| Patient | `/my-appointments.html` | status, token, cancel (until 1 h before), **I've arrived**, live wait, "It's your turn", banners |
| Doctor | `/doctor-appointments.html` | add walk-ins, own bookings by day, accept / reject with reason, check in, auto-accept on/off |
| Doctor | `/index.html#doctor` | **Call next** / Finish, as before: only checked-in patients, in slot order |

| Test file | Covers |
|---|---|
| `test_appointments_db.py` | the table's own rules (no double booking, one per patient per doctor per day) |
| `test_appointments_patient.py` | slots, booking, double booking, cancel rules |
| `test_appointments_doctor.py` | tokens, slot-time order, doctor's list, reject, manual accept, settings |
| `test_appointments_flow.py` | check-in window, live queue, expected wait, Call next → completed, no-show |
| `test_notifications.py` | one message per event, the SMS hook, Got it |
| `test_walk_ins.py` | walk-ins: checked in, queued by arrival, permissions |
| `test_route_security.py` | every route: public on purpose, or login + role |
| `test_appointments_edge.py` | the booking race, no cancel / reject after check-in |

**Try it:** as the admin, give a doctor an OPD session that covers today
(Doctor schedule). Sign up as a patient, book a slot about 30 minutes from now,
press **I've arrived**, then as the doctor press **Call next** on the Doctor's
desk. The patient's page says **"It's your turn"**.

**Exercises**
1. A real SMS: change only `services/sms.py` (Twilio is already set up for call-backs).
2. Let the doctor mark a booking **urgent** (`priority = 1`) from their list.
3. Requests nobody answered: turn `requested` bookings whose time has passed into `rejected` ("the doctor didn't answer in time") in `sweep_no_shows`.
4. A "Now serving" waiting-room screen that shows `GEN-012 → Room 3` from the live queue.

## Part 19. Going live: Vercel + Neon Postgres

Built step by step; this part grows with each step. The click-by-click guide is DEPLOY.md.

### 19.1 Safety first

`.gitignore` keeps secrets and local data off GitHub: `.env`, `*.db`, `.DS_Store`,
`__pycache__/`, and `.vercel/` (made by `vercel dev`; it links your computer to
your Vercel account). `git log --all -- .env mediq.db` showed neither was ever
committed. `tests/test_deploy_safety.py` fails if that ever changes.

### 19.2 How Vercel runs mediQ

```
browser ─┬─ /api/...  /docs ───────>  api/index.py  ──>  FastAPI app (backend/app/main.py)  ──>  Neon Postgres
         ├─ /         ───────────────>  frontend/home.html            (static file)
         └─ /book.html, /style.css ...─> frontend/...                  (static file)
```

- **Static files** (HTML, CSS, JS) are served by Vercel directly: fast and free.
- **`api/index.py`** is a *serverless function*: no always-on server. Vercel
  starts a copy of the app when a request comes in and may stop it when it's
  quiet, and it may run several copies at once.
- `vercel.json` sets this up (`routes`, `outputDirectory: frontend`).
  `includeFiles` makes sure `backend/` and `migrations/` go into the function.

### 19.3 Relative URLs

Every request in the frontend goes to `/api/...`, never `http://localhost:8000/...`.
A path starting with `/` means "this same website", so the pages work on your
Mac and on `https://….vercel.app` with no change. `tests/test_frontend_urls.py`
keeps it that way.

### 19.4 One database address, two databases

| Where | `DATABASE_URL` | Database |
|---|---|---|
| your Mac | (not set) | SQLite file `mediq.db` |
| Vercel | `postgresql://…neon.tech/neondb?sslmode=require` | Neon Postgres |

**`normalize_database_url`** (config.py) turns `postgresql://` and `postgres://`
into `postgresql+psycopg2://`. SQLAlchemy 2.1 reads a plain `postgresql://` as
the newer *psycopg 3* driver, which we don't install, so without this the very
first request on Neon would have failed. `sslmode=require` = encrypted connection.

**NullPool** (database.py): a normal server keeps a pool of open connections.
Serverless copies come and go, so leftover pooled connections would pile up on
Neon. NullPool opens a connection for each piece of work and closes it after.

**Tested on a real PostgreSQL**, a temporary one started locally:
- All 11 migrations run, undo back to nothing, and run again. All 23 tables,
  CHECK rules and partial unique indexes are there, and the database matches
  the models exactly.
- **The whole test suite passes on PostgreSQL.** To repeat it:
  `TEST_DATABASE_URL=postgresql://user:pass@localhost/empty_db pytest`.

**What was different on PostgreSQL** (and fixed):
1. Migrations 0007, 0008, 0010 rebuilt whole tables. SQLite needs that, but
   PostgreSQL refuses to drop `users` / `tokens` while other tables point at
   them. They now change the CHECK rule in place on PostgreSQL.
2. Account times came back as `+05:30` (PostgreSQL answers in *its* time zone).
   The API now always converts them to UTC.

**Nothing in memory between requests.** Each request may reach a different
copy of the app, so all data lives in the database. A scan of the code found
only constants (weekday names, message texts, seed lists) and one danger:
without `SECRET_KEY`, each copy would invent its **own** random key, and a
login made on one copy would fail on the next. So on Vercel a missing
`SECRET_KEY` now stops the app with a clear message.

### 19.5 Start-up: nothing heavy on Vercel

| When the app starts… | On your Mac | On Vercel |
|---|---|---|
| migrations (`alembic upgrade head`) | yes | **no** |
| first admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD` | yes | **no** |
| demo data (departments, wards, ambulances, 30 medicines) | yes | **no** |

Why not on Vercel? A copy of the app starts on a *cold start* (the first
request after a quiet spell), and Vercel may start several copies at the same
moment. Migrating on every start would slow those first requests down, and two
copies migrating together could get in each other's way. Instead you run it
**once** from your laptop (`scripts/setup_production.py`, step 6) whenever
there's a new migration.

`RUN_STARTUP_TASKS` in `main.py` decides. Vercel sets `VERCEL=1` for every
function, so it's off there; `MEDIQ_STARTUP_TASKS=1` or `0` overrides it.

**No background jobs.** Serverless functions don't keep running between
requests, so a "check every minute" loop can't exist there. mediQ never had one:
the no-show check runs **when appointments are loaded** (My appointments, the
doctor's list, check-in, Call next), Part 18.5. A test checks those four places.

**Call-backs stay in dry run.** `DRY_RUN` counts as "true" unless it's exactly
`false`, so a forgotten setting can never ring real phones. DEPLOY.md sets
`DRY_RUN=true` in Vercel explicitly as well.

### 19.6 Setting up the production database: `scripts/setup_production.py`

Because Vercel does no start-up work (19.5), you prepare Neon **from your
laptop**, once before the first deploy and again after any new migration:

```
.env.production  (never uploaded: .gitignore has ".env.*")
    DATABASE_URL=postgresql://…neon.tech/neondb?sslmode=require
    ADMIN_EMAIL=you@yourhospital.example
    ADMIN_PASSWORD=a-long-password-only-for-production

.venv/bin/python scripts/setup_production.py
```

It shows where it will write (host and database, **never** the password),
asks "Continue? Type yes", then:

1. **migrations:** `alembic upgrade head`, all tables up to date
2. **the first admin**, from `ADMIN_EMAIL` / `ADMIN_PASSWORD`
3. **departments:** booking needs them
4. **sample data:** 30 medicines with batches, wards, ambulances (`--no-sample-data` skips this)

Each step only adds what's missing, so running it again is safe (a test runs
it twice and checks nothing is doubled).

**Guard rails** (each has a test):
- it refuses a SQLite address: it's for the production database;
- it refuses if the **production** admin isn't named in `.env.production`. Your
  local `.env` also has an admin, and the script must never quietly copy your
  local password into production;
- no answer to "Continue?" means **no**, and nothing is touched.

Tried for real on a local PostgreSQL: empty database → version 0011, admin
`boss@prod.example`, 3 departments, 30 medicines. Then the app, loaded exactly as
Vercel loads it (`api/index.py`, `VERCEL=1`), let that admin log in and found
"Dolo 650" in the medicine search.

### 19.7 Every setting in one place: `.env.example`

`.env.example` lists **every** setting the code reads, grouped (database,
logins, hospital, phone calls, start-up), each with a plain-words comment. It
holds **no real secrets**: it's the template you copy to `.env` on your Mac, and
the checklist for Vercel's Environment Variables.

On Vercel you need at least:

| Setting | Value |
|---|---|
| `DATABASE_URL` | Neon's connection string (set for you when you add Neon from the Storage tab) |
| `SECRET_KEY` | a new random key, different from your Mac's |
| `DRY_RUN` | `true` (no real phone calls yet) |

The rest have sensible defaults. `VERCEL` is set by Vercel itself. The admin
details go in `.env.production` on your laptop, for `scripts/setup_production.py`.

`tests/test_env_example.py` scans the code for every `os.getenv("…")` and fails
if one isn't explained in `.env.example`, so the list can't fall behind.

### 19.8 The deployment guide

`DEPLOY.md` is the click-by-click version for going live: commit and push →
make a production `SECRET_KEY` → import the repo on Vercel (Framework: Other)
with `SECRET_KEY`, `DRY_RUN`, `HOSPITAL_TIMEZONE` → add Neon from the Storage tab
(sets `DATABASE_URL`) → run `scripts/setup_production.py` with the **unpooled**
connection string → **Redeploy** (settings only reach new deployments) → test
health, sign-up, booking, check-in + Call next, and the pharmacy on the live
address. It ends with a troubleshooting table and how to ship updates (a new
migration: run the script *before* pushing). `tests/test_deploy_guide.py` checks
that the files and commands it mentions really exist.

### 19.9 The dress rehearsal: `vercel dev`

`vercel dev` runs the site on your Mac the way Vercel will (same routes, same
Python builder) at http://localhost:3000. The full DEPLOY.md Step 7 test passed
through it: health, home page, admin, staff accounts, OPD session, sign-up,
booking (GEN-001), "I've arrived", Call next with the "It's your turn" banner,
prescription and bill. Getting there found three things that would have bitten
on the real site or on your Mac:

1. **`"maxDuration"` in `vercel.json`** broke Vercel's Python builder
   (`DEV_BUILDER_RESULT_HAS_MAXDURATION`). Removed: the default time limit is fine.
2. **Python 3.9.** macOS's built-in `python3` is 3.9; Vercel's helper and mediQ
   need 3.10 or newer (`cannot import name 'UTC'`). `.python-version` now says
   **3.12** for Vercel, and DEPLOY.md shows how to give `vercel dev` Python 3.12.
3. **`vercel link` edited `.gitignore`**, adding `.env*`. Last rule wins, so that
   would have hidden `.env.example` from git. Removed: the existing `.env` and
   `.env.*` rules already cover `.env.local`.

Also good to know: `vercel dev` reads your **`.env`**, and an empty
`DATABASE_URL=` line there wins over other files. So locally it uses `mediq.db`.

## Part 20. The redesign, step 2: a new home page, header and footer

**What changed**
- **One header bar** (drawn by `frontend/site.js` on every website page): logo, four menus,
  a search icon, an Emergency button (108 and 112, the real Indian numbers), Log in, and
  the one main button, **Book an appointment**. On small screens the menus fold behind a
  menu button. A hidden **"Skip to content"** link appears when you press Tab, so keyboard
  users can jump past the menu.
- **The home page has one idea per screen**: the hero (live waits), "How it works" (three
  steps beside a picture of the patient's phone), specialities beside a photo, one navy band
  of live numbers, the hospitals as a plain directory, and the call-back form.
- **Two real photos** in `frontend/img/`, borrowed under Creative Commons licences. Those
  licences say *you must name the author*, so the footer has a credits line (filled by `home.js`).

**Ideas worth remembering**
- *Prove, don't claim.* Every number on the page (waits, beds, doctors, ambulances) comes from
  the API. If the API says 0, the page says 0.
- *A list beats a grid of identical boxes.* The old page had five same-size "service cards";
  the new one uses rows with lines between them, which are easier to scan.
- *Class names can clash.* The phone picture first used `.ph-day`, but `.ph-` already meant
  "pharmacy" in style.css, so it became `.ps-` ("phone screen").
- *Tests guard old promises.* `test_frontend_urls` refused a full web address in `home.js`
  (it stops a server address being hard-coded), so the photo credit is plain text.

## Part 21. A floating sidebar, and light/dark on every page

**What changed**
- **`frontend/shell.js`** draws a sidebar on the 12 signed-in pages (patient, doctor, pharmacy,
  admin). It lists only the pages *your role* can open. The **Collapse** button folds it to icons
  and remembers your choice in `localStorage` (the browser's small notebook). On a phone it hides,
  and the menu button in the app bar slides it in as a *drawer*.
- Admin, the doctor's desk, Ambulance and Call-backs used the **website** header; they now use the
  **app bar** like the other staff pages, so every staff page looks the same.
- The website header has a **moon/sun button**, so light/dark now works on every page.

**Ideas worth remembering**
- *Hiding a link is not security.* The sidebar only hides pages you can't use; the server still
  checks your role on every request.
- *Old global styles can surprise you.* An early rule `nav { display: flex }` laid the sidebar's
  groups side by side. The fix was one line: `.sb-nav { display: block }`.
- *Off-screen menus must leave the Tab order.* A closed drawer gets `visibility: hidden`, so
  keyboard users don't tab into links they can't see.

## Part 22. The hospital overview: KPI cards and charts

**What changed**
- **`GET /api/admin/activity`** (admin only, in `routers/admin.py`) returns three real lists:
  arrivals per hour today, the actual average wait per department today (arrival → called),
  and bookings for the next 7 days. Counts only, never names.
- **`/dashboard.html`** shows six KPI cards (waiting, average wait, beds, doctors in, ambulances,
  stock alerts) and six charts. Admins now land here after logging in; it's also in the sidebar.

**Ideas worth remembering**
- *Time zones.* The server saves times on its own clock (UTC on Vercel), but "10:00" must mean
  10:00 in the hospital. `.astimezone(ZoneInfo("Asia/Kolkata"))` converts before we count by hour.
- *Choose the chart by the question.* "How many each hour?" is columns. "How is one whole split?"
  is a segmented bar. "How full is each ward?" is a meter per row. No pie charts.
- *Check colours with a tool, not your eyes.* Red next to green looks fine to most people but is
  the same colour to about 1 in 12 men, so the call-back bar orders them green, blue, amber, red.
- *Charts need words too.* Each chart has a table version and keyboard-reachable tooltips, and a
  warning colour always comes with an icon and a word ("Full", "Expired").

## Part 23. Redesigning the overview with dashboard rules

The overview was redone with six rules that suit any dashboard:
1. **A 12-column grid** (`.g12`, `.span-3`, `.span-8`...): every block takes whole columns, so
   edges line up. Tablets switch to 6 columns, phones to one.
2. **Whitespace over borders:** the key numbers have no boxes at all; sections are soft white
   panels on the pale page.
3. **Fewer things on the main view:** 4 numbers, one trend, one comparison. The rest sits in
   **tabs** (Queues, Beds, Bookings, Pharmacy, Staff and fleet). Tabs follow the ARIA pattern:
   `role="tab"`, `aria-selected`, and arrow keys move between them.
4. **Mostly grey, one accent:** cobalt marks only the key point (this hour, the longest wait);
   amber/red appear only for problems, with an icon and a word.
5. **Scannable numbers:** whole minutes, whole percents, numbers right-aligned in tables.
6. **The chart fits the question:** a line for "how did today go?" (a trend), sorted bars for
   "which department waits longest?" (a comparison). The hour that isn't over yet is dashed,
   so a half-finished hour doesn't look like a sudden drop.

## Part 24. हिन्दी: the whole patient side in Hindi

**How it works**
- The pages stay written in English. `frontend/lang-hi.js` is a dictionary:
  `"Book an appointment": "अपॉइंटमेंट बुक करें"`. It is only downloaded when Hindi is chosen.
- `core.js` (section 1b) walks through every piece of text on the page and swaps it for the Hindi.
  A **MutationObserver** (the browser telling us "the page just changed") translates text that
  scripts add later: live numbers, messages, the server's error messages.
- Sentences with numbers or names use **patterns**: `/^(\d+) min$/ -> "$1 मिनट"`.
  Dates like "Thu 26 Nov" become "गुरु 26 नव॰". Lists ("Chest pain, Back pain") are translated part by part.
- The choice is saved in `localStorage` (`mediq_lang`); switching reloads the page.
- What people **type** (textareas) and names (doctors, tokens like GEN-014) are never changed.

**To add or fix a translation:** copy the English exactly as it appears on the page and add a
line to `phrases` in lang-hi.js. Have a native speaker check the medical words before going live.

**Not yet in Hindi:** the staff pages (doctor's desk, pharmacy, admin, dashboard). They will
show English for words the dictionary doesn't have yet.
