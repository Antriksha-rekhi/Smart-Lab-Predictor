"""Campus space availability demo: classrooms and lab computers."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from hmac import compare_digest

from flask import Flask, flash, g, redirect, render_template, request, session, url_for

try:
    import numpy as np
except ImportError:
    np = None
try:
    import pandas as pd
except ImportError:
    pd = None
try:
    import simpy
except ImportError:
    simpy = None

try:
    from authlib.integrations.flask_client import OAuth
except ImportError:
    OAuth = None

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "campus_availability.db"
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["LOCAL_DEMO_MODE"] = os.environ.get(
    "SPACEWISE_DEMO_MODE", "1" if __name__ == "__main__" else "0"
).strip().lower() in {"1", "true", "yes", "on"}
STUDENT_EMAIL_DOMAIN = os.environ.get("STUDENT_EMAIL_DOMAIN", "it.vjti.ac.in").strip().lower().lstrip("@")
oauth = OAuth(app) if OAuth else None

if oauth:
    oauth.register(
        name="google",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    microsoft_tenant = os.environ.get("MICROSOFT_TENANT_ID", "organizations")
    oauth.register(
        name="microsoft",
        client_id=os.environ.get("MICROSOFT_CLIENT_ID"),
        client_secret=os.environ.get("MICROSOFT_CLIENT_SECRET"),
        server_metadata_url=f"https://login.microsoftonline.com/{microsoft_tenant}/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.before_request
def require_student_sign_in():
    """Send visitors to college sign-in before rendering protected app pages."""
    public_endpoints = {
        "static", "student_login", "student_login_start", "student_login_callback",
        "student_logout", "student_demo_login", "receive_computer_status", "admin_portal",
    }
    if request.endpoint == "manage_computers" and not session.get("admin_authenticated"):
        flash("Computer status changes are available to administrators only.", "error")
        return redirect(url_for("admin_portal"))
    if (request.endpoint not in public_endpoints and not session.get("student_profile")
            and not session.get("admin_authenticated")):
        return redirect(url_for("student_login", next=request.full_path.rstrip("?")))


def initialize_database():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS spaces (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('classroom', 'lab')),
            location TEXT NOT NULL,
            capacity INTEGER NOT NULL CHECK (capacity >= 0)
        );
        CREATE TABLE IF NOT EXISTS computers (
            id INTEGER PRIMARY KEY,
            space_id INTEGER NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('available', 'occupied', 'maintenance')),
            UNIQUE(space_id, name)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            space_id INTEGER NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            title TEXT NOT NULL,
            CHECK (start_time < end_time)
        );
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY,
            space_id INTEGER NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            observed_on TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            was_available INTEGER NOT NULL CHECK (was_available IN (0, 1))
        );
        CREATE TABLE IF NOT EXISTS usage_records (
            record_id INTEGER PRIMARY KEY,
            computer_id INTEGER NOT NULL REFERENCES computers(id) ON DELETE CASCADE,
            usage_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            CHECK (start_time < end_time)
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_space_day_time ON sessions(space_id,weekday,start_time,end_time);
        CREATE INDEX IF NOT EXISTS idx_observations_space_time ON observations(space_id,time_slot,observed_on);
        CREATE INDEX IF NOT EXISTS idx_usage_computer_date ON usage_records(computer_id,usage_date,start_time,end_time);
    """)
    # Add heartbeat metadata to databases created by earlier versions.
    computer_columns = {row[1] for row in db.execute("PRAGMA table_info(computers)")}
    if "last_seen_at" not in computer_columns:
        db.execute("ALTER TABLE computers ADD COLUMN last_seen_at TEXT")
    if "status_source" not in computer_columns:
        db.execute("ALTER TABLE computers ADD COLUMN status_source TEXT NOT NULL DEFAULT 'manual'")
    if db.execute("SELECT COUNT(*) FROM spaces").fetchone()[0] == 0:
        seed_demo_data(db)
    if db.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0] == 0:
        seed_demo_usage(db)
    db.commit()
    db.close()


def effective_computer_status(computer, now=None):
    """Hide stale collector values rather than claiming an offline PC is free."""
    if computer["status_source"] != "collector":
        return computer["status"]
    try:
        last_seen = datetime.fromisoformat(computer["last_seen_at"])
    except (TypeError, ValueError):
        return "unknown"
    now = now or datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return computer["status"] if now - last_seen <= timedelta(seconds=90) else "unknown"


