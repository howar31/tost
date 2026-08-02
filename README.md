# TOST CLI

![License](https://img.shields.io/github/license/howar31/tost?style=flat-square)
![Made with Python](https://img.shields.io/badge/made%20with-Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-macOS-000000?style=flat-square&logo=apple)
![Conventional Commits](https://img.shields.io/badge/conventional%20commits-1.0.0-FE5196?style=flat-square&logo=conventionalcommits&logoColor=white)
![Last commit](https://img.shields.io/github/last-commit/howar31/tost?style=flat-square)
![Stars](https://img.shields.io/github/stars/howar31/tost?style=flat-square)

[中文](README.zh-TW.md)

Local Tesla order tracker. Pure Python stdlib, zero third-party dependencies,
no telemetry. Talks only to Tesla's official API (`auth.tesla.com`,
`owner-api.teslamotors.com`, `akamai-apigateway-vfx.tesla.com`); tokens live
in the macOS Keychain and never touch disk in plaintext.

Requirements: macOS (Keychain, launchd, osascript), Python 3.9+. The swift
token transport needs the Xcode Command Line Tools; without them it falls
back to the system curl automatically.

## Usage

```sh
python3 tost.py auth              # first run: Tesla login via browser (see below)
python3 tost.py status            # current order summary (fetches fresh)
python3 tost.py status --cached   # offline: read the local cache
python3 tost.py timeline          # change-history timeline
python3 tost.py timeline --since 2026-07-01
                                  #   only events newer than that timestamp
python3 tost.py fetch             # take a snapshot and show changes
python3 tost.py raw               # full raw JSON
python3 tost.py export            # summary + events + poll log (dashboard feed)
python3 tost.py agent install     # launchd agent: periodic fetch + notifications
                                  #   (--interval 30 for every 30 min, default 60)
python3 tost.py agent status      # background agent status
```

## Authentication

Since 2026-07 Tesla only accepts `tesla://auth/callback` as the redirect URI.
Browsers cannot follow that redirect, so the authorization code is copied out
of DevTools:

1. Run `python3 tost.py auth`; it prints the authorization URL (it does not
   auto-open a browser).
2. Open a new tab → open DevTools first (Cmd+Option+I) → Network → tick
   "Preserve log" → filter for `callback`.
3. Paste the authorization URL into that tab's address bar. With an active
   Tesla session it redirects instantly (no login needed); otherwise complete
   the Tesla login (password + MFA).
4. In the Network list, find `tesla://auth/callback?code=...` (the
   red/cancelled request, or the Location header of the last `/authorize`
   response). Copy that full URL and paste it back into the terminal.

The token exchange goes through Apple's TLS stack (`swift` running the
`app/token_post.swift` source) to pass Tesla's TLS fingerprint check; without
Xcode CLT it skips swift and falls back to the system curl, then Python
urllib.

## Notification channels

Change notifications go to the channels configured in `data/notify.json`
(template: `notify.json.example`). Channels are independent and best-effort;
a failing channel never affects the other channels or the fetch itself, and
each failure is logged with its reason to stderr (the background agent's
`data/logs/agent.log`).

Supported: macOS Notification Center, iMessage, Discord DM, Slack, Email.
Discord and Slack ride [dscrd](https://github.com/howar31/dscrd) and
[slk](https://github.com/howar31/slk) — token-efficient, agent-facing CLIs
for Discord and Slack; install and authenticate them separately. Both accept
a `profile` field that pins the sending account, so a global account switch
elsewhere can never silently change the sending identity. Email goes through
the `gws` CLI.

### Two caveats when picking channels

**Messages to yourself raise no notification.** iMessage and Slack self-DMs
both behave this way: a message from your account to that same account is
treated by the platform as a sent message syncing across devices, not as an
incoming one — no banner; you must open the app to see it. This is platform
mechanics: using another phone number or address you own changes nothing.
Such channels only work as passive records. For a real push, pick a channel
where you are a genuine recipient (e.g. a bot DM to you, or a bot posting to
a channel).

**Corporate accounts have visibility risks.** If the Email or Slack channel
uses an account owned by your organization, admins can usually inspect the
records (e.g. Google Workspace Email Log Search metadata, full content when
Vault is enabled, the connected-apps list). For personal use, avoid
organization accounts.

### macOS automation permission

The iMessage channel needs Automation permission (a dialog appears on first
send). If the background agent and manual runs use the same Python
interpreter path, they are the same TCC subject — authorizing once covers
both.

## AI agents

The repo ships an agent skill (`skills/tost/`) that teaches the query
interface — JSON contracts, exit codes, interpretation rules:

```sh
npx skills add https://github.com/howar31/tost
```

Claude Code picks the skill up automatically when working inside this repo;
other agents can start from [AGENTS.md](AGENTS.md).

### Watching an order over a period

[skills/tost/MONITOR.md](skills/tost/MONITOR.md) is a polling runbook: an agent
checks the order on an interval and reports each round in plain language, one
line when nothing changed and a short paragraph when something did. It is
written to be followed literally by a small, cheap model.

With Claude Code, if your setup has a repeat command:

```
/model haiku
/loop 30m Follow skills/tost/MONITOR.md and report this round.
```

Any other repeating mechanism works too; the runbook only assumes it is invoked
once per round.

The loop is read-only. It reads the cache the background agent writes and never
fetches, so it cannot swallow a pending change and suppress its notification.
An interval shorter than the background agent's refresh (`tost agent status`)
only produces repeated heartbeats.

## Tests

```sh
python3 -m unittest discover tests
```

## Data

Everything lives in `data/` (chmod 700, git-ignored): `latest.json` newest
snapshot, `history.jsonl` change-event stream, `archive/*.json.gz` raw
snapshot archive (written whenever any byte differs, including
noise-filtered fields — the full audit trail), `observations.jsonl` one line
per fetch (timestamp + content hash + archive filename, distinguishing "no
change" from "not polled"), `logs/agent.log` background agent output.

## License

[MIT](LICENSE)
