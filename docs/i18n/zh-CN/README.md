# ekte — 大模型中转站“货不对板”检测工具

> [🇬🇧 English](../../../README.md) · **🇨🇳 中文** · [🇫🇷 Français](../fr/README.md) · [🇪🇸 Español](../es/README.md) · [🇵🇹 Português](../pt/README.md) · [🇮🇹 Italiano](../it/README.md) · [🇩🇪 Deutsch](../de/README.md) · [🇳🇴 Norsk](../nb/README.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](../../../LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](../../../pyproject.toml)

**ekte** 是一个本地优先的工具，用来检测 API 中转站（转售商 / 代理）是否真的提供了它
声称的模型——还是偷偷换成更便宜的模型、截断你的上下文窗口、伪造流式输出，或虚报 token
计费。一句话：你付的钱，买到对的货了吗？它支持 **OpenAI Chat Completions API**、
**Anthropic Messages API** 和 **OpenAI Responses API**（`/v1/responses`）——自动识别，
也可用 `--api openai|anthropic|responses` 强制指定。

只需给出中转站地址和它声称提供的模型，ekte 就会运行一整套黑盒探测，把观察到的行为与内置的
**7 家厂商、98 个模型画像**的知识库比对，并给出清晰、有证据支撑的结论——可以在命令行里、
本地 Web 界面里查看，也可以输出 JSON 供其他工具或大模型读取。

> ekte 给出的是**“行为差异与风险”的黑盒证据，而非欺诈的密码学证明**。
> 请阅读 [负责任使用](guide/privacy.md#负责任使用)。

## 为什么需要它

中转 key 市场上充斥着“GPT-4o 一折价”之类的报价。很多是诚实的，也有一些不是——而
不诚实的那些很难用肉眼识破：

- 你请求 `gpt-4o`，实际却被悄悄换成了 `gpt-4o-mini` 或某个开源模型。
- 中转站宣称支持 1M token 上下文，实际却悄悄截断到 32K。
- 所谓的“流式输出”其实是把完整响应缓冲后再切块发送，毫无延迟优势。
- 返回的 `usage` token 数被虚报，你的余额消耗得比应有的更快。
- 本应支持工具调用 / JSON 模式的模型，实际悄悄不支持。

ekte 把“感觉哪里不对”变成一份可复现的报告。

## 安装

需要 Python 3.11+，支持 Linux、macOS 和 Windows。

```bash
pip install 'ekte[web]'          # 或：uv tool install 'ekte[web]'
```

`web` 扩展提供本地 Web 界面；只用命令行时可以不装。
从源码、用 uv 或在 Docker 中安装：[安装](guide/install.md)。

## 快速开始

```bash
export EKTE_API_KEY=sk-your-relay-key

# 按中转站声称的模型审计它
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard

# 最强检测：与同款模型的可信基线对比
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o

# 或者点鼠标：本地 Web 界面
ekte serve
```

更多示例、配置文件，以及在脚本或大模型智能体中使用：
[快速开始](guide/quickstart.md)。Web 界面：[Web 界面](guide/web-ui.md)。

## 检测了什么

ekte 对十个维度评分。四个**核心维度**——模型身份、上下文窗口、能力声明和计费用量——最直接地
指向“货不对板”。维度名称与 Web 界面和报告中使用的一致。

| 维度 | 标识 | 能发现什么 |
|---|---|---|
| **模型身份** | `model_identity` | 模型被悄悄降级或替换 |
| **上下文窗口** | `context_window` | 上下文被悄悄截断，以及“中段遗失” |
| **能力声明** | `capability` | 声称支持的工具调用、JSON 模式、最大输出或视觉能力其实没有兑现 |
| **协议兼容** | `protocol` | 请求参数和响应属性被丢弃或忽略 |
| **计费用量** | `billing` | token 用量被虚报或缺失 |
| **连通性** | `connectivity` | 端点可达性和公布的模型列表 |
| **流式真实性** | `streaming` | 伪流式（先缓冲再切块） |
| **并发可靠** | `reliability` | 并发负载下的失败和变慢 |
| **传输安全** | `security` | 明文 HTTP、密钥回显、注入的系统提示词、篡改 |
| **性能** | `performance` | 延迟、首 token 时间和吞吐量有多稳定 |

每项检测如何工作、结论如何得出：
[方法论](guide/methodology.md)。

## 文档

| 用户指南 | |
|---|---|
| [安装](guide/install.md) | pip、uv、从源码安装、可选扩展 |
| [快速开始](guide/quickstart.md) | 第一次检测、配置文件、在脚本和大模型智能体中使用 |
| [Web 界面](guide/web-ui.md) | 页面、后台检测、分析、语言 |
| [套件与对比模式](guide/suites.md) | 套件、自定义套件、可信基线、LLM 裁判 |
| [性能](guide/performance.md) | performance 部分、专用探测和请求超时 |
| [持续监控](guide/monitoring.md) | 定时重新检测、Webhook 告警、API 密钥的保存 |
| [Embedding、rerank、图像与音频检测](guide/other-endpoints.md) | 非对话端点的检测 |
| [知识库](guide/knowledge-base.md) | 模型画像，以及添加你自己的画像 |
| [报告](guide/reports.md) | 报告格式与内容 |
| [隐私与本地数据](guide/privacy.md) | 哪些数据留在你的机器上；负责任使用 |
| [GitHub Action](guide/github-action.md) | 让 CI 工作流以中转站检测结果为关卡 |
| [Docker](guide/docker.md) | 在容器中运行 Web 界面 |
| [方法论](guide/methodology.md) | 每项检测、它的计分标准和注意事项 |
| [从 zing 迁移](guide/migrating-from-zing.md) | 已安装 zing 的用户需要注意的变化 |

| 参考文档（英文） | |
|---|---|
| [命令行](../../reference/cli.md) | 所有命令与选项，以及退出码 |
| [报告与 webhook 格式](../../reference/schemas.md) | JSON 格式及其 `schema_version` |
| [稳定性与兼容性](../../reference/stability.md) | semver 保护什么、弃用政策、支持的 Python 版本与系统 |
| [更新日志](../../../CHANGELOG.md) | 每个版本的变更 |

参与贡献：[贡献指南](../../CONTRIBUTING.md) 与
[开发者指南](../../dev/developer-guide.md)（英文）。
安全问题：[安全政策](../../SECURITY.md)。

## 许可证

[Apache-2.0](../../../LICENSE)
