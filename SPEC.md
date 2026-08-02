# TOST CLI — SPEC

## Purpose

Local, self-auditable Tesla order tracker. Polls Tesla's order API for the
account's orders, keeps an append-only history of every meaningful change
(VIN assignment, delivery window, appointments), and pushes notifications
through channels the owner already uses. Runs entirely on the user's Mac:
no server, no telemetry, no third-party code. Consumed four ways: directly
as a CLI, unattended via a launchd background agent, conversationally by
AI agents through the bundled skill ([skills/tost/SKILL.md](skills/tost/SKILL.md)),
and as an ad-hoc polling monitor driven by a small model following
[skills/tost/MONITOR.md](skills/tost/MONITOR.md).

## Architecture

```
tost.py (argparse dispatch)
   auth ──► app/auth.py    OAuth2 PKCE (client_id=ownerapi) ── tokens ──► macOS Keychain
                │                                                        (security -i, base64 payload)
                └─ token exchange via app/transport.py: swift URLSession
                   (app/token_post.swift, run from source) → /usr/bin/curl → urllib
   fetch / status ──► app/cli.py run_fetch pipeline (serialized by flock on data/.lock):
       app/api.py  GET /api/1/users/orders  +  GET /tasks per order  ──► snapshot
       app/diff.py snapshot diff vs data/latest.json, noise-filtered  ──► events
       app/store.py persist: latest.json · history.jsonl · archive/*.json.gz
                    (sha256-deduped audit trail) · observations.jsonl (poll log)
       app/notify.py fan-out on changes: macOS / iMessage (osascript),
                    Discord (dscrd) / Slack (slk) / Email (gws) via external CLIs
   agent ──► app/agent.py  launchd LaunchAgent local.tost (StartInterval, RunAtLoad)
```

- **Outbound hosts** (complete list): `auth.tesla.com`,
  `owner-api.teslamotors.com`, `akamai-apigateway-vfx.tesla.com`.
- **Auth flow**: PKCE S256; redirect is `tesla://auth/callback`, which
  browsers cannot follow — the user copies the callback URL from DevTools.
  The token endpoint fingerprints TLS handshakes, so token requests prefer
  Apple's URLSession (same TLS family as the official app), falling back to
  system curl, then urllib (warns). Access-token expiry is read from the JWT
  `exp` locally (no signature check needed); refresh rewrites the Keychain.
  A refresh rejected with HTTP 4xx raises `AuthRequired` (exit 3); network
  failures and 5xx propagate as transient errors so an offline box never
  prompts a false re-login.
- **Diff semantics**: recursive dict comparison producing dot-path events
  (`changed`/`added`/`removed`, plus `discovered`/`vanished` per order and
  backfilled `milestone` events carrying their true historical timestamp).
  A prefix/exact ignore-list drops UI-string churn; the raw archive keeps
  every distinct response byte-for-byte so the filter can never silently
  destroy information. `timeline --since <ISO>` returns only events strictly
  newer than a timestamp, comparing as strings so the two timestamp shapes in
  `history.jsonl` (fetch-stamped `...Z` and backfilled historic values) order
  correctly without parsing; a malformed value exits 1 rather than degrading
  to an unfiltered dump.
- **Exit codes (public contract)**: 0 ok · 1 error · 2 changes found ·
  3 re-auth required. JSON to stdout; prompts and progress to stderr.

## Layout

```
tost.py                  CLI entry point: argparse dispatch, exit codes
app/
  auth.py                PKCE login, Keychain token store, refresh logic
  transport.py           token-endpoint transport chain (swift/curl/urllib)
  token_post.swift       minimal URLSession form-POST helper (run from source)
  api.py                 Tesla API client: orders + per-order tasks, retry/backoff
  cli.py                 command implementations, fetch pipeline, rendering
  diff.py                pure snapshot diff + noise filter (no I/O)
  store.py               data/ persistence: snapshot, history, archive,
                         observations, agent state, advisory lock
  notify.py              notification fan-out, per-channel argv builders
  agent.py               launchd agent install/uninstall/status
tests/                   stdlib unittest suite; injectable seams, no mocks
skills/tost/SKILL.md     agent-facing runbook (SSOT for agent usage)
skills/tost/MONITOR.md   polling-loop runbook for an ad-hoc monitoring agent
.claude/skills/tost      symlink → ../../skills/tost (Claude Code auto-load)
AGENTS.md                cross-tool quick guide for AI agents
README.md                human docs, English (primary)
README.zh-TW.md          human docs, Traditional Chinese (kept in sync)
notify.json.example      channel-config template → copy to data/notify.json
data/                    runtime data (git-ignored, chmod 700, files 600)
```