def seed_demo_data(db):
    spaces = [
        ("Lecture Hall A", "classroom", "Block A · 1st floor", 60),
        ("Room B204", "classroom", "Block B · 2nd floor", 35),
        ("Computer Lab 1", "lab", "Block C · Ground floor", 24),
        ("Computer Lab 2", "lab", "Block C · 1st floor", 20),
    ]
    db.executemany("INSERT INTO spaces(name,kind,location,capacity) VALUES(?,?,?,?)", spaces)
    ids = {row[0]: row[1] for row in db.execute("SELECT name,id FROM spaces")}
    for lab, names in (("Computer Lab 1", [f"PC-{i:02}" for i in range(1, 13)]),
                       ("Computer Lab 2", [f"PC-{i:02}" for i in range(1, 11)])):
        for index, name in enumerate(names):
            status = "maintenance" if index % 10 in (2, 9) else ("occupied" if index % 3 == 0 else "available")
            db.execute("INSERT INTO computers(space_id,name,status) VALUES(?,?,?)", (ids[lab], name, status))
    sessions = [
        ("Lecture Hall A", 0, "09:00", "11:00", "Engineering Mathematics"),
        ("Lecture Hall A", 2, "13:00", "15:00", "Physics"),
        ("Room B204", 1, "10:00", "12:00", "Programming"),
        ("Room B204", 3, "14:00", "16:00", "Tutorial"),
        ("Computer Lab 1", 0, "10:00", "12:00", "Python Lab"),
        ("Computer Lab 1", 4, "13:00", "15:00", "Database Lab"),
        ("Computer Lab 2", 1, "09:00", "11:00", "Networks Lab"),
    ]
    db.executemany("INSERT INTO sessions(space_id,weekday,start_time,end_time,title) VALUES(?,?,?,?,?)",
                   [(ids[name], day, start, end, title) for name, day, start, end, title in sessions])
    # Explicitly synthetic observations, so probabilities are demonstrations rather than campus facts.
    for space_name, probabilities in (("Lecture Hall A", [0.3, 0.7, 0.8, 0.6]),
                                       ("Room B204", [0.6, 0.5, 0.75, 0.9]),
                                       ("Computer Lab 1", [0.35, 0.55, 0.65, 0.8]),
                                       ("Computer Lab 2", [0.7, 0.6, 0.45, 0.75])):
        for slot_index, probability in enumerate(probabilities):
            for sample in range(10):
                day_offset = sample + slot_index * 10
                available = int(((sample * 7 + slot_index * 3) % 10) < round(probability * 10))
                db.execute("INSERT INTO observations(space_id,observed_on,time_slot,was_available) VALUES(?,?,?,?)",
                           (ids[space_name], date(2026, 9, 1).fromordinal(date(2026, 9, 1).toordinal() + day_offset).isoformat(),
                            ("09:00", "11:00", "13:00", "15:00")[slot_index], available))


def seed_demo_usage(db):
    """Add synthetic usage logs to the already seeded labs, including on existing installs."""
    sample_usage = [
        ("Computer Lab 1", "PC-01", "2026-09-07", "09:00", "10:00"),
        ("Computer Lab 1", "PC-02", "2026-09-07", "10:00", "11:30"),
        ("Computer Lab 1", "PC-04", "2026-09-08", "11:00", "12:00"),
        ("Computer Lab 1", "PC-05", "2026-09-09", "13:00", "14:30"),
        ("Computer Lab 2", "PC-01", "2026-09-07", "09:00", "11:00"),
        ("Computer Lab 2", "PC-03", "2026-09-08", "13:00", "14:00"),
        ("Computer Lab 2", "PC-04", "2026-09-10", "14:00", "15:30"),
        ("Computer Lab 2", "PC-06", "2026-09-11", "10:00", "11:00"),
    ]
    computer_ids = {(row[0], row[1]): row[2] for row in db.execute(
        "SELECT s.name,c.name,c.id FROM computers c JOIN spaces s ON s.id=c.space_id")}
    data = [(computer_ids[(lab, computer)], day, start, end)
            for lab, computer, day, start, end in sample_usage
            if (lab, computer) in computer_ids]
    db.executemany("INSERT INTO usage_records(computer_id,usage_date,start_time,end_time) VALUES(?,?,?,?)", data)


