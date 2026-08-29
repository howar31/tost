# TOST Vessel Runbook

A procedure for an agent asked about car-carrier (RoRo / PCTC) arrivals at a
Taiwan port, or to follow a specific ship that may carry the user's vehicle.
Written to be followed literally. Do not improvise transport or hosts.

For order-status questions, use [SKILL.md](SKILL.md). For the order polling
loop, use [MONITOR.md](MONITOR.md). Answer in the user's conversation language.

## Allowed hosts — hard rule

| Host | Use | Limits |
|---|---|---|
| `tpnet.twport.com.tw` | Port arrival data (primary) | read-only GET, a few queries per session |
| `www.vesselfinder.com` | Verify a ship's type, or its position at sea | read public pages only, best-effort |
| `www.marinetraffic.com` | Same, as fallback | read public pages only, best-effort |

- Never route these requests through a third-party proxy, mirror, or CORS
  worker (e.g. `twport.xyz`, `*.workers.dev`). The TPNET endpoint below works
  directly; mirrors add an uncontrolled middleman for zero benefit.
- Never send personal data to any of these hosts. Legitimate query parameters
  are only: port code, date range, ship name. Order numbers, VINs, names, and
  addresses never leave the machine.
- These are unofficial, no-SLA sources. If one breaks, say so and stop;
  do not hunt for replacement hosts.

## Picking the port

Derive the port from the order's `delivery_center` (via
`python3 tost.py status --cached --json`), do not assume:

| Delivery center region | Port | Code |
|---|---|---|
| Taipei / northern Taiwan | 臺北港 | `TPE` |
| Taichung / central Taiwan | 臺中港 | `TXG` |
| Kaohsiung / southern Taiwan | 高雄港 | `KHH` |

Other codes: `KEL` 基隆, `SUO` 蘇澳, `HUN` 花蓮, `APG` 安平, `MZG` 澎湖,
`PUT` 布袋.

## Fetching arrivals

TPNET's XML export is a plain GET: no login, no session, no personal data.
Use `curl` for transport (the site's TLS certificate lacks a Subject Key
Identifier, which Python 3.13+ rejects under its default strict verification;
curl accepts it). The response is **Big5**-encoded XML.

```bash
curl -sG 'https://tpnet.twport.com.tw/IFAWeb/Reports/InPortShipList/DownloadXMLReport' \
  --data-urlencode 'selectPort=TPE' \
  --data-urlencode 'orderBy=etaDt' --data-urlencode 'orderAsc=ASC' \
  --data-urlencode "spExpectDtFrom=$(date +%Y/%m/%d) 00:00" \
  --data-urlencode "spExpectDtTo=$(date -v+7d +%Y/%m/%d) 23:59" \
  --data-urlencode 'special01=False' --data-urlencode 'special02=False' \
  -o "$TMPDIR/tpnet.xml"
```

- End the range at `23:59`, not `00:00` — car carriers commonly arrive at
  06:00, so a midnight cutoff silently drops the last day.
- The XML honors the full range (about 7 days of forecast). The interactive
  HTML page shows only ~36 hours; do not scrape it.
- Optional `--data-urlencode 'vesselEname=TRANS FUTURE'` filters by English
  ship-name substring — use it to follow one known ship.

Parse with stdlib only:

```bash
python3 - <<'EOF'
import xml.etree.ElementTree as ET, os
root = ET.fromstring(open(os.path.join(os.environ.get("TMPDIR", "/tmp"), "tpnet.xml"), "rb").read().decode("big5", errors="replace"))
def ts(s): return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}" if len(s) >= 12 else ""
for ship in root.iter("SHIP"):
    g = lambda k: (ship.findtext(k) or "").strip()
    if g("STA_TYPE") in ("其他專用輪", "汽車船") and float(g("LENGTH") or 0) >= 140:
        print(g("VESSEL_ENAME"), g("VESSEL_CNAME"), ts(g("EXPECT_DT")),
              "arrived:" + (ts(g("ACT_PORT_DT")) or "not yet"),
              g("WHARF_CODE"), g("BEFORE_PORT"), g("LENGTH") + "m", sep=" | ")
EOF
```

## Field meanings

| XML field | Meaning |
|---|---|
| `VESSEL_ENAME` / `VESSEL_CNAME` | Ship name (EN / ZH) |
| `STA_TYPE` | Port's vessel-type label |
| `EXPECT_DT` | Forecast port-entry time (`YYYYMMDDHHMM`) — the ETA to report |
| `ACT_PORT_DT` | Actual entry time; empty means not arrived yet |
| `RESERVE_BERTH_TIME` | Forecast berthing time |
| `WHARF_CODE` | Wharf (南5碼頭 is the main vehicle wharf at TPE) |
| `BEFORE_PORT` | Immediately previous port of call only, not the origin |
| `GOAL_ARRIVAL` | Purpose: 卸…貨 unloading (imports), 裝…貨 loading (exports) |
| `LENGTH` / `GROSS_TOA` | Length (m) / gross tonnage |
| `PBG_NAME` | Local shipping agent |

## Identifying car carriers

Taiwan's ports have no dedicated car-carrier category: PCTCs land in
`其他專用輪` ("other special-purpose vessel"), alongside offshore-wind
installation ships, heavy-lift ships, and work boats. The
`type + length >= 140m` filter above is a heuristic, not ground truth.

- Known false positives: offshore-wind vessels (e.g. GREEN JADE 環海翡翠,
  203 m), heavy-lift ships. A previous port at a wind-farm site, or purpose
  裝非兩岸貨 with no car-trade route, are giveaways.
- When the answer hinges on one specific ship, verify it: search the ship
  name with IMO on vesselfinder or marinetraffic and confirm the type says
  "Vehicles Carrier". Real PCTCs are ~150–200 m and ~15,000–77,000 GT.
- Ships under 140 m may still be small regional RoRos; mention them only if
  a name-specific query surfaced them.

## Interpretation rules

- Never claim a particular ship carries the user's vehicle. Port data shows
  which car carriers arrive, not whose cars are aboard. Cross-check the order
  itself (`eta_to_delivery_center` in tost status, VIN timing) and say plainly
  what is confirmed versus inferred.
- Berlin-built vehicles sail from Europe (~30–40 days); `BEFORE_PORT` will
  show the last stop (often Singapore or another Asian port), not Germany.
  Do not treat a Shanghai or Nagoya previous port as evidence about
  European-built orders.
- Which ship was loaded with Taiwan-bound Teslas is community intelligence
  (forums, owner groups), found via ordinary web search. Label it unverified.
- Every report of a heuristic-filtered list ends with this caveat line,
  translated to the conversation language: 船種依港務資料推斷,未逐船驗證;
  預報時間仍可能異動。
- Forecasts shift; quote `EXPECT_DT` as "預計", and `ACT_PORT_DT` as fact.
- This data changes slowly. Do not poll more than a few times per day; in a
  monitoring loop, once per round at most.
