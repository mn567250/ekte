# Installasjon

> [🇬🇧 English](../../../guide/install.md) · [🇨🇳 中文](../../zh-CN/guide/install.md) · [🇫🇷 Français](../../fr/guide/install.md) · [🇪🇸 Español](../../es/guide/install.md) · [🇵🇹 Português](../../pt/guide/install.md) · [🇮🇹 Italiano](../../it/guide/install.md) · [🇩🇪 Deutsch](../../de/guide/install.md) · **🇳🇴 Norsk**

Krever Python 3.11+. Kjører på Linux, macOS og Windows (Docker-bildet er Linux); på Windows har eier-modusene til datamappen ingen virkning, se [Støttede operativsystemer](../../../reference/stability.md#os). Alle alternativene nedenfor gir deg kommandoen `ekte`.

## Med pip

```bash
# fra PyPI
pip install ekte

# eller fra kildekoden
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

## Med [uv](https://docs.astral.sh/uv/)

```bash
# fra PyPI, som et frittstående verktøy på PATH
uv tool install ekte

# eller kjør den én gang uten å installere
uvx --from ekte ekte --help

# eller fra kildekoden, inn i et virtuelt miljø lokalt i prosjektet
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Du kan også installere rett fra Git-repoet uten å klone:
`uv tool install git+https://github.com/mn567250/ekte`.

## Valgfrie tillegg

- `web` — det lokale nettgrensesnittet (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, fra PyPI
pip install -e '.[web]'            # pip, fra kildekoden
uv tool install 'ekte[web]'  # uv, fra PyPI
uv pip install -e '.[web]'         # uv, fra kildekoden
```

Tillegget `tokenizers` trengs ikke lenger: det er tomt og beholdes bare så eldre
installasjonskommandoer fortsatt virker. ekte teller tokens med en innebygd
heuristikk og laster ikke ned noe under kjøring (ingen tokenizer-filer), så den
kjører også i begrensede eller frakoblede miljøer som bare når releene du
reviderer.

PDF-rapporter (`--format pdf`, og PDF-nedlastingen i nettgrensesnittet) trenger
ikke noe tillegg: de settes med [ReportLab](https://www.reportlab.com/opensource/),
en ren Python-avhengighet som ikke trenger systembiblioteker på Linux, macOS eller
Windows.

## Med Docker (bare nettgrensesnittet)

Fra en utsjekk av kildekoden:

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# åpne http://localhost:8000
```

Publiser alltid porten på `127.0.0.1` som vist. Miljøvariabler og hva som
beskytter grensesnittet: [Docker](docker.md).
