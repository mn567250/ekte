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

## 证据文件

使用 `--evidence PATH`（`check`、`compare`、`image`、`audio`）时，以及每次保存到历史记录的检测默认情况下，
ekte 还会把这次检测的每一个原始 HTTP 请求和响应写入一个文件：一条 zstd 流中的 JSON Lines，
`<run_id>.jsonl.zst`（作为 `PATH` 给出的目录会得到这个文件名）。第一行描述这次检测；
之后每一行是一个请求及其响应，包括响应每一块到达的时间。某行的 `seq` 就是该请求在报告
`performance.requests` 中的 `seq`，因此报告列出的每个请求都能查到。报告的 `evidence`
给出文件名、其 SHA-256 和交换次数。

```bash
ekte check --base-url https://relay.example.com/v1 --model gpt-4o --evidence reports/
zstd -dc reports/<run_id>.jsonl.zst | jq -c 'select(.seq == 12)'
```

每个发现都会给出它所依据的请求（`evidence_seqs`；不依据任何请求时为空，如 TLS 检查）。
`ekte evidence-export` 接受证据文件（或已保存检测的 id），将其转换为 HAR，供 HAR 查看器或浏览器开发者工具使用（`--as har`），
或转换为重新发送这些请求的 curl 脚本（`--as curl`；请先设置 `EKTE_API_KEY`，文件中从不包含密钥），
或转换为单个 JSON 文档（`--as json`）；`--seq` 用于选择请求。

密钥和敏感请求头在写入前即被去除（见[隐私](privacy.md)）。每一行都符合
`ekte/schemas/evidence.schema.json`（[Schema](../../../reference/schemas.md)）。在 Web 界面中，
已保存检测的某个发现下的 **查看证据** 会列出其背后检测项的请求，并可打开每个原始请求和响应。
