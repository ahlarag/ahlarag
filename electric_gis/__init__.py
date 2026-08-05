"""Motor de referencia para sistemas de información geográfica eléctricos.

Cubre el trayecto completo de la distribución, desde la subestación hasta el
cliente, con tres capacidades sobre un mismo modelo de red:

* Topología: energización, radialidad, zonas de protección y aislamiento.
* Flujo de carga radial en media y baja tensión.
* Maniobras: trabajo programado, aislamiento de falla y transferencia entre
  circuitos, con estudio de factibilidad previo.
"""

from .loadflow import (
    EdgeResult,
    FeederResult,
    LoadFlowError,
    LoadFlowResult,
    NodeResult,
    Violation,
    solve,
)
from .model import (
    Edge,
    Feeder,
    Load,
    Network,
    NetworkError,
    Node,
    VoltageLevel,
)
from .reliability import (
    CustomerInterruption,
    ReliabilityIndices,
    compute_indices,
    estimate_energy_not_served_kwh,
)
from .switching import (
    ScenarioAssessment,
    SwitchingPlan,
    SwitchingStep,
    apply_switching,
    evaluate_scenario,
    evaluate_transfer,
    plan_fault_restoration,
    plan_planned_work,
    rank_transfer_options,
    unsupplied_customers,
)
from .topology import (
    FeederTree,
    ProtectionZone,
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

__all__ = [
    "Edge",
    "EdgeResult",
    "Feeder",
    "FeederResult",
    "FeederTree",
    "Load",
    "LoadFlowError",
    "LoadFlowResult",
    "Network",
    "NetworkError",
    "Node",
    "NodeResult",
    "ProtectionZone",
    "ScenarioAssessment",
    "SwitchingPlan",
    "SwitchingStep",
    "CustomerInterruption",
    "ReliabilityIndices",
    "Violation",
    "VoltageLevel",
    "apply_switching",
    "build_feeder_tree",
    "check_radiality",
    "compute_indices",
    "customers_impacted",
    "deenergized_loads",
    "energized_nodes",
    "estimate_energy_not_served_kwh",
    "evaluate_scenario",
    "evaluate_transfer",
    "plan_fault_restoration",
    "plan_planned_work",
    "protection_zone",
    "rank_transfer_options",
    "solve",
    "transfer_candidates",
    "unsupplied_customers",
    "upstream_protective_device",
    "zone_for_edge",
]
