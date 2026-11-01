# Installazione

> [🇬🇧 English](../../../guide/install.md) · [🇨🇳 中文](../../zh-CN/guide/install.md) · [🇫🇷 Français](../../fr/guide/install.md) · [🇪🇸 Español](../../es/guide/install.md) · [🇵🇹 Português](../../pt/guide/install.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/install.md) · [🇳🇴 Norsk](../../nb/guide/install.md)

Richiede Python 3.11+. Funziona su Linux, macOS e Windows (l'immagine Docker è Linux); su Windows le modalità riservate al proprietario della directory dei dati non hanno effetto, vedi [Sistemi operativi supportati](../../../reference/stability.md#os). Ognuna delle opzioni seguenti fornisce il comando `ekte`.

## Con pip

```bash
# da PyPI
pip install ekte

# oppure dai sorgenti
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

## Con [uv](https://docs.astral.sh/uv/)

```bash
# da PyPI, come strumento autonomo nel tuo PATH
uv tool install ekte

# oppure eseguirlo una volta senza installarlo
uvx --from ekte ekte --help

# oppure dai sorgenti, in un ambiente virtuale locale al progetto
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Puoi anche installarlo direttamente dal repository Git senza clonarlo:
`uv tool install git+https://github.com/mn567250/ekte`.

## Extra opzionali

- `web` — l'interfaccia web locale (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, da PyPI
pip install -e '.[web]'            # pip, dai sorgenti
uv tool install 'ekte[web]'  # uv, da PyPI
uv pip install -e '.[web]'         # uv, dai sorgenti
```

L'extra `tokenizers` non serve più: è vuoto e viene mantenuto solo
perché i vecchi comandi di installazione continuino a funzionare. ekte conta i
token con un'euristica integrata e non scarica nulla in fase di esecuzione
(nessun file di tokenizer), quindi funziona anche in ambienti con accesso
limitato o offline che raggiungono solo i relay che verifichi.

I rapporti PDF (`--format pdf` e il download PDF dell'interfaccia web) non
richiedono alcun extra: sono composti con
[ReportLab](https://www.reportlab.com/opensource/), una dipendenza in puro Python
che non richiede librerie di sistema su Linux, macOS o Windows.

## Con Docker (solo l'interfaccia web)

Da una copia dei sorgenti:

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# apri http://localhost:8000
```

Pubblica sempre la porta su `127.0.0.1`, come sopra. Variabili d'ambiente e cosa
protegge l'interfaccia: [Docker](docker.md).
