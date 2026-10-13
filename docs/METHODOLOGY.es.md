# zing — Metodología

> [🇬🇧 English](METHODOLOGY.md) · [🇨🇳 中文](METHODOLOGY.zh-CN.md) · [🇫🇷 Français](METHODOLOGY.fr.md) · **🇪🇸 Español** · [🇵🇹 Português](METHODOLOGY.pt.md) · [🇮🇹 Italiano](METHODOLOGY.it.md) · [🇩🇪 Deutsch](METHODOLOGY.de.md)

Este documento explica cómo llega **zing** a su veredicto: qué sondas de caja
negra envía cada detector, cómo sus resultados se convierten en puntos, cómo
los puntos se convierten en puntuaciones de dimensión y en una puntuación
global, y cómo se decide el veredicto de riesgo. Describe la implementación
actual; cada tabla de puntuación de abajo es la escala publicada del detector
(`SCALE` en `zing/detectors/*.py`), con la misma redacción que la interfaz web
muestra en **Escala de puntuación**.

> zing aporta **evidencia de caja negra de desviaciones y riesgos, no una
> prueba criptográfica de fraude.** Consulta [Límites y uso responsable](#límites-y-uso-responsable).

---

## Postura de base

Un relay puede, por motivos legítimos, desviarse, actualizar sus snapshots,
compartir capacidad o almacenar en búfer un upstream que no sabe hacer
streaming. Por eso zing trata cada señal aislada como un *indicador de riesgo*,
nunca como un veredicto: los hallazgos se basan en evidencia, se formulan con
cautela, y un resultado ambiguo queda **no concluyente** en lugar de forzarse a
correcto o fallo. El veredicto de riesgo solo llega a «alto» con evidencia
sólida de gravedad alta, y la confirmación más fuerte es siempre el **modo
comparación** (`zing compare`): ejecutar las mismas sondas, al mismo tiempo,
contra una *referencia de confianza del modelo declarado*.

## Cómo puntúa zing

### Puntuación del detector

Cada detector publica su **escala de puntuación** (`DetectorResult.scoring`,
construida con `zing/detectors/scale.py`): cada resultado posible de cada una de
sus comprobaciones, con estado, gravedad y efecto en la puntuación. Cada
hallazgo registra el `outcome` alcanzado, así que informe y comportamiento no
pueden divergir. Una escala usa uno de dos métodos:

- **Media de las comprobaciones** (`Scale`, método `mean_of_checks`): cada
  comprobación da puntos; la puntuación del detector es la media de las
  comprobaciones que computan. Un resultado marcado **No computa**
  (normalmente una comprobación no concluyente) ni sube ni baja la puntuación.
- **Deducciones** (`DeductionScale`, método `deductions`): la puntuación parte
  de 100, los hallazgos restan puntos (`Finding.deduction`) y/o la limitan
  (`Finding.cap`); gana el tope más bajo.

Una comprobación *parametrizada* aplica un mismo conjunto de filas a muchos
sujetos (por ejemplo, cada atributo de la respuesta): cada sujeto se puntúa por
separado, la escala se publica una vez por comprobación y los informes listan
los sujetos bajo su comprobación.

### Puntuación y estado de una dimensión

zing puntúa diez dimensiones. La puntuación de una dimensión es la **media con
igual peso de las puntuaciones de sus detectores**: un detector con muchas
comprobaciones no pesa más que uno con pocas, y un detector sin puntuación
numérica queda fuera. Su estado es el peor estado que concluyeron sus
detectores, salvo que un hallazgo de gravedad ALTA/CRÍTICA impone **Fallo** y
un hallazgo de gravedad MEDIA eleva **Correcto** a **Advertencia**, sea cual sea
la puntuación. Cada informe registra este cálculo por dimensión
(`DimensionScore.breakdown`: la puntuación de cada detector, si computó, y
cualquier cambio de estado con los hallazgos que lo causaron) y lo muestra en
**Dimension details** (Markdown/HTML/PDF) y en las filas desplegables de
**Comprobaciones por dimensión** de la interfaz web. Un detector que falla
internamente aparece con estado **Error** y nunca interrumpe la auditoría.

### Puntuación global, nota y pesos

La **puntuación de salud global** es la media ponderada de las dimensiones que
produjeron una puntuación (`DIMENSION_WEIGHTS` en `zing/scoring.py`). Una
dimensión que no se ejecutó (fuera de la suite, o no seleccionada en una
ejecución `custom`) sale del cálculo y los pesos restantes se renormalizan. La
nota es A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) o F.

| Dimensión | Id | Peso | Papel |
|---|---|---|---|
| Identidad del modelo | `model_identity` | 21 | núcleo |
| Ventana de contexto | `context_window` | 19 | núcleo |
| Capacidades declaradas | `capability` | 13 | núcleo |
| Conformidad del protocolo | `protocol` | 8 |  |
| Facturación y uso | `billing` | 8 |  |
| Conectividad | `connectivity` | 7 |  |
| Autenticidad del streaming | `streaming` | 6 |  |
| Fiabilidad en concurrencia | `reliability` | 6 |  |
| Seguridad del transporte | `security` | 6 |  |
| Rendimiento | `performance` | 6 |  |

Las tres **dimensiones núcleo** son aquellas cuyo fallo revela más directamente
un «gato por liebre».

### Veredicto de riesgo

El nivel de riesgo depende de la **gravedad de los hallazgos**, no de la
puntuación. Los hallazgos de la dimensión de conectividad quedan fuera: un relay
caído o limitado no pudo evaluarse, y eso no prueba que responda otro modelo.

| Riesgo | Etiqueta en la interfaz | Cuándo |
|---|---|---|
| `inconclusive` | Señal insuficiente | Ninguna dimensión núcleo dio un resultado utilizable (Correcto, Advertencia o Fallo) — por ejemplo, relay inaccesible, modelo sin perfil o ejecución `custom` sin dimensión núcleo |
| `high` | Gato por liebre | Un hallazgo CRÍTICO, un hallazgo ALTO/CRÍTICO en una dimensión núcleo, o dos o más hallazgos ALTOS |
| `medium` | Desviaciones detectadas | Exactamente un hallazgo ALTO fuera de las dimensiones núcleo, o un hallazgo MEDIO en una dimensión núcleo |
| `low` | Mayormente fiable | Cualquier otro hallazgo MEDIO |
| `clean` | Coherente (probablemente auténtico) | Ninguno de los anteriores |

### Confianza del veredicto

- **Baja** — el modelo declarado no está en la base de conocimiento, o menos de
  dos dimensiones núcleo dieron un resultado utilizable;
- **Media** — al menos dos dimensiones núcleo dieron un resultado utilizable;
- **Alta** — se usó una referencia *y* las tres dimensiones núcleo dieron un
  resultado utilizable, o la confianza era media y el juez LLM devolvió un
  veredicto utilizable.

## Suites, detectores y modos

