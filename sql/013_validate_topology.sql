-- Validación de las funciones de trazado sobre los datos de ejemplo.
-- Falla con excepción si algún resultado no es el esperado, de modo que se puede
-- ejecutar en integración continua.

DO $$
DECLARE
    v_count integer;
    v_codes text[];
    v_sec_a4 bigint;
    v_brk_f1 bigint;
    v_tie bigint;
    v_kind text;
BEGIN
    SELECT id INTO v_sec_a4 FROM electrical.switch_device WHERE code = 'SEC-A4';
    SELECT id INTO v_brk_f1 FROM electrical.switch_device WHERE code = 'BRK-F1';
    SELECT id INTO v_tie FROM electrical.switch_device WHERE code = 'TIE-A5-B4';

    -- En estado normal toda la red está energizada y el enlace permanece abierto.
    SELECT count(*) INTO v_count FROM electrical.fn_energized_nodes();
    IF v_count <> (SELECT count(*) FROM electrical.node) THEN
        RAISE EXCEPTION 'Se esperaban todos los nodos energizados, se obtuvieron %', v_count;
    END IF;

    SELECT count(*) INTO v_count FROM electrical.fn_deenergized_service_points();
    IF v_count <> 0 THEN
        RAISE EXCEPTION 'Ningún cliente debería estar sin servicio, hay %', v_count;
    END IF;

    -- Abrir el interruptor de cabecera deja sin servicio el circuito completo.
    SELECT count(*) INTO v_count
    FROM electrical.fn_deenergized_service_points(ARRAY[v_brk_f1]);
    IF v_count <> 5 THEN
        RAISE EXCEPTION 'Se esperaban 5 clientes sin servicio en F1, se obtuvieron %', v_count;
    END IF;

    -- Abrir el seccionador solo afecta a lo que alimenta aguas abajo.
    SELECT array_agg(s.code ORDER BY s.code) INTO v_codes
    FROM electrical.fn_deenergized_service_points(ARRAY[v_sec_a4]) AS s;
    IF v_codes IS DISTINCT FROM ARRAY['SP-A5-01', 'SP-A5-02'] THEN
        RAISE EXCEPTION 'Clientes afectados inesperados al abrir SEC-A4: %', v_codes;
    END IF;

    -- El impacto de la maniobra se mide contra el estado actual.
    SELECT array_agg(c.code ORDER BY c.code) INTO v_codes
    FROM electrical.fn_customers_impacted_by_switching(ARRAY[v_sec_a4]) AS c
    WHERE c.impact = 'interrupted';
    IF v_codes IS DISTINCT FROM ARRAY['SP-A5-01', 'SP-A5-02'] THEN
        RAISE EXCEPTION 'Impacto inesperado al abrir SEC-A4: %', v_codes;
    END IF;

    -- La zona de maniobra de A4 está delimitada por el reconectador y el seccionador.
    SELECT array_agg(d.code ORDER BY d.code) INTO v_codes
    FROM electrical.fn_isolating_devices(
        (SELECT id FROM electrical.node WHERE code = 'A4')
    ) AS d;
    IF v_codes IS DISTINCT FROM ARRAY['REC-A2', 'SEC-A4'] THEN
        RAISE EXCEPTION 'Frontera de aislamiento inesperada para A4: %', v_codes;
    END IF;

    -- Con la red normal, el enlace representa una transferencia entre circuitos vivos.
    SELECT t.transfer_kind INTO v_kind
    FROM electrical.fn_transfer_candidates(
        (SELECT id FROM electrical.feeder WHERE code = 'F1')
    ) AS t;
    IF v_kind IS DISTINCT FROM 'live_transfer' THEN
        RAISE EXCEPTION 'Se esperaba live_transfer, se obtuvo %', v_kind;
    END IF;

    -- Tras aislar el ramal, el mismo enlace sirve para recuperar carga sin tensión.
    SELECT t.transfer_kind INTO v_kind
    FROM electrical.fn_transfer_candidates(
        (SELECT id FROM electrical.feeder WHERE code = 'F1'),
        ARRAY[v_sec_a4]
    ) AS t;
    IF v_kind IS DISTINCT FROM 'dead_load_pickup' THEN
        RAISE EXCEPTION 'Se esperaba dead_load_pickup, se obtuvo %', v_kind;
    END IF;

    -- Cerrar el enlace recupera a los clientes del ramal aislado.
    SELECT array_agg(c.code ORDER BY c.code) INTO v_codes
    FROM electrical.fn_customers_impacted_by_switching(ARRAY[v_sec_a4], ARRAY[v_tie]) AS c
    WHERE c.impact = 'interrupted';
    IF v_codes IS NOT NULL THEN
        RAISE EXCEPTION 'La transferencia no debería interrumpir clientes: %', v_codes;
    END IF;

    RAISE NOTICE 'Validación de topología completada sin errores';
END;
$$;
