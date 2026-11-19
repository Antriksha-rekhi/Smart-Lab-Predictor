# Spacewise — Campus Space Availability

A beginner-friendly Flask + SQLite project for checking classroom availability and the number of available computers in campus labs. The app demonstrates set operations, empirical discrete probability, and relations in a working interface.

## Run locally

```bash
python -m venv .venv
```

Activate the environment (Windows PowerShell: `.venv\Scripts\Activate.ps1`; macOS/Linux: `source .venv/bin/activate`), then:

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The SQLite database is created automatically and filled with clearly synthetic demonstration records on first run.

To run the automated checks, use `python -m unittest discover -s tests -v`.

## Pages

- **Availability:** choose a weekday and time slot; compare schedule restrictions, lab computer counts, and the historical estimate.
- **Manage spaces:** add classrooms and labs; register a chosen number of computers for each new lab.
- **Manage computers:** manually update lab computers as available, occupied, or under maintenance.
- **Timetable:** add space sessions; the app rejects overlapping sessions for the same space and day.
- **Usage log:** record computer usage dates and times, see calculated durations, and reject overlapping use of the same computer.
- **Project report:** see [PROJECT_REPORT.md](PROJECT_REPORT.md) for the academic write-up, ER diagram, equations, limitations, and references.
- **Set explorer:** calculate union, intersection, difference, and complement of computer status sets.
- **Add observation:** record whether a space was available at a given date and time.
- **Recommendation:** the dashboard ranks currently eligible spaces by historical availability, then available lab computers and capacity.

## Concepts used

- **Set theory:** registered computers form the universe `C`; available, occupied, and maintenance computers form disjoint subsets. Python `set` implements operations and `len()` gives cardinality.
- **Discrete probability:** for a space, weekday and time slot, `P(available | selected day and time) = available observations / all observations for that day and time`. The dashboard shows the sample count; no observations means “No data.”
- **Relations:** foreign keys connect computers, sessions, observations, and usage records to their parent spaces or computers. SQL `JOIN` retrieves related names for display.
- **Python:** functions, dictionaries, lists, sets, loops, conditionals, input validation, Flask routes/templates, and SQLite.

## Scope and limitations

The sample data is synthetic and is labeled as demonstration data. Timetable availability assumes a space is free when no session overlaps the selected slot; it does not replace a live occupancy sensor or campus timetable feed. A lab’s computer statuses are manually maintained. Usage records are entered manually. Recommendations use the saved status and empirical observations; probabilities are estimates, not guarantees. The app does not use machine learning, NumPy, or pandas.

## Suggested real group contributions

1. Database and space/computer records.
2. Set operations and status rules.
3. Timetable logic and dashboard UI.
4. Observation entry and probability analysis.

Each group member should implement, understand, and present their actual contribution. Keep project data and screenshots labeled as demo data until replaced with verified campus information.
