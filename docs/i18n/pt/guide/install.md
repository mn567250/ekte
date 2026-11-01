# Instalação

> [🇬🇧 English](../../../guide/install.md) · [🇨🇳 中文](../../zh-CN/guide/install.md) · [🇫🇷 Français](../../fr/guide/install.md) · [🇪🇸 Español](../../es/guide/install.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/install.md) · [🇩🇪 Deutsch](../../de/guide/install.md) · [🇳🇴 Norsk](../../nb/guide/install.md)

Requer Python 3.11+. Funciona em Linux, macOS e Windows (a imagem Docker é Linux); no Windows os modos só para o proprietário do diretório de dados não têm efeito, consulte [Sistemas operativos suportados](../../../reference/stability.md#os). Qualquer uma das opções abaixo disponibiliza o comando `ekte`.

## Com pip

```bash
# a partir do PyPI
pip install ekte

# ou a partir do código-fonte
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

## Com [uv](https://docs.astral.sh/uv/)

```bash
# a partir do PyPI, como ferramenta autónoma no seu PATH
uv tool install ekte

# ou executá-lo uma vez sem instalar
uvx --from ekte ekte --help

# ou a partir do código-fonte, num ambiente virtual local do projeto
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Também pode instalar diretamente a partir do repositório Git sem o clonar:
`uv tool install git+https://github.com/mn567250/ekte`.

## Extras opcionais

- `web` — a interface web local (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, a partir do PyPI
pip install -e '.[web]'            # pip, a partir do código-fonte
uv tool install 'ekte[web]'  # uv, a partir do PyPI
uv pip install -e '.[web]'         # uv, a partir do código-fonte
```

O extra `tokenizers` já não é necessário: está vazio e só é
mantido para que os comandos de instalação antigos continuem a funcionar. O ekte
conta os tokens com uma heurística integrada e não descarrega nada em tempo de
execução (nenhum ficheiro de tokenizer), pelo que também funciona em ambientes
restritos ou offline que só alcançam os relays que audita.

Os relatórios PDF (`--format pdf` e a transferência em PDF da interface web) não
precisam de nenhum extra: são compostos com
[ReportLab](https://www.reportlab.com/opensource/), uma dependência em Python puro
que não precisa de bibliotecas de sistema em Linux, macOS ou Windows.

## Com Docker (apenas a interface web)

A partir de uma cópia do código-fonte:

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# abra http://localhost:8000
```

Publique sempre a porta em `127.0.0.1`, como acima. Variáveis de ambiente e o
que protege a interface: [Docker](docker.md).
