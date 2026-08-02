"""Command implementations: fetch pipeline, summaries, rendering."""

import json
import re
import sys
from datetime import datetime, timezone

from app.diff import diff_snapshots

MODEL_NAMES = {"m3": "Model 3", "my": "Model Y", "ms": "Model S", "mx": "Model X"}

_ISO_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CHANGES = 2
EXIT_AUTH_REQUIRED = 3


def _dig(data, *path):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def extract_summary(ref, entry):
    order = entry.get("order", {}) or {}
    details = entry.get("details", {}) or {}
    tasks = details.get("tasks", {}) or {}
    order_info = _dig(tasks, "registration", "orderDetails") or {}

    vin = (
        _dig(tasks, "deliveryDetails", "regData", "orderDetails", "vin")
        or _dig(tasks, "registration", "orderDetails", "vin")
        or order.get("vin")
    )
    odometer = order_info.get("vehicleOdometer")
    odometer_type = order_info.get("vehicleOdometerType")
    model_code = (order.get("modelCode") or "").lower()

    return {
        "order_id": ref,
        "status": order.get("orderStatus"),
        "model": MODEL_NAMES.get(model_code, order.get("modelCode")),
        "vin": vin,
        "delivery_window": _dig(tasks, "scheduling", "deliveryWindowDisplay"),
        "delivery_appointment": _dig(tasks, "scheduling", "deliveryAppointmentDate"),
        "delivery_center": _dig(tasks, "scheduling", "deliveryAddressTitle"),
        "eta_to_delivery_center": _dig(tasks, "finalPayment", "data", "etaToDeliveryCenter"),
        "odometer": f"{odometer} {odometer_type}" if odometer is not None and odometer_type else None,
        "ordered_at": order_info.get("orderBookedDate") or order_info.get("orderPlacedDate"),
        "options": order.get("mktOptions"),
    }


# Snapshot fields that carry a historical date worth a timeline entry of its
# own (they predate our tracking). path-in-details -> event key.
MILESTONE_FIELDS = {
    ("tasks", "registration", "regData", "startedOn"): "registration.startedOn",
}


def extract_milestones(snapshot):
    """Events for date-bearing milestone fields, stamped with their TRUE date."""
    events = []
    for ref, entry in snapshot.items():
        for path, key in MILESTONE_FIELDS.items():
            value = _dig(entry.get("details", {}) or {}, *path)
            if isinstance(value, str) and value:
                events.append({
                    "op": "milestone", "order": ref, "key": key,
                    "ts": value, "new": value,
                })
    return events


def filter_since(events, since):
    """Events strictly newer than `since`, compared as strings.

    History timestamps come in two shapes: fetch-stamped events use
    "2026-07-31T02:51:54Z", backfilled milestones carry their own historic
    value with no trailing Z. Lexicographic order is correct across both for
    the date and time components, and it matches the sort key cmd_timeline
    already uses, so no timestamp parsing is introduced.
    """
    return [e for e in events if e.get("ts", "") > since]


def run_fetch(store, get_snapshot, now_iso):
    """Fetch pipeline: snapshot -> diff -> backfill milestones -> persist."""
    with store.lock():
        old = store.load_latest()
        new = get_snapshot()
        events = diff_snapshots(old, new)

        recorded = {(e["op"], e.get("order"), e.get("key"))
                    for e in store.read_history()}
        backfill = [m for m in extract_milestones(new)
                    if ("milestone", m["order"], m["key"]) not in recorded]

        # milestone events carry their own historic ts, overriding the stamp
        store.append_history(events + backfill, ts=now_iso)
        store.save_latest(new, fetched_at=now_iso)
        archived = store.archive_if_changed(new, ts=now_iso)
        _, sha = store.canonical_sha256(new)
        store.record_observation(ts=now_iso, sha=sha, archive=archived)
    return events


# ---------------------------------------------------------------------------
# Command layer (thin; everything above is unit-tested)
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_line(event):
    op = event["op"]
    if op == "milestone":
        return f"[{event['order']}] {event['key']} = {event.get('new')}"
    if op == "discovered":
        return f"[{event['order']}] order discovered"
    if op == "vanished":
        return f"[{event['order']}] order no longer in account"
    if op == "added":
        return f"[{event['order']}] + {event['key']} = {event.get('new')!r}"
    if op == "removed":
        return f"[{event['order']}] - {event['key']} (was {event.get('old')!r})"
    return f"[{event['order']}] {event['key']}: {event.get('old')!r} -> {event.get('new')!r}"