def space_availability(space, weekday, slot):
    """Return current status, schedule conflicts, and historic empirical probability."""
    db = get_db()
    space_id = space["id"]
    occupied_session = db.execute("""SELECT title FROM sessions
        WHERE space_id=? AND weekday=? AND start_time<=? AND end_time>? LIMIT 1""",
        (space_id, weekday, slot, slot)).fetchone()
    computers = db.execute("SELECT status,status_source,last_seen_at FROM computers WHERE space_id=?",
                           (space_id,)).fetchall()
    computer_statuses = [effective_computer_status(row) for row in computers]
    available_computers = sum(status == "available" for status in computer_statuses)
    if space["kind"] == "lab":
        current_available = available_computers > 0 and occupied_session is None
    else:
        current_available = occupied_session is None
    # Python weekdays use Monday=0; SQLite strftime('%w') uses Sunday=0.
    sqlite_weekday = (weekday + 1) % 7
    if pd is not None:
        historical_rows = db.execute(
            "SELECT observed_on,time_slot,was_available FROM observations WHERE space_id=?",
            (space_id,),
        ).fetchall()
        history = pd.DataFrame([dict(row) for row in historical_rows])
        if history.empty:
            total, yes = 0, 0
        else:
            history["weekday"] = pd.to_datetime(history["observed_on"]).dt.weekday
            matching = history[(history["weekday"] == weekday) & (history["time_slot"] == slot)]
            total, yes = int(len(matching)), int(matching["was_available"].sum())
    else:
        hist = db.execute("""SELECT COUNT(*) AS total, COALESCE(SUM(was_available),0) AS yes
            FROM observations WHERE space_id=? AND time_slot=?
            AND CAST(strftime('%w', observed_on) AS INTEGER)=?""",
            (space_id, slot, sqlite_weekday)).fetchone()
        total, yes = hist["total"], hist["yes"]
    probability = yes / total if total else None
    return {
        "current_available": current_available,
        "session": occupied_session["title"] if occupied_session else None,
        "available_computers": available_computers,
        "total_computers": len(computers),
        "unknown_computers": sum(status == "unknown" for status in computer_statuses),
        "probability": probability,
        "observations": total,
    }


@app.route("/")
def dashboard():
    db = get_db()
    spaces = db.execute("SELECT * FROM spaces ORDER BY kind DESC,name").fetchall()
    weekday = request.args.get("weekday", default=datetime.now().weekday(), type=int)
    slot = request.args.get("slot", default="11:00")
    # Availability can be checked at any minute during campus hours.
    try:
        parsed_slot = datetime.strptime(slot, "%H:%M").time()
        if not datetime.strptime("07:00", "%H:%M").time() <= parsed_slot <= datetime.strptime("22:00", "%H:%M").time():
            raise ValueError
    except ValueError:
        slot = "11:00"
    rows = []
    for space in spaces:
        rows.append({"space": space, **space_availability(space, weekday, slot)})
    eligible = [row for row in rows if row["current_available"]]
    recommendation = max(eligible, key=lambda row: (
        row["probability"] if row["probability"] is not None else -1,
        row["available_computers"])) if eligible else None
    computers = db.execute("SELECT * FROM computers ORDER BY space_id,name").fetchall()
    all_sets = {"available": set(), "occupied": set(), "maintenance": set(), "unknown": set()}
    for computer in computers:
        all_sets[effective_computer_status(computer)].add(computer["id"])
    # These sets partition the universe of registered computers.
    counts = {status: len(items) for status, items in all_sets.items()}
    return render_template("dashboard.html", rows=rows, weekday=weekday, slot=slot,
                           counts=counts, total_computers=len(computers),
                           recommendation=recommendation,
                           weekdays=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])


