"""Maniobras, transferencias de carga y restauración del servicio.

Toda maniobra se evalúa antes de ejecutarse sobre tres criterios que deben
cumplirse simultáneamente:

1. Radialidad: la red no puede quedar en anillo ni con dos fuentes alimentando
   el mismo tramo, salvo una transferencia con traslape deliberada y controlada.
2. Cargabilidad: ningún conductor ni circuito puede superar su límite al recibir
   la carga transferida.
3. Tensión: la caída de tensión debe mantenerse dentro de los límites del nivel
   correspondiente.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .loadflow import LoadFlowError, LoadFlowResult, Violation, solve
from .model import Network
from .topology import (
    check_radiality,
    customers_impacted,
    deenergized_loads,
    effective_state,
    energized_nodes,
    protection_zone,
    transfer_candidates,
    upstream_protective_device,
    zone_for_edge,
)


@dataclass
class SwitchingStep:
    step_number: int
    device: str
    action: str
    reason: str
    remote_controlled: bool = False


@dataclass
class ScenarioAssessment:
    """Resultado del estudio de factibilidad de un escenario de maniobra."""

    force_open: tuple[str, ...]
    force_close: tuple[str, ...]
    radial: bool
    loop_edges: list[str] = field(default_factory=list)
    converged: bool = False
    customers_interrupted: int = 0
    customers_restored: int = 0
    priority_interrupted: int = 0
    min_voltage_pu: float = 0.0
    overloads: list[Violation] = field(default_factory=list)
    voltage_violations: list[Violation] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    load_flow: LoadFlowResult | None = None

    @property
    def feasible(self) -> bool:
        return (
            self.radial
            and self.converged
            and not self.overloads
            and not self.voltage_violations
        )


def evaluate_scenario(
    network: Network,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
    baseline_open: set[str] | tuple[str, ...] = (),
    baseline_close: set[str] | tuple[str, ...] = (),
) -> ScenarioAssessment:
    """Evalúa un escenario de maniobra sin modificar el estado de la red.

    baseline_open y baseline_close definen el estado contra el cual se mide el
    impacto en clientes. Por omisión es la operación normal.
    """
    force_open = tuple(force_open)
    force_close = tuple(force_close)

    radial, loops = check_radiality(network, force_open, force_close)
    impact = customers_impacted(network, force_open, force_close, baseline_open, baseline_close)

    assessment = ScenarioAssessment(
        force_open=force_open,
        force_close=force_close,
        radial=radial,
        loop_edges=loops,
        customers_interrupted=impact["interrupted"],
        customers_restored=impact["restored"],
        priority_interrupted=impact["priority_interrupted"],
    )

    if not radial:
        assessment.reasons.append(
            "La maniobra deja la red en anillo: " + ", ".join(loops)
        )
        return assessment

    try:
        flow = solve(network, force_open, force_close)
    except LoadFlowError as error:
        assessment.reasons.append(str(error))
        return assessment

    assessment.load_flow = flow
    assessment.converged = flow.converged
    assessment.min_voltage_pu = flow.min_voltage_pu
    assessment.overloads = flow.overloads()
    assessment.voltage_violations = flow.voltage_violations()

    if not flow.converged:
        assessment.reasons.append("El flujo de carga no converge en el escenario planteado")
    for violation in assessment.overloads:
        assessment.reasons.append(
            f"Sobrecarga en {violation.element}: {violation.value:.1f} A sobre {violation.limit:.1f} A"
        )
    for violation in assessment.voltage_violations:
        assessment.reasons.append(
            f"Tensión fuera de límite en {violation.element}: {violation.value:.3f} pu"
        )
    if assessment.priority_interrupted:
        assessment.reasons.append(
            f"La maniobra interrumpe {assessment.priority_interrupted} clientes prioritarios"
        )

    return assessment


@dataclass
class SwitchingPlan:
    """Orden de maniobra propuesta con su estudio de factibilidad."""

    purpose: str
    steps: list[SwitchingStep] = field(default_factory=list)
    assessment: ScenarioAssessment | None = None
    customers_still_out: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_executable(self) -> bool:
        return bool(self.steps) and self.assessment is not None and self.assessment.feasible


def plan_planned_work(network: Network, target: str) -> SwitchingPlan:
    """Orden de maniobra para intervenir un punto de la red de forma programada.

    target admite el identificador de un elemento o de un nodo. Aísla la zona
    mínima que lo contiene abriendo los dispositivos de la frontera y evalúa el
    impacto en clientes.
    """
    if target in network.edges:
        zone = zone_for_edge(network, target)
    else:
        zone = protection_zone(network, target)

    devices_to_open = [
        edge_id
        for edge_id in zone.boundary_devices
        if effective_state(network.edges[edge_id])
    ]

    plan = SwitchingPlan(purpose="planned_maintenance")
    for index, device_id in enumerate(devices_to_open, start=1):
        device = network.edges[device_id]
        plan.steps.append(
            SwitchingStep(
                step_number=index,
                device=device_id,
                action="open",
                reason="Aislar la zona de trabajo",
                remote_controlled=device.remote_controlled,
            )
        )

    for index, device_id in enumerate(devices_to_open, start=len(devices_to_open) + 1):
        plan.steps.append(
            SwitchingStep(
                step_number=index,
                device=device_id,
                action="verify_open",
                reason="Verificar ausencia de tensión antes de intervenir",
                remote_controlled=network.edges[device_id].remote_controlled,
            )
        )

    plan.assessment = evaluate_scenario(network, force_open=devices_to_open)
    plan.customers_still_out = plan.assessment.customers_interrupted

    if not devices_to_open:
        plan.notes.append("La zona ya está aislada: no hay dispositivos cerrados en la frontera")
    return plan


def evaluate_transfer(
    network: Network,
    tie_device: str,
    open_devices: set[str] | tuple[str, ...] = (),
) -> ScenarioAssessment:
    """Evalúa cerrar un enlace de transferencia abriendo los puntos indicados.

    Para preservar la radialidad, todo cierre de enlace entre circuitos debe
    acompañarse de la apertura del punto que quedaría alimentado por dos
    fuentes. El impacto se mide contra el estado sin el enlace cerrado, de modo
    que customers_restored refleja lo que aporta la transferencia.
    """
    return evaluate_scenario(
        network,
        force_open=open_devices,
        force_close=[tie_device],
        baseline_open=open_devices,
    )


def rank_transfer_options(
    network: Network,
    feeder_code: str,
    open_devices: set[str] | tuple[str, ...] = (),
) -> list[ScenarioAssessment]:
    """Ordena los enlaces de respaldo disponibles por conveniencia operativa.

    Prioriza las opciones factibles, luego las que recuperan más clientes y
    finalmente las que dejan mayor margen de tensión.
    """
    options = [
        evaluate_transfer(network, tie.id, open_devices)
        for tie in transfer_candidates(network, feeder_code, force_open=open_devices)
    ]
    return sorted(
        options,
        key=lambda item: (
            not item.feasible,
            -item.customers_restored,
            -item.min_voltage_pu,
        ),
    )


def plan_fault_restoration(network: Network, faulted_element: str) -> SwitchingPlan:
    """Plan de aislamiento y restauración ante una falla.

    Sigue la secuencia operativa habitual:

    1. La protección aguas arriba ya despejó la falla y dejó sin servicio a todo
       lo que alimenta.
    2. Se aísla la zona fallada abriendo los seccionamientos de su frontera.
    3. Se reconecta la protección para devolver servicio al tramo sano aguas
       arriba.
    4. Se evalúa transferir el tramo sano aguas abajo a un circuito de respaldo.
    """
    if faulted_element not in network.edges:
        raise KeyError(f"Elemento inexistente: {faulted_element}")

    edge = network.edges[faulted_element]
    plan = SwitchingPlan(purpose="fault_isolation")

    protective = upstream_protective_device(network, edge.from_node)
    if protective is None:
        plan.notes.append(
            "No se encontró dispositivo de protección aguas arriba: revisar la coordinación del circuito"
        )
    else:
        plan.notes.append(
            f"La falla la despeja {protective.id} ({protective.device_type}), que deja sin servicio su zona completa"
        )

    zone = zone_for_edge(network, faulted_element)
    isolation_devices = [
        device_id
        for device_id in zone.boundary_devices
        if effective_state(network.edges[device_id])
        and (protective is None or device_id != protective.id)
    ]

    step_number = 1
    for device_id in isolation_devices:
        plan.steps.append(
            SwitchingStep(
                step_number=step_number,
                device=device_id,
                action="open",
                reason="Aislar el elemento fallado",
                remote_controlled=network.edges[device_id].remote_controlled,
            )
        )
        step_number += 1

    # La protección solo se repone si el aislamiento logró dejar el elemento
    # fallado sin alimentación. Si la falla está justo aguas abajo de la
    # protección, cerrarla la volvería a energizar y debe permanecer abierta.
    final_open = list(isolation_devices)
    if protective is not None:
        live = energized_nodes(network, force_open=isolation_devices, force_close=[protective.id])
        fault_reenergized = edge.from_node in live or edge.to_node in live
        if fault_reenergized:
            final_open.append(protective.id)
            plan.steps.append(
                SwitchingStep(
                    step_number=step_number,
                    device=protective.id,
                    action="verify_open",
                    reason="Confirmar abierto y bloquear el recierre: la falla está en su zona inmediata",
                    remote_controlled=protective.remote_controlled,
                )
            )
            step_number += 1
            plan.notes.append(
                f"{protective.id} debe permanecer abierto: la falla está en su zona inmediata "
                "y no existe seccionamiento intermedio para reponerlo"
            )
        else:
            plan.steps.append(
                SwitchingStep(
                    step_number=step_number,
                    device=protective.id,
                    action="close",
                    reason="Restablecer el tramo sano aguas arriba de la falla",
                    remote_controlled=protective.remote_controlled,
                )
            )
            step_number += 1

    plan.assessment = evaluate_scenario(network, force_open=final_open)
    plan.customers_still_out = unsupplied_customers(network, force_open=final_open)

    if plan.customers_still_out:
        feeder_code = _feeder_for_edge(network, edge)
        if feeder_code is None:
            plan.notes.append(
                "El elemento fallado no tiene circuito asociado: no se evalúa transferencia automática"
            )
            return plan

        for option in rank_transfer_options(network, feeder_code, open_devices=final_open):
            if not option.feasible or not option.customers_restored:
                continue
            tie_id = option.force_close[0]
            # Un enlace situado dentro de la zona fallada volvería a alimentar la
            # falla por el otro extremo, por lo que se descarta.
            live_after_tie = energized_nodes(network, force_open=final_open, force_close=[tie_id])
            if edge.from_node in live_after_tie or edge.to_node in live_after_tie:
                plan.notes.append(
                    f"{tie_id} se descarta porque reenergizaría el elemento fallado {faulted_element}"
                )
                continue
            plan.steps.append(
                SwitchingStep(
                    step_number=step_number,
                    device=tie_id,
                    action="close",
                    reason="Transferir el tramo sano aguas abajo al circuito de respaldo",
                    remote_controlled=network.edges[tie_id].remote_controlled,
                )
            )
            plan.assessment = option
            plan.customers_still_out = unsupplied_customers(
                network, force_open=final_open, force_close=[tie_id]
            )
            break
        else:
            plan.notes.append(
                "No hay transferencia factible: los clientes aguas abajo quedan sin servicio hasta reparar"
            )

    return plan


def apply_switching(network: Network, plan: SwitchingPlan) -> None:
    """Aplica al modelo el estado resultante de una orden de maniobra ejecutada.

    verify_open deja el elemento abierto porque cubre tanto la comprobación
    previa a intervenir como el bloqueo de la protección que operó.
    """
    for step in plan.steps:
        if step.action in {"open", "verify_open"}:
            network.edges[step.device].closed = False
        elif step.action == "close":
            network.edges[step.device].closed = True


def unsupplied_customers(
    network: Network,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
) -> int:
    """Clientes sin servicio en el escenario indicado."""
    return sum(load.customers for load in deenergized_loads(network, force_open, force_close))


def _feeder_for_edge(network: Network, edge) -> str | None:
    if edge.feeder:
        return edge.feeder
    for feeder in network.feeders.values():
        if edge.from_node in energized_nodes(network, sources=[feeder.source_node]):
            return feeder.code
    return None
