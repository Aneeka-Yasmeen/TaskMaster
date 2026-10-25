import unittest
from datetime import datetime

from statetrace import reminders as R
from statetrace.store import Store

NOW = datetime(2026, 10, 9, 12, 0, 0)


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.store.append_event("p", "goal", "note", occurred_at="2026-10-09T09:00:00")

    def tearDown(self):
        self.store.close()

    def status(self, mid):
        return next(m for m in R.milestones_with_status(self.store, "p", NOW) if m["id"] == mid)

    def test_assessment_states_reasons_not_probabilities(self):
        overdue = self.store.add_milestone("p", "Tapeout", "2026-10-08T17:00")
        soon = self.store.add_milestone("p", "Review", "2026-10-10T17:00")
        later = self.store.add_milestone("p", "Demo", "2026-11-30T17:00")
        self.assertEqual(self.status(overdue["id"])["state"], "overdue")
        self.assertIn("Overdue by", self.status(overdue["id"])["reasons"][0])
        self.assertEqual(self.status(soon["id"])["state"], "due_soon")
        self.assertFalse(self.status(later["id"])["at_risk"])

    def test_inferred_dates_need_confirmation_and_never_remind(self):
        m = self.store.add_milestone("p", "Board bring-up", "2026-10-09T13:00", origin="inferred", confirmed=False)
        self.assertEqual(self.status(m["id"])["state"], "unconfirmed")
        self.assertEqual(R.generate_notices(self.store, NOW), [])
        self.store.update_milestone(m["id"], confirmed=True)
        self.assertEqual(len(R.generate_notices(self.store, NOW)), 1)

    def test_reminders_are_deduplicated_and_rearm_on_reschedule(self):
        m = self.store.add_milestone("p", "Review", "2026-10-10T10:00", reminders=[1440, 60])
        self.assertEqual(len(R.generate_notices(self.store, NOW)), 1)   # 22 h left: the 1-day reminder
        self.assertEqual(R.generate_notices(self.store, NOW), [])        # same issue not reported again
        self.store.update_milestone(m["id"], due_at="2026-10-09T12:30")  # rescheduled closer
        self.assertEqual(len(R.generate_notices(self.store, NOW)), 1)
        self.store.update_milestone(m["id"], status="done")
        self.assertEqual(R.generate_notices(self.store, datetime(2026, 10, 12)), [])

    def test_opting_out_of_reminders_silences_the_milestone(self):
        self.store.add_milestone("p", "Quiet", "2026-10-09T12:30", reminders=[-1])
        self.store.add_milestone("p", "Defaulted", "2026-10-09T12:30", reminders=[])
        self.assertEqual([k.split(":")[1] for k in R.generate_notices(self.store, NOW)], ["2"])

    def test_quiet_hours_and_disable(self):
        R.set_prefs(self.store, {"quiet_start": "22:00", "quiet_end": "08:00"})
        self.assertTrue(R.notices_for_delivery(self.store, datetime(2026, 10, 9, 23, 30))["quiet"])
        self.assertFalse(R.notices_for_delivery(self.store, datetime(2026, 10, 9, 14, 0))["quiet"])
        R.set_prefs(self.store, {"enabled": False})
        self.store.add_milestone("p", "x", "2026-10-09T12:30")
        self.assertEqual(R.generate_notices(self.store, NOW), [])
        with self.assertRaises(ValueError):
            R.set_prefs(self.store, {"quiet_start": "25:99"})

    def test_blocked_project_flags_nearby_milestone_with_reason(self):
        from statetrace.schema import empty_state
        from statetrace.validator import apply_operations
        ev = self.store.get_event("p", "E1")
        st, _ = apply_operations(empty_state("p"), [{"op": "ADD", "field": "current_blocker", "value": "AXI fails"}],
                                 ev, {"E1": ev})
        self.store.save_state(st)
        m = self.store.add_milestone("p", "Demo", "2026-10-14T17:00")
        s = self.status(m["id"])
        self.assertTrue(s["at_risk"])
        self.assertIn("Project is blocked: AXI fails", s["reasons"])


if __name__ == "__main__":
    unittest.main()
