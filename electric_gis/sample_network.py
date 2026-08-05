"""Red de ejemplo con dos subestaciones y un enlace de transferencia.

Sirve como caso de referencia para validar el trazado, el flujo de carga y las
maniobras. La topología reproduce una configuración habitual de distribución:

    Subestación A            Subestación B
    34,5 kV                  34,5 kV
      | transformador           | transformador
    13,8 kV barra            13,8 kV barra
      | interruptor             | interruptor
    troncal MT               troncal MT
      | reconectador            | reconectador
    troncal MT               troncal MT
      | seccionador
    ramal MT ----- enlace normalmente abierto ----- troncal MT

Los transformadores de distribución derivan a redes de baja tensión con clientes
agrupados por punto de servicio.
"""

from __future__ import annotations

from .model import Feeder, Load, Network, Node, VoltageLevel

# Niveles de tensión. En baja tensión se declaran los dos casos habituales:
# trifásico 208/120 V, donde la carga se sirve a 120 V fase-neutro, y el servicio
# monofásico de dos hilos a 240 V, donde la carga se sirve entre conductores y por
# eso la tensión de cálculo es la propia 240 V.
SUB_HV = VoltageLevel.three_phase("34.5kV", 34.5, "subtransmission")
MV = VoltageLevel.three_phase("13.8kV", 13.8, "medium")
LV_THREE_PHASE = VoltageLevel.three_phase("208/120V", 0.208, "low")
LV_SINGLE_PHASE = VoltageLevel("240V", 0.24, 0.24, "low")

# Conductores típicos de distribución.
ACSR_4_0 = {"r1_ohm_km": 0.2745, "x1_ohm_km": 0.4200, "ampacity_a": 340.0}
ACSR_2 = {"r1_ohm_km": 0.8580, "x1_ohm_km": 0.4500, "ampacity_a": 180.0}
LV_TRIPLEX_4_0 = {"r1_ohm_km": 0.2700, "x1_ohm_km": 0.0800, "ampacity_a": 230.0}
LV_TRIPLEX_1_0 = {"r1_ohm_km": 0.5300, "x1_ohm_km": 0.0900, "ampacity_a": 150.0}


def build_sample_network() -> Network:
    """Construye la red de ejemplo completa."""
    network = Network()

    _build_substation(network, "A", feeder_code="F1")
    _build_substation(network, "B", feeder_code="F2")
    _build_feeder_a(network)
    _build_feeder_b(network)

    # Enlace normalmente abierto entre el ramal de F1 y el troncal de F2.
    network.add_switch(
        id="TIE-A5-B4",
        from_node="A5",
        to_node="B4",
        device_type="tie_switch",
        closed=False,
        feeder=None,
        ampacity_a=400.0,
        is_tie=True,
        remote_controlled=True,
    )

    return network


def _build_substation(network: Network, suffix: str, feeder_code: str) -> None:
    network.add_node(
        Node(id=f"HV-{suffix}", voltage_level=SUB_HV, is_source=True, node_type="substation_busbar")
    )
    network.add_node(
        Node(id=f"BUS-{suffix}", voltage_level=MV, node_type="substation_busbar")
    )
    network.add_transformer(
        id=f"PT-{suffix}",
        hv_node=f"HV-{suffix}",
        lv_node=f"BUS-{suffix}",
        rated_kva=10_000.0,
        impedance_pct=8.0,
        x_over_r=15.0,
    )
    network.add_feeder(
        Feeder(
            code=feeder_code,
            source_node=f"BUS-{suffix}",
            rated_current_a=400.0,
            emergency_current_a=480.0,
            substation=f"SUB-{suffix}",
        )
    )


