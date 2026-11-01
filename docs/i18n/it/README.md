# ekte — verifica della realtà dei relay LLM

> [🇬🇧 English](../../../README.md) · [🇨🇳 中文](../zh-CN/README.md) · [🇫🇷 Français](../fr/README.md) · [🇪🇸 Español](../es/README.md) · [🇵🇹 Português](../pt/README.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../de/README.md) · [🇳🇴 Norsk](../nb/README.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](../../../LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](../../../pyproject.toml)

**ekte** è uno strumento local-first che verifica se un relay di API (rivenditore
/ proxy) serve davvero il modello che dichiara — o se lo sostituisce di nascosto
con uno più economico, tronca la tua finestra di contesto, simula lo streaming o
gonfia la fatturazione dei token. In breve: ottieni ciò per cui paghi? Parla
l'**API OpenAI Chat Completions**, l'**API Anthropic Messages** e l'**API OpenAI
Responses** (`/v1/responses`) — rilevate automaticamente, o forzate con
`--api openai|anthropic|responses`.

Gli indichi l'endpoint di un relay e il modello che dice di servire; ekte esegue
una batteria di sonde black-box, confronta il comportamento osservato con una
base di conoscenza integrata di **98 profili di modelli di 7 fornitori** e
fornisce un verdetto chiaro, sostenuto da prove — da riga di comando, in
un'interfaccia web locale o in JSON per un altro strumento o LLM.

> ekte fornisce **prove black-box di scostamenti e rischi, non una prova
> crittografica di frode.** Vedi [Uso responsabile](guide/privacy.md#uso-responsabile).

## Perché

Il mercato delle chiavi di relay è pieno di offerte del tipo «GPT-4o a un decimo
del prezzo». Molte sono oneste. Alcune no — e quelle disoneste sono difficili da
scoprire a occhio nudo:

- Chiedi `gpt-4o`; di nascosto ti viene servito `gpt-4o-mini` o un modello aperto.
- Il relay pubblicizza un contesto da 1M di token ma lo tronca silenziosamente a 32K.
- Lo «streaming» è la risposta completa messa in buffer e rispezzettata, senza alcun guadagno di latenza.
- I token di `usage` riportati sono gonfiati, quindi il tuo credito si consuma più in fretta del dovuto.
- Un modello che dovrebbe supportare chiamate di strumenti / modalità JSON di nascosto non lo fa.

ekte trasforma un «qui qualcosa non torna» in un rapporto riproducibile.

## Installazione

Richiede Python 3.11+ su Linux, macOS o Windows.

```bash
pip install 'ekte[web]'          # oppure: uv tool install 'ekte[web]'
```

L'extra `web` aggiunge l'interfaccia web locale; omettilo per usare solo la riga
di comando. Dai sorgenti, con uv o in Docker: [Installazione](guide/install.md).

## Avvio rapido

```bash
export EKTE_API_KEY=sk-your-relay-key

# verificare un relay rispetto al modello che dichiara di servire
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard

# il controllo più forte: confronto con un riferimento affidabile dello stesso modello
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o

# oppure punta e clicca: l'interfaccia web locale
ekte serve
```

Altri esempi, file di configurazione e uso da script o agenti LLM:
[Avvio rapido](guide/quickstart.md). L'interfaccia web: [Interfaccia web](guide/web-ui.md).

## Cosa controlla

ekte assegna un punteggio a dieci dimensioni. Le quattro **dimensioni centrali** —
identità del modello, finestra di contesto, capacità dichiarate e fatturazione e
consumo — rivelano più direttamente una merce non conforme. I nomi sono quelli
dell'interfaccia web e dei rapporti.

| Dimensione | Id | Cosa rileva |
|---|---|---|
| **Identità del modello** | `model_identity` | Declassamento o sostituzione silenziosa del modello |
| **Finestra di contesto** | `context_window` | Troncamento silenzioso del contesto e «lost in the middle» |
| **Capacità dichiarate** | `capability` | Chiamate di strumenti, modalità JSON, output massimo o visione dichiarati ma non forniti |
| **Conformità del protocollo** | `protocol` | Parametri di richiesta e attributi di risposta scartati o ignorati |
| **Fatturazione e consumo** | `billing` | Consumo di token gonfiato o assente |
| **Connettività** | `connectivity` | Raggiungibilità dell'endpoint e l'elenco dei modelli pubblicizzato |
| **Autenticità dello streaming** | `streaming` | Streaming finto (buffer e poi spezzettamento) |
| **Affidabilità in concorrenza** | `reliability` | Errori e rallentamenti sotto carico concorrente |
| **Sicurezza del trasporto** | `security` | HTTP in chiaro, eco dei segreti, prompt di sistema iniettati, manomissioni |
| **Prestazioni** | `performance` | Quanto sono costanti latenza, tempo al primo token e throughput |

Come funziona ogni controllo e come si arriva al verdetto:
[Metodologia](guide/methodology.md).

## Documentazione

| Guida per l'utente | |
|---|---|
| [Installazione](guide/install.md) | pip, uv, dai sorgenti, extra opzionali |
| [Avvio rapido](guide/quickstart.md) | Prime verifiche, file di configurazione, uso da script e agenti LLM |
| [Interfaccia web](guide/web-ui.md) | Pagine, verifiche in background, analisi, lingue |
| [Suite e modalità di confronto](guide/suites.md) | Suite, suite personalizzata, riferimento affidabile, giudice LLM |
| [Prestazioni](guide/performance.md) | La sezione delle prestazioni, la sonda e i timeout delle richieste |
| [Monitoraggio](guide/monitoring.md) | Verifiche ripetute pianificate, avvisi via webhook, archiviazione delle chiavi API |
| [Verifiche di embedding, rerank, immagini e audio](guide/other-endpoints.md) | Verifiche di endpoint che non sono chat |
| [Base di conoscenza](guide/knowledge-base.md) | Profili dei modelli e come aggiungere i tuoi |
| [Rapporti](guide/reports.md) | Formati e contenuti dei rapporti |
| [Privacy e dati locali](guide/privacy.md) | Cosa resta sulla tua macchina; uso responsabile |
| [Bloccare la CI con una verifica di relay ekte](guide/github-action.md) | Subordinare un workflow di CI alla verifica di un relay |
| [Eseguire l'interfaccia web in Docker](guide/docker.md) | Eseguire l'interfaccia web in un container |
| [Metodologia](guide/methodology.md) | Ogni controllo, la sua scala dei punteggi e le sue avvertenze |
| [Se arrivi da zing](guide/migrating-from-zing.md) | Cosa cambia per un'installazione di zing esistente |

| Riferimento (in inglese) | |
|---|---|
| [Riga di comando](../../reference/cli.md) | Tutti i comandi e le opzioni, e i codici di uscita |
| [Schemi del rapporto e del webhook](../../reference/schemas.md) | I formati JSON e la loro `schema_version` |
| [Stabilità e compatibilità](../../reference/stability.md) | Cosa protegge semver, deprecazione, versioni di Python e sistemi supportati |
| [Registro delle modifiche](../../../CHANGELOG.md) | Cosa è cambiato in ogni versione |

Contribuire: [Guida ai contributi](../../CONTRIBUTING.md) e
[Guida per sviluppatori](../../dev/developer-guide.md) (in inglese).
Problemi di sicurezza: [Politica di sicurezza](../../SECURITY.md).

## Licenza

[Apache-2.0](../../../LICENSE)
