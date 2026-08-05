"""Validación de los índices de confiabilidad."""

from __future__ import annotations

import pytest

from electric_gis import CustomerInterruption, compute_indices, estimate_energy_not_served_kwh


def test_indices_of_a_single_sustained_interruption():
    interruptions = [
        CustomerInterruption(service_point="SP-1", customers=100, duration_min=120.0, feeder="F1")
    ]
    indices = compute_indices(interruptions, total_customers=1000)

    assert indices.saifi == pytest.approx(0.1)
    assert indices.saidi_min == pytest.approx(12.0)
    assert indices.caidi_min == pytest.approx(120.0)
    assert indices.maifi == pytest.approx(0.0)


def test_staged_restoration_is_measured_per_customer_group():
    """Cada grupo recupera el servicio en un momento distinto."""
    interruptions = [
        CustomerInterruption(service_point="SP-1", customers=70, duration_min=45.0, feeder="F1"),
        CustomerInterruption(service_point="SP-2", customers=160, duration_min=300.0, feeder="F1"),
    ]
    indices = compute_indices(interruptions, total_customers=370)

    assert indices.customer_interruptions == 230
    assert indices.customer_minutes == pytest.approx(70 * 45.0 + 160 * 300.0)
    assert indices.saifi == pytest.approx(230 / 370)
    assert indices.saidi_min == pytest.approx((70 * 45.0 + 160 * 300.0) / 370)


def test_momentary_interruptions_go_to_maifi():
    interruptions = [
        CustomerInterruption(
            service_point="SP-1", customers=200, duration_min=0.5, outage_class="momentary"
        ),
        CustomerInterruption(service_point="SP-2", customers=50, duration_min=60.0),
    ]
    indices = compute_indices(interruptions, total_customers=1000)

    assert indices.maifi == pytest.approx(0.2)
    assert indices.saifi == pytest.approx(0.05)
    assert indices.customer_minutes == pytest.approx(3000.0)


def test_short_interruption_below_the_threshold_is_momentary():
    interruptions = [CustomerInterruption(service_point="SP-1", customers=10, duration_min=2.0)]
    indices = compute_indices(interruptions, total_customers=100)

    assert indices.saifi == pytest.approx(0.0)
    assert indices.maifi == pytest.approx(0.1)


def test_planned_interruptions_can_be_excluded():
    interruptions = [
        CustomerInterruption(
            service_point="SP-1", customers=100, duration_min=240.0, outage_class="planned"
        ),
        CustomerInterruption(service_point="SP-2", customers=50, duration_min=60.0),
    ]

    with_planned = compute_indices(interruptions, total_customers=1000)
    without_planned = compute_indices(interruptions, total_customers=1000, include_planned=False)

    assert with_planned.customer_interruptions == 150
    assert without_planned.customer_interruptions == 50


def test_asai_reflects_availability():
    interruptions = [CustomerInterruption(service_point="SP-1", customers=1000, duration_min=525.6)]
    indices = compute_indices(interruptions, total_customers=1000, period_hours=8760.0)

    # 525,6 minutos sobre un año equivalen a una disponibilidad del 99,9 por ciento.
    assert indices.asai_pct == pytest.approx(99.9, abs=1e-6)


def test_indices_can_be_grouped_by_feeder():
    interruptions = [
        CustomerInterruption(service_point="SP-1", customers=100, duration_min=60.0, feeder="F1"),
        CustomerInterruption(service_point="SP-2", customers=40, duration_min=30.0, feeder="F2"),
    ]
    indices = compute_indices(interruptions, total_customers=1000, group_by_feeder=True)

    assert set(indices.by_feeder) == {"F1", "F2"}
    assert indices.by_feeder["F1"].saidi_min == pytest.approx(60.0)
    assert indices.by_feeder["F2"].saidi_min == pytest.approx(30.0)


def test_energy_not_served():
    assert estimate_energy_not_served_kwh(load_kw=200.0, duration_min=90.0) == pytest.approx(300.0)
    assert estimate_energy_not_served_kwh(
        load_kw=200.0, duration_min=90.0, load_factor=0.6
    ) == pytest.approx(180.0)


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        compute_indices([], total_customers=0)
    with pytest.raises(ValueError):
        CustomerInterruption(service_point="SP", customers=1, duration_min=-1.0)
    with pytest.raises(ValueError):
        estimate_energy_not_served_kwh(load_kw=10.0, duration_min=10.0, load_factor=0.0)
