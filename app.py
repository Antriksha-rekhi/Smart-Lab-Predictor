"""Campus space availability demo: classrooms and lab computers."""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "campus_availability.db"
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-demo-key-change-me")


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
    """)
    if db.execute("SELECT COUNT(*) FROM spaces").fetchone()[0] == 0:
        seed_demo_data(db)
    db.commit()
    db.close()


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


def space_availability(space, weekday, slot):
    """Return current status, schedule conflicts, and historic empirical probability."""
    db = get_db()
    space_id = space["id"]
    occupied_session = db.execute("""SELECT title FROM sessions
        WHERE space_id=? AND weekday=? AND start_time<=? AND end_time>? LIMIT 1""",
        (space_id, weekday, slot, slot)).fetchone()
    computers = db.execute("SELECT status FROM computers WHERE space_id=?", (space_id,)).fetchall()
    available_computers = sum(row["status"] == "available" for row in computers)
    if space["kind"] == "lab":
        current_available = available_computers > 0 and occupied_session is None
    else:
        current_available = occupied_session is None
    # Python weekdays use Monday=0; SQLite strftime('%w') uses Sunday=0.
    sqlite_weekday = (weekday + 1) % 7
    hist = db.execute("""SELECT COUNT(*) AS total, COALESCE(SUM(was_available),0) AS yes
        FROM observations WHERE space_id=? AND time_slot=?
        AND CAST(strftime('%w', observed_on) AS INTEGER)=?""",
        (space_id, slot, sqlite_weekday)).fetchone()
    probability = hist["yes"] / hist["total"] if hist["total"] else None
    return {
        "current_available": current_available,
        "session": occupied_session["title"] if occupied_session else None,
        "available_computers": available_computers,
        "total_computers": len(computers),
        "probability": probability,
        "observations": hist["total"],
    }


@app.route("/")
def dashboard():
    db = get_db()
    spaces = db.execute("SELECT * FROM spaces ORDER BY kind DESC,name").fetchall()
    weekday = request.args.get("weekday", default=datetime.now().weekday(), type=int)
    slot = request.args.get("slot", default="11:00")
    rows = []
    for space in spaces:
        rows.append({"space": space, **space_availability(space, weekday, slot)})
    computers = db.execute("SELECT * FROM computers ORDER BY space_id,name").fetchall()
    all_sets = {"available": set(), "occupied": set(), "maintenance": set()}
    for computer in computers:
        all_sets[computer["status"]].add(computer["id"])
    # These sets partition the universe of registered computers.
    counts = {status: len(items) for status, items in all_sets.items()}
    return render_template("dashboard.html", rows=rows, weekday=weekday, slot=slot,
                           counts=counts, total_computers=len(computers),
                           timeslots=["09:00", "11:00", "13:00", "15:00"],
                           weekdays=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])


@app.route("/sets")
def set_explorer():
    db = get_db()
    computer_rows = db.execute("""SELECT c.id,c.name,c.status,s.name AS lab_name
        FROM computers c JOIN spaces s ON s.id=c.space_id ORDER BY s.name,c.name""").fetchall()
    # Use primary keys as set elements: computer names such as PC-01 repeat across labs.
    statuses = {name: {row["id"] for row in computer_rows if row["status"] == name}
                for name in ("available", "occupied", "maintenance")}
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
            cursor = db.execute("UPDATE computers SET status=? WHERE id=?", (status, computer_id))
            if cursor.rowcount:
                db.commit()
                flash("Computer status updated.", "success")
            else:
                flash("Computer not found.", "error")
        return redirect(url_for("manage_computers"))
    computers = db.execute("""SELECT c.id,c.name,c.status,s.name AS lab_name
        FROM computers c JOIN spaces s ON s.id=c.space_id
        WHERE s.kind='lab' ORDER BY s.name,c.name""").fetchall()
    return render_template("computers.html", computers=computers,
                           statuses=["available", "occupied", "maintenance"])


@app.route("/spaces", methods=["GET", "POST"])
def manage_spaces():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        kind = request.form.get("kind", "")
        location = request.form.get("location", "").strip()
        capacity = request.form.get("capacity", type=int)
        computer_count = request.form.get("computer_count", default=0, type=int)
        if (not name or len(name) > 80 or not location or len(location) > 120
                or kind not in {"classroom", "lab"} or capacity is None or not 0 <= capacity <= 500
                or computer_count is None or not 0 <= computer_count <= 200
                or (kind == "classroom" and computer_count != 0)):
            flash("Enter a name, location, valid type and capacity. Labs can have up to 200 computers.", "error")
        else:
            try:
                cursor = db.execute("INSERT INTO spaces(name,kind,location,capacity) VALUES(?,?,?,?)",
                                    (name, kind, location, capacity))
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
            if slot not in {"09:00", "11:00", "13:00", "15:00"}:
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
                           today=date.today().isoformat(), timeslots=["09:00", "11:00", "13:00", "15:00"])


initialize_database()

if __name__ == "__main__":
    app.run(debug=True)
