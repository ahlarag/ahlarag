"""Índices de confiabilidad del servicio según IEEE 1366.

Los índices se calculan a partir de interrupciones por cliente y no por evento,
porque en una restauración por etapas cada grupo de clientes recupera el
servicio en un momento distinto y esa diferencia es la que mide el desempeño
real de la operación.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Umbral que separa una interrupción momentánea de una sostenida. IEEE 1366 usa
# cinco minutos como valor de referencia.
SUSTAINED_THRESHOLD_MIN = 5.0


@dataclass
class CustomerInterruption:
    """Interrupción sufrida por un grupo de clientes en un evento."""

    service_point: str
    customers: int
    duration_min: float
    outage_class: str = "sustained"
    feeder: str | None = None
    energy_not_served_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.customers < 0:
            raise ValueError(f"Clientes negativos en {self.service_point}")
        if self.duration_min < 0:
            raise ValueError(f"Duración negativa en {self.service_point}")
        if self.outage_class not in {"sustained", "momentary", "planned"}:
            raise ValueError(f"Clase de interrupción inválida: {self.outage_class}")

    @property
    def is_sustained(self) -> bool:
        return self.outage_class != "momentary" and self.duration_min >= SUSTAINED_THRESHOLD_MIN

    @property
    def customer_minutes(self) -> float:
        return self.customers * self.duration_min


@dataclass
class ReliabilityIndices:
    total_customers: int
    period_hours: float
    saifi: float
    saidi_min: float
    caidi_min: float
    maifi: float
    asai_pct: float
    customer_interruptions: int
    customer_minutes: float
    energy_not_served_kwh: float
    by_feeder: dict[str, "ReliabilityIndices"] = field(default_factory=dict)


def compute_indices(
    interruptions: list[CustomerInterruption],
    total_customers: int,
    period_hours: float = 8760.0,
    include_planned: bool = True,
    group_by_feeder: bool = False,
) -> ReliabilityIndices:
    """Calcula SAIFI, SAIDI, CAIDI, MAIFI, ASAI y energía no suministrada.

    include_planned controla si las interrupciones programadas entran en los
    índices. Muchos reguladores exigen reportarlas por separado.
    """
    if total_customers <= 0:
        raise ValueError("El total de clientes servidos debe ser positivo")
    if period_hours <= 0:
        raise ValueError("El periodo debe ser positivo")

    considered = [
        item
        for item in interruptions
        if include_planned or item.outage_class != "planned"
    ]

    sustained = [item for item in considered if item.is_sustained]
    momentary = [item for item in considered if not item.is_sustained]

    customer_interruptions = sum(item.customers for item in sustained)
    customer_minutes = sum(item.customer_minutes for item in sustained)
    momentary_interruptions = sum(item.customers for item in momentary)

    saifi = customer_interruptions / total_customers
    saidi = customer_minutes / total_customers
    caidi = (customer_minutes / customer_interruptions) if customer_interruptions else 0.0
    maifi = momentary_interruptions / total_customers

    total_customer_minutes = total_customers * period_hours * 60.0
    asai = 100.0 * (total_customer_minutes - customer_minutes) / total_customer_minutes

    indices = ReliabilityIndices(
        total_customers=total_customers,
        period_hours=period_hours,
        saifi=saifi,
        saidi_min=saidi,
        caidi_min=caidi,
        maifi=maifi,
        asai_pct=asai,
        customer_interruptions=customer_interruptions,
        customer_minutes=customer_minutes,
        energy_not_served_kwh=sum(item.energy_not_served_kwh for item in considered),
    )

    if group_by_feeder:
        feeders = {item.feeder for item in considered if item.feeder}
        for feeder in sorted(feeders):
            subset = [item for item in considered if item.feeder == feeder]
            feeder_customers = _customers_served(subset)
            indices.by_feeder[feeder] = compute_indices(
                subset,
                total_customers=max(feeder_customers, 1),
                period_hours=period_hours,
                include_planned=include_planned,
            )

    return indices


def estimate_energy_not_served_kwh(load_kw: float, duration_min: float, load_factor: float = 1.0) -> float:
    """Energía no suministrada a partir de la demanda interrumpida.

    load_factor permite corregir la demanda de punta al promedio del periodo de
    la interrupción.
    """
    if load_kw < 0 or duration_min < 0:
        raise ValueError("La demanda y la duración deben ser no negativas")
    if not 0 < load_factor <= 1:
        raise ValueError("El factor de carga debe estar entre cero y uno")
    return load_kw * load_factor * (duration_min / 60.0)


def _customers_served(interruptions: list[CustomerInterruption]) -> int:
    """Clientes distintos afectados, usado como base cuando se agrupa por circuito."""
    per_point: dict[str, int] = {}
    for item in interruptions:
        per_point[item.service_point] = max(per_point.get(item.service_point, 0), item.customers)
    return sum(per_point.values())