## Conventions

See [CLAUDE.md](CLAUDE.md) for the iron rules (stdlib-only, three-host network
limit, Keychain-only tokens, no telemetry) and workflow conventions (TDD with
injectable seams, synthetic-only test fixtures, English comments, bilingual
README sync, Conventional Commits).

## Verification

- `python3 -m unittest discover tests` — the whole suite is offline: network,
  Keychain, and subprocess boundaries are injected (`fetch`, `runner`,
  `token_request`, `snapshot_fn`, `impls/order`).
- Live smoke: `python3 tost.py status --cached` (no network) or
  `python3 tost.py fetch` (real API; requires prior `auth`).
- Background agent: `python3 tost.py agent status`, log at
  `data/logs/agent.log`.

## Known Limitations / Non-goals

- macOS-only by design (Keychain, launchd, osascript, Apple TLS stack).
- Tesla's order API is unofficial and drifts; `raw` and `--json` output stay
  usable even when the summary renderer lags behind. Known 403 causes are
  handled: retired app versions (far-future `appVersion`) and fingerprinted
  TLS (transport chain).
- Lists are diffed as opaque scalars (old ≠ new → one `changed` event).
- `timeline --since` filters on event `ts`, so a `milestone` event backfilled
  after a monitoring session started would carry a historic timestamp, sort
  before the watermark, and never be reported. Backfill is deduplicated and
  fires only on first discovery, so this cannot happen with the current
  `MILESTONE_FIELDS`; adding an entry later would reintroduce it.
- OAuth `state` is generated but not verified — acceptable in a copy-paste
  flow where the user transports the callback URL themselves.
- Single account, single machine; no GUI, no multi-user, no sharing.
- Notification channels are best-effort: a failing channel is never retried,
  but each failure is logged with its reason to stderr (agent.log); channel
  failures do not fail the fetch.

## Key Decisions

- **Keychain over a plaintext 600 file** — token safety is the project's
  raison d'être; the secret also never appears in process argv
  (`security -i` reads the command from stdin, payload base64-wrapped).
- **Source-run swift helper over an HTTP-impersonation dependency** — keeps
  the zero-third-party, auditable-source guarantee while still presenting a
  browser-grade TLS handshake.
- **JSON files over SQLite** — auditable with `cat`, trivial data volume.
- **Dual record: filtered history + raw archive + poll log** —
  `history.jsonl` is the interpreted story, `archive/` the byte-exact ground
  truth (sha256-deduped), `observations.jsonl` distinguishes "unchanged"
  from "never polled".
- **`status` fetches fresh by default** — a manual query means "now";
  `--cached` is the explicit offline path.
- **Advisory flock around the whole fetch pipeline** — manual runs and the
  launchd agent cannot interleave writes.
- **External CLIs for remote notification channels** — reuses the user's
  already-authenticated tools (dscrd/slk/gws) instead of adding network code
  or credentials to this codebase.
- **The monitor loop is read-only** (`timeline --since` + `status --cached`
  only). Any fetch consumes the pending diff, so a monitor that pulled its own
  data would silently suppress the background agent's notification for exactly
  the changes it just absorbed. Freshness is deliberately delegated to the
  launchd agent; the monitor only translates its cache.
- **The monitor's field dictionary lives in the runbook, not in Python** — a
  hardcoded severity table would rot against Tesla's schema drift, and
  interpreting fields the table has never seen is the reason a model is doing
  the job at all. `MONITOR.md` pairs the dictionary with an explicit fallback
  rule for unlisted paths.
