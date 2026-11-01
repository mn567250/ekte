# Berichte

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` und `ekte compare` geben ein Urteil aus und schreiben den Bericht nach
`reports/` (`--out-dir`) als JSON, Markdown, HTML und PDF (`--format all`, der
Standard); `--format json|md|html|pdf` schreibt ein einzelnes Format. `--json` und
`--compact` geben stattdessen auf stdout aus.

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

Ein Bericht enthält das Urteil (Risiko, Konfidenz, Bewertung, Note), die
wichtigsten Befunde mit Empfehlungen, die Bewertungen je Dimension und
**Dimension details**, die Befunde jedes Detektors mit Belegen, den
Leistungsabschnitt, das verwendete Wissensbasis-Profil und die Testsprachen. Vom
Relay kontrollierter Text wird vor dem Schreiben geschwärzt und maskiert.
