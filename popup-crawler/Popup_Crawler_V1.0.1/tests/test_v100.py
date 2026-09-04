from __future__ import annotations

import unittest
from pathlib import Path

from run_daily import VERSION
from storage.csv_export import CSV_FIELDS


ROOT = Path(__file__).resolve().parents[1]


class V100ReleaseTests(unittest.TestCase):
    def test_release_version_is_1_0_1(self):
        self.assertEqual("1.0.1", VERSION)
        self.assertEqual("1.0.1", (ROOT / "VERSION").read_text(encoding="utf-8").strip())

    def test_scheduled_runner_is_unattended(self):
        text = (ROOT / "run_daily_scheduled.bat").read_text(encoding="utf-8")
        self.assertIn("run_daily.py", text)
        self.assertNotIn("pause", text.lower())
        self.assertIn("logs\\scheduler", text)

    def test_schedule_installer_defaults_to_0800_and_daily(self):
        text = (ROOT / "scripts" / "install_daily_schedule.ps1").read_text(encoding="utf-8")
        self.assertIn('[string]$Time = "08:00"', text)
        self.assertIn("New-ScheduledTaskTrigger -Daily", text)
        self.assertIn("-StartWhenAvailable", text)
        self.assertIn("-WakeToRun", text)
        self.assertIn("run_daily_scheduled.bat", text)

    def test_backend_docs_exist(self):
        for name in (
            "BACKEND_HANDOFF.md",
            "CSV_SCHEMA.md",
            "INSTALL_AND_SCHEDULE.md",
            "OPERATIONS_RUNBOOK.md",
            "RELEASE_NOTES_v1.0.0.md",
        ):
            self.assertTrue((ROOT / "docs" / name).exists(), name)

    def test_backend_export_contract_is_explicit(self):
        self.assertEqual(38, len(CSV_FIELDS))
        self.assertEqual("popup_id", CSV_FIELDS[0])
        self.assertIn("source_refs", CSV_FIELDS)
        self.assertIn("last_verified_at", CSV_FIELDS)
        self.assertIn("operation_hours_raw", CSV_FIELDS)
        self.assertIn("operation_schedule", CSV_FIELDS)
        self.assertIn("today_day", CSV_FIELDS)
        self.assertIn("today_schedule", CSV_FIELDS)
        self.assertIn("today_opening_time", CSV_FIELDS)
        self.assertIn("today_closing_time", CSV_FIELDS)
        self.assertIn("today_closed", CSV_FIELDS)
        self.assertNotIn("opening_time", CSV_FIELDS)
        self.assertNotIn("closing_time", CSV_FIELDS)

    def test_runtime_artifacts_are_gitignored(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/", text)
        self.assertIn("output/", text)
        self.assertIn("logs/", text)


if __name__ == "__main__":
    unittest.main()
