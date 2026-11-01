# Relatórios

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` e `ekte compare` imprimem um veredito e escrevem o relatório em
`reports/` (`--out-dir`) como JSON, Markdown, HTML e PDF (`--format all`, o valor
por omissão); `--format json|md|html|pdf` escreve um único formato. `--json` e
`--compact` imprimem antes em stdout.

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

Um relatório contém o veredito (risco, confiança, pontuação, nota), as
constatações principais com recomendações, as pontuações por dimensão e os
**Dimension details**, as constatações de cada detetor com as suas evidências, a
secção de desempenho, o perfil da base de conhecimento usado e os idiomas de
sonda. O texto controlado pelo relay é ocultado e escapado antes de ser escrito.
