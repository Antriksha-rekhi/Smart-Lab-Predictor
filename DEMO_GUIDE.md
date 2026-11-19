# Spacewise demo guide

## Before presenting

1. Start Flask from the project folder with the virtual environment active: `python3 app.py`.
2. Open `http://127.0.0.1:5000` and confirm the dashboard loads.
3. Keep the terminal running during the demo.
4. Call the built-in records **synthetic demo data**, not real campus measurements.

## Five-minute walkthrough

### 1. Problem and goal — 30 seconds

“Students may not know whether a classroom is free or whether a lab has usable computers. Spacewise brings the timetable, manually maintained computer status, and historical observations into one dashboard.”

### 2. Dashboard — 60 seconds

Choose a day and time. Point out the scheduled-session result, the current lab computer count, the historical availability estimate, and the best currently eligible option. Explain that timetable and current status are direct records, while the probability is based on past observations and is not a guarantee.

Useful seeded example: Computer Lab 1 has a Monday session from 10:00 to 12:00. Select Monday at 11:00 and show that it is scheduled. Select a time without a session to compare. The lab's computer count comes from the manually maintained statuses.

### 3. Computer status and set theory — 60 seconds

Open **Manage computers** and show the three statuses: Available, Occupied, and Maintenance. Then open **Set explorer** and choose Available ∩ Occupied. It should contain zero computers because a computer has exactly one status at a time. Explain that `&` in Python calculates intersection, and each computer's database ID keeps computers with repeated labels in different labs distinct.

### 4. Timetable and relations — 60 seconds

Open **Timetable** and show that a space is related to its sessions through `space_id`. Explain that the overlap rule rejects sessions where `existing_start < new_end` and `existing_end > new_start`. The app stores the relationship with SQLite foreign keys.

### 5. Observations and probability — 60 seconds

Open **Add observation** and show an observation as one recorded outcome for a space, day, and time. Explain:

`P(available) = available observations / total observations`

The dashboard shows both the percentage and the observation count. If there are no observations, it shows “No data” instead of dividing by zero.

Open **Usage log** to show sample computer records and duration calculation. You can save a new record; the app rejects overlapping use for the same computer.

### 6. Close — 30 seconds

“This is a local demonstration using Flask and SQLite. Statuses are entered manually; there are no live sensors. The historical probability summarizes sample observations and cannot guarantee future availability.”

## Suggested real four-person presentation split

1. **Person 1:** Problem, project goal, and spaces/computers data.
2. **Person 2:** Set theory and the Set explorer.
3. **Person 3:** Timetable and database relations.
4. **Person 4:** Observation records, empirical probability, limitations, and conclusion.

Each person should explain and take responsibility for the part they actually worked on.

## Backup if the live demo fails

- Explain the planned flow from this guide and show the project files.
- The core pages were checked through Flask's in-process client; the in-app browser may not be able to reach a local `127.0.0.1` server. Use a browser on the same Mac where Flask is running.
- Do not claim that the sample data is actual college data or that the app uses sensors or machine learning.
