import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from app.cli import EXIT_ERROR, EXIT_OK, cmd_timeline, filter_since
from app.store import Store

NAIVE = "2026-07-02T12:45:10"  # backfilled milestone: historic ts, no Z
STAMPED = "2026-07-31T02:51:54Z"  # fetch-stamped event


def timeline_args(**overrides):
    defaults = {"n": None, "json": True, "since": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestFilterSince(unittest.TestCase):
    def test_keeps_only_strictly_newer_events(self):
        events = [
            {"ts": "2026-07-30T00:00:00Z", "key": "a"},
            {"ts": STAMPED, "key": "b"},
            {"ts": "2026-08-01T00:00:00Z", "key": "c"},
        ]
        kept = filter_since(events, STAMPED)
        self.assertEqual([e["key"] for e in kept], ["c"])

    def test_orders_naive_milestone_before_stamped_event(self):
        events = [{"ts": NAIVE, "key": "old"}, {"ts": STAMPED, "key": "new"}]
        kept = filter_since(events, "2026-07-30T00:00:00Z")
        self.assertEqual([e["key"] for e in kept], ["new"])

    def test_missing_ts_is_treated_as_oldest(self):
        events = [{"key": "no-ts"}, {"ts": STAMPED, "key": "b"}]
        kept = filter_since(events, "2026-07-01T00:00:00Z")
        self.assertEqual([e["key"] for e in kept], ["b"])


class TestCmdTimelineSince(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "data")
        self.store.append_history(
            [
                {"ts": NAIVE, "op": "milestone", "order": "RN1", "key": "reg.startedOn"},
                {"ts": STAMPED, "op": "changed", "order": "RN1", "key": "copy"},
                {"ts": "2026-08-01T01:00:00Z", "op": "added", "order": "RN1", "key": "field"},
            ],
            ts="2026-08-01T01:00:00Z",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, **overrides):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cmd_timeline(timeline_args(**overrides), self.store)
        return code, out.getvalue(), err.getvalue()

    def test_since_filters_before_tailing(self):
        # one event survives --since, so -n 2 must still yield one.
        # Tailing first would leak "copy", which --since excluded.
        code, out, _ = self._run(since=STAMPED, n=2)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual([e["key"] for e in json.loads(out)], ["field"])

    def test_empty_result_prints_empty_json_array_and_exits_zero(self):
        code, out, _ = self._run(since="2026-09-01T00:00:00Z")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out), [])

    def test_malformed_since_exits_error_without_dumping_history(self):
        code, out, err = self._run(since="yesterday")
        self.assertEqual(code, EXIT_ERROR)
        self.assertEqual(out, "")
        self.assertIn("--since", err)

    def test_without_since_every_event_is_returned(self):
        code, out, _ = self._run()
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(len(json.loads(out)), 3)


if __name__ == "__main__":
    unittest.main()
