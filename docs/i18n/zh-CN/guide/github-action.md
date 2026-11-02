# 用 ekte 中转站检测为 CI 把关

> [🇬🇧 English](../../../guide/github-action.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/github-action.md) · [🇪🇸 Español](../../es/guide/github-action.md) · [🇵🇹 Português](../../pt/guide/github-action.md) · [🇮🇹 Italiano](../../it/guide/github-action.md) · [🇩🇪 Deutsch](../../de/guide/github-action.md) · [🇳🇴 Norsk](../../nb/guide/github-action.md)

`ekte` 提供一个可复用的 **GitHub 组合 action（composite action）**，当中转站偏离它声称提供的模型时，
你可以让构建失败、阻止部署，或运行定时健康检查。

action 在内部运行：

```
ekte check --base-url … --api-key env:… --model … --suite … \
           --fail-on-risk <level> --compact
```

它解析紧凑的 JSON 结论，把 `risk` / `score` / `rating` 作为步骤输出（step outputs）提供，
在运行的 **Summary** 标签页写入一份简明摘要，并由 `ekte` 自身的退出码让作业失败（风险关卡
触发时退出码为 `1`，配置错误时为 `2`）。

> API 密钥通过环境变量传给 `ekte`（`--api-key env:…`），因此它从不出现在命令行中，也从不被回显。
> 请始终从仓库 secret 中提供它。

## 快速开始

```yaml
# .github/workflows/relay-audit.yml
name: Relay audit
on:
  schedule:
    - cron: "0 6 * * *"   # 每天 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.1   # 固定到一个标签——见下文“版本固定”
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

## 输入

| 输入                | 必填 | 默认值        | 说明 |
| ------------------- | ---- | ------------- | ---- |
| `base-url`          | 是   | —             | 中转站基础地址，例如 `https://relay.example.com/v1`。 |
| `api-key`           | 是   | —             | 中转站 API 密钥。请传入 secret：`${{ secrets.RELAY_API_KEY }}`。从不回显。 |
| `model`             | 是   | —             | 请求中实际发送的模型 id。 |
| `claimed-model`     | 否   | `""`          | 中转站声称提供的模型（如果与 `model` 不同）。 |
| `api`               | 否   | `auto`        | 线上协议：`auto` \| `openai` \| `anthropic` \| `responses`。 |
| `declared-provider` | 否   | `""`          | 用于知识库查找的厂商提示（`openai`、`anthropic`、`deepseek`……）。 |
| `suite`             | 否   | `standard`    | 检测套件：`smoke` \| `standard` \| `deep` \| `full`。 |
| `fail-on-risk`      | 否   | `high`        | 风险 `>=` 该级别时让作业失败：`low` \| `medium` \| `high`。 |
| `python-version`    | 否   | `3.12`        | 用于安装和运行 `ekte` 的 Python 版本。 |
| `version`           | 否   | `ekte`  | pip 安装规格。若要可复现的运行请固定版本，例如 `ekte==0.33.1`。 |

## 输出

| 输出     | 说明 |
| -------- | ---- |
| `risk`   | 风险级别：`clean` \| `low` \| `medium` \| `high` \| `inconclusive`。 |
| `score`  | 综合分 `0`–`100`（如果 `ekte` 无法为中转站评分，则为空字符串）。 |
| `rating` | 结论中的可读评级（可能为空）。 |

## 以中转站健康状况为部署把关

先运行检测，只有通过时才部署。由于风险关卡触发时检测步骤会让作业失败，`needs:` 它的依赖作业
就不会运行。

```yaml
name: Deploy
on:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  relay-health:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.1
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          claimed-model: gpt-4o
          fail-on-risk: medium   # 风险为中或更高时阻止部署
    outputs:
      risk: ${{ steps.ekte.outputs.risk }}
      score: ${{ steps.ekte.outputs.score }}

  deploy:
    needs: relay-health          # 只有检测通过关卡时才运行
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "Relay is healthy (risk=${{ needs.relay-health.outputs.risk }}, \
            score=${{ needs.relay-health.outputs.score }}). Deploying…"
          # ./deploy.sh
```

## 版本固定

请把 action 固定到一个**发布标签**（`mn567250/ekte@v0.33.1`），而不是会变动的分支。这能让检测
可复现，并避免 action 发生意外变化。标签可以被移动；若要最严格的供应链保护，请固定到该发布的
完整提交 SHA，并在注释中写明版本（`mn567250/ekte@<full-commit-sha> # v0.33.1`），再让 Dependabot
保持更新。若要完全可复现的 CLI 行为，还应把 `version` 输入固定到一个确切的发布版本，例如
`version: ekte==0.33.1`。

可直接复制的定时运行示例见
[`.github/workflows/example-audit.yml`](../../../../.github/workflows/example-audit.yml)。
