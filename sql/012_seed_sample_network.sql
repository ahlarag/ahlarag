-- Datos de ejemplo para validar el modelo y las funciones de trazado.
--
-- La red reproduce la topología de electric_gis/sample_network.py y se ubica en
-- Isla de Margarita, estado Nueva Esparta. Las longitudes se derivan de la
-- geometría para que el dato declarado y el geográfico sean consistentes.

BEGIN;

TRUNCATE TABLE
    electrical.outage_customer,
    electrical.outage_event,
    electrical.switching_step,
    electrical.switching_order,
    electrical.load_measurement,
    electrical.service_point,
    electrical.distribution_transformer,
    electrical.switch_device,
    electrical.line_section,
    electrical.structure,
    electrical.feeder,
    electrical.power_transformer,
    electrical.node,
    electrical.substation,
    electrical.conductor_spec,
    electrical.voltage_level
RESTART IDENTITY CASCADE;

INSERT INTO electrical.voltage_level
    (code, name, nominal_kv, nominal_ln_kv, level_class, default_phases)
VALUES
    ('34.5kV', 'Subtransmisión 34,5 kV', 34.5, 19.9186, 'subtransmission', 3),
    ('13.8kV', 'Media tensión 13,8 kV', 13.8, 7.9674, 'medium', 3),
    ('208/120V', 'Baja tensión trifásica 208/120 V', 0.208, 0.1201, 'low', 3),
    -- Servicio monofásico de dos hilos: la carga se sirve entre conductores, por
    -- lo que la tensión de cálculo es la propia 240 V.
    ('240V', 'Baja tensión monofásica 240 V', 0.24, 0.24, 'low', 1);

INSERT INTO electrical.conductor_spec
    (code, description, material, size_label, r1_ohm_km, x1_ohm_km, r0_ohm_km, x0_ohm_km, ampacity_a)
VALUES
    ('ACSR-4/0', 'Troncal de media tensión', 'acsr', '4/0 AWG', 0.27450, 0.42000, 0.41000, 1.60000, 340.0),
    ('ACSR-2', 'Ramal de media tensión', 'acsr', '2 AWG', 0.85800, 0.45000, 1.02000, 1.70000, 180.0),
    ('LV-4/0', 'Circuito secundario trifásico', 'aluminum', '4/0 AWG', 0.27000, 0.08000, NULL, NULL, 230.0),
    ('LV-1/0', 'Circuito secundario monofásico', 'aluminum', '1/0 AWG', 0.53000, 0.09000, NULL, NULL, 150.0);

INSERT INTO electrical.substation (code, name, municipality_name, state_name, geom)
VALUES
    ('SUB-A', 'Subestación Porlamar', 'Mariño', 'Nueva Esparta',
     ST_SetSRID(ST_MakePoint(-63.8620, 10.9560), 4326)),
    ('SUB-B', 'Subestación Pampatar', 'Maneiro', 'Nueva Esparta',
     ST_SetSRID(ST_MakePoint(-63.8200, 10.9980), 4326));

INSERT INTO electrical.node (code, voltage_level_id, node_type, substation_id, is_source, geom)
SELECT
    seed.code,
    (SELECT id FROM electrical.voltage_level WHERE code = seed.voltage_code),
    seed.node_type,
    (SELECT id FROM electrical.substation WHERE code = seed.substation_code),
    seed.is_source,
    ST_SetSRID(ST_MakePoint(seed.lon, seed.lat), 4326)
FROM (
    VALUES
        ('HV-A',  '34.5kV',   'substation_busbar',  'SUB-A', true,  -63.8620, 10.9560),
        ('BUS-A', '13.8kV',   'substation_busbar',  'SUB-A', false, -63.8615, 10.9562),
        ('A1',    '13.8kV',   'pole_connection',    NULL,    false, -63.8600, 10.9570),
        ('A2',    '13.8kV',   'pole_connection',    NULL,    false, -63.8500, 10.9640),
        ('A3',    '13.8kV',   'pole_connection',    NULL,    false, -63.8495, 10.9645),
        ('A4',    '13.8kV',   'pole_connection',    NULL,    false, -63.8420, 10.9700),
        ('A4B',   '13.8kV',   'pole_connection',    NULL,    false, -63.8418, 10.9702),
        ('A5',    '13.8kV',   'pole_connection',    NULL,    false, -63.8380, 10.9760),
        ('A4LV',  '208/120V', 'transformer_lv',     NULL,    false, -63.8422, 10.9698),
        ('A4C',   '208/120V', 'service_connection', NULL,    false, -63.8425, 10.9694),
        ('A5LV',  '240V',     'transformer_lv',     NULL,    false, -63.8382, 10.9758),
        ('A5C',   '240V',     'service_connection', NULL,    false, -63.8385, 10.9754),
        ('HV-B',  '34.5kV',   'substation_busbar',  'SUB-B', true,  -63.8200, 10.9980),
        ('BUS-B', '13.8kV',   'substation_busbar',  'SUB-B', false, -63.8205, 10.9978),
        ('B1',    '13.8kV',   'pole_connection',    NULL,    false, -63.8215, 10.9970),
        ('B2',    '13.8kV',   'pole_connection',    NULL,    false, -63.8290, 10.9900),
        ('B3',    '13.8kV',   'pole_connection',    NULL,    false, -63.8295, 10.9895),
        ('B4',    '13.8kV',   'pole_connection',    NULL,    false, -63.8350, 10.9820),
        ('B3LV',  '208/120V', 'transformer_lv',     NULL,    false, -63.8297, 10.9893),
        ('B3C',   '208/120V', 'service_connection', NULL,    false, -63.8300, 10.9890)
) AS seed (code, voltage_code, node_type, substation_code, is_source, lon, lat);