def _print_summary(summary):
    labels = [
        ("order_id", "Order"),
        ("status", "Status"),
        ("model", "Model"),
        ("vin", "VIN"),
        ("delivery_window", "Delivery window"),
        ("delivery_appointment", "Appointment"),
        ("delivery_center", "Delivery center"),
        ("eta_to_delivery_center", "ETA to center"),
        ("odometer", "Odometer"),
        ("ordered_at", "Ordered at"),
    ]
    for key, label in labels:
        value = summary.get(key)
        print(f"  {label:16} {value if value is not None else 'n/a'}")


def _authed_snapshot():
    from app import api, auth

    token = auth.get_access_token()
    return api.fetch_snapshot(token)


def cmd_fetch(args, store):
    from app import auth, notify

    try:
        events = run_fetch(store, _authed_snapshot, _now_iso())
    except auth.AuthRequired as e:
        if args.notify:
            notify.send("TOST", "Tesla re-authentication required (run: tost auth)")
        print(f"auth required: {e}", file=sys.stderr)
        return EXIT_AUTH_REQUIRED
    except Exception as e:
        if args.notify:
            state = store.load_agent_state()
            failures = state.get("consecutive_failures", 0) + 1
            state["consecutive_failures"] = failures
            store.save_agent_state(state)
            if failures >= 3:
                notify.send("TOST", f"fetch failing repeatedly ({failures}x): {e}")
        print(f"fetch failed: {e}", file=sys.stderr)
        return EXIT_ERROR

    if args.notify:
        state = store.load_agent_state()
        if state.get("consecutive_failures"):
            state["consecutive_failures"] = 0
            store.save_agent_state(state)

    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    elif events:
        print(f"{len(events)} change(s):")
        for event in events:
            print(f"  {_event_line(event)}")
    elif not args.quiet:
        print("no changes")

    if events and args.notify:
        first = _event_line(events[0])
        more = f" (+{len(events) - 1} more)" if len(events) > 1 else ""
        notify.send("TOST", f"{first}{more}")
    return EXIT_CHANGES if events else EXIT_OK


def cmd_status(args, store, snapshot_fn=None):
    if not args.cached:
        try:
            run_fetch(store, snapshot_fn or _authed_snapshot, _now_iso())
        except Exception as e:
            if store.load_latest():
                print(f"(fetch failed: {e} — showing cached data)", file=sys.stderr)
            else:
                print(f"fetch failed: {e}", file=sys.stderr)
                from app.auth import AuthRequired
                return EXIT_AUTH_REQUIRED if isinstance(e, AuthRequired) else EXIT_ERROR
    latest = store.load_latest()
    if not latest:
        print("no data yet — run: tost fetch", file=sys.stderr)
        return EXIT_ERROR
    summaries = [extract_summary(ref, entry) for ref, entry in latest.items()]
    if args.json:
        print(json.dumps(
            {"fetched_at": store.load_fetched_at(), "orders": summaries},
            ensure_ascii=False, indent=2,
        ))
    else:
        print(f"fetched at: {store.load_fetched_at()}")
        for summary in summaries:
            print()
            _print_summary(summary)
    return EXIT_OK


def cmd_timeline(args, store):
    since = getattr(args, "since", None)
    if since is not None and not _ISO_DATE_PREFIX.match(since):
        # Falling back to "no filter" would dump the whole history and make a
        # polling agent re-report everything; fail loudly instead.
        print(f"invalid --since {since!r}: expected an ISO timestamp such as "
              "2026-07-31T02:51:54Z", file=sys.stderr)
        return EXIT_ERROR
    # chronological by event time (backfilled milestones predate recording order)
    events = sorted(store.read_history(), key=lambda e: e.get("ts", ""))
    if since is not None:
        events = filter_since(events, since)
    if args.n:
        events = events[-args.n:]
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not events:
        print("no history yet — run: tost fetch", file=sys.stderr)
        return EXIT_OK
    current_day = None
    for event in events:
        day = event.get("ts", "")[:10]
        if day != current_day:
            current_day = day
            print(f"\n{day}")
        print(f"  {event.get('ts', '')[11:16]}  {_event_line(event)}")
    return EXIT_OK


def cmd_export(args, store):
    """One JSON document with everything a dashboard needs."""
    print(json.dumps({
        "fetched_at": store.load_fetched_at(),
        "orders": [extract_summary(ref, entry)
                   for ref, entry in store.load_latest().items()],
        "events": store.read_history(),
        "observations": store.read_observations(),
        "archives": store.list_archives(),
    }, ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_raw(args, store):
    latest = store.load_latest()
    if args.order:
        latest = {k: v for k, v in latest.items() if k == args.order}
    print(json.dumps(latest, ensure_ascii=False, indent=2))
    return EXIT_OK
