-- Trazado de topología sobre el modelo electrical.*
--
-- Todas las funciones derivan el estado eléctrico por recorrido de grafo. El
-- estado de energización no se almacena: se calcula desde los nodos fuente
-- atravesando únicamente aristas conductoras.

-- Vista unificada de aristas. Homogeneiza tramos, seccionamiento y
-- transformadores para poder recorrer la red con una sola consulta.
CREATE OR REPLACE VIEW electrical.v_network_edge AS
SELECT
    'line_section'::text AS element_type,
    ls.id AS element_id,
    ls.code,
    ls.feeder_id,
    ls.from_node_id,
    ls.to_node_id,
    ls.phases,
    ls.in_service AS is_closed,
    false AS is_tie,
    ls.network_type,
    ls.geom::geometry AS geom
FROM electrical.line_section AS ls
UNION ALL
SELECT
    'switch_device'::text,
    sd.id,
    sd.code,
    sd.feeder_id,
    sd.from_node_id,
    sd.to_node_id,
    sd.phases,
    sd.current_state = 'closed',
    sd.is_tie,
    NULL::text,
    sd.geom::geometry
FROM electrical.switch_device AS sd
UNION ALL
SELECT
    'distribution_transformer'::text,
    dt.id,
    dt.code,
    dt.feeder_id,
    dt.hv_node_id,
    dt.lv_node_id,
    dt.phases,
    true,
    false,
    NULL::text,
    dt.geom::geometry
FROM electrical.distribution_transformer AS dt
UNION ALL
SELECT
    'power_transformer'::text,
    pt.id,
    pt.code,
    NULL::integer,
    pt.hv_node_id,
    pt.lv_node_id,
    'ABC'::text,
    true,
    false,
    NULL::text,
    s.geom::geometry
FROM electrical.power_transformer AS pt
JOIN electrical.substation AS s ON s.id = pt.substation_id;

-- Nodos energizados considerando maniobras hipotéticas.
--
-- p_force_open  : dispositivos que se asumen abiertos aunque estén cerrados.
-- p_force_close : dispositivos que se asumen cerrados aunque estén abiertos.
-- p_source_nodes: fuentes a considerar. NULL usa todos los nodos fuente.
--
-- Permite responder tanto "qué está energizado ahora" como "qué quedaría
-- energizado si ejecuto esta maniobra".
CREATE OR REPLACE FUNCTION electrical.fn_energized_nodes(
    p_force_open bigint[] DEFAULT '{}',
    p_force_close bigint[] DEFAULT '{}',
    p_source_nodes bigint[] DEFAULT NULL
)
RETURNS TABLE (node_id bigint)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_frontier bigint[];
    v_next bigint[];
    v_visited bigint[];
BEGIN
    IF p_source_nodes IS NULL THEN
        SELECT coalesce(array_agg(n.id), '{}')
        INTO v_frontier
        FROM electrical.node AS n
        WHERE n.is_source;
    ELSE
        v_frontier := p_source_nodes;
    END IF;

    v_visited := v_frontier;

    WHILE array_length(v_frontier, 1) IS NOT NULL LOOP
        SELECT coalesce(array_agg(DISTINCT reached), '{}')
        INTO v_next
        FROM (
            SELECT
                CASE WHEN e.from_node_id = ANY (v_frontier) THEN e.to_node_id ELSE e.from_node_id END AS reached
            FROM electrical.v_network_edge AS e
            WHERE (e.from_node_id = ANY (v_frontier) OR e.to_node_id = ANY (v_frontier))
              AND (
                  (e.element_type = 'switch_device' AND e.element_id = ANY (p_force_close))
                  OR (
                      e.is_closed
                      AND NOT (e.element_type = 'switch_device' AND e.element_id = ANY (p_force_open))
                  )
              )
        ) AS reachable
        WHERE reached <> ALL (v_visited);

        v_frontier := v_next;
        v_visited := v_visited || v_next;
    END LOOP;

    RETURN QUERY SELECT DISTINCT unnest(v_visited);
END;
$$;

