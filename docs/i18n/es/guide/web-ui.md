# Interfaz web (`ekte serve`)

> [🇬🇧 English](../../../guide/web-ui.md) · [🇨🇳 中文](../../zh-CN/guide/web-ui.md) · [🇫🇷 Français](../../fr/guide/web-ui.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/web-ui.md) · [🇮🇹 Italiano](../../it/guide/web-ui.md) · [🇩🇪 Deutsch](../../de/guide/web-ui.md) · [🇳🇴 Norsk](../../nb/guide/web-ui.md)

¿Prefieres hacer clic? Una interfaz web local envuelve el mismo motor — sin
línea de comandos.

```bash
pip install 'ekte[web]'     # o: uv tool install 'ekte[web]'
ekte serve                        # abre http://localhost:8000
```

El formulario te guía por la configuración:

1. Elige el **Relay / proveedor**: un proveedor de la base de conocimiento o un
   relay que guardaste. Se rellena su URL base (las demás URL conocidas del
   proveedor se ofrecen como sugerencias). Para cualquier otro relay elige
   **Otro (introducir la URL)** e introduce la **URL del intermediario**.
2. Añade la **Clave de API** si el relay la necesita.
3. ekte lista por sí mismo los modelos del relay (al elegir un relay y cada vez
   que cambian la URL o la clave; **Actualizar modelos** vuelve a preguntar).
   Elige el **Modelo solicitado**. Un relay sin lista de modelos pasa a escribir
   el id (**Introducir a mano**).
4. Opcionalmente, elige el **Modelo declarado** entre los modelos de la base de
   conocimiento: el modelo que el relay dice servir. Si el modelo solicitado está
   en la base de conocimiento, aparece preseleccionado; cámbialo solo si el
   relay vende el modelo con otro nombre. De él se deriva el perfil de
   proveedor con el que ekte audita.

Un relay que aún no está en la lista se puede conservar con **Guardar en la
base** con el nombre que le des; la próxima vez estará a una selección. La
referencia de confianza (**Comparar con una referencia de confianza**) y las
auditorías de embeddings y rerank se configuran igual.

Después, **Iniciar auditoría** y
sigue las comprobaciones **en vivo**: cada comprobación muestra su puntuación y
cuánto tardó, y una comprobación con hallazgos se despliega para mostrar la
evidencia. El resultado es un informe de veredicto que puedes compartir: nota,
**Comprobaciones por dimensión** con sus escalas de puntuación, hallazgos en
lenguaje claro, la sección de rendimiento y un **Registro de ejecución** de cada
detector.

