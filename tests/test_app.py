import tempfile
import unittest
from pathlib import Path

import app as project


class SpacewiseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        project.DATABASE = Path(self.temp_dir.name) / "test.sqlite3"
        project.initialize_database()
        project.app.config.update(TESTING=True)
        self.client = project.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_all_pages_render_with_seed_data(self):
        for path in ("/", "/spaces", "/computers", "/schedule", "/usage", "/sets", "/observations"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        with project.app.app_context():
            db = project.get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM spaces").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM computers").fetchone()[0], 22)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0], 8)

    def test_set_intersection_uses_unique_computer_ids(self):
        with project.app.app_context():
            db = project.get_db()
            db.execute("""UPDATE computers SET status='occupied' WHERE name='PC-01'
                AND space_id=(SELECT id FROM spaces WHERE name='Computer Lab 1')""")
            db.execute("""UPDATE computers SET status='available' WHERE name='PC-01'
                AND space_id=(SELECT id FROM spaces WHERE name='Computer Lab 2')""")
            db.commit()
        page = self.client.get("/sets?status=available&operation=intersection&other=occupied")
        self.assertIn("0 members", page.get_data(as_text=True))

    def test_computer_status_can_be_updated(self):
        with project.app.app_context():
            db = project.get_db()
            computer_id = db.execute("SELECT id FROM computers WHERE name='PC-02' LIMIT 1").fetchone()[0]
        response = self.client.post("/computers", data={"computer_id": computer_id, "status": "maintenance"})
        self.assertEqual(response.status_code, 302)
        with project.app.app_context():
            status = project.get_db().execute("SELECT status FROM computers WHERE id=?", (computer_id,)).fetchone()[0]
        self.assertEqual(status, "maintenance")

    def test_timetable_rejects_overlaps_but_allows_adjacent_sessions(self):
        with project.app.app_context():
            db = project.get_db()
            space_id = db.execute("SELECT id FROM spaces WHERE name='Lecture Hall A'").fetchone()[0]
        conflict = self.client.post("/schedule", data={
            "space_id": space_id, "weekday": 0, "title": "Conflict", "start_time": "10:00", "end_time": "12:00"
        }, follow_redirects=True)
        self.assertIn("overlaps an existing session", conflict.get_data(as_text=True))
        adjacent = self.client.post("/schedule", data={
            "space_id": space_id, "weekday": 0, "title": "Adjacent", "start_time": "11:00", "end_time": "12:00"
        }, follow_redirects=True)
        self.assertIn("Timetable session added", adjacent.get_data(as_text=True))

    def test_usage_duration_and_conflict_validation(self):
        with project.app.app_context():
            db = project.get_db()
            computer_id = db.execute("""SELECT u.computer_id FROM usage_records u
                WHERE u.usage_date='2026-09-07' AND u.start_time='09:00' LIMIT 1""").fetchone()[0]
        conflict = self.client.post("/usage", data={
            "computer_id": computer_id, "usage_date": "2026-09-07", "start_time": "09:30", "end_time": "10:30"
        }, follow_redirects=True)
        self.assertIn("overlapping this time", conflict.get_data(as_text=True))
        adjacent = self.client.post("/usage", data={
            "computer_id": computer_id, "usage_date": "2026-09-07", "start_time": "10:00", "end_time": "11:00"
        }, follow_redirects=True)
        self.assertIn("Usage record saved", adjacent.get_data(as_text=True))
        self.assertIn("1h 0m", adjacent.get_data(as_text=True))

    def test_lab_creation_registers_related_computers(self):
        response = self.client.post("/spaces", data={
            "name": "Test Lab", "kind": "lab", "location": "Block Z", "capacity": "10", "computer_count": "3"
        }, follow_redirects=True)
        self.assertIn("Space added", response.get_data(as_text=True))
        with project.app.app_context():
            count = project.get_db().execute("""SELECT COUNT(*) FROM computers
                WHERE space_id=(SELECT id FROM spaces WHERE name='Test Lab')""").fetchone()[0]
        self.assertEqual(count, 3)

    def test_weekday_probability_and_no_observation_handling(self):
        with project.app.app_context():
            db = project.get_db()
            lab_id = db.execute("SELECT id FROM spaces WHERE name='Computer Lab 1'").fetchone()[0]
        response = self.client.post("/observations", data={
            "space_id": lab_id, "observed_on": "2026-11-19", "time_slot": "13:00", "was_available": "1"
        }, follow_redirects=True)
        self.assertIn("Observation saved", response.get_data(as_text=True))
        with project.app.test_request_context():
            db = project.get_db()
            lab = db.execute("SELECT * FROM spaces WHERE id=?", (lab_id,)).fetchone()
            estimate = project.space_availability(lab, 3, "13:00")
            self.assertEqual(estimate["observations"], 2)
            self.assertEqual(estimate["probability"], 0.5)
            db.execute("INSERT INTO spaces(name,kind,location,capacity) VALUES(?,?,?,?)",
                       ("No History", "classroom", "Block Y", 20))
            fresh = db.execute("SELECT * FROM spaces WHERE name='No History'").fetchone()
            estimate = project.space_availability(fresh, 3, "13:00")
            self.assertIsNone(estimate["probability"])
            self.assertEqual(estimate["observations"], 0)


if __name__ == "__main__":
    unittest.main()
