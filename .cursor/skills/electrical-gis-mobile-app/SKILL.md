---
name: electrical-gis-mobile-app
description: >-
  Diseña y construye la aplicación móvil de campo de un SIG eléctrico: mapa con
  la red georreferenciada, levantamiento de postes y transformadores con GPS,
  operación sin conexión con sincronización posterior, ejecución de órdenes de
  maniobra, atención de fallas y consulta de clientes afectados. Usa esta skill
  cuando haya que construir o mejorar la aplicación para cuadrillas y
  operadores, definir el modelo sin conexión, o resolver conflictos de
  sincronización de datos de red.
---

# Aplicación móvil de campo para SIG eléctrico

Consume el modelo de `electrical-gis-network-model` y los análisis de las skills
de trazado, flujos y maniobras. La aplicación no reimplementa los cálculos:
consulta al servidor y muestra resultados.

## Requisito que define la arquitectura: operar sin conexión

Las cuadrillas trabajan donde no hay cobertura, y en una contingencia general la
red celular es lo primero que se congestiona. Si la aplicación necesita conexión
para funcionar, no sirve para el caso de uso que más importa.

Consecuencias de diseño:

* Base de datos local en el dispositivo con la porción de red asignada a la
  cuadrilla, no la red completa.
* Mosaicos de mapa descargados por adelantado para el área de trabajo.
* Toda acción del usuario se registra localmente y se encola para sincronizar.
* La interfaz indica siempre y de forma visible si el dato mostrado está
  sincronizado, pendiente o en conflicto.

## Sincronización y conflictos

Usa una cola de operaciones con identificador propio generado en el dispositivo,
para que reintentar no duplique registros. Cada operación lleva marca de tiempo
del dispositivo y del servidor.

Reglas de resolución por tipo de dato, porque no todos se tratan igual:

| Dato | Regla |
| --- | --- |
| Estado de dispositivo de maniobra | El servidor manda. Es dato operativo crítico y puede haber cambiado por telecontrol. Nunca lo sobreescribas desde el móvil sin confirmación explícita. |
| Levantamiento de un elemento nuevo | El dispositivo manda. Es información que solo existe en campo. |
| Corrección de atributos de un elemento existente | Resolución manual con las dos versiones a la vista. |
| Fotografías y evidencias | Se agregan, nunca se reemplazan. |

Nunca resuelvas conflictos de conectividad de red automáticamente. Un cambio de
conectividad mal aplicado corrompe todos los análisis posteriores.

## Levantamiento en campo

* Captura la coordenada con su precisión y rechaza o marca las lecturas con
  precisión insuficiente para el uso previsto. Un poste con precisión de quince
  metros no sirve para replanteo de obra.
* Permite corregir la posición arrastrando el elemento sobre el mapa o sobre una
  imagen satelital, porque a veces es más preciso que el GPS del dispositivo.
* Al agregar un elemento serie, obliga a declarar con qué elementos conecta. La
  conectividad no se deduce de la proximidad.
* Usa formularios que reflejen el catálogo del modelo de datos, con listas
  cerradas en lugar de texto libre para tipo de estructura, calibre de conductor
  y clase de cliente.
* Registra fotografía georreferenciada del elemento y de su placa de datos.

## Visualización de la red

Usa mosaicos vectoriales servidos desde la base de datos y estilos por capa. La
simbología debe seguir la convención del sector, que los operadores ya conocen:

* Media tensión y baja tensión en colores distintos y claramente diferenciados.
* Estado de los dispositivos de maniobra visible de un vistazo: cerrado, abierto
  y el caso importante de abierto fuera de su estado normal.
* Zonas sin tensión con relleno distintivo, calculado por el servidor.
* Etiquetas de identificación de circuito y de dispositivo legibles sin
  ampliar, porque se consultan con una sola mano y con guantes.

Para resaltar áreas, como un municipio o una zona sin servicio, dibuja el
contorno con un halo y el interior con relleno translúcido, de modo que el mapa
base siga siendo legible. La silueta del área debe verse completa.

## Funciones que la cuadrilla realmente usa

Priorízalas en este orden:

1. **Localizar un elemento** por código, por cliente o por cercanía a la posición
   actual.
2. **Ver a quién afecta** abrir un elemento, antes de operarlo, con el conteo de
   clientes y el destaque de clientes prioritarios.
3. **Ejecutar una orden de maniobra** paso a paso, confirmando cada uno, con
   bloqueo de los pasos fuera de secuencia.
4. **Reportar una falla** con su ubicación, causa y evidencia fotográfica.
5. **Consultar el estado del circuito**: qué está energizado y qué no.

## Seguridad operativa en la interfaz

La aplicación opera equipo eléctrico. Requisitos no negociables:

* Confirmación explícita en dos pasos para cualquier acción que cambie el estado
  de un dispositivo.
* Advertencia destacada cuando la maniobra afecte clientes prioritarios.
* Bloqueo de la maniobra si el estudio de factibilidad no está aprobado, con el
  motivo visible.
* Registro de auditoría de quién ejecutó qué, cuándo y con qué posición.
* No permitir la ejecución de un paso si el paso anterior no fue confirmado.

## Recomendaciones técnicas

* Mapa: una biblioteca de mosaicos vectoriales libre, con soporte de estilos
  declarativos y de mosaicos sin conexión.
* Almacenamiento local: una base relacional embebida con soporte espacial, para
  poder consultar por cercanía sin conexión.
* Consumo del servidor: expón los resultados de análisis como servicios que
  devuelvan geometrías con las propiedades de estilo ya resueltas, para que la
  aplicación no tenga que replicar reglas de negocio.
* Mide y limita el tamaño del paquete de datos descargado por cuadrilla. Cargar
  la red completa de un estado en un teléfono no es viable ni necesario.