| Detector | Id | Dimensión | Desde la suite |
|---|---|---|---|
| Conectividad y completado básico | `connectivity` | Conectividad | `smoke` |
| Conformidad de compatibilidad con OpenAI | `protocol` | Conformidad del protocolo | `standard` |
| Compatibilidad de atributos de solicitud | `protocol_request` | Conformidad del protocolo | `standard` |
| Disponibilidad de atributos de respuesta | `protocol_response` | Conformidad del protocolo | `standard` |
| Determinismo y corrección de caché | `determinism` | Conformidad del protocolo | `deep` |
| Ventana de contexto real y truncado | `context_window` | Ventana de contexto | `deep` |
| Identidad del modelo y huella de degradación | `model_identity` | Identidad del modelo | `standard` |
| Evaluación de calidad / degradación por un LLM juez | `quality_judge` | Identidad del modelo | `deep` (solo con `--judge`) |
| Verificación de capacidades declaradas | `capability` | Capacidades declaradas | `standard` |
| Verificación de la capacidad multimodal (visión) | `vision` | Capacidades declaradas | `deep` |
| Autenticidad del streaming | `streaming` | Autenticidad del streaming | `standard` |
| Auditoría de facturación de tokens | `billing` | Facturación y uso | `standard` |
| Fiabilidad y latencia en concurrencia | `reliability` | Fiabilidad en concurrencia | `standard` |
| Señales de transporte y manejo de secretos | `security` | Seguridad del transporte | `smoke` |
| Detección de prompt de sistema inyectado | `injected_prompt` | Seguridad del transporte | `deep` |
| Integridad de respuestas / manipulación | `integrity` | Seguridad del transporte | `deep` |
| Caché de prefijo de prompt (tiempos) | `prompt_cache` | Seguridad del transporte | `deep` |
| Sonda de rendimiento | `performance` | Rendimiento | `deep` (en `standard` solo con una referencia, 5 solicitudes) |

- **smoke** ejecuta conectividad y seguridad; **standard** añade los detectores
  de protocolo, identidad, capacidades, streaming, facturación y fiabilidad;
  **deep** añade las sondas de contexto largo, determinismo, visión, prompt
  inyectado, integridad, caché de prompt y rendimiento (y el juez con
  `--judge`); **full** ejecuta los mismos detectores que deep y mide el
  rendimiento con y sin streaming; **custom** ejecuta todos los detectores de
  las dimensiones seleccionadas, con la profundidad de deep.
- **Código puro (por defecto):** todos los detectores salvo `quality_judge`
  deciden con código determinista — comprobaciones de texto y de expresiones
  regulares, aritmética, estadística de tiempos. No hace falta un segundo
  modelo.
- **Híbrido código + LLM (`--judge`):** `quality_judge` pregunta a un modelo
  juez de confianza, configurado aparte (nunca el objetivo), si las respuestas
  del objetivo se parecen al modelo declarado. Sin `--judge-base-url`, el modo
  comparación usa la referencia como juez.
- **Modo comparación** (`zing compare`) da a las sondas una referencia de
  confianza: `model_identity` registra la autoidentificación de la referencia
  junto a la del objetivo, `protocol_request` reenvía a la referencia los
  parámetros rechazados, `integrity` eleva a CRÍTICA una sustitución que la
  referencia no hace, `quality_judge` muestra ambos lados al juez y
  `performance` sondea ambos endpoints de forma alterna. La confianza solo puede
  ser alta con una referencia.
- **Base de conocimiento:** el perfil del modelo declarado
  (`zing/knowledge/data/*.yaml` más tus propias entradas en `kb.db`) aporta la
  ventana de contexto declarada, la salida máxima, el tokenizer, las
  capacidades, las palabras clave de identidad y las huellas de comportamiento
  con las que se juzgan las sondas. Cada informe registra el perfil usado
  (`knowledge`).
- **Idioma de los prompts:** cada texto de sonda está en
  `zing/prompts/en.json` y es en inglés sea cual sea el idioma de la interfaz;
  solo las huellas cuyo idioma *es* la medida declaran `prompt_lang` y
  `language_bound`. Cada informe lista los idiomas de las sondas usadas
  (`prompt_languages`).
- **Modelos de razonamiento:** una sonda corta que termina en su límite de
  salida con la respuesta ausente, o cortada después de que el razonamiento usara al
  menos la mitad del límite (se informan `reasoning_tokens`), se repite una vez con un
  límite de 4.096 tokens, para que un modelo que piensa antes de responder no se
  lea como fallo. Las sondas cuyo límite o tiempo es la medida (rendimiento,
  caché de prompts, fiabilidad, prompt inyectado, salida máxima, el atributo de
  solicitud `max_tokens`) nunca se repiten. Una vez que se sabe que un endpoint
  razona (su perfil dice `reasoning: true`, o tras su primera repetición de este
  tipo), las sondas cortas se envían desde el principio con el límite de 4.096
  tokens en lugar de dos veces.

---

## `connectivity` — Conectividad

**Detecta.** Ningún truco directamente: es la puerta de la que dependen todos
los demás detectores. Separa una clave muerta o mal configurada de un relay que
merece auditarse.

**Cómo funciona.** `GET /v1/models` (anota si el modelo declarado aparece) y
una completion de chat a `temperature=0` que pide al modelo repetir un canario
exacto; registra la latencia y el campo `model` devuelto.

**Escala de puntuación** (`zing/detectors/connectivity.py`):

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `connectivity.models` | La lista de modelos (/v1/models) respondió. | Correcto | 100 pts |
|  | La lista de modelos (/v1/models) no respondió; algunos relays la desactivan. | Advertencia · Baja | 60 pts |
| `connectivity.chat` | Una completion de chat devolvió contenido y repitió el canario. | Correcto | 100 pts |
|  | Una completion de chat devolvió contenido, pero no repitió el canario. | Correcto | 85 pts |
|  | La completion de chat falló o no devolvió contenido. | Fallo · Alta | 0 pts |

**Advertencias.** La ausencia de `/v1/models` es benigna; muchos relays la
desactivan. Un error de red pasajero o un 5xx puede hacer fallar la
comprobación de chat: vuelve a ejecutar. La conectividad no prueba nada sobre
*qué* modelo respondió. Sus hallazgos nunca elevan el veredicto de riesgo.

---

## `protocol` — Conformidad del protocolo

**Detecta.** Relays cuyo middleware rompe el contrato del protocolo (turnos
perdidos, secuencias de parada ignoradas, errores malformados, campos de
respuesta ausentes o a cero, parámetros de solicitud eliminados) y, mediante el
determinismo, `cache.ignore-temperature`. Cubre en parte
`capability.json-tool-fakery`.

### `protocol` — Conformidad de compatibilidad con OpenAI

**Cómo funciona.** Tres sondas: una conversación multiturno que debe recordar
un color de un turno anterior; una secuencia `stop` que debe cortar la salida;
y una solicitud deliberadamente inválida (`messages` vacío) que debe
rechazarse con un 4xx, idealmente con un cuerpo de error al estilo OpenAI.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `protocol.multi_turn` | Se recordó el color de un turno anterior. | Correcto | 100 pts |
|  | No se recordó el color de un turno anterior. | Advertencia · Media | 55 pts |
|  | No hubo una respuesta útil para evaluar. | No concluyente · Baja | No computa |
| `protocol.stop` | La salida se detuvo en la secuencia de parada. | Correcto | 100 pts |
|  | No se pudo confirmar el manejo de la parada a partir del texto. | Advertencia · Baja | 70 pts |
|  | Se devolvió texto posterior a la secuencia de parada. | Advertencia · Baja | 60 pts |
|  | No hubo una respuesta útil para evaluar. | No concluyente · Baja | No computa |
| `protocol.error_schema` | Rechazada con un 4xx y un cuerpo de error al estilo OpenAI. | Correcto | 100 pts |
|  | Rechazada con un 4xx, pero el cuerpo no sigue el estilo OpenAI. | Advertencia · Baja | 80 pts |
|  | Sin respuesta HTTP; no se pudo confirmar el manejo de errores del cliente. | Advertencia · Baja | 55 pts |
|  | Otro estado HTTP; no se pudo confirmar el manejo de errores del cliente. | Advertencia · Baja | 55 pts |
|  | La solicitud no válida provocó un error del servidor (5xx). | Fallo · Media | 35 pts |
|  | La solicitud no válida fue aceptada (2xx). | Fallo · Media | 30 pts |

