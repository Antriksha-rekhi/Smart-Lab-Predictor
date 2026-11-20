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

When launched locally with `python app.py`, Spacewise enables a clearly labeled local demo sign-in so the pages can be presented without college OAuth credentials. The demo form accepts a name, registration ID, and `@it.vjti.ac.in` email but does not verify them. Do not expose this local demo mode on a public server. When the app is imported by a production server, demo mode is off unless explicitly enabled with `SPACEWISE_DEMO_MODE=1`.

To run the automated checks, use `python -m unittest discover -s tests -v`.

## Optional Windows login-status collector

The `collector/windows_collector.py` script is a small per-PC agent. It checks whether Windows has an active interactive session and sends only the computer database ID plus `available` or `occupied` to `POST /api/computer-status`. It does not read or send usernames. The server authenticates updates with the `COMPUTER_STATUS_TOKEN` environment variable. The dashboard marks collector data as **Unknown** if it has not received a heartbeat for 90 seconds; manual status entries do not expire. Maintenance status remains protected from collector updates.

This is an integration prototype. College IT must approve and configure it on authorized lab PCs, map each PC to its ID (shown on Manage computers), and run the script at startup. Set the token as a secret environment variable on the Flask host. On each Windows PC, set `SPACEWISE_API_URL` to the server address, `SPACEWISE_COMPUTER_ID` to that PC's database ID, and `COMPUTER_STATUS_TOKEN` to the same secret, then run `python collector\\windows_collector.py`. Use HTTPS for a deployed server; do not expose the token over a public HTTP connection. A logged-in session indicates occupied, but it cannot prove a person is physically at the computer.

## Admin portal

Open **Admin portal** or visit `/admin`. Set `ADMIN_PASSWORD` in the environment before starting the app; the password is not stored in SQLite or source code. For a local macOS/Linux shell:

```bash
export ADMIN_PASSWORD='choose-a-private-password'
.venv/bin/python app.py
```

An administrator can set each lab computer to Available, In use, or Under maintenance. Student accounts cannot edit computer status. If `ADMIN_PASSWORD` is not set during a local `python app.py` presentation run, `/admin` offers a clearly marked demo-admin entry. Anyone with access to that local app can use this mode. For a deployed server, set a strong private `ADMIN_PASSWORD`; demo-admin mode defaults off. A manual maintenance status is protected from the Windows collector until an admin changes it back.

## Student Google/Microsoft sign-in setup

The student page is the landing page. Local presentation runs provide a clearly marked demo sign-in. Real student sign-in uses OpenID Connect through Authlib and only accepts accounts whose provider-issued email ends in `@it.vjti.ac.in`; it requires registered Google/Microsoft OAuth applications and credentials supplied by an authorized administrator. Never commit client secrets to Git or paste them into source files.

Set these environment variables before starting Flask:

```bash
export SECRET_KEY='use-a-long-random-secret'
export STUDENT_EMAIL_DOMAIN='it.vjti.ac.in'
export GOOGLE_CLIENT_ID='...'
export GOOGLE_CLIENT_SECRET='...'
export MICROSOFT_CLIENT_ID='...'
export MICROSOFT_CLIENT_SECRET='...'
export MICROSOFT_TENANT_ID='organizations'
```

Register these exact callback URLs in the provider applications (adjust the host for your deployment):

- Local Google: `http://127.0.0.1:5000/student-login/google/callback`
- Local Microsoft: `http://127.0.0.1:5000/student-login/microsoft/callback`
- For deployment, use the matching HTTPS domain and callback paths.

Google's OAuth application must allow the local/deployed origin and callback. For Microsoft, the app registration must support organizational accounts; use the tenant ID supplied by VJTI IT if one is available. Provider registration and secrets require access to the respective developer portals; the project itself cannot create or guarantee those credentials. Authlib handles the OIDC authorization-code flow and token/ID-token validation; the app then enforces the allowed email domain. See [Google's OpenID Connect docs](https://developers.google.com/identity/openid-connect/openid-connect) and [Microsoft's Flask sign-in tutorial](https://learn.microsoft.com/en-us/entra/identity-platform/tutorial-web-app-python-flask-sign-in).

The identity providers return account name and email, not VJTI registration numbers. The current login does not ask for or claim to verify a registration ID. A real registration ID check requires an authorized student directory or registrar-provided source.

## Pages

- **Availability:** choose a weekday and time slot; compare schedule restrictions, lab computer counts, and the historical estimate.
- **Manage spaces:** add classrooms and labs; register a chosen number of computers for each new lab.
- **Manage computers:** manually update statuses or identify a computer for the optional Windows collector.
- **Admin portal:** password-protected manual status updates, including maintenance mode.
- **Timetable:** add space sessions; the app rejects overlapping sessions for the same space and day.
- **Usage log:** record computer usage dates and times, see calculated durations, and reject overlapping use of the same computer.
- **Project report:** see [PROJECT_REPORT.md](PROJECT_REPORT.md) for the academic write-up, ER diagram, equations, limitations, and references.
- **Set explorer:** calculate union, intersection, difference, and complement of available, occupied, maintenance, and unknown computer status sets.
- **Lab simulator:** use SimPy to model student requests competing for the currently reported free lab computers; NumPy supplies random arrivals and session durations, and pandas summarizes repeated runs.
- **Add observation:** record whether a space was available at a given date and time.
- **Student login:** Google/Microsoft OpenID Connect for `@it.vjti.ac.in` accounts after provider setup; no registration ID is inferred.
- **Recommendation:** the dashboard ranks currently eligible spaces by historical availability, then the number of available lab computers.

## Concepts used

- **Set theory:** registered computers form the universe `C`; available, occupied, maintenance, and unknown computers form disjoint subsets. Python `set` implements operations and `len()` gives cardinality.
- **Discrete probability:** for a space, weekday and time slot, `P(available | selected day and time) = available observations / all observations for that day and time`. The dashboard shows the sample count; no observations means “No data.”
- **Probability simulation:** NumPy draws exponential arrival gaps and session lengths from user-specified averages. SimPy models the limited computers as a shared resource and measures queues. Pandas summarizes the repeated run results. This demonstrates stochastic simulation and queueing; output depends on assumptions and does not guarantee real wait times.
- **Data analysis:** pandas groups observation records by selected weekday and time to calculate the empirical availability fraction.
- **Relations:** foreign keys connect computers, sessions, observations, and usage records to their parent spaces or computers. SQL `JOIN` retrieves related names for display.
- **Python:** functions, dictionaries, lists, sets, loops, conditionals, input validation, Flask routes/templates, and SQLite.

## Scope and limitations

The sample data is synthetic and is labeled as demonstration data. Timetable availability assumes a space is free when no session overlaps the selected slot. Lab statuses can be manually maintained or reported by the optional Windows collector; a login session indicates use but does not prove physical presence. Usage records are entered manually. Recommendations use saved statuses and empirical observations; probabilities are estimates, not guarantees. The simulator is a separate what-if analysis and does not change actual availability or reserve a computer.

Until provider applications and credentials are configured, student sign-in is not available. Configure HTTPS, a persistent random `SECRET_KEY`, and provider callback URLs before public deployment.

## Suggested real group contributions

1. Database and space/computer records.
2. Set operations and status rules.
3. Timetable logic and dashboard UI.
4. Observation entry and probability analysis.

Each group member should implement, understand, and present their actual contribution. Keep project data and screenshots labeled as demo data until replaced with verified campus information.
