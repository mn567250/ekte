# 快速开始

> [🇬🇧 English](../../../guide/quickstart.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/quickstart.md) · [🇪🇸 Español](../../es/guide/quickstart.md) · [🇵🇹 Português](../../pt/guide/quickstart.md) · [🇮🇹 Italiano](../../it/guide/quickstart.md) · [🇩🇪 Deutsch](../../de/guide/quickstart.md) · [🇳🇴 Norsk](../../nb/guide/quickstart.md)

```bash
# 1) 按中转站声称的模型审计它（模型 id + 厂商提示）
export EKTE_API_KEY=sk-your-relay-key
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) 最强检测：与同款模型的可信基线对比
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) 审计 Anthropic 原生（Messages API）中转——协议根据 base_url/model 自动识别，
#    也可用 --api anthropic 强制指定
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) 确认疑似替换：用中转的“真实”模型 id 对照它被宣传成的模型画像来审计
#    （此例：一个豆包模型被当作 deepseek-v4-flash 出售）
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) 列出某个端点公布的模型
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) 查看知识库
ekte kb            # 全部画像及其来源
ekte kb deepseek   # 单个厂商

# 7) 生成可提交的配置文件
ekte init          # 写出 ekte.yaml
ekte check -c ekte.yaml
```

API 密钥可以直接填写，也可以写成 `env:VAR` 或 `file:/path`；报告里只会出现密钥的指纹。
完整的配置文件示例见 [`examples/ekte.yaml`](../../../../examples/ekte.yaml)。

配置文件带有格式版本（`version: 1`；没有版本的文件按格式 1 处理）。错误的类型和无效的值会被拒绝，并指明文件、行号和键；未知的键会给出警告并被忽略，自 ekte 1.0.0 起将被拒绝。`ekte config migrate` 可更新旧文件。模式见 [`docs/schemas/config.schema.json`](../../../schemas/config.schema.json)。

## 作为给大模型 / Agent 使用的工具

ekte 天生适合被其他程序或模型驱动。所有内容（包括错误）都以 JSON 输出到 stdout，
退出码即门禁。

```bash
# 精简、适合 Agent 的结论（比 --json 小约 5 倍：不含大体量证据）
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# 需要每条发现的证据时，输出完整结构化报告
ekte check --base-url ... --model gpt-4o --json

# 先算预算：会运行哪些检测器 + 预估 API 调用次数，且“不”发出任何请求
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# 以退出码做门禁（风险 >= medium 或分数低于 --fail-under 时退出码为 1）；
# 配置/用法错误以 JSON 输出并退出码 2
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# 机器可读的发现能力
ekte kb --json                      # 整个知识库
ekte models --base-url ... --json   # 某个端点公布了哪些模型
```

在 `--json`/`--compact` 模式下，配置错误会输出 `{"error": {...}}`（退出码 2），
而不是面向人的提示，方便流水线统一解析失败。
