# TOST CLI — Agent Guide

Local Tesla order tracker (macOS, Python stdlib only). This file is the quick
reference for AI agents; the full runbook is
[skills/tost/SKILL.md](skills/tost/SKILL.md), installable across agents with
`npx skills add https://github.com/howar31/tost`.

To run a polling loop that watches the order and reports each round in plain
language, follow [skills/tost/MONITOR.md](skills/tost/MONITOR.md) instead. It is
written to be followed literally by a small model.

## Commands

Run from the TOST checkout (the directory containing `tost.py`):

| Task | Command |
|---|---|
| Current status (fresh fetch) | `python3 tost.py status --json` |
| Current status (offline/fast) | `python3 tost.py status --cached --json` |
| Change history | `python3 tost.py timeline --json` |
| Only what is new since a timestamp | `python3 tost.py timeline --json --since <ISO>` |
| Full raw snapshot | `python3 tost.py raw` |
| Force a snapshot now | `python3 tost.py fetch` |
| Dashboard-shaped export | `python3 tost.py export` |
| Background agent status | `python3 tost.py agent status` |

Exit codes: 0 ok, 1 error, 2 fetch found changes, 3 re-auth required.

## Output contract

- `status --json` → `{fetched_at, orders: [{order_id, status, model, vin,
  delivery_window, delivery_appointment, delivery_center,
  eta_to_delivery_center, odometer, ordered_at, options}]}`. `null` = Tesla
  has not populated that field yet.
- `timeline --json` → events `{ts, op: discovered|changed|added|removed|
  vanished|milestone, order, key, old, new}`. Dot-paths refer to the raw API
  structure; explain them in plain language rather than echoing key paths.
- For questions the summary can't answer, read `raw` output and interpret the
  underlying Tesla fields directly.

## Hard rules

- Exit code 3 (re-auth): tell the human to run `python3 tost.py auth` in a
  terminal — it needs their browser; do not attempt it yourself.
- Never edit files under `data/`; never add network endpoints to the code.
- A launchd agent may already be snapshotting periodically; prefer `--cached`
  when that freshness is enough.
