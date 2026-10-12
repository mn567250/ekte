# zing — 开发者指南

> [🇬🇧 English](DEVELOPER_GUIDE.md) · **🇨🇳 中文** · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md)

本指南面向修改 zing 的人：它是如何构建的、如何搭建开发环境、如何参与贡献，以及如何打包、
在 Docker 中运行和发布。zing 能做什么、如何使用，见 [README](README.zh-CN.md)；
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
  - [独立审计器](#独立审计器)
  - [Web 服务](#web-服务)
  - [Web 前端](#web-前端)
  - [本地数据](#本地数据)
- [参与贡献](#参与贡献)
  - [Pull Request](#pull-request)
  - [新增检测器](#新增检测器)
  - [编辑知识库](#编辑知识库)
  - [修改探测提示词](#修改探测提示词)
  - [翻译](#翻译)
  - [文档](#文档)
- [测试](#测试)
- [Docker](#docker)
- [持续集成](#持续集成)
- [发布](#发布)
- [安全](#安全)
- [许可证](#许可证)

## 原则

zing 是黑盒审计辅助工具：正确性以及**不冤枉诚实的中转站**，比抓住每一种可能的作弊手法更重要。
任何改动都请牢记这条标准。

- **证据优先，不做指控。** 发现只报告*偏离与风险*，从不说「欺诈」。宁可*不确定*，也不要猜测。
  新增的「高」严重度路径需要确凿、可复现的证据，并且很难在诚实端点上被触发。
- **测试不联网。** 检测器测试针对 `tests/conftest.py` 中的进程内模拟服务
  （httpx `MockTransport`）运行，绝不访问真实 API。
- **密钥不外泄。** API 密钥只保留指纹，绝不写入报告。任何新的输出路径都必须让中转站控制的文本
  经过 `zing.utils.redact`，并按输出格式进行转义。
- **对所有人使用相同的探测。** 探测文本固定为英文，与界面语言无关，这样同一个中转站总会得到
  同样的结论（见[提示词库](#提示词库)）。
- **仅限本地。** zing 只联系用户配置的端点，Web 界面只监听回环地址（见 [Web 服务](#web-服务)）。

## 开发环境

需要 Python 3.10+。Node.js 可选：浏览器 JavaScript 的测试在 `node` 下运行，没有 Node.js 时跳过。

```bash
git clone https://github.com/cenbonew/zing
cd zing
pip install -e '.[dev,web]'   # 以可编辑模式安装开发工具和 Web 界面
pytest                        # 测试套件
ruff check zing tests         # 代码检查
mypy zing                     # 类型检查
```

使用 uv：`uv venv && uv pip install -e '.[dev,web]'`。无需任何系统库，PDF 报告也不例外。

从源码运行：`zing …` 或 `python -m zing …`。`zing serve` 直接从 `zing/web/static/` 提供
Web 界面，刷新浏览器即可看到前端改动；没有构建步骤。

## 仓库结构

```text
zing/
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
  prompts/en.json      zing 发给 LLM API 的全部文本
  perf/                逐请求记录与报告中的性能部分
  report/              JSON / Markdown / HTML / PDF 渲染与写出
  embed_audit.py       独立的 embedding 与 rerank 审计器
  media_audit.py       独立的图像与音频（TTS）审计器
  notify.py            Webhook 告警（Slack / 飞书 / 钉钉 / 通用 JSON）
  datadir.py           本地数据目录及其 SQLite 文件
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
    watches.py         监控存储（watches.db）
    masterkey.py       主密钥的状态与操作（服务器与 `zing secret`）
    static/            经典界面页面与共用脚本（lang.js、i18n.js 等）
    static/v2/         新界面的页面、样式和脚本
tests/                 pytest 测试套件；conftest.py 中是模拟中转站
docs/                  METHODOLOGY（7 种语言）、CI.md、DOCKER.md、PUBLISHING.md
examples/zing.yaml     带注释的配置文件
prototypes/            Web 界面的静态 HTML 设计原型（不随包发布）
action.yml             GitHub 复合 Action
Dockerfile             Web 界面镜像
```

## 架构

### 一次检测的流程

`zing check`、`zing compare`、`zing watch`、Web 界面的检测流及其监控调度器，最终都进入
同一个函数 `zing.runner.run_audit()`：

1. **配置。** `zing/config.py` 把 YAML 配置与命令行选项合并为 `TargetConfig`（目标，
   以及可选的基线和裁判）和 `AuditOptions`（套件、维度、探测规模、输出）。以 `env:VAR`
   或 `file:/path` 给出的 API 密钥在这里解析。
2. **知识库。** `load_knowledge_base()` 加载内置画像、`--kb-dir`/`ZING_KB_DIR` 和用户的
   `kb.db`，并把**声称的**模型（默认即请求的模型）解析为一个画像。监控则改为传入它固定的快照。
3. **客户端。** `make_client()` 按所选或自动识别的协议为目标（及基线）创建客户端。
   `RequestRecorder` 包裹每一次调用，用于性能部分。
4. **检测器。** `select_detectors()` 为套件（或自定义维度）挑选已注册的检测器，并去掉缺少
   裁判或基线时无法运行的那些。它们**依次**运行，这是有意为之：并发请求会触发限流并干扰计时
   测量（可靠性和性能探测会自行控制有限的并发）。`run_detector()` 为每个检测器计时，并把崩溃
   转换为状态为**错误**的结果，因此中转站的异常响应绝不会中断整个检测。
5. **计分。** `scoring.build_dimensions()` 和 `build_verdict()` 把检测器结果转换为维度得分、
   综合健康分与评级、风险结论及其置信度。
6. **报告。** 一切汇总到一个 `AuditReport`（`zing/models.py`）中，包括脱敏后的目标、知识库画像
   快照、性能部分和探测语言。命令行负责渲染并写出；Web 界面则把它流式推送。

`run_audit()` 接受一个 `on_event` 回调；Web 服务把它的事件（检测器开始/结束及精简的发现、
批量的逐请求耗时）转换为 Server-Sent Events，用于实时视图。

### 客户端

`zing/clients/` 为每种协议提供一个客户端——`openai_compatible.py`（Chat Completions）、
`anthropic.py`（Messages）和 `responses.py`（Responses）——接口相同，都构建在 `base.py`
的共用 HTTP 机制之上。`clients/__init__.py` 中的 `make_client()` 根据 `--api` 选择，
或根据 base URL 和模型自动识别。检测器只与这一接口打交道（输入 `RequestSpec`，
输出 `CompletionOutcome`），因此与协议无关。

### 检测器与计分标准

一个检测器就是 `zing/detectors/` 中一个自包含的文件：继承 `Detector`（`base.py`），
定义 `id`、`name`、`dimension`、首次运行的套件（`min_suite`）、供 `--dry-run` 使用的大致
`cost_hint`，以及 `async def run(self, ctx) -> DetectorResult`。`@register` 把它加入注册表；
`zing/detectors/__init__.py` 导入每个模块，保证注册表完整。

每个检测器都公开自己的**计分标准**（`SCALE`，由 `scale.py` 构建）：每个检查项所有可能的结果，
及其分数、状态和严重程度。发现都由计分标准生成（`SCALE.finding(check, outcome, …)`），
因此报告与实际行为不可能不一致。`Scale` 取各检查项的平均分；`DeductionScale` 从 100 开始扣分
或设上限。Web 界面在「**计分标准**」中展示它；[方法论](docs/METHODOLOGY.zh-CN.md)收录了
每一份计分标准。`connectivity.py` 是最短、最标准的示例。

在 `zing serve` 中，检测器与其他所有检测共用一个事件循环，因此 CPU 密集的工作不能在其上运行：
事件循环一旦卡住，就会拖延其他检测的请求，并让它们记录的延迟虚高。`helpers.build_filler()`
以线性时间构建填充文本，并缓存最近几种长度的结果；上下文窗口和提示缓存检测器通过
`asyncio.to_thread` 调用它（以及 `build_haystack()`）。token 计数来自 `zing/utils/tokenize.py`，
一个只用标准库的启发式方法：zing 不导入任何分词器库，运行时也不下载任何东西，因此在受限环境中
同样可以运行。`estimate_tokens()` 的 `tokenizer` 参数仍被接受，但不会改变计数；报告字段
`tokens_exact` / `exact_tokenizer` 为兼容而保留，始终为 false。

### 计分与结论

`zing/scoring.py` 定义了 `DIMENSION_WEIGHTS` 和结论规则：维度得分是其各检测器得分的
平均值（权重相同），综合健康分是已运行维度的加权平均，风险等级遵循
[方法论 → zing 如何计分](docs/METHODOLOGY.zh-CN.md#zing-如何计分)中描述的严重程度阶梯。
每个维度都在 `DimensionScore.breakdown` 中记录计算过程，报告中的 **Dimension details**
和 Web 界面「**逐项体检**」的可展开行都由它生成。

### 知识库

`zing/knowledge/` 定义画像结构（`schema.py`：`ProviderProfile`、`ModelProfile`、
`FingerprintProbe`），加载并合并各层（`loader.py`：内置 YAML → `ZING_KB_DIR`/`--kb-dir`
→ 用户的 `kb.db`），保存用户条目（`store.py`），检查并导入 YAML（`importer.py`），
生成供外部助手使用的调研提示词（`research.py`），并为一次运行所用的画像拍快照（`snapshot.py`）。
模型 id 通过别名和声明的厂商解析；每份报告都会记录 id 是如何匹配的。

`load_knowledge_base()` 会缓存合并结果，默认返回一份深拷贝，因此调用方可以修改拿到的结果。
只读取它的调用方（Web 界面的列表和目录、解析模型）传入 `copy=False`，拿到共享的缓存实例，
它们不得修改这个实例。

中转站也是端点：`relays.py` 把厂商的 `base_url_hints` 转换为可用的基础地址（`GET /api/kb` →
`base_urls`），并把 Web 界面中保存的中转站作为厂商条目写入 `kb.db`（`origin = relay`：一个
`display_name` 和一个基础地址，不含模型；无需修改结构）。

### 提示词库

zing 发给 LLM API 的每一段文本——对话探测、裁判提示词、工具 schema、embedding / rerank /
图像 / 音频输入——都在 `zing/prompts/en.json` 中，通过 `zing.prompts.text()` / `get()` 读取。
`{{name}}` 表示运行时填入的值。探测语言固定为英文（`PROBE_LANG`），与界面语言无关，
因为答案校验和 token 估算都针对这些确切文本校准过。语言本身就是测量对象的探测（例如中国
原生模型的中文流畅度、分词器或自我身份识别）连同期望答案放在知识库中，并声明 `prompt_lang`
和 `language_bound` 理由。runner 会把实际使用的语言记录在 `prompt_languages` 中。

### 报告

`zing/report/render.py` 把 `AuditReport` 渲染为 JSON、面向 Agent 的精简 JSON、Markdown 和 HTML；
`dimensions.py` 和 `performance.py` 渲染 **Dimension details** 和性能部分；`pdf.py` 用
ReportLab 基于同样的数据和辅助函数排版 PDF（纯 Python；只使用 PDF 标准字体，中文用 CID 字体
STSong-Light，因此不嵌入任何字体；绝不加载外部资源），命令行和 Web 界面共用它；`writer.py` 负责写文件。
所有由中转站控制的文本在输出前都会脱敏并转义（HTML / Markdown）。Web 界面的
`POST /api/report/export` 复用这些渲染器来实现**下载报告**，并把面向人阅读的文本翻译成界面语言。

### 独立审计器

Embedding/rerank（`embed_audit.py`）和图像/音频（`media_audit.py`）不是对话接口，因此各有
自己的小型审计器和结论，而不走检测器流水线。它们共用客户端的 HTTP 设置、知识库（原生维度、
图像尺寸、音色）和提示词库。所有解码（图像文件头、WAV）只使用标准库。

### Web 服务

`zing/web/server.py` 是由 `create_app()` 创建的 FastAPI 应用：

- **页面。** 经典界面（`/`、`/console`、`/history`、`/watches`、`/tools`）和新界面
  （`/v2/`、`/v2/history`、`/v2/watches`、`/v2/tools`、`/v2/kb`）都是静态 HTML 文件。
  `?ui=v2` / `?ui=v1` 用于切换，并由 cookie 记住选择；选了新界面之后，经典界面的 URL
  会重定向到对应的新页面。
- **API。** `/api/audit/stream` 运行检测并通过 SSE 推送事件；`/api/models` 列出中转站的模型；
  `/api/report/export` 渲染报告；`/api/history…`、`/api/watches…`、`/api/kb…`、`/api/embed`
  和 `/api/rerank` 为其他页面提供服务。
- **中转站。** `POST /api/kb/relays` 保存中转站 `{name, base_url}`（输入无效时返回 400，名称或地址已存在时返回 409）。
- **后台检测。** `jobs.py` 把每次检测作为服务器拥有的任务运行。`POST /api/jobs` 排入一个任务，
  `GET /api/jobs` 列出排队中、运行中和刚结束的任务（以及运行中的监控）及其进度，
  `GET /api/jobs/{id}/events` 先回放任务的事件日志，再通过 SSE 实时跟随，
  `POST /api/jobs/{id}/cancel` 停止任务。新界面使用这些接口，因此检测不随页面结束；
  `/api/audit/stream`（经典界面）包装同一种任务，并在数据流关闭时取消它。
  中转站互斥让同一中转站同一时间只运行一项检测（或一次监控运行），按主机名区分，所有回环地址视为同一主机；
  同时最多运行 `ZING_MAX_PARALLEL_AUDITS`（默认 4）项，等待者按到达顺序执行。
- **监控调度器。** 应用的 lifespan 启动一个后台循环，把每个到期的监控作为独立任务启动，
  因此不同中转站上的监控会同时检测；中转站互斥依然生效，所以监控可能占满
  `ZING_MAX_PARALLEL_AUDITS` 个名额，手动检测可能排在它们之后。一次运行的 `last_run_ts`
  是其检测开始的时刻（在等待中转站空闲之后）。每次运行都存入检测历史；恶化检查将其与同一目标和
  模型最近一次保存的运行比较（`history.latest_for()`，一次带索引的查询），并在越过阈值或恶化时
  并发发送 Webhook 告警（`zing/notify.py`）。调度器刚启动某个监控时，
  `POST /api/watches/{id}/run` 返回 409；重置主密钥会取消尚未开始的计划运行，关闭服务会取消
  正在进行的运行。
- **压缩与缓存。** `caching.py` 对 1 KiB 及以上的响应（Server-Sent Events 除外）进行 gzip
  压缩，前提是客户端接受（`gzip;q=0` 表示拒绝）。页面和 `/locales.js` 在生成时只压缩一次，
  以预压缩形式提供，带 `Content-Encoding: gzip`、`Vary: Accept-Encoding` 和一个以 `-gz`
  结尾的独立 ETag；页面通过 `html_page(page, request.scope)` 提供，从而走这条路径，并对条件请求
  返回 304。页面中本地脚本和样式表的 URL 带有 `?v=<content hash>`，作为不可变资源缓存。
- **安全。** `security.py` 决定绑定地址（仅回环地址；只有在检测到容器且设置了
  `ZING_CONTAINER=1` 时例外），并安装 `LocalOnlyMiddleware`：防 DNS 重绑定的 Host 白名单、
  防 CSRF 的 `Origin` 与 `Sec-Fetch-Site` 校验、只接受 JSON 请求体，以及防嵌入 / 禁止
  MIME 嗅探 / 不发送 Referrer 的响应头。界面有意不设登录。

### Web 前端

前端是纯 HTML、CSS 和浏览器 JavaScript，不使用模块，也没有构建步骤。经典页面位于
`zing/web/static/`；新界面位于 `zing/web/static/v2/`，共用一个页头（`nav.js`）、报告渲染器
（`report.js`）、主题切换（`theme.js`）和样式（`zing.css`、`fields.css`、`report.css`、
`perf.css`）。共用脚本从根路径提供：`lang.js`（语言切换）、`locales.js`（翻译数据）、
`i18n.js`（发现的翻译）、`icons.js`、`modelpicker.js`（**获取模型列表**）、`secretfield.js`
和 `perf.js`（性能图表）。

v2 的**检测**和**工具**页面用 `v2/relaycfg.js` 配置中转站：选择中转站/厂商 → 基础地址 → 中转站的模型
（`/api/models`，在改变时获取，按地址/密钥/协议缓存）→ 从知识库选择声称的模型（`/api/kb/resolve`
预选）→ 推导出声明的厂商，另有**保存到知识库**（`POST /api/kb/relays`）。其纯函数在 node 下测试；
经典页面继续使用 `modelpicker.js`。

**翻译约定。** 写在 HTML 中的中文是原文，保持不动；每个元素在 `data-en`（以及
`data-en-placeholder`、`data-en-title`、`data-en-aria-label`）中携带英文文本。英文文本是
其他所有语言的查找键。脚本对动态文本使用 `T(zh, en)`，对来自后端的文本（检测器名称、建议、
结论语句）使用 `ZING_LANG.server(text)`。

### 本地数据

`zing/datadir.py` 管理 `$ZING_DATA_DIR`（默认 `~/.zing`），以 `0700` 创建，其中的 SQLite 文件
为 `0600`：`history.db`（`web/history.py`）、`watches.db`（`web/watches.py`，加密保存监控的
API 密钥）和 `kb.db`（`knowledge/store.py`）。每次调用都打开一个短生命周期的连接，因此这些存储
在 FastAPI 的线程池中是安全的。全局选项 `--data-dir`（`zing serve` 也支持）只是把 `ZING_DATA_DIR`
设为该绝对路径，`zing data-dir` 输出解析后的目录。已存在的目录保留其权限；只有默认的 `~/.zing`
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

保存的 API 密钥由 `zing/secretbox.py` 加密（Fernet，存为 `enc:v1:…`；`env:`/`file:` 引用保持原样）。
主密钥本身从不保存：`web/masterkey.py`（`Vault`，服务器与 `zing secret` 共用）在主密钥来自
`ZING_SECRET_KEY`、旧版 `secret.key` 或用户在监控页面的输入后，把它保存在服务器内存中；`watches.db`
只保存一个校验值（`secret_meta`），用来拒绝错误的密钥。更换密钥时，所有已保存的密钥会在同一个事务中
重新加密并改写校验值。主密钥只存在于一个进程的内存中，因此每个数据目录只运行一个服务器。

## 参与贡献

### Pull Request

- 保持 `pytest`、`ruff check zing tests` 和 `mypy zing` 全部通过（CI 在 Python 3.10–3.13
  上运行这三项）。
- 说明改动针对的是哪种中转站作弊手法或哪种误报。
- 在 `CHANGELOG.md` 的 `[Unreleased]` 下更新记录。
- 在**所有语言**中更新受影响的文档——README、本指南、方法论（见[文档](#文档)）。

提交贡献即表示你同意你的贡献以本项目的 [Apache-2.0](LICENSE) 许可证授权。

### 新增检测器

1. 创建 `zing/detectors/<name>.py`，并在 `zing/detectors/__init__.py` 中导入它。
2. 定义它的 `SCALE`（`scale.py` 中的 `Scale` 或 `DeductionScale`），列出每个检查项的每种结果，
   并只通过它生成发现。
3. 继承 `Detector`；设置 `id`、`name`、`dimension`、`min_suite` 和 `cost_hint`；需要裁判或
   基线时设置 `requires_judge = True` 或 `requires_baseline = True`，其他条件则覆盖 `applies()`。
   用 `@register` 装饰该类。
4. 实现 `async def run(self, ctx) -> DetectorResult`，从
   `self.new_result(scoring=SCALE.scoring())` 开始。通过 `ctx.client` 发送请求，每条提示词都从
   `zing/prompts/en.json` 读取。
5. 使用 `tests/conftest.py` 中的模拟中转站，为「命中」和「正常」两条路径都编写行为测试。
6. 翻译新的发现标题和摘要（见[翻译](#翻译)），并在每一份[方法论](docs/METHODOLOGY.zh-CN.md)
   文件中记录该检测器及其计分标准。

### 编辑知识库

画像位于 `zing/knowledge/data/<provider>.yaml`，每个厂商一个文件。每个模型包含原生上下文窗口、
最大输出、知识截止日期、分词器、模态、能力标记、不支持的参数、身份关键词和指纹（见
`zing/knowledge/schema.py`）。修改数值字段时，请在 Pull Request 中**注明权威来源**（厂商官方的
模型卡、价格页或文档）：错误的数值会导致对诚实中转站的误报。`zing kb-import --check <file>`
会执行与用户导入相同的检查（结构、限制、不安全的正则表达式、提示词、id 冲突）。

`identity_keywords` 一律要填上模型自称时使用的厂商与系列词。身份检查还会把厂商键、显示名称
和模型 id 当作正品品牌，并扩展到 `VENDOR_BRANDS`（`zing/knowledge/identity.py`，同时也是检测器
的竞品品牌列表）中同一厂商的其他名称；导入时若关键词为空，会据这些名称补上并给出警告。新厂商的
品牌词作为一组加到那里。

### 修改探测提示词

探测文本是校准数据。修改 `zing/prompts/en.json` 中的某条文本，可能改变答案校验、token 估算，
进而改变结论；请同步调整检测器及其测试，并在 CHANGELOG 中说明。绝不要让探测跟随界面语言。

### 翻译

界面和 Webhook 告警共用一套翻译，位于 `zing/i18n/locales/<code>.json`：

- `meta` —— 语言代码、下拉框中该语言的自称、`html` 语言、日期区域设置和菜单顺序；
- `strings` —— 英文文本 → 译文（`en.json` 是恒等映射，也是所有可翻译文本的权威清单）；
- `findings` —— 发现 id → `[标题, 摘要模板]`（`zh.json` 中是原始中文目录）。

功能也可以用片段的形式提供文案：`zing/i18n/locales/fragments/<feature>/<code>.json`，
内容为 `{"strings": {…}}`，加载时合并进对应语言。`/locales.js` 只发送所选语言
（`?lang=<code>`，或 `lang.js` 写入的 `zing_lang` cookie；两者都没有时发送全部语言），
每种变体只生成并 gzip 压缩一次，并通过 `ETag` 重新验证；切换语言时按需加载新语言。

- **新的界面文案：** 把中文写进 HTML，英文写进 `data-en`（或使用 `T(zh, en)`），然后把英文键加入
  `en.json` 或某个片段，并在其他每种语言中加上译文。
- **新的语言：** 新增 `zing/i18n/locales/<code>.json`（复制 `de.json`）以及每个片段的对应文件；
  下拉框、页面、告警和 `--alert-lang` 都会自动识别。
- `tests/test_web_locales.py` 会一直失败，直到每条界面文案和每条发现都已翻译，且占位符与标记
  完好无损。

**用词。** 每个术语在每种语言中只有一种译法。在新文案和文档中，沿用界面已有的用词（页面名称、
维度名称、风险名称、按钮文字）。

### 文档

文档提供七种语言——英文、中文（`zh-CN`）、法语、西班牙语、葡萄牙语、意大利语和德语：

| 文件 | 读者 |
|---|---|
| `README.md`、`README.<lang>.md` | 使用者：zing 能做什么、安装、命令行与 Web 界面的使用 |
| `DEVELOPER_GUIDE.md`、`DEVELOPER_GUIDE.<lang>.md` | 贡献者：架构、环境搭建、参与贡献、Docker、发布 |
| `docs/METHODOLOGY.md`、`docs/METHODOLOGY.<lang>.md` | 所有人：每项检测、它的计分标准和注意事项 |
| `docs/CI.md`、`docs/DOCKER.md`、`docs/PUBLISHING.md` | 参考页面（英文） |

英文文件为基准。修改其中一份时，请在同一个 Pull Request 中同步修改其他语言，并在每种语言中使用
界面的用词（在 `zing/i18n/locales/` 中查找对应术语）。METHODOLOGY 文件中的计分标准措辞与界面
「**计分标准**」中显示的一致。

## 测试

```bash
pytest                       # 全部
pytest tests/test_billing.py # 单个模块
pytest -k streaming          # 按关键字
pytest -n auto               # 并行运行，每个 CPU 一个 worker（pytest-xdist）
```

- `tests/conftest.py` 提供 `MockServer`：基于 `httpx.MockTransport` 的 OpenAI 兼容端点，
  针对 zing 要识别的每种偏离都有开关（实际提供的模型、自我身份、上下文截断、伪流式、用量缺失或
  虚报、工具调用、JSON 模式等）。每个开关的默认值都代表诚实的中转站。
- Anthropic 与 Responses 客户端有各自的测试（`test_anthropic.py`、`test_responses.py`）；
  Web 服务通过 FastAPI 的测试客户端测试（`test_web*.py`），包括仅限本地的防护
  （`test_web_security.py`）。
- 浏览器脚本（`lang.js`、`modelpicker.js`、`v2/relaycfg.js`、`perf.js`、`secretfield.js`、`v2/report.js`、
  翻译数据）在 `test_web_*_js.py` 和 `test_web_locales.py` 中由 `node` 执行；没有 Node.js 时跳过。
- 任何测试都不得访问网络。
- `test_cli_startup.py` 保证 CLI 启动迅速：导入 `zing.cli` 时不得加载 HTTP 客户端、runner、
  知识库加载器、报告渲染器（ReportLab）或 Web 服务器。请在需要它们的命令内部导入。
- `test_filler_perf.py` 逐字节固定填充文本，并在上下文窗口探测卡住事件循环时失败。
- `tests/a11y/` 在真实浏览器中（Playwright + axe-core），以每种界面语言和两种主题，按
  BITV 2.0 / EN 301 549 / WCAG 2.1 AA 检查新界面（v2）：
  `pip install -e '.[web,a11y]' && playwright install chromium`，然后运行 `pytest -m a11y`。
  没有 Playwright 时跳过该目录。哪些已自动化、哪些仍需人工 BITV 审查，见
  [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md)（英文）。

## Docker

`Dockerfile` 构建 Web 界面的镜像（Python 3.12 slim，带 `web` 附加项；PDF 报告不需要任何系统软件包）。镜像以非特权用户运行，数据目录位于 `/data`。

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# 打开 http://localhost:8000
```

**务必只发布到 `127.0.0.1`。** 直接写 `-p 8000:8000` 会把界面——以及在其中输入或保存在监控里的
每一个 API 密钥——暴露到你的网络上。在容器内，服务必须监听所有网卡；只有设置了
`ZING_CONTAINER=1`（镜像已设置）*并且*检测到容器运行时，才允许这样做。

| 变量 | 默认值 | 作用 |
|---|---|---|
| `ZING_CONTAINER` | 未设置（镜像中为 `1`） | 在检测到的容器内允许绑定非回环地址 |
| `ZING_HOST` | `127.0.0.1`（镜像中为 `0.0.0.0`） | 绑定地址；`--host` 优先 |
| `ZING_PORT` | `8000` | 端口；`--port` 优先 |
| `ZING_DATA_DIR` | `~/.zing`（镜像中为 `/data`） | 检测历史、监控（含加密后的密钥）和你的知识库条目；在此挂载数据卷。`--data-dir` 优先 |
| `ZING_SECRET_KEY` | 未设置 | 监控已保存 API 密钥的主密钥（一个密钥，或 `file:/run/secrets/…` / `env:VAR`）；未设置时，每次启动后监控页面都会请求它。从不保存在 `ZING_DATA_DIR` 中 |
| `ZING_KB_DIR` | 未设置 | 额外的知识库 YAML 目录，例如 `-v ./profiles:/kb:ro -e ZING_KB_DIR=/kb` |
| `ZING_NO_USER_KB` | 未设置 | 设为 `1` 时忽略你自己的知识库条目（`kb.db`） |
| `ZING_ALLOWED_HOSTS` | 未设置 | 界面额外响应的主机名，逗号分隔 |

完整参考（含界面的防护措施）见 [docs/DOCKER.md](docs/DOCKER.md)（英文）。

## 持续集成

| 工作流 | 触发条件 | 作用 |
|---|---|---|
| `.github/workflows/ci.yml` | 推送到 `main` 及针对 `main` 的 Pull Request（以及集成分支 `a11y/integration`、`perf/integration`） | 在 Python 3.10–3.13 上带 `dev` 和 `web` 附加项运行 `ruff`、`mypy` 和 `pytest`；构建 wheel 和 sdist，并验证 wheel 能安装并加载知识库；运行无障碍测试套件（仅供参考，从不导致运行失败）并上传其结果——但针对 `perf/integration` 的 Pull Request 除外，此时跳过较慢的浏览器测试套件（它在该分支的推送及其针对 `main` 的 Pull Request 上运行） |
| `.github/workflows/release.yml` | `v*` 标签 | 构建、运行 `twine check` 并发布到 PyPI（Trusted Publishing） |
| `.github/workflows/example-audit.yml` | 每日定时、手动 | 使用该 Action 定时审计中转站的示例 |

复合 Action 本身是 `action.yml`，文档见 [docs/CI.md](docs/CI.md)。

## 发布

1. 把 `CHANGELOG.md` 中的 `[Unreleased]` 改为新版本号，并提升 `pyproject.toml` 中的 `version`。
2. 提交，打上 `vX.Y.Z` 标签并推送该标签；`release.yml` 会发布到 PyPI。
3. 用 CHANGELOG 中的说明创建 GitHub Release，并更新各 README 和 `docs/CI.md` 中固定的 Action 版本。

PyPI 的一次性配置和手动发布流程见 [docs/PUBLISHING.md](docs/PUBLISHING.md)。

## 安全

请按 [SECURITY.md](SECURITY.md) 中的说明私下报告漏洞。重点关注：密钥或其他机密进入报告、
由中转站控制的文本向报告或界面注入标记、向已配置端点之外的地方发送数据，以及绕过 Web 界面
仅限本地防护的方法。

## 许可证

[Apache-2.0](LICENSE)
