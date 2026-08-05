-- Modelo de red de distribución eléctrica georreferenciada.
-- Cubre el trayecto completo: subestación -> circuito MT -> seccionamiento ->
-- transformador de distribución -> red BT -> punto de servicio del cliente.
--
-- Convención de conectividad: modelo nodo-arista (bus-branch).
--   * electrical.node concentra todos los puntos de conexión eléctrica.
--   * Los elementos serie (tramos, seccionamiento, transformadores) son aristas
--     con from_node_id / to_node_id.
--   * El estado de energización nunca se almacena como dato maestro: se deriva
--     por trazado desde las fuentes con las aristas cerradas.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS electrical;

-- ---------------------------------------------------------------------------
-- Catálogos base
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS electrical.voltage_level (
    id smallserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    -- Tensión nominal entre fases.
    nominal_kv numeric(10, 4) NOT NULL,
    -- Tensión nominal fase-neutro. Se declara explícitamente porque los
    -- sistemas BT monofásicos de tres hilos (240/120 V) no cumplen kv/sqrt(3).
    nominal_ln_kv numeric(10, 4) NOT NULL,
    level_class text NOT NULL,
    default_phases smallint NOT NULL DEFAULT 3,
    -- Límites operativos de tensión en por unidad.
    v_min_pu numeric(4, 3) NOT NULL DEFAULT 0.950,
    v_max_pu numeric(4, 3) NOT NULL DEFAULT 1.050,
    CONSTRAINT voltage_level_class_check CHECK (
        level_class IN ('transmission', 'subtransmission', 'medium', 'low')
    ),
    CONSTRAINT voltage_level_phases_check CHECK (default_phases IN (1, 2, 3)),
    CONSTRAINT voltage_level_kv_check CHECK (nominal_kv > 0 AND nominal_ln_kv > 0)
);

CREATE TABLE IF NOT EXISTS electrical.conductor_spec (
    id serial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    description text,
    material text NOT NULL,
    -- Calibre comercial tal como se maneja en campo (2 AWG, 4/0, 240 mm2...).
    size_label text NOT NULL,
    -- Impedancia de secuencia positiva y cero por kilómetro.
    r1_ohm_km numeric(10, 5) NOT NULL,
    x1_ohm_km numeric(10, 5) NOT NULL,
    r0_ohm_km numeric(10, 5),
    x0_ohm_km numeric(10, 5),
    ampacity_a numeric(10, 2) NOT NULL,
    CONSTRAINT conductor_spec_material_check CHECK (
        material IN ('copper', 'aluminum', 'acsr', 'aac', 'aaac', 'xlpe', 'epr', 'other')
    ),
    CONSTRAINT conductor_spec_impedance_check CHECK (r1_ohm_km >= 0 AND x1_ohm_km >= 0),
    CONSTRAINT conductor_spec_ampacity_check CHECK (ampacity_a > 0)
);

