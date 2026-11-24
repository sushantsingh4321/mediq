# Putting mediQ online (Vercel + Neon)

This guide takes mediQ from your Mac to a public web address, step by step.
It takes about 30 minutes the first time. You need:

- your GitHub account (the code is in the **curable** repository),
- a free **Vercel** account (it will host the website), and
- a free **Neon** database (PostgreSQL), which you add from inside Vercel.

How it fits together (LEARN.md Part 19 explains why):

```
browser ──> Vercel ──┬── pages (HTML, CSS, JS) straight from the frontend/ folder
                     └── /api/...  ──> mediQ's Python code (api/index.py) ──> Neon database
```

Your Mac's `mediq.db` and `.env` stay on your Mac. They are never uploaded.

---

## Step 1. Put the latest code on GitHub

Open **Terminal** and go to the project folder:

```bash
cd ~/Desktop/MediQ/mediq
```

Check that everything works (all tests should pass):

```bash
.venv/bin/pytest -q
```

Save the deployment changes as commits, one piece at a time. Copy each pair of
lines, press Enter, and check that it says `files changed`:

```bash
git add .gitignore tests/test_deploy_safety.py
git commit -m "Keep secrets, databases and Vercel files out of git"

git add api/index.py vercel.json .python-version requirements.txt backend/app/main.py tests/test_vercel_setup.py tests/test_frontend_urls.py
git commit -m "Add Vercel setup: serverless API function and static frontend"

git add backend/app/config.py backend/app/database.py backend/app/routers/auth.py backend/app/security.py backend/app/services/sms.py migrations/versions tests/conftest.py tests/test_database.py tests/test_database_config.py
git commit -m "Make the database work on Neon Postgres (driver, NullPool, migrations)"

git add tests/test_startup.py
git commit -m "No start-up work or background jobs on Vercel"

git add scripts tests/test_setup_production.py
git commit -m "Add script to set up the production database"

git add .env.example tests/test_env_example.py tests/test_deploy_guide.py LEARN.md DEPLOY.md
git commit -m "Document every setting and how to deploy"
```

Then check that nothing is left, and upload:

```bash
git status
git push
```

`git status` should say **nothing to commit, working tree clean**.
`git push` asks for your GitHub username and, as the password, your **GitHub
token** (not your normal password). Nothing shows while you paste it; that's normal.

Open https://github.com/sushantsingh4321/curable and check that you can see the
folders `api` and `scripts` and the file `vercel.json`.

---

## Optional: try it on your Mac exactly as Vercel runs it (`vercel dev`)

This step is optional; it was already done once for you. `vercel dev` serves the
site the way Vercel will (same routing, same Python builder), on your Mac, at
http://localhost:3000. It uses your local `.env` and `mediq.db`.