Todo se ejecuta en tu máquina: una clave escrita en el navegador solo llega a tu
servidor ekte local y al relay que auditas, nunca a terceros. Consulta
[Privacidad y datos locales](privacy.md#privacidad-y-datos-locales).

## Páginas

La interfaz web se sirve en la raíz de la dirección que abre `ekte serve`, con la página de auditoría en `/`. Las direcciones anteriores redirigen a la página correspondiente hasta 1.0.0 (consulta [Direcciones de la interfaz web](../../../reference/stability.md#surface-web-addresses)).

| Página | Dirección | Para qué sirve |
|---|---|---|
| **Auditoría** | `/` | Auditar un relay (opcionalmente frente a una referencia) y leer el informe; las auditorías de embeddings y rerank también empiezan aquí, con el selector de tipo de endpoint |
| **Monitores** | `/watches` | Reauditorías programadas con alertas por webhook |
| **Historial** | `/history` | Cada auditoría ejecutada en esta máquina, agrupada por relay + modelo declarado, con tendencias |
| **Analítica** | `/analytics` | Relays y modelos comparados en el tiempo: indicadores, gráficos con tablas de datos, clasificaciones |
| **Conocimiento** | `/kb` | La base de conocimiento en tres pestañas — modelos, proveedores, relays: explorar, activar/desactivar, añadir lo tuyo |
| **Accesibilidad** | `/accessibility` | El informe de conformidad y la declaración de accesibilidad (el icono junto al selector de idioma); aún sin revisión manual por una persona (limitación conocida) |

Además, en las páginas: filtros y tendencias configurables (puntuación, nota,
latencia p50, tokens/s) en el **Historial**; **Programar como monitor** y **Repetir auditoría** en cada
ejecución del Historial; **Descargar informe** en todos los formatos; y un selector
de tema (Automático / Claro / Oscuro). Cada página
salvo Accesibilidad tiene un aviso justo bajo su introducción, coloreado según
su importancia (información, éxito, advertencia, crítico): p. ej. la última
auditoría terminada en **Auditoría**, la clave maestra en **Monitores**, las
ejecuciones aún en proceso en **Historial** y **Analítica**, las entradas
omitidas en **Conocimiento**.

**Auditorías en segundo plano.** Una auditoría iniciada en la
página **Auditoría** sigue en marcha cuando cambias de página o cierras la
pestaña; **Continuar en segundo plano** la envía allí a propósito. El
**Historial** muestra cada auditoría en cola y en marcha (y cada monitor en
ejecución) con su progreso; **Ver en directo** vuelve a abrir la vista en vivo,
que se pone al día con todo lo ocurrido. Las auditorías del mismo relay se
ejecutan una tras otra, para no distorsionar sus resultados de latencia o
fiabilidad (todas las direcciones loopback cuentan como un solo host, así que
los modelos servidos desde tu propia máquina también esperan); las de relays
distintos se ejecutan en paralelo, como máximo cuatro a la vez
(`EKTE_MAX_PARALLEL_AUDITS`). Los monitores esperan a su relay del mismo modo.

**Analítica.** `/analytics` convierte el historial local
en comparaciones: indicadores del periodo elegido (ejecuciones, puntuación
mediana, proporción de riesgo alto, tasa de éxito, TTFT, velocidad de salida,
ratios de facturación) con el cambio frente al periodo anterior de igual
duración; un gráfico de cualquier métrica por relay, modelo o relay × modelo,
por hora, día o semana (línea mediana con la banda p25–p75, hasta cuatro
series, cada gráfico también como tabla de datos); y una clasificación de los
relays de un modelo o de los modelos de un relay. Los relays se agrupan por su
entrada de la base de conocimiento (relays guardados y proveedores), así que
renombrar un relay reagrupa su historial. Los intervalos con menos de 3
ejecuciones se dibujan atenuados: una sola auditoría puede ser un valor
atípico; un monitor da mediciones regulares. Las ejecuciones antiguas muestran
lo que midieron: la página indica en cuántas ejecuciones se basa un valor. Por
defecto compara una suite y un modo de sondeo (los más frecuentes), para no
mezclar ejecuciones distintas; filtros y vista se guardan en la URL, así que
una vista se puede marcar o compartir. Nada sale del equipo.

Otros paneles responden preguntas más concretas: **horas punta** (un mapa de
calor día de la semana × hora del TTFT, la latencia y la velocidad de decodificación (mediana y colas p95 /
p5), la variación entre tokens, los tiempos de red y del relay o la tasa de éxito o de
error en tu zona horaria: ¿un relay se vuelve más lento o falla más en las horas
de más carga? Por día de la semana o, con 90 días de ejecuciones, en un ciclo
de 4 semanas y, con 180 días, por semana del mes), **errores y fiabilidad** (llamadas fallidas por causa: límite
de peticiones (HTTP 429), errores del servidor (5xx), tiempos agotados, errores
de red; a lo largo del tiempo y por relay o modelo, a partir de los registros
de peticiones guardados, indicando cuántas auditorías los tienen),
**integridad del modelo** (resultados de las comprobaciones de identidad,
ventana de contexto y capacidades por relay × modelo, la proporción de
auditorías cuyo modelo devuelto difiere y la proporción medida de la ventana
de contexto declarada), **facturación y tokens** (ratios de facturación a lo
largo del tiempo frente a la línea del 100 %: por encima, el relay informa más
tokens de los que contó ekte; además de las proporciones de tokens de
razonamiento y de entrada en caché) y **sobrecarga del relay** (el tiempo de
procesamiento que informa el relay junto al tiempo de ida y vuelta de red).

**Pestañas y enlaces para compartir (Analítica).** Los paneles están en cinco
pestañas — **Resumen** (indicadores, clasificación), **Tendencias**
(comparación en el tiempo, horas punta), **Fiabilidad** (errores, sobrecarga
del relay), **Integridad del modelo** y **Facturación** — bajo la cabecera de
la página y un panel de filtros común; solo se carga la pestaña que está
viendo. La URL guarda la pestaña, los filtros y cada opción de los gráficos
(`#tab=reliability&range=30&relay=…&eb=dow_hour`), y **Copiar el enlace a esta
vista** la copia (o la muestra en un campo para copiarla si el navegador no lo
permite): el enlace abre exactamente esa vista. El panel de filtros es el mismo
en **Historial**, **Monitores** y **Analítica**: cerrado, indica cuántos filtros están activos
y los nombra en una línea (p. ej. «Últimos 30 días · standard · Streaming ·
Example Relay»), así una vista compartida dice lo que muestra.

## Idiomas

Un menú de idioma en la cabecera de cada página cambia la interfaz entre
**🇬🇧 inglés** (por defecto), **🇨🇳 chino** (la interfaz original),
**🇫🇷 francés**, **🇪🇸 español**, **🇵🇹 portugués**, **🇮🇹 italiano**,
**🇩🇪 alemán** y **🇳🇴 noruego** (bokmål); la elección se recuerda por navegador.

Los informes descargados desde la interfaz (**Descargar informe**: JSON,
Markdown, HTML o PDF) siguen el idioma elegido: las claves JSON, los valores
enumerados (`risk_level`, `status`, `severity`, …), los ids y la evidencia quedan
exactamente como en el informe de la CLI (el JSON sigue siendo un informe de ekte
válido), mientras que los valores legibles (titular y resumen del veredicto,
títulos y resúmenes de los hallazgos, recomendaciones, nombres de detectores,
notas) se traducen, y el nombre del archivo lleva el idioma
(`ekte-report.es.json`, `ekte-report.es.pdf`). Los encabezados de sección de los
archivos Markdown/HTML/PDF están en inglés. Los informes de la CLI con
`--format json|md|html|pdf` siguen en inglés.

**Los prompts enviados al endpoint auditado no siguen el idioma de la
interfaz.** Todo texto que ekte envía a una API de LLM está en inglés, para que el
mismo relay reciba el mismo veredicto sea quien sea quien lea el informe (las
comprobaciones de respuestas y las estimaciones de tokens están calibradas con
esos textos exactos). Las únicas excepciones son las huellas de la base de
conocimiento cuyo idioma *es* la medida — por ejemplo, las sondas de fluidez en
chino, de tokenizer y de autoidentificación de los modelos chinos. Cada informe
registra los idiomas de sonda realmente usados (`prompt_languages`, p. ej.
`["en", "zh"]`).
Cada informe también registra cómo se habló con el endpoint: el protocolo
(`target.api`: `openai`, `anthropic` o `responses`), si `--api auto` lo detectó
(`target.api_auto`) y el modo de petición de la sonda de rendimiento
(`stream_mode`: `stream`, `non_stream` o `both` para la suite completa). La página
de historial de la interfaz web puede filtrar por los tres.
`started_at` registra cuándo empezó la auditoría (UTC); el `start_ms` de cada
registro de petición cuenta desde ese momento.
