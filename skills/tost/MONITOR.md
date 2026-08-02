# TOST Monitor Runbook

A procedure for an agent that watches a Tesla order closely for a limited period,
for example while a VIN assignment is expected, and reports each round in plain
language. Written to be followed literally by a small model. Do not improvise.

For one-off questions about the order, use [SKILL.md](SKILL.md) instead. This file
is only for the polling loop.

Reports are written in the user's conversation language. The templates and examples
below are in Traditional Chinese; copy their shape exactly.

## What this loop must never do

- Never run `fetch`. Never run `status` without `--cached`. Both would pull from
  Tesla and consume the pending diff, which silently suppresses the background
  agent's phone notification for those same changes.
- Never run `auth`. It needs a browser. If anything reports that re-authentication
  is required, tell the user to run `python3 tost.py auth` themselves and stop.
- Never create, edit, or delete anything under `data/`.
- Never show a raw dot-path such as `details.tasks.scheduling.deliveryWindowDisplay`
  to the user. Translate it using the dictionary below.
- Never say a VIN was assigned while the `vin` field is `null`.
- Never invent a value that is not in the command output. `null` means Tesla has not
  published it yet, and "not yet published" is the correct thing to report.

## One round

Run these from the TOST checkout, in this order.

```bash
python3 tost.py timeline --json --since <watermark>   # new events, usually []
python3 tost.py status --cached --json                # fields for the report line
date -u +%FT%TZ; date +%H:%M                          # UTC now, then local now
```

All three are local. None touch the network.

Then print either the heartbeat line or the expanded block, and always finish with
the `STATE` line.

## Watermark protocol

`<watermark>` is the timestamp of the newest event already reported. It is carried
between rounds in your own output, because a long-running loop gets its earlier
context compacted away.

Every round ends with exactly this line, as the last line of the report:

```
STATE since=2026-07-31T02:51:54Z
```

At the start of a round, scan back through your previous output for the most recent
`STATE since=` line and use that value.

**Bootstrap**, used when no `STATE` line exists yet (first round of a session):

```bash
python3 tost.py timeline --json -n 1
```

Take that event's `ts` as the watermark, print `監控開始，基準時間 <ts>`, print the
`STATE` line, and stop for this round. Do not dump the history.

**Recovery**: if you cannot find a `STATE` line, bootstrap again. Losing one round of
reporting is acceptable; guessing a watermark is not.

**Carrying forward**: when `timeline --since` returns `[]`, the watermark does not
change. Repeat the same value in the `STATE` line.

**Advancing**: when events come back, the new watermark is the `ts` of the last
event in the returned list (the command returns them in chronological order).

## Field dictionary

Paths are rooted at the order snapshot. Severity controls the order in which events
are listed, not whether they are reported. **Report every event, including noise.**
The user has explicitly asked to see all changes.

| Path | Plain language | Severity |
|---|---|---|
| `details.tasks.deliveryDetails.regData.orderDetails.vin` | 配到 VIN | milestone |
| `details.tasks.scheduling.deliveryWindowDisplay` | 交車時間窗出現或收窄 | milestone |
| `details.tasks.scheduling.deliveryAppointmentDate` | 交車預約成立或改期 | milestone |
| `order.orderStatus` | 訂單狀態變更 | milestone |
| `details.tasks.scheduling.deliveryAddressTitle` | 交付中心變更 | routine |
| `details.tasks.finalPayment.data.etaToDeliveryCenter` | 預計抵達交付中心的時間 | routine |
| `details.tasks.registration.orderDetails.vehicleOdometer` | 車輛里程數 | routine |
| `registration.startedOn` | 註冊流程開始 | routine |
| `details.tasks.insurance.*` | 保險任務欄位 | routine |
| `details.tasks.financing.*` | 貸款任務欄位 | routine |
| `details.tasks.tradeIn.*` | 舊車換購任務欄位 | routine |
| any path containing `.strings.` | Tesla 介面文案改寫，與交車進度無關 | noise |
| any newly added field whose value is `""`, `null`, or `[]` | Tesla 新增的空欄位，尚未填值 | noise |

Severity here is a reporting-priority label defined by this runbook. It has nothing
to do with the `op` value `milestone` that some events carry; that `op` marks a
date-bearing field backfilled with its own historic timestamp. Do not conflate them.

**Event `op` values and their severity**:

| `op` | Meaning | Severity |
|---|---|---|
| `vanished` | 訂單已不在帳號中 | milestone, always list first |
| `discovered` | 首次看到這筆訂單 | milestone |
| `changed` | 欄位值被取代 | look up `key` in the table above |
| `added` | 欄位首次出現 | look up `key` in the table above |
| `removed` | 欄位消失 | look up `key` in the table above |
| `milestone` | 帶歷史日期回填的欄位 | look up `key` in the table above |

`discovered` and `vanished` carry an empty `key`; describe them from the `op`
alone.

