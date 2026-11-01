# Rendimiento

> [🇬🇧 English](../../../guide/performance.md) · [🇨🇳 中文](../../zh-CN/guide/performance.md) · [🇫🇷 Français](../../fr/guide/performance.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/performance.md) · [🇮🇹 Italiano](../../it/guide/performance.md) · [🇩🇪 Deutsch](../../de/guide/performance.md) · [🇳🇴 Norsk](../../nb/guide/performance.md)

Cada informe incluye una sección **performance**: latencia, tiempo hasta el
primer token (TTFT), tokens/s de decodificación y de extremo a extremo, latencia
y jitter entre fragmentos, tasas de error/timeout/429, un desglose de red
(conexión TCP, TLS, un viaje de ida y vuelta `GET /models`, tiempo de servidor) y
arranque en frío, cada uno como count / min / mean / p50 / p75 / p90 / p95 / p99
/ max / stdev.

Cuando se ejecuta la sonda dedicada, puntúa la dimensión **Rendimiento**. La
puntuación mide la **constancia**, no la velocidad bruta, así que un endpoint
lento pero constante (un modelo local o autoalojado) no se penaliza por no ser un
centro de datos; las comprobaciones y sus puntos están en la
[Metodología](methodology.md#performance--rendimiento). Los hallazgos de
rendimiento son como mucho de gravedad baja: mueven la puntuación, nunca el
veredicto de riesgo. Sin la sonda (`standard` sin
referencia, `smoke`), la dimensión no se ejecuta y sale de la puntuación global.

- **standard** reúne la sección a partir de las propias peticiones de la auditoría.
- **deep / full / custom** añaden una sonda dedicada: 100 peticiones no
  cacheables de 128 tokens de salida (un id de petición aleatorio abre cada
  prompt; no se envían parámetros de caché ni de razonamiento) más una ráfaga con
  `--concurrency`. Ajústala con `--performance-requests` (0 la desactiva) y
  `--performance-max-tokens`.
- La sonda usa streaming por defecto; `--performance-non-streaming` (o el
  selector **Streaming / Sin streaming** de la interfaz web) mide relays que no
  pueden hacer streaming. **full** mide ambos modos, intercalados, y los muestra
  lado a lado.
- **compare** ejecuta la sonda en ambos endpoints, alternando peticiones, y añade
  una tabla objetivo-vs-referencia (5 peticiones por lado en `standard`,
  demasiadas pocas para las comprobaciones de constancia) cuyas diferencias se
  marcan en verde ✓ cuando el objetivo es mejor y en rojo ✗ cuando es peor.

Los tokens se cuentan dos veces — a partir del `usage` del relay y localmente —,
así que el throughput se puede medir incluso sin `usage`. El conteo local es una
estimación con una heurística integrada (aproximadamente ±15-20 %; no se usa ni
se descarga ningún tokenizer), y la sección siempre lo indica. Un percentil solo
se muestra con suficientes muestras (p90 desde 10, p95 desde 20, p99 desde 100). El
informe JSON guarda los tiempos de cada petición (solo números, sin texto); el
informe HTML y la interfaz web los representan a lo largo de la línea temporal de
la auditoría.

Las auditorías que se ejecutan a la vez en `ekte serve` (varias pestañas del
navegador, monitores) no distorsionan los tiempos de las demás: la preparación
intensiva en CPU, como construir los largos prompts de ventana de contexto, se
ejecuta fuera del bucle de eventos del servidor.

**Tiempos de espera.** `timeout_sec` (`--timeout`, 60 s por defecto) es la base;
cada petición recibe más tiempo según el tamaño del prompt y el presupuesto de
salida, para que una sonda larga de ventana de contexto o un modelo autoalojado
lento no se corte al minuto. Los hosts locales y privados (`localhost`, `127.x`,
`192.168.x`, `host.docker.internal`, …) reciben al menos 300 s. `max_request_sec`
(`--max-request-time`, 900 s por defecto) es el tope absoluto de cada petición,
streams incluidos, así que ninguna petición puede quedarse colgada para siempre.
Una sonda de ventana de contexto que aun así agota el tiempo se informa como no
concluyente, no como truncamiento.