-- Puntos de servicio sin suministro bajo un escenario de maniobra.
CREATE OR REPLACE FUNCTION electrical.fn_deenergized_service_points(
    p_force_open bigint[] DEFAULT '{}',
    p_force_close bigint[] DEFAULT '{}'
)
RETURNS TABLE (
    service_point_id bigint,
    code text,
    customer_class text,
    is_priority boolean,
    contracted_kw numeric,
    geom geometry
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        sp.id,
        sp.code,
        sp.customer_class,
        sp.is_priority,
        sp.contracted_kw,
        sp.geom::geometry
    FROM electrical.service_point AS sp
    WHERE sp.lv_node_id NOT IN (
        SELECT n.node_id
        FROM electrical.fn_energized_nodes(p_force_open, p_force_close) AS n
    );
$$;

-- Clientes que se quedarían sin servicio por una maniobra, comparando contra el
-- estado actual. Aísla el efecto propio de la maniobra y excluye a los clientes
-- que ya estaban fuera de servicio.
CREATE OR REPLACE FUNCTION electrical.fn_customers_impacted_by_switching(
    p_force_open bigint[] DEFAULT '{}',
    p_force_close bigint[] DEFAULT '{}'
)
RETURNS TABLE (
    service_point_id bigint,
    code text,
    is_priority boolean,
    impact text
)
LANGUAGE sql
STABLE
AS $$
    WITH current_out AS (
        SELECT s.service_point_id FROM electrical.fn_deenergized_service_points('{}', '{}') AS s
    ),
    scenario_out AS (
        SELECT s.service_point_id FROM electrical.fn_deenergized_service_points(p_force_open, p_force_close) AS s
    )
    SELECT
        sp.id,
        sp.code,
        sp.is_priority,
        CASE
            WHEN sp.id IN (SELECT service_point_id FROM scenario_out)
                 AND sp.id NOT IN (SELECT service_point_id FROM current_out)
                THEN 'interrupted'
            ELSE 'restored'
        END
    FROM electrical.service_point AS sp
    WHERE (
        sp.id IN (SELECT service_point_id FROM scenario_out)
        AND sp.id NOT IN (SELECT service_point_id FROM current_out)
    )
    OR (
        sp.id IN (SELECT service_point_id FROM current_out)
        AND sp.id NOT IN (SELECT service_point_id FROM scenario_out)
    );
$$;

-- Dispositivos de seccionamiento que aíslan un nodo del resto de la red.
-- Es la base para armar la orden de maniobra de un trabajo programado o para
-- delimitar la zona de falla.
CREATE OR REPLACE FUNCTION electrical.fn_isolating_devices(p_node_id bigint)
RETURNS TABLE (
    switch_device_id bigint,
    code text,
    device_type text,
    remote_controlled boolean,
    geom geometry
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_frontier bigint[] := ARRAY[p_node_id];
    v_visited bigint[] := ARRAY[p_node_id];
    v_next bigint[];
    v_boundary bigint[] := '{}';
BEGIN
    -- Se expande el área desde el nodo objetivo. La expansión se detiene en cada
    -- dispositivo de seccionamiento, que pasa a formar parte de la frontera.
    WHILE array_length(v_frontier, 1) IS NOT NULL LOOP
        SELECT coalesce(array_agg(DISTINCT e.element_id), '{}')
        INTO v_next
        FROM electrical.v_network_edge AS e
        WHERE (e.from_node_id = ANY (v_frontier) OR e.to_node_id = ANY (v_frontier))
          AND e.element_type = 'switch_device';

        v_boundary := v_boundary || v_next;

        SELECT coalesce(array_agg(DISTINCT reached), '{}')
        INTO v_next
        FROM (
            SELECT
                CASE WHEN e.from_node_id = ANY (v_frontier) THEN e.to_node_id ELSE e.from_node_id END AS reached
            FROM electrical.v_network_edge AS e
            WHERE (e.from_node_id = ANY (v_frontier) OR e.to_node_id = ANY (v_frontier))
              AND e.element_type <> 'switch_device'
              AND e.is_closed
        ) AS reachable
        WHERE reached <> ALL (v_visited);

        v_frontier := v_next;
        v_visited := v_visited || v_next;
    END LOOP;

    RETURN QUERY
    SELECT sd.id, sd.code, sd.device_type, sd.remote_controlled, sd.geom::geometry
    FROM electrical.switch_device AS sd
    WHERE sd.id = ANY (v_boundary);
END;
$$;

-- Enlaces de transferencia disponibles para respaldar un circuito.
--
-- Se distinguen dos casos, porque la maniobra requerida es distinta:
--   * dead_load_pickup: un extremo energizado y el otro sin tensión. Cerrarlo
--     devuelve servicio y no exige abrir nada más.
--   * live_transfer: ambos extremos energizados. Exige abrir otro punto para no
--     dejar dos fuentes en paralelo.
CREATE OR REPLACE FUNCTION electrical.fn_transfer_candidates(
    p_feeder_id integer,
    p_force_open bigint[] DEFAULT '{}',
    p_force_close bigint[] DEFAULT '{}'
)
RETURNS TABLE (
    switch_device_id bigint,
    code text,
    device_type text,
    remote_controlled boolean,
    transfer_kind text,
    remote_node_id bigint,
    geom geometry
)
LANGUAGE sql
STABLE
AS $$
    WITH feeder_source AS (
        SELECT ARRAY[f.source_node_id] AS source_nodes
        FROM electrical.feeder AS f
        WHERE f.id = p_feeder_id
    ),
    own_nodes AS (
        SELECT n.node_id
        FROM feeder_source AS fs
        CROSS JOIN LATERAL electrical.fn_energized_nodes(
            p_force_open, p_force_close, fs.source_nodes
        ) AS n
    ),
    live_nodes AS (
        SELECT n.node_id
        FROM electrical.fn_energized_nodes(p_force_open, p_force_close) AS n
    ),
    ties AS (
        SELECT
            sd.*,
            sd.from_node_id IN (SELECT node_id FROM live_nodes) AS from_live,
            sd.to_node_id IN (SELECT node_id FROM live_nodes) AS to_live,
            sd.from_node_id IN (SELECT node_id FROM own_nodes) AS from_own,
            sd.to_node_id IN (SELECT node_id FROM own_nodes) AS to_own
        FROM electrical.switch_device AS sd
        WHERE sd.is_tie
          AND NOT (
              sd.id = ANY (p_force_close)
              OR (sd.current_state = 'closed' AND NOT sd.id = ANY (p_force_open))
          )
    )
    SELECT
        t.id,
        t.code,
        t.device_type,
        t.remote_controlled,
        CASE WHEN t.from_live AND t.to_live THEN 'live_transfer' ELSE 'dead_load_pickup' END,
        CASE WHEN t.from_live THEN t.to_node_id ELSE t.from_node_id END,
        t.geom::geometry
    FROM ties AS t
    WHERE (t.from_live <> t.to_live)
       OR (t.from_live AND t.to_live AND (t.from_own OR t.to_own));
$$;
