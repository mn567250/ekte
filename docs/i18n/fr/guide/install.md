# Installation

> [🇬🇧 English](../../../guide/install.md) · [🇨🇳 中文](../../zh-CN/guide/install.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/install.md) · [🇵🇹 Português](../../pt/guide/install.md) · [🇮🇹 Italiano](../../it/guide/install.md) · [🇩🇪 Deutsch](../../de/guide/install.md) · [🇳🇴 Norsk](../../nb/guide/install.md)

Nécessite Python 3.11+. Fonctionne sous Linux, macOS et Windows (l'image Docker est Linux) ; sous Windows, les modes réservés au propriétaire du répertoire de données n'ont aucun effet, voir [Systèmes d'exploitation pris en charge](../../../reference/stability.md#os). Chacune des options ci-dessous fournit la commande `ekte`.

## Avec pip

```bash
# depuis PyPI
pip install ekte

# ou depuis les sources
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

## Avec [uv](https://docs.astral.sh/uv/)

```bash
# depuis PyPI, comme outil autonome dans votre PATH
uv tool install ekte

# ou l'exécuter une fois sans l'installer
uvx --from ekte ekte --help

# ou depuis les sources, dans un environnement virtuel local au projet
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows : .venv\Scripts\activate
```

Vous pouvez aussi installer directement depuis le dépôt Git sans le cloner :
`uv tool install git+https://github.com/mn567250/ekte`.

## Extras optionnels

- `web` — l'interface web locale (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, depuis PyPI
pip install -e '.[web]'            # pip, depuis les sources
uv tool install 'ekte[web]'  # uv, depuis PyPI
uv pip install -e '.[web]'         # uv, depuis les sources
```

L'extra `tokenizers` n'est plus nécessaire : il est vide et
n'est conservé que pour que les anciennes commandes d'installation fonctionnent
encore. ekte compte les tokens avec une heuristique intégrée et ne télécharge
rien à l'exécution (aucun fichier de tokenizer), si bien qu'il fonctionne aussi
dans des environnements restreints ou hors ligne qui n'atteignent que les relais
que vous auditez.

Les rapports PDF (`--format pdf` et le téléchargement PDF de l'interface web) ne
demandent aucun extra : ils sont composés avec
[ReportLab](https://www.reportlab.com/opensource/), une dépendance en pur Python,
sans bibliothèque système sous Linux, macOS ou Windows.

## Avec Docker (interface web uniquement)

Depuis une copie des sources :

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# ouvrir http://localhost:8000
```

Publiez toujours le port sur `127.0.0.1` comme ci-dessus. Variables
d'environnement et ce qui protège l'interface : [Docker](docker.md).