### `protocol_response` — Disponibilidad de atributos de respuesta

**Cómo funciona.** Una llamada normal sin streaming; cada atributo del
protocolo del objetivo (OpenAI Chat Completions, Anthropic Messages u OpenAI
Responses; catálogo en `zing/detectors/wire_attrs.py`) se juzga sobre el cuerpo
en bruto. Los atributos principales son, por ejemplo, `model`,
`choices[0].message.role/content`, `finish_reason`, `usage.prompt_tokens`,
`usage.completion_tokens` y `usage.total_tokens` (que debe ser la suma de los
dos); los secundarios son `id`, `object`, `created`/`created_at`,
`choices[0].index` y `type`. Un cero donde un recuento debe ser positivo
(`completion_tokens: 0` para una respuesta no vacía) cuenta como cero, no como
válido.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `protocol_response.core` (Atributos de respuesta principales) | Presente con un valor válido. | Correcto | 100 pts |
|  | Presente pero cero o vacío (p. ej., completion_tokens: 0). | Fallo · Media | 20 pts |
|  | Presente con un tipo o valor incorrecto (p. ej., total ≠ suma de las partes). | Advertencia · Media | 40 pts |
|  | Ausente en la respuesta. | Fallo · Media | 0 pts |
| `protocol_response.minor` (Atributos de respuesta secundarios) | Presente con un valor válido. | Correcto | 100 pts |
|  | Presente pero cero o vacío. | Advertencia · Baja | 50 pts |
|  | Presente con un tipo o valor incorrecto. | Advertencia · Baja | 70 pts |
|  | Ausente en la respuesta. | Advertencia · Baja | 60 pts |
| `protocol_response.call` (Sondeo de atributos de respuesta) | La llamada de sondeo no devolvió un cuerpo de respuesta que evaluar. | No concluyente · Baja | No computa |

### `protocol_request` — Compatibilidad de atributos de solicitud

**Cómo funciona.** Se envía cada parámetro de solicitud del protocolo (unas
cinco llamadas). Los parámetros con efecto observable tienen su propia llamada y
deben mostrarlo: `system`/`instructions` seguido, el límite de salida termina en
`finish_reason: length`, `n: 2` devuelve dos opciones, se devuelven
`logprobs`. Los parámetros que solo deben aceptarse (`temperature`, `top_p`,
`seed`, penalizaciones, `user`, `top_k`, `metadata`) comparten una llamada y
solo se reintentan uno a uno si se rechaza. Un 4xx cuenta como límite del
modelo (no computa) en lugar de rechazo cuando la base de conocimiento lista el
parámetro en `unsupported_params`, cuando se envía un parámetro de muestreo a un
modelo de razonamiento o cuando una referencia con el mismo protocolo también
lo rechaza. Herramientas y modo JSON quedan en `capability`, `stop` en
`protocol`, el uso en streaming en `streaming`.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `protocol_request.param` (Parámetros de solicitud) | Aceptado, y su efecto es visible en la respuesta. | Correcto | 100 pts |
|  | Aceptado (su efecto no puede observarse en una sola respuesta). | Correcto | 100 pts |
|  | Aceptado, pero su efecto no aparece en la respuesta. | Advertencia · Baja | 50 pts |
|  | Rechazado con un 4xx (posiblemente un límite del propio modelo). | Advertencia · Baja | 40 pts |
|  | Rechazado con un 4xx, mientras que la referencia lo acepta. | Fallo · Media | 15 pts |
|  | Rechazado, pero el propio modelo no lo admite; no se cuenta. | Info | No computa |
|  | Error del servidor o sin respuesta; no se cuenta. | No concluyente · Baja | No computa |

### `determinism` — Determinismo y corrección de caché

**Cómo funciona.** Cuatro prompts creativos idénticos a `temperature=1.0` (sin
seed): un modelo real varía; una salida idéntica byte a byte en todas las
muestras apunta a una caché de respuestas que ignora el muestreo. El veredicto
se suprime para los modelos de razonamiento, que ignoran la temperatura de
forma legítima. Dos preguntas factuales idénticas a `temperature=0` son solo
informativas.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `determinism.temp1_variability` | Las muestras repetidas con temperature=1.0 fueron distintas, como en un muestreo real. | Correcto | 100 pts |
|  | Las muestras fueron idénticas, pero los modelos de razonamiento ignoran legítimamente temperature. | Info | 100 pts |
|  | Todas las muestras con temperature=1.0 fueron idénticas byte a byte, lo que sugiere respuestas en caché. | Advertencia · Media | 55 pts |
|  | No hubo una respuesta útil para evaluar. | No concluyente · Baja | No computa |
| `determinism.temp0_stability` | Respuestas idénticas con temperature=0 (esperado); solo informativo, no puntúa. | Info | No computa |
|  | Las respuestas difirieron con temperature=0; solo informativo, no puntúa. | Info | No computa |
|  | No hubo una respuesta útil para evaluar. | No concluyente · Baja | No computa |

**Advertencias.** Las pasarelas pueden añadir campos propios del proveedor;
solo se señalan campos obligatorios ausentes o inválidos. La traducción entre
los dialectos de Anthropic y OpenAI remodela legítimamente algunas
estructuras. Confirma un defecto sospechado repitiéndolo y, si es posible, en
modo comparación.

---

## `context_window` — Ventana de contexto

**Detecta.** `context.window-truncation` (un relay anuncia 128K/200K/1M pero
recorta el prompt en silencio) y `context.lost-in-middle-rag` (una capa barata
de RAG/resumen solo reenvía partes del prompt).

**Cómo funciona.** Recuperación de una aguja en un pajar a `temperature=0`: un
marcador único se inserta en un texto de relleno no repetitivo, y el modelo
debe devolverlo.

- **Ventana sondeada.** La sonda llega hasta `upper` = la ventana declarada,
  limitada por `--max-context-tokens` (200K por defecto). Cada veredicto se
  juzga frente a `upper`, nunca frente a la parte de una ventana declarada
  mayor que quede por encima del tope.
- **Los tamaños son tokens reales.** La estimación de tokens integrada en zing
  cuenta este relleno entre un 12 % (o200k) y un 15 % (cl100k) por debajo de
  los tokenizadores reales, así que cada prompt se construye a tamaño ÷ 1,2
  según la estimación (aguja y pregunta incluidas): un peldaño de tamaño N cabe
  en N tokens reales. Los tamaños de la evidencia (`size`, `effective_window`,
  `top_rung`) son esos presupuestos de tokens reales; las filas de la escalera
  incluyen además la estimación con que se construyó cada prompt
  (`heuristic_tokens`).

1. Una escalera de siete tamaños como mucho, que se divide a la mitad desde un
   **peldaño superior al 90 % de `upper`** (ningún peldaño alcanza la ventana
   completa, lo que deja sitio a la respuesta y a la plantilla de chat) hasta un
   mínimo de 1K (`context_probe_floor_tokens`); una ventana pequeña baja el
   mínimo a un cuarto del peldaño superior (una ventana de 2K sondea ~460, ~920
   y ~1,8K). Cada tamaño se sondea primero con la aguja en el **inicio**
   (profundidad 0,0): un truncado que conserva la pregunta al final del prompt
   solo puede descartar su inicio (un servidor local que recorta el prompt a su
   longitud de contexto conserva el final), así que un acierto ahí aprueba el
   tamaño con una sola llamada. Un fallo se comprueba en el final (profundidad
   0,95); si el final se recupera, el inicio se sondea una vez más con una aguja
   nueva, y un segundo fallo suspende el tamaño como **truncado por el inicio**
   (indicado en la evidencia del veredicto). Tres llamadas por tamaño como
   mucho; la escalera se detiene en el primer fallo confirmado.