def _build_feeder_a(network: Network) -> None:
    for node_id in ("A1", "A2", "A3", "A4", "A4B", "A5"):
        network.add_node(Node(id=node_id, voltage_level=MV, node_type="pole_connection"))
    network.add_node(Node(id="A4LV", voltage_level=LV_THREE_PHASE, node_type="transformer_lv"))
    network.add_node(Node(id="A4C", voltage_level=LV_THREE_PHASE, node_type="service_connection"))
    network.add_node(Node(id="A5LV", voltage_level=LV_SINGLE_PHASE, node_type="transformer_lv"))
    network.add_node(Node(id="A5C", voltage_level=LV_SINGLE_PHASE, node_type="service_connection"))

    network.add_switch(
        id="BRK-F1",
        from_node="BUS-A",
        to_node="A1",
        device_type="circuit_breaker",
        closed=True,
        feeder="F1",
        ampacity_a=600.0,
        remote_controlled=True,
    )
    network.add_line("L-A1-A2", "A1", "A2", length_m=2000.0, feeder="F1", **ACSR_4_0)
    network.add_switch(
        id="REC-A2",
        from_node="A2",
        to_node="A3",
        device_type="recloser",
        closed=True,
        feeder="F1",
        ampacity_a=400.0,
        remote_controlled=True,
    )
    network.add_line("L-A3-A4", "A3", "A4", length_m=1500.0, feeder="F1", **ACSR_4_0)
    network.add_switch(
        id="SEC-A4",
        from_node="A4",
        to_node="A4B",
        device_type="load_break_switch",
        closed=True,
        feeder="F1",
        ampacity_a=400.0,
        remote_controlled=True,
    )
    network.add_line("L-A4B-A5", "A4B", "A5", length_m=900.0, feeder="F1", phases=3, **ACSR_2)

    network.add_transformer(
        id="TR-A1",
        hv_node="A4",
        lv_node="A4LV",
        rated_kva=100.0,
        impedance_pct=4.0,
        feeder="F1",
    )
    network.add_line("LV-A1", "A4LV", "A4C", length_m=50.0, feeder="F1", **LV_TRIPLEX_4_0)
    network.add_load(
        Load(node="A4C", p_kw=50.0, q_kvar=15.0, phases=3, customers=40, label="Sector residencial A4")
    )

    network.add_transformer(
        id="TR-A2",
        hv_node="A5",
        lv_node="A5LV",
        rated_kva=50.0,
        impedance_pct=2.5,
        phases=1,
        feeder="F1",
    )
    network.add_line("LV-A2", "A5LV", "A5C", length_m=60.0, phases=1, feeder="F1", **LV_TRIPLEX_1_0)
    network.add_load(
        Load(node="A5C", p_kw=25.0, q_kvar=8.0, phases=1, customers=30, label="Sector residencial A5")
    )


def _build_feeder_b(network: Network) -> None:
    for node_id in ("B1", "B2", "B3", "B4"):
        network.add_node(Node(id=node_id, voltage_level=MV, node_type="pole_connection"))
    network.add_node(Node(id="B3LV", voltage_level=LV_THREE_PHASE, node_type="transformer_lv"))
    network.add_node(Node(id="B3C", voltage_level=LV_THREE_PHASE, node_type="service_connection"))

    network.add_switch(
        id="BRK-F2",
        from_node="BUS-B",
        to_node="B1",
        device_type="circuit_breaker",
        closed=True,
        feeder="F2",
        ampacity_a=600.0,
        remote_controlled=True,
    )
    network.add_line("L-B1-B2", "B1", "B2", length_m=1800.0, feeder="F2", **ACSR_4_0)
    network.add_switch(
        id="REC-B2",
        from_node="B2",
        to_node="B3",
        device_type="recloser",
        closed=True,
        feeder="F2",
        ampacity_a=400.0,
        remote_controlled=True,
    )
    network.add_line("L-B3-B4", "B3", "B4", length_m=1200.0, feeder="F2", **ACSR_4_0)

    network.add_transformer(
        id="TR-B1",
        hv_node="B3",
        lv_node="B3LV",
        rated_kva=100.0,
        impedance_pct=4.0,
        feeder="F2",
    )
    network.add_line("LV-B1", "B3LV", "B3C", length_m=55.0, feeder="F2", **LV_TRIPLEX_4_0)
    network.add_load(
        Load(
            node="B3C",
            p_kw=60.0,
            q_kvar=18.0,
            phases=3,
            customers=50,
            priority=True,
            label="Centro de salud y comercio B3",
        )
    )
