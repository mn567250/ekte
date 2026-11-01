# 报告

> [🇬🇧 English](../../../guide/reports.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` 和 `ekte compare` 会输出结论，并把报告以 JSON、Markdown、HTML 和 PDF 写入
`reports/`（`--out-dir`，`--format all`，默认）；
`--format json|md|html|pdf` 只写一种格式。`--json` 和 `--compact` 则改为输出到 stdout。

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

报告包含结论（风险、置信度、分数、评级）、带建议的关键发现、各维度得分与 **Dimension details**、
每个检测器的发现及证据、性能部分、所用的知识库画像以及探测语言。由中转站控制的文本在写出前都会
经过脱敏和转义。
