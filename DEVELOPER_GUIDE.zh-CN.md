# ekte — 开发者指南

> [🇬🇧 English](DEVELOPER_GUIDE.md) · **🇨🇳 中文** · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md) · [🇳🇴 Norsk](DEVELOPER_GUIDE.nb.md)

本指南面向修改 ekte 的人：它是如何构建的、如何搭建开发环境、如何参与贡献，以及如何打包、
在 Docker 中运行和发布。ekte 能做什么、如何使用，见 [README](README.zh-CN.md)；
每项检测如何工作、如何计分，见[方法论](docs/METHODOLOGY.zh-CN.md)。

---

## 目录

- [原则](#原则)
- [开发环境](#开发环境)
- [仓库结构](#仓库结构)
- [架构](#架构)
  - [一次检测的流程](#一次检测的流程)
  - [客户端](#客户端)
  - [检测器与计分标准](#检测器与计分标准)
  - [计分与结论](#计分与结论)
  - [知识库](#知识库)
  - [提示词库](#提示词库)
  - [报告](#报告)
  - [接口类型（surface）](#接口类型surface)
  - [独立审计器](#独立审计器)
  - [Web 服务](#web-服务)
  - [HTTP API v1](#http-api-v1)
  - [Web 前端](#web-前端)
  - [本地数据](#本地数据)
- [参与贡献](#参与贡献)
  - [Pull Request](#pull-request)
  - [新增检测器](#新增检测器)
  - [编辑知识库](#编辑知识库)
  - [保持知识库最新](#保持知识库最新)
  - [修改探测提示词](#修改探测提示词)
  - [修改数据库模式](#修改数据库模式)
  - [翻译](#翻译)
  - [文档](#文档)
- [测试](#测试)
- [Docker](#docker)
- [持续集成](#持续集成)
- [发布](#发布)
- [安全](#安全)
- [许可证](#许可证)

## 原则

ekte 是黑盒审计辅助工具：正确性以及**不冤枉诚实的中转站**，比抓住每一种可能的作弊手法更重要。
任何改动都请牢记这条标准。

- **证据优先，不做指控。** 发现只报告*偏离与风险*，从不说「欺诈」。宁可*不确定*，也不要猜测。
  新增的「高」严重度路径需要确凿、可复现的证据，并且很难在诚实端点上被触发。
- **测试不联网。** 检测器测试针对 `tests/conftest.py` 中的进程内模拟服务
  （httpx `MockTransport`）运行，绝不访问真实 API。
- **密钥不外泄。** API 密钥只保留指纹，绝不写入报告。任何新的输出路径都必须让中转站控制的文本
  经过 `ekte.utils.redact`，并按输出格式进行转义。
- **对所有人使用相同的探测。** 探测文本固定为英文，与界面语言无关，这样同一个中转站总会得到
  同样的结论（见[提示词库](#提示词库)）。
- **仅限本地。** ekte 只联系用户配置的端点，Web 界面只监听回环地址（见 [Web 服务](#web-服务)）。

## 开发环境

需要 Python 3.11+。CI 在 Linux、macOS 和 Windows 上测试；仅在 POSIX 上有意义的测试在 Windows 上带明确原因跳过（`skipif(sys.platform == "win32", reason=...)`）。请使用 `pathlib`，文本 I/O 指定 `encoding="utf-8"`，不要写死 `/tmp`。Node.js 可选：浏览器 JavaScript 的测试在 `node` 下运行，没有 Node.js 时跳过。

```bash
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e '.[dev,web]'   # 以可编辑模式安装开发工具和 Web 界面
pytest                        # 测试套件
ruff check ekte tests         # 代码检查
mypy ekte                     # 类型检查
```

使用 uv：`uv venv && uv pip install -e '.[dev,web]'`。无需任何系统库，PDF 报告也不例外。

从源码运行：`ekte …` 或 `python -m ekte …`。`ekte serve` 直接从 `ekte/web/static/` 提供
Web 界面，刷新浏览器即可看到前端改动；没有构建步骤。

## 仓库结构

```text
ekte/
  cli.py               Typer 命令行：check、compare、models、kb*、serve、watch、embed、rerank、image、audio
  config.py            YAML 配置、密钥引用（env:/file:）、AuditOptions
  runner.py            run_audit()：组装一切并运行检测器
  context.py           传给每个检测器的 AuditContext
  models.py            pydantic 数据契约：TargetConfig、Finding、DetectorResult、AuditReport 等
  scoring.py           维度得分、权重、综合健康分、风险结论、置信度
  clients/             HTTP 客户端：OpenAI 兼容、Anthropic Messages、OpenAI Responses
  detectors/           每个检测器一个文件，另有 base.py（注册表）、scale.py、helpers.py
  judge/               quality_judge 使用的可信 LLM 裁判
  knowledge/           画像结构、加载器、用户存储（kb.db）、导入、调研提示词、快照
    data/              内置厂商画像（*.yaml）
  prompts/en.json      ekte 发给 LLM API 的全部文本
  perf/                逐请求记录与报告中的性能部分
  report/              JSON / Markdown / HTML / PDF 渲染与写出
  embed_audit.py       独立的 embedding 与 rerank 审计器
  media_audit.py       独立的图像与音频（TTS）审计器
  notify.py            Webhook 告警（Slack / 飞书 / 钉钉 / 通用 JSON）
  datadir.py           本地数据目录及其 SQLite 文件
  legacy.py            改名前的 ZING_* 设置与 ~/.zing 的复制
  secretbox.py         已保存机密的加密；内存中的主密钥
  i18n/                Web 界面与告警共用的翻译
    locales/           每种语言一个 <code>.json，以及 fragments/<feature>/<code>.json
  utils/               脱敏、SSE 解析、统计、token 估算
  web/
    server.py          FastAPI 应用：页面、JSON API、SSE 检测流、监控调度器
    jobs.py            后台检测任务与按中转站的互斥
    security.py        回环绑定、Host 白名单、Origin/JSON 校验、安全响应头
    history.py         检测历史存储（history.db）
    analytics_store.py 其分析表：每次运行的指标、请求记录
    analytics.py       分析查询：关键指标、时间序列、排行榜
    watches.py         监控存储（watches.db）
    masterkey.py       主密钥的状态与操作（服务器与 `ekte secret`）
    static/            所有页面共用的脚本（lang.js、i18n.js、icons.js 等）
    static/v2/         Web 界面的页面、样式和脚本
tests/                 pytest 测试套件；conftest.py 中是模拟中转站
docs/                  METHODOLOGY（8 种语言）、CI.md、DOCKER.md、PUBLISHING.md
examples/ekte.yaml     带注释的配置文件
action.yml             GitHub 复合 Action
Dockerfile             Web 界面镜像
```

## 架构

### 一次检测的流程

`ekte check`、`ekte compare`、`ekte watch`、Web 界面的检测流及其监控调度器，最终都进入
同一个函数 `ekte.runner.run_audit()`：

1. **配置。** `ekte/config.py` 把 YAML 配置与命令行选项合并为 `TargetConfig`（目标，
   以及可选的基线和裁判）和 `AuditOptions`（套件、维度、探测规模、输出）。以 `env:VAR`
   或 `file:/path` 给出的 API 密钥在这里解析。
   格式定义在 `ekte/configfile.py` 中（一张包含键、类型和默认值的表），并发布为 JSON 模式 [`docs/schemas/config.schema.json`](docs/schemas/config.schema.json)，用 `uv run python -m ekte.configfile` 重新生成（模式过期时测试会失败）。`ekte/config.py` 通过它加载文件，因此每个命令都会校验。格式变更需要新的 `CURRENT_VERSION`、`RENAMES_FROM` 中的重命名（供 `ekte config migrate` 使用）和更新日志条目；已弃用的键连同其替代键放入 `DEPRECATED`。参见[稳定性策略](docs/STABILITY.md#surface-config)。
2. **知识库。** `load_knowledge_base()` 加载内置画像、`--kb-dir`/`EKTE_KB_DIR` 和用户的
   `kb.db`，并把**声称的**模型（默认即请求的模型）解析为一个画像。监控则改为传入它固定的快照。
3. **客户端。** `make_client()` 按所选或自动识别的协议为目标（及基线）创建客户端。
   `RequestRecorder` 包裹每一次调用，用于性能部分。
4. **检测器。** `select_detectors()` 为套件（或自定义维度）挑选已注册的检测器，并去掉缺少
   裁判或基线时无法运行的那些。它们**依次**运行，这是有意为之：并发请求会触发限流并干扰计时
   测量（可靠性和性能探测会自行控制有限的并发）。`run_detector()` 为每个检测器计时，并把崩溃
   转换为状态为**错误**的结果，因此中转站的异常响应绝不会中断整个检测。
5. **计分。** `scoring.build_dimensions()` 和 `build_verdict()` 把检测器结果转换为维度得分、
   综合健康分与评级、风险结论及其置信度。
6. **报告。** 一切汇总到一个 `AuditReport`（`ekte/models.py`）中，包括脱敏后的目标、知识库画像
   快照、性能部分和探测语言。命令行负责渲染并写出；Web 界面则把它流式推送。

`run_audit()` 接受一个 `on_event` 回调；Web 服务把它的事件（检测器开始/结束及精简的发现、
批量的逐请求耗时）转换为 Server-Sent Events，用于实时视图。

### 客户端

`ekte/clients/` 为每种协议提供一个客户端——`openai_compatible.py`（Chat Completions）、
`anthropic.py`（Messages）和 `responses.py`（Responses）——接口相同，都构建在 `base.py`
的共用 HTTP 机制之上。`clients/__init__.py` 中的 `make_client()` 根据 `--api` 选择，
或根据 base URL 和模型自动识别。检测器只与这一接口打交道（输入 `RequestSpec`，
输出 `CompletionOutcome`），因此与协议无关。

客户端还会让请求适应模型所接受的参数（`base.py`）：runner 根据画像填入
`unsupported_params`，其中所列的采样参数会被省略；在 Chat Completions 上，若列有
`max_tokens`，则以 `max_completion_tokens` 发送上限。4xx 若点名此类参数，会将其加入该
集合，并把请求调整后重发一次（被拒绝的尝试以阶段 `param_retry` 记录）。评判未经调整的
拒绝的探测会设置 `RequestSpec.exact_params`。

### 检测器与计分标准

一个检测器就是 `ekte/detectors/` 中一个自包含的文件：继承 `Detector`（`base.py`），
定义 `id`、`name`、`dimension`、首次运行的套件（`min_suite`）、供 `--dry-run` 使用的大致
`cost_hint`，以及 `async def run(self, ctx) -> DetectorResult`。`@register` 把它加入注册表；
`ekte/detectors/__init__.py` 导入每个模块，保证注册表完整。

每个检测器都公开自己的**计分标准**（`SCALE`，由 `scale.py` 构建）：每个检查项所有可能的结果，
及其分数、状态和严重程度。发现都由计分标准生成（`SCALE.finding(check, outcome, …)`），
因此报告与实际行为不可能不一致。`Scale` 取各检查项的平均分；`DeductionScale` 从 100 开始扣分
或设上限。Web 界面在「**计分标准**」中展示它；[方法论](docs/METHODOLOGY.zh-CN.md)收录了
每一份计分标准。`connectivity.py` 是最短、最标准的示例。

在 `ekte serve` 中，检测器与其他所有检测共用一个事件循环，因此 CPU 密集的工作不能在其上运行：
事件循环一旦卡住，就会拖延其他检测的请求，并让它们记录的延迟虚高。`helpers.build_filler()`
以线性时间构建填充文本，并缓存最近几种长度的结果；上下文窗口和提示缓存检测器通过
`asyncio.to_thread` 调用它（以及 `build_haystack()`）。token 计数来自 `ekte/utils/tokenize.py`，
一个只用标准库的启发式方法：ekte 不导入任何分词器库，运行时也不下载任何东西，因此在受限环境中
同样可以运行。`estimate_tokens()` 的 `tokenizer` 参数仍被接受，但不会改变计数；报告字段
`tokens_exact` / `exact_tokenizer` 为兼容而保留，始终为 false。

### 计分与结论

`ekte/scoring.py` 定义了 `DIMENSION_WEIGHTS` 和结论规则：维度得分是其各检测器得分的
平均值（权重相同），综合健康分是已运行维度的加权平均，风险等级遵循
[方法论 → ekte 如何计分](docs/METHODOLOGY.zh-CN.md#ekte-如何计分)中描述的严重程度阶梯。
每个维度都在 `DimensionScore.breakdown` 中记录计算过程，报告中的 **Dimension details**
和 Web 界面「**逐项体检**」的可展开行都由它生成。

### 知识库

`ekte/knowledge/` 定义画像结构（`schema.py`：`ProviderProfile`、`ModelProfile`、
`FingerprintProbe`），加载并合并各层（`loader.py`：内置 YAML → `EKTE_KB_DIR`/`--kb-dir`
→ 用户的 `kb.db`），保存用户条目（`store.py`），检查并导入 YAML（`importer.py`），
生成供外部助手使用的调研提示词（`research.py`），并为一次运行所用的画像拍快照（`snapshot.py`）。
模型 id 依次按精确 id、别名或规范化名称解析，并由声明的厂商缩小范围。模糊匹配取所声称 id
中包含的最长知识库名称（快照或带修饰的 id），除非其余部分指向另一个档位或变体（`-mini`、
`-lite`、`-image` 等）；截断形式的 id 只有在恰好一个模型的名称以它开头时才会解析，因此像
`gpt-4` 这样有歧义的 id 不会匹配任何画像，而不是被猜成某个档位。每份报告都会记录 id 是如何
匹配的。

`load_knowledge_base()` 会缓存合并结果，默认返回一份深拷贝，因此调用方可以修改拿到的结果。
只读取它的调用方（Web 界面的列表和目录、解析模型）传入 `copy=False`，拿到共享的缓存实例，
它们不得修改这个实例。

中转站也是端点：`relays.py` 把厂商的 `base_url_hints` 转换为可用的基础地址（`GET /api/kb` →
`base_urls`），并把 Web 界面中保存的中转站作为厂商条目写入 `kb.db`（`origin = relay`：一个
`display_name` 和一个基础地址，不含模型；无需修改结构）。

### 提示词库

ekte 发给 LLM API 的每一段文本——对话探测、裁判提示词、工具 schema、embedding / rerank /
图像 / 音频输入——都在 `ekte/prompts/en.json` 中，通过 `ekte.prompts.text()` / `get()` 读取。
`{{name}}` 表示运行时填入的值。探测语言固定为英文（`PROBE_LANG`），与界面语言无关，
因为答案校验和 token 估算都针对这些确切文本校准过。语言本身就是测量对象的探测（例如中国
原生模型的中文流畅度、分词器或自我身份识别）连同期望答案放在知识库中，并声明 `prompt_lang`
和 `language_bound` 理由。runner 会把实际使用的语言记录在 `prompt_languages` 中。

### 报告

`ekte/report/render.py` 把 `AuditReport` 渲染为 JSON、面向 Agent 的精简 JSON、Markdown 和 HTML；
`dimensions.py` 和 `performance.py` 渲染 **Dimension details** 和性能部分；`pdf.py` 用
ReportLab 基于同样的数据和辅助函数排版 PDF（纯 Python；只使用 PDF 标准字体，中文用 CID 字体
STSong-Light，因此不嵌入任何字体；绝不加载外部资源），命令行和 Web 界面共用它；`writer.py` 负责写文件。
所有由中转站控制的文本在输出前都会脱敏并转义（HTML / Markdown）。Web 界面的
`POST /api/report/export` 复用这些渲染器来实现**下载报告**，并把面向人阅读的文本翻译成界面语言。

### 接口类型（surface）

**surface** 是被审计端点的类型：`chat`（默认）、`embedding` 或 `rerank`（`ekte.config.SURFACES`；
以后还有图像、TTS）。它是与测试套件并列的第二个维度，由 `AuditOptions.surface`、`AuditReport.surface`
以及 `history.db` 和 `watches.db` 中可为空的 `surface` 列承载（`NULL` 和缺失的 JSON 字段都表示
`chat`；无需迁移）。

- 检测器声明 `surface: ClassVar[str]`；`select_detectors` 先按它筛选，再按套件层级筛选。嵌入和重排
  检测器复用现有维度。
- 评分权重以及画像 / 核心 / 基础设施维度集合按 surface 区分（`scoring.SURFACE_WEIGHTS`）；对话保持原值。
- 记录器把嵌入调用标为 `op="embed"`，重排调用标为 `op="rerank"`（`ekte.config.SURFACE_OPS`）；
  `perf/summary.py` 中的函数接受 `op` 参数（默认 `complete`）。
- `embed_audit.run_embedding_audit()` 和 `run_rerank_audit()`（供 `ekte embed` / `ekte rerank` 使用）以 `surface="embedding"` 或 `"rerank"` 运行 runner，把同一 surface
  上一次已保存的运行作为 `previous_report`（漂移）传入，并保存报告（`--no-save` 时不保存）。
- 重排检测器：`rerank.connectivity`、`rerank.known_answer`（CAPABILITY）、`rerank.identity` 和
  `rerank.drift`（MODEL_IDENTITY）、`rerank.determinism`（RELIABILITY）以及 `performance.rerank`。
  权重：MODEL_IDENTITY 30、CAPABILITY 30、PERFORMANCE 20、RELIABILITY 10、CONNECTIVITY 10。
- 监控：监控的 `surface` 和 `embedding_dimensions`（0 = 取自知识库）在 `_run_one_watch_inner` 中写入
  `AuditOptions`；嵌入或重排监控在审计前用 `history.latest_for(..., surface=...)` 读取漂移参照，
  告警只与同一 surface 的运行比较。surface 在创建时确定（`POST /api/watches`、
  `/api/watches/from-history/{id}`，后者也接受 `embedding_dimensions`），`PATCH` 不能修改；`PATCH`
  可以修改嵌入监控的 `embedding_dimensions`（v2 监控卡片可直接编辑）。

### 独立审计器

图像/音频（`media_audit.py`）还不是 surface，因此各有自己的小型审计器和结论，而不走检测器流水线。它们
共用客户端的 HTTP 设置、知识库（原生维度、图像尺寸、音色）和提示词库。所有解码（图像文件头、WAV）只
使用标准库。

### Web 服务

`ekte/web/server.py` 是由 `create_app()` 创建的 FastAPI 应用：

- **页面。** Web 界面（`/`、`/history`、`/watches`、`/analytics`、`/kb`、
  `/accessibility`）是在根路径提供的静态 HTML，脚本和样式位于 `/static/`。没有工具页面：嵌入和
  重排检测从检测页面的接口类型选择器开始（`/?surface=embedding|rerank`）。在 1.0.0 之前，以前的地址会连同查询字符串
  重定向（308）到根路径下的页面：`/v2/…`（`/v2/tools` 转到 `/?surface=embedding`，`#rerank` 选择重排）
  以及已移除的经典界面的 `/tools` 和 `/console`。这些重定向已弃用，将在 1.0.0 中移除。
- **API。** `/api/jobs…` 运行检测（见下文）；`/api/models` 列出中转站的模型；
  `/api/report/export` 渲染报告；`/api/history…`、`/api/watches…`、`/api/kb…` 和
  `/api/analytics…` 为其他页面提供服务。 它们均为内部接口；公开子集见 [HTTP API v1](#http-api-v1)。
- **中转站。** `POST /api/kb/relays` 保存中转站 `{name, base_url}`（输入无效时返回 400，名称或地址已存在时返回 409）。
- **分析。** `GET /api/analytics/options`（历史中出现的中转站、模型、套件、流式模式、API 及日期范围）、`/api/analytics/summary`（`from`–`to` 区间的关键指标，并与之前等长区间对比）、`/api/analytics/series`（按 `group=relay|model|relay_model` 给出 `metric`，最多 4 个 `keys`，按查看者时区 `tz` 或 `tz_offset` 划分为 `bucket=hour|day|week|dow_hour` 区间；`dow_hour` 还接受 `block`（每行小时数）和 `fold=week|4weeks|month_week`，在检测覆盖 90 天或 180 天之前回退为 `week`）以及 `/api/analytics/leaderboard`（`model=` 列出其各中转站，或 `relay=` 列出其各模型）。所有端点都接受筛选参数 `from`、`to`、`suite`、`stream_mode`、`api`、`source=all|manual|monitor`、`relay` 和 `model`。`ekte/web/analytics.py` 基于 `history.analytics_runs()` 在 Python 中完成全部计算：指标 id 来自固定白名单；中转站在查询时按知识库条目分组；某次运行未测得的值不参与计算（每个值都带有 `n` 和 `coverage`）；运行次数少于 `MIN_RUNS`（3）的区间标记为 `low_n`。参数无效时返回 400；响应带 `Cache-Control: no-store`。
- **分析面板。** `/api/analytics/breakdown`（在所选区间内按 `group=relay|model|relay_model|all` 给出最多 8 个 `metrics`）、`/api/analytics/errors`（目标端补全调用按结果类别 `success|client_4xx|rate_limited|server_5xx|timeout|network|other` 统计，按 `group=relay|model` 和 `bucket` 划分，由 `history.analytics_request_classes()` 在 SQL 中计数，不加载请求行；调用时间为所属检测的开始时间加上偏移，精确到分钟；`covered` 为有请求记录的检测次数）以及 `/api/analytics/integrity`（每个「中转站 × 模型」的身份、能力、图像理解、流式、协议、完整性、注入提示词与连通性检测器的通过 / 警告 / 失败次数，模型不符占比，以及实测 / 声明上下文窗口的中位数比例）。`/api/analytics/series` 也接受 `group=all`。筛选与错误处理同上。
- **后台检测。** `jobs.py` 把每次检测作为服务器拥有的任务运行。`POST /api/jobs` 排入一个任务，
  `GET /api/jobs` 列出排队中、运行中和刚结束的任务（以及运行中的监控）及其进度，
  `GET /api/jobs/{id}/events` 先回放任务的事件日志，再通过 SSE 实时跟随，
  `POST /api/jobs/{id}/cancel` 停止任务。Web 界面使用这些接口，因此检测不随页面结束。
  中转站互斥让同一中转站同一时间只运行一项检测（或一次监控运行），按主机名区分，所有回环地址视为同一主机；
  同时最多运行 `EKTE_MAX_PARALLEL_AUDITS`（默认 4）项，等待者按到达顺序执行。
- **监控调度器。** 应用的 lifespan 启动一个后台循环，把每个到期的监控作为独立任务启动，
  因此不同中转站上的监控会同时检测；中转站互斥依然生效，所以监控可能占满
  `EKTE_MAX_PARALLEL_AUDITS` 个名额，手动检测可能排在它们之后。一次运行的 `last_run_ts`
  是其检测开始的时刻（在等待中转站空闲之后）。每次运行都存入检测历史；恶化检查将其与同一目标和
  模型最近一次保存的运行比较（`history.latest_for()`，一次带索引的查询），并在越过阈值或恶化时
  并发发送 Webhook 告警（`ekte/notify.py`）。调度器刚启动某个监控时，
  `POST /api/watches/{id}/run` 返回 409；重置主密钥会取消尚未开始的计划运行，关闭服务会取消
  正在进行的运行。
- **压缩与缓存。** `caching.py` 对 1 KiB 及以上的响应（Server-Sent Events 除外）进行 gzip
  压缩，前提是客户端接受（`gzip;q=0` 表示拒绝）。页面和 `/locales.js` 在生成时只压缩一次，
  以预压缩形式提供，带 `Content-Encoding: gzip`、`Vary: Accept-Encoding` 和一个以 `-gz`
  结尾的独立 ETag；页面通过 `html_page(page, request.scope)` 提供，从而走这条路径，并对条件请求
  返回 304。页面中本地脚本和样式表的 URL 带有 `?v=<content hash>`，作为不可变资源缓存。
- **安全。** `security.py` 决定绑定地址（仅回环地址；只有在检测到容器且设置了
  `EKTE_CONTAINER=1` 时例外），并安装 `LocalOnlyMiddleware`：防 DNS 重绑定的 Host 白名单、
  防 CSRF 的 `Origin` 与 `Sec-Fetch-Site` 校验、只接受 JSON 请求体，以及防嵌入 / 禁止
  MIME 嗅探 / 不发送 Referrer 的响应头。界面有意不设登录。

### HTTP API v1

HTTP API 的公开部分位于 `/api/v1/` 之下，遵循[稳定性政策](docs/STABILITY.md#surface-http-api)：只有在大版本中、经过弃用期后才会发生不兼容的变更。`/api/` 下的其他路径均为内部接口，任何版本都可能变更。内部响应带有 `X-Ekte-API: internal`，v1 响应带有 `X-Ekte-API: v1`。Web 界面使用内部路径。

| 端点 | 请求 | 响应 |
|---|---|---|
| `POST /api/v1/jobs` | JSON 请求体，含 `base_url`, `model`，可选 `api_key`, `claimed_model`, `suite`, `surface`, `dimensions`, `baseline` | 200 及该任务；输入无效时返回 400 |
| `GET /api/v1/jobs/{id}` | 无 | 200 及该任务；id 未知时返回 404 |
| `GET /api/v1/jobs/{id}/events` | 无 | 200 及 `text/event-stream`：该任务迄今的事件，随后实时推送，以 `done` 结束；id 未知时返回 404 |
| `GET /api/v1/history` | 可选 `limit`（1–500，默认 50）和 `perf` | 200 及运行摘要的 JSON 数组，最新的在前 |
| `GET /api/v1/history/{id}` | 无 | 200 及原样保存的报告；id 未知时返回 404 |

任务包含 `id`、`status`（`queued`、`running`、`done`、`error` 或 `cancelled`）、进度字段、报告保存后的 `report_id` 以及 `error`；API 密钥从不返回。每个事件是一行 SSE `data: {JSON}`，带有 `type`；`report` 事件携带报告及其 `report_id`，`done` 始终是最后一个事件。客户端应忽略不认识的事件类型和字段。

每个错误都是只有一个字段 `error` 的 JSON，内容为可读的消息，状态码为以下之一：400（请求无效）、404（未找到）、403（拒绝跨站或跨源请求）、415（请求体不是 JSON）、421（未知主机）。

```json
{"error": "not found"}
```

- **仅限本地。** Web 服务的保护措施同样适用于 `/api/v1/`，与其他所有路径一样：默认绑定回环地址、Host 检查、拒绝跨站写入、请求体仅限 JSON。它们以相同的错误格式响应。

### Web 前端

前端是纯 HTML、CSS 和浏览器 JavaScript，不使用模块，也没有构建步骤。页面位于
`ekte/web/static/v2/`，共用一个页头（`nav.js`）、报告渲染器
（`report.js`）、主题切换（`theme.js`）和样式（`tokens.css`、`ekte.css`、`fields.css`、`report.css`、
`perf.css`）。共用脚本从根路径提供：`lang.js`（语言切换）、`locales.js`（翻译数据）、
`i18n.js`（发现的翻译）、`icons.js`（包括 ekte 标志）、`secretfield.js` 和 `perf.js`（性能图表）。

除无障碍页面外，每个 v2 页面在 hero 正下方都有一条**页面提示**（`<div class="znote" id="note">`，由 `v2/notice.js` 绘制，样式为 `ekte.css` 中的 `.znote`）：`EkteNotice.show(el, {level, title, detail, items, actions})`；级别 `info`、`success`、`warning` 或 `critical` 决定底色、边框和图标（critical 为 `role="alert"`，其余为 `role="status"`；再次显示相同提示不会有任何变化）。页面选出最重要的消息，其余列在 `items` 里。检测：服务无法连接 / 有检测在运行 / 最新保存的运行 / 本地运行；检测历史：无法读取历史 / 监控运行已暂停（主密钥已锁定）或较早的运行仍在处理 / 运行次数；分析：无法读取数据 / 运行尚未计入图表或开始时间为估算 / 数据依据；知识库：加载失败 / 条目被跳过或被忽略 / 已停用的条目 / 完整。监控页面保留它的主密钥栏（`masterkey.js`），外观和位置相同。整个历史的数字来自 `GET /api/history/status`（`history.status()`：运行次数、最早和最新的运行、分析回填尚未处理的行、开始时间为估算的运行）。

v2 的**检测**页面用 `v2/relaycfg.js` 配置中转站：选择中转站/厂商 → 基础地址 → 中转站的模型
（`/api/models`，在改变时获取，按地址/密钥/协议缓存）→ 从知识库选择声称的模型（`/api/kb/resolve`
预选）→ 推导出声明的厂商，另有**保存到知识库**（`POST /api/kb/relays`）。其纯函数在 node 下测试。

v2 的**分析**页面（`v2/analytics.html`）只读取 `/api/analytics/*`（`options` 还列出「中转站 × 模型」组合 `relay_models`，供数据系列选择使用）。页面在同一个筛选栏下每个面板一个 `<section class="card panel">`，便于加入新面板；筛选与视图保存在网址片段（`#range=30&metric=score&…`）和 `localStorage` 中。图表来自 `v2/charts.js`（`EkteCharts.timeChart`：手绘内联 SVG，含中位数折线、p25–p75 色带、空时间段留空、`low_n` 时间段的淡化标记、标注线和悬停提示；`fmt` / `fmtDelta` 按单位格式化数值）和 `v2/charts.css`（每个主题四种经过校验的系列颜色，并以标记形状区分）。每张图表也都以数据表呈现。

每个面板都是独立的：页面脚本中的 `PANELS` 注册表列出其 section id、`load()`（用当前筛选与视图获取数据后绘制）和 `render()`（用已加载的数据重绘，例如切换语言时），因此面板可以重新排列而互不影响。`EkteCharts.heatmap` 绘制「星期几 × 小时」网格（每个主题一套五级单色顺序色阶，`low_n` 格子加斜线，空格子只画轮廓），`EkteCharts.stackBars` 绘制堆叠的错误柱状图，`timeChart` 支持 `ref` 参考线（100% 计费比）。`EkteCharts.donut`（由一个整体的各部分组成的圆环，中间是 HTML 数字）和 `EkteCharts.meter`（由各部分组成的细条）绘制无障碍报告的「覆盖范围」卡片；它们的 `k-*` 颜色（谁判定一个步骤：蓝色为测试套件，紫色为人）来自 `tokens.css`。`v2/chartmotion.js`（`EkteMotion.enter`）与其他图表一样，仅在有新数据时按顺时针绘制圆环、让细条从左侧伸展，在减少动态效果或页眉「关闭动画」时从不播放。

页面标题和筛选面板位于五个页内标签页之上（`v2/tabs.js`，与知识库页面相同）：每个 `PANELS` 条目注明所属的 `tab`，只加载当前显示的标签页的面板；筛选变化时重新加载该标签页，其他标签页标记为过期（`activate()` 在显示时加载）。这里给 `tabs.js` 传入 `writeHash: false`，因为页面自己把整个视图写进网址片段——`#tab=trends&range=30&suite=…&metric=…`（`stateQuery()`），**复制此视图的链接**复制的就是它（剪贴板 API 不存在或被拒绝时，改为显示并选中一个只读文本框）；不含 `tab` 的片段打开概览，粘贴进来的链接（`hashchange`）会重新读取视图。可折叠的筛选面板是 `v2/filterpanel.js` + `v2/filterpanel.css`，与检测历史、监控和知识库共用：`EkteFilterPanel.create(section, {label, title, storeKey, open, onReset})` 返回 `render({body, foot, count, summary})`、`sync({count, summary})`、`setOpen()` 和 `focusStart()`；页面负责自己的筛选条件和字段，面板负责带生效筛选计数的切换按钮、收起时显示的一行摘要、记住的展开状态以及**重置筛选**。

**翻译约定。** 写在 HTML 中的中文是原文，保持不动；每个元素在 `data-en`（以及
`data-en-placeholder`、`data-en-title`、`data-en-aria-label`）中携带英文文本。英文文本是
其他所有语言的查找键。脚本对动态文本使用 `T(zh, en)`，对来自后端的文本（检测器名称、建议、
结论语句）使用 `EKTE_LANG.server(text)`。

### 本地数据

`ekte/datadir.py` 管理 `$EKTE_DATA_DIR`（默认 `~/.ekte`），以 `0700` 创建，其中的 SQLite 文件
为 `0600`：`history.db`（`web/history.py`）、`watches.db`（`web/watches.py`，加密保存监控的
API 密钥）和 `kb.db`（`knowledge/store.py`）。每次调用都打开一个短生命周期的连接，因此这些存储
在 FastAPI 的线程池中是安全的。全局选项 `--data-dir`（`ekte serve` 也支持）只是把 `EKTE_DATA_DIR`
设为该绝对路径，`ekte data-dir` 输出解析后的目录。已存在的目录保留其权限；只有默认的 `~/.ekte`
会被收紧为 `0700`。检测历史的记录按目标和模型建立索引（`idx_history_target`），
`history.latest_for()` 借此找到监控的上一次运行。

自 schema 版本 2（`PRAGMA user_version`）起，`history.db` 还包含分析表，定义在
`web/analytics_store.py`：`history_metrics`（每次运行一行提取出的指标：开始时间、各类比率、
延迟/TTFT/解码速度的百分位、计费比、发现数量等；该次运行未测量的值为 NULL）、
`history_dimensions`（各维度和检测器的得分）以及 `history_requests`（该次运行的请求记录，
含目标与基线，按列表顺序）。报告的 `performance.requests` 只存放在那里：`save()` 把它们从
`report_json` 中移出（由 `requests_split` 标记该行），`get()` / `latest_for()` 再放回去，
因此读回的报告与保存时完全一致；列无法精确还原的内容存入 JSON 列 `extra`。
`extract_metrics()` 是纯函数，并带版本号（`EXTRACT_VERSION`）。迁移之后，分批回填
（每批一个短事务，幂等）会移出旧行的请求记录、提取其指标，并重新提取由较旧
`EXTRACT_VERSION` 写入的行；需要时可用 `history.backfill_analytics()` 再次运行。一次运行的
开始时间是报告的 `started_at`；早于该字段的报告取 `generated_at` 减去其请求记录覆盖的时长
（`started_at_estimated` = 1）。

监控的 API 密钥保存在哪里由用户决定（`watches.get_key_storage()`，`secret_meta` 中的一行）：
默认的 `memory` 不保存任何密钥——`api_key` 列只存标记 `mem:`，密钥留在 `watches._memory_keys` 中直到进程结束
（重启后该行为 `key_missing`，调度器把它当作已锁定的密钥处理：运行会等待，不告警）；`encrypted` 按下文方式保存。
尚无该行时，已有加密密钥或校验值的存储、或设置了 `EKTE_SECRET_KEY` / 旧版 `secret.key` 的安装从 `encrypted` 开始；
该选择在启动时记录。`Vault.set_storage()`（`POST /api/secret/storage`）在一个事务中切换并迁移密钥
（`keys_to_memory()` 清除加密密钥和校验值并清理文件；`keys_to_store()` 加密内存中的密钥）。
请求可以传入 `key_storage: "memory"`，使其密钥无论设置如何都不进入数据库；
任何请求都无法强制保存。

保存的 API 密钥由 `ekte/secretbox.py` 加密（Fernet，存为 `enc:v1:…`；`env:`/`file:` 引用保持原样）。
主密钥本身从不保存：`web/masterkey.py`（`Vault`，服务器与 `ekte secret` 共用）在主密钥来自
`EKTE_SECRET_KEY`、旧版 `secret.key` 或用户在监控页面的输入后，把它保存在服务器内存中；`watches.db`
只保存一个校验值（`secret_meta`），用来拒绝错误的密钥。更换密钥时，所有已保存的密钥会在同一个事务中
重新加密并改写校验值。主密钥只存在于一个进程的内存中，因此每个数据目录只运行一个服务器。

`ekte/legacy.py` 让改名前的安装继续可用：每个 `EKTE_*` 设置都通过 `legacy.getenv` 读取，未设置时回退到旧的 `ZING_*` 名称（在 stderr 上提示一次）；当只有旧目录存在时，`datadir.data_dir()` 会把 `~/.zing` 一次性复制到 `~/.ekte`（SQLite 文件通过备份 API 复制，先写入同级临时目录再重命名）。`~/.zing` 永远不会被修改或删除。`lang.js` 以同样方式把浏览器中的 `zing.*` 设置复制为 `ekte.*`，服务器在 `ekte_*` cookie 出现之前仍会读取 `zing_lang` / `zing_ui`。以上全部已弃用，将在 1.0.0 中移除（提示中会写明该版本）；ekte 绝不会删除旧的 `~/.zing`。

## 参与贡献

### Pull Request

- 保持 `pytest`、`ruff check ekte tests` 和 `mypy ekte` 全部通过（CI 在 Python 3.11–3.14
  上运行这三项）。
- 说明改动针对的是哪种中转站作弊手法或哪种误报。
- 在 `CHANGELOG.md` 的 `[Unreleased]` 下更新记录。
- 在**所有语言**中更新受影响的文档——README、本指南、方法论（见[文档](#文档)）。

提交贡献即表示你同意你的贡献以本项目的 [Apache-2.0](LICENSE) 许可证授权。

### 新增检测器

1. 创建 `ekte/detectors/<name>.py`，并在 `ekte/detectors/__init__.py` 中导入它。
2. 定义它的 `SCALE`（`scale.py` 中的 `Scale` 或 `DeductionScale`），列出每个检查项的每种结果，
   并只通过它生成发现。
3. 继承 `Detector`；设置 `id`、`name`、`dimension`、`min_suite` 和 `cost_hint`；需要裁判或
   基线时设置 `requires_judge = True` 或 `requires_baseline = True`，其他条件则覆盖 `applies()`。
   用 `@register` 装饰该类。
4. 实现 `async def run(self, ctx) -> DetectorResult`，从
   `self.new_result(scoring=SCALE.scoring())` 开始。通过 `ctx.client` 发送请求，每条提示词都从
   `ekte/prompts/en.json` 读取。
5. 使用 `tests/conftest.py` 中的模拟中转站，为「命中」和「正常」两条路径都编写行为测试。
6. 翻译新的发现标题和摘要（见[翻译](#翻译)），并在每一份[方法论](docs/METHODOLOGY.zh-CN.md)
   文件中记录该检测器及其计分标准。

### 编辑知识库

画像位于 `ekte/knowledge/data/<provider>.yaml`，每个厂商一个文件。每个模型包含原生上下文窗口、
最大输出、知识截止日期、分词器、模态、能力标记、不支持的参数、身份关键词和指纹（见
`ekte/knowledge/schema.py`）。修改数值字段时，请在 Pull Request 中**注明权威来源**（厂商官方的
模型卡、价格页或文档）：错误的数值会导致对诚实中转站的误报。`ekte kb-import --check <file>`
会执行与用户导入相同的检查（结构、限制、不安全的正则表达式、提示词、id 冲突）。

厂商级 `fingerprints` 会在该厂商的每个模型上运行。期望只对部分模型成立的探测（知识截止日期、
Pro 档位的知识检查、推理陷阱）应放在这些模型自己的 `fingerprints` 中，否则另一个模型的如实
回答会被算作偏离。

`identity_keywords` 一律要填上模型自称时使用的厂商与系列词。身份检查还会把厂商键、显示名称
和模型 id 当作正品品牌，并扩展到 `VENDOR_BRANDS`（`ekte/knowledge/identity.py`，同时也是检测器
的竞品品牌列表）中同一厂商的其他名称；导入时若关键词为空，会据这些名称补上并给出警告。新厂商的
品牌词作为一组加到那里。

### 保持知识库最新

提供商和模型的数据过时很快，而每个结论都依赖这些数据，因此 ekte 会如实说明数据的新旧。
每个内置的提供商配置都带有 `last_verified`，即其数据最近一次对照提供商文档核实的日期。
其中最早的日期就是**知识库日期**：它保存在每份报告中（`knowledge.kb_date`），由 `ekte kb`
以及 Markdown、HTML、PDF 报告显示，并由 `ekte kb --json` 输出。若它早于
`STALE_AFTER_DAYS`（180 天，位于 `ekte/knowledge/freshness.py`），报告会带上一条警告，
提示更新 ekte 或添加自己的条目。该警告不会改变结论。

更新流程：

- **来源。** 只使用提供商的官方页面：模型列表与模型卡、价格与限制页面、弃用与下线公告、
  发布说明。请在拉取请求中附上链接。
- **负责人。** 维护者。任何人都可以通过议题表单“Knowledge base update”（提供商、模型 ID、
  变更内容、来源链接及其日期）或拉取请求提出修改。
- **频率。** 至少在每个次版本发布前更新一次；出现重大模型变化（旗舰模型发布、模型下线、
  模型 ID 改名）时，另发补丁版本。发布检查清单包含这一步。
- **评审。** 修改 `ekte/knowledge/data/*.yaml` 的拉取请求，每个改动的值都要有引用的来源并经过
  第二人复核，且 `ekte kb-import --check` 必须通过。只有核对完某个提供商的整个文件之后，
  才可更新它的 `last_verified`，而不是只核对改动的那几行。
- **更新日志。** 内置数据的每次改动都要写入 `CHANGELOG.md`，因为它可能改变结论。

### 修改探测提示词

探测文本是校准数据。修改 `ekte/prompts/en.json` 中的某条文本，可能改变答案校验、token 估算，
进而改变结论；请同步调整检测器及其测试，并在 CHANGELOG 中说明。绝不要让探测跟随界面语言。

### 修改数据库模式

ekte 创建的每个 SQLite 数据库（`history.db`、`watches.db`、`kb.db`）都由同一个共享机制
`ekte/dbmigrate.py` 管理版本和迁移；存储模块不得再用临时的 `ALTER TABLE` 自行迁移。
模式版本保存在 `PRAGMA user_version` 中，`datadir.connect(name, MIGRATIONS)` 在每次
打开时检查它。

修改模式的步骤：

1. 在存储模块（`web/history.py`、`web/watches.py`、`knowledge/store.py`）中添加一个
   执行变更的函数 `_vN(conn)`，并把 `dbmigrate.Migration(N, _vN)` 追加到其
   `MIGRATIONS` 元组末尾。切勿修改或重排已有步骤：线上的数据库已经执行过它们。
2. 保持步骤幂等（`CREATE ... IF NOT EXISTS`，列用 `kb_snapshot.add_link_columns()`），
   且不要在其中提交或回滚。该机制在各自独立的 `BEGIN IMMEDIATE` 事务中执行每个步骤，
   并同时更新版本号；因此被中断或失败的步骤会让数据库保持在上一个版本。
3. 新数据库从版本 0 开始并执行所有步骤；版本化之前的数据库同样是版本 0，所以存储模块的
   第 1 步必须能接管已有的模式。
4. 在 `tests/test_dbmigrate.py` 中添加测试：构建版本 N-1 的模式，打开它，并检查新版本、
   新模式以及数据完好。如果需要为已有数据回填行，请在存储模块的 `on_migrated` 回调中
   完成（见 `history._after_migration`），而不是在步骤里。

该机制为你做的事：由**更新版本**的 ekte 写入的数据库会在写入任何内容之前被
`DatabaseTooNewError` 拒绝（会指明两个版本以及该怎么做）；一次运行的第一个步骤之前，
非空数据库会被复制到旁边的 `<db>.v<版本>.<UTC 时间>.bak`，每个数据库只保留最新的 3 份备份
（`dbmigrate.BACKUP_KEEP`）；版本号在写锁下重新读取，所以 CLI 和服务器永远不会把同一个
步骤执行两次。

### 翻译

界面和 Webhook 告警共用一套翻译，位于 `ekte/i18n/locales/<code>.json`：

- `meta` —— 语言代码、下拉框中该语言的自称、`html` 语言、日期区域设置和菜单顺序；
- `strings` —— 英文文本 → 译文（`en.json` 是恒等映射，也是所有可翻译文本的权威清单）；
- `findings` —— 发现 id → `[标题, 摘要模板]`（`zh.json` 中是原始中文目录）。

功能也可以用片段的形式提供文案：`ekte/i18n/locales/fragments/<feature>/<code>.json`，
内容为 `{"strings": {…}}`，加载时合并进对应语言。`/locales.js` 只发送所选语言
（`?lang=<code>`，或 `lang.js` 写入的 `ekte_lang` cookie；两者都没有时发送全部语言），
每种变体只生成并 gzip 压缩一次，并通过 `ETag` 重新验证；切换语言时按需加载新语言。

- **新的界面文案：** 把中文写进 HTML，英文写进 `data-en`（或使用 `T(zh, en)`），然后把英文键加入
  `en.json` 或某个片段，并在其他每种语言中加上译文。
- **新的语言：** 新增 `ekte/i18n/locales/<code>.json`（复制 `de.json`）以及每个片段的对应文件；
  下拉框、页面、告警和 `--alert-lang` 都会自动识别。
- `tests/test_web_locales.py` 会一直失败，直到每条界面文案和每条发现都已翻译，且占位符与标记
  完好无损。

**用词。** 每个术语在每种语言中只有一种译法。在新文案和文档中，沿用界面已有的用词（页面名称、
维度名称、风险名称、按钮文字）。

### 文档

文档提供八种语言——英文、中文（`zh-CN`）、法语、西班牙语、葡萄牙语、意大利语、德语和挪威语（书面挪威语，`nb`）：

| 文件 | 读者 |
|---|---|
| `README.md`、`README.<lang>.md` | 使用者：ekte 能做什么、安装、命令行与 Web 界面的使用 |
| `DEVELOPER_GUIDE.md`、`DEVELOPER_GUIDE.<lang>.md` | 贡献者：架构、环境搭建、参与贡献、Docker、发布 |
| `docs/METHODOLOGY.md`、`docs/METHODOLOGY.<lang>.md` | 所有人：每项检测、它的计分标准和注意事项 |
| `docs/CI.md`、`docs/DOCKER.md`、`docs/PUBLISHING.md` | 参考页面（英文） |

英文文件为基准。修改其中一份时，请在同一个 Pull Request 中同步修改其他语言，并在每种语言中使用
界面的用词（在 `ekte/i18n/locales/` 中查找对应术语）。METHODOLOGY 文件中的计分标准措辞与界面
「**计分标准**」中显示的一致。

## 测试

```bash
pytest                       # 全部
pytest tests/test_billing.py # 单个模块
pytest -k streaming          # 按关键字
pytest -n auto               # 并行运行，每个 CPU 一个 worker（pytest-xdist）
```

- `tests/conftest.py` 提供 `MockServer`：基于 `httpx.MockTransport` 的 OpenAI 兼容端点，
  针对 ekte 要识别的每种偏离都有开关（实际提供的模型、自我身份、上下文截断、伪流式、用量缺失或
  虚报、工具调用、JSON 模式等）。每个开关的默认值都代表诚实的中转站。
- Anthropic 与 Responses 客户端有各自的测试（`test_anthropic.py`、`test_responses.py`）；
  Web 服务通过 FastAPI 的测试客户端测试（`test_web*.py`），包括仅限本地的防护
  （`test_web_security.py`）。
- 浏览器脚本（`lang.js`、`v2/relaycfg.js`、`perf.js`、`secretfield.js`、`v2/report.js`、
  翻译数据）在 `test_web_*_js.py` 和 `test_web_locales.py` 中由 `node` 执行；没有 Node.js 时跳过。
- 任何测试都不得访问网络。
- `test_cli_startup.py` 保证 CLI 启动迅速：导入 `ekte.cli` 时不得加载 HTTP 客户端、runner、
  知识库加载器、报告渲染器（ReportLab）或 Web 服务器。请在需要它们的命令内部导入。
- `test_filler_perf.py` 逐字节固定填充文本，并在上下文窗口探测卡住事件循环时失败。
- `tests/a11y/` 在真实浏览器中（Playwright + axe-core），以每种界面语言和两种主题，按
  BITV 2.0 / EN 301 549 / WCAG 2.1 AA 检查 Web 界面（v2）：
  `pip install -e '.[web,a11y]' && playwright install chromium`，然后运行 `pytest -m a11y`。
  没有 Playwright 时跳过该目录。哪些已自动化、哪些仍需人工 BITV 审查，见
  [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md)（英文）。
- `EKTE_A11Y_PAGES=history,kb` 只运行这些页面的无障碍测试（以及跨所有页面的检查）；
  `python -m tests.a11y.affected --base origin/main --head HEAD` 输出某次改动影响的页面。
  两者使用同一份映射 `tests/a11y/pages.py`：新增页面时须加入其中的 `PAGES` 和 `RULES`
  （[tests/a11y/README.md](tests/a11y/README.md)）。

## Docker

`Dockerfile` 构建 Web 界面的镜像（Python 3.12 slim，带 `web` 附加项；PDF 报告不需要任何系统软件包）。镜像以非特权用户运行，数据目录位于 `/data`。

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# 打开 http://localhost:8000
```

**务必只发布到 `127.0.0.1`。** 直接写 `-p 8000:8000` 会把界面——以及在其中输入或保存在监控里的
每一个 API 密钥——暴露到你的网络上。在容器内，服务必须监听所有网卡；只有设置了
`EKTE_CONTAINER=1`（镜像已设置）*并且*检测到容器运行时，才允许这样做。

| 变量 | 默认值 | 作用 |
|---|---|---|
| `EKTE_CONTAINER` | 未设置（镜像中为 `1`） | 在检测到的容器内允许绑定非回环地址 |
| `EKTE_HOST` | `127.0.0.1`（镜像中为 `0.0.0.0`） | 绑定地址；`--host` 优先 |
| `EKTE_PORT` | `8000` | 端口；`--port` 优先 |
| `EKTE_DATA_DIR` | `~/.ekte`（镜像中为 `/data`） | 检测历史、监控（含加密后的密钥）和你的知识库条目；在此挂载数据卷。`--data-dir` 优先 |
| `EKTE_SECRET_KEY` | 未设置 | 监控已保存 API 密钥的主密钥（一个密钥，或 `file:/run/secrets/…` / `env:VAR`）；未设置时，每次启动后监控页面都会请求它。从不保存在 `EKTE_DATA_DIR` 中 |
| `EKTE_KB_DIR` | 未设置 | 额外的知识库 YAML 目录，例如 `-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb` |
| `EKTE_NO_USER_KB` | 未设置 | 设为 `1` 时忽略你自己的知识库条目（`kb.db`） |
| `EKTE_ALLOWED_HOSTS` | 未设置 | 界面额外响应的主机名，逗号分隔 |

完整参考（含界面的防护措施）见 [docs/DOCKER.md](docs/DOCKER.md)（英文）。

## 持续集成

| 工作流 | 触发条件 | 作用 |
|---|---|---|
| `.github/workflows/ci.yml` | 推送到 `main` 及针对 `main` 的 Pull Request（以及集成分支 `a11y/integration`、`perf/integration`）；每晚定时及手动（仅无障碍测试） | 在 Python 3.11–3.14 上带 `dev` 和 `web` 附加项运行 `ruff`、`mypy` 和 `pytest`；构建 wheel 和 sdist，并验证 wheel 能安装并加载知识库；运行无障碍测试套件（仅供参考，从不导致运行失败）并上传其结果：推送、每晚及手动运行测试所有页面（并生成 BITV 符合性报告），Pull Request 只测试改动影响的页面（仅改文档时不运行）——但针对 `perf/integration` 的 Pull Request 除外，此时跳过较慢的浏览器测试套件（它在该分支的推送及其针对 `main` 的 Pull Request 上运行） |
| `.github/workflows/release.yml` | `v*` 标签 | 构建、运行 `twine check` 并发布到 PyPI（Trusted Publishing） |
| `.github/workflows/example-audit.yml` | 每日定时、手动 | 使用该 Action 定时审计中转站的示例 |

复合 Action 本身是 `action.yml`，文档见 [docs/CI.md](docs/CI.md)。

### 发行包中的第三方文件

源码发行包（sdist）包含测试，但不包含随附的第三方文件。`tests/a11y/vendor/axe.min.js`（axe-core，MPL-2.0）只在 git 仓库中；它被排除在 sdist 之外（`pyproject.toml` 中 `[tool.hatch.build.targets.sdist]` 下的 `exclude`），也从未属于 wheel。

- 需要被排除文件的测试在文件缺失时会跳过并给出明确原因；请在 git 检出中运行无障碍测试套件。
- `NOTICE` 列出每个第三方文件并说明是否分发。新增随附文件时，请加入 `exclude` 列表和 `NOTICE`；若必须随包分发，则在 `NOTICE` 中说明。
- `scripts/check_dist_contents.py` 构建 wheel 和 sdist（`uv build`），若包含被排除的文件或 `NOTICE` 标明不分发的文件则失败。`.github/workflows/dist.yml` 工作流在单独的 job 中运行它。

## 发布

一次发布就是一个版本标签；其余一切均已自动化并带有检查。检查清单见
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)，一次性的 PyPI 设置和手动
备用方案见 [docs/PUBLISHING.md](docs/PUBLISHING.md)。

### 创建发布

1. 逐项完成[发布检查清单](docs/RELEASE_CHECKLIST.md)：版本与变更日志、支持的
   Python 版本与系统、知识库是否新鲜、升级 fixture、UI 变更的无障碍审查、
   所有语言的文档、安全公告。
2. 在 `pyproject.toml` 中设置 `version`，并把 `CHANGELOG.md` 中的 `[Unreleased]`
   重命名为 `[X.Y.Z] - YYYY-MM-DD`。本地用
   `python scripts/release_check.py version vX.Y.Z` 和 `... notes vX.Y.Z` 检查。
3. 合并后给该提交打标签并推送：
   `git tag -a vX.Y.Z -m "ekte vX.Y.Z"`，`git push origin vX.Y.Z`。
4. `release.yml` 先用 `scripts/release_check.py` 检查：标签与包版本一致、
   `CHANGELOG.md` 有对应章节、带标签提交的 CI 为绿色（CI 仍在运行时会等待）。
   任何检查失败，工作流即停止，不会发布任何内容。随后构建，通过 Trusted
   Publishing 发布到 PyPI 并附带来源证明（provenance attestations），再以变更
   日志章节作为说明创建 GitHub Release。

### 候选版本（Release Candidate）

打标签 `vX.Y.ZrcN`（`pyproject.toml` 中 `version = "X.Y.ZrcN"`）。PyPI 将其视为
PEP 440 预发布版本：`pip install ekte` 会忽略它，`pip install --pre ekte` 可以找到；
GitHub 会把该发布标记为“Pre-release”。变更日志中使用 `[X.Y.ZrcN]`、`[X.Y.Z]` 或
`[Unreleased]` 章节均可。

### 发布中途失败时

PyPI 从不接受同一文件两次，版本号也不能复用；关键看运行进行到了哪一步
（Actions，“Release to PyPI”）：

- **某项检查失败（verify 作业）。** 未发布任何内容。修复原因（版本、变更日志、
  CI），在本地和 origin 删除标签（`git push origin :refs/tags/vX.Y.Z`），然后给
  修复后的提交重新打标签。
- **在 PyPI 收到文件之前，构建或上传失败。** 重新运行失败的作业；没有消耗版本号。
  若带标签的提交本身需要修改，则删除标签后重新创建。
- **PyPI 已有部分文件**（见 <https://pypi.org/project/ekte/#files>）。重新运行失败
  的作业：上传会跳过已存在的文件。若这些文件与要发布的内容不符，不要重试：在
  PyPI 上 yank 该版本，并发布下一个版本（`X.Y.Z+1` 或 `rcN+1`）。
- **PyPI 已完整但 GitHub Release 失败。** 重新运行 `GitHub Release` 作业；它会
  幂等地创建或更新发布。或手动执行：
  `gh release create vX.Y.Z --notes-file <(python scripts/release_check.py notes vX.Y.Z)`。
- **有缺陷的版本已上线。** 在 PyPI 上 yank（之后只能通过精确版本号安装），
  用新版本向前修复，并在其变更日志中注明。

## 安全

请按 [SECURITY.md](SECURITY.md) 中的说明私下报告漏洞。重点关注：密钥或其他机密进入报告、
由中转站控制的文本向报告或界面注入标记、向已配置端点之外的地方发送数据，以及绕过 Web 界面
仅限本地防护的方法。

## 许可证

[Apache-2.0](LICENSE)