-- ---------------------------------------------------------------------------
-- Subestaciones y alimentadores
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS electrical.substation (
    id serial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    municipality_name text,
    state_name text,
    geom geometry(Point, 4326) NOT NULL,
    site_geom geometry(Polygon, 4326),
    commissioned_on date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS electrical.node (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    voltage_level_id smallint NOT NULL REFERENCES electrical.voltage_level (id),
    node_type text NOT NULL,
    substation_id integer REFERENCES electrical.substation (id) ON DELETE SET NULL,
    -- Marca los nodos que pueden inyectar potencia al sistema: barras de
    -- subestación y generación distribuida despachable.
    is_source boolean NOT NULL DEFAULT false,
    geom geometry(Point, 4326) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT node_type_check CHECK (
        node_type IN (
            'substation_busbar',
            'pole_connection',
            'junction',
            'transformer_hv',
            'transformer_lv',
            'service_connection',
            'open_point'
        )
    )
);

CREATE TABLE IF NOT EXISTS electrical.power_transformer (
    id serial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    substation_id integer NOT NULL REFERENCES electrical.substation (id) ON DELETE CASCADE,
    hv_node_id bigint NOT NULL REFERENCES electrical.node (id),
    lv_node_id bigint NOT NULL REFERENCES electrical.node (id),
    rated_mva numeric(10, 3) NOT NULL,
    impedance_pct numeric(6, 3) NOT NULL,
    x_over_r numeric(6, 3) NOT NULL DEFAULT 10.000,
    tap_pu numeric(5, 4) NOT NULL DEFAULT 1.0000,
    CONSTRAINT power_transformer_rating_check CHECK (rated_mva > 0),
    CONSTRAINT power_transformer_impedance_check CHECK (impedance_pct > 0),
    CONSTRAINT power_transformer_nodes_check CHECK (hv_node_id <> lv_node_id)
);

-- Un feeder es el circuito que arranca en el interruptor de salida de la
-- subestación. Es la unidad de operación para maniobras y reportes.
CREATE TABLE IF NOT EXISTS electrical.feeder (
    id serial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    substation_id integer NOT NULL REFERENCES electrical.substation (id) ON DELETE CASCADE,
    voltage_level_id smallint NOT NULL REFERENCES electrical.voltage_level (id),
    source_node_id bigint NOT NULL REFERENCES electrical.node (id),
    rated_current_a numeric(10, 2) NOT NULL,
    -- Límite operativo usado al evaluar transferencias de carga.
    emergency_current_a numeric(10, 2),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT feeder_rated_current_check CHECK (rated_current_a > 0)
);

-- ---------------------------------------------------------------------------
-- Estructuras (postes, torres, pedestales)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS electrical.structure (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    structure_type text NOT NULL,
    material text,
    height_m numeric(6, 2),
    -- Georreferenciación de campo: precisión y origen del levantamiento.
    gps_accuracy_m numeric(6, 2),
    survey_source text,
    municipality_name text,
    geom geometry(Point, 4326) NOT NULL,
    installed_on date,
    condition_rating smallint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT structure_type_check CHECK (
        structure_type IN ('pole', 'tower', 'pedestal', 'underground_vault', 'wall_mount')
    ),
    CONSTRAINT structure_condition_check CHECK (
        condition_rating IS NULL OR condition_rating BETWEEN 1 AND 5
    )
);

-- ---------------------------------------------------------------------------
-- Aristas de red: tramos, seccionamiento y transformadores de distribución
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS electrical.line_section (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    feeder_id integer REFERENCES electrical.feeder (id) ON DELETE SET NULL,
    from_node_id bigint NOT NULL REFERENCES electrical.node (id),
    to_node_id bigint NOT NULL REFERENCES electrical.node (id),
    voltage_level_id smallint NOT NULL REFERENCES electrical.voltage_level (id),
    conductor_spec_id integer NOT NULL REFERENCES electrical.conductor_spec (id),
    network_type text NOT NULL,
    installation text NOT NULL,
    -- Fases físicamente presentes en el tramo: 'ABC', 'AB', 'A', ...
    phases text NOT NULL,
    length_m numeric(12, 3) NOT NULL,
    geom geometry(LineString, 4326) NOT NULL,
    in_service boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT line_section_network_type_check CHECK (network_type IN ('medium', 'low', 'subtransmission')),
    CONSTRAINT line_section_installation_check CHECK (installation IN ('overhead', 'underground', 'submarine')),
    CONSTRAINT line_section_phases_check CHECK (phases ~ '^[ABC]{1,3}N?$'),
    CONSTRAINT line_section_length_check CHECK (length_m > 0),
    CONSTRAINT line_section_nodes_check CHECK (from_node_id <> to_node_id)
);

-- Todo elemento capaz de abrir o cerrar el circuito. Incluye el interruptor de
-- cabecera, reconectadores, seccionadores, fusibles y enlaces normalmente
-- abiertos entre circuitos.
CREATE TABLE IF NOT EXISTS electrical.switch_device (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    device_type text NOT NULL,
    feeder_id integer REFERENCES electrical.feeder (id) ON DELETE SET NULL,
    from_node_id bigint NOT NULL REFERENCES electrical.node (id),
    to_node_id bigint NOT NULL REFERENCES electrical.node (id),
    structure_id bigint REFERENCES electrical.structure (id) ON DELETE SET NULL,
    voltage_level_id smallint NOT NULL REFERENCES electrical.voltage_level (id),
    phases text NOT NULL DEFAULT 'ABC',
    -- normal_state es el estado de diseño; current_state es el operativo real.
    normal_state text NOT NULL,
    current_state text NOT NULL,
    remote_controlled boolean NOT NULL DEFAULT false,
    -- Un enlace de transferencia conecta dos circuitos distintos y en estado
    -- normal permanece abierto para preservar la radialidad.
    is_tie boolean NOT NULL DEFAULT false,
    rated_current_a numeric(10, 2),
    interrupting_ka numeric(10, 2),
    geom geometry(Point, 4326) NOT NULL,
    last_operated_at timestamptz,
    CONSTRAINT switch_device_type_check CHECK (
        device_type IN (
            'circuit_breaker',
            'recloser',
            'sectionalizer',
            'fuse',
            'disconnector',
            'load_break_switch',
            'tie_switch'
        )
    ),
    CONSTRAINT switch_device_normal_state_check CHECK (normal_state IN ('open', 'closed')),
    CONSTRAINT switch_device_current_state_check CHECK (current_state IN ('open', 'closed')),
    CONSTRAINT switch_device_phases_check CHECK (phases ~ '^[ABC]{1,3}N?$'),
    CONSTRAINT switch_device_nodes_check CHECK (from_node_id <> to_node_id)
);

CREATE TABLE IF NOT EXISTS electrical.distribution_transformer (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    feeder_id integer REFERENCES electrical.feeder (id) ON DELETE SET NULL,
    hv_node_id bigint NOT NULL REFERENCES electrical.node (id),
    lv_node_id bigint NOT NULL REFERENCES electrical.node (id),
    structure_id bigint REFERENCES electrical.structure (id) ON DELETE SET NULL,
    hv_voltage_level_id smallint NOT NULL REFERENCES electrical.voltage_level (id),
    lv_voltage_level_id smallint NOT NULL REFERENCES electrical.voltage_level (id),
    rated_kva numeric(10, 2) NOT NULL,
    phases text NOT NULL,
    connection text,
    impedance_pct numeric(6, 3) NOT NULL DEFAULT 2.500,
    x_over_r numeric(6, 3) NOT NULL DEFAULT 3.000,
    mounting text,
    geom geometry(Point, 4326) NOT NULL,
    installed_on date,
    CONSTRAINT distribution_transformer_rating_check CHECK (rated_kva > 0),
    CONSTRAINT distribution_transformer_phases_check CHECK (phases ~ '^[ABC]{1,3}N?$'),
    CONSTRAINT distribution_transformer_nodes_check CHECK (hv_node_id <> lv_node_id),
    CONSTRAINT distribution_transformer_mounting_check CHECK (
        mounting IS NULL OR mounting IN ('pole', 'pad', 'vault', 'substation')
    )
);

-- ---------------------------------------------------------------------------
-- Clientes
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS electrical.service_point (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    lv_node_id bigint NOT NULL REFERENCES electrical.node (id),
    transformer_id bigint REFERENCES electrical.distribution_transformer (id) ON DELETE SET NULL,
    customer_class text NOT NULL,
    meter_code text,
    contracted_kw numeric(10, 3),
    phases text NOT NULL DEFAULT 'A',
    -- Clientes cuya interrupción exige priorización: hospitales, bombeos,
    -- telecomunicaciones críticas.
    is_priority boolean NOT NULL DEFAULT false,
    address text,
    municipality_name text,
    geom geometry(Point, 4326) NOT NULL,
    connected_on date,
    CONSTRAINT service_point_class_check CHECK (
        customer_class IN ('residential', 'commercial', 'industrial', 'official', 'street_lighting')
    ),
    CONSTRAINT service_point_phases_check CHECK (phases ~ '^[ABC]{1,3}N?$')
);

-- Demanda por punto de servicio o por transformador. Alimenta el flujo de carga
-- cuando no hay telemedida disponible.
CREATE TABLE IF NOT EXISTS electrical.load_measurement (
    id bigserial PRIMARY KEY,
    service_point_id bigint REFERENCES electrical.service_point (id) ON DELETE CASCADE,
    transformer_id bigint REFERENCES electrical.distribution_transformer (id) ON DELETE CASCADE,
    measured_at timestamptz NOT NULL,
    p_kw numeric(12, 3) NOT NULL,
    q_kvar numeric(12, 3) NOT NULL DEFAULT 0,
    source text NOT NULL DEFAULT 'estimated',
    CONSTRAINT load_measurement_target_check CHECK (
        (service_point_id IS NOT NULL) <> (transformer_id IS NOT NULL)
    ),
    CONSTRAINT load_measurement_source_check CHECK (
        source IN ('ami', 'scada', 'field_reading', 'estimated')
    )
);

-- ---------------------------------------------------------------------------
-- Maniobras
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS electrical.switching_order (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    purpose text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    feeder_id integer REFERENCES electrical.feeder (id) ON DELETE SET NULL,
    planned_start timestamptz,
    planned_end timestamptz,
    executed_start timestamptz,
    executed_end timestamptz,
    -- Resultado del estudio de factibilidad antes de autorizar la maniobra.
    validated_radial boolean,
    validated_ampacity boolean,
    validated_voltage boolean,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT switching_order_purpose_check CHECK (
        purpose IN ('planned_maintenance', 'fault_isolation', 'load_transfer', 'restoration', 'commissioning')
    ),
    CONSTRAINT switching_order_status_check CHECK (
        status IN ('draft', 'validated', 'approved', 'executing', 'completed', 'cancelled')
    )
);

CREATE TABLE IF NOT EXISTS electrical.switching_step (
    id bigserial PRIMARY KEY,
    switching_order_id bigint NOT NULL REFERENCES electrical.switching_order (id) ON DELETE CASCADE,
    step_number integer NOT NULL,
    switch_device_id bigint NOT NULL REFERENCES electrical.switch_device (id),
    action text NOT NULL,
    executed_at timestamptz,
    executed_by text,
    CONSTRAINT switching_step_action_check CHECK (action IN ('open', 'close', 'verify_open', 'ground', 'remove_ground')),
    CONSTRAINT switching_step_unique UNIQUE (switching_order_id, step_number)
);

-- ---------------------------------------------------------------------------
-- Interrupciones y confiabilidad
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS electrical.outage_event (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    feeder_id integer REFERENCES electrical.feeder (id) ON DELETE SET NULL,
    outage_class text NOT NULL,
    cause text,
    -- Elemento que originó la salida y elemento que la despejó.
    failed_element_type text,
    failed_element_id bigint,
    tripped_device_id bigint REFERENCES electrical.switch_device (id) ON DELETE SET NULL,
    started_at timestamptz NOT NULL,
    restored_at timestamptz,
    switching_order_id bigint REFERENCES electrical.switching_order (id) ON DELETE SET NULL,
    CONSTRAINT outage_event_class_check CHECK (outage_class IN ('sustained', 'momentary', 'planned')),
    CONSTRAINT outage_event_interval_check CHECK (restored_at IS NULL OR restored_at >= started_at)
);

-- Un cliente puede recuperar servicio por etapas (transferencia parcial), por
-- eso la duración se registra por cliente y no solo por evento.
CREATE TABLE IF NOT EXISTS electrical.outage_customer (
    id bigserial PRIMARY KEY,
    outage_event_id bigint NOT NULL REFERENCES electrical.outage_event (id) ON DELETE CASCADE,
    service_point_id bigint NOT NULL REFERENCES electrical.service_point (id) ON DELETE CASCADE,
    interrupted_at timestamptz NOT NULL,
    restored_at timestamptz,
    energy_not_served_kwh numeric(12, 3),
    CONSTRAINT outage_customer_unique UNIQUE (outage_event_id, service_point_id),
    CONSTRAINT outage_customer_interval_check CHECK (restored_at IS NULL OR restored_at >= interrupted_at)
);

-- ---------------------------------------------------------------------------
-- Índices espaciales y de consulta
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS substation_geom_gix ON electrical.substation USING gist (geom);
CREATE INDEX IF NOT EXISTS node_geom_gix ON electrical.node USING gist (geom);
CREATE INDEX IF NOT EXISTS structure_geom_gix ON electrical.structure USING gist (geom);
CREATE INDEX IF NOT EXISTS line_section_geom_gix ON electrical.line_section USING gist (geom);
CREATE INDEX IF NOT EXISTS switch_device_geom_gix ON electrical.switch_device USING gist (geom);
CREATE INDEX IF NOT EXISTS distribution_transformer_geom_gix ON electrical.distribution_transformer USING gist (geom);
CREATE INDEX IF NOT EXISTS service_point_geom_gix ON electrical.service_point USING gist (geom);

CREATE INDEX IF NOT EXISTS node_source_idx ON electrical.node (is_source) WHERE is_source;
CREATE INDEX IF NOT EXISTS line_section_from_node_idx ON electrical.line_section (from_node_id);
CREATE INDEX IF NOT EXISTS line_section_to_node_idx ON electrical.line_section (to_node_id);
CREATE INDEX IF NOT EXISTS line_section_feeder_idx ON electrical.line_section (feeder_id);
CREATE INDEX IF NOT EXISTS switch_device_from_node_idx ON electrical.switch_device (from_node_id);
CREATE INDEX IF NOT EXISTS switch_device_to_node_idx ON electrical.switch_device (to_node_id);
CREATE INDEX IF NOT EXISTS switch_device_tie_idx ON electrical.switch_device (is_tie) WHERE is_tie;
CREATE INDEX IF NOT EXISTS distribution_transformer_hv_node_idx ON electrical.distribution_transformer (hv_node_id);
CREATE INDEX IF NOT EXISTS service_point_lv_node_idx ON electrical.service_point (lv_node_id);
CREATE INDEX IF NOT EXISTS service_point_transformer_idx ON electrical.service_point (transformer_id);
CREATE INDEX IF NOT EXISTS load_measurement_measured_at_idx ON electrical.load_measurement (measured_at DESC);
CREATE INDEX IF NOT EXISTS outage_customer_event_idx ON electrical.outage_customer (outage_event_id);