def simulate_lab_queue(computer_count, arrivals_per_hour, average_session_minutes,
                       simulation_minutes, replications):
    """Run a reproducible M/M/c-style queue simulation with SimPy and NumPy."""
    replications_data = []
    for replication in range(replications):
        rng = np.random.default_rng(2026 + replication)
        environment = simpy.Environment()
        computers = simpy.Resource(environment, capacity=computer_count)
        wait_times = []

        def student_request():
            arrived_at = environment.now
            with computers.request() as request_event:
                yield request_event
                wait_times.append(environment.now - arrived_at)
                duration = max(0.1, float(rng.exponential(average_session_minutes)))
                yield environment.timeout(duration)

        def arrivals():
            while True:
                gap = float(rng.exponential(60 / arrivals_per_hour))
                yield environment.timeout(gap)
                if environment.now >= simulation_minutes:
                    return
                environment.process(student_request())

        environment.process(arrivals())
        environment.run()
        replications_data.append({
            "requests": len(wait_times),
            "average_wait": float(np.mean(wait_times)) if wait_times else 0.0,
            "queue_rate": (sum(wait > 0.01 for wait in wait_times) / len(wait_times)) if wait_times else 0.0,
            "longest_wait": max(wait_times, default=0.0),
        })

    results = pd.DataFrame(replications_data)
    return {
        "average_requests": float(results["requests"].mean()),
        "average_wait": float(results["average_wait"].mean()),
        "queue_rate": float(results["queue_rate"].mean()),
        "p95_wait": float(results["longest_wait"].quantile(0.95)),
        "replications": replications,
    }


@app.route("/simulation", methods=["GET", "POST"])
def lab_simulator():
    db = get_db()
    labs = db.execute("SELECT * FROM spaces WHERE kind='lab' ORDER BY name").fetchall()
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    def int_value(field, default):
        raw_value = request.values.get(field)
        if raw_value is None or raw_value == "":
            return default
        try:
            return int(raw_value)
        except ValueError:
            return None

    values = {
        "lab_id": int_value("lab_id", labs[0]["id"] if labs else 0),
        "weekday": int_value("weekday", datetime.now().weekday()),
        "slot": request.values.get("slot", "11:00"),
        "arrivals_per_hour": int_value("arrivals_per_hour", 18),
        "average_session_minutes": int_value("average_session_minutes", 30),
        "simulation_minutes": int_value("simulation_minutes", 60),
        "replications": int_value("replications", 100),
    }
    selected_lab = next((lab for lab in labs if lab["id"] == values["lab_id"]), None)
    capacity = 0
    analysis = None
    error = None
    if selected_lab:
        try:
            datetime.strptime(values["slot"], "%H:%M")
            slot_valid = True
        except (TypeError, ValueError):
            slot_valid = False
        if slot_valid and 0 <= values["weekday"] <= 6:
            availability = space_availability(selected_lab, values["weekday"], values["slot"])
            capacity = availability["available_computers"] if not availability["session"] else 0
    if request.method == "POST":
        if np is None or pd is None or simpy is None:
            error = "Install the project libraries with: pip install -r requirements.txt"
        elif (not selected_lab or values["weekday"] is None or not 0 <= values["weekday"] <= 6 or not slot_valid
              or any(values[field] is None for field in ("arrivals_per_hour", "average_session_minutes", "simulation_minutes", "replications"))
              or not 1 <= values["arrivals_per_hour"] <= 60
              or not 5 <= values["average_session_minutes"] <= 180
              or not 30 <= values["simulation_minutes"] <= 240
              or not 10 <= values["replications"] <= 200):
            error = "Choose a lab and keep each value within the limits shown on the form."
        elif capacity <= 0:
            error = "No computers are currently reported available for this lab and time. Update its status or choose another lab/time."
        else:
            analysis = simulate_lab_queue(
                capacity, values["arrivals_per_hour"], values["average_session_minutes"],
                values["simulation_minutes"], values["replications"],
            )
    dependencies_ready = np is not None and pd is not None and simpy is not None
    return render_template("simulation.html", labs=labs, weekdays=weekdays, values=values,
                           selected_lab=selected_lab, capacity=capacity, analysis=analysis,
                           error=error, dependencies_ready=dependencies_ready)


