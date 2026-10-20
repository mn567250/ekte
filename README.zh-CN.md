# zing — 大模型中转站「货不对板」检测工具

> [🇬🇧 English](README.md) · **🇨🇳 中文** · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** 是一个本地优先的工具，用来检测 API 中转站（转售商 / 代理）是否真的提供了它
声称的模型——还是偷偷换成更便宜的模型、截断你的上下文窗口、伪造流式输出，或虚报 token
计费。一句话：你付的钱，买到对的货了吗？它支持 **OpenAI Chat Completions API**、
**Anthropic Messages API** 和 **OpenAI Responses API**（`/v1/responses`）——自动识别，
也可用 `--api openai|anthropic|responses` 强制指定。

只需给出中转站地址和它声称提供的模型，zing 就会运行一整套黑盒探测，把观察到的行为与内置的
**7 家厂商、98 个模型画像**的知识库比对，并给出清晰、有证据支撑的结论——可以在命令行里、
本地 Web 界面里查看，也可以输出 JSON 供其他工具或大模型读取。

> zing 给出的是**「行为差异与风险」的黑盒证据，而非欺诈的密码学证明**。
> 请阅读 [负责任使用](#负责任使用)。

本 README 面向 zing 的**使用者**。zing 如何构建、测试和发布，见[开发者指南](DEVELOPER_GUIDE.zh-CN.md)；
每项检测如何工作、如何计分，见[方法论](docs/METHODOLOGY.zh-CN.md)。

---

## 目录

- [为什么需要它](#为什么需要它)
- [安装](#安装)
- [快速开始](#快速开始)
- [Web 界面（`zing serve`）](#web-界面zing-serve)
- [检测了什么](#检测了什么)
- [结论如何得出](#结论如何得出)
- [套件（suite）](#套件suite)
- [性能](#性能)
- [对比模式与 LLM 裁判](#对比模式与-llm-裁判)
- [持续监控](#持续监控)
- [Embedding、rerank、图像与音频检测](#embeddingrerank图像与音频检测)
- [在 CI 中使用（GitHub Action）](#在-ci-中使用github-action)
- [知识库](#知识库)
- [报告](#报告)
- [隐私与本地数据](#隐私与本地数据)
- [负责任使用](#负责任使用)
- [更多文档](#更多文档)
- [许可证](#许可证)

## 为什么需要它

中转 key 市场上充斥着「GPT-4o 一折价」之类的报价。很多是诚实的，也有一些不是——而
不诚实的那些很难用肉眼识破：

- 你请求 `gpt-4o`，实际却被悄悄换成了 `gpt-4o-mini` 或某个开源模型。
- 中转站宣称支持 1M token 上下文，实际却悄悄截断到 32K。
- 所谓的「流式输出」其实是把完整响应缓冲后再切块发送，毫无延迟优势。
- 返回的 `usage` token 数被虚报，你的余额消耗得比应有的更快。
- 本应支持工具调用 / JSON 模式的模型，实际悄悄不支持。

zing 把「感觉哪里不对」变成一份可复现的报告。

## 安装

需要 Python 3.10+。以下任一方式都会提供 `zing` 命令。

### 使用 pip

```bash
# 从 PyPI 安装
pip install zing-audit

# 或从源码安装
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### 使用 [uv](https://docs.astral.sh/uv/)

```bash
# 从 PyPI 安装为独立工具，加入 PATH
uv tool install zing-audit

# 或不安装、直接运行一次
uvx --from zing-audit zing --help

# 或从源码安装到项目本地的虚拟环境
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows：.venv\Scripts\activate
```

也可以不克隆，直接从 Git 仓库安装：
`uv tool install git+https://github.com/cenbonew/zing`。

### 可选附加项

- `web` —— 本地 Web 界面（`zing serve`）。

```bash
pip install 'zing-audit[web]'      # pip，从 PyPI
pip install -e '.[web]'            # pip，从源码
uv tool install 'zing-audit[web]'  # uv，从 PyPI
uv pip install -e '.[web]'         # uv，从源码
```

不再需要 `tokenizers` 附加项：自 0.19.0 起它是空的，保留它只是为了让旧的安装命令仍然可用。
zing 用内置的启发式方法计数 token，运行时不下载任何东西（也不下载分词器文件），因此在只能访问
被检测中转站的受限或离线环境中同样可以运行。

PDF 报告（`--format pdf` 以及 Web 界面中的 PDF 下载）无需任何附加项：由
[ReportLab](https://www.reportlab.com/opensource/) 排版，这是一个纯 Python 依赖，在 Linux、macOS 和
Windows 上都不需要系统库。

### 使用 Docker（仅 Web 界面）

在源码目录中：

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# 打开 http://localhost:8000
```

端口务必像上面这样只发布到 `127.0.0.1`。详细说明和环境变量见
[开发者指南 → Docker](DEVELOPER_GUIDE.zh-CN.md#docker) 与 [docs/DOCKER.md](docs/DOCKER.md)。

## 快速开始

```bash
# 1) 按中转站声称的模型审计它（模型 id + 厂商提示）
export ZING_API_KEY=sk-your-relay-key
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) 最强检测：与同款模型的可信基线对比
export OPENAI_API_KEY=sk-your-openai-key
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) 审计 Anthropic 原生（Messages API）中转——协议根据 base_url/model 自动识别，
#    也可用 --api anthropic 强制指定
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) 确认疑似替换：用中转的「真实」模型 id 对照它被宣传成的模型画像来审计
#    （此例：一个豆包模型被当作 deepseek-v4-flash 出售）
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) 列出某个端点公布的模型
zing models --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY

# 6) 查看知识库
zing kb            # 全部画像及其来源
zing kb deepseek   # 单个厂商

# 7) 生成可提交的配置文件
zing init          # 写出 zing.yaml
zing check -c zing.yaml
```

API 密钥可以直接填写，也可以写成 `env:VAR` 或 `file:/path`；报告里只会出现密钥的指纹。
完整的配置文件示例见 [`examples/zing.yaml`](examples/zing.yaml)。

### 作为给大模型 / Agent 使用的工具

zing 天生适合被其他程序或模型驱动。所有内容（包括错误）都以 JSON 输出到 stdout，
退出码即门禁。

```bash
# 精简、适合 Agent 的结论（比 --json 小约 5 倍：不含大体量证据）
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# 需要每条发现的证据时，输出完整结构化报告
zing check --base-url ... --model gpt-4o --json

# 先算预算：会运行哪些检测器 + 预估 API 调用次数，且「不」发出任何请求
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# 以退出码做门禁（风险 >= medium 或分数低于 --fail-under 时退出码为 1）；
# 配置/用法错误以 JSON 输出并退出码 2
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# 机器可读的发现能力
zing kb --json                      # 整个知识库
zing models --base-url ... --json   # 某个端点公布了哪些模型
```

在 `--json`/`--compact` 模式下，配置错误会输出 `{"error": {...}}`（退出码 2），
而不是面向人的提示，方便流水线统一解析失败。

## Web 界面（`zing serve`）

更喜欢点鼠标？本地 Web 界面封装了同一套引擎——无需命令行。

```bash
pip install 'zing-audit[web]'     # 或：uv tool install 'zing-audit[web]'
zing serve                        # 打开 http://localhost:8000
```

新界面的表单会引导你完成配置：

1. 选择**中转站 / 厂商**：知识库中的厂商，或你保存过的中转站。它的基础地址会自动填写（该厂商的
   其他已知地址作为建议提供）。其他中转站请选**其他（手动填写地址）**并填写**中转站地址**。
2. 如果中转站需要，填写 **API 密钥**。
3. zing 会自动列出中转站的模型（选择中转站时，以及地址或密钥每次改变时；**刷新模型列表**会重新获取）。
   选择**请求的模型**。没有模型列表的中转站会改为手动输入 id（**手动输入**）。
4. 可选：从知识库的模型中选择**声称的模型**，即中转站声称提供的模型。若请求的模型在知识库中，
   会被预先选中；只有当中转站以另一个名字出售该模型时才需要更改。zing 据此确定检测所用的厂商资料。

尚不在列表中的中转站可以用**保存到知识库**以你起的名字保存，下次选一下即可。可信基线
（**对照可信基线**）和**工具**页面的配置方式相同。经典界面保留简单的输入框和**获取模型列表**。

然后点击**开始检测**，**实时**观看检测过程：每个检测项
都显示得分和耗时，有发现的检测项可以展开查看证据。结果是一份可分享的结论报告：评级、带计分标准的
**逐项体检**、通俗易懂的发现以及性能部分（新界面中还有列出每个检测器的**执行记录**）。

一切都在你的机器上运行：在浏览器里输入的密钥只会到达你本地的 zing 服务和被测中转站，
绝不会发给第三方。见[隐私与本地数据](#隐私与本地数据)。

### 页面

Web 界面有两个版本，共用同一个服务和同一份数据。**经典界面**在 `/` 打开；点它的
**试用新界面**链接进入 `/v2/` 下的**新界面**，新界面的**经典界面**链接可切回。
选择按浏览器记住。

| 页面 | 经典界面 | 新界面 | 用途 |
|---|---|---|---|
| **检测** | `/` | `/v2/` | 审计中转站（可对照基线）并阅读报告 |
| **控制台**（Console） | `/console` | — | 以紧凑的日志风格控制台运行同样的检测 |
| **工具** | `/tools` | `/v2/tools` | Embedding 与 rerank 检测 |
| **检测历史** | `/history` | `/v2/history` | 本机上运行过的每次检测，按「中转站 + 声称的模型」分组，附趋势 |
| **分析** | — | `/v2/analytics` | 按时间对比各中转站与模型：关键指标、带数据表的图表、排行榜 |
| **监控** | `/watches` | `/v2/watches` | 定时重新检测，并通过 Webhook 告警 |
| **知识库** | — | `/v2/kb` | 以模型、厂商、中转站三个标签页呈现知识库：浏览、启用/停用、添加你自己的 |

新界面额外提供：**检测历史**中的筛选和可配置趋势（分数、评级、延迟 p50、tokens/s）；
检测历史中每次运行都可**设为监控**或**重新检测**；各种格式的**下载报告**；主题切换（跟随系统 / 浅色 / 深色）；
以及**知识库**页面。

**后台检测（新界面）。** 在**检测**页启动的检测在切换页面或关闭标签页后仍会继续运行；
**转到后台运行**可主动将其转入后台。**检测历史**列出所有排队中和运行中的检测（以及运行中的监控）及其进度；
**实时查看**会重新打开实时视图，并补齐之前发生的全部内容。同一中转站的检测依次运行，互不干扰延迟和可靠性结果
（所有回环地址视为同一主机，因此本机部署的模型也会排队）；不同中转站的检测并行运行，最多同时四个
（`ZING_MAX_PARALLEL_AUDITS`）。监控同样会等待其中转站空闲。

**分析（新界面）。** `/v2/analytics` 把本地历史变成对比：所选时间范围的关键指标
（检测次数、健康分中位数、高风险占比、成功率、首字延迟、输出速度、计费比），并与之前
同样长度的一段时间对比；任一指标按中转站、模型或「中转站 × 模型」、按小时 / 天 / 周
的图表（中位数折线加 p25–p75 色带，最多四个数据系列，每张图都有对应的数据表）；以及
某个模型的各中转站、或某个中转站的各模型的排行榜。中转站按知识库条目（已保存的中转站
与厂商）分组，改名后历史会立即重新归组。少于 3 次检测的时间段会淡化显示——单次检测可能
是离群值；设置监控可获得定期测量。较早的检测只显示它当时测到的数据：页面会注明一个数值
基于多少次检测。默认只对比一种套件和探测方式（最常见的那种），避免混合不同的检测；筛选与
视图保存在网址中，可收藏或分享。所有数据都不离开本机。

其他面板回答更具体的问题：**高峰时段**（按你所在时区的「星期几 × 小时」热力图，显示首字延迟、延迟和输出速度（中位数及 p95 / p5 尾部）、字间抖动、网络与中转耗时、成功率或错误率——中转站在繁忙时段会变慢或更容易出错吗？按星期汇总；检测覆盖 90 天后可按 4 周周期，覆盖 180 天后可按月内周次）、**错误与可靠性**（按原因统计的失败调用——限流（HTTP 429）、服务器错误（5xx）、超时、网络错误——随时间变化并按中转站或模型划分，来自已保存的请求记录，并注明有多少次检测含有这些记录）、**模型真实性**（每个「中转站 × 模型」的身份、上下文窗口与能力检查结果，返回模型与请求不符的检测占比，以及实测上下文占声明上下文的比例）、**计费与 token**（计费比随时间变化并与 100% 参考线对比——高于此线说明中转站报告的 token 多于 zing 统计的——以及推理 token 和缓存输入的占比）和**中转开销**（中转站自报的处理耗时与到它的网络往返时间并列）。

**标签页与分享链接（分析）。** 各面板分在五个标签页里——**概览**（关键指标、排行榜）、**趋势**（随时间对比、高峰时段）、**可靠性**（错误、中转开销）、**模型真实性**和**计费**——位于页面标题和所有标签页共用的筛选面板下方；只加载正在查看的标签页。URL 保存标签页、筛选条件和每个图表选项（`#tab=reliability&range=30&relay=…&eb=dow_hour`），**复制此视图的链接**会复制它（浏览器不允许时则显示在一个可复制的文本框里）：打开链接即可看到完全相同的视图。**检测历史**和**分析**使用同一个筛选面板：收起时显示生效的筛选数量，并用一行列出它们（例如“最近 30 天 · standard · 流式 · Example Relay”），这样分享出去的视图一眼就能看出筛选了什么。

### 语言

每个页面顶部的语言下拉框可在 **🇬🇧 英语**（默认）、**🇨🇳 中文**（界面原始语言）、
**🇫🇷 法语**、**🇪🇸 西班牙语**、**🇵🇹 葡萄牙语**、**🇮🇹 意大利语** 和 **🇩🇪 德语**
之间切换界面；选择按浏览器记住。

从界面下载的报告（**下载报告**：JSON、Markdown、HTML 或 PDF）同样跟随所选语言：
JSON 键、枚举值（`risk_level`、`status`、`severity` 等）、id 和证据与命令行报告完全一致
（JSON 仍是合法的 zing 报告），而面向人阅读的值（结论标题和摘要、发现标题和摘要、建议、
检测器名称、备注）会被翻译，文件名也会带上语言（`zing-report.zh.json`、`zing-report.zh.pdf`）。
Markdown/HTML/PDF 文件的章节标题为英文。命令行自身的 `--format json|md|html|pdf`
报告始终为英文。

**发往被测端点的提示词不跟随界面语言。** zing 发给 LLM API 的每一段文本都是英文，
这样无论谁来读报告，同一个中转站都会得到同样的结论（答案校验和 token 估算都针对这些确切文本
校准过）。唯一的例外是那些「语言本身就是测量对象」的知识库指纹——例如中国原生模型的
中文流畅度、分词器和自我身份识别探测。每份报告都会记录实际使用的探测语言
（`prompt_languages`，例如 `["en", "zh"]`）。
`started_at` 记录检测开始的时间（UTC），每条请求记录的 `start_ms` 都从这一刻算起。

## 检测了什么

zing 对十个维度评分。四个**核心维度**——模型身份、上下文窗口、能力声明和计费用量——最直接地
指向「货不对板」。维度名称与 Web 界面和报告中使用的一致。

| 维度 | 标识 | 权重 | 能发现什么 |
|---|---|---|---|
| **模型身份** | `model_identity` | 21 | 模型被悄悄降级或替换——自我身份识别、知识截止日期、分词器指纹、回包中的 `model` 字段；可选 LLM 裁判 |
| **上下文窗口** | `context_window` | 19 | 上下文被悄悄截断（宣称 1M，32K 时回忆就失败），以及廉价 RAG/摘要中间层导致的「中段遗失」，通过大海捞针 + 二分搜索检测 |
| **能力声明** | `capability` | 13 | 声称支持的工具调用 / JSON 模式 / JSON schema / 最大输出其实没有兑现（或*超额*兑现，暗示换了模型）；**视觉**——声称支持图像输入的模型必须读出一张答案已知的生成图片 |
| **协议兼容** | `protocol` | 8 | 线上协议合规：多轮对话、停止序列、错误结构；每个请求参数都被接受（可见时也被遵守）、每个响应属性都存在；忽略 temperature/seed 的响应缓存 |
| **计费用量** | `billing` | 8 | token/用量虚报，以及缺失或无法核实的用量统计，通过独立的启发式 token 估算检测 |
| **连通性** | `connectivity` | 7 | 端点可达性和公布的 `/v1/models` 列表 |
| **流式真实** | `streaming` | 6 | 伪流式（先缓冲再切块），根据分块数量和块间时间间隔识别 |
| **并发可靠** | `reliability` | 6 | 并发负载下的成功率和延迟（HTTP 429 限流单独统计） |
| **传输安全** | `security` | 6 | HTTPS、请求头卫生、密钥回显；隐藏注入的系统提示词；传输途中对回答和工具调用的篡改（答案已知的金丝雀）；提示词前缀缓存（计时） |
| **性能表现** | `performance` | 6 | 延迟、首 token 时间和吞吐量有多*稳定*，失败率，以及并发负载下的变慢程度；速度本身只与参考值对比（见[性能](#性能)） |

[方法论](docs/METHODOLOGY.zh-CN.md)介绍了每项探测、它对应的中转站作弊手法、它的计分标准，
以及误报方面的注意事项。

## 结论如何得出

简要说明（详见[方法论](docs/METHODOLOGY.zh-CN.md#zing-如何计分)）：

- 每个检测器都公开自己的**计分标准**——每个检查项所有可能的结果及其分数——Web 界面在
  「**计分标准**」中展示。
- **维度得分**是其各检测器得分的平均值（权重相同）。「高/严重」发现会强制判为**失败**，
  「中」发现会把**通过**提升为**警告**，与分数无关。报告在 **Dimension details** 中按维度解释这一过程；
  Web 界面中「**逐项体检**」的每一行都可展开查看同样的细节。
- **综合健康分**是已运行维度的加权平均（权重见上表），评级为 A（≥ 90）、B（≥ 80）、
  C（≥ 70）、D（≥ 60）或 F。
- **风险结论**由发现的严重程度决定，而不是由分数决定：

| 风险 | 界面中的名称 | 条件 |
|---|---|---|
| `inconclusive` | 信号不足 | 没有可用于判定的结果：模型身份、上下文窗口和能力声明运行了但都未得出可用结果（中转站不可达、模型不在知识库中），或除连通性外没有任何维度得出可用结果 |
| `high` | 货不对板 | 出现「严重」发现；或核心维度中出现「高/严重」发现；或出现两个及以上「高」发现 |
| `medium` | 存在偏离 | 核心维度之外恰有一个「高」发现，或核心维度中出现「中」发现 |
| `low` | 基本可信 | 其他任何「中」发现 |
| `clean` | 一致（疑似真货） | 以上都不满足 |

连通性维度的发现从不抬高风险：中转站宕机或限流只说明无法评估，并不能证明它换了模型。
结论的**置信度**（低 / 中 / 高）随得出结果的核心维度数量、是否使用基线以及 LLM 裁判而提高。

传输类提示——明文 HTTP（`security.tls`）以及负载下的失败或慢尾（`reliability.*`）——会降低所在维度的分数，但同样不会抬高换模型风险；摘要会把它们列为提示。响应被篡改和 API 密钥被回显仍会抬高风险。指向本机或私有网络的明文 HTTP 只是低严重度警告，因为密钥不会离开该网络。
只经模糊（fuzzy）匹配到的知识库档案会把置信度限制为低；拿不到任何可用回答的检测器结果为无法判定，绝不算通过。

## 套件（suite）

| 套件 | 检测器 | 成本 |
|---|---|---|
| `smoke` | connectivity、security | 很低 |
| `standard` | + protocol、protocol_request、protocol_response、model_identity、capability、streaming、billing、reliability | 低–中 |
| `deep` | + context_window、determinism、vision、injected_prompt、integrity、prompt_cache、performance、quality_judge（需 `--judge`） | 较高（长上下文和计时探测会消耗 token） |
| `full` | 与 `deep` 相同的检测器，性能在流式和非流式下各测一遍 | 最高 |
| `custom` | 只运行你选择的维度，深度同 `deep` | 取决于所选维度 |

上下文窗口探测受 `--max-context-tokens`（默认 200K）限制，因此审计 1M token 的模型也不会太贵。
`--only` / `--skip` 可按 id 单独运行或跳过某些检测器。
大于 `--max-context-tokens` 上限的窗口会报告为*已验证至上限*，绝不会报告为被截断。

### 自定义套件

只运行你关心的维度，节省时间和 token。每个所选维度下的所有检测器都会以 `deep` 深度运行：

```bash
zing check --base-url ... --model gpt-4o -D protocol -D performance
zing check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` 可重复或用逗号分隔，并隐含 `--suite custom`；配置文件中使用
`run.dimensions: [protocol, performance]`。可选维度为 `connectivity`、`protocol`、
`context_window`、`model_identity`、`capability`、`streaming`、`billing`、`reliability`、
`security` 和 `performance`。Web 界面中，`custom` 套件按钮会在检测页、控制台和监控中打开
同样的选择（**检测维度**）。

**综合分只按所选维度加权平均**；未选的维度标为「未选择」。风险结论同样只基于所选维度：
未选择模型身份时，结论只涵盖所选维度，不说明实际提供的是哪个模型，并会注明这一点。

## 性能

每份报告都包含一个 **performance** 部分：延迟、首 token 时间（TTFT）、解码与端到端 tokens/s、
块间延迟与抖动、错误/超时/429 比率、网络拆解（TCP 连接、TLS、一次 `GET /models` 往返、
服务端耗时）以及冷启动，每项都给出 count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev。

运行专用探测时，它会为**性能表现**维度计分。分数衡量的是**稳定性**而非绝对速度，因此慢但稳定的
端点（本地或自托管模型）不会因为不是数据中心而被扣分：

| 检查项 | 计分依据 |
|---|---|
| 延迟 / TTFT 稳定性 | 尾部比 p90 ÷ p50（≤ 1.3 平稳 100 · ≤ 1.75 稳定 85 · ≤ 2.5 波动明显 65 · 更高：极不稳定 40）；至少需要 10 个样本 |
| 吞吐稳定性 | tokens/s 的尾部比 p50 ÷ p10，分档相同 |
| 错误 | 失败的探测请求：≤ 2% 100 · ≤ 10% 80 · 更高：50（429 不计入） |
| 负载稳定性 | 突发时 p50 延迟 ÷ 顺序 p50：≤ 1.5x 100 · ≤ 3x 80 · 更高：55 |
| 缓存命中 | 唯一提示词却由缓存作答：60 |
| 参考值 | tokens/s 与可信基线对比，没有基线时与知识库中该模型公布的范围对比：相符 100 · 更慢：不计分（仅作提示，不算失败）· 快 2 倍及以上 60（暗示是更小的模型）· 无参考值：不计分 |

性能发现的严重程度最高为「低」：它们影响分数，但从不影响风险结论。没有探测时
（`standard` 且无基线，或 `smoke`），该维度不运行，也不计入综合分。

- **standard** 从检测自身的请求中收集性能数据。
- **deep / full / custom** 额外运行专用探测：100 个不可缓存的请求，每个输出 128 个 token
  （每个提示词都以随机请求 id 开头；不发送任何缓存或推理参数），外加一次并发度为 `--concurrency`
  的突发。可用 `--performance-requests`（0 表示关闭）和 `--performance-max-tokens` 调整。
- 探测默认使用流式；`--performance-non-streaming`（或 Web 界面中的**流式 / 非流式**开关）
  可测量不支持流式的中转站。**full** 会交替测量两种模式并并排展示。
- **compare** 在两个端点上交替发送请求运行探测，并增加一张「目标 vs 基线」对照表
  （`standard` 下每侧 5 个请求，不足以进行稳定性检查），目标更好的差异以绿色 ✓ 标出，
  更差的以红色 ✗ 标出。

token 会计数两次——取自中转站的 `usage` 和本地计数——因此即使缺少 `usage` 也能测量吞吐。
本地计数是内置启发式方法的估算值（约 ±15-20%；不使用也不下载任何分词器），该部分始终会注明这一点。
只有样本足够时才显示对应分位数（p90 需 10 个，p95 需 20 个，p99 需 100 个）。JSON 报告保存
每个请求的耗时（只有数字，没有文本）；HTML 报告和 Web 界面会把它们画在检测时间轴上。

在 `zing serve` 中同时运行的检测（多个浏览器标签页、监控）不会相互扭曲计时：CPU 密集的准备工作
（例如构建较长的上下文窗口提示）在服务器的事件循环之外运行。

**请求超时。** `timeout_sec`（`--timeout`，默认 60 秒）是基础值；每个请求会按提示长度和
输出预算额外加时，因此较长的上下文窗口探测或较慢的自托管模型不会在一分钟后被切断。
本地和私有地址（`localhost`、`127.x`、`192.168.x`、`host.docker.internal` 等）至少有
300 秒。`max_request_sec`（`--max-request-time`，默认 900 秒）是单个请求（含流式）的
硬上限，任何请求都不会无限挂起。仍然超时的上下文窗口探测记为“不确定”，而不是截断。

## 对比模式与 LLM 裁判

zing 有两种检测模式：

- **纯代码（默认）：** 除 `quality_judge` 外，所有检测器都由确定性代码判定——指纹、上下文扫描、
  计费算术、流式计时。不需要第二个模型，结果可复现。
- **代码 + LLM 混合（`--judge`）：** 额外请一个*可信*的裁判模型（单独配置，绝不是被测目标）
  判断目标的回答是否像所声称的模型——质量、推理深度这类纯代码难以判定的模糊信号。
  这就是 `quality_judge` 检测器。

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

**对比模式**（`zing compare`，或 Web 界面中的**对照可信基线**）在同一时间用完全相同的探测
去打一个所声称模型的可信基线。这是最有力的确认手段：身份回答、被拒绝的请求参数、篡改金丝雀和
性能都会并排比较，而且只有使用基线时，结论的置信度才可能达到*高*。未指定 `--judge-base-url` 时，
对比模式会把基线用作裁判。

## 持续监控

中转站今天可能提供真货，下周就悄悄换掉。`zing watch` 按计划重新检测，把每次运行记录到
检测历史，并在风险越过阈值或相比上一次**恶化**时通知 Webhook。

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang zh                                     # 或用 --once 配合 cron
```

告警会按 **Slack / 飞书 / 钉钉 / 通用 JSON** 格式化（根据 Webhook URL 自动识别），并使用
告警语言撰写——默认英文；`--alert-lang en|zh|fr|es|pt|it|de`。通用 JSON 负载的键和机器值
（`risk_level`、`score` 等）保持语言中立，面向人阅读的值（`text`、`headline`、`key_findings`）
会被翻译，并注明 `language`。

**在 Web 界面中**，`zing serve` 在服务进程内的后台调度器中运行同样的监控，把每次运行存入
**检测历史**，并发送同样的 Webhook 告警：

- **新界面：** 在**检测历史**中打开一次运行，选择**设为监控**。zing 会把该次运行的配置
  （中转站、模型、声称的模型、厂商、套件、自定义维度）复制成**监控**页面上一个已暂停的监控；
  在那里设置间隔和 API 密钥（检测历史从不保存密钥）并启用。间隔、密钥、**告警阈值**、
  Webhook 和**告警语言**都可以在每个监控上直接修改。
- **经典界面：** 在**监控**页面填写表单，然后点击**添加监控**。

每个监控都有自己的告警语言（默认跟随界面语言），可以立即运行、暂停或删除，并固定使用创建时的
知识库画像，直到你重新固定。

到期的监控会同时运行，每个都是一次独立的检测，但同一中转站主机同一时刻最多只有一个检测，总数最多为
`ZING_MAX_PARALLEL_AUDITS`；运行会等待空闲名额（你手动启动的检测也可能排在运行中的监控之后）。
一次运行的时间是其检测开始的时刻（在任何等待之后）。判断是否恶化时，与同一中转站和模型最近一次保存的运行比较，
无论此后又保存了多少其他运行。一次运行的告警 Webhook 会同时发送，因此一个缓慢或失效的 Webhook
不会拖住其他 Webhook。密钥加密保存在本地数据目录中，绝不会返回给浏览器。

**主密钥。** 监控的 API 密钥用一个主密钥加密，zing 从不把主密钥写入磁盘。你第一次保存 API 密钥时，
**监控**页面会创建主密钥并只显示一次：复制或下载它，保存在密码管理器中（浏览器也可以保存），再粘贴回来确认。
每次重启 `zing serve` 后页面都会再次请求它（浏览器可以自动填入）；在此之前，需要它的监控会等待，
而没有密钥或使用 `env:`/`file:` 密钥的监控照常运行。页面上的状态栏还提供**锁定**、**更换**和
**忘记了密钥？**（丢弃已加密的 API 密钥，以便你重新输入）。无人值守或 Docker 部署时，
用 `ZING_SECRET_KEY` 传入主密钥（见 [docs/DOCKER.md](docs/DOCKER.md)）；命令行中用
`zing secret status | export | rotate` 管理它。

## Embedding、rerank、图像与音频检测

这些端点返回的是向量、排序、图像或音频，而不是对话，因此 zing 用独立的专用检测器来审计，
而不走十维度的对话流水线。每个都会输出结论，并支持 `--json` 和 `--fail-on-risk`。

### Embedding 与 rerank

```bash
# 期望的向量维度会根据声称的模型从知识库中解析。
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# 或直接指定期望维度：
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank：内置一个答案已知的探测——真正的 reranker 必须把明显相关的文档排在第一。
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

`embed` 检查连通性、**维度匹配**（返回向量的长度 vs 声称模型的原生维度——最核心的
「货不对板」信号：声称是 3072 维 `text-embedding-3-large`、却返回 1024 维的中转站，提供的是替代品）、
确定性（相同输入 → 余弦 ≈ 1）、区分度（无关输入 → 余弦明显小于 1）以及回包中的 `model` 字段。
内置画像：OpenAI `text-embedding-3-small`（1536）、`text-embedding-3-large`（3072）、
`text-embedding-ada-002`（1536），Qwen `text-embedding-v3`/`-v4`（1024）。

两者也都在 Web 界面的**工具**页面中（**嵌入审计**、**重排审计**），在那里还可以用你自己的
查询和文档替换 rerank 探测。

### 图像与音频（TTS）生成

图像生成（`POST /v1/images/generations`）和文本转语音（`POST /v1/audio/speech`），
只用 Python 标准库解码——从文件头字节读取图像尺寸（PNG/JPEG/GIF/WebP），用 `wave` 读取 WAV 时长。

```bash
# 声称是 DALL·E 3 的中转真的返回了所请求的 1792x1024 吗？被缩小 / 尺寸错误的图像
# （或尺寸不在知识库中声称模型的原生尺寸内）就是最核心的「货不对板」信号。
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# 声称是 tts-1-hd 的中转返回的是时长随输入增长的真实音频吗
# （而不是固定的占位音频，也不是伪装成音频的 HTML/JSON）？
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` 检查连通性、格式有效且可解码、**尺寸匹配**（解码出的宽 × 高 vs 请求尺寸和声称模型的
原生尺寸——不匹配即 FAIL/HIGH）、区分度（两个提示词 → 不同的图像，识破固定占位图）、数量以及
`model` 字段。`audio` 检查连通性、容器/格式有效性、格式是否被遵守、随输入增长的非平凡时长、
区分度以及 `model` 字段。知识库包含 OpenAI DALL·E 2/3、gpt-image-1、
tts-1/tts-1-hd/gpt-4o-mini-tts，以及 Qwen 的图像/TTS 画像。

## 在 CI 中使用（GitHub Action）

用内置的复合 Action 给任意工作流加上中转站审计门禁。它运行
`zing check --compact --fail-on-risk`，把 `risk` / `score` / `rating` 作为输出，
向运行写入摘要，并在风险门禁触发时让任务失败。

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.20.0         # 固定到发布标签
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # 调用方的密钥；绝不回显
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

中转站密钥通过环境变量传递（`--api-key env:…`），因此绝不会出现在命令行上。完整的输入/输出
和部署门禁示例见 [docs/CI.md](docs/CI.md)。

## 知识库

zing 依据所声称模型的**画像**来评判中转站：原生上下文窗口、最大输出、知识截止日期、分词器、
能力标记、身份关键词和行为指纹。内置画像覆盖 OpenAI、Anthropic、Google Gemini、DeepSeek、
Qwen、GLM 和 Moonshot（用 `zing kb` 查看）。共有三层，后面的优先：

1. **内置**画像，每个厂商一个 YAML 文件，位于 [`zing/knowledge/data/`](zing/knowledge/data)。
2. **你自己的 YAML 目录**：`--kb-dir ./my-profiles`（可重复）或 `ZING_KB_DIR`。
3. **你的条目**（数据目录中的 `kb.db`），无需 YAML 文件或可编辑安装即可添加：
   - 在 Web 界面的**知识库**页面（`/v2/kb`），分为**模型**、**厂商**、**中转站**三个标签页。每个标签页
     列出完整集合——内置的、`ZING_KB_DIR` 的和你的（标记为**你的**）——提供筛选、每项的启用/停用开关
     和**添加…**表单：**添加模型** → **复制调研提示词**，粘贴到你选用的 AI 助手中，上传或粘贴它回复的
     YAML，然后**检查并保存**；**添加厂商**以同样方式接收厂商 YAML；**添加中转站**只需名称和基础地址。
     **某个模型 ID 会使用哪份资料？**显示某个 id 如何解析；你的条目可导出为 YAML；
   - 在 Web 界面的**检测**和**工具**页面：**保存到知识库**会保存中转站的名称和基础地址（一个不含模型的
     厂商条目），列在**知识库 → 中转站**中；
   - 在命令行：`zing kb-prompt <model>`、`zing kb-import <file>`（加 `--check` 只检查不保存）
     和 `zing kb-export`。

保存条目前 zing 会先检查：结构与限制、不安全的正则表达式、它将发送的每条提示词，以及会解析到
其他画像的模型 id。你的模型若与内置模型 id 相同，会替换内置模型（报告为*遮蔽*了它），但绝不会
修改内置厂商自身的设置；指纹按 id 合并。在**知识库**页面停用内置模型、厂商或中转站同样保存在
`kb.db` 中：停用的模型 id 不再参与解析，停用的厂商会连同其模型和基础地址一起停用。`zing check`
与 `zing serve` 使用完全相同的画像；`--no-user-kb`（或 `ZING_NO_USER_KB=1`）会排除你的条目和开关。

`identity_keywords` 为空的模型不会原样保存：zing 会根据厂商与模型名称补上它自己的品牌词
（例如 `glm` 和 `z.ai`），并显示一条警告提醒你核对；没有这些词，身份检查
可能把模型说出的自家厂商当成竞品品牌。研究提示词也会明确要求 AI 助手给出这些词。

每份报告都会记录它对照的画像（`knowledge`：厂商、模型、id 如何匹配、来源，以及带内容哈希的
完整快照），因此即使知识库之后发生变化，报告依然可以核验。

## 报告

`zing check` 和 `zing compare` 会输出结论，并把报告以 JSON、Markdown、HTML 和 PDF 写入
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

## 隐私与本地数据

- **仅限本地。** `zing serve` 只监听回环地址（`127.0.0.1`、`::1`、`localhost`），只响应这些主机名，
  并拒绝跨站请求；它没有登录，因为你的机器之外没有任何东西能访问它。zing 只会联系你配置的端点
  （目标、基线、裁判、Webhook）；运行时不下载任何东西，连分词器文件也不下载。
- **密钥。** 报告和检测历史只保存 API 密钥的指纹。监控的密钥加密保存在 `watches.db` 中；
  用于解密的主密钥从不写入数据目录（由你保管，见上文**持续监控**），因此目录的副本不会泄露任何 API 密钥。
  该目录仍然仅对你本人可访问。
- **数据目录。** `~/.zing`（或 `ZING_DATA_DIR`），以 `0700` 创建，文件为 `0600`：
  `history.db`（检测历史）、`watches.db`（监控，含加密后的密钥）和 `kb.db`（你的知识库条目）。
  删除该目录即可清除全部数据。
  `zing data-dir` 会显示它的位置；`--data-dir 路径` 可为单次运行另选目录，例如
  `zing serve --data-dir .` 把数据库放在当前文件夹。它们是普通的 SQLite 文件，可自行打开分析
  （zing 运行时最好只读打开）。如果该文件夹是代码仓库，请勿提交 `watches.db`。
  `history_metrics` 每次运行存一行测量值，`history_requests` 存每条请求记录（只在那里存一份，
  不再放进每份报告）。

## 负责任使用

zing 是黑盒审计辅助工具。它**无法证明**：

- 某个服务商存储了你的提示词或用其训练，
- 它始终路由到同一个确切的模型（中转站可以按概率路由），
- 超出独立 token 估算所能提示范围的计费欺诈。

请把报告用于你自己的尽职调查。**不要仅凭单次运行就公开指控某个服务商**，而不去审视样本量、
成本设置和当地法律。在得出强结论之前，请先用 `zing compare` 对照可信基线运行。

## 更多文档

| 文档 | 用途 |
|---|---|
| [方法论](docs/METHODOLOGY.zh-CN.md) | 每项检测如何工作、它的计分标准和注意事项 |
| [开发者指南](DEVELOPER_GUIDE.zh-CN.md) | 架构、开发环境、贡献、翻译、Docker、发布 |
| [docs/CI.md](docs/CI.md) | GitHub Action：输入、输出、示例（英文） |
| [docs/DOCKER.md](docs/DOCKER.md) | 在容器中运行 Web 界面（英文） |
| [CHANGELOG.md](CHANGELOG.md) | 每个版本的变更（英文） |
| [SECURITY.md](SECURITY.md) | 报告安全漏洞（英文） |

## 许可证

[Apache-2.0](LICENSE)
