# 套件与对比模式

> [🇬🇧 English](../../../guide/suites.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/suites.md) · [🇪🇸 Español](../../es/guide/suites.md) · [🇵🇹 Português](../../pt/guide/suites.md) · [🇮🇹 Italiano](../../it/guide/suites.md) · [🇩🇪 Deutsch](../../de/guide/suites.md) · [🇳🇴 Norsk](../../nb/guide/suites.md)

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

## 自定义套件

只运行你关心的维度，节省时间和 token。每个所选维度下的所有检测器都会以 `deep` 深度运行：

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` 可重复或用逗号分隔，并隐含 `--suite custom`；配置文件中使用
`run.dimensions: [protocol, performance]`。可选维度为 `connectivity`、`protocol`、
`context_window`、`model_identity`、`capability`、`streaming`、`billing`、`reliability`、
`security` 和 `performance`。Web 界面中，`custom` 套件按钮会在检测页和监控中打开
同样的选择（**检测维度**）。

**综合分只按所选维度加权平均**；未选的维度标为“未选择”。风险结论同样只基于所选维度：
未选择模型身份时，结论只涵盖所选维度，不说明实际提供的是哪个模型，并会注明这一点。

## 对比模式与 LLM 裁判

ekte 有两种检测模式：

- **纯代码（默认）：** 除 `quality_judge` 外，所有检测器都由确定性代码判定——指纹、上下文扫描、
  计费算术、流式计时。不需要第二个模型，结果可复现。
- **代码 + LLM 混合（`--judge`）：** 额外请一个*可信*的裁判模型（单独配置，绝不是被测目标）
  判断目标的回答是否像所声称的模型——质量、推理深度这类纯代码难以判定的模糊信号。
  这就是 `quality_judge` 检测器。

```bash
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

**对比模式**（`ekte compare`，或 Web 界面中的**对照可信基线**）在同一时间对所声称模型的可信基线
发送完全相同的探测。这是最有力的确认手段：身份回答、被拒绝的请求参数、篡改金丝雀和
性能都会并排比较，而且只有使用基线时，结论的置信度才可能达到*高*。未指定 `--judge-base-url` 时，
对比模式会把基线用作裁判。
