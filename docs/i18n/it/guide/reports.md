# Rapporti

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` e `ekte compare` stampano un verdetto e scrivono il rapporto in
`reports/` (`--out-dir`) come JSON, Markdown, HTML e PDF (`--format all`, il
predefinito); `--format json|md|html|pdf` scrive un solo formato. `--json` e
`--compact` stampano invece su stdout.

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

Un rapporto contiene il verdetto (rischio, affidabilità, punteggio, voto), le
rilevazioni principali con le raccomandazioni, i punteggi per dimensione e i
**Dimension details**, le rilevazioni di ogni rilevatore con le prove, la sezione
prestazioni, il profilo della base di conoscenza usato e le lingue di sonda. Il
testo controllato dal relay viene oscurato ed escapato prima di essere scritto.
