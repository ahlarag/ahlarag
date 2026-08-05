"""Validación del trazado de topología."""

from __future__ import annotations

from electric_gis import (
    build_feeder_tree,
    check_radiality,
    customers_impacted,
    deenergized_loads,
    energized_nodes,
    protection_zone,
    transfer_candidates,
    upstream_protective_device,
    zone_for_edge,
)
from electric_gis.sample_network import build_sample_network


def test_whole_network_is_energized_in_normal_state():
    network = build_sample_network()
    live = energized_nodes(network)

    assert live == set(network.nodes)
    assert deenergized_loads(network) == []


def test_tie_switch_is_open_in_normal_state():
    network = build_sample_network()
    assert network.edges["TIE-A5-B4"].closed is False
    assert network.edges["TIE-A5-B4"].is_tie is True


def test_opening_the_head_breaker_deenergizes_the_whole_feeder():
    network = build_sample_network()
    live = energized_nodes(network, force_open=["BRK-F1"])

    assert "A1" not in live
    assert "A4C" not in live
    assert "B3C" in live

    impact = customers_impacted(network, force_open=["BRK-F1"])
    assert impact["interrupted"] == 70
    assert impact["restored"] == 0


def test_opening_a_sectionalizing_point_only_affects_downstream_customers():
    network = build_sample_network()
    impact = customers_impacted(network, force_open=["SEC-A4"])

    assert impact["interrupted"] == 30
    assert impact["priority_interrupted"] == 0


def test_priority_customers_are_reported():
    network = build_sample_network()
    impact = customers_impacted(network, force_open=["BRK-F2"])

    assert impact["interrupted"] == 50
    assert impact["priority_interrupted"] == 50


def test_normal_state_is_radial_and_closing_the_tie_is_not():
    network = build_sample_network()

    radial, violations = check_radiality(network)
    assert radial
    assert violations == []

    radial, violations = check_radiality(network, force_close=["TIE-A5-B4"])
    assert not radial
    assert violations == ["TIE-A5-B4"]


def test_feeder_tree_orders_nodes_from_the_source():
    network = build_sample_network()
    tree = build_feeder_tree(network, "HV-A")

    assert tree.is_radial
    assert tree.order[0] == "HV-A"
    assert tree.parent_node["A2"] == "A1"
    assert tree.parent_edge["A2"] == "L-A1-A2"
    assert tree.order.index("A1") < tree.order.index("A5")
    assert "B1" not in tree.nodes()


def test_upstream_protective_device_ignores_non_interrupting_switches():
    network = build_sample_network()

    # Aguas arriba de A4B hay un seccionador y luego el reconectador. El
    # seccionador no interrumpe corriente de falla.
    device = upstream_protective_device(network, "A4B")
    assert device is not None
    assert device.id == "REC-A2"

    assert upstream_protective_device(network, "A1").id == "BRK-F1"


def test_protection_zone_is_bounded_by_switching_devices():
    network = build_sample_network()
    zone = protection_zone(network, "A4")

    assert "A4" in zone.nodes
    assert "A4LV" in zone.nodes
    assert "A4C" in zone.nodes
    assert "A5" not in zone.nodes
    assert set(zone.boundary_devices) == {"REC-A2", "SEC-A4"}


def test_zone_for_a_faulted_line_contains_both_ends():
    network = build_sample_network()
    zone = zone_for_edge(network, "L-A3-A4")

    assert {"A3", "A4"} <= zone.nodes
    assert set(zone.boundary_devices) == {"REC-A2", "SEC-A4"}


def test_transfer_candidate_is_found_for_dead_load_pickup():
    network = build_sample_network()
    candidates = transfer_candidates(network, "F1", force_open=["SEC-A4"])

    assert [edge.id for edge in candidates] == ["TIE-A5-B4"]


def test_transfer_candidate_is_found_between_live_circuits():
    network = build_sample_network()
    candidates = transfer_candidates(network, "F1")

    assert [edge.id for edge in candidates] == ["TIE-A5-B4"]