@app.route("/sets")
def set_explorer():
    db = get_db()
    computer_rows = db.execute("""SELECT c.id,c.name,c.status,c.status_source,c.last_seen_at,s.name AS lab_name
        FROM computers c JOIN spaces s ON s.id=c.space_id ORDER BY s.name,c.name""").fetchall()
    # Use primary keys as set elements: computer names such as PC-01 repeat across labs.
    statuses = {name: {row["id"] for row in computer_rows
                       if effective_computer_status(row) == name}
                for name in ("available", "occupied", "maintenance", "unknown")}
    labels = {row["id"]: f"{row['lab_name']} · {row['name']}" for row in computer_rows}
    selected = request.args.get("status", "available")
    selected = selected if selected in statuses else "available"
    operation = request.args.get("operation", "single")
    other = request.args.get("other", "occupied")
    if other not in statuses:
        other = "occupied"
    if operation == "union":
        result = statuses[selected] | statuses[other]
        label = f"{selected.title()} ∪ {other.title()}"
    elif operation == "intersection":
        result = statuses[selected] & statuses[other]
        label = f"{selected.title()} ∩ {other.title()}"
    elif operation == "difference":
        result = statuses[selected] - statuses[other]
        label = f"{selected.title()} − {other.title()}"
    elif operation == "complement":
        universe = {row["id"] for row in computer_rows}
        result = universe - statuses[selected]
        label = f"Complement of {selected.title()}"
    else:
        result, label = statuses[selected], selected.title()
    return render_template("sets.html", statuses=statuses, selected=selected, other=other,
                           operation=operation, result=sorted(labels[item] for item in result), label=label,
                           universe_count=len(computer_rows))


@app.route("/computers", methods=["GET", "POST"])
def manage_computers():
    db = get_db()
    allowed_statuses = {"available", "occupied", "maintenance"}
    if request.method == "POST":
        computer_id = request.form.get("computer_id", type=int)
        status = request.form.get("status", "")
        if status not in allowed_statuses:
            flash("Choose a valid computer status.", "error")
        else:
            cursor = db.execute("UPDATE computers SET status=?,status_source='manual',last_seen_at=NULL WHERE id=?",
                                (status, computer_id))
            if cursor.rowcount:
                db.commit()
                flash("Computer status updated.", "success")
            else:
                flash("Computer not found.", "error")
        return redirect(url_for("manage_computers"))
    computer_rows = db.execute("""SELECT c.id,c.name,c.status,c.status_source,c.last_seen_at,s.name AS lab_name
        FROM computers c JOIN spaces s ON s.id=c.space_id
        WHERE s.kind='lab' ORDER BY s.name,c.name""").fetchall()
    computers = []
    for row in computer_rows:
        item = dict(row)
        item["effective_status"] = effective_computer_status(row)
        item["source_label"] = "Automatic collector" if row["status_source"] == "collector" else "Manual update"
        computers.append(item)
    return render_template("computers.html", computers=computers,
                           statuses=["available", "occupied", "maintenance"])


@app.route("/admin", methods=["GET", "POST"])
def admin_portal():
    db = get_db()
    configured_password = os.environ.get("ADMIN_PASSWORD", "")
    csrf_token = session.setdefault("admin_csrf_token", secrets.token_urlsafe(32))
    if request.method == "POST":
        if not compare_digest(request.form.get("csrf_token", ""), csrf_token):
            flash("The form expired. Reload the admin page and try again.", "error")
            return redirect(url_for("admin_portal"))
        action = request.form.get("action")
        if action == "login":
            submitted_password = request.form.get("password", "")
            if not configured_password:
                flash("Admin access is not configured. Set ADMIN_PASSWORD before starting the app.", "error")
            elif compare_digest(submitted_password, configured_password):
                session["admin_authenticated"] = True
                session["admin_csrf_token"] = secrets.token_urlsafe(32)
                flash("Admin access granted.", "success")
            else:
                flash("Incorrect admin password.", "error")
            return redirect(url_for("admin_portal"))

        if action == "demo_login":
            if app.config["LOCAL_DEMO_MODE"] and not configured_password:
                session["admin_authenticated"] = True
                session["admin_demo"] = True
                session["admin_csrf_token"] = secrets.token_urlsafe(32)
                flash("Local demo admin session started. Status changes are saved in the demo database.", "success")
            else:
                flash("Local demo admin sign-in is disabled when deployed or when an admin password is configured.", "error")
            return redirect(url_for("admin_portal"))

        if action == "logout":
            session.pop("admin_authenticated", None)
            session.pop("admin_demo", None)
            session["admin_csrf_token"] = secrets.token_urlsafe(32)
            flash("Admin signed out.", "success")
            return redirect(url_for("admin_portal"))

        if not session.get("admin_authenticated"):
            flash("Sign in as an administrator first.", "error")
            return redirect(url_for("admin_portal"))
        computer_id = request.form.get("computer_id", type=int)
        status = request.form.get("status", "")
        if status not in {"available", "occupied", "maintenance"}:
            flash("Choose Available, In use, or Under maintenance.", "error")
        else:
            cursor = db.execute("""UPDATE computers SET status=?,status_source='manual',last_seen_at=NULL
                WHERE id=? AND space_id IN (SELECT id FROM spaces WHERE kind='lab')""",
                (status, computer_id))
            if cursor.rowcount:
                db.commit()
                flash("Computer status saved. The change appears on Availability.", "success")
            else:
                flash("Lab computer not found.", "error")
        return redirect(url_for("admin_portal"))

    computer_rows = db.execute("""SELECT c.id,c.name,c.status,c.status_source,c.last_seen_at,
        s.name AS lab_name FROM computers c JOIN spaces s ON s.id=c.space_id
        WHERE s.kind='lab' ORDER BY s.name,c.name""").fetchall()
    computers = [dict(row, effective_status=effective_computer_status(row)) for row in computer_rows]
    return render_template("admin_portal.html", computers=computers,
                           admin_authenticated=session.get("admin_authenticated", False),
                           admin_configured=bool(configured_password),
                           local_demo_mode=app.config["LOCAL_DEMO_MODE"],
                           admin_demo=session.get("admin_demo", False), csrf_token=csrf_token)


