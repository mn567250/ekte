# 持续监控

> [🇬🇧 English](../../../guide/monitoring.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/monitoring.md) · [🇪🇸 Español](../../es/guide/monitoring.md) · [🇵🇹 Português](../../pt/guide/monitoring.md) · [🇮🇹 Italiano](../../it/guide/monitoring.md) · [🇩🇪 Deutsch](../../de/guide/monitoring.md) · [🇳🇴 Norsk](../../nb/guide/monitoring.md)

中转站今天可能提供真货，下周就悄悄换掉。`ekte watch` 按计划重新检测，把每次运行记录到
检测历史，并在风险越过阈值或相比上一次**恶化**时通知 Webhook。

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang zh                                     # 或用 --once 配合 cron
```

告警会按 **Slack / 飞书 / 钉钉 / 通用 JSON** 格式化（根据 Webhook URL 自动识别），并使用
告警语言撰写——默认英文；`--alert-lang en|zh|fr|es|pt|it|de|nb`。通用 JSON 负载的键和机器值
（`risk_level`、`score` 等）保持语言中立，面向人阅读的值（`text`、`headline`、`key_findings`）
会被翻译，并注明 `language`。

**在 Web 界面中**，`ekte serve` 在服务进程内的后台调度器中运行同样的监控，把每次运行存入
**检测历史**，并发送同样的 Webhook 告警。在**检测历史**中打开一次运行，选择**设为监控**。ekte 会把该次运行的配置
（中转站、模型、声称的模型、厂商、套件、自定义维度）复制成**监控**页面上一个已暂停的监控；
在那里设置间隔和 API 密钥（检测历史从不保存密钥）并启用。间隔、密钥、**告警阈值**、
Webhook 和**告警语言**都可以在每个监控上直接修改。点击监控名称可把卡片折叠为名称、状态和上次运行
（列表上方的**全部折叠** / **全部展开**；按浏览器记住），筛选面板（搜索、状态、上次风险、接口类型、
中转站、套件）可像**检测历史**一样缩小较长的列表。

每个监控都有自己的告警语言（默认跟随界面语言），可以立即运行、暂停或删除，并固定使用创建时的
知识库画像，直到你重新固定。

到期的监控会同时运行，每个都是一次独立的检测，但同一中转站主机同一时刻最多只有一个检测，总数最多为
`EKTE_MAX_PARALLEL_AUDITS`；运行会等待空闲名额（你手动启动的检测也可能排在运行中的监控之后）。
一次运行的时间是其检测开始的时刻（在任何等待之后）。判断是否恶化时，与同一中转站和模型最近一次保存的运行比较，
无论此后又保存了多少其他运行。一次运行的告警 Webhook 会同时发送，因此一个缓慢或失效的 Webhook
不会拖住其他 Webhook。密钥加密保存在本地数据目录中，绝不会返回给浏览器。

**API 密钥保存方式。** 默认情况下 ekte **不保存**监控的 API 密钥：你输入的密钥只留在
`ekte serve` 的内存中，从不写入磁盘。重启后，**监控**页面会列出需要重新输入密钥的监控；
它们会等待（不会运行失败，也不会告警），直到你重新输入。没有密钥的监控以及 `env:`/`file:`
引用照常运行。如果希望密钥在重启后依然可用，请在**监控**页面的 **API 密钥保存方式**中
选择**加密保存在本机**：密钥会用主密钥加密后保存在 `watches.db` 中。切换回来时，已保存的
密钥会移入内存并从 `watches.db` 中清除。页面提示会显示当前模式、在切换前请你确认，并报告
移动了哪些密钥。已经保存了加密密钥、或设置了
`EKTE_SECRET_KEY` 的安装会继续保存，直到你切换。

**主密钥。** 监控的 API 密钥用一个主密钥加密，ekte 从不把主密钥写入磁盘。你第一次保存 API 密钥时，
**监控**页面会创建主密钥并只显示一次：复制或下载它，保存在密码管理器中（浏览器也可以保存），再粘贴回来确认。
每次重启 `ekte serve` 后页面都会再次请求它（浏览器可以自动填入）；在此之前，需要它的监控会等待，
而没有密钥或使用 `env:`/`file:` 密钥的监控照常运行。页面上的状态栏还提供**锁定**、**更换**和
**忘记了密钥？**（丢弃已加密的 API 密钥，以便你重新输入）。无人值守或 Docker 部署时，
用 `EKTE_SECRET_KEY` 传入主密钥（见 [Docker](docker.md)）；命令行中用
`ekte secret status | export | rotate` 管理它。
