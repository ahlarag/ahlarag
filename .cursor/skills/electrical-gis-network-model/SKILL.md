---
name: electrical-gis-network-model
description: >-
  Diseña y mantiene el modelo de datos georreferenciado de una red de
  distribución eléctrica completa, desde la subestación hasta el cliente:
  subestaciones, transformadores de potencia, circuitos de media tensión,
  postes y estructuras, seccionamiento, transformadores de distribución, redes
  de baja tensión y puntos de servicio. Usa esta skill cuando se trate de
  esquemas PostGIS para redes eléctricas, conectividad nodo-arista, niveles de
  tensión, fases, catálogo de conductores, o cuando haya que cargar, validar o
  corregir datos de red en un SIG eléctrico.
---

# Modelo de red de distribución georreferenciada

Esta skill define el modelo de datos. Para trazado y energización usa
`electrical-gis-topology-tracing`, para flujos de carga
`electrical-gis-load-flow`, para maniobras `electrical-gis-switching-operations`
y para la aplicación de campo `electrical-gis-mobile-app`.

## Regla fundamental: conectividad nodo-arista

No modeles la red como geometrías sueltas. Un SIG eléctrico útil necesita un
grafo explícito, porque sin él no se puede trazar energización, calcular flujos
ni evaluar maniobras.

* `node` concentra todos los puntos de conexión eléctrica.
* Los elementos serie son aristas con `from_node_id` y `to_node_id`: tramos de
  línea, dispositivos de seccionamiento y transformadores.
* Los clientes cuelgan de un nodo de baja tensión.

La geometría es un atributo del elemento, no la fuente de la conectividad. Dos
líneas que se cruzan en el mapa no están conectadas si no comparten nodo. Nunca
derives conectividad por proximidad geométrica sin validarla.

## Regla fundamental: el estado de energización no se almacena

`energizado` no es un campo. Se deriva recorriendo el grafo desde los nodos
fuente a través de las aristas cerradas. Si lo almacenas, quedará desactualizado
en la primera maniobra y todos los análisis posteriores serán falsos.

Lo que sí se almacena es el estado de cada dispositivo de maniobra, con dos
campos distintos:

* `normal_state`: estado de diseño del dispositivo. Define la configuración
  normal del circuito.
* `current_state`: estado operativo real en este momento.

## Jerarquía de elementos

| Nivel | Elemento | Rol en el modelo |
| --- | --- | --- |
| Subestación | `substation`, `power_transformer` | Origen de la alimentación. El nodo de barra es la fuente del trazado. |
| Circuito | `feeder` | Unidad de operación y de reporte. Arranca en el interruptor de cabecera. |
| Media tensión | `line_section`, `switch_device` | Troncal y ramales, con su seccionamiento. |
| Estructuras | `structure` | Postes, torres y pedestales. Soportan elementos, no conducen. |
| Frontera MT/BT | `distribution_transformer` | Arista entre un nodo de media y uno de baja tensión. |
| Baja tensión | `line_section` con `network_type = 'low'` | Circuitos secundarios y acometidas. |
| Cliente | `service_point` | Punto de servicio con su medidor y clase tarifaria. |

Aplica el esquema de referencia en `sql/010_electric_network_schema.sql` y las
funciones de trazado en `sql/011_electric_network_topology.sql`.

## Niveles de tensión: declara siempre las dos tensiones

Un error frecuente y costoso es asumir que la tensión fase-neutro es la nominal
entre raíz de tres. Eso vale para sistemas trifásicos, pero no para el servicio
monofásico de dos hilos a 240 V, donde la carga se conecta entre conductores.

Por eso `voltage_level` declara `nominal_kv` y `nominal_ln_kv` por separado.
Si te equivocas aquí, todas las corrientes de baja tensión saldrán con el doble
o la mitad del valor real.

Niveles habituales en distribución:

* Subtransmisión: 34,5 kV y 24 kV.
* Media tensión: 13,8 kV y 12,47 kV.
* Baja tensión trifásica: 208/120 V y 400/230 V.
* Baja tensión monofásica: 240/120 V.

## Fases

Registra las fases presentes en cada elemento con la notación `ABC`, `AB`, `A`.
Es indispensable para:

* Verificar que un ramal monofásico no alimente una carga trifásica.
* Calcular la impedancia del lazo, que en circuitos monofásicos incluye el
  retorno por neutro y por tanto aproximadamente duplica la caída de tensión.
* Detectar desequilibrio de carga entre fases.

## Impedancias

El catálogo `conductor_spec` guarda impedancia por kilómetro, no por tramo. La
impedancia del tramo se calcula con su longitud. Guarda secuencia positiva para
flujos de carga y secuencia cero para cálculo de fallas a tierra.

Para transformadores guarda la impedancia porcentual sobre su potencia nominal y
la relación entre reactancia y resistencia. Al usarla en cálculos hay que
referirla a un lado concreto:

```
Z_base_por_fase = (V_fase_neutro_BT)^2 / (S_nominal / número_de_fases)
Z_ohm = (impedancia_porcentual / 100) * Z_base_por_fase
```

## Validaciones obligatorias al cargar datos

Ejecuta estas comprobaciones sobre cualquier carga de datos antes de darla por
buena. Los datos de campo casi siempre traen errores de conectividad:

1. Nodos huérfanos: nodos sin ninguna arista incidente.
2. Aristas con nodos de niveles de tensión distintos que no sean
   transformadores.
3. Islas sin fuente: componentes del grafo sin ningún nodo `is_source`.
4. Anillos en estado normal: la red de distribución debe ser radial.
5. Clientes sin transformador asociado o colgados de un nodo de media tensión.
6. Tramos cuya longitud declarada difiera de la longitud geométrica más de una
   tolerancia razonable, que indica geometría o conectividad mal capturada.
7. Fases incoherentes: un elemento con más fases que su elemento aguas arriba.
8. Transformadores cuya suma de demanda de clientes supere ampliamente su
   potencia nominal, que indica clientes mal asignados.

## Georreferenciación

* Almacena en EPSG:4326 para intercambio y visualización web.
* Para cálculos de longitud y distancia usa una proyección métrica adecuada a la
  zona, o funciones geodésicas, nunca grados.
* Registra la precisión del levantamiento y su origen en `structure`. Un poste
  capturado con precisión de quince metros no sirve para replanteo de obra.

## Al modificar el esquema

Usa migraciones numeradas y aditivas. Nunca reescribas una migración aplicada.
Cuando cambies la conectividad de un elemento en producción, conserva la
trazabilidad porque los análisis históricos de interrupciones dependen de la
topología que existía en ese momento.