@app.route("/api/computer-status", methods=["POST"])
def receive_computer_status():
    """Receive a minimal status heartbeat from an authorized lab collector."""
    expected_token = os.environ.get("COMPUTER_STATUS_TOKEN", "")
    supplied_token = request.headers.get("Authorization", "")
    if not expected_token or not compare_digest(supplied_token, f"Bearer {expected_token}"):
        return {"error": "Collector authentication is not configured or is invalid."}, 401
    payload = request.get_json(silent=True) or {}
    computer_id = payload.get("computer_id")
    status = payload.get("status")
    if isinstance(computer_id, bool) or not isinstance(computer_id, int) or computer_id < 1:
        return {"error": "computer_id must be a positive integer."}, 400
    if status not in {"available", "occupied"}:
        return {"error": "status must be available or occupied."}, 400
    db = get_db()
    computer = db.execute("""SELECT c.id,c.status,s.kind FROM computers c
        JOIN spaces s ON s.id=c.space_id WHERE c.id=?""", (computer_id,)).fetchone()
    if not computer or computer["kind"] != "lab":
        return {"error": "Lab computer not found."}, 404
    last_seen = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if computer["status"] == "maintenance":
        db.execute("UPDATE computers SET last_seen_at=? WHERE id=?", (last_seen, computer_id))
        effective_status = "maintenance"
    else:
        db.execute("""UPDATE computers SET status=?,status_source='collector',last_seen_at=?
            WHERE id=?""", (status, last_seen, computer_id))
        effective_status = status
    db.commit()
    return {"ok": True, "computer_id": computer_id, "status": effective_status,
            "last_seen_at": last_seen}, 200


@app.route("/student-login")
def student_login():
    """Offer real college SSO and a visibly unverified local presentation sign-in."""
    return render_template(
        "student_login.html",
        student=session.get("student_profile"),
        email_domain=STUDENT_EMAIL_DOMAIN,
        local_demo_mode=app.config["LOCAL_DEMO_MODE"],
        authlib_available=oauth is not None,
        google_ready=bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET")),
        microsoft_ready=bool(os.environ.get("MICROSOFT_CLIENT_ID") and os.environ.get("MICROSOFT_CLIENT_SECRET")),
    )


@app.route("/student-demo-login", methods=["POST"])
def student_demo_login():
    if not app.config["LOCAL_DEMO_MODE"]:
        return "Local demo sign-in is disabled.", 404
    name = request.form.get("name", "").strip()
    registration_id = request.form.get("registration_id", "").strip()
    email = request.form.get("college_email", "").strip().lower()
    if (not name or len(name) > 100 or not registration_id or len(registration_id) > 40
            or len(email) > 254 or "@" not in email
            or email.rsplit("@", 1)[1] != STUDENT_EMAIL_DOMAIN):
        flash(f"Enter your name, registration ID, and a college email ending in @{STUDENT_EMAIL_DOMAIN}.", "error")
        return redirect(url_for("student_login"))
    session.clear()
    session["student_profile"] = {
        "name": name,
        "registration_id": registration_id,
        "college_email": email,
        "provider": "local demo",
        "verified": False,
    }
    flash("Demo student session started. The details were not verified.", "success")
    return redirect(url_for("dashboard"))


