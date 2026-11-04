# 隐私与本地数据

> [🇬🇧 English](../../../guide/privacy.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/privacy.md) · [🇪🇸 Español](../../es/guide/privacy.md) · [🇵🇹 Português](../../pt/guide/privacy.md) · [🇮🇹 Italiano](../../it/guide/privacy.md) · [🇩🇪 Deutsch](../../de/guide/privacy.md) · [🇳🇴 Norsk](../../nb/guide/privacy.md)

- **仅限本地。** `ekte serve` 只监听回环地址（`127.0.0.1`、`::1`、`localhost`），只响应这些主机名，
  并拒绝跨站请求；它没有登录，因为你的机器之外没有任何东西能访问它。ekte 只会联系你配置的端点
  （目标、基线、裁判、Webhook）；运行时不下载任何东西，连分词器文件也不下载。
- **密钥。** 报告和检测历史只保存 API 密钥的指纹。监控的密钥加密保存在 `watches.db` 中；
  用于解密的主密钥从不写入数据目录（由你保管，见[持续监控](monitoring.md)），因此目录的副本不会泄露任何 API 密钥。
  该目录仍然仅对你本人可访问。
- **数据目录。** `~/.ekte`（或 `EKTE_DATA_DIR`），以 `0700` 创建，文件为 `0600`：
  `history.db`（检测历史）、`watches.db`（监控，含加密后的密钥）和 `kb.db`（你的知识库条目）。
  删除该目录即可清除全部数据。
  `ekte data-dir` 会显示它的位置；`--data-dir 路径` 可为单次运行另选目录，例如
  `ekte serve --data-dir .` 把数据库放在当前文件夹。它们是普通的 SQLite 文件，可自行打开分析
  （ekte 运行时最好只读打开）。如果该文件夹是代码仓库，请勿提交 `watches.db`。
  `history_metrics` 每次运行存一行测量值，`history_requests` 存每条请求记录（只在那里存一份，
  不再放进每份报告）。
- **证据文件。** 保存到历史记录的检测（Web 界面、监控、`ekte watch`、
  `ekte embed`、`ekte rerank`）还会保留它收发的每一个原始请求和响应，存放在数据目录的
  `evidence/<run_id>.jsonl.zst` 中，这样每个发现都能对照实际发送和收到的内容核验。
  你的 API 密钥、`--header` 的值、`Authorization`、Cookie 及其他敏感请求头会在写入前去除；
  提示词和回答原样保留。删除一次检测会同时删除其文件。可以按次关闭（检测表单中的
  **原始请求/响应** 设置，或 `POST /api/v1/jobs` 中的 `"evidence": false`）、按监控关闭，
  或对整个服务器关闭（`ekte serve --no-evidence`、`EKTE_NO_EVIDENCE=1`）。
  `ekte check`、`compare`、`image` 和 `audio` 默认不保留，除非使用 `--evidence PATH`
  （见[报告](reports.md)）。

## 负责任使用

ekte 是黑盒审计辅助工具。它**无法证明**：

- 某个厂商存储了你的提示词或用其训练，
- 它始终路由到同一个确切的模型（中转站可以按概率路由），
- 超出独立 token 估算所能提示范围的计费欺诈。

请把报告用于你自己的尽职调查。**不要仅凭单次运行就公开指控某个厂商**，而不去审视样本量、
成本设置和当地法律。在得出强结论之前，请先用 `ekte compare` 对照可信基线运行。
