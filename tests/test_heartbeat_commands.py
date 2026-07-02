import datetime
import tempfile
import unittest
from pathlib import Path

from main.commands import heartbeat_commands as heartbeat


class HeartbeatCommandsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_file = heartbeat._HEARTBEAT_FILE
        heartbeat._HEARTBEAT_FILE = Path(self.tmp.name) / "heartbeat_tasks.json"
        heartbeat._heartbeat_tasks = []
        heartbeat._ROUTE_CMD_CB = None
        heartbeat._heartbeat_scheduler._last_mtime = 0.0
        heartbeat._heartbeat_scheduler.set_speak_callback(lambda _text: None)

    def tearDown(self):
        heartbeat._HEARTBEAT_FILE = self.original_file
        heartbeat._heartbeat_tasks = []
        heartbeat._ROUTE_CMD_CB = None
        self.tmp.cleanup()

    def test_replace_with_empty_list_clears_memory_and_file(self):
        heartbeat.replace_heartbeat_tasks([{
            "task_text": "first",
            "time": "12:00",
            "recurring": "daily",
        }])

        payload = heartbeat.replace_heartbeat_tasks([])

        self.assertEqual(payload, [])
        self.assertEqual(heartbeat.get_heartbeat_tasks(), [])
        self.assertEqual(heartbeat._HEARTBEAT_FILE.read_text(encoding="utf-8").strip(), "[]")

    def test_load_empty_file_clears_existing_in_memory_tasks(self):
        heartbeat._heartbeat_tasks = [
            heartbeat.HeartbeatTask("stale", "12:00", "daily", "2026-07-02-12-00-00")
        ]
        heartbeat._HEARTBEAT_FILE.write_text("[]", encoding="utf-8")

        heartbeat._load_heartbeat_tasks()

        self.assertEqual(heartbeat._heartbeat_tasks, [])

    def test_normalizes_legacy_and_invalid_task_fields(self):
        payload = heartbeat.replace_heartbeat_tasks([
            {
                "id": "same",
                "task_text": "  check weather  ",
                "time": "99:99",
                "recurring": "interval",
                "interval_minutes": 0,
                "created_at": "bad",
            },
            {
                "id": "same",
                "task_text": "second",
                "time": "8:5",
                "recurring": "unknown",
            },
        ])

        self.assertEqual(payload[0]["task_text"], "check weather")
        self.assertEqual(payload[0]["time"], "12:00")
        self.assertEqual(payload[0]["interval_minutes"], 1)
        self.assertEqual(payload[1]["time"], "08:05")
        self.assertEqual(payload[1]["recurring"], "daily")
        self.assertNotEqual(payload[0]["id"], payload[1]["id"])

    def test_rejects_non_list_payload(self):
        with self.assertRaises(ValueError):
            heartbeat.replace_heartbeat_tasks({"tasks": []})

    def test_tick_records_success_status(self):
        now = datetime.datetime.now()
        heartbeat.replace_heartbeat_tasks([{
            "task_text": "say hi",
            "time": now.strftime("%H:%M"),
            "recurring": "once",
            "target_date": now.strftime("%Y-%m-%d"),
        }])
        heartbeat.set_heartbeat_route_callback(lambda text: f"done {text}")

        heartbeat._heartbeat_scheduler._tick()
        task = heartbeat._heartbeat_tasks[0]

        self.assertFalse(task.enabled)
        self.assertEqual(task.last_status, "success")
        self.assertEqual(task.run_count, 1)
        self.assertIsNotNone(task.last_run)


if __name__ == "__main__":
    unittest.main()
