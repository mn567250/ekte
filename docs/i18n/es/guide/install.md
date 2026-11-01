# Instalación

> [🇬🇧 English](../../../guide/install.md) · [🇨🇳 中文](../../zh-CN/guide/install.md) · [🇫🇷 Français](../../fr/guide/install.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/install.md) · [🇮🇹 Italiano](../../it/guide/install.md) · [🇩🇪 Deutsch](../../de/guide/install.md) · [🇳🇴 Norsk](../../nb/guide/install.md)

Requiere Python 3.11+. Funciona en Linux, macOS y Windows (la imagen de Docker es Linux); en Windows los modos de solo propietario del directorio de datos no tienen efecto, consulta [Sistemas operativos compatibles](../../../reference/stability.md#os). Cualquiera de las opciones siguientes proporciona el comando `ekte`.

## Con pip

```bash
# desde PyPI
pip install ekte

# o desde el código fuente
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

## Con [uv](https://docs.astral.sh/uv/)

```bash
# desde PyPI, como herramienta independiente en tu PATH
uv tool install ekte

# o ejecutarlo una vez sin instalarlo
uvx --from ekte ekte --help

# o desde el código fuente, en un entorno virtual local del proyecto
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

También puedes instalarlo directamente desde el repositorio Git sin clonarlo:
`uv tool install git+https://github.com/mn567250/ekte`.

## Extras opcionales

- `web` — la interfaz web local (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, desde PyPI
pip install -e '.[web]'            # pip, desde el código fuente
uv tool install 'ekte[web]'  # uv, desde PyPI
uv pip install -e '.[web]'         # uv, desde el código fuente
```

El extra `tokenizers` ya no es necesario: está vacío y solo se
conserva para que los comandos de instalación antiguos sigan funcionando. ekte
cuenta los tokens con una heurística integrada y no descarga nada en tiempo de
ejecución (ningún archivo de tokenizer), así que también funciona en entornos
restringidos o sin conexión que solo alcanzan los relays que auditas.

Los informes PDF (`--format pdf` y la descarga en PDF de la interfaz web) no
necesitan ningún extra: se componen con
[ReportLab](https://www.reportlab.com/opensource/), una dependencia en Python puro
que no requiere bibliotecas del sistema en Linux, macOS ni Windows.

## Con Docker (solo la interfaz web)

Desde una copia del código fuente:

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# abre http://localhost:8000
```

Publica siempre el puerto en `127.0.0.1`, como arriba. Variables de entorno y qué
protege la interfaz: [Docker](docker.md).