2. Un paso de búsqueda binaria entre el último tamaño recuperado y el primero
   que falló.
3. Pérdida en el medio: con min(32K, ventana medida), la aguja se coloca en las
   profundidades 0,1, 0,5 y 0,9. Si se recuperan el principio y el final pero no
   el medio, el medio se sondea una vez más con una aguja nueva; solo un segundo
   fallo es un hallazgo.
4. Un 4xx cuyo mensaje menciona la longitud de contexto es un rechazo por
   tamaño; un rechazo de `max_tokens` (modelos de razonamiento) se reintenta con
   `max_completion_tokens` y nunca se lee como un techo.
5. Una sonda que agota el tiempo de espera o recibe un error (otro parámetro
   rechazado, un error HTTP, un 5xx, una respuesta vacía o malformada) termina
   la escalera sin contar como fallo: la ventana por encima del último tamaño
   recordado se informa como no verificada (no concluyente, sin puntuar), nunca
   como truncamiento ni `no_recall`. Solo una respuesta sin la aguja es un
   fallo.

La ventana medida (el mayor tamaño recordado) se compara con `upper`: recordar
en el peldaño superior es coherente (o, si la ventana declarada supera el tope,
**verificado hasta el tope**: la ventana por encima no se probó); por debajo,
el veredicto descuenta la parte del peldaño superior que no se recordó — una
advertencia desde la mitad de `upper`, un fallo por debajo. Sin ventana
declarada, la medida se informa pero no se puntúa.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `context_window.window` (Ventana de contexto efectiva) | El recuerdo se mantuvo en el peldaño superior (90 % de la ventana sondeada): sin deducción. | Correcto | Sin deducción |
|  | Recuerdo verificado hasta el tope de la sonda; la ventana declarada por encima no se probó. | Correcto | Sin deducción |
|  | El recuerdo se mantuvo hasta el 50-90 % de la ventana sondeada; descuenta la parte del peldaño superior que no se recordó. | Advertencia · Media | hasta −50 pts |
|  | El recuerdo falló por debajo de la mitad de la ventana sondeada; descuenta la parte del peldaño superior que no se recordó. | Fallo · Alta | hasta −100 pts |
|  | Ni siquiera el tamaño de sonda más pequeño recordó la aguja. | Fallo · Alta | −100 pts |
| `context_window.lost_in_middle` | Se recordaron el principio y el final, pero la parte central no, dos veces. | Advertencia · Media | −15 pts |
| `context_window.rejected_below_claim` | Un prompt muy por debajo de la ventana declarada fue rechazado por demasiado largo. | Fallo · Alta | Sin deducción |
| `context_window.measured` | No hay ventana declarada con la que comparar: solo se mide, no puntúa. | Info | Sin deducción |
| `context_window.no_ladder` | Ningún tamaño de sonda cabía entre el mínimo y el tope. | No concluyente · Baja | Sin deducción |
| `context_window.timed_out` | Una sonda agotó el tiempo de espera antes de alcanzar la ventana declarada: un endpoint lento, no una prueba de truncamiento. | No concluyente · Baja | Sin deducción |
| `context_window.probe_error` | Una sonda recibió un error (un parámetro rechazado, un error HTTP o del servidor) antes del peldaño superior: no es evidencia de truncamiento. | No concluyente · Baja | Sin deducción |

**Advertencias.** Los modelos reales de contexto largo también pierden agujas
en el medio; por eso solo un fallo en el **borde** se lee como recorte. La
recuperación cerca del techo es probabilística; vuelve a ejecutar antes de
concluir. La sonda está limitada por `--max-context-tokens`, así que una
ventana mayor no se ejercita por completo (súbelo para sondear más). El peldaño
superior está al 90 % de la ventana y el presupuesto de tokens es prudente, así
que el último ~10-15 % de una ventana nunca se sondea. Compara con una
referencia de confianza para separar el comportamiento del modelo del de una
capa intermedia.

---

## `model_identity` — Identidad del modelo

**Detecta.** `downgrade.silent-substitution` (un nombre premium sobre un backend
más barato o abierto), además de señales de `downgrade.reasoning-collapse`,
`downgrade.quantized-distilled` y `downgrade.partial-probabilistic-routing`
cuando cambian el comportamiento.

### `model_identity` — Identidad del modelo y huella de degradación

**Cómo funciona.** Tres señales independientes:

1. **Autoidentificación** a `temperature=0`, cotejada por palabras completas
   con las palabras clave de identidad del perfil (la marca auténtica) y con
   una lista de marcas rivales (`identity_forbidden` del perfil más una lista
   integrada). Una marca rival solo cuenta si falta la auténtica; «Soy Claude,
   no GPT» es un contraste benigno.
   La marca auténtica son las `identity_keywords` del perfil más sus propios
   nombres: la clave del proveedor, el nombre inicial del nombre visible del
   proveedor, la primera palabra del id y de la familia del modelo, y los demás
   nombres de ese fabricante en la lista integrada (`z.ai` también cubre
   `zhipu`). Por eso un modelo que nombra a su propio fabricante nunca es una
   marca rival, aunque `identity_keywords` esté vacío. Los nombres derivados
   nunca anulan `identity_forbidden`, las palabras genéricas («ai»,
   «platform», …) nunca cuentan, y la marca propia de una plataforma no cuenta
   para el modelo de otro fabricante que sirve.
2. **Huellas de comportamiento** de la base de conocimiento (fecha de corte del
   conocimiento, particularidades del tokenizer, formato, sondas ligadas a un
   idioma, …): hasta seis sondas de código puro, comprobadas con
   `expect_contains`, `expect_contains_any`, `expect_not_contains` o
   `expect_regex`; salida limitada a 512 tokens. Una sonda que
   necesita más salida (por ejemplo, una comprobación de la salida máxima) se
   omite, figura como Info y otra sonda ocupa su lugar. Una huella que se
   desvía resta
   su parte de peso sobre 100 puntos (25 como mucho); sola se queda en BAJA,
   dos o más añaden un hallazgo agregado MEDIO.
3. **Campo `model` devuelto** por una llamada simple: se toleran sufijos de
   snapshot y alias; se señala una palabra de gama inferior (`mini`, `flash`,
   `lite`, `8b`, …) o una familia distinta.

Sin perfil en la base de conocimiento, el detector es no concluyente.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `model_identity.self_id` | La autodescripción nombró la marca auténtica. | Correcto | Sin deducción |
|  | La autodescripción nombró una marca rival y no la auténtica. | Fallo · Alta | tope 20 |
|  | La autodescripción nombró la marca auténtica y una rival (normalmente una comparación inocua). | Advertencia · Baja | Sin deducción |
|  | La autodescripción no nombró ni la marca auténtica ni una rival. | Advertencia · Baja | Sin deducción |
|  | No hubo una respuesta útil para evaluar. | No concluyente | Sin deducción |
| `model_identity.fp` (Huellas de comportamiento) | La respuesta coincidió con el comportamiento nativo del modelo declarado. | Correcto | Sin deducción |
|  | La respuesta se desvió del comportamiento nativo: resta la parte de peso de la sonda sobre 100 puntos. | Advertencia · Baja | hasta −25 pts |
|  | La respuesta nombró una marca rival y no la auténtica: resta la parte de peso de la sonda. | Fallo · Alta | hasta −25 pts · tope 20 |
|  | No hubo una respuesta útil para evaluar. | No concluyente | Sin deducción |
|  | La sonda necesita más salida que el tope de identidad de 512 tokens; no se ejecuta. | Info | Sin deducción |
| `model_identity.fp_aggregate` | Dos o más huellas de comportamiento se desviaron. | Advertencia · Media | Sin deducción |
| `model_identity.model_field` | El campo model devuelto coincidió con el modelo solicitado. | Correcto | Sin deducción |
|  | El campo model devuelto nombra un modelo distinto o más pequeño. | Advertencia · Media | Sin deducción |
|  | La respuesta no tenía un campo model utilizable. | No concluyente | Sin deducción |