INSERT INTO electrical.power_transformer
    (code, substation_id, hv_node_id, lv_node_id, rated_mva, impedance_pct, x_over_r)
SELECT
    seed.code,
    (SELECT id FROM electrical.substation WHERE code = seed.substation_code),
    (SELECT id FROM electrical.node WHERE code = seed.hv_code),
    (SELECT id FROM electrical.node WHERE code = seed.lv_code),
    10.0,
    8.0,
    15.0
FROM (
    VALUES
        ('PT-A', 'SUB-A', 'HV-A', 'BUS-A'),
        ('PT-B', 'SUB-B', 'HV-B', 'BUS-B')
) AS seed (code, substation_code, hv_code, lv_code);

INSERT INTO electrical.feeder
    (code, name, substation_id, voltage_level_id, source_node_id, rated_current_a, emergency_current_a)
SELECT
    seed.code,
    seed.name,
    (SELECT id FROM electrical.substation WHERE code = seed.substation_code),
    (SELECT id FROM electrical.voltage_level WHERE code = '13.8kV'),
    (SELECT id FROM electrical.node WHERE code = seed.source_code),
    400.0,
    480.0
FROM (
    VALUES
        ('F1', 'Circuito Porlamar 1', 'SUB-A', 'BUS-A'),
        ('F2', 'Circuito Pampatar 1', 'SUB-B', 'BUS-B')
) AS seed (code, name, substation_code, source_code);

INSERT INTO electrical.line_section (
    code, feeder_id, from_node_id, to_node_id, voltage_level_id, conductor_spec_id,
    network_type, installation, phases, length_m, geom
)
SELECT
    seed.code,
    (SELECT id FROM electrical.feeder WHERE code = seed.feeder_code),
    from_node.id,
    to_node.id,
    (SELECT id FROM electrical.voltage_level WHERE code = seed.voltage_code),
    (SELECT id FROM electrical.conductor_spec WHERE code = seed.conductor_code),
    seed.network_type,
    'overhead',
    seed.phases,
    round(ST_Length(ST_MakeLine(from_node.geom, to_node.geom)::geography)::numeric, 3),
    ST_MakeLine(from_node.geom, to_node.geom)
FROM (
    VALUES
        ('L-A1-A2',  'F1', 'A1',   'A2',  '13.8kV',   'ACSR-4/0', 'medium', 'ABC'),
        ('L-A3-A4',  'F1', 'A3',   'A4',  '13.8kV',   'ACSR-4/0', 'medium', 'ABC'),
        ('L-A4B-A5', 'F1', 'A4B',  'A5',  '13.8kV',   'ACSR-2',   'medium', 'ABC'),
        ('LV-A1',    'F1', 'A4LV', 'A4C', '208/120V', 'LV-4/0',   'low',    'ABCN'),
        ('LV-A2',    'F1', 'A5LV', 'A5C', '240V',     'LV-1/0',   'low',    'AN'),
        ('L-B1-B2',  'F2', 'B1',   'B2',  '13.8kV',   'ACSR-4/0', 'medium', 'ABC'),
        ('L-B3-B4',  'F2', 'B3',   'B4',  '13.8kV',   'ACSR-4/0', 'medium', 'ABC'),
        ('LV-B1',    'F2', 'B3LV', 'B3C', '208/120V', 'LV-4/0',   'low',    'ABCN')
) AS seed (code, feeder_code, from_code, to_code, voltage_code, conductor_code, network_type, phases)
JOIN electrical.node AS from_node ON from_node.code = seed.from_code
JOIN electrical.node AS to_node ON to_node.code = seed.to_code;

