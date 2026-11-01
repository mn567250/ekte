# Informes

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` y `ekte compare` imprimen un veredicto y escriben el informe en
`reports/` (`--out-dir`) como JSON, Markdown, HTML y PDF (`--format all`, el valor
por defecto); `--format json|md|html|pdf` escribe un solo formato. `--json` y
`--compact` imprimen en stdout en su lugar.

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
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
