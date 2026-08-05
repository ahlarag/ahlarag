"""Modelo de red de distribución para análisis eléctrico.

El modelo es nodo-arista. Los elementos serie (tramos de línea, dispositivos de
seccionamiento y transformadores) son aristas entre dos nodos de conectividad.

Las impedancias se manejan en ohmios por fase y las tensiones en voltios
fase-neutro. Se trabaja en unidades físicas en lugar de por unidad porque la red
mezcla niveles de tensión y el transformador se representa con su relación de
transformación explícita.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Factor de retorno por corriente de neutro. En un circuito trifásico
# equilibrado la corriente de retorno es nula, por lo que la caída de tensión
# depende solo de la impedancia de fase. En un circuito monofásico la corriente
# retorna por el neutro y el lazo tiene aproximadamente el doble de impedancia.
PHASE_RETURN_FACTOR = {1: 2.0, 2: 1.5, 3: 1.0}


class NetworkError(ValueError):
    """Error de consistencia del modelo de red."""


@dataclass(frozen=True)
class VoltageLevel:
    """Nivel de tensión normalizado.

    nominal_kv es la tensión entre fases y nominal_ln_kv la tensión
    fase-neutro. Se declaran por separado porque los sistemas de baja tensión
    monofásicos de tres hilos (240/120 V) no cumplen la relación raíz de tres.
    """

    code: str
    nominal_kv: float
    nominal_ln_kv: float
    level_class: str
    v_min_pu: float = 0.95
    v_max_pu: float = 1.05

    def __post_init__(self) -> None:
        if self.nominal_kv <= 0 or self.nominal_ln_kv <= 0:
            raise NetworkError(f"Nivel de tensión {self.code} con tensión no positiva")
        if self.level_class not in {"transmission", "subtransmission", "medium", "low"}:
            raise NetworkError(f"Clase de tensión inválida en {self.code}: {self.level_class}")

    @property
    def nominal_ln_v(self) -> float:
        return self.nominal_ln_kv * 1000.0

    @classmethod
    def three_phase(cls, code: str, nominal_kv: float, level_class: str, **kwargs: float) -> "VoltageLevel":
        """Nivel trifásico donde la tensión fase-neutro es la nominal entre raíz de tres."""
        return cls(
            code=code,
            nominal_kv=nominal_kv,
            nominal_ln_kv=nominal_kv / math.sqrt(3.0),
            level_class=level_class,
            **kwargs,
        )


@dataclass
class Node:
    """Punto de conexión eléctrica."""

    id: str
    voltage_level: VoltageLevel
    is_source: bool = False
    node_type: str = "junction"
    lon: float | None = None
    lat: float | None = None


@dataclass
class Edge:
    """Elemento serie entre dos nodos.

    r_ohm y x_ohm son la impedancia del lazo por fase, es decir ya incluyen el
    factor de retorno cuando el elemento no es trifásico. ratio es la relación
    de tensión fase-neutro del nodo destino respecto al nodo origen y solo es
    distinta de uno en transformadores.
    """

    id: str
    kind: str
    from_node: str
    to_node: str
    phases: int
    closed: bool = True
    feeder: str | None = None
    r_ohm: float = 0.0
    x_ohm: float = 0.0
    ampacity_a: float | None = None
    ratio: float = 1.0
    device_type: str | None = None
    is_tie: bool = False
    remote_controlled: bool = False
    length_m: float | None = None
    rated_kva: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"line", "switch", "transformer"}:
            raise NetworkError(f"Tipo de arista inválido en {self.id}: {self.kind}")
        if self.phases not in PHASE_RETURN_FACTOR:
            raise NetworkError(f"Número de fases inválido en {self.id}: {self.phases}")
        if self.from_node == self.to_node:
            raise NetworkError(f"La arista {self.id} conecta el nodo {self.from_node} consigo mismo")

    @property
    def impedance(self) -> complex:
        return complex(self.r_ohm, self.x_ohm)

    @property
    def is_switchable(self) -> bool:
        return self.kind == "switch"


@dataclass
class Load:
    """Demanda concentrada en un nodo.

    p_kw y q_kvar son totales del elemento, no por fase. El reparto entre fases
    lo hace el flujo de carga según el número de fases declarado.
    """

    node: str
    p_kw: float
    q_kvar: float = 0.0
    phases: int = 3
    customers: int = 0
    priority: bool = False
    label: str | None = None

    def __post_init__(self) -> None:
        if self.phases not in PHASE_RETURN_FACTOR:
            raise NetworkError(f"Carga en {self.node} con número de fases inválido: {self.phases}")


@dataclass
class Feeder:
    """Circuito de distribución que arranca en la subestación."""

    code: str
    source_node: str
    rated_current_a: float
    emergency_current_a: float | None = None
    substation: str | None = None

    @property
    def transfer_limit_a(self) -> float:
        """Límite de corriente aplicable al evaluar transferencias de carga."""
        return self.emergency_current_a or self.rated_current_a


@dataclass
class Network:
    """Red completa: nodos, aristas, cargas y circuitos."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    loads: list[Load] = field(default_factory=list)
    feeders: dict[str, Feeder] = field(default_factory=dict)

    # -- Construcción -------------------------------------------------------

    def add_node(self, node: Node) -> Node:
        if node.id in self.nodes:
            raise NetworkError(f"Nodo duplicado: {node.id}")
        self.nodes[node.id] = node
        return node

    def add_feeder(self, feeder: Feeder) -> Feeder:
        if feeder.code in self.feeders:
            raise NetworkError(f"Circuito duplicado: {feeder.code}")
        self._require_node(feeder.source_node)
        self.feeders[feeder.code] = feeder
        return feeder

    def add_load(self, load: Load) -> Load:
        self._require_node(load.node)
        self.loads.append(load)
        return load

    def add_line(
        self,
        id: str,
        from_node: str,
        to_node: str,
        length_m: float,
        r1_ohm_km: float,
        x1_ohm_km: float,
        ampacity_a: float,
        phases: int = 3,
        feeder: str | None = None,
        closed: bool = True,
    ) -> Edge:
        """Tramo de línea aérea o subterránea.

        La impedancia resultante incluye el factor de retorno por neutro cuando
        el tramo no es trifásico.
        """
        if length_m <= 0:
            raise NetworkError(f"El tramo {id} debe tener longitud positiva")
        length_km = length_m / 1000.0
        factor = PHASE_RETURN_FACTOR[phases]
        return self._add_edge(
            Edge(
                id=id,
                kind="line",
                from_node=from_node,
                to_node=to_node,
                phases=phases,
                closed=closed,
                feeder=feeder,
                r_ohm=r1_ohm_km * length_km * factor,
                x_ohm=x1_ohm_km * length_km * factor,
                ampacity_a=ampacity_a,
                length_m=length_m,
            )
        )

    def add_switch(
        self,
        id: str,
        from_node: str,
        to_node: str,
        device_type: str,
        closed: bool,
        phases: int = 3,
        feeder: str | None = None,
        ampacity_a: float | None = None,
        is_tie: bool = False,
        remote_controlled: bool = False,
    ) -> Edge:
        """Elemento de maniobra. Se modela con impedancia despreciable."""
        return self._add_edge(
            Edge(
                id=id,
                kind="switch",
                from_node=from_node,
                to_node=to_node,
                phases=phases,
                closed=closed,
                feeder=feeder,
                ampacity_a=ampacity_a,
                device_type=device_type,
                is_tie=is_tie,
                remote_controlled=remote_controlled,
            )
        )

    def add_transformer(
        self,
        id: str,
        hv_node: str,
        lv_node: str,
        rated_kva: float,
        impedance_pct: float,
        phases: int = 3,
        x_over_r: float = 3.0,
        feeder: str | None = None,
        closed: bool = True,
    ) -> Edge:
        """Transformador de distribución o de potencia.

        La impedancia se refiere al lado de baja tensión, que es donde el
        barrido calcula la corriente del elemento.
        """
        if rated_kva <= 0:
            raise NetworkError(f"El transformador {id} debe tener potencia nominal positiva")
        if impedance_pct <= 0:
            raise NetworkError(f"El transformador {id} debe tener impedancia positiva")

        hv = self._require_node(hv_node)
        lv = self._require_node(lv_node)

        # Impedancia base por fase en el lado de baja tensión.
        rated_va_per_phase = (rated_kva * 1000.0) / phases
        z_base = (lv.voltage_level.nominal_ln_v**2) / rated_va_per_phase
        z_magnitude = (impedance_pct / 100.0) * z_base
        r = z_magnitude / math.sqrt(1.0 + x_over_r**2)
        x = r * x_over_r

        return self._add_edge(
            Edge(
                id=id,
                kind="transformer",
                from_node=hv_node,
                to_node=lv_node,
                phases=phases,
                closed=closed,
                feeder=feeder,
                r_ohm=r,
                x_ohm=x,
                ratio=lv.voltage_level.nominal_ln_v / hv.voltage_level.nominal_ln_v,
                rated_kva=rated_kva,
            )
        )

    # -- Consultas ----------------------------------------------------------

    @property
    def source_nodes(self) -> list[str]:
        return [node_id for node_id, node in self.nodes.items() if node.is_source]

    def loads_by_node(self) -> dict[str, list[Load]]:
        grouped: dict[str, list[Load]] = {}
        for load in self.loads:
            grouped.setdefault(load.node, []).append(load)
        return grouped

    def switch_devices(self) -> list[Edge]:
        return [edge for edge in self.edges.values() if edge.is_switchable]

    def tie_devices(self) -> list[Edge]:
        return [edge for edge in self.edges.values() if edge.is_tie]

    def edges_at(self, node_id: str) -> list[Edge]:
        return [
            edge
            for edge in self.edges.values()
            if edge.from_node == node_id or edge.to_node == node_id
        ]

    def other_end(self, edge: Edge, node_id: str) -> str:
        if edge.from_node == node_id:
            return edge.to_node
        if edge.to_node == node_id:
            return edge.from_node
        raise NetworkError(f"La arista {edge.id} no incide en el nodo {node_id}")

    def total_customers(self) -> int:
        return sum(load.customers for load in self.loads)

    # -- Internos -----------------------------------------------------------

    def _add_edge(self, edge: Edge) -> Edge:
        if edge.id in self.edges:
            raise NetworkError(f"Arista duplicada: {edge.id}")
        self._require_node(edge.from_node)
        self._require_node(edge.to_node)
        self.edges[edge.id] = edge
        return edge

    def _require_node(self, node_id: str) -> Node:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise NetworkError(f"Nodo inexistente: {node_id}") from None
