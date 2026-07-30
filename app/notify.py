"""Notification fan-out: macOS Notification Center + optional remote channels.

Remote channels ride the user's own CLIs (dscrd / slk / gws) so the phone gets
push notifications through services already in use — no new third-party code.
Channel targets live in data/notify.json (git-ignored, personal identifiers):

    {"channels": {"macos": {},
                  "discord": {"user_id": "..."},
                  "slack":   {"channel": "..."},
                  "email":   {"to": "..."}}}

Absolute CLI paths because the launchd agent runs with a minimal PATH.
Every channel is best-effort; a failing channel never breaks the fetch or the
other channels.
"""

import json
import subprocess
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "data" / "notify.json"

DSCRD = "/opt/homebrew/bin/dscrd"
SLK = "/opt/homebrew/bin/slk"
GWS = "/opt/homebrew/bin/gws"

CHANNEL_TIMEOUT = 30


def _escape(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _osascript_argv(title, message):
    script = f'display notification "{_escape(message)}" with title "{_escape(title)}"'
    return ["/usr/bin/osascript", "-e", script]


def _imessage_argv(to, text):
    # Message-to-self via the user's own iMessage account; native iPhone push.
    script = (
        'tell application "Messages" to send "{}" to participant "{}" '
        "of (1st account whose service type = iMessage)"
    ).format(_escape(text), _escape(to))
    return ["/usr/bin/osascript", "-e", script]


def _profile_flag(opts):
    """Pin the CLI profile so a global `auth switch` elsewhere can never
    silently change which account TOST notifies from."""
    profile = opts.get("profile")
    return ["--profile", profile] if profile else []


def build_channel_commands(config, title, message):
    """Pure: config -> [(channel_name, argv)]. Unconfigured = macOS only."""
    channels = (config or {}).get("channels") or {"macos": {}}
    text = f"{title} — {message}"
    commands = []
    for name, opts in channels.items():
        if name == "macos":
            commands.append((name, _osascript_argv(title, message)))
        elif name == "discord" and opts.get("user_id"):
            commands.append((name, [DSCRD, "dm", "send"] + _profile_flag(opts)
                             + ["--user", opts["user_id"], "--text", text]))
        elif name == "slack" and opts.get("channel"):
            commands.append((name, [SLK, "msg", "send"] + _profile_flag(opts)
                             + ["--channel", opts["channel"], "--text", text]))
        elif name == "email" and opts.get("to"):
            commands.append((name, [GWS, "gmail", "+send", "--to", opts["to"],
                                    "--subject", text, "--body", message]))
        elif name == "imessage" and opts.get("to"):
            commands.append((name, _imessage_argv(opts["to"], text)))
    return commands


def _run(argv):
    subprocess.run(argv, capture_output=True, timeout=CHANNEL_TIMEOUT, check=True)


def dispatch(commands, runner=_run):
    """Run every channel command; isolate failures. Returns {channel: ok}."""
    results = {}
    for name, argv in commands:
        try:
            runner(argv)
            results[name] = True
        except Exception:
            results[name] = False
    return results


def _load_config(path=CONFIG_FILE):
    if not path.exists():
        return {}  # unconfigured is a valid state: macOS-only fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        # a broken config must not silently drop the remote push channels;
        # stderr lands in agent.log under launchd
        print(f"[!] cannot read {path.name} ({e}) — using macOS-only notification",
              file=sys.stderr)
        return {}


def send(title, message):
    """Best-effort notification to all configured channels."""
    try:
        dispatch(build_channel_commands(_load_config(), title, message))
    except Exception:
        pass
