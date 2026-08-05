"""Trazado de topología sobre la red de distribución.

El estado de energización nunca se almacena: se deriva recorriendo la red desde
los nodos fuente a través de las aristas cerradas. Esto permite evaluar tanto la
operación actual como escenarios hipotéticos de maniobra.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .model import Edge, Load, Network

# Dispositivos capaces de interrumpir corriente de falla por sí mismos. El
# seccionalizador queda fuera porque no interrumpe falla: cuenta operaciones del
# reconectador y abre durante el intervalo sin tensión.
PROTECTIVE_DEVICE_TYPES = frozenset({"circuit_breaker", "recloser", "fuse"})


def effective_state(
    edge: Edge,
    force_open: frozenset[str] | set[str] | tuple[str, ...] = (),
    force_close: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> bool:
    """Estado de conducción de una arista bajo un escenario de maniobra.

    Solo los elementos de maniobra pueden forzarse. Un tramo fuera de servicio
    permanece abierto porque representa una condición física, no una maniobra.
    """
    if edge.is_switchable:
        if edge.id in force_close:
            return True
        if edge.id in force_open:
            return False
    return edge.closed


def energized_nodes(
    network: Network,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
    sources: list[str] | None = None,
) -> set[str]:
    """Conjunto de nodos con tensión bajo el escenario indicado."""
    roots = sources if sources is not None else network.source_nodes
    visited: set[str] = set(roots)
    queue = deque(roots)

    while queue:
        current = queue.popleft()
        for edge in network.edges_at(current):
            if not effective_state(edge, force_open, force_close):
                continue
            neighbour = network.other_end(edge, current)
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)

    return visited


@dataclass
class FeederTree:
    """Árbol radial de un circuito, listo para el barrido del flujo de carga.

    order recorre el árbol desde la fuente hacia las puntas, por lo que el
    barrido hacia atrás usa el orden invertido. loop_edges contiene las aristas
    que cerrarían un anillo y que por tanto rompen la radialidad.
    """

    source: str
    parent_edge: dict[str, str] = field(default_factory=dict)
    parent_node: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    loop_edges: list[str] = field(default_factory=list)

    @property
    def is_radial(self) -> bool:
        return not self.loop_edges

    def nodes(self) -> set[str]:
        return set(self.order)

    def children_edges(self) -> dict[str, list[str]]:
        """Aristas hijas por nodo, en el sentido fuente hacia carga."""
        children: dict[str, list[str]] = {node: [] for node in self.order}
        for node, edge_id in self.parent_edge.items():
            children.setdefault(self.parent_node[node], []).append(edge_id)
        return children


def build_feeder_tree(
    network: Network,
    source: str,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
) -> FeederTree:
    """Construye el árbol de alimentación desde un nodo fuente.

    Detecta las aristas que cierran anillo, condición que invalida el barrido
    radial y que en operación normal indica un enlace de transferencia cerrado
    por error.
    """
    tree = FeederTree(source=source, order=[source])
    visited = {source}
    queue = deque([source])
    loop_edges: list[str] = []

    while queue:
        current = queue.popleft()
        for edge in network.edges_at(current):
            if not effective_state(edge, force_open, force_close):
                continue
            neighbour = network.other_end(edge, current)
            if neighbour not in visited:
                visited.add(neighbour)
                tree.parent_edge[neighbour] = edge.id
                tree.parent_node[neighbour] = current
                tree.order.append(neighbour)
                queue.append(neighbour)
            elif tree.parent_edge.get(current) != edge.id and edge.id not in loop_edges:
                loop_edges.append(edge.id)

    tree.loop_edges = loop_edges
    return tree


def check_radiality(
    network: Network,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
) -> tuple[bool, list[str]]:
    """Verifica que la red energizada sea radial.

    Devuelve las aristas que cierran anillo o que ponen dos fuentes en paralelo
    alimentando el mismo tramo, aunque el grafo no forme un ciclo cerrado.

    El recorrido se hace en dos etapas para que el elemento reportado sea el que
    el operador va a maniobrar: primero se explora la red tal como está y
    después se incorporan los cierres propuestos. Así un enlace de transferencia
    que pone dos subestaciones en paralelo se reporta como el enlace mismo y no
    como un tramo intermedio.

    Es la validación obligatoria antes de autorizar el cierre de un enlace entre
    circuitos.
    """
    root_of: dict[str, str] = {}
    parent_edge: dict[str, str] = {}
    violations: list[str] = []
    queue: deque[str] = deque()

    existing_edges = [
        edge
        for edge in network.edges.values()
        if edge.id not in force_close and effective_state(edge, force_open, ())
    ]
    adjacency: dict[str, list[Edge]] = {}
    for edge in existing_edges:
        adjacency.setdefault(edge.from_node, []).append(edge)
        adjacency.setdefault(edge.to_node, []).append(edge)

    def expand() -> None:
        while queue:
            current = queue.popleft()
            for edge in adjacency.get(current, []):
                neighbour = network.other_end(edge, current)
                if neighbour not in root_of:
                    root_of[neighbour] = root_of[current]
                    parent_edge[neighbour] = edge.id
                    queue.append(neighbour)
                elif parent_edge.get(current) != edge.id and edge.id not in violations:
                    violations.append(edge.id)

    for source in network.source_nodes:
        root_of[source] = source
        queue.append(source)
    expand()

    pending = [
        network.edges[edge_id]
        for edge_id in force_close
        if network.edges[edge_id].is_switchable
    ]
    progress = True
    while progress and pending:
        progress = False
        deferred: list[Edge] = []
        for edge in pending:
            from_reached = edge.from_node in root_of
            to_reached = edge.to_node in root_of
            if from_reached and to_reached:
                if edge.id not in violations:
                    violations.append(edge.id)
            elif from_reached or to_reached:
                known, unknown = (
                    (edge.from_node, edge.to_node) if from_reached else (edge.to_node, edge.from_node)
                )
                root_of[unknown] = root_of[known]
                parent_edge[unknown] = edge.id
                queue.append(unknown)
                adjacency.setdefault(edge.from_node, []).append(edge)
                adjacency.setdefault(edge.to_node, []).append(edge)
                expand()
                progress = True
            else:
                deferred.append(edge)
        pending = deferred

    return (not violations, violations)


def deenergized_loads(
    network: Network,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
) -> list[Load]:
    """Cargas sin suministro bajo el escenario indicado."""
    live = energized_nodes(network, force_open, force_close)
    return [load for load in network.loads if load.node not in live]


def customers_impacted(
    network: Network,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
    baseline_open: set[str] | tuple[str, ...] = (),
    baseline_close: set[str] | tuple[str, ...] = (),
) -> dict[str, int]:
    """Clientes que pierden y que recuperan servicio respecto a un estado base.

    El estado base es por omisión la operación normal. Al analizar una
    restauración conviene usar como base el estado posterior al aislamiento de la
    falla, para medir solo lo que aporta la maniobra evaluada.
    """
    before = {load.node for load in deenergized_loads(network, baseline_open, baseline_close)}
    after = {load.node for load in deenergized_loads(network, force_open, force_close)}

    interrupted = sum(load.customers for load in network.loads if load.node in after - before)
    restored = sum(load.customers for load in network.loads if load.node in before - after)
    priority_interrupted = sum(
        load.customers for load in network.loads if load.node in after - before and load.priority
    )

    return {
        "interrupted": interrupted,
        "restored": restored,
        "priority_interrupted": priority_interrupted,
    }


@dataclass
class ProtectionZone:
    """Zona delimitada por elementos de maniobra.

    Es la mínima porción de red que se puede dejar sin tensión para intervenir
    un elemento: todo lo que está entre los dispositivos de la frontera.
    """

    nodes: set[str]
    boundary_devices: list[str]

    def isolating_devices(self, network: Network) -> list[Edge]:
        return [network.edges[edge_id] for edge_id in self.boundary_devices]


def protection_zone(network: Network, node: str) -> ProtectionZone:
    """Zona de maniobra que contiene al nodo indicado."""
    zone_nodes = {node}
    boundary: list[str] = []
    queue = deque([node])

    while queue:
        current = queue.popleft()
        for edge in network.edges_at(current):
            if edge.is_switchable:
                if edge.id not in boundary:
                    boundary.append(edge.id)
                continue
            if not edge.closed:
                continue
            neighbour = network.other_end(edge, current)
            if neighbour not in zone_nodes:
                zone_nodes.add(neighbour)
                queue.append(neighbour)

    return ProtectionZone(nodes=zone_nodes, boundary_devices=boundary)


def zone_for_edge(network: Network, edge_id: str) -> ProtectionZone:
    """Zona de maniobra que contiene a una arista, típicamente el elemento fallado."""
    edge = network.edges[edge_id]
    if edge.is_switchable:
        return ProtectionZone(nodes={edge.from_node, edge.to_node}, boundary_devices=[edge.id])
    return protection_zone(network, edge.from_node)


def upstream_protective_device(network: Network, node: str) -> Edge | None:
    """Primer dispositivo de protección entre el nodo y su fuente.

    Es el elemento que operaría ante una falla en ese punto, y por tanto el que
    define cuántos clientes quedan sin servicio. Una falla despejada por el
    interruptor de cabecera deja sin tensión el circuito completo.
    """
    for source in network.source_nodes:
        tree = build_feeder_tree(network, source)
        if node not in tree.nodes():
            continue

        current = node
        while current != tree.source:
            edge = network.edges[tree.parent_edge[current]]
            if edge.device_type in PROTECTIVE_DEVICE_TYPES:
                return edge
            current = tree.parent_node[current]
    return None


def transfer_candidates(
    network: Network,
    feeder_code: str,
    force_open: set[str] | tuple[str, ...] = (),
    force_close: set[str] | tuple[str, ...] = (),
) -> list[Edge]:
    """Enlaces normalmente abiertos que pueden respaldar a un circuito.

    Se reconocen dos situaciones distintas:

    * Recuperación de carga sin tensión: el enlace tiene un extremo energizado y
      el otro no, por lo que al cerrarlo devuelve servicio.
    * Transferencia entre circuitos vivos: ambos extremos están energizados y al
      menos uno pertenece al circuito analizado. Requiere abrir otro punto para
      no dejar dos fuentes en paralelo.

    force_open y force_close permiten evaluar el respaldo disponible después de
    aislar una falla.
    """
    feeder = network.feeders[feeder_code]
    own_nodes = energized_nodes(network, force_open, force_close, sources=[feeder.source_node])
    live_nodes = energized_nodes(network, force_open, force_close)

    candidates: list[Edge] = []
    for edge in network.tie_devices():
        if effective_state(edge, force_open, force_close):
            continue
        from_live = edge.from_node in live_nodes
        to_live = edge.to_node in live_nodes
        if from_live != to_live:
            candidates.append(edge)
        elif from_live and to_live and {edge.from_node, edge.to_node} & own_nodes:
            candidates.append(edge)
    return candidates
