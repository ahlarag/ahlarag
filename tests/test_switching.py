"""Validación de maniobras, transferencias y restauración."""

from __future__ import annotations

import pytest

from electric_gis import (
    Load,
    apply_switching,
    evaluate_scenario,
    evaluate_transfer,
    plan_fault_restoration,
    plan_planned_work,
    rank_transfer_options,
    unsupplied_customers,
)
from electric_gis.sample_network import build_sample_network


def test_closing_the_tie_without_opening_a_point_is_not_feasible():
    network = build_sample_network()
    assessment = evaluate_scenario(network, force_close=["TIE-A5-B4"])

    assert not assessment.radial
    assert not assessment.feasible
    assert "anillo" in assessment.reasons[0]


def test_transfer_with_an_open_point_is_feasible():
    network = build_sample_network()
    assessment = evaluate_transfer(network, "TIE-A5-B4", open_devices=["SEC-A4"])

    assert assessment.radial
    assert assessment.feasible
    assert assessment.customers_restored == 30
    assert assessment.customers_interrupted == 0
    assert assessment.load_flow is not None

    # Tras la transferencia el ramal queda alimentado desde el otro circuito.
    assert assessment.load_flow.feeders["F2"].customers == 80
    assert assessment.load_flow.feeders["F1"].customers == 40


def test_planned_work_isolates_the_minimum_zone():
    network = build_sample_network()
    plan = plan_planned_work(network, "L-A3-A4")

    actions = {(step.device, step.action) for step in plan.steps}
    assert ("REC-A2", "open") in actions
    assert ("SEC-A4", "open") in actions
    assert any(step.action == "verify_open" for step in plan.steps)

    assert plan.assessment is not None
    assert plan.assessment.customers_interrupted == 70


def test_fault_downstream_of_a_sectionalizer_restores_upstream_customers():
    """Falla en el ramal: el reconectador puede reponerse tras aislar."""
    network = build_sample_network()
    plan = plan_fault_restoration(network, "L-A4B-A5")

    steps = [(step.device, step.action) for step in plan.steps]
    assert ("SEC-A4", "open") in steps
    assert ("REC-A2", "close") in steps

    # El enlace de transferencia queda dentro de la zona fallada, por lo que
    # cerrarlo reenergizaría la falla y debe descartarse.
    assert ("TIE-A5-B4", "close") not in steps
    assert any("reenergizaría" in note for note in plan.notes)

    assert plan.customers_still_out == 30


def test_fault_next_to_the_recloser_keeps_it_open_and_transfers_downstream():
    """Falla inmediatamente aguas abajo de la protección.

    No hay seccionamiento intermedio, por lo que el reconectador permanece
    abierto y el tramo sano aguas abajo se recupera por transferencia.
    """
    network = build_sample_network()
    plan = plan_fault_restoration(network, "L-A3-A4")

    steps = [(step.device, step.action) for step in plan.steps]
    assert ("SEC-A4", "open") in steps
    assert ("REC-A2", "close") not in steps
    assert ("REC-A2", "verify_open") in steps
    assert ("TIE-A5-B4", "close") in steps

    assert any("debe permanecer abierto" in note for note in plan.notes)
    assert plan.customers_still_out == 40


def test_ranking_prefers_feasible_options():
    network = build_sample_network()
    options = rank_transfer_options(network, "F1", open_devices=["SEC-A4"])

    assert options
    assert options[0].feasible
    assert options[0].force_close == ("TIE-A5-B4",)


def test_transfer_is_rejected_when_the_backup_circuit_gets_overloaded():
    network = build_sample_network()

    # Cliente industrial atendido en media tensión al final del ramal. Al
    # transferirlo, el troncal del circuito de respaldo queda sobrecargado.
    network.add_load(
        Load(node="A5", p_kw=9000.0, q_kvar=3000.0, phases=3, customers=1, label="Industrial MT")
    )

    assessment = evaluate_transfer(network, "TIE-A5-B4", open_devices=["SEC-A4"])

    assert assessment.radial
    assert not assessment.feasible
    assert "L-B3-B4" in {item.element for item in assessment.overloads}
    assert any("Sobrecarga" in reason for reason in assessment.reasons)


def test_unsupplied_customers_counts_the_whole_affected_area():
    network = build_sample_network()

    assert unsupplied_customers(network) == 0
    assert unsupplied_customers(network, force_open=["BRK-F1"]) == 70
    assert unsupplied_customers(network, force_open=["SEC-A4"]) == 30


def test_apply_switching_persists_the_resulting_state():
    network = build_sample_network()
    plan = plan_fault_restoration(network, "L-A3-A4")
    apply_switching(network, plan)

    assert network.edges["SEC-A4"].closed is False
    assert network.edges["TIE-A5-B4"].closed is True
    assert unsupplied_customers(network) == 40


def test_unknown_element_raises():
    network = build_sample_network()
    with pytest.raises(KeyError):
        plan_fault_restoration(network, "NO-EXISTE")
