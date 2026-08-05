---
name: electrical-gis-switching-operations
description: >-
  Planifica y valida maniobras en redes de distribución: apertura y cierre de
  seccionamiento para trabajos programados, aislamiento de fallas, transferencia
  de carga entre circuitos, restauración por etapas, y cálculo de índices de
  confiabilidad SAIFI, SAIDI, CAIDI, MAIFI y energía no suministrada. Usa esta
  skill cuando haya que generar una orden de maniobra, evaluar si un circuito de
  respaldo aguanta una transferencia, analizar el disparo de una protección, o
  medir el impacto de interrupciones programadas y fortuitas.
---

# Maniobras, transferencias y confiabilidad

Requiere `electrical-gis-topology-tracing` para el trazado y
`electrical-gis-load-flow` para verificar la factibilidad eléctrica.
Implementación de referencia: `electric_gis/switching.py` y
`electric_gis/reliability.py`.

## Los tres criterios de factibilidad

Ninguna maniobra se autoriza sin cumplir los tres simultáneamente. Evaluar solo
la topología es el error más peligroso: la maniobra "funciona" en el mapa y
quema conductor o deja el circuito en subtensión.

1. **Radialidad.** La red no puede quedar en anillo ni con dos fuentes
   alimentando el mismo tramo. Recuerda que unir dos circuitos radiales con un
   solo enlace no forma un ciclo en el grafo pero sí pone dos subestaciones en
   paralelo.
2. **Cargabilidad.** Ningún conductor, transformador ni circuito puede superar su
   límite al recibir la carga transferida. Para transferencias se admite el
   límite de emergencia del circuito, que suele ser mayor que el nominal.
3. **Tensión.** La caída debe mantenerse dentro de los límites del nivel
   correspondiente. Un ramal transferido queda alimentado desde más lejos, por lo
   que la tensión es la restricción que más frecuentemente bloquea la maniobra.

Evalúa siempre sobre un escenario hipotético, sin modificar el estado de la red
hasta que la maniobra se ejecute realmente.

## Secuencia ante una falla

La secuencia operativa correcta, en este orden:

1. **La protección ya operó.** Identifica qué dispositivo despejó la falla
   recorriendo aguas arriba: solo interruptor, reconectador y fusible interrumpen
   corriente de falla. Todo lo que ese dispositivo alimenta está sin servicio. El
   disparo de un elemento dentro de la subestación deja el circuito completo sin
   tensión.
2. **Aísla la zona fallada** abriendo los dispositivos de seccionamiento de su
   frontera.
3. **Repón la protección** para devolver servicio al tramo sano aguas arriba.
4. **Transfiere el tramo sano aguas abajo** a un circuito de respaldo.
5. **Repara y normaliza**, devolviendo los dispositivos a su estado normal.

## Dos trampas críticas en la restauración

**No repongas la protección si la falla sigue alimentada.** Cuando la falla está
inmediatamente aguas abajo de la protección y no hay seccionamiento intermedio,
cerrarla vuelve a energizar la falla. Verifica el escenario antes de incluir el
paso de cierre: simula la protección cerrada con los aislamientos abiertos y
comprueba que el elemento fallado quede sin tensión. Si no lo queda, la
protección debe permanecer abierta y bloqueada.

**No cierres un enlace situado dentro de la zona fallada.** Lo alimentaría por el
otro extremo. Antes de aceptar una transferencia, verifica que el elemento
fallado siga sin tensión después de cerrar el enlace.

Ambas verificaciones son barata de implementar y evitan una maniobra que
reenergiza una falla, con riesgo para el personal y para el equipo.

## Medir el aporte de cada alternativa

Al comparar opciones de restauración, el estado base es el posterior al
aislamiento de la falla, no la operación normal. Si comparas contra la operación
normal, toda alternativa parecerá no recuperar a nadie.

Ordena las alternativas por: primero las factibles, luego las que recuperan más
clientes, y como criterio de desempate el mayor margen de tensión. Reporta
siempre aparte los clientes prioritarios.

## Orden de maniobra

Una orden de maniobra es una secuencia numerada de pasos con acción explícita
sobre un dispositivo identificado. Acciones necesarias:

| Acción | Uso |
| --- | --- |
| `open` | Abrir el dispositivo. |
| `close` | Cerrar el dispositivo. |
| `verify_open` | Verificar ausencia de tensión antes de intervenir, y bloquear el recierre de una protección que debe permanecer abierta. |
| `ground` | Poner a tierra la zona de trabajo. |
| `remove_ground` | Retirar la puesta a tierra antes de normalizar. |

Indica en cada paso si el dispositivo es telecontrolado, porque determina si la
maniobra requiere cuadrilla en sitio y por tanto el tiempo de restauración. Un
análisis muy valioso es comparar el tiempo de restauración con el seccionamiento
actual frente al que se lograría con seccionamiento telecontrolado: es el
argumento cuantitativo para justificar la inversión.

Guarda el resultado del estudio de factibilidad junto con la orden, y registra
quién y cuándo ejecutó cada paso.

## Índices de confiabilidad

Calcula los índices por cliente y no por evento. En una restauración por etapas
cada grupo recupera el servicio en un momento distinto, y esa diferencia es
precisamente lo que mide el desempeño de la operación.

| Índice | Definición | Interpretación |
| --- | --- | --- |
| SAIFI | Interrupciones de cliente sostenidas entre clientes servidos | Cuántas veces al año se interrumpe el cliente promedio |
| SAIDI | Minutos de interrupción de cliente entre clientes servidos | Cuánto tiempo al año está sin servicio el cliente promedio |
| CAIDI | SAIDI entre SAIFI | Duración media de cada interrupción |
| MAIFI | Interrupciones momentáneas de cliente entre clientes servidos | Frecuencia de interrupciones breves |
| ASAI | Disponibilidad del servicio en porcentaje | Complemento del tiempo sin servicio |
| ENS | Energía no suministrada | Impacto económico de la interrupción |

Detalles que cambian el resultado y hay que declarar:

* El umbral entre interrupción momentánea y sostenida, habitualmente cinco
  minutos según IEEE 1366.
* Si las interrupciones programadas se incluyen o se reportan por separado, que
  suele depender del marco regulatorio aplicable.
* El universo de clientes servidos usado como denominador.

Agrupa los índices por circuito y por municipio para identificar dónde priorizar
inversión. Un circuito con SAIFI alto y SAIDI bajo tiene un problema de
protecciones o de vegetación; con SAIFI bajo y SAIDI alto, un problema de
seccionamiento y logística de restauración.
