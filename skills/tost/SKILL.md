---
name: tost
description: Query the user's Tesla order status from local TOST data, or run a polling loop that watches the order and reports each round. Use when the user asks about their Tesla order, delivery window, VIN assignment, order changes, or timeline, or asks to keep watching it — e.g. (zh) 「我的特斯拉訂單」「交車日期」「訂單有什麼變化」「VIN 配了嗎」「幫我盯著訂單」「定期回報訂單」; (en) "my Tesla order", "delivery date", "any order changes", "did I get a VIN", "keep monitoring my order".
---

# TOST — Tesla Order Status Queries

All commands run from the TOST checkout (the directory containing `tost.py`).
The tool is local-only: it talks exclusively to Tesla's API, stores data
under `data/`.

This file covers one-off questions. For a polling loop that watches the order
over a period and reports each round, follow [MONITOR.md](MONITOR.md) instead.

## Commands

| Question | Command |
|---|---|
| Current status (fresh) | `python3 tost.py status --json` |
| Current status (offline/fast) | `python3 tost.py status --cached --json` |
| What changed / history | `python3 tost.py timeline --json` |
| Only what is new since a timestamp | `python3 tost.py timeline --json --since <ISO>` |
| Anything not in the summary | `python3 tost.py raw` (full snapshot JSON) |
| Force a snapshot now | `python3 tost.py fetch` |
| Dashboard-shaped export | `python3 tost.py export` |

Exit codes: 0 ok, 1 error, 2 fetch found changes, 3 re-auth required.

## Interpretation

- `status --json` returns `{fetched_at, orders: [{order_id, status, model, vin,
  delivery_window, delivery_appointment, delivery_center,
  eta_to_delivery_center, odometer, ordered_at, options}]}`. `null` = Tesla has
  not populated that field yet.
- VIN appearing for the first time, a narrowing `delivery_window`, or a
  `delivery_appointment` are the milestones the user cares about — lead with
  those.
- `timeline --json` events: `{ts, op: discovered|changed|added|removed|vanished,
  order, key, old, new}`. Dot-paths refer to the raw API structure; explain them
  in plain language, don't echo raw key paths at the user.
- For questions the summary can't answer, read `raw` output and interpret the
  underlying Tesla fields directly.
- Answer in the user's conversation language.

## Rules

- Exit code 3 (or `AuthRequired`): tell the user to run `python3 tost.py auth`
  in a terminal — it needs their browser; do not attempt it yourself.
- Never edit files under `data/` and never add network endpoints to the code.
- A periodic launchd agent may already be snapshotting in the background
  (`python3 tost.py agent status` shows its interval); prefer `--cached` when
  that freshness is enough.
