import argparse
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from app.agent import LABEL, build_plist
from app.cli import EXIT_AUTH_REQUIRED, cmd_status
from app.store import Store


def status_args(**overrides):
    defaults = {"cached": False, "json": True}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdStatus(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "data")

    def tearDown(self):
        self._tmp.cleanup()

    def test_json_output_is_single_document(self):
        snap = {"RN1": {"order": {"orderStatus": "BOOKED", "modelCode": "my"},
                        "details": {}}}
        out = io.StringIO()
        with redirect_stdout(out):
            code = cmd_status(status_args(), self.store, snapshot_fn=lambda: snap)
        self.assertEqual(code, 0)
        doc = json.loads(out.getvalue())  # raises if two docs were printed
        self.assertEqual(doc["orders"][0]["order_id"], "RN1")
        self.assertEqual(doc["orders"][0]["model"], "Model Y")

    def test_fetch_failure_with_cache_falls_back(self):
        snap = {"RN1": {"order": {"orderStatus": "BOOKED"}, "details": {}}}
        with redirect_stdout(io.StringIO()):
            cmd_status(status_args(), self.store, snapshot_fn=lambda: snap)

        def boom():
            raise OSError("offline")

        out = io.StringIO()
        with redirect_stdout(out):
            code = cmd_status(status_args(), self.store, snapshot_fn=boom)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["orders"][0]["order_id"], "RN1")

    def test_fetch_failure_without_cache_errors(self):
        def boom():
            from app.auth import AuthRequired
            raise AuthRequired("no tokens")

        code = cmd_status(status_args(), self.store, snapshot_fn=boom)
        self.assertEqual(code, EXIT_AUTH_REQUIRED)


class TestPickPython(unittest.TestCase):
    def test_prefers_unversioned_homebrew_symlink(self):
        from app.agent import pick_python

        picked = pick_python(
            candidates=["/opt/homebrew/bin/python3"],
            exists=lambda p: True,
            fallback="/opt/homebrew/opt/python@3.14/bin/python3.14",
        )
        self.assertEqual(picked, "/opt/homebrew/bin/python3")

    def test_falls_back_to_current_interpreter(self):
        from app.agent import pick_python

        picked = pick_python(
            candidates=["/opt/homebrew/bin/python3"],
            exists=lambda p: False,
            fallback="/usr/local/bin/python3.12",
        )
        self.assertEqual(picked, "/usr/local/bin/python3.12")


class TestEnsureLogDir(unittest.TestCase):
    def test_creates_missing_log_directories_with_700(self):
        from app.agent import ensure_log_dir

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "data" / "logs" / "agent.log"
            ensure_log_dir(log)
            self.assertTrue(log.parent.is_dir())
            self.assertEqual(os.stat(log.parent).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(log.parent.parent).st_mode & 0o777, 0o700)

    def test_existing_directories_left_untouched(self):
        from app.agent import ensure_log_dir

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            os.chmod(data, 0o755)
            ensure_log_dir(data / "logs" / "agent.log")
            self.assertEqual(os.stat(data).st_mode & 0o777, 0o755)
            self.assertEqual(os.stat(data / "logs").st_mode & 0o777, 0o700)


class TestAgentPlist(unittest.TestCase):
    def test_plist_runs_quiet_notify_fetch_hourly(self):
        import plistlib

        data = plistlib.loads(
            build_plist("/usr/bin/python3", "/x/tost.py", "/x/data/logs/agent.log")
        )
        self.assertEqual(data["Label"], LABEL)
        self.assertEqual(
            data["ProgramArguments"],
            ["/usr/bin/python3", "/x/tost.py", "fetch", "--notify", "--quiet"],
        )
        self.assertEqual(data["StartInterval"], 3600)
        self.assertTrue(data["RunAtLoad"])

    def test_plist_honors_custom_interval_minutes(self):
        import plistlib

        data = plistlib.loads(
            build_plist("/usr/bin/python3", "/x/tost.py", "/x/log",
                        interval_minutes=30)
        )
        self.assertEqual(data["StartInterval"], 1800)


if __name__ == "__main__":
    unittest.main()
