# Informes

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` y `ekte compare` imprimen un veredicto y escriben el informe en
`reports/` (`--out-dir`) como JSON, Markdown, HTML y PDF (`--format all`, el valor
por defecto); `--format json|md|html|pdf` escribe un solo formato. `--json` y
`--compact` imprimen en stdout en su lugar.

```text
╭─ ✗ Likely substituted — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · coverage 100% · confidence medium             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

Un informe contiene el veredicto (riesgo, confianza, puntuación, nota), los
hallazgos clave con recomendaciones, las puntuaciones por dimensión y los
**Dimension details**, los hallazgos de cada detector con su evidencia, la
sección de rendimiento, el perfil de la base de conocimiento usado y los idiomas
de sonda. El texto controlado por el relay se censura y se escapa antes de
escribirse.

Junto a la puntuación, cada informe muestra la **cobertura**: la parte del peso
de las dimensiones ejecutadas que pudo evaluarse. El resumen del veredicto
nombra la dimensión que se ejecutó pero no pudo evaluarse, y una cobertura baja
limita la calificación o la omite («sin calificación: se evaluó demasiado
poco»); véase [Puntuación global, nota y pesos](methodology.md#puntuación-global-nota-y-pesos).

## Archivos de evidencia

Con `--evidence PATH` (`check`, `compare`, `image`, `audio`), y por defecto
para cada ejecución guardada en el historial, ekte escribe además cada petición
y respuesta HTTP original de la ejecución en un archivo: JSON Lines en un flujo
zstd, `<run_id>.jsonl.zst` (un directorio indicado como `PATH` recibe ese
nombre). La primera línea describe la ejecución; cada línea siguiente es una
petición con su respuesta, incluido el momento en que llegó cada fragmento de la
respuesta. El `seq` de una línea es el `seq` de la petición en
`performance.requests` del informe, así que cada petición que lista el informe
puede consultarse. El campo `evidence` del informe nombra el archivo con su
SHA-256 y su número de intercambios.

```bash
ekte check --base-url https://relay.example.com/v1 --model gpt-4o --evidence reports/
zstd -dc reports/<run_id>.jsonl.zst | jq -c 'select(.seq == 12)'
```

Cada hallazgo nombra las peticiones en las que se basa (`evidence_seqs`; vacío
cuando no se basa en ninguna, como la comprobación TLS). `ekte evidence-export`
toma el archivo (o el id de una ejecución guardada) y lo convierte en HAR para
un visor HAR o las herramientas de desarrollo del navegador (`--as har`),
en un script curl que vuelve a enviar las peticiones (`--as curl`; defina
antes `EKTE_API_KEY`, el archivo nunca contiene la clave) o en un único
documento JSON (`--as json`); `--seq` elige peticiones.

`ekte rescore` vuelve a evaluar una ejecución registrada con la versión de
ekte instalada: repite la misma auditoría, pero responde a cada petición con la
respuesta registrada (al ritmo registrado) en lugar de contactar con el
intermediario, de modo que las comprobaciones mejoradas se aplican a
ejecuciones antiguas. Admite el id de una ejecución guardada o un archivo de informe con
`--evidence PATH`. Con `--replace` el resultado sustituye a la ejecución
guardada (mismo id, hora y monitor); sin él se sigue guardando como una
ejecución nueva, lo que está obsoleto y muestra un aviso (una versión posterior
de ekte sustituirá por defecto; `--no-save` no guarda nada). Una comprobación que ahora pregunta algo que la
ejecución registrada nunca preguntó queda sin concluir en lugar de puntuarse
con una suposición; el campo `rescored_from` del informe indica cuántas
peticiones se reprodujeron y qué comprobaciones no tenían ninguna.

`ekte rescore --all` vuelve a puntuar, una tras otra, todas las ejecuciones
guardadas que puntuó otra versión de ekte, sustituye cada una y muestra su
veredicto antes y después. Una ejecución sin un archivo de evidencia utilizable
no se vuelve a puntuar: conserva su veredicto y se omite indicando el motivo.
Lo mismo ocurre con una ejecución cuya nueva puntuación no tendría puntuación
alguna (ninguna de sus comprobaciones tiene una respuesta grabada, como en una
ejecución anterior a ellas); `ekte rescore ID` no guarda esa nueva puntuación.
`ekte serve` hace lo mismo en segundo plano en su primer arranque tras una
actualización (consulta [Interfaz web](web-ui.md)).

Las exportaciones en Markdown, HTML y PDF de un informe vuelto a puntuar
indican ambas versiones, cuándo se volvió a puntuar y el veredicto anterior;
el veredicto `--compact` las incluye como `rescored`.

Las claves y los encabezados sensibles se eliminan antes de escribir nada (vea
[Privacidad](privacy.md)). Cada línea cumple
`ekte/schemas/evidence.schema.json` ([Esquemas](../../../reference/schemas.md)).
En la interfaz web, **Ver evidencia** bajo un hallazgo de una ejecución guardada
lista las peticiones de la comprobación correspondiente y abre cada petición y
respuesta original.
