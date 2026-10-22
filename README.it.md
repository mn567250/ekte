# zing — verifica della realtà dei relay LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** è uno strumento local-first che verifica se un relay di API (rivenditore
/ proxy) serve davvero il modello che dichiara — o se lo sostituisce di nascosto
con uno più economico, tronca la tua finestra di contesto, simula lo streaming o
gonfia la fatturazione dei token. In breve: ottieni ciò per cui paghi? Parla
l'**API OpenAI Chat Completions**, l'**API Anthropic Messages** e l'**API OpenAI
Responses** (`/v1/responses`) — rilevate automaticamente, o forzate con
`--api openai|anthropic|responses`.

Gli indichi l'endpoint di un relay e il modello che dice di servire; zing esegue
una batteria di sonde black-box, confronta il comportamento osservato con una
base di conoscenza integrata di **98 profili di modelli di 7 fornitori** e
fornisce un verdetto chiaro, sostenuto da prove — da riga di comando, in
un'interfaccia web locale o in JSON per un altro strumento o LLM.

> zing fornisce **prove black-box di scostamenti e rischi, non una prova
> crittografica di frode.** Vedi [Uso responsabile](#uso-responsabile).

Questo README è per chi **usa** zing. Come zing viene costruito, testato e
pubblicato è nella [Guida per sviluppatori](DEVELOPER_GUIDE.it.md); come funziona
e come viene valutato ogni controllo, nella [Metodologia](docs/METHODOLOGY.it.md).

---

## Indice

- [Perché](#perché)
- [Installazione](#installazione)
- [Avvio rapido](#avvio-rapido)
- [Interfaccia web (`zing serve`)](#interfaccia-web-zing-serve)
- [Cosa controlla](#cosa-controlla)
- [Come si arriva al verdetto](#come-si-arriva-al-verdetto)
- [Suite](#suite)
- [Prestazioni](#prestazioni)
- [Modalità di confronto e giudice LLM](#modalità-di-confronto-e-giudice-llm)
- [Monitoraggio](#monitoraggio)
- [Verifiche di embedding, rerank, immagini e audio](#verifiche-di-embedding-rerank-immagini-e-audio)
- [Uso in CI (GitHub Action)](#uso-in-ci-github-action)
- [Base di conoscenza](#base-di-conoscenza)
- [Rapporti](#rapporti)
- [Privacy e dati locali](#privacy-e-dati-locali)
- [Uso responsabile](#uso-responsabile)
- [Altra documentazione](#altra-documentazione)
- [Licenza](#licenza)

## Perché

Il mercato delle chiavi di relay è pieno di offerte del tipo «GPT-4o a un decimo
del prezzo». Molte sono oneste. Alcune no — e quelle disoneste sono difficili da
scoprire a occhio nudo:

- Chiedi `gpt-4o`; di nascosto ti viene servito `gpt-4o-mini` o un modello aperto.
- Il relay pubblicizza un contesto da 1M di token ma lo tronca silenziosamente a 32K.
- Lo «streaming» è la risposta completa messa in buffer e rispezzettata, senza alcun guadagno di latenza.
- I token di `usage` riportati sono gonfiati, quindi il tuo credito si consuma più in fretta del dovuto.
- Un modello che dovrebbe supportare chiamate di strumenti / modalità JSON di nascosto non lo fa.

zing trasforma un «qui qualcosa non torna» in un rapporto riproducibile.

## Installazione

Richiede Python 3.10+. Ognuna delle opzioni seguenti fornisce il comando `zing`.

### Con pip

```bash
# da PyPI
pip install zing-audit

# oppure dai sorgenti
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Con [uv](https://docs.astral.sh/uv/)

```bash
# da PyPI, come strumento autonomo nel tuo PATH
uv tool install zing-audit

# oppure eseguirlo una volta senza installarlo
uvx --from zing-audit zing --help

# oppure dai sorgenti, in un ambiente virtuale locale al progetto
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Puoi anche installarlo direttamente dal repository Git senza clonarlo:
`uv tool install git+https://github.com/cenbonew/zing`.

### Extra opzionali

- `web` — l'interfaccia web locale (`zing serve`).

```bash
pip install 'zing-audit[web]'      # pip, da PyPI
pip install -e '.[web]'            # pip, dai sorgenti
uv tool install 'zing-audit[web]'  # uv, da PyPI
uv pip install -e '.[web]'         # uv, dai sorgenti
```

L'extra `tokenizers` non serve più: dalla 0.19.0 è vuoto e viene mantenuto solo
perché i vecchi comandi di installazione continuino a funzionare. zing conta i
token con un'euristica integrata e non scarica nulla in fase di esecuzione
(nessun file di tokenizer), quindi funziona anche in ambienti con accesso
limitato o offline che raggiungono solo i relay che verifichi.

I rapporti PDF (`--format pdf` e il download PDF dell'interfaccia web) non
richiedono alcun extra: sono composti con
[ReportLab](https://www.reportlab.com/opensource/), una dipendenza in puro Python
che non richiede librerie di sistema su Linux, macOS o Windows.

### Con Docker (solo l'interfaccia web)

Da una copia dei sorgenti:

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# apri http://localhost:8000
```

Pubblica sempre la porta su `127.0.0.1`, come sopra. Dettagli e variabili
d'ambiente: [Guida per sviluppatori → Docker](DEVELOPER_GUIDE.it.md#docker) e
[docs/DOCKER.md](docs/DOCKER.md).

## Avvio rapido

```bash
# 1) verificare un relay rispetto a ciò che dichiara (id del modello + indizio sul fornitore)
export ZING_API_KEY=sk-la-tua-chiave-del-relay
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) il controllo più forte: confronto con un riferimento affidabile dello stesso modello
export OPENAI_API_KEY=sk-la-tua-chiave-openai
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) verificare un relay nativo Anthropic (API Messages) — il protocollo è rilevato
#    automaticamente da base_url/model, o forzato con --api anthropic
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) confermare una sostituzione sospetta: verificare l'id REALE del modello del relay rispetto
#    al profilo con cui viene venduto (qui: un modello Doubao spacciato per deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) elencare i modelli che un endpoint pubblicizza
zing models --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY

# 6) consultare la base di conoscenza
zing kb            # tutti i profili, con la loro origine
zing kb deepseek   # un fornitore

# 7) generare una configurazione da versionare
zing init          # scrive zing.yaml
zing check -c zing.yaml
```

Le chiavi API si possono indicare in chiaro, come `env:VAR` o come
`file:/percorso`; i rapporti contengono sempre e solo un'impronta della chiave.
Un file di configurazione completo è in [`examples/zing.yaml`](examples/zing.yaml).

### Come strumento per un LLM / agente

zing è pensato per essere pilotato da un altro programma o modello. Tutto va su
stdout in JSON, errori compresi, e il codice di uscita fa da barriera.

```bash
# verdetto snello, adatto agli agenti (~5x più piccolo di --json: senza le prove voluminose)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# rapporto strutturato completo quando ti servono le prove di ogni rilevazione
zing check --base-url ... --model gpt-4o --json

# prima il budget: quali rilevatori girano + chiamate API stimate, SENZA farne nessuna
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# barriera sul codice di uscita (1 se il rischio >= medium, o il punteggio è sotto --fail-under);
# gli errori di configurazione/uso escono con 2, in JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# scoperta leggibile dalle macchine
zing kb --json                      # l'intera base di conoscenza
zing models --base-url ... --json   # cosa pubblicizza un endpoint
```

In modalità `--json`/`--compact` una configurazione errata stampa
`{"error": {...}}` (codice di uscita 2) invece di un messaggio per persone,
così una pipeline può gestire i fallimenti in modo uniforme.

## Interfaccia web (`zing serve`)

Preferisci cliccare? Un'interfaccia web locale avvolge lo stesso motore — senza
riga di comando.

```bash
pip install 'zing-audit[web]'     # oppure: uv tool install 'zing-audit[web]'
zing serve                        # apre http://localhost:8000
```

Nella nuova interfaccia il modulo guida la configurazione:

1. Scegli il **Relay / provider**: un provider della base di conoscenza o un
   relay che hai salvato. Il suo URL di base viene compilato (gli altri URL noti
   del provider sono offerti come suggerimenti). Per qualsiasi altro relay
   scegli **Altro (inserisci l'URL)** e inserisci l'**URL dell'intermediario**.
2. Aggiungi la **Chiave API** se il relay ne richiede una.
3. zing elenca da solo i modelli del relay (alla scelta di un relay e ogni volta
   che cambiano URL o chiave; **Aggiorna modelli** chiede di nuovo). Scegli il
   **Modello richiesto**. Un relay senza elenco di modelli ripiega
   sull'inserimento dell'id (**Inserisci a mano**).
4. Facoltativamente scegli il **Modello dichiarato** tra i modelli della base di
   conoscenza: il modello che il relay dice di servire. Se il modello richiesto
   è nella base di conoscenza viene preselezionato; cambialo solo se il relay
   vende il modello con un altro nome. Da esso deriva il profilo del provider
   usato per la verifica.

Un relay non ancora in elenco si può conservare con **Salva nella base** con un
nome a tua scelta; la volta successiva basta sceglierlo. Il riferimento
affidabile (**Confronta con un riferimento affidabile**) e la pagina
**Strumenti** si configurano allo stesso modo. L'interfaccia classica mantiene i
campi semplici con **Recupera modelli**.

Poi **Avvia
verifica** e segui i controlli **in tempo reale**: ogni controllo mostra il suo
punteggio e quanto è durato, e un controllo con rilevazioni si espande per
mostrare le prove. Il risultato è un rapporto con il verdetto da condividere:
voto, **Controlli per dimensione** con le loro scale dei punteggi, rilevazioni in
linguaggio chiaro e la sezione prestazioni (nella nuova interfaccia anche un
**Registro di esecuzione** di ogni rilevatore).

Tutto gira sulla tua macchina: una chiave digitata nel browser raggiunge solo il
tuo server zing locale e il relay che verifichi, mai terze parti. Vedi
[Privacy e dati locali](#privacy-e-dati-locali).

### Pagine

L'interfaccia web esiste in due versioni che condividono lo stesso server e gli
stessi dati. L'**interfaccia classica** si apre su `/`; il suo link **Prova la
nuova interfaccia** passa alla **nuova interfaccia** sotto `/v2/`, il cui link
**Interfaccia classica** riporta indietro. La scelta è ricordata per browser.

| Pagina | Interfaccia classica | Nuova interfaccia | A cosa serve |
|---|---|---|---|
| **Verifica** | `/` | `/v2/` | Verificare un relay (eventualmente rispetto a un riferimento) e leggere il rapporto |
| **Console** | `/console` | — | La stessa verifica come console compatta, in stile registro |
| **Strumenti** | `/tools` | `/v2/tools` | Verifiche di embedding e rerank |
| **Cronologia** | `/history` | `/v2/history` | Ogni verifica eseguita su questa macchina, raggruppata per relay + modello dichiarato, con tendenze |
| **Analisi** | — | `/v2/analytics` | Relay e modelli confrontati nel tempo: indicatori, grafici con tabelle di dati, classifiche |
| **Monitor** | `/watches` | `/v2/watches` | Verifiche ripetute pianificate con avvisi via webhook |
| **Conoscenza** | — | `/v2/kb` | La base di conoscenza in tre schede — modelli, provider, relay: sfogliare, attivare/disattivare, aggiungere i propri |

La nuova interfaccia aggiunge: filtri e tendenze configurabili (punteggio, voto,
latenza p50, token/s) nella **Cronologia**; **Pianifica come monitor** e **Riesegui audit** su ogni
esecuzione della Cronologia; **Scarica il rapporto** in tutti i formati; un
selettore del tema (Automatico / Chiaro / Scuro); e la pagina **Conoscenza**.

**Audit in background (nuova interfaccia).** Un audit avviato dalla pagina
**Audit** continua quando cambi pagina o chiudi la scheda; **Continua in
background** ce lo manda di proposito. La **Cronologia** elenca ogni audit in
coda e in corso (e ogni monitor in esecuzione) con il suo avanzamento; **Guarda
dal vivo** riapre la vista live, che recupera tutto ciò che è già successo. Gli
audit dello stesso relay vengono eseguiti uno dopo l'altro, così non falsano i
rispettivi risultati di latenza o affidabilità (tutti gli indirizzi loopback
contano come un solo host, quindi anche i modelli serviti dalla tua macchina
attendono); gli audit di relay diversi vengono eseguiti in parallelo, al massimo
quattro alla volta (`ZING_MAX_PARALLEL_AUDITS`). I monitor attendono il loro
relay allo stesso modo.

**Analisi (nuova interfaccia).** `/v2/analytics` trasforma la cronologia
locale in confronti: indicatori per il periodo scelto (esecuzioni, punteggio
mediano, quota ad alto rischio, tasso di successo, TTFT, velocità di output,
rapporti di fatturazione) con la variazione rispetto al periodo precedente di
pari durata; un grafico di qualsiasi metrica per relay, modello o relay ×
modello, per ora, giorno o settimana (linea mediana con la fascia p25–p75, fino
a quattro serie, ogni grafico anche come tabella di dati); e una classifica dei
relay per un modello o dei modelli di un relay. I relay sono raggruppati per
voce della knowledge base (relay salvati e provider), quindi rinominare un relay
ne raggruppa di nuovo la cronologia. Gli intervalli con meno di 3 esecuzioni
sono attenuati — un singolo audit può essere un valore anomalo; un monitor
fornisce misurazioni regolari. Le esecuzioni più vecchie mostrano ciò che hanno
misurato: la pagina dice su quante esecuzioni si basa un valore. Per
impostazione predefinita confronta una suite e una modalità di sonda (le più
frequenti), per non mescolare esecuzioni diverse; filtri e vista restano
nell'URL, quindi una vista si può salvare nei preferiti o condividere. Nulla
lascia la macchina.

Altri pannelli rispondono a domande più specifiche: **ore di punta** (una mappa
di calore giorno della settimana × ora di TTFT, latenza e velocità di decodifica (mediana e code p95 / p5), jitter
tra token, tempi di rete e del relay, tasso di successo o di
errore nel tuo fuso orario: un relay rallenta o fallisce di più nelle ore di
maggior carico? Per giorno della settimana oppure, con 90 giorni di esecuzioni,
su un ciclo di 4 settimane e, con 180 giorni, per settimana del mese), **errori e affidabilità** (chiamate fallite per causa: limiti
di frequenza (HTTP 429), errori del server (5xx), timeout, errori di rete; nel
tempo e per relay o modello, dai registri delle richieste salvati, indicando
quanti audit li hanno), **integrità del modello** (esiti dei controlli di
identità, finestra di contesto e capacità per relay × modello, la quota di
audit in cui il modello restituito è diverso e la quota misurata della
finestra di contesto dichiarata), **fatturazione e token** (rapporti di
fatturazione nel tempo rispetto alla linea del 100%: sopra, il relay dichiara
più token di quanti ne abbia contati zing; più le quote di token di
ragionamento e di input in cache) e **sovraccarico del relay** (il tempo di
elaborazione dichiarato dal relay accanto al round trip di rete).

**Schede e link da condividere (Analisi).** I pannelli sono in cinque schede —
**Panoramica** (indicatori, classifica), **Andamenti** (confronto nel tempo, ore
di punta), **Affidabilità** (errori, overhead del relay), **Integrità del
modello** e **Fatturazione** — sotto l’intestazione della pagina e un pannello
dei filtri comune; si carica solo la scheda che stai guardando. L’URL conserva
la scheda, i filtri e ogni opzione dei grafici
(`#tab=reliability&range=30&relay=…&eb=dow_hour`), e **Copia il link a questa
vista** lo copia (o lo mostra in un campo da copiare se il browser non lo
consente): il link apre esattamente quella vista. Il pannello dei filtri è lo
stesso in **Cronologia** e **Analisi**: chiuso, indica quanti filtri sono
attivi e li nomina in una riga (ad es. «Ultimi 30 giorni · standard · Streaming
· Example Relay»), così una vista condivisa dice cosa mostra.

### Lingue

Un menu della lingua nell'intestazione di ogni pagina passa l'interfaccia tra
**🇬🇧 inglese** (predefinito), **🇨🇳 cinese** (l'interfaccia originale),
**🇫🇷 francese**, **🇪🇸 spagnolo**, **🇵🇹 portoghese**, **🇮🇹 italiano** e
**🇩🇪 tedesco**; la scelta è ricordata per browser.

I rapporti scaricati dall'interfaccia (**Scarica il rapporto**: JSON, Markdown,
HTML o PDF) seguono la lingua scelta: le chiavi JSON, i valori enumerati
(`risk_level`, `status`, `severity`, …), gli id e le prove restano esattamente
come nel rapporto della CLI (il JSON resta un rapporto zing valido), mentre i
valori leggibili (titolo e riepilogo del verdetto, titoli e riepiloghi delle
rilevazioni, raccomandazioni, nomi dei rilevatori, note) vengono tradotti, e il
nome del file porta la lingua (`zing-report.it.json`, `zing-report.it.pdf`). I
titoli di sezione dei file Markdown/HTML/PDF sono in inglese. I rapporti della
CLI con `--format json|md|html|pdf` restano in inglese.

**I prompt inviati all'endpoint verificato non seguono la lingua
dell'interfaccia.** Ogni testo che zing invia a un'API di LLM è in inglese, così
lo stesso relay riceve lo stesso verdetto chiunque legga il rapporto (i controlli
delle risposte e le stime dei token sono calibrati su quei testi esatti). Le sole
eccezioni sono le impronte della base di conoscenza la cui lingua *è* la misura —
per esempio le sonde di scioltezza in cinese, di tokenizer e di
autoidentificazione dei modelli cinesi. Ogni rapporto registra le lingue di sonda
effettivamente usate (`prompt_languages`, per es. `["en", "zh"]`).
`started_at` registra quando è iniziata la verifica (UTC); lo `start_ms` di ogni
record di richiesta conta da quel momento.

## Cosa controlla

zing assegna un punteggio a dieci dimensioni. Le quattro **dimensioni centrali** —
identità del modello, finestra di contesto, capacità dichiarate e fatturazione e
consumo — rivelano più direttamente una merce non conforme. I nomi sono quelli
dell'interfaccia web e dei rapporti.

| Dimensione | Id | Peso | Cosa rileva |
|---|---|---|---|
| **Identità del modello** | `model_identity` | 21 | Declassamento o sostituzione silenziosa del modello — autoidentificazione, data di cutoff delle conoscenze, impronte del tokenizer, il campo `model` restituito; facoltativamente un giudice LLM |
| **Finestra di contesto** | `context_window` | 19 | Troncamento silenzioso del contesto (dichiara 1M, il richiamo fallisce a 32K) e «lost in the middle» dovuto a strati economici di RAG/riassunto, con ago nel pagliaio e ricerca binaria |
| **Capacità dichiarate** | `capability` | 13 | Chiamate di strumenti / modalità JSON / schema JSON / output massimo dichiarati ma non forniti (o forniti *oltre*, indizio di un sostituto); **visione** — un modello che dichiara input immagine deve leggere un'immagine generata a risposta nota |
| **Conformità del protocollo** | `protocol` | 8 | Conformità sul filo: multi-turno, sequenze di stop, schema degli errori; ogni parametro di richiesta accettato (e rispettato quando visibile), ogni attributo di risposta presente; cache delle risposte che ignora temperature/seed |
| **Fatturazione e consumo** | `billing` | 8 | Gonfiamento di token/consumo e contabilizzazione assente o non verificabile, con una stima euristica indipendente dei token |
| **Connettività** | `connectivity` | 7 | Raggiungibilità dell'endpoint e l'elenco `/v1/models` pubblicizzato |
| **Autenticità dello streaming** | `streaming` | 6 | Streaming finto (buffer e poi spezzettamento), dal numero dei frammenti e dalla loro spaziatura |
| **Affidabilità in concorrenza** | `reliability` | 6 | Tasso di successo e latenza sotto carico concorrente (la limitazione HTTP 429 è contata a parte) |
| **Sicurezza del trasporto** | `security` | 6 | HTTPS, igiene delle intestazioni, eco dei segreti; un prompt di sistema iniettato nascosto; manomissione in transito di risposte e chiamate di strumenti (canarini a risposta nota); cache del prefisso del prompt (tempi) |
| **Prestazioni** | `performance` | 6 | Quanto sono *costanti* latenza, tempo al primo token e throughput, il tasso di errore e il rallentamento sotto carico; la velocità solo rispetto a un riferimento (vedi [Prestazioni](#prestazioni)) |

La [Metodologia](docs/METHODOLOGY.it.md) descrive ogni sonda, il trucco del relay a
cui risponde, la sua scala dei punteggi e le sue avvertenze sui falsi positivi.

## Come si arriva al verdetto

In breve (i dettagli sono nella [Metodologia](docs/METHODOLOGY.it.md#come-zing-assegna-i-punteggi)):

- Ogni rilevatore pubblica la propria **scala dei punteggi** — ogni esito
  possibile di ogni controllo con i suoi punti — e l'interfaccia web la mostra
  sotto **Scala dei punteggi**.
- Il **punteggio di una dimensione** è la media a pari peso dei punteggi dei suoi
  rilevatori. Una rilevazione ALTA/CRITICA impone **Fallito** e una rilevazione
  MEDIA porta **Superato** ad **Avviso**, qualunque sia il punteggio. I rapporti
  lo spiegano per dimensione in **Dimension details**; nell'interfaccia web ogni
  riga dei **Controlli per dimensione** si espande negli stessi dettagli.
- Il **punteggio di salute complessivo** è la media ponderata delle dimensioni eseguite
  (pesi sopra), con voto A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) o F.
- Il **verdetto di rischio** dipende dalla gravità delle rilevazioni, non dal
  punteggio:

| Rischio | Etichetta nell'interfaccia | Quando |
|---|---|---|
| `inconclusive` | Segnale insufficiente | Niente di utilizzabile da giudicare: identità del modello, finestra di contesto e capacità dichiarate sono state eseguite senza risultato utilizzabile (relay irraggiungibile, modello non presente nella base di conoscenza), o nessuna dimensione oltre alla connettività ne ha prodotto uno |
| `high` | Merce non conforme | Una rilevazione CRITICA, una rilevazione ALTA/CRITICA in una dimensione centrale, o due o più rilevazioni ALTE |
| `medium` | Scostamenti rilevati | Esattamente una rilevazione ALTA fuori dalle dimensioni centrali, o una rilevazione MEDIA in una dimensione centrale |
| `low` | Per lo più affidabile | Qualsiasi altra rilevazione MEDIA |
| `clean` | Coerente (probabilmente autentico) | Nessuno dei casi precedenti |

Le rilevazioni della dimensione connettività non alzano mai il rischio: un relay
irraggiungibile o limitato non ha potuto essere valutato, e questo non prova che
risponda un altro modello. L'**affidabilità** del verdetto (bassa / media / alta)
cresce con il numero di dimensioni centrali che hanno prodotto un risultato, con
un riferimento e con il giudice LLM.

Gli avvisi di trasporto — HTTP in chiaro (`security.tls`) e fallimenti o code lente
sotto carico (`reliability.*`) — abbassano il punteggio della loro dimensione ma
non alzano neppure il rischio di sostituzione; il riepilogo li elenca come avvisi.
Risposte manomesse e una chiave API rimandata indietro lo alzano ancora. HTTP in
chiaro verso questa macchina o una rete privata è solo un avviso di gravità bassa,
perché la chiave non la lascia mai. Un profilo della base di conoscenza abbinato
solo in modo approssimativo (fuzzy) limita l'affidabilità a bassa, e un rilevatore
senza alcuna risposta utilizzabile è non conclusivo, mai un superamento.

## Suite

| Suite | Rilevatori | Costo |
|---|---|---|
| `smoke` | connectivity, security | molto basso |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | basso–medio |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (con `--judge`) | più alto (le sonde di contesto lungo e di temporizzazione costano token) |
| `full` | i rilevatori di `deep`, con le prestazioni misurate con e senza streaming | il più alto |
| `custom` | solo le dimensioni che scegli, alla profondità di `deep` | secondo la selezione |

La sonda della finestra di contesto è limitata da `--max-context-tokens` (200K
per impostazione predefinita), così verificare un modello da 1M di token resta
sostenibile. `--only` / `--skip` eseguono o escludono singoli rilevatori per id.
Una finestra più grande del limite di `--max-context-tokens` è riportata come *verificata fino al limite*, mai come troncata.

### Suite personalizzata

Esegui solo le dimensioni che ti interessano, risparmiando tempo e token. Ogni
rilevatore di ogni dimensione scelta viene eseguito, come in `deep`:

```bash
zing check --base-url ... --model gpt-4o -D protocol -D performance
zing check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` è ripetibile o separato da virgole e implica `--suite custom`;
in un file di configurazione usa `run.dimensions: [protocol, performance]`. Le
dimensioni sono `connectivity`, `protocol`, `context_window`, `model_identity`,
`capability`, `streaming`, `billing`, `reliability`, `security` e
`performance`. Nell'interfaccia web il pulsante di suite `custom` apre la stessa
scelta (**Dimensioni da eseguire**) nella pagina di verifica, nella console e nei
monitor.

Il **punteggio complessivo è la media ponderata delle sole dimensioni scelte**;
quelle escluse compaiono come «non selezionate». Anche il verdetto di rischio si
basa sulle dimensioni scelte: senza l'identità del modello copre solo quelle,
non quale modello viene servito, e lo dice.

## Prestazioni

Ogni rapporto contiene una sezione **performance**: latenza, tempo al primo token
(TTFT), token/s di decodifica e end-to-end, latenza e jitter tra frammenti, tassi
di errore/timeout/429, una scomposizione di rete (connessione TCP, TLS, un giro
`GET /models`, tempo del server) e avvio a freddo, ciascuno come count / min /
mean / p50 / p75 / p90 / p95 / p99 / max / stdev.

Quando la sonda dedicata viene eseguita, assegna il punteggio alla dimensione
**Prestazioni**. Il punteggio misura la **costanza**, non la velocità pura, quindi
un endpoint lento ma costante (un modello locale o self-hosted) non viene
penalizzato per non essere un data center:

| Controllo | Valutato su |
|---|---|
| costanza di latenza / TTFT | rapporto di coda p90 ÷ p50 (≤ 1,3 costante 100 · ≤ 1,75 stabile 85 · ≤ 2,5 variabile 65 · oltre: irregolare 40); servono ≥ 10 campioni |
| costanza del throughput | rapporto di coda p50 ÷ p10 dei token/s, stesse fasce |
| errori | richieste di sonda fallite: ≤ 2 % 100 · ≤ 10 % 80 · oltre: 50 (i 429 non contano) |
| stabilità sotto carico | latenza p50 in raffica ÷ p50 sequenziale: ≤ 1,5x 100 · ≤ 3x 80 · oltre: 55 |
| cache hit | prompt unici serviti da una cache: 60 |
| riferimento | token/s rispetto al riferimento affidabile o, in mancanza, all'intervallo pubblicato per il modello nella base di conoscenza: in linea 100 · più lento: non conteggiato (informativo, mai un fallimento) · ≥ 2x più veloce 60 (indizio di un modello più piccolo) · nessun riferimento: non conteggiato |

Le rilevazioni sulle prestazioni sono al massimo di gravità bassa: spostano il
punteggio, mai il verdetto di rischio. Senza la sonda (`standard` senza
riferimento, `smoke`), la dimensione non viene eseguita ed esce dal punteggio
complessivo.

- **standard** raccoglie la sezione dalle richieste della verifica stessa.
- **deep / full / custom** aggiungono una sonda dedicata: 100 richieste non
  memorizzabili in cache da 128 token di output (un id di richiesta casuale apre
  ogni prompt; non vengono inviati parametri di cache né di ragionamento) più una
  raffica a `--concurrency`. Regolala con `--performance-requests` (0 la
  disattiva) e `--performance-max-tokens`.
- La sonda usa lo streaming per impostazione predefinita;
  `--performance-non-streaming` (o il selettore **Streaming / Senza streaming**
  dell'interfaccia web) misura i relay che non supportano lo streaming. **full**
  misura entrambe le modalità, alternate, e le mostra affiancate.
- **compare** esegue la sonda su entrambi gli endpoint, alternando le richieste,
  e aggiunge una tabella obiettivo-vs-riferimento (5 richieste per lato in
  `standard`, troppo poche per i controlli di costanza) le cui differenze sono
  segnate in verde ✓ dove l'obiettivo è migliore e in rosso ✗ dove è peggiore.

I token vengono contati due volte — dall'`usage` del relay e localmente —, così il
throughput è misurabile anche senza `usage`. Il conteggio locale è una stima
fatta con un'euristica integrata (circa ±15-20%; nessun tokenizer viene usato o
scaricato), e la sezione lo indica sempre. Un percentile viene mostrato solo con
campioni sufficienti (p90 da 10, p95 da 20, p99 da 100). Il rapporto JSON conserva
i tempi di ogni richiesta (solo numeri, nessun testo); il rapporto HTML e
l'interfaccia web li tracciano sulla linea temporale della verifica.

Gli audit eseguiti contemporaneamente in `zing serve` (più schede del browser,
monitor) non falsano i rispettivi tempi: la preparazione che impegna la CPU,
come la costruzione dei lunghi prompt della finestra di contesto, viene eseguita
fuori dall'event loop del server.

**Timeout delle richieste.** `timeout_sec` (`--timeout`, predefinito 60 s) è la
base; ogni richiesta riceve tempo in più in base alla dimensione del prompt e al
budget di output, così una lunga sonda della finestra di contesto o un modello
self-hosted lento non viene interrotto dopo un minuto. Gli host locali e privati
(`localhost`, `127.x`, `192.168.x`, `host.docker.internal`, …) hanno almeno 300 s.
`max_request_sec` (`--max-request-time`, predefinito 900 s) è il limite massimo di
ogni singola richiesta, stream compresi, quindi nessuna richiesta può restare
appesa all'infinito. Una sonda della finestra di contesto che va comunque in
timeout è riportata come non conclusiva, non come troncamento.

## Modalità di confronto e giudice LLM

zing ha due modalità di rilevamento:

- **Solo codice (predefinita):** tutti i rilevatori tranne `quality_judge`
  decidono con codice deterministico — impronte, scansione del contesto,
  aritmetica della fatturazione, tempi dello streaming. Non serve un secondo
  modello; i risultati sono riproducibili.
- **Ibrida codice + LLM (`--judge`):** interroga inoltre un modello giudice
  *affidabile* (configurato a parte, mai l'obiettivo) per capire se le risposte
  dell'obiettivo somigliano al modello dichiarato — segnali sfumati come la
  qualità e la profondità di ragionamento che il solo codice non può decidere. È
  il rilevatore `quality_judge`.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

La **modalità di confronto** (`zing compare`, o **Confronta con un riferimento
affidabile** nell'interfaccia web) esegue le stesse sonde, nello stesso momento,
contro un riferimento affidabile del modello dichiarato. È la via di conferma più
forte: risposte d'identità, parametri di richiesta rifiutati, canarini di
manomissione e prestazioni vengono giudicati fianco a fianco, e solo un
riferimento permette all'affidabilità del verdetto di essere *alta*. Senza
`--judge-base-url`, la modalità di confronto usa il riferimento come giudice.

## Monitoraggio

Un relay può servire il modello vero oggi e sostituirlo di nascosto la settimana
prossima. `zing watch` ripete la verifica secondo una pianificazione, registra
ogni esecuzione nella cronologia e avvisa un webhook quando il rischio supera una
soglia o **peggiora** rispetto all'esecuzione precedente.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang it                                     # oppure --once per cron
```

Gli avvisi sono formattati per **Slack / Feishu / DingTalk / JSON generico**,
rilevati automaticamente dall'URL del webhook, e scritti nella lingua degli avvisi
— inglese per impostazione predefinita; `--alert-lang en|zh|fr|es|pt|it|de`. Il
payload JSON generico mantiene neutri chiavi e valori macchina (`risk_level`,
`score`, …), traduce quelli leggibili (`text`, `headline`, `key_findings`) e
indica la `language`.

**Nell'interfaccia web**, `zing serve` esegue gli stessi monitor in uno
scheduler in background all'interno del processo del server, registra ogni
esecuzione nella **Cronologia** e invia gli stessi avvisi via webhook:

- **Nuova interfaccia:** apri un'esecuzione nella **Cronologia** e scegli
  **Pianifica come monitor**. zing copia la configurazione di quell'esecuzione
  (relay, modello, modello dichiarato, fornitore, suite, dimensioni
  personalizzate) in un monitor in pausa nella pagina **Monitor**; lì imposta
  l'intervallo e la chiave API (la Cronologia non salva mai le chiavi) e
  attivalo. Intervallo, chiave, **Soglia di avviso**, webhook e **Lingua degli
  avvisi** si modificano direttamente su ogni monitor.
- **Interfaccia classica:** compila il modulo della pagina **Monitor** e scegli
  **Aggiungi monitor**.

Ogni monitor ha la propria lingua degli avvisi (per impostazione predefinita
quella dell'interfaccia), si può eseguire subito, mettere in pausa o eliminare,
e resta legato al profilo della base di conoscenza con cui è stato creato finché
non lo ricolleghi.

I monitor in scadenza vengono eseguiti contemporaneamente, ciascuno come audit a
sé, ma mai più di un audit alla volta per host di relay e al massimo
`ZING_MAX_PARALLEL_AUDITS` in totale; un'esecuzione attende che si liberi un posto
(anche un audit avviato a mano può finire in coda dietro ai monitor in
esecuzione). L'orario di un'esecuzione è quello in cui inizia il suo audit, dopo
un'eventuale attesa. Il controllo di regressione confronta con l'esecuzione
salvata più recente dello stesso relay e modello, a prescindere da quante altre
esecuzioni siano state salvate nel frattempo. I webhook di avviso di
un'esecuzione vengono inviati contemporaneamente, così uno lento o non
raggiungibile non blocca gli altri. Le chiavi sono salvate cifrate nella tua
directory dei dati locale e non vengono mai restituite al browser.

**Chiave principale.** Le chiavi API dei monitor sono cifrate con una chiave
principale che zing non scrive mai su disco. La prima volta che salvi una chiave
API, la pagina **Monitor** la crea e la mostra una sola volta: copiala o
scaricala, conservala in un gestore di password (il browser può salvarla) e
incollala di nuovo per confermare. Dopo ogni riavvio di `zing serve` la pagina
la richiede (il browser può compilarla); fino ad allora i monitor che ne hanno
bisogno aspettano, mentre quelli senza chiave o con chiavi `env:`/`file:`
continuano a girare. La barra di stato della pagina offre anche **Blocca**,
**Ruota** e **Chiave dimenticata?** (scarta le chiavi API cifrate così puoi
reinserirle). Per un uso non presidiato o con Docker, passa la chiave come
`ZING_SECRET_KEY` (vedi [docs/DOCKER.md](docs/DOCKER.md));
`zing secret status | export | rotate` la gestiscono da riga di comando.

## Verifiche di embedding, rerank, immagini e audio

Questi endpoint restituiscono vettori, classifiche, immagini o audio invece di
chat, quindi zing li verifica con sonde mirate invece dei prompt di chat. Ognuno
stampa un verdetto e supporta `--json` e `--fail-on-risk`.

### Tipo di endpoint (superficie), monitor di embedding e rerank

Ogni verifica, riga della cronologia e monitor ha un **tipo di endpoint**
(`surface`): `chat` (predefinito), `embedding` o `rerank`. È indipendente dalla
suite. Le verifiche di embedding e rerank passano per lo stesso runner, lo stesso
punteggio (0–100, A–F), la cronologia, l'analisi e i monitor delle verifiche di
chat; cambiano solo i rilevatori. Cronologia e analisi filtrano per tipo di
endpoint, e l'analisi mostra solo le metriche pertinenti.

Per monitorare un endpoint di embedding o rerank, verificalo nella pagina
**Strumenti** e scegli **Monitora**, oppure **Pianifica come monitor** sulla sua
riga della cronologia. Il monitor ripete la verifica secondo la pianificazione, con
lo stesso fissaggio della base di conoscenza, la stessa soglia di avviso e gli
stessi avvisi di regressione di un monitor di chat, e controlla la **deriva**
rispetto alla sua esecuzione precedente (i vettori di una sonda di embedding, la
classifica e i punteggi di una sonda di rerank). La dimensione dichiarata di un
monitor di embedding si modifica sulla sua scheda (vuota o 0: dalla base di
conoscenza). Le sonde di velocità (embedding: latenza, avvio a freddo, input/s,
scalabilità a lotti; rerank: latenza, avvio a freddo, documenti/s, 4 contro 32
documenti) girano solo nelle suite deep, full o custom, o in standard con una
baseline.

### Embedding e rerank

```bash
# La dimensione del vettore attesa è ricavata dalla base di conoscenza per il modello dichiarato.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Oppure indicare direttamente la dimensione attesa:
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: una sonda integrata a risposta nota — un vero reranker deve mettere
# al primo posto il documento palesemente pertinente.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank

# Più a fondo: aggiunge la sonda di velocità del rerank; --no-save tiene l'esecuzione fuori dalla cronologia.
zing rerank --base-url ... --model my-rerank --suite deep --no-save
# Vedere prima i controlli e le chiamate stimate, senza inviare richieste:
zing rerank --base-url ... --model my-rerank --dry-run
```

`rerank` controlla la connettività, la **sonda a risposta nota** (il documento
chiaramente pertinente deve finire primo), il campo `model` restituito, il
determinismo (la stessa query due volte dà la stessa classifica e gli stessi
punteggi) e la **deriva della classifica** rispetto all'esecuzione salvata
precedente. `zing embed` e `zing rerank` accettano `--suite`, `--save/--no-save`
(salvato per impostazione predefinita, così l'esecuzione successiva ha un
riferimento di deriva) e `--dry-run`.

`embed` controlla la connettività, la **corrispondenza della dimensione**
(lunghezza del vettore restituito rispetto alla dimensione nativa del modello
dichiarato — il segnale principale di merce non conforme: un relay che dichiara
`text-embedding-3-large` a 3072-d ma restituisce 1024-d serve un sostituto), il
determinismo (stesso input → coseno ≈ 1), la distinzione (input non correlati →
coseno nettamente sotto 1) e il campo `model` restituito. Profili integrati:
OpenAI `text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Entrambi sono anche nella pagina **Strumenti** dell'interfaccia web (**Verifica
embedding**, **Verifica rerank**). La verifica rerank usa sempre le sonde
integrate, così ogni esecuzione resta confrontabile per la deriva e il
monitoraggio.

### Generazione di immagini e audio (TTS)

Generazione di immagini (`POST /v1/images/generations`) e sintesi vocale
(`POST /v1/audio/speech`), decodificate con la sola libreria standard di Python —
dimensioni dell'immagine dai byte dell'intestazione (PNG/JPEG/GIF/WebP), durata
WAV tramite `wave`.

```bash
# Un relay che dichiara DALL·E 3 restituisce davvero il 1792x1024 richiesto? Un'immagine
# ridotta o di dimensioni errate (o fuori dalle dimensioni native del modello dichiarato,
# secondo la base di conoscenza) è il segnale principale di merce non conforme.
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Un relay che dichiara tts-1-hd restituisce audio vero la cui durata cresce con l'input
# (non un segnaposto fisso, non HTML/JSON travestito da audio)?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` controlla la connettività, un formato valido e decodificabile, la
**corrispondenza delle dimensioni** (larghezza × altezza decodificate rispetto alla
richiesta e alle dimensioni native del modello dichiarato — FAIL/HIGH in caso di
discrepanza), la distinzione (due prompt → immagini diverse, per smascherare un
segnaposto fisso), il numero e il campo `model`. `audio` controlla la
connettività, la validità del contenitore/formato, il rispetto del formato, una
durata non banale che cresce con l'input, la distinzione e il campo `model`. La
base di conoscenza include OpenAI DALL·E 2/3, gpt-image-1,
tts-1/tts-1-hd/gpt-4o-mini-tts e profili immagine/TTS di Qwen.

## Uso in CI (GitHub Action)

Subordina qualsiasi workflow a una verifica del relay con l'action composita
inclusa. Esegue `zing check --compact --fail-on-risk`, espone `risk` / `score` /
`rating` come output, scrive un riepilogo nell'esecuzione e fa fallire il job
quando scatta la barriera di rischio.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.20.0         # fissare a un tag di rilascio
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # secret del chiamante; mai mostrato
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

La chiave del relay viene passata tramite una variabile d'ambiente
(`--api-key env:…`), quindi non compare mai su una riga di comando. Vedi
[docs/CI.md](docs/CI.md) per tutti gli input e output e un esempio di barriera sul
deploy.

## Base di conoscenza

zing giudica un relay in base al **profilo** del modello che dichiara: finestra di
contesto nativa, output massimo, data di cutoff delle conoscenze, tokenizer,
capacità, parole chiave d'identità e impronte comportamentali. I profili integrati
coprono OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM e Moonshot
(`zing kb` li elenca). Ci sono tre livelli; i successivi prevalgono:

1. Profili **integrati**, un file YAML per fornitore in
   [`zing/knowledge/data/`](zing/knowledge/data).
2. **Una directory con i tuoi file YAML**: `--kb-dir ./my-profiles` (ripetibile)
   o `ZING_KB_DIR`.
3. **Le tue voci** (`kb.db` nella directory dei dati), aggiunte senza file YAML né
   installazione modificabile:
   - nella pagina **Conoscenza** dell'interfaccia web (`/v2/kb`), con una scheda
     per **Modelli**, **Provider** e **Relay**. Ogni scheda elenca l'insieme
     completo — inclusi, `ZING_KB_DIR` e tuoi (contrassegnati **Tuo**) — con un
     filtro, un interruttore per elemento e un modulo **Aggiungi …**: **Aggiungi un
     modello** → **Copia il prompt di ricerca** nell'assistente IA che preferisci,
     carica o incolla lo YAML con cui risponde, poi **Verifica e salva**;
     **Aggiungi un provider** accetta YAML di provider allo stesso modo; **Aggiungi
     un relay** chiede un nome e un URL di base. **Quale profilo usa un ID di
     modello?** mostra come si risolve un id; le tue voci si possono esportare in
     YAML;
   - nelle pagine **Verifica** e **Strumenti** dell'interfaccia web: **Salva
     nella base** conserva nome e URL di base di un relay (una voce di provider
     senza modelli), elencato in **Conoscenza → Relay**;
   - da riga di comando: `zing kb-prompt <model>`, `zing kb-import <file>`
     (aggiungi `--check` per limitarti a verificarlo) e `zing kb-export`.

Prima di salvare una voce zing la controlla: schema e limiti, espressioni regolari
pericolose, ogni prompt che invierebbe e id di modello che verrebbero risolti in un
altro profilo. Un tuo modello con l'id di uno integrato lo sostituisce (segnalato
come *oscuramento*), ma non modifica mai le impostazioni proprie di un fornitore
integrato; le impronte vengono unite per id. Disattivare un modello, provider o
relay incluso nella pagina **Conoscenza** viene salvato anch'esso in `kb.db`: un id
di modello disattivato non viene più risolto, un provider disattivato porta con sé
i suoi modelli e URL di base. `zing check` e `zing serve` usano esattamente gli
stessi profili; `--no-user-kb` (o `ZING_NO_USER_KB=1`) esclude le tue voci e i tuoi
interruttori.

Un modello con `identity_keywords` vuoto non viene salvato così: zing completa
le sue parole di marchio a partire dai nomi del provider e del modello (per
esempio `glm` e `z.ai`) e mostra un avviso
per controllarle, perché senza di esse il controllo d'identità potrebbe
scambiare il produttore del modello per un marchio rivale. Il prompt di ricerca
le chiede esplicitamente all'assistente IA.

Ogni rapporto registra il profilo rispetto a cui ha verificato (`knowledge`:
fornitore, modello, come è stato risolto l'id, la sua origine e un'istantanea
completa con il suo hash del contenuto), così un rapporto resta verificabile anche
dopo che la base di conoscenza è cambiata.

## Rapporti

`zing check` e `zing compare` stampano un verdetto e scrivono il rapporto in
`reports/` (`--out-dir`) come JSON, Markdown, HTML e PDF (`--format all`, il
predefinito); `--format json|md|html|pdf` scrive un solo formato. `--json` e
`--compact` stampano invece su stdout.

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

Un rapporto contiene il verdetto (rischio, affidabilità, punteggio, voto), le
rilevazioni principali con le raccomandazioni, i punteggi per dimensione e i
**Dimension details**, le rilevazioni di ogni rilevatore con le prove, la sezione
prestazioni, il profilo della base di conoscenza usato e le lingue di sonda. Il
testo controllato dal relay viene oscurato ed escapato prima di essere scritto.

## Privacy e dati locali

- **Solo locale.** `zing serve` ascolta solo su loopback (`127.0.0.1`, `::1`,
  `localhost`), risponde solo a quei nomi host e rifiuta le richieste
  cross-site; non ha login perché nulla al di fuori della tua macchina può
  raggiungerlo. zing contatta solo gli endpoint che configuri (obiettivo,
  riferimento, giudice, webhook); non scarica nulla in fase di esecuzione,
  nemmeno file di tokenizer.
- **Chiavi.** I rapporti e la cronologia conservano solo un'impronta di una
  chiave API. Le chiavi dei monitor sono salvate cifrate in `watches.db`; la
  chiave principale che le decifra non viene mai scritta nella directory dei
  dati (la conservi tu, vedi **Monitoraggio** sopra), quindi una copia della
  directory non rivela alcuna chiave API. La directory resta comunque
  accessibile solo al tuo utente.
- **Directory dei dati.** `~/.zing` (o `ZING_DATA_DIR`), creata con `0700` e
  file con `0600`: `history.db` (cronologia delle verifiche), `watches.db`
  (monitor, chiavi cifrate comprese) e `kb.db` (le tue voci della base di
  conoscenza). Elimina la directory per rimuovere tutto.
  `zing data-dir` mostra dove si trova; `--data-dir PERCORSO` ne sceglie
  un'altra per una singola esecuzione, ad es. `zing serve --data-dir .` tiene
  i database nella cartella corrente. Sono normali file SQLite che puoi aprire
  per le tue analisi (meglio in sola lettura mentre zing è in esecuzione). Non
  fare commit di `watches.db` se quella cartella è un repository.
  `history_metrics` contiene una riga di valori misurati per esecuzione e
  `history_requests` ogni record di richiesta (salvato lì una sola volta, non
  dentro ogni rapporto).

## Uso responsabile

zing è un aiuto alla verifica black-box. **Non può dimostrare**:

- che un fornitore conservi i tuoi prompt o li usi per l'addestramento,
- che instradi sempre verso un unico modello esatto (i relay possono instradare in modo probabilistico),
- frodi di fatturazione oltre quanto la stima indipendente dei token può suggerire.

Usa i rapporti per la tua due diligence. **Non accusare pubblicamente un
fornitore** sulla base di una singola esecuzione senza aver valutato la dimensione
del campione, le impostazioni di costo e la legge locale. Esegui `zing compare`
contro un riferimento affidabile prima di trarre conclusioni forti.

## Altra documentazione

| Documento | Per |
|---|---|
| [Metodologia](docs/METHODOLOGY.it.md) | Come funziona ogni controllo, la sua scala dei punteggi e le sue avvertenze |
| [Guida per sviluppatori](DEVELOPER_GUIDE.it.md) | Architettura, ambiente di sviluppo, contributi, traduzioni, Docker, rilasci |
| [docs/CI.md](docs/CI.md) | La GitHub Action: input, output, esempi (in inglese) |
| [docs/DOCKER.md](docs/DOCKER.md) | Eseguire l'interfaccia web in un container (in inglese) |
| [CHANGELOG.md](CHANGELOG.md) | Cosa è cambiato in ogni versione (in inglese) |
| [SECURITY.md](SECURITY.md) | Segnalare una vulnerabilità (in inglese) |

## Licenza

[Apache-2.0](LICENSE)