### `quality_judge` — Evaluación de calidad / degradación por un LLM juez

**Cómo funciona.** Solo con `--judge` (desde deep). Una breve serie de prompts
que distinguen gamas (razonamiento en varios pasos, una tarea de código
precisa, seguimiento de instrucciones con matices) va al objetivo y, en modo
comparación, a la referencia; un juez de confianza aparte solo ve las
respuestas y devuelve un veredicto con su confianza. Un veredicto del juez solo
es ALTO si una referencia corroboró la diferencia y el juez no indicó una
confianza baja o media.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `quality_judge.verdict` (Veredicto del juez LLM) | El juez encontró las respuestas coherentes con el modelo declarado. | Correcto | 95 pts |
|  | El juez encontró las respuestas distintas del modelo declarado (confianza baja/media). | Advertencia · Media | 50 pts |
|  | El juez está seguro de que las respuestas difieren del modelo declarado (sin referencia). | Advertencia · Media | 25 pts |
|  | El juez está seguro y una referencia de confianza corroboró la diferencia. | Fallo · Alta | 25 pts |
|  | El juez no dio confianza y una referencia de confianza corroboró la diferencia. | Fallo · Alta | 50 pts |
|  | El juez no pudo emitir un veredicto. | No concluyente · Baja | No computa |
|  | No hay respuestas del objetivo que juzgar. | No concluyente · Baja | No computa |

**Advertencias.** Las API oficiales actualizan sus snapshots en silencio; una
desviación puede ser deriva benigna — zing informa «divergente», nunca
«sustitución probada». Los modelos alucinan su propio nombre, así que la
autoidentificación sola nunca decide. Un relay podría memorizar una serie de
sondas fija. Un veredicto de confianza alta exige el modo comparación contra el
snapshot exacto declarado.

**No implementado.** La huella por distancia de embeddings (estilo LLMmap), las
pruebas estadísticas de dos muestras y el muestreo masivo contra el
enrutamiento probabilístico son líneas de investigación, no comprobaciones
actuales.

---

## `capability` — Capacidades declaradas

**Detecta.** `capability.json-tool-fakery`: llamadas a herramientas, modo JSON,
esquemas estrictos, longitud de salida o visión anunciados pero no cumplidos —
o *sobre*cumplidos, señal de un sustituto.

### `capability` — Verificación de capacidades declaradas

**Cómo funciona.** Cuatro sondas a `temperature=0`, cada una juzgada frente a
las capacidades del perfil:

- **Herramientas:** se ofrece una herramienta con `tool_choice: "auto"` y una
  petición explícita de usarla; debe volver una llamada a herramienta.
  Argumentos entregados como objeto en lugar de la cadena JSON que devuelve
  OpenAI se señalan como un motor que no es de OpenAI.
- **Modo JSON:** `response_format: json_object` debe devolver un objeto
  analizable con el valor pedido.
- **Esquema estricto:** un `json_schema` estricto; la conformidad se verifica si
  el modelo lo declara y solo se anota (informativo) si no. Se omite sin
  perfil.
- **Salida máxima:** una generación larga limitada a min(salida máxima
  declarada, 2048) tokens; llegar al límite o a una longitud plausible es
  correcto, detenerse por debajo de una cuarta parte se señala.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `capability.tools` | Volvió una llamada a herramienta ante una petición explícita de herramienta. | Correcto | 100 pts |
|  | Se declara la llamada a herramientas pero no volvió ninguna llamada. | Fallo · Media | 0 pts |
|  | No volvió ninguna llamada a herramienta, y no se declara esa capacidad. | Info | No computa |
|  | No hubo una respuesta útil para evaluar. | No concluyente · Baja | No computa |
| `capability.tools.encoding` | Los argumentos de la herramienta llegaron como objeto, no como la cadena JSON de OpenAI. | Advertencia · Baja | No computa |
| `capability.json_mode` | El modo JSON devolvió un objeto analizable con el valor pedido. | Correcto | 100 pts |
|  | Volvió un objeto JSON con un valor incorrecto; el modo JSON no se declara. | Info | 70 pts |
|  | No volvió ningún objeto JSON analizable; el modo JSON no se declara. | Advertencia | 50 pts |
|  | Se declara el modo JSON pero no volvió un objeto válido con el valor. | Fallo · Media | 0 pts |
|  | No hubo una respuesta útil para evaluar. | No concluyente · Baja | No computa |
| `capability.json_schema` | Se declara el esquema estricto y la respuesta lo cumplió. | Correcto | 100 pts |
|  | El esquema estricto no se aplicó, de acuerdo con lo declarado. | Info | 100 pts |
|  | La respuesta lo cumplió aunque el modelo declarado no tiene esquemas estrictos. | Info | 90 pts |
|  | Se declara el esquema estricto pero la respuesta no lo cumplió. | Advertencia · Baja | 40 pts |
|  | No hubo una respuesta útil para evaluar. | No concluyente · Baja | No computa |
| `capability.max_output` | La salida continuó hasta el tope de tokens solicitado. | Correcto | 100 pts |
|  | La salida terminó antes del tope con una longitud plausible. | Correcto | 90 pts |
|  | La salida terminó por debajo de un cuarto de la longitud pedida. | Advertencia · Baja | 70 pts |
|  | La salida terminó por debajo de un cuarto de lo pedido pese a un máximo declarado grande. | Advertencia · Baja | 60 pts |
|  | No hubo una respuesta útil para evaluar. | No concluyente · Baja | No computa |

### `vision` — Verificación de la capacidad multimodal (visión)

**Cómo funciona.** Desde deep y solo si el perfil declara visión: un pequeño
PNG naranja liso, generado en tiempo de ejecución, se envía en línea con una
pregunta de una palabra sobre su color. Un sustituto solo de texto no puede
nombrar el color de forma fiable.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `vision.color` | El modelo nombró el color de la imagen de prueba. | Correcto | 100 pts |
|  | Se declara visión pero el modelo no nombró el color de la imagen. | Advertencia · Media | 0 pts |
|  | No hubo una respuesta útil para evaluar. | No concluyente | No computa |
| `vision.not_claimed` | No se declara visión, así que no se envió ninguna imagen. | Info | No computa |

**Advertencias.** Los modelos reales a veces omiten una herramienta o emiten
JSON inválido; una sonda por capacidad es una señal, no una tasa. La
traducción entre dialectos remodela legítimamente el JSON de las llamadas a
herramientas. La sonda de salida máxima no ejercita todo el techo declarado.
Una sola imagen es un indicio, no una prueba.

---

## `streaming` — Autenticidad del streaming

**Detecta.** `stream.fake-streaming`: el relay almacena en búfer toda la
respuesta del upstream y la reproduce en uno o pocos fragmentos, perdiendo la
ventaja de latencia.

