---
name: electrical-gis-load-flow
description: >-
  Calcula flujos de carga y corriente en redes de distribución de media y baja
  tensión: caída de tensión, cargabilidad de conductores y transformadores,
  pérdidas técnicas, y verificación de límites operativos. Usa esta skill cuando
  haya que resolver un flujo de potencia radial, dimensionar conductores,
  evaluar si un circuito soporta carga adicional, estimar pérdidas, analizar
  caída de tensión en baja tensión, o revisar el desequilibrio entre fases.
---

# Flujo de carga en redes de distribución

Requiere el modelo de `electrical-gis-network-model` y el trazado de
`electrical-gis-topology-tracing`. Implementación de referencia:
`electric_gis/loadflow.py`.

## Método: barrido hacia atrás y hacia adelante

Para redes radiales no uses Newton-Raphson ni Gauss-Seidel de transmisión. El
método adecuado es el barrido por sumatoria de potencias, porque aprovecha la
estructura de árbol, converge en pocas iteraciones y no requiere factorizar la
matriz de admitancias.

Cada iteración tiene dos pasos:

1. **Hacia atrás**, desde las puntas hacia la fuente: acumula la demanda y las
   pérdidas de cada elemento usando la tensión estimada del nodo aguas abajo.
2. **Hacia adelante**, desde la fuente hacia las puntas: actualiza las tensiones
   restando la caída de cada elemento.

Se repite hasta que el cambio máximo de tensión sea inferior a la tolerancia.
Antes de iterar, verifica que la red energizada sea radial: si hay anillo, el
barrido no es aplicable y hay que rechazarlo explícitamente en lugar de devolver
un resultado inválido.

## Unidades: trabaja en unidades físicas o en por unidad, pero sé consistente

La red mezcla niveles de tensión. Dos enfoques válidos:

* **Unidades físicas**: tensiones en voltios fase-neutro, impedancias en ohmios,
  y el transformador con su relación de transformación explícita. La impedancia
  del transformador se refiere al lado donde se calcula la corriente.
* **Por unidad**: una potencia base común y una tensión base por nodo. El
  transformador desaparece como relación pero hay que llevar la contabilidad de
  bases con cuidado.

El error más común es mezclar ambos sin darse cuenta, típicamente al referir mal
la impedancia del transformador. Verifica el resultado con el balance de potencia
descrito más abajo.

## Baja tensión: dos errores que invalidan el cálculo

**Retorno por neutro.** En un circuito trifásico equilibrado la corriente de
retorno es nula y la caída depende solo de la impedancia de fase. En un circuito
monofásico la corriente retorna por el neutro y el lazo tiene aproximadamente el
doble de impedancia. Si no aplicas el factor de lazo, subestimas la caída de
tensión en baja tensión a la mitad, que es justo donde más importa.

**Tensión de servicio.** En un servicio monofásico de dos hilos a 240 V la carga
se conecta entre conductores, no a 120 V contra neutro. Si usas 120 V como
tensión de cálculo, obtienes el doble de corriente real.

Ten presente la escala: en baja tensión las corrientes son intrínsecamente altas.
Cuarenta kilovoltamperios por fase a 120 V son más de trescientos amperios. Si tu
cálculo arroja un circuito secundario con cientos de kilovatios por un solo
conductor, el modelo de datos está mal, no el algoritmo.

## Verificación obligatoria: balance de potencia

Todo resultado debe cumplir que la potencia inyectada por las fuentes iguale la
demanda servida más las pérdidas. Si no cuadra, hay un error en el modelo, no un
problema de convergencia. Es la comprobación más rápida y efectiva:

```
inyección_fuentes = demanda_servida + pérdidas_totales
```

Comprueba también que las pérdidas sean un porcentaje razonable de la demanda.
Pérdidas técnicas del orden del uno al seis por ciento son normales en
distribución. Un veinte por ciento indica impedancias, longitudes o niveles de
tensión mal cargados.

## Qué reportar

* Tensión por nodo en voltios y en por unidad, con el mínimo del circuito.
* Corriente y cargabilidad porcentual por elemento respecto a su ampacidad.
* Pérdidas por elemento y totales.
* Violaciones separadas por tipo: subtensión, sobretensión, sobrecarga de
  conductor y sobrecarga de circuito.
* Cargas no suministradas, es decir las que quedaron en zona sin tensión.

Los límites de tensión pertenecen al nivel de tensión, no al algoritmo. Un
criterio habitual es más y menos cinco por ciento en media tensión, con margen
más estrecho en baja tensión por la caída de la acometida.

## Modelo de carga

Modela las cargas a potencia constante para verificar caída de tensión y
cargabilidad: es el criterio conservador, porque al bajar la tensión la corriente
sube. Si necesitas simular el comportamiento real de la demanda residencial,
considera un modelo mixto con componente de impedancia constante, pero declara
explícitamente el criterio usado en el reporte.

Cuando no haya telemedida, distribuye la demanda del circuito entre los
transformadores en proporción a su potencia nominal, y documenta que es una
estimación. Registra en el modelo de datos el origen del dato de demanda.

## Alcance y extensiones

El barrido equilibrado por fase resuelve el noventa por ciento de los casos de
planificación. Declara sus límites en lugar de ocultarlos:

* No resuelve desequilibrio real entre fases ni acoplamiento mutuo entre
  conductores. Para eso se requiere el método de barrido trifásico con matrices
  de impedancia de tres por tres calculadas con las ecuaciones de Carson.
* No calcula corrientes de cortocircuito. Para coordinación de protecciones se
  necesita el cálculo de fallas con impedancias de secuencia positiva, negativa y
  cero.
* No modela regulación automática de tensión ni compensación capacitiva
  conmutada. Si el circuito tiene reguladores o bancos de capacitores
  conmutables, su posición cambia el resultado.
