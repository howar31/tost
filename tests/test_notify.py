import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from app import notify

CONFIG = {
    "channels": {
        "macos": {},
        "discord": {"user_id": "000000000000000000"},
        "slack": {"channel": "U000TESTID"},
        "email": {"to": "user@example.com"},
    }
}


class TestBuildCommands(unittest.TestCase):
    def test_all_configured_channels_produce_commands(self):
        cmds = notify.build_channel_commands(CONFIG, "TOST", "VIN assigned")
        names = [name for name, _ in cmds]
        self.assertEqual(names, ["macos", "discord", "slack", "email"])

    def test_discord_command_targets_user(self):
        cmds = dict(notify.build_channel_commands(CONFIG, "TOST", "msg"))
        argv = cmds["discord"]
        self.assertEqual(argv[0], "/opt/homebrew/bin/dscrd")
        self.assertIn("000000000000000000", argv)
        self.assertIn("TOST — msg", " ".join(argv))

    def test_slack_command_targets_channel(self):
        cmds = dict(notify.build_channel_commands(CONFIG, "TOST", "msg"))
        argv = cmds["slack"]
        self.assertEqual(argv[0], "/opt/homebrew/bin/slk")
        self.assertIn("U000TESTID", argv)

    def test_discord_profile_pinned_when_configured(self):
        config = {"channels": {"discord": {"user_id": "1", "profile": "MyBot"}}}
        argv = dict(notify.build_channel_commands(config, "T", "m"))["discord"]
        self.assertIn("--profile", argv)
        self.assertEqual(argv[argv.index("--profile") + 1], "MyBot")

    def test_slack_profile_pinned_when_configured(self):
        config = {"channels": {"slack": {"channel": "C1", "profile": "personal"}}}
        argv = dict(notify.build_channel_commands(config, "T", "m"))["slack"]
        self.assertIn("--profile", argv)
        self.assertEqual(argv[argv.index("--profile") + 1], "personal")

    def test_no_profile_flag_when_unconfigured(self):
        config = {"channels": {"discord": {"user_id": "1"}}}
        argv = dict(notify.build_channel_commands(config, "T", "m"))["discord"]
        self.assertNotIn("--profile", argv)

    def test_email_command_has_subject_and_body(self):
        cmds = dict(notify.build_channel_commands(CONFIG, "TOST", "delivery window changed"))
        argv = cmds["email"]
        self.assertEqual(argv[0], "/opt/homebrew/bin/gws")
        joined = " ".join(argv)
        self.assertIn("user@example.com", joined)
        self.assertIn("delivery window changed", joined)

    def test_missing_config_falls_back_to_macos_only(self):
        cmds = notify.build_channel_commands({}, "TOST", "msg")
        self.assertEqual([name for name, _ in cmds], ["macos"])

    def test_imessage_command_targets_handle_via_osascript(self):
        config = {"channels": {"imessage": {"to": "self@example.com"}}}
        cmds = dict(notify.build_channel_commands(config, "TOST", "VIN assigned"))
        argv = cmds["imessage"]
        self.assertEqual(argv[0], "/usr/bin/osascript")
        joined = " ".join(argv)
        self.assertIn("self@example.com", joined)
        self.assertIn("VIN assigned", joined)
        self.assertIn("Messages", joined)

    def test_imessage_message_quotes_escaped(self):
        config = {"channels": {"imessage": {"to": "self@example.com"}}}
        cmds = dict(notify.build_channel_commands(config, "TOST", 'say "hi"'))
        joined = " ".join(cmds["imessage"])
        self.assertNotIn('say "hi"', joined)  # raw quotes must not survive
        self.assertIn('say \\"hi\\"', joined)


class TestLoadConfig(unittest.TestCase):
    def test_missing_file_returns_empty_silently(self):
        err = io.StringIO()
        with redirect_stderr(err):
            cfg = notify._load_config(Path("/nonexistent/notify.json"))
        self.assertEqual(cfg, {})
        self.assertEqual(err.getvalue(), "")

    def test_invalid_json_warns_instead_of_silently_dropping_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notify.json"
            path.write_text('{"channels": broken', encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err):
                cfg = notify._load_config(path)
        self.assertEqual(cfg, {})
        self.assertIn("notify.json", err.getvalue())


class TestDispatchIsolation(unittest.TestCase):
    def test_one_failing_channel_does_not_block_others(self):
        ran = []

        def runner(argv):
            ran.append(argv[0])
            if "discord" in argv[0]:
                raise RuntimeError("discord down")

        results = notify.dispatch(
            [("discord", ["discord-cli", "x"]), ("slack", ["slack-cli", "y"])],
            runner=runner,
        )
        self.assertEqual(ran, ["discord-cli", "slack-cli"])
        self.assertEqual(results, {"discord": False, "slack": True})


if __name__ == "__main__":
    unittest.main()
