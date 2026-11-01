# Rapports

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` et `ekte compare` affichent un verdict et écrivent le rapport dans
`reports/` (`--out-dir`) en JSON, Markdown, HTML et PDF (`--format all`, par
défaut) ; `--format json|md|html|pdf` écrit un seul format. `--json` et `--compact`
écrivent plutôt sur stdout.

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

Un rapport contient le verdict (risque, confiance, score, note), les constats
clés avec leurs recommandations, les scores par dimension et les **Dimension
details**, les constats de chaque détecteur avec leurs preuves, la section
performance, le profil de la base de connaissances utilisé et les langues de
sonde. Le texte contrôlé par le relais est expurgé et échappé avant d'être écrit.
