"""Pure snapshot-diff functions. No I/O, no network."""

# Noisy paths that flap without carrying information: localized UI strings,
# per-response layout "card" blobs, duplicated VIN locations, and internal
# flags that toggle without an order-state meaning.
# Entries ending with "." are prefixes; others match exactly.
IGNORED_KEYS = {
    "order.vin",  # duplicated at details.tasks.deliveryDetails.regData.orderDetails.vin
    "details.tasks.registration.orderDetails.vin",
    "details.tasks.registration.regData.orderDetails.vin",
    "details.tasks.finalPayment.data.vin",
    "details.tasks.tradeIn.isMatched",
    "details.tasks.registration.isMatched",
    "details.tasks.registration.orderDetails.vehicleModelYear",
    "details.state.",
    "details.strings.",
    "details.scheduling.card.",
    "details.scheduling.strings.",
    "details.tasks.carbonCredit.card.",
    "details.tasks.carbonCredit.strings.",
    "details.tasks.finalPayment.card.",
    "details.tasks.finalPayment.strings.",
    "details.tasks.scheduling.card.",
    "details.tasks.scheduling.strings.",
    "details.tasks.scheduling.isDeliveryEstimatesEnabled",
    "details.tasks.registration.orderDetails.isAvailableForMatch",
    "details.tasks.finalPayment.data.isAvailableForMatch",
    "details.tasks.finalPayment.data.deliveryReadinessDetail.",
    "details.tasks.finalPayment.data.deliveryReadiness.",
    "details.tasks.finalPayment.data.agreementDetails",
    "details.tasks.finalPayment.data.vehicleId",
    "details.tasks.deliveryAcceptance.gates",
    "details.tasks.deliveryAcceptance.card.",
    "details.tasks.deliveryAcceptance.strings.",
    "details.tasks.deliveryDetails.regData.reggieRegistrationStatus",
    "details.tasks.deliveryDetails.strings.",
    "details.tasks.deliveryDetails.card.",
    "details.tasks.registration.card.",
    "details.tasks.registration.regData.reggieRegistrationStatus",
    "details.tasks.registration.strings.",
    "details.tasks.finalPayment.complete",
    "details.tasks.finalPayment.data.finalPaymentStatus",
    "details.tasks.scheduling.apptDateTimeAddressStr",
    "details.tasks.scheduling.isInventoryOrMatched",
    "details.tasks.finalPayment.data.hasFinalInvoice",
    "details.tasks.finalPayment.data.hasActiveInvoice",
    "details.tasks.finalPayment.data.selfSchedulingDetails.",
    "details.tasks.financing.card.",
    "details.tasks.financing.strings.",
    "details.tasks.tradeIn.card.",
    "details.tasks.tradeIn.strings.",
}

_IGNORED_PREFIXES = tuple(k for k in IGNORED_KEYS if k.endswith("."))
_IGNORED_EXACT = frozenset(k for k in IGNORED_KEYS if not k.endswith("."))


def diff_dicts(old, new, prefix=""):
    """Recursively compare two dicts, returning flat change events.

    Non-dict values (including lists) are compared as opaque scalars.
    """
    events = []
    for key in old:
        path = f"{prefix}{key}"
        if key not in new:
            events.append({"op": "removed", "key": path, "old": old[key]})
        elif isinstance(old[key], dict) and isinstance(new[key], dict):
            events.extend(diff_dicts(old[key], new[key], prefix=f"{path}."))
        elif old[key] != new[key]:
            events.append(
                {"op": "changed", "key": path, "old": old[key], "new": new[key]}
            )
    for key in new:
        if key not in old:
            events.append({"op": "added", "key": f"{prefix}{key}", "new": new[key]})
    return events


def filter_ignored(events):
    """Drop events whose key is on the noise list."""
    return [
        e
        for e in events
        if e["key"] not in _IGNORED_EXACT
        and not e["key"].startswith(_IGNORED_PREFIXES)
    ]


def diff_snapshots(old_snapshot, new_snapshot):
    """Compare per-order snapshots keyed by referenceNumber.

    Returns events tagged with their order ref. New orders collapse into a
    single "discovered" event; orders missing from the new snapshot emit
    "vanished".
    """
    events = []
    for ref in old_snapshot:
        if ref not in new_snapshot:
            events.append({"op": "vanished", "order": ref, "key": ""})
    for ref, entry in new_snapshot.items():
        if ref not in old_snapshot:
            events.append({"op": "discovered", "order": ref, "key": ""})
            continue
        order_events = filter_ignored(diff_dicts(old_snapshot[ref], entry))
        for event in order_events:
            event["order"] = ref
            events.append(event)
    return events
