# Arquitectura del SIG eléctrico

Sistema de información geográfica para una red de distribución completa, desde la
subestación hasta el cliente, con análisis de topología, flujos de carga,
maniobras y confiabilidad.

## Componentes

| Componente | Ubicación | Rol |
| --- | --- | --- |
| Esquema de red | `sql/010_electric_network_schema.sql` | Modelo de datos georreferenciado en PostGIS. |
| Funciones de trazado | `sql/011_electric_network_topology.sql` | Energización, aislamiento y transferencias en la base de datos. |
| Datos de ejemplo | `sql/012_seed_sample_network.sql` | Red de prueba ubicada en Isla de Margarita. |
| Validación | `sql/013_validate_topology.sql` | Comprobación automática de las funciones de trazado. |
| Motor de análisis | `electric_gis/` | Topología, flujo de carga, maniobras y confiabilidad. |
| Skills del agente | `.cursor/skills/electrical-gis-*` | Criterios de ingeniería para trabajar sobre el sistema. |

## Modelo de datos

La conectividad se representa como grafo nodo-arista. `electrical.node`
concentra los puntos de conexión eléctrica y los elementos serie son aristas:

* `electrical.line_section` para tramos de media y baja tensión.
* `electrical.switch_device` para interruptores, reconectadores, seccionalizadores,
  fusibles, seccionadores y enlaces de transferencia.
* `electrical.distribution_transformer` como arista entre un nodo de media y uno
  de baja tensión.
* `electrical.power_transformer` para los transformadores de la subestación.

Los clientes son `electrical.service_point` y cuelgan de un nodo de baja tensión.
Las estructuras, `electrical.structure`, soportan elementos pero no conducen.

La energización no se almacena. Se deriva del recorrido desde los nodos fuente a
través de las aristas cerradas, de modo que nunca queda desactualizada.

## Niveles de tensión soportados

El catálogo `electrical.voltage_level` es configurable. Los datos de ejemplo
incluyen los niveles habituales de distribución:

* Subtransmisión: 34,5 kV.
* Media tensión: 13,8 kV.
* Baja tensión trifásica: 208/120 V.
* Baja tensión monofásica de dos hilos: 240 V.

Cada nivel declara la tensión entre fases y la tensión de cálculo fase-neutro por
separado, porque en el servicio monofásico de dos hilos la carga se sirve entre
conductores y no cumple la relación raíz de tres. Agregar 24 kV o 12,47 kV es
solo insertar una fila.

Pendiente de confirmación: la solicitud mencionaba "INEA 34". Se interpretó como
el nivel de 34,5 kV y así está modelado. Si se refiere a una norma específica con
requisitos de atributos o de simbología, hay que indicarlo para incorporarla al
catálogo y a las validaciones.

## Motor de análisis

### Topología

`electric_gis/topology.py` responde las consultas operativas fundamentales:
energización bajo escenarios hipotéticos, radialidad, zonas de maniobra,
dispositivo de protección que despeja una falla, clientes afectados y candidatos
de transferencia.

La detección de radialidad marca el origen de cada nodo, por lo que identifica no
solo anillos sino también dos subestaciones puestas en paralelo, caso que no
forma ciclo en el grafo pero es igualmente inadmisible.

### Flujo de carga

`electric_gis/loadflow.py` resuelve el flujo radial por barrido de sumatoria de
potencias, en unidades físicas, con la impedancia del transformador referida al
lado de baja tensión.

Hipótesis declaradas:

* Equivalente por fase con reparto equilibrado entre las fases presentes. No
  resuelve desequilibrio ni acoplamiento mutuo entre conductores.
* La caída de tensión de los elementos monofásicos y bifásicos incorpora el
  retorno por neutro mediante el factor de impedancia del lazo.
* Cargas a potencia constante, criterio conservador para caída de tensión y
  cargabilidad.

El resultado expone `power_balance_error_kw`, que debe ser nulo: la inyección de
las fuentes tiene que igualar la demanda servida más las pérdidas.

### Maniobras

`electric_gis/switching.py` genera y evalúa órdenes de maniobra. Toda maniobra se
valida contra radialidad, cargabilidad y tensión antes de considerarse
ejecutable.

La restauración ante falla incorpora dos verificaciones de seguridad:

* La protección solo se repone si el aislamiento dejó el elemento fallado sin
  alimentación. Si la falla está en su zona inmediata, la protección queda
  bloqueada abierta.
* Se descarta todo enlace de transferencia que reenergizaría el elemento fallado
  por el extremo opuesto.

### Confiabilidad

`electric_gis/reliability.py` calcula SAIFI, SAIDI, CAIDI, MAIFI, ASAI y energía
no suministrada según IEEE 1366, a partir de interrupciones por cliente para
reflejar correctamente las restauraciones por etapas.

## Puesta en marcha

Base de datos:

```bash
createdb gis_electrico
psql -d gis_electrico -f sql/010_electric_network_schema.sql
psql -d gis_electrico -f sql/011_electric_network_topology.sql
psql -d gis_electrico -f sql/012_seed_sample_network.sql
psql -d gis_electrico -f sql/013_validate_topology.sql
```

Motor de análisis y pruebas:

```bash
python3 -m pytest tests -q
```

Ejemplo de uso del motor:

```python
from electric_gis import plan_fault_restoration, solve
from electric_gis.sample_network import build_sample_network

network = build_sample_network()

flow = solve(network)
print(flow.feeders["F1"].current_a, flow.min_voltage_pu, flow.total_loss_kw)

plan = plan_fault_restoration(network, "L-A3-A4")
for step in plan.steps:
    print(step.step_number, step.device, step.action, step.reason)
print("Clientes sin servicio tras la maniobra:", plan.customers_still_out)
```

## Integración con la cartografía municipal

El paquete de cartografía de Nueva Esparta, descrito en
`docs/nueva_esparta_cartography.md`, aporta los límites municipales. Se combinan
con la red eléctrica para agrupar activos, clientes e índices de confiabilidad
por municipio mediante `ST_Contains` o `ST_Intersects` entre la geometría del
municipio y la del elemento.

## Alcance actual y extensiones necesarias

Implementado y verificado:

* Modelo de datos completo de subestación a cliente, aplicado sobre PostGIS.
* Trazado de topología en base de datos y en el motor de análisis.
* Flujo de carga radial de media y baja tensión con verificación de límites.
* Maniobras programadas, aislamiento de falla, transferencia y restauración.
* Índices de confiabilidad.

No implementado, y necesario para un despliegue de operación:

* Cálculo de cortocircuito y coordinación de protecciones, que requiere
  impedancias de secuencia negativa y cero y las curvas de los dispositivos.
* Flujo trifásico desequilibrado con acoplamiento mutuo.
* Reguladores de tensión y bancos de capacitores conmutables.
* Generación distribuida, que rompe el supuesto de flujo unidireccional desde la
  subestación.
* Integración con SCADA para el estado real de los dispositivos telecontrolados.
* Servicios de mosaicos vectoriales y la aplicación móvil, cuyos criterios de
  diseño están en la skill `electrical-gis-mobile-app`.
