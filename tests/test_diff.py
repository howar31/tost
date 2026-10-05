import unittest

from app.diff import diff_dicts, diff_snapshots, filter_ignored


class TestDiffDicts(unittest.TestCase):
    def test_changed_value_reported_with_dot_path(self):
        events = diff_dicts({"a": {"b": 1}}, {"a": {"b": 2}})
        self.assertEqual(
            events, [{"op": "changed", "key": "a.b", "old": 1, "new": 2}]
        )

    def test_added_key_reported(self):
        events = diff_dicts({"a": 1}, {"a": 1, "b": "x"})
        self.assertEqual(events, [{"op": "added", "key": "b", "new": "x"}])

    def test_removed_key_reported(self):
        events = diff_dicts({"a": 1, "b": "x"}, {"a": 1})
        self.assertEqual(events, [{"op": "removed", "key": "b", "old": "x"}])

    def test_equal_dicts_produce_no_events(self):
        self.assertEqual(diff_dicts({"a": {"b": [1, 2]}}, {"a": {"b": [1, 2]}}), [])

    def test_changed_list_reported_as_single_change(self):
        events = diff_dicts({"a": [1, 2]}, {"a": [1, 3]})
        self.assertEqual(
            events, [{"op": "changed", "key": "a", "old": [1, 2], "new": [1, 3]}]
        )

    def test_dict_replaced_by_scalar_reported_as_change(self):
        events = diff_dicts({"a": {"b": 1}}, {"a": 5})
        self.assertEqual(
            events, [{"op": "changed", "key": "a", "old": {"b": 1}, "new": 5}]
        )


class TestFilterIgnored(unittest.TestCase):
    def test_ignored_prefix_dropped(self):
        events = [
            {"op": "changed", "key": "details.strings.foo", "old": 1, "new": 2},
            {"op": "changed", "key": "details.tasks.scheduling.deliveryWindowDisplay",
             "old": "May", "new": "June"},
        ]
        kept = filter_ignored(events)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["key"],
                         "details.tasks.scheduling.deliveryWindowDisplay")

    def test_exact_ignored_key_dropped(self):
        events = [{"op": "changed", "key": "details.tasks.finalPayment.data.vehicleId",
                   "old": None, "new": 1}]
        self.assertEqual(filter_ignored(events), [])

    def test_match_flags_kept(self):
        events = [
            {"op": "changed", "key": "details.tasks.scheduling.isInventoryOrMatched",
             "old": True, "new": False},
            {"op": "changed", "key": "details.tasks.tradeIn.isMatched",
             "old": True, "new": False},
        ]
        self.assertEqual(filter_ignored(events), events)

    def test_order_level_vin_kept(self):
        # order.vin is populated before any task-level VIN location.
        events = [{"op": "added", "key": "order.vin", "new": "5YJ00000000000000"}]
        self.assertEqual(filter_ignored(events), events)

    def test_vehicle_model_year_kept(self):
        events = [{"op": "added",
                   "key": "details.tasks.registration.orderDetails.vehicleModelYear",
                   "new": "2027"}]
        self.assertEqual(filter_ignored(events), events)


class TestDiffSnapshots(unittest.TestCase):
    def test_new_order_emits_discovered_event(self):
        new = {"RN123": {"order": {"referenceNumber": "RN123"}, "details": {}}}
        events = diff_snapshots({}, new)
        self.assertEqual(
            events, [{"op": "discovered", "order": "RN123", "key": "", }]
        )

    def test_changed_order_events_carry_order_ref(self):
        old = {"RN1": {"order": {"orderStatus": "BOOKED"}, "details": {"tasks": {}}}}
        new = {"RN1": {"order": {"orderStatus": "DELIVERED"}, "details": {"tasks": {}}}}
        events = diff_snapshots(old, new)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["order"], "RN1")
        self.assertEqual(events[0]["key"], "order.orderStatus")
        self.assertEqual(events[0]["op"], "changed")

    def test_removed_order_emits_removed_event(self):
        old = {"RN1": {"order": {}, "details": {}}}
        events = diff_snapshots(old, {})
        self.assertEqual(events, [{"op": "vanished", "order": "RN1", "key": ""}])

    def test_vin_assigned_at_order_level_only_is_reported(self):
        old = {"RN1": {"order": {"orderStatus": "BOOKED"}, "details": {"tasks": {}}}}
        new = {"RN1": {"order": {"orderStatus": "BOOKED",
                                 "vin": "5YJ00000000000000"},
                       "details": {"tasks": {}}}}
        self.assertEqual(
            diff_snapshots(old, new),
            [{"op": "added", "key": "order.vin", "new": "5YJ00000000000000",
              "order": "RN1"}],
        )

    def test_noise_keys_filtered_from_order_diff(self):
        old = {"RN1": {"order": {}, "details": {"strings": {"a": 1}}}}
        new = {"RN1": {"order": {}, "details": {"strings": {"a": 2}}}}
        self.assertEqual(diff_snapshots(old, new), [])


if __name__ == "__main__":
    unittest.main()
