# Installation

> [🇬🇧 English](../../../guide/install.md) · [🇨🇳 中文](../../zh-CN/guide/install.md) · [🇫🇷 Français](../../fr/guide/install.md) · [🇪🇸 Español](../../es/guide/install.md) · [🇵🇹 Português](../../pt/guide/install.md) · [🇮🇹 Italiano](../../it/guide/install.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/install.md)

Erfordert Python 3.11+. Läuft unter Linux, macOS und Windows (das Docker-Image ist Linux); unter Windows haben die Nur-Besitzer-Modi des Datenverzeichnisses keine Wirkung, siehe [Unterstützte Betriebssysteme](../../../reference/stability.md#os). Jede der folgenden Varianten stellt den Befehl `ekte` bereit.

## Mit pip

```bash
# von PyPI
pip install ekte

# oder aus dem Quellcode
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

## Mit [uv](https://docs.astral.sh/uv/)

```bash
# von PyPI, als eigenständiges Werkzeug in Ihrem PATH
uv tool install ekte

# oder einmalig ausführen, ohne zu installieren
uvx --from ekte ekte --help

# oder aus dem Quellcode, in eine projektlokale virtuelle Umgebung
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Sie können auch direkt aus dem Git-Repository installieren, ohne es zu klonen:
`uv tool install git+https://github.com/mn567250/ekte`.

## Optionale Extras

- `web` — die lokale Weboberfläche (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, von PyPI
pip install -e '.[web]'            # pip, aus dem Quellcode
uv tool install 'ekte[web]'  # uv, von PyPI
uv pip install -e '.[web]'         # uv, aus dem Quellcode
```

Das Extra `tokenizers` wird nicht mehr gebraucht: Es ist leer und
bleibt nur erhalten, damit ältere Installationsbefehle weiter funktionieren. ekte
zählt Token mit einer eingebauten Heuristik und lädt zur Laufzeit nichts herunter
(keine Tokenizer-Dateien), läuft also auch in eingeschränkten oder Offline-Umgebungen,
die nur die geprüften Relays erreichen.

PDF-Berichte (`--format pdf` und der PDF-Download in der Weboberfläche) brauchen
kein Extra: Sie werden mit [ReportLab](https://www.reportlab.com/opensource/)
gesetzt, einer reinen Python-Abhängigkeit ohne Systembibliotheken unter Linux, macOS
und Windows.

## Mit Docker (nur Weboberfläche)

Aus einem Checkout des Quellcodes:

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# http://localhost:8000 öffnen
```

Veröffentlichen Sie den Port immer wie gezeigt an `127.0.0.1`. Umgebungsvariablen
und was die Oberfläche schützt: [Docker](docker.md).
