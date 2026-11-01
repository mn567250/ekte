# 在 Docker 中运行 Web 界面

> [🇬🇧 English](../../../guide/docker.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/docker.md) · [🇪🇸 Español](../../es/guide/docker.md) · [🇵🇹 Português](../../pt/guide/docker.md) · [🇮🇹 Italiano](../../it/guide/docker.md) · [🇩🇪 Deutsch](../../de/guide/docker.md) · [🇳🇴 Norsk](../../nb/guide/docker.md)

`ekte serve` 是一个没有登录功能的单用户工具。在容器之外，它只监听回环地址（`127.0.0.1`、`::1`、
`localhost`），拒绝任何其他绑定地址。容器是唯一的例外：服务器必须监听容器自身的网络接口，
Docker 的端口发布才能访问到它。

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# 打开 http://localhost:8000
```

**务必只发布到 `127.0.0.1`**（`-p 127.0.0.1:8000:8000`，而不是 `-p 8000:8000`）。
单纯的 `-p 8000:8000` 会把界面——以及输入其中或保存在监控里的每一个 API 密钥——暴露到你的网络上。

## 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `EKTE_CONTAINER` | 未设置（镜像中为 `1`） | 允许绑定非回环地址。ekte 还会检查自己是否确实运行在容器中（`/.dockerenv`、`/run/.containerenv` 或 Kubernetes）；在普通主机上设置它不会让服务器对外开放。 |
| `EKTE_HOST` | `127.0.0.1`（镜像中为 `0.0.0.0`） | 绑定地址。任何非回环地址都需要 `EKTE_CONTAINER=1`。`--host` 优先于它。 |
| `EKTE_PORT` | `8000` | 容器内的端口。`--port` 优先于它。 |
| `EKTE_DATA_DIR` | `~/.ekte`（镜像中为 `/data`） | 检测历史、监控（包括它们的 API 密钥）以及你自己添加的知识库条目。在此挂载一个卷即可保留它们。 |
| `EKTE_SECRET_KEY` | 未设置 | 加密监控所保存 API 密钥的主密钥：**监控**页面（或 `ekte secret rotate`）显示给你的密钥，或 `file:/run/secrets/ekte_key` / `env:VAR`。未设置时，每次容器启动后都要在**监控**页面输入该密钥。它从不保存在 `EKTE_DATA_DIR` 中。在全新的数据目录上设置它会选择加密保存密钥；不设置时，监控的 API 密钥完全不保存，每次容器启动后都必须重新输入。见下文。 |
| `EKTE_KB_DIR` | 未设置 | 额外的知识库 YAML 目录，例如以只读方式挂载（`-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb`）。 |
| `EKTE_NO_USER_KB` | 未设置 | 设为 `1` 时忽略你在界面中添加的知识库条目（`kb.db`）。 |
| `EKTE_ALLOWED_HOSTS` | 未设置 | 以逗号分隔的额外主机名，如果你不是通过 `localhost`/`127.0.0.1` 访问界面，界面也会响应这些名字。 |

**从 zing 镜像迁移。** 把 `-e ZING_*` 选项改名为 `EKTE_*`。如果某个 `EKTE_*` 变量未设置，ekte
仍会读取对应的 `ZING_*` 变量，但镜像自己设置了 `EKTE_CONTAINER`、`EKTE_HOST`、`EKTE_PORT` 和
`EKTE_DATA_DIR`，因此旧的 `ZING_HOST`、`ZING_PORT` 或 `ZING_DATA_DIR` 在容器中不起作用。数据卷
仍位于 `/data`，非特权用户仍为 uid 10001，因此现有的 `zing-data` 卷可以原样挂载
（`-v zing-data:/data`）。`ZING_*` 回退已弃用，将在 ekte 1.0.0 中移除
（见[稳定性政策](../../../reference/stability.md#deprecation-zing)）。

## 界面的保护措施

- **主机白名单。** `Host` 请求头不是 `localhost`、`127.0.0.1`、`[::1]`，也不在
  `EKTE_ALLOWED_HOSTS` 中的请求会被拒绝。这能阻止 DNS 重绑定攻击，即网站把自己的域名指向
  `127.0.0.1` 来与本地服务器通信。端口不做检查，因此任何发布的主机端口都可以使用。
- **来源和 JSON 检查。** 来自其他来源的修改状态的请求会被拒绝，请求体必须是
  `application/json`，因此其他网站无法向本地 API 提交表单。
- **安全响应头。** 界面不能被其他网站嵌入框架（`X-Frame-Options`、`frame-ancestors`），
  页面也不会发出任何 referrer。
- **加密的监控密钥。** 保存的 API 密钥用一个从不写入数据卷的主密钥加密，因此数据卷的副本
  不会泄露任何 API 密钥。没有 `EKTE_SECRET_KEY` 时，**监控**页面会在创建主密钥时显示一次，
  并在每次容器启动后要求输入；需要它的监控会一直等待。若希望无人值守地重启，可以把它作为
  Docker secret 传入（服务器将其保存在内存中；每个数据卷只运行一个服务器进程）：

  ```bash
  # 监控页面显示给你的密钥，或一个新密钥：ekte secret rotate
  docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data \
    -v "$PWD/ekte_key:/run/secrets/ekte_key:ro" \
    -e EKTE_SECRET_KEY=file:/run/secrets/ekte_key ekte
  ```

  与已保存 API 密钥所用密钥不一致的 `EKTE_SECRET_KEY` 会被拒绝（界面会提示）。用
  `ekte secret rotate` 轮换；丢失的密钥只能在**监控**页面重置，这会删除已保存的 API 密钥。
- **仅所有者可访问的数据。** 数据目录以 `0700` 创建，每个数据库文件都是 `0600`；镜像以
  非特权用户运行。
