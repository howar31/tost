# TOST — agent rules

## Authority
- Architecture, data flow, key decisions → [SPEC.md](SPEC.md) (SSOT).
- Human-facing usage → [README.md](README.md) (EN, primary) and
  [README.zh-TW.md](README.zh-TW.md) — content changes must land in both.
- Agent-facing usage → [AGENTS.md](AGENTS.md) (quick guide) +
  [skills/tost/SKILL.md](skills/tost/SKILL.md) (full runbook, SSOT).
  `.claude/skills/tost` is a symlink to `skills/tost` — edit the latter.
- This file: development rules only; do not duplicate usage docs here.

## Run / test
```bash
python3 -m unittest discover tests   # must stay green
python3 tost.py status --cached      # smoke test without network
python3 tost.py agent status         # background launchd agent state
```

## Iron rules (the reason this project exists)
- Python stdlib ONLY. No third-party packages, no compiled helpers — the swift
  token transport runs from source (`app/token_post.swift`); keep it that way.
- Outbound network limited to exactly three hosts: `auth.tesla.com`,
  `owner-api.teslamotors.com`, `akamai-apigateway-vfx.tesla.com`.
  Never add hosts or endpoints.
- Tokens live in the macOS Keychain only — never on disk, never in logs, and
  never in argv (Keychain writes go through `security -i` stdin; process
  argv is visible system-wide).
- No telemetry, no auto-update.
- `data/` holds personal order data: mode 700, git-ignored. Never edit its
  files, never commit it, never `git add -f` it.

## Conventions
- TDD: failing test first (stdlib `unittest`). Prefer injectable seams
  (`fetch`, `runner`, `token_request`, `snapshot_fn`) over mock libraries.
- Test fixtures are synthetic: fake order numbers (`RN114455`), fake VINs,
  `example.com` addresses, zeroed IDs, generic place names. Never commit real
  identifiers, real locations, or any value that appears under `data/`.
- Code comments and AI-facing docs in English; README.zh-TW.md is the
  human-facing translation.
- Exit codes are a public contract: 0 ok · 1 error · 2 changes found ·
  3 re-auth required. JSON goes to stdout only; prompts/progress to stderr.
- Conventional Commits.

## Tesla-side traps
- The token endpoint fingerprints the TLS handshake: tokens minted over plain
  Python TLS are later rejected by owner-api with 403. Transport chain:
  swift URLSession (from source) → system curl → urllib (warns). `/usr/bin/swift`
  exists as a stub without Xcode CLT — availability is gated on
  `xcode-select -p`.
- `redirect_uri` must be `tesla://auth/callback`; browsers cannot follow the
  scheme, so the auth code is copied out of DevTools (see README).
- `appVersion` must be the far-future `9.99.9-9999`; retired real build
  numbers get 403 "Update App".
- launchd does not create parent directories for `StandardOutPath`
  (`agent install` creates the log dir itself).
- iMessage / Slack self-sends deliver but raise no phone notification — see
  the channel caveats in README before touching `app/notify.py`.
