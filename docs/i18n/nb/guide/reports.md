# Rapporter

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · **🇳🇴 Norsk**

`ekte check` og `ekte compare` skriver ut en konklusjon og skriver rapporten til
`reports/` (`--out-dir`) som JSON, Markdown, HTML og PDF (`--format all`,
standard); `--format json|md|html|pdf` skriver ett format. `--json` og
`--compact` skriver til stdout i stedet.

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

En rapport inneholder konklusjonen (risiko, sikkerhet, score, karakter), de
viktigste funnene med anbefalinger, scorene per dimensjon og **Dimension
details**, funnene fra hver detektor med bevis, ytelsesdelen, profilen fra
kunnskapsbasen som ble brukt, og probespråkene. Tekst som reléet styrer, sladdes
og escapes før den skrives.