**Cómo funciona.** Una solicitud en streaming (`max_tokens` 256,
`stream_options.include_usage`) de la que se registra la hora de llegada de cada
fragmento. Tres señales de búfer: **pocos fragmentos** (dos o menos) y **primer
token tardío** (TTFT por encima del 90 % de la duración total), evaluadas solo
cuando llegaron al menos 220 caracteres, e **intervalos uniformes** (cuatro o
más fragmentos con intervalos casi iguales, CV < 0,1, y por debajo de 2 ms:
volcados de golpe). Un flujo sin fragmento de uso se señala aparte.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `streaming.healthy` | Muchos fragmentos, un primer token temprano y huecos repartidos: streaming real. | Correcto | Sin deducción |
| `streaming.few_chunks` | Señal de búfer: la primera resta 40 puntos, una segunda 20, las siguientes nada. | Advertencia · Media | hasta −40 pts |
| `streaming.late_ttft` | Señal de búfer: la primera resta 40 puntos, una segunda 20, las siguientes nada. | Advertencia · Media | hasta −40 pts |
| `streaming.uniform_gaps` | Señal de búfer: la primera resta 40 puntos, una segunda 20, las siguientes nada. | Advertencia · Media | hasta −40 pts |
| `streaming.no_usage` | No hay fragmento de uso en el stream: resta 15 puntos si nada está en búfer. | Advertencia · Baja | hasta −15 pts |
| `streaming.failed` | La solicitud en streaming falló. | Fallo · Alta | tope 0 |

Es decir: auténtico 100 · falta el uso 85 · una señal de búfer 60 · dos o más
40 · fallo 0.

**Advertencias.** Salidas cortas, un modelo pequeño y rápido o la fluctuación de
la red pueden parecer una ráfaga. Un upstream que no sabe hacer streaming
obliga al relay a usar un búfer de forma legítima; léelo como «el relay no hace
streaming», no como mala fe. Vuelve a ejecutar y compara con una referencia que
sí haga streaming.

---

## `billing` — Facturación y uso

**Detecta.** `billing.usage-inflation` (tokens de prompt o de completion
inflados), `billing.missing-usage` (`usage` ausente, parcial o incoherente) y,
como señal de corroboración, `prompt.injected-system-prompt`.

**Cómo funciona.** Una llamada determinista (un párrafo conocido que resumir,
`temperature=0`). El prompt y la respuesta visible se cuentan de forma
independiente con una heurística sensible al idioma (aprox. ±25 %), para todas
las familias de modelos: zing no usa ninguna biblioteca de tokenizer ni descarga
ninguna. Tokens de prompt informados por encima de 2,5× la estimación y más de
50 tokens por encima cuentan como inflado. Los tokens de completion de un modelo
de razonamiento incluyen legítimamente tokens de razonamiento ocultos y no se
señalan; si no, tokens de completion por encima de 3× la estimación y más de 80
tokens por encima son una advertencia suave, nunca un fallo, porque la
estimación de una respuesta corta es ruidosa. `total` debe ser
`prompt + completion` (±2), y un total sin desglose se señala. Un recuento por
debajo (menos de la mitad de la estimación) es informativo (no perjudica al
comprador).

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `billing.request-failed` | No hubo una respuesta útil para evaluar. | No concluyente · Baja | Sin deducción |
| `billing.missing-usage` | La respuesta no incluía ningún uso de tokens. | Advertencia · Media | tope 75 |
| `billing.usage-inflation` | Los tokens de prompt declarados superan con creces la estimación independiente. | Fallo · Alta | tope 55 |
| `billing.usage-inflation-completion` | Los tokens de completion declarados están muy por encima de una estimación heurística. | Advertencia · Media | tope 70 |
| `billing.reasoning-tokens` | Los tokens de completion superan el texto visible, como es de esperar en un modelo de razonamiento. | Info | Sin deducción |
| `billing.usage-undercount-prompt` | Los tokens de prompt declarados están muy por debajo de la estimación (no perjudica al comprador). | Info | Sin deducción |
| `billing.usage-undercount-completion` | Los tokens de completion declarados están muy por debajo de la estimación (no perjudica al comprador). | Info | Sin deducción |
| `billing.total-mismatch` | El total declarado no es igual a los tokens de prompt + completion. | Advertencia · Baja | tope 90 |
| `billing.partial-usage` | El uso indica un total sin el desglose prompt/completion. | Advertencia · Media | tope 80 |
| `billing.usage-consistent` | El uso declarado está dentro de la tolerancia de la estimación independiente. | Correcto | Sin deducción |

Una solicitud de sonda fallida deja el detector sin puntuación.

**Advertencias.** Las plantillas de chat y los tokens especiales añaden un
pequeño desfase fijo; no se espera una coincidencia exacta. Si el modelo servido
difiere del declarado, el tokenizer «correcto» es desconocido. Los tokens de
razonamiento ocultos no pueden contarse desde fuera. Una sonda mide un tamaño;
un multiplicador que crece con el tamaño requiere ejecuciones repetidas o el
modo comparación.

---

## `reliability` — Fiabilidad en concurrencia

**Detecta.** Parte de `throttle.rate-limit-quality`: un relay que falla o se
arrastra con un paralelismo moderado.

**Cómo funciona.** Una ráfaga de pequeñas solicitudes idénticas
(`--reliability-requests`, 8 por defecto) con concurrencia limitada
(`--concurrency`, 3 por defecto). La tasa de éxito se calcula sobre las
solicitudes realmente intentadas: un HTTP 429 es una limitación honesta y se
contabiliza aparte. La puntuación resta la parte fallida; una latencia p95 por
encima de 30 s conserva el 85 % del resto.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `reliability.success_rate` | Todas las solicitudes intentadas de la ráfaga tuvieron éxito. | Correcto | Sin deducción |
|  | Falló hasta el 10 % de las solicitudes intentadas; resta la parte fallida. | Advertencia · Baja | hasta −10 pts |
|  | Falló más del 10 % de las solicitudes intentadas; resta la parte fallida. | Fallo · Media | hasta −100 pts |
|  | Todas las solicitudes fueron limitadas (HTTP 429): no puntúa. | No concluyente · Baja | Sin deducción |
| `reliability.latency` | Latencia p95 por encima de 30 s bajo carga; resta el 15 % de la puntuación restante. | Advertencia · Baja | hasta −15 pts |
| `reliability.rate_limited` | Parte de la ráfaga fue limitada: limitación legítima, no computa. | Info | Sin deducción |
| `reliability.skipped` | La sonda de fiabilidad estaba desactivada. | Info | Sin deducción |

Las mediciones de velocidad dedicadas pertenecen a la dimensión `performance`.

**Advertencias.** Los proveedores reales también se ralentizan y devuelven 429
bajo carga real. Una instantánea no capta el comportamiento según la hora;
`zing watch` vuelve a auditar según un calendario.

**No implementado.** La medición de calidad a lo largo del tiempo y con carga
variable, y las señales de clave upstream compartida
(`infra.shared-upstream-key`: cuota que baja en reposo, identificadores de
solicitud upstream filtrados) están en la hoja de ruta.

---

## `security` — Seguridad del transporte

**Detecta.** `prompt.injected-system-prompt`, `integrity.response-tampering`,
indicios de `privacy.prompt-logging-leakage` (caché por prefijo) y la higiene
básica de transporte y secretos.

### `security` — Señales de transporte y manejo de secretos

**Cómo funciona.** Comprueba que el endpoint use HTTPS, que la clave de API
nunca aparezca literalmente en una respuesta y qué cabeceras de respuesta
delatan un upstream o proxy (`server`, `via`, `x-powered-by`, `x-upstream-*`,
`x-litellm-*`, …; informativo). También recuerda el límite: el registro de
prompts y las claves upstream compartidas no pueden probarse desde fuera.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `security.tls` | El endpoint usa HTTPS. | Correcto | Sin deducción |
|  | El endpoint no usa HTTPS; la clave API viaja en texto plano. | Fallo · Alta | tope 40 |
| `security.key_echo` | La clave API no aparece en la respuesta. | Correcto | Sin deducción |
|  | La clave API aparece literalmente en la respuesta. | Fallo · Alta | tope 30 |
| `security.headers` | Ninguna cabecera de respuesta revela el upstream (solo informativo). | Correcto | Sin deducción |
|  | Las cabeceras de respuesta revelan el upstream o el proxy (solo informativo). | Info · Baja | Sin deducción |
|  | No hay cabeceras de respuesta que inspeccionar. | No concluyente | Sin deducción |
| `security.note` | El registro de prompts y las claves upstream compartidas no se pueden demostrar desde fuera. | Info | Sin deducción |