@app.route("/student-login/<provider>")
def student_login_start(provider):
    if provider not in {"google", "microsoft"}:
        return "Unknown sign-in provider.", 404
    if oauth is None:
        flash("Google/Microsoft sign-in needs Authlib. Install the project requirements first.", "error")
        return redirect(url_for("student_login"))
    if not (os.environ.get(f"{provider.upper()}_CLIENT_ID")
            and os.environ.get(f"{provider.upper()}_CLIENT_SECRET")):
        flash(f"{provider.title()} sign-in is not configured yet. See the SSO setup in README.md.", "error")
        return redirect(url_for("student_login"))
    client = oauth.create_client(provider)
    callback = url_for("student_login_callback", provider=provider, _external=True)
    return client.authorize_redirect(callback)


@app.route("/student-login/<provider>/callback")
def student_login_callback(provider):
    if provider not in {"google", "microsoft"} or oauth is None:
        return redirect(url_for("student_login"))
    try:
        token = oauth.create_client(provider).authorize_access_token()
        claims = token.get("userinfo") or {}
    except Exception:
        app.logger.exception("Student SSO callback failed")
        flash("Sign-in could not be verified. Please try again or contact the project administrator.", "error")
        return redirect(url_for("student_login"))

    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if "@" not in email or email.rsplit("@", 1)[1] != STUDENT_EMAIL_DOMAIN:
        flash(f"Use your college account ending in @{STUDENT_EMAIL_DOMAIN}.", "error")
        return redirect(url_for("student_login"))
    if provider == "google" and claims.get("email_verified") is not True:
        flash("Google did not confirm that this email address is verified.", "error")
        return redirect(url_for("student_login"))

    session.clear()
    session["student_profile"] = {
        "name": claims.get("name") or email.split("@", 1)[0],
        "college_email": email,
        "provider": provider,
        "verified": True,
    }
    flash("College account verified successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/student-logout", methods=["POST"])
def student_logout():
    session.clear()
    flash("Student account signed out.", "success")
    return redirect(url_for("student_login"))


@app.route("/spaces", methods=["GET", "POST"])
def manage_spaces():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        kind = request.form.get("kind", "")
        location = request.form.get("location", "").strip()
        computer_count = request.form.get("computer_count", default=0, type=int)
        if (not name or len(name) > 80 or not location or len(location) > 120
                or kind not in {"classroom", "lab"}
                or computer_count is None or not 0 <= computer_count <= 200
                or (kind == "classroom" and computer_count != 0)):
            flash("Enter a name and location, choose a valid type, and set a valid computer count for labs.", "error")
        else:
            try:
                cursor = db.execute("INSERT INTO spaces(name,kind,location,capacity) VALUES(?,?,?,?)",
                                    (name, kind, location, 0))
                space_id = cursor.lastrowid
                if kind == "lab":
                    db.executemany("INSERT INTO computers(space_id,name,status) VALUES(?,?,?)",
                                   [(space_id, f"PC-{number:02}", "available")
                                    for number in range(1, computer_count + 1)])
                db.commit()
                flash("Space added. Lab computers were registered as available.", "success")
            except sqlite3.IntegrityError:
                db.rollback()
                flash("A space with that name already exists.", "error")
        return redirect(url_for("manage_spaces"))
    spaces = db.execute("""SELECT s.*,COUNT(c.id) AS computer_count FROM spaces s
        LEFT JOIN computers c ON c.space_id=s.id GROUP BY s.id ORDER BY s.kind,s.name""").fetchall()
    return render_template("spaces.html", spaces=spaces)


@app.route("/schedule", methods=["GET", "POST"])
def manage_schedule():
    db = get_db()
    if request.method == "POST":
        space_id = request.form.get("space_id", type=int)
        weekday = request.form.get("weekday", type=int)
        title = request.form.get("title", "").strip()
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")
        try:
            datetime.strptime(start_time, "%H:%M")
            datetime.strptime(end_time, "%H:%M")
            if not title or weekday is None or not 0 <= weekday <= 6 or start_time >= end_time:
                raise ValueError
            overlap = db.execute("""SELECT 1 FROM sessions
                WHERE space_id=? AND weekday=? AND start_time < ? AND end_time > ? LIMIT 1""",
                                 (space_id, weekday, end_time, start_time)).fetchone()
            if overlap:
                flash("That time overlaps an existing session for this space.", "error")
            else:
                db.execute("""INSERT INTO sessions(space_id,weekday,start_time,end_time,title)
                    VALUES(?,?,?,?,?)""", (space_id, weekday, start_time, end_time, title))
                db.commit()
                flash("Timetable session added.", "success")
        except (ValueError, TypeError, sqlite3.IntegrityError):
            flash("Enter a title, valid day, and end time later than the start time.", "error")
        return redirect(url_for("manage_schedule"))
    spaces = db.execute("SELECT id,name,kind FROM spaces ORDER BY name").fetchall()
    sessions = db.execute("""SELECT t.*,s.name AS space_name FROM sessions t
        JOIN spaces s ON s.id=t.space_id ORDER BY t.weekday,t.start_time,s.name""").fetchall()
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return render_template("schedule.html", spaces=spaces, sessions=sessions, weekdays=weekdays)


