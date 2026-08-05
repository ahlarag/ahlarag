"""Validación del flujo de carga radial."""

from __future__ import annotations

import math

import pytest

from electric_gis import Feeder, Load, Network, Node, VoltageLevel, solve
from electric_gis.loadflow import LoadFlowError
from electric_gis.sample_network import ACSR_4_0, MV, build_sample_network


def build_two_node_feeder(load_kw: float = 1000.0, load_kvar: float = 0.0) -> Network:
    """Circuito mínimo de un tramo, verificable a mano."""
    network = Network()
    network.add_node(Node(id="BUS", voltage_level=MV, is_source=True, node_type="substation_busbar"))
    network.add_node(Node(id="END", voltage_level=MV, node_type="pole_connection"))
    network.add_line("L1", "BUS", "END", length_m=1000.0, feeder="F", **ACSR_4_0)
    network.add_feeder(Feeder(code="F", source_node="BUS", rated_current_a=400.0))
    network.add_load(Load(node="END", p_kw=load_kw, q_kvar=load_kvar, phases=3, customers=10))
    return network


def test_two_node_feeder_matches_hand_calculation():
    network = build_two_node_feeder()
    result = solve(network)

    assert result.converged

    # Corriente esperada de un circuito trifásico con carga de potencia
    # constante: I = S por fase entre la tensión fase-neutro resultante.
    voltage_ln = result.nodes["END"].voltage_v
    expected_current = (1000.0 * 1000.0 / 3.0) / voltage_ln
    assert result.edges["L1"].current_a == pytest.approx(expected_current, rel=1e-6)

    # Caída de tensión con factor de potencia unitario: I por la resistencia.
    resistance = ACSR_4_0["r1_ohm_km"] * 1.0
    expected_drop = expected_current * resistance
    assert MV.nominal_ln_v - voltage_ln == pytest.approx(expected_drop, abs=0.05)

    # Pérdidas trifásicas: tres veces I al cuadrado por la resistencia.
    expected_loss_kw = 3.0 * (expected_current**2) * resistance / 1000.0
    assert result.edges["L1"].loss_kw == pytest.approx(expected_loss_kw, rel=1e-6)
    assert result.edges["L1"].loss_kw == pytest.approx(1.44, abs=0.05)


def test_power_balance_is_conserved():
    result = solve(build_sample_network())

    assert result.converged
    assert result.served_load_kw == pytest.approx(50.0 + 25.0 + 60.0)
    assert result.power_balance_error_kw == pytest.approx(0.0, abs=1e-6)
    assert result.total_loss_kw > 0.0


def test_voltage_decreases_towards_the_end_of_the_feeder():
    result = solve(build_sample_network())

    trunk = ["BUS-A", "A1", "A2", "A3", "A4"]
    voltages = [result.nodes[node].voltage_pu for node in trunk]
    assert voltages == sorted(voltages, reverse=True)

    # La red de baja tensión acumula la caída del transformador y del tramo BT.
    assert result.nodes["A4C"].voltage_pu < result.nodes["A4"].voltage_pu


def test_single_phase_branch_uses_neutral_return_impedance():
    """El lazo monofásico tiene el doble de impedancia que la fase sola."""
    network = build_sample_network()

    single_phase = network.edges["LV-A2"]
    length_km = single_phase.length_m / 1000.0
    assert single_phase.r_ohm == pytest.approx(0.53 * length_km * 2.0)

    three_phase = network.edges["LV-A1"]
    assert three_phase.r_ohm == pytest.approx(0.27 * (three_phase.length_m / 1000.0))


def test_feeder_results_are_attributed_per_circuit():
    result = solve(build_sample_network())

    assert set(result.feeders) == {"F1", "F2"}
    assert result.feeders["F1"].customers == 70
    assert result.feeders["F2"].customers == 50
    assert result.feeders["F1"].load_kw == pytest.approx(75.0)

    # La corriente de cabecera debe ser coherente con la potencia del circuito.
    feeder = result.feeders["F1"]
    apparent_kva = math.hypot(feeder.p_kw, feeder.q_kvar)
    expected_current = apparent_kva * 1000.0 / (math.sqrt(3.0) * MV.nominal_kv * 1000.0)
    assert feeder.current_a == pytest.approx(expected_current, rel=0.02)


def test_transformer_ratio_steps_down_voltage():
    result = solve(build_sample_network())

    mv_voltage = result.nodes["A4"].voltage_v
    lv_voltage = result.nodes["A4LV"].voltage_v
    assert lv_voltage < mv_voltage / 50.0
    assert result.nodes["A4LV"].voltage_pu < 1.0


def test_deenergized_loads_are_reported_as_unserved():
    network = build_sample_network()
    result = solve(network, force_open=["BRK-F1"])

    unserved_nodes = {load.node for load in result.unserved_loads}
    assert unserved_nodes == {"A4C", "A5C"}
    assert result.served_load_kw == pytest.approx(60.0)


def test_non_radial_network_is_rejected():
    network = build_sample_network()

    with pytest.raises(LoadFlowError, match="no es radial"):
        solve(network, force_close=["TIE-A5-B4"])


def test_overload_is_detected():
    network = build_two_node_feeder(load_kw=9000.0, load_kvar=3000.0)
    result = solve(network)

    overloads = result.overloads()
    assert "L1" in {item.element for item in overloads}
    assert result.edges["L1"].loading_pct > 100.0


def test_undervoltage_is_detected():
    voltage_level = VoltageLevel.three_phase("13.8kV", 13.8, "medium")
    network = Network()
    network.add_node(Node(id="BUS", voltage_level=voltage_level, is_source=True))
    network.add_node(Node(id="END", voltage_level=voltage_level))
    network.add_line("L1", "BUS", "END", length_m=25000.0, feeder="F", **ACSR_4_0)
    network.add_feeder(Feeder(code="F", source_node="BUS", rated_current_a=400.0))
    network.add_load(Load(node="END", p_kw=3000.0, q_kvar=1000.0, phases=3, customers=500))

    result = solve(network)
    violations = result.voltage_violations()

    assert [item.kind for item in violations] == ["undervoltage"]
    assert result.min_voltage_pu < 0.95