### `injected_prompt` — Detección de prompt de sistema inyectado

**Cómo funciona.** Dos indicios independientes. (1) Un **sobrecoste fijo de
tokens de entrada**: dos mensajes de usuario de distinto tamaño sin mensaje de
sistema; los `prompt_tokens` informados menos la estimación independiente
deben seguir siendo pequeños. Un sobrecoste de al menos 30 tokens que se
mantiene constante (con 16 de margen) en ambos tamaños indica un prompt oculto
antepuesto y no un inflado proporcional. (2) Una **sonda de filtración** que
pide al modelo repetir cualquier instrucción anterior. Solo ambos juntos
alcanzan MEDIA.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `injected_prompt.verdict` (Prompt de sistema inyectado) | La sobrecarga de tokens de entrada es pequeña y no se filtraron instrucciones ocultas. | Correcto | 100 pts |
|  | Se filtró texto con aspecto de instrucciones al pedirlo (débil por sí solo). | Info · Baja | 85 pts |
|  | Una gran sobrecarga fija de tokens de entrada, constante con el tamaño del mensaje. | Advertencia · Baja | 75 pts |
|  | Una sobrecarga fija de tokens de entrada y un preámbulo filtrado a la vez. | Advertencia · Media | 55 pts |
|  | No hay recuentos de tokens de prompt utilizables para medir la sobrecarga. | No concluyente | No computa |

### `integrity` — Integridad de respuestas / manipulación

**Cómo funciona.** Canarios de respuesta conocida con valores sensibles — una
URL de instalación y un paquete `pip install` fijado — deben volver
literalmente. Un eco exacto es correcto, la falta de eco (paráfrasis, negativa)
es no concluyente, y solo una **sustitución del valor** que conserva la
estructura cuenta como manipulación. En modo comparación, una sustitución que la
referencia de confianza no hace es CRÍTICA.
Una respuesta cortada en el límite de salida es no concluyente, no una sustitución.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `integrity.verdict` (Integridad de las respuestas) | Los canarios de respuesta conocida volvieron intactos. | Correcto | 100 pts |
|  | Se sustituyó un valor canario (aún sin confirmar con una referencia). | Fallo · Media | 45 pts |
|  | Se sustituyó un valor canario mientras la referencia de confianza lo mantuvo intacto. | Fallo · Crítica | 10 pts |
|  | Ningún canario se repitió literalmente, así que no se pudo evaluar la manipulación. | No concluyente | No computa |

### `prompt_cache` — Caché de prefijo de prompt (tiempos)

**Cómo funciona.** Un prefijo único de unos 1.200 tokens se envía dos veces en
streaming (en frío y luego en caliente) y un prefijo de control distinto una
vez. Si el TTFT en caliente es menos de la mitad del TTFT en frío y del de
control, y al menos 150 ms más rápido que en frío, la caché por prefijo está
activa. Siempre informativo: la caché por prefijo es una optimización legítima.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `prompt_cache.verdict` (Caché por prefijo de prompt) | Un prefijo de prompt repetido volvió mucho más rápido: la caché por prefijo está activa. | Info | No computa |
|  | Un prefijo de prompt repetido no fue claramente más rápido. | Info | No computa |
|  | Una o más sondas de tiempo no devolvieron un tiempo utilizable. | No concluyente | No computa |

**Advertencias.** Los modelos inventan «prompts de sistema» falsos cuando se les
pide filtrarlos; una filtración sola se queda en BAJA. La traducción entre
dialectos remodela el JSON de las llamadas a herramientas; solo cuenta una
sustitución del *valor*. Una manipulación condicional (solo para ciertas
palabras clave, clientes o tras un calentamiento) puede escapar a un número
finito de sondas. El registro en caja negra es **imposible de probar** desde el
cliente, y zing no puede mostrar una caché compartida *entre usuarios* con una
sola clave: la ausencia de una señal temporal no prueba que los prompts no se
registren.

---

## `performance` — Rendimiento

**Qué mide.** Cuán **constante** es el endpoint, no cuán rápido. Un modelo local
o autoalojado lento pero constante puntúa bien; la velocidad bruta solo cuenta
frente a una referencia.

**Cómo funciona.** La sonda dedicada se ejecuta en deep, full y custom, y en
standard solo en modo comparación (5 solicitudes por lado, demasiado pocas para
las comprobaciones de constancia). Por endpoint: tres pings `GET /models`, una
solicitud de calentamiento (informada como arranque en frío),
`--performance-requests` solicitudes uniformes (100 por defecto) de
`--performance-max-tokens` tokens de salida (128 por defecto) y, en deep/full,
una ráfaga a `--concurrency`. Cada solicitud es no cacheable: un identificador
de solicitud aleatorio abre el prompt, los temas rotan y no se envían parámetros
de caché ni de razonamiento; una respuesta que aun así viene de una caché se
señala y se excluye de las estadísticas. La sonda usa streaming por defecto
(`--performance-non-streaming` para relays que no saben hacer streaming); full
mide ambos modos, intercalados. En modo comparación, objetivo y referencia se
alternan para que la deriva de la red afecte a ambos por igual.
Los tokens de entrada en caché solo cuentan cuando cubren al menos la mitad del
prompt: los servidores locales (Ollama, llama.cpp, LM Studio) reutilizan la
plantilla de chat en caché de cada prompt, lo que no es una respuesta guardada.
Cada llamada de la auditoría se guarda como registro de petición
(`performance.requests`, solo números, nunca texto del prompt ni de la
respuesta); su `start_ms` cuenta desde el `started_at` del informe (UTC), así
que la hora de cada llamada se puede reconstruir.

La constancia usa ratios de cola (p90 ÷ p50 para latencia y TTFT, p50 ÷ p10 para
el rendimiento), que una solicitud atípica no mueve como mueve una desviación
típica; necesitan al menos 10 muestras limpias. La referencia es la referencia
de confianza o, si no hay, el rango `performance.decode_tps` del perfil en la
base de conocimiento.

