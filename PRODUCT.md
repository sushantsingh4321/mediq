# mediQ: product

**What it is.** OPD (outpatient) queue and hospital-operations software for a network of
Indian hospitals: patients book a doctor's time and follow their place in the queue live;
staff run the queue, beds, ambulances, the pharmacy and the schedule.

**Who uses it, and where**

| Who | Where, under what light | What they came to do |
|---|---|---|
| Patients and families | on a phone, at home or in a bright waiting room, often anxious | book a slot, see their token and wait, know when to walk in |
| Doctors | at a consulting-room desk, bright clinical light, between patients | call the next patient, see who is coming, write prescriptions |
| Pharmacists | at a counter, standing, interrupted | dispense a prescription correctly (batches, expiry, Schedule H), print a bill |
| Admins | an office desk | accounts, schedules, departments, reports |
| Everyone in the waiting room | a TV on the wall, read from metres away | "Now serving GEN-014 → Room 3" |

**Surfaces and their mode** (impeccable's modes)

| Surface | Mode | Success looks like |
|---|---|---|
| Home page `/` | Persuade | in seconds a visitor knows this is a hospital network with live, short waits, and books |
| Book, My appointments | Operate (patient) | a booking in about a minute on a phone; the token, wait and "your turn" never missed |
| Log in, Sign up | Operate | in and out, no confusion |
| Doctor's desk, Appointments, Pharmacy, Admin, Schedule, Beds, Ambulance | Operate | the task done fast and without error; state always visible |
| Waiting-room display | Experience-like signage | readable from across the room |

**Product truths that never change in a redesign**
- One main action on the home page: **Book an appointment** (patients).
- Live numbers are real (wait times, waiting counts, beds, doctors on duty), never invented.
- English and Hindi (हिन्दी) must both render: every face needs a Devanagari partner.
- Works on a 360px phone, at 200% zoom, and with the keyboard alone.
- Light and dark mode, defaulting to the device setting.
- Demo content is fictional: phone numbers and addresses are clearly fake (`.example` emails,
  no realistic phone numbers or postcodes).

**Brand commitments (pinned by the owner)**
- The home hero is the GradientASCII "horizon" (frontend/gradient-ascii.js) with its palette:
  `#1e3fd8`, `#f6f8ff`, `#a5d8ff`, `#38bdf8`, on a night-navy ground.
- Minimal: fewer, larger things; one idea per screen on the website.
