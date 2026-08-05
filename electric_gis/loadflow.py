"""Flujo de carga radial para redes de media y baja tensión.

Método: barrido hacia atrás y hacia adelante por sumatoria de potencias
(backward/forward sweep), que es el algoritmo estándar para redes de
distribución radiales porque converge en pocas iteraciones y no requiere
factorizar la matriz de admitancias.

Hipótesis del modelo, relevantes al interpretar los resultados:

* Se resuelve el equivalente por fase asumiendo reparto equilibrado entre las
  fases presentes en cada elemento. No resuelve desequilibrio entre fases ni
  acoplamiento mutuo entre conductores.
* La caída de tensión de los elementos monofásicos y bifásicos incorpora el
  retorno por neutro mediante el factor de la impedancia del lazo.
* Las cargas se modelan a potencia constante, que es el criterio conservador
  para verificar caída de tensión y cargabilidad.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Load, Network
from .topology import build_feeder_tree, check_radiality, energized_nodes


class LoadFlowError(RuntimeError):
    """La red no cumple las condiciones necesarias para el barrido radial."""


@dataclass
class NodeResult:
    node: str
    voltage_v: float
    voltage_pu: float
    angle_deg: float
    base_ln_v: float


@dataclass
class EdgeResult:
    edge: str
    current_a: float
    p_kw: float
    q_kvar: float
    loss_kw: float
    loss_kvar: float
    ampacity_a: float | None = None

    @property
    def loading_pct(self) -> float | None:
        if not self.ampacity_a:
            return None
        return 100.0 * self.current_a / self.ampacity_a


@dataclass
class Violation:
    kind: str
    element: str
    value: float
    limit: float
    detail: str = ""


@dataclass
class FeederResult:
    feeder: str
    source_node: str
    p_kw: float
    q_kvar: float
    current_a: float
    loss_kw: float
    load_kw: float
    min_voltage_pu: float
    customers: int


@dataclass
class LoadFlowResult:
    converged: bool
    iterations: int
    nodes: dict[str, NodeResult] = field(default_factory=dict)
    edges: dict[str, EdgeResult] = field(default_factory=dict)
    feeders: dict[str, FeederResult] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)
    unserved_loads: list[Load] = field(default_factory=list)
    # Potencia inyectada por las fuentes. Debe coincidir con la demanda servida
    # más las pérdidas, y es la comprobación de consistencia del resultado.
    source_injection_kw: float = 0.0
    source_injection_kvar: float = 0.0
    served_load_kw: float = 0.0

    @property
    def total_load_kw(self) -> float:
        return self.served_load_kw

    @property
    def total_loss_kw(self) -> float:
        return sum(result.loss_kw for result in self.edges.values())

    @property
    def power_balance_error_kw(self) -> float:
        return abs(self.source_injection_kw - self.served_load_kw - self.total_loss_kw)

    @property
    def min_voltage_pu(self) -> float:
        if not self.nodes:
            return 0.0
        return min(result.voltage_pu for result in self.nodes.values())

    def overloads(self) -> list[Violation]:
        return [item for item in self.violations if item.kind in {"edge_overload", "feeder_overload"}]

    def voltage_violations(self) -> list[Violation]:
        return [item for item in self.violations if item.kind in {"undervoltage", "overvoltage"}]


def solve(
    network: Network,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
    source_voltage_pu: float = 1.0,
    tolerance_pu: float = 1e-9,
    max_iterations: int = 60,
) -> LoadFlowResult:
    """Resuelve el flujo de carga de todos los circuitos energizados."""
    radial, loops = check_radiality(network, force_open, force_close)
    if not radial:
        raise LoadFlowError(
            "La red energizada no es radial. Aristas que cierran anillo: " + ", ".join(loops)
        )

    live_nodes = energized_nodes(network, force_open, force_close)
    loads_by_node = network.loads_by_node()

    result = LoadFlowResult(converged=True, iterations=0)
    result.unserved_loads = [load for load in network.loads if load.node not in live_nodes]

    for source in network.source_nodes:
        tree = build_feeder_tree(network, source, force_open, force_close)
        if len(tree.order) == 1 and not network.edges_at(source):
            continue

        voltages, currents, edge_flows, iterations = _sweep(
            network,
            tree,
            loads_by_node,
            source_voltage_pu,
            tolerance_pu,
            max_iterations,
        )
        result.iterations = max(result.iterations, iterations)
        if iterations >= max_iterations:
            result.converged = False

        _collect_node_results(network, tree, voltages, result)
        _collect_edge_results(network, tree, currents, edge_flows, result)
        _collect_feeder_results(network, tree, currents, edge_flows, loads_by_node, result)

        for node in tree.order:
            if node != tree.source and tree.parent_node[node] == tree.source:
                injection = edge_flows[tree.parent_edge[node]]
                result.source_injection_kw += injection.real / 1000.0
                result.source_injection_kvar += injection.imag / 1000.0

        result.served_load_kw += sum(
            load.p_kw for node in tree.nodes() for load in loads_by_node.get(node, [])
        )

    _check_voltage_limits(network, result)
    return result


def _sweep(
    network: Network,
    tree,
    loads_by_node: dict[str, list[Load]],
    source_voltage_pu: float,
    tolerance_pu: float,
    max_iterations: int,
) -> tuple[dict[str, complex], dict[str, complex], dict[str, complex], int]:
    """Barrido iterativo. Devuelve tensiones, corrientes y flujos por arista."""
    base_v = {node: network.nodes[node].voltage_level.nominal_ln_v for node in tree.order}
    voltages: dict[str, complex] = {node: complex(base_v[node], 0.0) for node in tree.order}
    voltages[tree.source] = complex(base_v[tree.source] * source_voltage_pu, 0.0)

    # Potencia aparente local por nodo en VA, referida al total del elemento.
    local_power: dict[str, complex] = {}
    for node in tree.order:
        total = complex(0.0, 0.0)
        for load in loads_by_node.get(node, []):
            total += complex(load.p_kw * 1000.0, load.q_kvar * 1000.0)
        local_power[node] = total

    currents: dict[str, complex] = {}
    edge_flows: dict[str, complex] = {}
    iterations = 0

    while iterations < max_iterations:
        iterations += 1

        # Barrido hacia atrás: acumula demanda y pérdidas desde las puntas.
        accumulated: dict[str, complex] = dict(local_power)
        for node in reversed(tree.order):
            if node == tree.source:
                continue
            edge = network.edges[tree.parent_edge[node]]
            downstream = accumulated[node]
            phase_power = downstream / edge.phases
            current = (phase_power / voltages[node]).conjugate()
            phase_loss = (abs(current) ** 2) * edge.impedance

            currents[edge.id] = current
            edge_flows[edge.id] = downstream + edge.phases * phase_loss
            accumulated[tree.parent_node[node]] += edge_flows[edge.id]

        # Barrido hacia adelante: propaga tensiones desde la fuente.
        max_delta = 0.0
        for node in tree.order:
            if node == tree.source:
                continue
            edge = network.edges[tree.parent_edge[node]]
            upstream_voltage = voltages[tree.parent_node[node]]
            updated = upstream_voltage * edge.ratio - currents[edge.id] * edge.impedance
            max_delta = max(max_delta, abs(updated - voltages[node]) / base_v[node])
            voltages[node] = updated

        if max_delta < tolerance_pu:
            break

    return voltages, currents, edge_flows, iterations


def _collect_node_results(network, tree, voltages: dict[str, complex], result: LoadFlowResult) -> None:
    for node in tree.order:
        base = network.nodes[node].voltage_level.nominal_ln_v
        voltage = voltages[node]
        result.nodes[node] = NodeResult(
            node=node,
            voltage_v=abs(voltage),
            voltage_pu=abs(voltage) / base,
            angle_deg=_degrees(voltage),
            base_ln_v=base,
        )


def _collect_edge_results(
    network,
    tree,
    currents: dict[str, complex],
    edge_flows: dict[str, complex],
    result: LoadFlowResult,
) -> None:
    for node in tree.order:
        if node == tree.source:
            continue
        edge = network.edges[tree.parent_edge[node]]
        current = currents[edge.id]
        phase_loss = (abs(current) ** 2) * edge.impedance
        total_loss = edge.phases * phase_loss
        flow = edge_flows[edge.id]

        edge_result = EdgeResult(
            edge=edge.id,
            current_a=abs(current),
            p_kw=flow.real / 1000.0,
            q_kvar=flow.imag / 1000.0,
            loss_kw=total_loss.real / 1000.0,
            loss_kvar=total_loss.imag / 1000.0,
            ampacity_a=edge.ampacity_a,
        )
        result.edges[edge.id] = edge_result

        loading = edge_result.loading_pct
        if loading is not None and loading > 100.0:
            result.violations.append(
                Violation(
                    kind="edge_overload",
                    element=edge.id,
                    value=edge_result.current_a,
                    limit=edge.ampacity_a or 0.0,
                    detail=f"Cargabilidad {loading:.1f} por ciento",
                )
            )


def _collect_feeder_results(
    network,
    tree,
    currents: dict[str, complex],
    edge_flows: dict[str, complex],
    loads_by_node: dict[str, list[Load]],
    result: LoadFlowResult,
) -> None:
    """Agrega resultados por circuito.

    Un circuito arranca en la barra de la subestación, que no coincide con el
    nodo fuente cuando se modela el transformador de potencia. Por eso la
    agregación se hace sobre el subárbol que nace en la cabecera del circuito.
    """
    children: dict[str, list[str]] = {}
    for node, parent in tree.parent_node.items():
        children.setdefault(parent, []).append(node)

    tree_nodes = tree.nodes()

    for feeder in network.feeders.values():
        if feeder.source_node not in tree_nodes:
            continue

        head_nodes = [
            child
            for child in children.get(feeder.source_node, [])
            if network.edges[tree.parent_edge[child]].feeder == feeder.code
        ]
        if not head_nodes:
            continue

        subtree: list[str] = []
        stack = list(head_nodes)
        while stack:
            node = stack.pop()
            subtree.append(node)
            stack.extend(children.get(node, []))

        head_edges = [network.edges[tree.parent_edge[node]] for node in head_nodes]
        injection = sum((edge_flows[edge.id] for edge in head_edges), complex(0.0, 0.0))
        head_current = max(abs(currents[edge.id]) for edge in head_edges)

        result.feeders[feeder.code] = FeederResult(
            feeder=feeder.code,
            source_node=feeder.source_node,
            p_kw=injection.real / 1000.0,
            q_kvar=injection.imag / 1000.0,
            current_a=head_current,
            loss_kw=sum(result.edges[tree.parent_edge[node]].loss_kw for node in subtree),
            load_kw=sum(load.p_kw for node in subtree for load in loads_by_node.get(node, [])),
            min_voltage_pu=min(result.nodes[node].voltage_pu for node in subtree),
            customers=sum(
                load.customers for node in subtree for load in loads_by_node.get(node, [])
            ),
        )

        if head_current > feeder.rated_current_a:
            result.violations.append(
                Violation(
                    kind="feeder_overload",
                    element=feeder.code,
                    value=head_current,
                    limit=feeder.rated_current_a,
                    detail="Corriente de cabecera sobre la nominal del circuito",
                )
            )


def _check_voltage_limits(network: Network, result: LoadFlowResult) -> None:
    for node_result in result.nodes.values():
        level = network.nodes[node_result.node].voltage_level
        if node_result.voltage_pu < level.v_min_pu:
            result.violations.append(
                Violation(
                    kind="undervoltage",
                    element=node_result.node,
                    value=node_result.voltage_pu,
                    limit=level.v_min_pu,
                    detail=f"Tensión {node_result.voltage_v:.1f} V fase-neutro",
                )
            )
        elif node_result.voltage_pu > level.v_max_pu:
            result.violations.append(
                Violation(
                    kind="overvoltage",
                    element=node_result.node,
                    value=node_result.voltage_pu,
                    limit=level.v_max_pu,
                    detail=f"Tensión {node_result.voltage_v:.1f} V fase-neutro",
                )
            )


def _degrees(value: complex) -> float:
    return math.degrees(math.atan2(value.imag, value.real))