INSERT INTO electrical.switch_device (
    code, device_type, feeder_id, from_node_id, to_node_id, voltage_level_id,
    phases, normal_state, current_state, remote_controlled, is_tie, rated_current_a, geom
)
SELECT
    seed.code,
    seed.device_type,
    (SELECT id FROM electrical.feeder WHERE code = seed.feeder_code),
    from_node.id,
    to_node.id,
    (SELECT id FROM electrical.voltage_level WHERE code = '13.8kV'),
    'ABC',
    seed.normal_state,
    seed.normal_state,
    seed.remote_controlled,
    seed.is_tie,
    seed.rated_current_a,
    from_node.geom
FROM (
    VALUES
        ('BRK-F1',     'circuit_breaker',   'F1', 'BUS-A', 'A1',  'closed', true,  false, 600.0),
        ('REC-A2',     'recloser',          'F1', 'A2',    'A3',  'closed', true,  false, 400.0),
        ('SEC-A4',     'load_break_switch', 'F1', 'A4',    'A4B', 'closed', true,  false, 400.0),
        ('BRK-F2',     'circuit_breaker',   'F2', 'BUS-B', 'B1',  'closed', true,  false, 600.0),
        ('REC-B2',     'recloser',          'F2', 'B2',    'B3',  'closed', true,  false, 400.0),
        ('TIE-A5-B4',  'tie_switch',        NULL, 'A5',    'B4',  'open',   true,  true,  400.0)
) AS seed (code, device_type, feeder_code, from_code, to_code, normal_state, remote_controlled, is_tie, rated_current_a)
JOIN electrical.node AS from_node ON from_node.code = seed.from_code
JOIN electrical.node AS to_node ON to_node.code = seed.to_code;

INSERT INTO electrical.distribution_transformer (
    code, feeder_id, hv_node_id, lv_node_id, hv_voltage_level_id, lv_voltage_level_id,
    rated_kva, phases, impedance_pct, mounting, geom
)
SELECT
    seed.code,
    (SELECT id FROM electrical.feeder WHERE code = seed.feeder_code),
    hv_node.id,
    lv_node.id,
    (SELECT id FROM electrical.voltage_level WHERE code = '13.8kV'),
    (SELECT id FROM electrical.voltage_level WHERE code = seed.lv_voltage_code),
    seed.rated_kva,
    seed.phases,
    seed.impedance_pct,
    'pole',
    hv_node.geom
FROM (
    VALUES
        ('TR-A1', 'F1', 'A4', 'A4LV', '208/120V', 100.0, 'ABC', 4.0),
        ('TR-A2', 'F1', 'A5', 'A5LV', '240V',      50.0, 'AN',  2.5),
        ('TR-B1', 'F2', 'B3', 'B3LV', '208/120V', 100.0, 'ABC', 4.0)
) AS seed (code, feeder_code, hv_code, lv_code, lv_voltage_code, rated_kva, phases, impedance_pct)
JOIN electrical.node AS hv_node ON hv_node.code = seed.hv_code
JOIN electrical.node AS lv_node ON lv_node.code = seed.lv_code;

INSERT INTO electrical.service_point (
    code, lv_node_id, transformer_id, customer_class, contracted_kw, phases,
    is_priority, municipality_name, geom
)
SELECT
    seed.code,
    lv_node.id,
    (SELECT id FROM electrical.distribution_transformer WHERE code = seed.transformer_code),
    seed.customer_class,
    seed.contracted_kw,
    seed.phases,
    seed.is_priority,
    seed.municipality_name,
    lv_node.geom
FROM (
    VALUES
        ('SP-A4-01', 'A4C', 'TR-A1', 'residential', 20.0, 'ABC', false, 'Mariño'),
        ('SP-A4-02', 'A4C', 'TR-A1', 'commercial',  20.0, 'ABC', false, 'Mariño'),
        ('SP-A4-03', 'A4C', 'TR-A1', 'residential', 10.0, 'ABC', false, 'Mariño'),
        ('SP-A5-01', 'A5C', 'TR-A2', 'residential', 15.0, 'AN',  false, 'Mariño'),
        ('SP-A5-02', 'A5C', 'TR-A2', 'residential', 10.0, 'AN',  false, 'Mariño'),
        ('SP-B3-01', 'B3C', 'TR-B1', 'official',    40.0, 'ABC', true,  'Maneiro'),
        ('SP-B3-02', 'B3C', 'TR-B1', 'commercial',  20.0, 'ABC', false, 'Maneiro')
) AS seed (code, lv_code, transformer_code, customer_class, contracted_kw, phases, is_priority, municipality_name)
JOIN electrical.node AS lv_node ON lv_node.code = seed.lv_code;

COMMIT;
