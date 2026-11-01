# 安装

> [🇬🇧 English](../../../guide/install.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/install.md) · [🇪🇸 Español](../../es/guide/install.md) · [🇵🇹 Português](../../pt/guide/install.md) · [🇮🇹 Italiano](../../it/guide/install.md) · [🇩🇪 Deutsch](../../de/guide/install.md) · [🇳🇴 Norsk](../../nb/guide/install.md)

需要 Python 3.11+。支持 Linux、macOS 和 Windows（Docker 镜像为 Linux）；在 Windows 上，数据目录的仅所有者权限模式不起作用，详见[支持的操作系统](../../../reference/stability.md#os)。以下任一方式都会提供 `ekte` 命令。

## 使用 pip

```bash
# 从 PyPI 安装
pip install ekte

# 或从源码安装
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

## 使用 [uv](https://docs.astral.sh/uv/)

```bash
# 从 PyPI 安装为独立工具，加入 PATH
uv tool install ekte

# 或不安装、直接运行一次
uvx --from ekte ekte --help

# 或从源码安装到项目本地的虚拟环境
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows：.venv\Scripts\activate
```

也可以不克隆，直接从 Git 仓库安装：
`uv tool install git+https://github.com/mn567250/ekte`。

## 可选附加项

- `web` —— 本地 Web 界面（`ekte serve`）。

```bash
pip install 'ekte[web]'      # pip，从 PyPI
pip install -e '.[web]'            # pip，从源码
uv tool install 'ekte[web]'  # uv，从 PyPI
uv pip install -e '.[web]'         # uv，从源码
```

不再需要 `tokenizers` 附加项：它是空的，保留它只是为了让旧的安装命令仍然可用。
ekte 用内置的启发式方法计数 token，运行时不下载任何东西（也不下载分词器文件），因此在只能访问
被检测中转站的受限或离线环境中同样可以运行。

PDF 报告（`--format pdf` 以及 Web 界面中的 PDF 下载）无需任何附加项：由
[ReportLab](https://www.reportlab.com/opensource/) 排版，这是一个纯 Python 依赖，在 Linux、macOS 和
Windows 上都不需要系统库。

## 使用 Docker（仅 Web 界面）

在源码目录中：

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# 打开 http://localhost:8000
```

端口务必像上面这样只发布到 `127.0.0.1`。环境变量以及保护界面的措施见
[Docker](docker.md)。
