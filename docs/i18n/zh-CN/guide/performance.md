# 性能

> [🇬🇧 English](../../../guide/performance.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/performance.md) · [🇪🇸 Español](../../es/guide/performance.md) · [🇵🇹 Português](../../pt/guide/performance.md) · [🇮🇹 Italiano](../../it/guide/performance.md) · [🇩🇪 Deutsch](../../de/guide/performance.md) · [🇳🇴 Norsk](../../nb/guide/performance.md)

每份报告都包含一个 **performance** 部分：延迟、首 token 时间（TTFT）、解码与端到端 tokens/s、
块间延迟与抖动、错误/超时/429 比率、网络拆解（TCP 连接、TLS、一次 `GET /models` 往返、
服务端耗时）以及冷启动，每项都给出 count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev。

运行专用探测时，它会为**性能表现**维度计分。分数衡量的是**稳定性**而非绝对速度，因此慢但稳定的
端点（本地或自托管模型）不会因为不是数据中心而被扣分；各项检查及其分值见
[方法论](methodology.md#performance--性能表现)。性能发现的严重程度最高为“低”：它们影响分数，但从不影响风险结论。没有探测时
（`standard` 且无基线，或 `smoke`），该维度不运行，也不计入综合分。

- **standard** 从检测自身的请求中收集性能数据。
- **deep / full / custom** 额外运行专用探测：100 个不可缓存的请求，每个输出 128 个 token
  （每个提示词都以随机请求 id 开头；不发送任何缓存或推理参数），外加一次并发度为 `--concurrency`
  的突发。可用 `--performance-requests`（0 表示关闭）和 `--performance-max-tokens` 调整。
- 探测默认使用流式；`--performance-non-streaming`（或 Web 界面中的**流式 / 非流式**开关）
  可测量不支持流式的中转站。**full** 会交替测量两种模式并并排展示。
- **compare** 在两个端点上交替发送请求运行探测，并增加一张“目标 vs 基线”对照表
  （`standard` 下每侧 5 个请求，不足以进行稳定性检查），目标更好的差异以绿色 ✓ 标出，
  更差的以红色 ✗ 标出。

token 会计数两次——取自中转站的 `usage` 和本地计数——因此即使缺少 `usage` 也能测量吞吐。
本地计数是内置启发式方法的估算值（约 ±15-20%；不使用也不下载任何分词器），该部分始终会注明这一点。
只有样本足够时才显示对应分位数（p90 需 10 个，p95 需 20 个，p99 需 100 个）。JSON 报告保存
每个请求的耗时（只有数字，没有文本）；HTML 报告和 Web 界面会把它们画在检测时间轴上。

在 `ekte serve` 中同时运行的检测（多个浏览器标签页、监控）不会相互扭曲计时：CPU 密集的准备工作
（例如构建较长的上下文窗口提示）在服务器的事件循环之外运行。

**请求超时。** `timeout_sec`（`--timeout`，默认 60 秒）是基础值；每个请求会按提示长度和
输出预算额外加时，因此较长的上下文窗口探测或较慢的自托管模型不会在一分钟后被切断。
本地和私有地址（`localhost`、`127.x`、`192.168.x`、`host.docker.internal` 等）至少有
300 秒。`max_request_sec`（`--max-request-time`，默认 900 秒）是单个请求（含流式）的
硬上限，任何请求都不会无限挂起。仍然超时的上下文窗口探测记为“不确定”，而不是截断。
