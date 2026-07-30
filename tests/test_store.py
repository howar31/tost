import json
import os
import tempfile
import unittest
from pathlib import Path

from app.store import Store


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name) / "data"
        self.store = Store(self.base)

    def tearDown(self):
        self._tmp.cleanup()


class TestLatestSnapshot(StoreTestCase):
    def test_load_latest_returns_empty_dict_when_missing(self):
        self.assertEqual(self.store.load_latest(), {})

    def test_save_then_load_round_trips(self):
        snap = {"RN1": {"order": {"a": 1}, "details": {}}}
        self.store.save_latest(snap, fetched_at="2026-07-30T10:00:00Z")
        self.assertEqual(self.store.load_latest(), snap)

    def test_fetched_at_stored_and_readable(self):
        self.store.save_latest({}, fetched_at="2026-07-30T10:00:00Z")
        self.assertEqual(self.store.load_fetched_at(), "2026-07-30T10:00:00Z")

    def test_latest_file_mode_is_600(self):
        self.store.save_latest({}, fetched_at="t")
        mode = os.stat(self.base / "latest.json").st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_base_dir_created_with_700(self):
        self.store.save_latest({}, fetched_at="t")
        mode = os.stat(self.base).st_mode & 0o777
        self.assertEqual(mode, 0o700)

    def test_no_leftover_tmp_file_after_save(self):
        self.store.save_latest({"RN1": {}}, fetched_at="t")
        leftovers = [p for p in self.base.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])


class TestHistory(StoreTestCase):
    def test_append_stamps_ts_on_each_event(self):
        self.store.append_history(
            [{"op": "changed", "order": "RN1", "key": "k", "old": 1, "new": 2}],
            ts="2026-07-30T10:00:00Z",
        )
        events = self.store.read_history()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["ts"], "2026-07-30T10:00:00Z")
        self.assertEqual(events[0]["op"], "changed")

    def test_append_is_additive_across_calls(self):
        self.store.append_history([{"op": "discovered", "order": "A", "key": ""}], ts="t1")
        self.store.append_history([{"op": "discovered", "order": "B", "key": ""}], ts="t2")
        self.assertEqual([e["order"] for e in self.store.read_history()], ["A", "B"])

    def test_read_history_limit_returns_newest(self):
        for i in range(5):
            self.store.append_history(
                [{"op": "changed", "order": "RN1", "key": f"k{i}", "old": 0, "new": i}],
                ts=f"t{i}",
            )
        events = self.store.read_history(limit=2)
        self.assertEqual([e["key"] for e in events], ["k3", "k4"])

    def test_read_history_empty_when_missing(self):
        self.assertEqual(self.store.read_history(), [])

    def test_append_empty_events_writes_nothing(self):
        self.store.append_history([], ts="t")
        self.assertEqual(self.store.read_history(), [])


class TestArchive(StoreTestCase):
    def test_first_snapshot_archived(self):
        wrote = self.store.archive_if_changed({"RN1": {"a": 1}}, ts="2026-07-30T10:00:00Z")
        self.assertTrue(wrote)
        self.assertEqual(len(self.store.list_archives()), 1)

    def test_identical_snapshot_not_archived_again(self):
        snap = {"RN1": {"a": 1}}
        self.store.archive_if_changed(snap, ts="t1")
        wrote = self.store.archive_if_changed(dict(snap), ts="t2")
        self.assertFalse(wrote)
        self.assertEqual(len(self.store.list_archives()), 1)

    def test_any_byte_difference_archived_even_ignored_paths(self):
        self.store.archive_if_changed(
            {"RN1": {"details": {"strings": {"x": 1}}}}, ts="2026-07-30T10:00:00Z")
        wrote = self.store.archive_if_changed(
            {"RN1": {"details": {"strings": {"x": 2}}}}, ts="2026-07-30T10:30:00Z")
        self.assertTrue(wrote)
        self.assertEqual(len(self.store.list_archives()), 2)

    def test_archive_round_trips_content(self):
        snap = {"RN1": {"order": {"vin": "V1"}}}
        self.store.archive_if_changed(snap, ts="2026-07-30T10:00:00Z")
        name, content = self.store.read_archive(self.store.list_archives()[0])
        self.assertEqual(content, snap)
        self.assertIn("2026-07-30", name)


class TestObservations(StoreTestCase):
    def test_archive_returns_filename_when_written(self):
        name = self.store.archive_if_changed({"a": 1}, ts="2026-07-30T10:00:00Z")
        self.assertTrue(str(name).endswith(".json.gz"))

    def test_archive_returns_none_when_deduped(self):
        self.store.archive_if_changed({"a": 1}, ts="2026-07-30T10:00:00Z")
        self.assertIsNone(
            self.store.archive_if_changed({"a": 1}, ts="2026-07-30T10:30:00Z"))

    def test_every_observation_recorded_even_when_unchanged(self):
        self.store.record_observation(ts="t1", sha="abc", archive="a.json.gz")
        self.store.record_observation(ts="t2", sha="abc", archive=None)
        obs = self.store.read_observations()
        self.assertEqual(len(obs), 2)
        self.assertEqual(obs[0], {"ts": "t1", "sha": "abc", "archive": "a.json.gz"})
        self.assertIsNone(obs[1]["archive"])

    def test_observations_empty_when_missing(self):
        self.assertEqual(self.store.read_observations(), [])


class TestLock(StoreTestCase):
    def test_lock_is_exclusive_while_held(self):
        import fcntl

        with self.store.lock():
            with open(self.base / ".lock") as f:
                with self.assertRaises(OSError):
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_lock_released_after_exit(self):
        import fcntl

        with self.store.lock():
            pass
        with open(self.base / ".lock") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # must not raise
            fcntl.flock(f, fcntl.LOCK_UN)


class TestAgentState(StoreTestCase):
    def test_default_state_empty(self):
        self.assertEqual(self.store.load_agent_state(), {})

    def test_state_round_trips(self):
        self.store.save_agent_state({"consecutive_failures": 2})
        self.assertEqual(
            self.store.load_agent_state(), {"consecutive_failures": 2}
        )


if __name__ == "__main__":
    unittest.main()
