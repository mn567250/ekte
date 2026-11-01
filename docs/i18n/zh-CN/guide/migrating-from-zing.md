# 从 zing 迁移

> [🇬🇧 English](../../../guide/migrating-from-zing.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/migrating-from-zing.md) · [🇪🇸 Español](../../es/guide/migrating-from-zing.md) · [🇵🇹 Português](../../pt/guide/migrating-from-zing.md) · [🇮🇹 Italiano](../../it/guide/migrating-from-zing.md) · [🇩🇪 Deutsch](../../de/guide/migrating-from-zing.md) · [🇳🇴 Norsk](../../nb/guide/migrating-from-zing.md)

ekte 以新名称延续 [zing](https://github.com/cenbonew/zing)（其最后一个版本为
0.11.0）。对已有安装而言的变化：

- **包与命令。** `pip install ekte`（原为 `zing-audit`），命令 `ekte`（原为
  `zing`），Python 包 `ekte`。附加项名称不变，例如 `pip install 'ekte[web]'`。
  两个包既不共用命令也不共用模块，因此 `zing-audit` 可以与 ekte 同时安装。
- **环境变量。** `EKTE_*` 取代 `ZING_*`（`EKTE_DATA_DIR`、`EKTE_SECRET_KEY`、
  `EKTE_HOST` 等）。只要对应的 `EKTE_*` 未设置，旧的 `ZING_*` 变量仍然有效；
  ekte 会在 stderr 上提示一次。
- **数据目录。** 首次运行时，如果 `~/.ekte` 尚不存在，ekte 会把 `~/.zing`
  复制到 `~/.ekte`（历史记录、监控、知识库），此后只使用 `~/.ekte`。
  `~/.zing` 保持原样，供仍在运行的 zing 使用；不再需要时请自行删除。通过
  `EKTE_DATA_DIR`、`ZING_DATA_DIR` 或 `--data-dir` 指定的目录按原样使用。
- **Web 界面。** 语言、主题和筛选设置，以及保存在浏览器密码管理器中的主密钥
  都会沿用。zing 的经典界面已经移除：它的地址（`/tools`、`/console`）会打开检测页面（`/`）。
- **报告与探测。** 报告、webhook 和文件名都使用 `ekte`（例如
  `"tool": "ekte"`、`ekte-report.json`），发送给中转站的探测请求也是如此。
  在其中查找 `zing` 的脚本需要更新。
- **时间表。** 整个兼容层（`ZING_*` 回退、`~/.zing` 复制、浏览器设置、Cookie 与已保存主密钥的沿用，以及经典界面的地址）已弃用，将在 ekte **1.0.0** 中移除（1.0.0rc1 是第一个不含它的版本）。在此之前每一部分都照常工作，其提示会写明这个版本；旧的 `/v2/…` 页面地址同样跳转到 1.0.0。ekte 绝不会删除旧的 `~/.zing`，即使复制功能被移除也一样。
