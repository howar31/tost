import tempfile
import unittest
from pathlib import Path

from app.cli import extract_summary, run_fetch
from app.store import Store

FIXTURE_ENTRY = {
    "order": {
        "referenceNumber": "RN114455",
        "orderStatus": "BOOKED",
        "modelCode": "my",
        "vin": None,
        "locale": "zh-TW",
        "mktOptions": "APBS,MTY13,PPSW",
    },
    "details": {
        "tasks": {
            "scheduling": {
                "deliveryWindowDisplay": "2026年8月15日 - 2026年8月30日",
                "deliveryAppointmentDate": None,
                "deliveryAddressTitle": "Tesla Delivery Center",
            },
            "registration": {
                "orderDetails": {
                    "vehicleOdometer": 12.5,
                    "vehicleOdometerType": "KM",
                    "orderBookedDate": "2026-06-01T08:00:00Z",
                }
            },
            "deliveryDetails": {
                "regData": {"orderDetails": {"vin": "LRW3E7EBXPC123456"}}
            },
            "finalPayment": {"data": {"etaToDeliveryCenter": "2026-08-10"}},
        }
    },
}


class TestExtractSummary(unittest.TestCase):
    def test_full_fixture_summary(self):
        s = extract_summary("RN114455", FIXTURE_ENTRY)
        self.assertEqual(s["order_id"], "RN114455")
        self.assertEqual(s["status"], "BOOKED")
        self.assertEqual(s["model"], "Model Y")
        self.assertEqual(s["vin"], "LRW3E7EBXPC123456")
        self.assertEqual(s["delivery_window"], "2026年8月15日 - 2026年8月30日")
        self.assertEqual(s["delivery_center"], "Tesla Delivery Center")
        self.assertEqual(s["eta_to_delivery_center"], "2026-08-10")
        self.assertEqual(s["odometer"], "12.5 KM")
        self.assertEqual(s["ordered_at"], "2026-06-01T08:00:00Z")

    def test_empty_entry_yields_na_fields_not_crash(self):
        s = extract_summary("RN1", {"order": {}, "details": {}})
        self.assertEqual(s["order_id"], "RN1")
        self.assertIsNone(s["vin"])
        self.assertIsNone(s["delivery_window"])

    def test_vin_falls_back_to_order_vin(self):
        entry = {"order": {"vin": "VIN999", "modelCode": "m3"}, "details": {}}
        s = extract_summary("RN1", entry)
        self.assertEqual(s["vin"], "VIN999")
        self.assertEqual(s["model"], "Model 3")


class TestExtractMilestones(unittest.TestCase):
    def test_registration_started_on_extracted(self):
        snap = {"RN1": {"order": {}, "details": {"tasks": {"registration": {
            "regData": {"startedOn": "2026-07-02T12:45:10", "startedBy": "CUSTOMER"}}}}}}
        from app.cli import extract_milestones
        events = extract_milestones(snap)
        self.assertEqual(events, [{
            "op": "milestone", "order": "RN1",
            "key": "registration.startedOn",
            "ts": "2026-07-02T12:45:10",
            "new": "2026-07-02T12:45:10",
        }])

    def test_missing_fields_yield_nothing(self):
        from app.cli import extract_milestones
        self.assertEqual(extract_milestones({"RN1": {"order": {}, "details": {}}}), [])


class TestRunFetch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "data")

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_fetch_discovers_and_persists(self):
        snap = {"RN1": {"order": {"orderStatus": "BOOKED"}, "details": {}}}
        events = run_fetch(self.store, lambda: snap, now_iso="t1")
        self.assertEqual([e["op"] for e in events], ["discovered"])
        self.assertEqual(self.store.load_latest(), snap)
        self.assertEqual(self.store.read_history()[0]["op"], "discovered")

    def test_fetch_pipeline_serialized_via_lock_file(self):
        # concurrent manual fetch vs launchd agent must not interleave writes
        run_fetch(self.store, lambda: {}, now_iso="t1")
        self.assertTrue((Path(self._tmp.name) / "data" / ".lock").exists())

    def test_second_fetch_records_change(self):
        run_fetch(
            self.store,
            lambda: {"RN1": {"order": {"orderStatus": "BOOKED"}, "details": {}}},
            now_iso="t1",
        )
        events = run_fetch(
            self.store,
            lambda: {"RN1": {"order": {"orderStatus": "DELIVERED"}, "details": {}}},
            now_iso="t2",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["op"], "changed")
        self.assertEqual(events[0]["key"], "order.orderStatus")
        history = self.store.read_history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["ts"], "t2")

    def test_no_change_returns_no_events_and_no_history(self):
        snap = {"RN1": {"order": {"orderStatus": "BOOKED"}, "details": {}}}
        run_fetch(self.store, lambda: snap, now_iso="t1")
        events = run_fetch(self.store, lambda: dict(snap), now_iso="t2")
        self.assertEqual(events, [])
        self.assertEqual(len(self.store.read_history()), 1)

    def test_every_fetch_logged_as_observation(self):
        snap = {"RN1": {"order": {"orderStatus": "BOOKED"}, "details": {}}}
        run_fetch(self.store, lambda: snap, now_iso="2026-07-30T10:00:00Z")
        run_fetch(self.store, lambda: dict(snap), now_iso="2026-07-30T10:30:00Z")
        obs = self.store.read_observations()
        self.assertEqual([o["ts"] for o in obs],
                         ["2026-07-30T10:00:00Z", "2026-07-30T10:30:00Z"])
        self.assertTrue(obs[0]["archive"])       # first fetch archived
        self.assertIsNone(obs[1]["archive"])     # identical content deduped
        self.assertEqual(obs[0]["sha"], obs[1]["sha"])

    def test_milestone_backfilled_once_with_historic_ts(self):
        snap = {"RN1": {"order": {}, "details": {"tasks": {"registration": {
            "regData": {"startedOn": "2026-07-02T12:45:10"}}}}}}
        run_fetch(self.store, lambda: snap, now_iso="2026-07-30T10:00:00Z")
        run_fetch(self.store, lambda: dict(snap), now_iso="2026-07-30T11:00:00Z")
        milestones = [e for e in self.store.read_history() if e["op"] == "milestone"]
        self.assertEqual(len(milestones), 1)
        self.assertEqual(milestones[0]["ts"], "2026-07-02T12:45:10")

    def test_latest_updated_even_when_only_ignored_keys_change(self):
        run_fetch(
            self.store,
            lambda: {"RN1": {"order": {}, "details": {"strings": {"a": 1}}}},
            now_iso="t1",
        )
        run_fetch(
            self.store,
            lambda: {"RN1": {"order": {}, "details": {"strings": {"a": 2}}}},
            now_iso="t2",
        )
        self.assertEqual(
            self.store.load_latest()["RN1"]["details"]["strings"]["a"], 2
        )
        self.assertEqual(self.store.load_fetched_at(), "t2")


if __name__ == "__main__":
    unittest.main()