@app.route("/usage", methods=["GET", "POST"])
def usage_history():
    db = get_db()
    if request.method == "POST":
        computer_id = request.form.get("computer_id", type=int)
        usage_date = request.form.get("usage_date", "")
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")
        try:
            date.fromisoformat(usage_date)
            start = datetime.strptime(start_time, "%H:%M")
            end = datetime.strptime(end_time, "%H:%M")
            if start >= end:
                raise ValueError
            overlap = db.execute("""SELECT 1 FROM usage_records
                WHERE computer_id=? AND usage_date=? AND start_time < ? AND end_time > ? LIMIT 1""",
                                 (computer_id, usage_date, end_time, start_time)).fetchone()
            if overlap:
                flash("That computer already has a usage record overlapping this time.", "error")
            else:
                db.execute("""INSERT INTO usage_records(computer_id,usage_date,start_time,end_time)
                    VALUES(?,?,?,?)""", (computer_id, usage_date, start_time, end_time))
                db.commit()
                flash("Usage record saved.", "success")
        except (ValueError, TypeError, sqlite3.IntegrityError):
            flash("Enter a valid computer, date, and end time later than the start time.", "error")
        return redirect(url_for("usage_history"))
    computers = db.execute("""SELECT c.id,c.name,s.name AS lab_name FROM computers c
        JOIN spaces s ON s.id=c.space_id ORDER BY s.name,c.name""").fetchall()
    records = db.execute("""SELECT u.*,c.name AS computer_name,s.name AS lab_name
        FROM usage_records u JOIN computers c ON c.id=u.computer_id
        JOIN spaces s ON s.id=c.space_id ORDER BY u.usage_date DESC,u.start_time DESC LIMIT 50""").fetchall()
    usage_rows = []
    for record in records:
        start = datetime.strptime(record["start_time"], "%H:%M")
        end = datetime.strptime(record["end_time"], "%H:%M")
        usage_rows.append({**dict(record), "duration_minutes": int((end - start).total_seconds() // 60)})
    return render_template("usage.html", computers=computers, records=usage_rows,
                           today=date.today().isoformat())


@app.route("/observations", methods=["GET", "POST"])
def observations():
    db = get_db()
    if request.method == "POST":
        space_id = request.form.get("space_id", type=int)
        observed_on = request.form.get("observed_on", "")
        slot = request.form.get("time_slot", "")
        available = request.form.get("was_available") == "1"
        try:
            date.fromisoformat(observed_on)
            parsed_slot = datetime.strptime(slot, "%H:%M").time()
            if not datetime.strptime("07:00", "%H:%M").time() <= parsed_slot <= datetime.strptime("22:00", "%H:%M").time():
                raise ValueError
            db.execute("INSERT INTO observations(space_id,observed_on,time_slot,was_available) VALUES(?,?,?,?)",
                       (space_id, observed_on, slot, int(available)))
            db.commit()
            flash("Observation saved. The historical estimate will use it.", "success")
        except (ValueError, TypeError, sqlite3.IntegrityError):
            flash("Please enter a valid date, space, and time slot.", "error")
        return redirect(url_for("observations"))
    spaces = db.execute("SELECT * FROM spaces ORDER BY name").fetchall()
    recent = db.execute("""SELECT o.*,s.name AS space_name FROM observations o JOIN spaces s ON s.id=o.space_id
        ORDER BY o.observed_on DESC,o.id DESC LIMIT 15""").fetchall()
    return render_template("observations.html", spaces=spaces, recent=recent,
                           today=date.today().isoformat())


if __name__ == "__main__":
    initialize_database()
    app.run(debug=False)