One-time setup: Node.js, the Vercel tool and `uv` (a helper Vercel's Python builder needs):

```bash
brew install node uv
npm install -g vercel
vercel login
cd ~/Desktop/MediQ/mediq
vercel link
```

Then, each time:

```bash
PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH" vercel dev
```

The `PATH=…` part makes it use Python 3.12. Without it, macOS's old built-in
Python 3.9 is used and every `/api/...` request fails with
`cannot import name 'UTC' from 'datetime'`. Stop it with **Ctrl + C**.

---

## Step 2. Make a secret key for the live site

The live site needs its own `SECRET_KEY` (it signs everyone's logins). Make a
new one, **different from the one on your Mac**:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

It prints a long random line. Keep this Terminal window open; you'll paste it in Step 3.
Never put it in a file that goes to GitHub.

---

## Step 3. Create the project on Vercel

1. Go to **https://vercel.com** and **Sign up / Log in with GitHub**.
2. Click **Add New… → Project**.
3. Find **curable** in the list and click **Import**.
   (Not in the list? Click **Adjust GitHub App Permissions** and give Vercel access to it.)
4. On the **Configure Project** screen:
   - **Project Name:** e.g. `curable` (it becomes part of your web address).
   - **Framework Preset:** **Other**.
   - **Root Directory:** leave it as `./`.
   - **Build and Output Settings:** leave them alone. `vercel.json` already says what to do.
5. Open **Environment Variables** and add these three, one at a time
   (Key on the left, Value on the right, then **Add**):

   | Key | Value |
   |---|---|
   | `SECRET_KEY` | the long line from Step 2 |
   | `DRY_RUN` | `true` |
   | `HOSPITAL_TIMEZONE` | `Asia/Kolkata` |

6. Click **Deploy** and wait about a minute.

The site's pages will now open, but anything that needs data won't work yet:
there is no database. That's next.

> **Already ran `vercel link` / `vercel dev` on your Mac?** Then the project
> already exists on Vercel (`vercel link` named it **mediq**), without GitHub.
> Don't import it again. Open the **mediq** project → **Settings → Git →
> Connect Git Repository** → choose **curable**. Your address will be
> `https://mediq-….vercel.app`. Then add the three settings above in **Settings → Environment
> Variables**, and do **Deployments → Redeploy** (or just `git push`).

---

## Step 4. Add the Neon database

1. In your Vercel project, open the **Storage** tab.
2. Click **Create Database** (or **Connect Database**), choose **Neon** (Serverless Postgres), and **Continue**.
3. Pick a region close to your patients (for India: **Singapore** or **Mumbai** if offered), keep the free plan, and give it a name like `mediq-db`.
4. When it asks which environments to connect, tick **Production** and **Preview**, and connect it to the **curable** project.

Vercel now adds the database settings to your project by itself, including
**`DATABASE_URL`**. Check: **Settings → Environment Variables**: you should see
`DATABASE_URL` (and some others starting with `PG…` / `POSTGRES_…`; leave those alone).

---

## Step 5. Set up the database from your laptop

The live site never changes the database's tables by itself (LEARN.md 19.5).
You do it once now, from your Mac, with a script.

**5a. Get the connection string.** In Vercel: **Storage → your database →**
**`.env.local` / Quickstart** (or in the Neon console: **Connection string**).
Copy the value of **`DATABASE_URL_UNPOOLED`**. For setting up tables, the
*direct* (unpooled) connection is the right one. (If you only see
`DATABASE_URL`, that works too.) It looks like:

```
postgresql://neondb_owner:abc123...@ep-cool-name-123456.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

**5b. Make the file `.env.production`** in the `mediq` folder. Open it in VS Code
(**File → New File**, save as `.env.production` in the `mediq` folder) and write:

```
DATABASE_URL=postgresql://...the line you copied...?sslmode=require
ADMIN_EMAIL=your-email@example.com
ADMIN_PASSWORD=choose-a-long-password-just-for-the-live-site
```

This is the **live** admin account. Use a strong password, different from your
Mac's. `.env.production` is in `.gitignore`: git will never upload it.

**5c. Run the script:**

```bash
cd ~/Desktop/MediQ/mediq
.venv/bin/python scripts/setup_production.py
```

It shows where it will write (your Neon host, never the password) and asks
**Continue? Type yes**. Type `yes` and press Enter. You should see:

```
1. Migrations ...
   tables are at version 0011
2. Admin account ...
   admin accounts: your-email@example.com
3. Departments ...
4. Sample data: medicines, wards, ambulances ...

Done. departments: 3, medicines: 30, wards: 3, ambulances: 4, users: 1
```

(Want an empty hospital without the sample medicines, wards and ambulances? Add
`--no-sample-data` to the command.)

---

## Step 6. Deploy again

Settings only reach the site on the **next** deployment, and `DATABASE_URL` was
added after the first one. In Vercel: **Deployments** → the top one → **⋯** →
**Redeploy** → **Redeploy**. Wait for **Ready**.

Your address is on the project's **Overview** page, e.g. `https://curable.vercel.app`.

> Use the **production** address (on the Overview page). The longer "preview"
> addresses may ask you to log in to Vercel first; that's Vercel's protection
> for unfinished versions, not mediQ.

---

## Step 7. Test the live site

Do these in order. Each one checks a different part.

**7a. Is it alive?** Open `https://YOUR-ADDRESS/api/health`.
You should see something like `{"status":"ok", ...}`.

**7b. The website.** Open `https://YOUR-ADDRESS/`. The home page appears with
its menu. Click **Book Appointment**: the booking page has a blue bar with a moon
button; try it (dark mode).

**7c. Admin login.** Log in with the `ADMIN_EMAIL` / `ADMIN_PASSWORD` from
`.env.production`. You land on the admin console.

**7d. Make staff accounts.** On the admin page, create:
- a **Doctor** (e.g. `doctor@yourhospital.example`), and
- a **Pharmacist** (e.g. `pharmacy@yourhospital.example`).

**7e. Give the doctor an OPD session.** Open **Doctor schedule**, add a session
for the doctor in **General Medicine**, **today**, from now until a few hours
later. (Booking only shows doctors with sessions.)

**7f. Patient sign-up and booking.** Log out. Click **Sign up**, make a patient
account, then **Book Appointment**: General Medicine → your doctor → today → a
free time about 30-60 minutes from now → write a reason → **Book appointment**.
On **My appointments** you see **Confirmed** and a token like **GEN-001**.

**7g. The token flow.** Still as the patient, press **I've arrived** (it opens 1
hour before the slot). Then log in as the doctor (another browser or a private
window), open **Doctor's desk**, pick General Medicine and the room, and press
**Call next patient**. The patient's page says **It's your turn**.

**7h. Pharmacy.** As the doctor, **Add prescription** for that patient (e.g.
Dolo 650, 1-0-1, 3 days). Log in as the pharmacist → **Dispense** → pick the
prescription → **Dispense and make bill** → **Print bill**.

If all of that works, mediQ is live.

---

## When something goes wrong

**Where to look:** Vercel → your project → **Logs** (or **Deployments** → a
deployment → **Functions**). Errors from the Python code show up there.

| You see | Why | Fix |
|---|---|---|
| Error mentioning **`SECRET_KEY is not set`** | it's missing in Vercel | Step 3.5, then **Redeploy** (Step 6) |
| **`relation "users" does not exist`**, or logins fail on a fresh site | the database is empty | run the script (Step 5), no redeploy needed |
| **Pages open, but every `/api/...` gives an error** | `DATABASE_URL` missing, or added after the last deploy | check **Settings → Environment Variables**, then **Redeploy** |
| The script says **`could not translate host name`** or **timeout** | wrong connection string, or no internet | copy it again from Neon/Vercel; keep `?sslmode=require` |
| The script stops: **ADMIN_EMAIL and ADMIN_PASSWORD must be in .env.production** | the file is missing them | add both lines to `.env.production` |
| Booking shows **no doctors** | no OPD session for that department | Step 7e |
| The very first click after a quiet while is slow (a few seconds) | a "cold start": Vercel is starting the Python code | normal; the next clicks are fast |
| A preview address asks you to log in to Vercel | Vercel's deployment protection | use the production address |

---

## Later: updating the live site

**Code changes:** commit and `git push`. Vercel deploys every push to `main` by
itself (watch **Deployments**).

**A new migration** (a new file in `migrations/versions/`): run the script
**before** pushing, so the tables are ready when the new code arrives:

```bash
.venv/bin/python scripts/setup_production.py
git push
```

It's always safe to run again: it only adds what's missing.

---

## Safety checklist

- `.env`, `.env.production` and `mediq.db` never go to GitHub (`.gitignore` covers them).
- The live `SECRET_KEY` is different from your Mac's and is only in Vercel.
- `DRY_RUN=true`: call-back requests are saved but no real phone is called. Change
  it only after setting up Twilio (the `TWILIO_…` settings in `.env.example`).
- After your first live login, you may delete `ADMIN_PASSWORD` from `.env.production`.
  The account already exists, and the script never changes an existing admin.
- Patient data now lives in Neon. In the Neon console you can see **Backups /
  Branches** (point-in-time restore) for your plan.