**Short keys.** `op: milestone` events do not use full dot-paths. They carry the
short label defined in `MILESTONE_FIELDS` in `app/cli.py`, for example
`registration.startedOn`. Look those up as written; do not expect a `details.`
prefix.

**Paths not in the table.** The table will always be incomplete because Tesla adds
fields. Describe the change from the value itself, and treat it as `routine`. If the
new value looks like a date, or like a 17-character VIN, treat it as a milestone
candidate and say plainly that you are not certain what the field means.

## Output templates

Heartbeat, when the round returned no new events. One line, then `STATE`:

```
14:30  無變化 · BOOKED · VIN 未配 · 交車窗 未定
STATE since=2026-07-31T02:51:54Z
```

Fill it from `status --cached --json`: `status`, then `vin` (or `VIN 未配` when
null), then `delivery_window` (or `交車窗 未定` when null). Use the local `HH:MM`
from `date +%H:%M`.

Expanded, when there are new events. Verdict sentence, one line per event with
milestones first, interpretation sentence, then `STATE`:

```
14:30  2 筆變動
Tesla 更新了兩個與交車無關的欄位。
- 「在家充電」方案說明改寫，新增不得轉讓與限當季交付的條款
- 保險任務新增一個空欄位
交車進度未動：仍為 BOOKED，尚未配 VIN，交車時間窗未定。
STATE since=2026-07-31T02:51:54Z
```

**Stale cache marker.** Compare `fetched_at` from the status output with the UTC
timestamp from `date -u`. The background agent refreshes every 30 minutes, so a gap
beyond roughly 90 minutes means it has probably stopped. Precision is not needed:
if the date differs, or the UTC hour differs by 2 or more, append this to the
heartbeat line:

```
 · 注意：快取已超過 90 分鐘未更新，背景 agent 可能已停止
```

## Worked example A: nothing new

Commands and their output:

```
$ python3 tost.py timeline --json --since 2026-07-31T02:51:54Z
[]
$ python3 tost.py status --cached --json
{
  "fetched_at": "2026-07-31T03:22:01Z",
  "orders": [{"order_id": "RN114455", "status": "BOOKED", "model": "Model Y",
              "vin": null, "delivery_window": null, "delivery_appointment": "",
              "delivery_center": "Example Delivery Center",
              "eta_to_delivery_center": null, "odometer": null,
              "ordered_at": null, "options": "MDLY,PN00"}]
}
$ date -u +%FT%TZ; date +%H:%M
2026-07-31T03:31:44Z
11:31
```

Exact report:

```
11:31  無變化 · BOOKED · VIN 未配 · 交車窗 未定
STATE since=2026-07-31T02:51:54Z
```

## Worked example B: two noise events

Commands and their output:

```
$ python3 tost.py timeline --json --since 2026-07-30T09:43:46Z
[
  {"ts": "2026-07-31T02:51:54Z", "op": "changed", "order": "RN114455",
   "key": "details.tasks.homeCharging.strings.intent_subtitle",
   "old": "在家充電一公里僅需 X 元", "new": "在家充電一公里最低僅需 X 元。方案不得轉讓或拆售。"},
  {"ts": "2026-07-31T02:51:54Z", "op": "added", "order": "RN114455",
   "key": "details.tasks.insurance.insuranceSubType", "new": ""}
]
$ python3 tost.py status --cached --json
{"fetched_at": "2026-07-31T03:22:01Z",
 "orders": [{"order_id": "RN114455", "status": "BOOKED", "vin": null,
             "delivery_window": null, "...": "..."}]}
$ date -u +%FT%TZ; date +%H:%M
2026-07-31T03:31:44Z
11:31
```

Exact report:

```
11:31  2 筆變動
Tesla 更新了兩個與交車無關的欄位。
- 「在家充電」方案說明改寫，新增不得轉讓或拆售的條款
- 保險任務新增一個空欄位
交車進度未動：仍為 BOOKED，尚未配 VIN，交車時間窗未定。
STATE since=2026-07-31T02:51:54Z
```

Note what did **not** happen: no dot-path appears in the report, both events are
still reported despite being noise, and the watermark advanced to the newest `ts`.

## Error handling

- Either command exits non-zero: print the stderr line verbatim on one line, keep
  the previous watermark unchanged, print the `STATE` line, and stop for this round.
  Do not guess at the order state.
- `invalid --since`: your watermark is malformed. Bootstrap again.
- `no data yet`: tell the user to run `python3 tost.py fetch` once, and stop.
- Re-authentication required: tell the user to run `python3 tost.py auth`
  themselves, and stop. This should be unreachable, since this loop never fetches.

## Starting a monitoring session

From the TOST checkout, in a Claude Code session:

```
/model haiku
/loop 30m Follow skills/tost/MONITOR.md and report this round.
```

An interval shorter than the background agent's refresh (30 minutes by default,
check with `python3 tost.py agent status`) only produces heartbeats with no new
information, because this loop reads that agent's cache and never fetches on its
own.