| Comprobación | Resultado | Estado | Efecto |
|---|---|---|---|
| `performance.summary` | Se midieron la latencia, el TTFT y el rendimiento. | Info | No computa |
|  | Ninguna de las solicitudes de sondeo tuvo éxito. | No concluyente | No computa |
| `performance.latency_consistency` | La latencia es constante (ratio de cola como máximo 1,3). | Correcto | 100 pts |
|  | La latencia es estable (ratio de cola como máximo 1,75). | Correcto | 85 pts |
|  | La latencia varía notablemente (ratio de cola como máximo 2,5). | Advertencia · Baja | 65 pts |
|  | La latencia es errática (ratio de cola superior a 2,5). | Fallo · Baja | 40 pts |
|  | Muy pocas muestras para juzgar la constancia de la latencia. | Info | No computa |
| `performance.ttft_consistency` | El tiempo hasta el primer token es constante (ratio de cola como máximo 1,3). | Correcto | 100 pts |
|  | El tiempo hasta el primer token es estable (ratio de cola como máximo 1,75). | Correcto | 85 pts |
|  | El tiempo hasta el primer token varía notablemente (ratio de cola como máximo 2,5). | Advertencia · Baja | 65 pts |
|  | El tiempo hasta el primer token es errático (ratio de cola superior a 2,5). | Fallo · Baja | 40 pts |
|  | Muy pocas muestras para juzgar la constancia del tiempo hasta el primer token. | Info | No computa |
| `performance.throughput_consistency` | El rendimiento es constante (ratio de cola como máximo 1,3). | Correcto | 100 pts |
|  | El rendimiento es estable (ratio de cola como máximo 1,75). | Correcto | 85 pts |
|  | El rendimiento varía notablemente (ratio de cola como máximo 2,5). | Advertencia · Baja | 65 pts |
|  | El rendimiento es errático (ratio de cola superior a 2,5). | Fallo · Baja | 40 pts |
|  | Muy pocas muestras para juzgar la constancia del rendimiento. | Info | No computa |
| `performance.errors` | Falló como máximo el 2 % de las peticiones de la sonda. | Correcto | 100 pts |
|  | Hasta el 10 % de las peticiones de la sonda fallaron o agotaron el tiempo. | Advertencia · Baja | 80 pts |
|  | Muchas peticiones de la sonda fallaron o agotaron el tiempo. | Fallo · Baja | 50 pts |
| `performance.load_stability` | La latencia se mantiene bajo carga concurrente (como máximo 1,5x). | Correcto | 100 pts |
|  | La latencia aumenta bajo carga concurrente (hasta 3x). | Advertencia · Baja | 80 pts |
|  | La latencia se degrada mucho bajo carga concurrente (más de 3x). | Fallo · Baja | 55 pts |
| `performance.cache_hit` | Prompts de sondeo únicos volvieron de una caché (excluidos de las estadísticas). | Advertencia · Baja | 60 pts |
|  | La referencia sirvió prompts únicos desde una caché (no puntúa). | Info | No computa |
| `performance.reference` | El rendimiento concuerda con la referencia de este modelo. | Correcto | 100 pts |
|  | Más lento que la referencia (p. ej. local o hardware más pequeño); no es un fallo. | Info | 80 pts |
|  | Mucho más rápido que la referencia (compatible con un modelo más pequeño). | Advertencia · Baja | 60 pts |
| `performance.reasoning` | El modelo gasta tokens de razonamiento ocultos; el TTFT incluye el razonamiento. | Info | No computa |
| `performance.relay_overhead` | Latencia comparada con la referencia de confianza (solo informativo). | Info | No computa |
| `performance.skipped` | La sonda de rendimiento estaba desactivada. | Info | No computa |

**Advertencias.** La latencia depende del camino de red y de la carga del
proveedor en ese momento; repite un mal resultado de constancia en otro
momento. Los rangos de la base de conocimiento son medianas deliberadamente
amplias de las API nativas, y un objetivo más lento nunca es un fallo. Todos
los hallazgos son como mucho de gravedad BAJA: esta dimensión mueve la
puntuación, nunca el veredicto de riesgo.

---

## Correspondencia truco → detector

Los 16 trucos de relay de la investigación se reparten así en zing.

| # | Truco (id) | Gravedad | Detector(es) | Cobertura actual |
|---|---|---|---|---|
| 1 | `downgrade.silent-substitution` | critical | `model_identity`, `quality_judge` | autoidentificación, huellas, campo `model`; juez; modo comparación |
| 2 | `downgrade.reasoning-collapse` | critical | `model_identity`, `quality_judge` | solo huellas y juez; aún sin escalera de dificultad propia |
| 3 | `downgrade.quantized-distilled` | high | `quality_judge`, `model_identity` | juez con referencia; aún sin prueba de distribución |
| 4 | `downgrade.partial-probabilistic-routing` | high | `model_identity` | solo si las solicitudes muestreadas dan con el sustituto; el muestreo masivo está en la hoja de ruta |
| 5 | `context.window-truncation` | high | `context_window` | escalera con aguja en el borde + búsqueda binaria; medida vs declarada |
| 6 | `context.lost-in-middle-rag` | high | `context_window` | profundidades 0,1/0,5/0,9 con un tamaño medio |
| 7 | `stream.fake-streaming` | medium | `streaming` | número de fragmentos, momento del primer token, uniformidad de intervalos |
| 8 | `billing.usage-inflation` | high | `billing` | estimación heurística independiente de tokens de una sonda conocida |
| 9 | `billing.missing-usage` | medium | `billing`, `protocol_response`, `streaming` | presencia, desglose y aritmética del uso; fragmento de uso del flujo |
| 10 | `privacy.prompt-logging-leakage` | high | `prompt_cache` | caché por prefijo mediante TTFT (informativo); compartir entre usuarios y el registro siguen sin poder probarse con una clave |
| 11 | `infra.shared-upstream-key` | high | — | hoja de ruta (cuota que baja en reposo, identificadores de solicitud upstream filtrados) |
| 12 | `cache.ignore-temperature` | medium | `determinism` | salida idéntica byte a byte a temperatura 1,0; suprimido para modelos de razonamiento |
| 13 | `prompt.injected-system-prompt` | medium | `injected_prompt`, `billing` | sobrecoste fijo de tokens de entrada (dos tamaños) + sonda de filtración |
| 14 | `throttle.rate-limit-quality` | medium | `reliability`, `performance` | tasa de éxito (429 aparte), latencia de cola, estabilidad bajo carga; la medición a lo largo del tiempo está en la hoja de ruta |
| 15 | `capability.json-tool-fakery` | medium | `capability`, `protocol_request` | herramientas, modo JSON, esquema estricto, parámetros; una sonda cada uno, no tasas |
| 16 | `integrity.response-tampering` | critical | `integrity` | canarios de URL/paquete de respuesta conocida; CRÍTICA cuando una referencia lo corrobora |

---

## Límites y uso responsable

**zing informa de desviaciones y riesgos, no de pruebas de fraude.** El
veredicto usa un lenguaje prudente (clean / low / medium / high /
inconclusive), deja no concluyentes los resultados ambiguos y solo sube a
«alto» con evidencia sólida de gravedad alta.

**Lo que una auditoría de caja negra no puede demostrar:**

- **Registro de prompts o retención de datos.** Una señal temporal prueba una
  caché; su ausencia no prueba que los prompts no se registren.
- **Integridad de las respuestas** sin respuestas firmadas por el proveedor:
  una manipulación condicional puede escapar a un número finito de sondas.
- **Claves compartidas o robadas:** como mucho, un *riesgo* de pool compartido.
- **Deriva benigna o sustitución:** las API oficiales actualizan sus snapshots
  en silencio.
- **Enrutamiento constante:** un relay puede enrutar de forma probabilística, y
  una auditoría solo ve las solicitudes que envió.

**Método.** Los hallazgos que dependen de una comparación exacta usan
`temperature=0` y prompts acotados. Cada hallazgo lleva su evidencia (entradas,
valores observados, recuentos, tiempos) y cada informe registra el perfil, los
idiomas de los prompts y la configuración con que se ejecutó, para que un
resultado pueda verificarse de forma independiente. Un relay puede detectar las
pruebas: vuelve a ejecutar en otros momentos y prefiere el modo comparación
contra una referencia de confianza del **snapshot exacto declarado** — es la
forma más sólida de separar el comportamiento del modelo del del relay, y la
única de alcanzar una confianza alta.

**Divulgación responsable.** **No acuses públicamente a un proveedor**
basándote en un informe de zing. Antes de actuar: vuelve a ejecutar con más
muestras y en otros momentos, confirma con el modo comparación y descarta
explicaciones de deriva, red y carga. Si persiste una duda seria, plantéasela
primero en privado al proveedor, como preguntas sobre el comportamiento
observado y no como acusaciones.
