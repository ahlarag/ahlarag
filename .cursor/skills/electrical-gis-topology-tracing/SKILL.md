---
name: electrical-gis-topology-tracing
description: >-
  Traza la topología de una red de distribución eléctrica: qué está energizado,
  qué clientes dependen de cada elemento, zonas de protección y aislamiento,
  radialidad, recorridos aguas arriba y aguas abajo, y candidatos de
  transferencia entre circuitos. Usa esta skill cuando haya que determinar
  clientes afectados por una salida, delimitar la zona mínima a desenergizar
  para un trabajo, identificar qué protección despeja una falla, o validar que
  la red siga siendo radial.
---

# Trazado de topología de la red

Requiere el modelo nodo-arista descrito en `electrical-gis-network-model`.
Implementación de referencia: `electric_gis/topology.py` y
`sql/011_electric_network_topology.sql`.

## Principio: todo se deriva del recorrido, nada se asume

Cada pregunta operativa se responde recorriendo el grafo desde las fuentes por
las aristas cerradas. Las cuatro consultas fundamentales son:

1. **Energización**: nodos alcanzables desde algún nodo fuente.
2. **Aguas abajo**: qué depende de un elemento, es decir a quién dejo sin
   servicio si lo abro.
3. **Aguas arriba**: qué alimenta a un punto, para saber qué protección lo
   respalda.
4. **Zona de maniobra**: la porción mínima de red que puedo dejar sin tensión,
   delimitada por dispositivos de seccionamiento.

## Análisis de escenarios sin modificar el estado

Nunca modifiques el estado de la red para responder una pregunta hipotética. El
trazado debe aceptar dispositivos forzados a abierto y a cerrado, de modo que la
misma función responda tanto la operación actual como el escenario propuesto:

```python
live_now = energized_nodes(network)
live_after = energized_nodes(network, force_open=["SEC-A4"], force_close=["TIE-A5-B4"])
```

Solo los elementos de maniobra pueden forzarse. Un tramo fuera de servicio por
avería representa una condición física, no una maniobra, y debe permanecer
abierto en todos los escenarios.

## Medir impacto contra el estado base correcto

Al contar clientes afectados, define explícitamente el estado contra el cual
comparas. Es el error de interpretación más frecuente:

* Para una maniobra programada, la base es la operación normal, y lo que
  interesa es cuántos clientes se interrumpen.
* Para una restauración, la base es el estado posterior al aislamiento de la
  falla, y lo que interesa es cuántos clientes recupera cada alternativa. Si
  comparas contra la operación normal, toda alternativa parecerá aportar cero.

Reporta siempre por separado los clientes prioritarios, como hospitales,
bombeos de agua y telecomunicaciones.

## Zonas de protección y aislamiento

La zona de maniobra que contiene un elemento se obtiene expandiendo desde él a
través de aristas que no son de maniobra, y deteniéndose en cada dispositivo de
seccionamiento. Esos dispositivos forman la frontera y son exactamente los que
hay que abrir para intervenir.

Consecuencia práctica que debes comunicar: la granularidad del seccionamiento
determina cuántos clientes se ven afectados. Si entre la protección y el punto
de falla no hay seccionamiento intermedio, no existe forma de restablecer a los
clientes de esa zona sin repararla. Este análisis es el que justifica inversión
en seccionamiento telecontrolado.

## Qué dispositivo despeja una falla

Solo interrumpen corriente de falla el interruptor, el reconectador y el
fusible. El seccionalizador no interrumpe falla: cuenta operaciones del
reconectador y abre durante el intervalo sin tensión. El seccionador de
operación con carga tampoco despeja falla.

Al recorrer aguas arriba desde el punto de falla, el primer elemento de esos
tres tipos es el que opera, y todo lo que él alimenta queda sin servicio. Por
eso el disparo de un elemento dentro de la subestación deja sin tensión el
circuito completo: la protección es el interruptor de cabecera.

## Radialidad

La red de distribución opera radialmente. Antes de autorizar cualquier cierre de
enlace entre circuitos hay que verificar que no queden dos fuentes alimentando
el mismo tramo.

Cuidado con una trampa habitual: unir dos circuitos radiales con un solo enlace
no crea un ciclo en el grafo, pero sí pone dos subestaciones en paralelo. La
detección debe marcar el origen de cada nodo y señalar cuando dos zonas ya
energizadas quedan unidas, no solo buscar ciclos.

Reporta el elemento que el operador va a maniobrar, no un tramo intermedio. Para
lograrlo, explora primero la red tal como está y después incorpora los cierres
propuestos.

## Candidatos de transferencia

Distingue dos situaciones porque las maniobras son distintas:

* **Recuperación de carga sin tensión**: el enlace tiene un extremo energizado y
  el otro no. Cerrarlo devuelve servicio y no requiere abrir nada más.
* **Transferencia entre circuitos vivos**: ambos extremos están energizados.
  Requiere abrir otro punto para no dejar dos fuentes en paralelo, salvo que se
  ejecute un traslape deliberado y controlado.

Descarta siempre los enlaces situados dentro de la zona fallada: cerrarlos
volvería a alimentar la falla por el otro extremo.

## Rendimiento

En redes grandes, el recorrido por nodo con consultas individuales a la base de
datos es inaceptablemente lento. Opciones válidas:

* Cargar la topología del circuito en memoria y recorrerla allí.
* Usar consultas recursivas o funciones en la base de datos sobre una vista
  unificada de aristas.
* Cachear el árbol del circuito e invalidarlo cuando cambie un estado de
  maniobra.
