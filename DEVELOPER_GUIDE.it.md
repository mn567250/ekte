# zing — Guida per sviluppatori

> [🇬🇧 English](DEVELOPER_GUIDE.md) · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md)

Questa guida è per chi modifica zing: com'è costruito, come preparare un ambiente
di sviluppo, come contribuire e come viene pacchettizzato, eseguito in Docker e
pubblicato. Cosa fa zing e come usarlo è nel [README](README.it.md); come
funziona e come viene valutato ogni controllo, nella
[Metodologia](docs/METHODOLOGY.it.md).

---

## Indice

- [Principi](#principi)
- [Ambiente di sviluppo](#ambiente-di-sviluppo)
- [Struttura del repository](#struttura-del-repository)
- [Architettura](#architettura)
  - [Flusso di una verifica](#flusso-di-una-verifica)
  - [Client](#client)
  - [Rilevatori e scale dei punteggi](#rilevatori-e-scale-dei-punteggi)
  - [Punteggio e verdetto](#punteggio-e-verdetto)
  - [Base di conoscenza](#base-di-conoscenza)
  - [Libreria dei prompt](#libreria-dei-prompt)
  - [Rapporti](#rapporti)
  - [Verificatori autonomi](#verificatori-autonomi)
  - [Server web](#server-web)
  - [Frontend web](#frontend-web)
  - [Dati locali](#dati-locali)
- [Contribuire](#contribuire)
  - [Pull request](#pull-request)
  - [Aggiungere un rilevatore](#aggiungere-un-rilevatore)
  - [Modificare la base di conoscenza](#modificare-la-base-di-conoscenza)
  - [Modificare i prompt delle sonde](#modificare-i-prompt-delle-sonde)
  - [Traduzioni](#traduzioni)
  - [Documentazione](#documentazione)
- [Test](#test)
- [Docker](#docker)
- [Integrazione continua](#integrazione-continua)
- [Rilasci](#rilasci)
- [Sicurezza](#sicurezza)
- [Licenza](#licenza)

## Principi

zing è un aiuto alla verifica black-box: la correttezza e **non accusare a torto
relay onesti** contano più che cogliere ogni trucco possibile. Tieni presente
quest'asticella in ogni modifica.

- **Prove, non accuse.** Le rilevazioni segnalano *scostamento e rischio*, mai
  «frode». Meglio *non conclusivo* di un'ipotesi. Un nuovo percorso di gravità
  ALTA richiede prove solide e riproducibili e deve essere difficile da far
  scattare con un endpoint onesto.
- **Niente rete nei test.** I test dei rilevatori girano contro il server
  simulato in-process di `tests/conftest.py` (httpx `MockTransport`), mai contro
  un'API reale.
- **I segreti non escono.** Le chiavi API vengono ridotte a un'impronta e mai
  salvate nei rapporti. Ogni nuovo percorso di output deve far passare il testo
  controllato dal relay da `zing.utils.redact` ed eseguirne l'escape per il suo
  formato.
- **Le stesse sonde per tutti.** I testi delle sonde sono in inglese e fissi,
  qualunque sia la lingua dell'interfaccia, così lo stesso relay riceve lo stesso
  verdetto (vedi [Libreria dei prompt](#libreria-dei-prompt)).
- **Solo locale.** zing contatta solo gli endpoint configurati dall'utente, e
  l'interfaccia web ascolta solo su loopback (vedi [Server web](#server-web)).

## Ambiente di sviluppo

Richiede Python 3.10+. Node.js è facoltativo: i test del JavaScript del browser
girano con `node` e vengono saltati senza.

```bash
git clone https://github.com/cenbonew/zing
cd zing
pip install -e '.[dev,web]'   # installazione modificabile con gli strumenti di sviluppo e l'interfaccia web
pytest                        # suite di test
ruff check zing tests         # lint
mypy zing                     # controllo dei tipi
```

Con uv: `uv venv && uv pip install -e '.[dev,web]'`. Non servono
librerie di sistema, nemmeno per i rapporti PDF.

Esegui dai sorgenti con `zing …` o `python -m zing …`. `zing serve` serve
l'interfaccia web direttamente da `zing/web/static/`, quindi ricaricare il browser
applica le modifiche al frontend; non c'è una fase di build.

## Struttura del repository

```text
zing/
  cli.py               CLI Typer: check, compare, models, kb*, serve, watch, embed, rerank, image, audio
  config.py            configurazione YAML, riferimenti ai segreti (env:/file:), AuditOptions
  runner.py            run_audit(): collega tutto ed esegue i rilevatori
  context.py           AuditContext passato a ogni rilevatore
  models.py            contratti dati pydantic: TargetConfig, Finding, DetectorResult, AuditReport, …
  scoring.py           punteggi di dimensione, pesi, punteggio complessivo, verdetto di rischio, affidabilità
  clients/             client HTTP: compatibile OpenAI, Anthropic Messages, OpenAI Responses
  detectors/           un file per rilevatore, più base.py (registro), scale.py, helpers.py
  judge/               il giudice LLM affidabile usato da quality_judge
  knowledge/           schema, loader, archivio utente (kb.db), importazione, prompt di ricerca, istantanee
    data/              profili dei fornitori integrati (*.yaml)
  prompts/en.json      ogni testo che zing invia a un'API di LLM
  perf/                registrazione per richiesta e la sezione prestazioni del rapporto
  report/              renderer JSON / Markdown / HTML / PDF e scrittura
  embed_audit.py       verificatore autonomo di embedding e rerank
  media_audit.py       verificatore autonomo di immagini e audio (TTS)
  notify.py            avvisi via webhook (Slack / Feishu / DingTalk / JSON generico)
  datadir.py           la directory dei dati locale e i suoi file SQLite
  secretbox.py         cifratura dei segreti salvati; la chiave principale in memoria
  i18n/                traduzioni condivise dall'interfaccia web e dagli avvisi
    locales/           <code>.json per lingua, fragments/<feature>/<code>.json
  utils/               oscuramento, parsing SSE, statistica, stima dei token
  web/
    server.py          app FastAPI: pagine, API JSON, flusso SSE delle verifiche, scheduler dei monitor
    jobs.py            verifiche in background e il blocco per relay
    security.py        ascolto su loopback, elenco di host ammessi, controlli Origin/JSON, intestazioni
    history.py         archivio della cronologia delle verifiche (history.db)
    analytics_store.py le sue tabelle di analisi: metriche per esecuzione, record delle richieste
    analytics.py       query di analisi: KPI, serie temporali, classifiche
    watches.py         archivio dei monitor (watches.db)
    masterkey.py       stati e azioni della chiave principale (server e `zing secret`)
    static/            pagine dell'interfaccia classica e script condivisi (lang.js, i18n.js, …)
    static/v2/         pagine, stili e script della nuova interfaccia
tests/                 suite pytest; conftest.py contiene il relay simulato
docs/                  METHODOLOGY (7 lingue), CI.md, DOCKER.md, PUBLISHING.md
examples/zing.yaml     file di configurazione commentato
prototypes/            prototipi HTML statici del design dell'interfaccia web (non distribuiti)
action.yml             l'action composita di GitHub
Dockerfile             immagine dell'interfaccia web
```

## Architettura

### Flusso di una verifica

`zing check`, `zing compare`, `zing watch`, il flusso di verifica
dell'interfaccia web e il suo scheduler dei monitor finiscono tutti nella stessa
funzione, `zing.runner.run_audit()`:

1. **Configurazione.** `zing/config.py` unisce la configurazione YAML e le
   opzioni da riga di comando in `TargetConfig` (obiettivo, riferimento e giudice
   facoltativi) e `AuditOptions` (suite, dimensioni, dimensione delle sonde,
   output). Le chiavi API indicate come `env:VAR` o `file:/percorso` vengono
   risolte qui.
2. **Base di conoscenza.** `load_knowledge_base()` carica i profili integrati,
   `--kb-dir`/`ZING_KB_DIR` e il `kb.db` dell'utente, e risolve il modello
   **dichiarato** (per impostazione predefinita quello richiesto) in un profilo.
   Un monitor passa invece la propria istantanea fissata.
3. **Client.** `make_client()` crea un client per l'obiettivo (e il riferimento)
   nel protocollo scelto o rilevato automaticamente. Un `RequestRecorder` avvolge
   ogni chiamata per la sezione prestazioni.
4. **Rilevatori.** `select_detectors()` sceglie i rilevatori registrati per la
   suite (o per le dimensioni personalizzate), scartando quelli che richiedono un
   giudice o un riferimento assenti. Girano **in sequenza**, di proposito: le
   richieste concorrenti farebbero scattare i limiti di frequenza e falserebbero
   le misure dei tempi (le sonde di affidabilità e prestazioni gestiscono da sé
   una concorrenza limitata). `run_detector()` cronometra ciascuno e trasforma un
   crash in un risultato con stato **Errore**, così una risposta anomala del relay
   non interrompe mai la verifica.
5. **Punteggio.** `scoring.build_dimensions()` e `build_verdict()` trasformano i
   risultati dei rilevatori in punteggi di dimensione, punteggio complessivo e
   voto, verdetto di rischio e la sua affidabilità.
6. **Rapporto.** Tutto confluisce in un `AuditReport` (`zing/models.py`) con
   l'obiettivo oscurato, l'istantanea del profilo della base di conoscenza, la
   sezione prestazioni e le lingue delle sonde. La CLI lo renderizza e lo scrive;
   l'interfaccia web lo trasmette.

`run_audit()` accetta una callback `on_event`; il server web trasforma i suoi
eventi (rilevatore avviato/terminato con rilevazioni compatte, tempi per
richiesta raggruppati) in Server-Sent Events per la vista in tempo reale.

### Client

`zing/clients/` ha un client per protocollo — `openai_compatible.py` (Chat
Completions), `anthropic.py` (Messages) e `responses.py` (Responses) — con la
stessa interfaccia, costruiti sulla meccanica HTTP comune di `base.py`.
`make_client()` in `clients/__init__.py` ne sceglie uno in base a `--api` o lo
rileva dall'URL di base e dal modello. I rilevatori parlano solo con questa
interfaccia (`RequestSpec` in ingresso, `CompletionOutcome` in uscita), quindi
sono indipendenti dal protocollo.

I client adattano anche le richieste a ciò che il modello accetta (`base.py`):
il runner inizializza `unsupported_params` dal profilo, i parametri di
campionamento elencati lì vengono omessi e, su Chat Completions, un `max_tokens`
elencato invia il limite come `max_completion_tokens`. Un 4xx che nomina un tale
parametro lo aggiunge all'insieme e ripete la richiesta una volta adattata (il
tentativo rifiutato è registrato con la fase `param_retry`). Una sonda che
giudica il rifiuto grezzo imposta `RequestSpec.exact_params`.

### Rilevatori e scale dei punteggi

Un rilevatore è un file autonomo in `zing/detectors/`: una sottoclasse di
`Detector` (`base.py`) con un `id`, un `name`, una `dimension`, la prima suite in
cui gira (`min_suite`), un `cost_hint` approssimativo per `--dry-run` e
`async def run(self, ctx) -> DetectorResult`. `@register` lo aggiunge al
registro; `zing/detectors/__init__.py` importa ogni modulo così il registro è
completo.

Ogni rilevatore pubblica la propria **scala dei punteggi** (`SCALE`, costruita
con `scale.py`): ogni esito possibile di ogni controllo con punti, stato e
gravità. Le rilevazioni vengono create dalla scala
(`SCALE.finding(check, outcome, …)`), così rapporto e comportamento non possono
divergere. `Scale` assegna la media dei suoi controlli; `DeductionScale` parte da
100 e detrae o limita. L'interfaccia web mostra la scala sotto **Scala dei
punteggi**; la [Metodologia](docs/METHODOLOGY.it.md) riporta ogni scala.
`connectivity.py` è l'esempio canonico e più breve.

I rilevatori condividono un unico event loop con ogni altra verifica in
`zing serve`, quindi il lavoro che impegna la CPU non deve girarci sopra: un loop
bloccato ritarda le richieste delle altre verifiche e gonfia le latenze che
registrano. `helpers.build_filler()` costruisce il testo di riempimento in tempo
lineare e memorizza in cache le ultime dimensioni, e i rilevatori della finestra
di contesto e della cache dei prompt lo chiamano (insieme a `build_haystack()`)
tramite `asyncio.to_thread`. I conteggi dei token vengono da
`zing/utils/tokenize.py`, un'euristica basata solo sulla libreria standard: zing
non importa alcuna libreria di tokenizer e non scarica nulla in fase di
esecuzione, quindi funziona in ambienti con accesso limitato. L'argomento
`tokenizer` di `estimate_tokens()` è accettato ma non cambia il conteggio, e i
campi del rapporto `tokens_exact` / `exact_tokenizer` sono mantenuti per
compatibilità e valgono sempre false.

### Punteggio e verdetto

`zing/scoring.py` contiene `DIMENSION_WEIGHTS` e le regole del verdetto: il
punteggio di una dimensione è la media a pari peso dei suoi rilevatori, il
punteggio complessivo la media ponderata delle dimensioni eseguite, e il livello
di rischio segue la scala di gravità descritta in
[Metodologia → Come zing assegna i punteggi](docs/METHODOLOGY.it.md#come-zing-assegna-i-punteggi).
Ogni dimensione registra come è stata calcolata in `DimensionScore.breakdown`,
che alimenta i **Dimension details** dei rapporti e le righe espandibili dei
**Controlli per dimensione** dell'interfaccia web.

### Base di conoscenza

`zing/knowledge/` definisce lo schema dei profili (`schema.py`:
`ProviderProfile`, `ModelProfile`, `FingerprintProbe`), carica e unisce i livelli
(`loader.py`: YAML integrato → `ZING_KB_DIR`/`--kb-dir` → il `kb.db`
dell'utente), salva le voci dell'utente (`store.py`), controlla e importa YAML
(`importer.py`), costruisce il prompt di ricerca per gli assistenti esterni
(`research.py`) e fotografa il profilo usato da un'esecuzione (`snapshot.py`). Gli
id di modello si risolvono tramite alias e fornitore dichiarato; ogni rapporto
registra come è stato risolto l'id.

`load_knowledge_base()` tiene in cache i risultati uniti e per impostazione
predefinita restituisce una copia profonda, così i chiamanti possono modificare
ciò che ricevono. I chiamanti che si limitano a leggerla (gli elenchi e il
catalogo dell'interfaccia web, la risoluzione di un modello) passano
`copy=False` e ottengono l'istanza condivisa in cache, che non devono
modificare.

Anche i relay sono endpoint: `relays.py` trasforma i `base_url_hints` di un
provider in URL di base utilizzabili (`GET /api/kb` → `base_urls`) e salva un
relay dall'interfaccia web come voce di provider in `kb.db` (`origin = relay`: un
`display_name` e un URL di base, nessun modello; nessuna modifica allo schema).

### Libreria dei prompt

Ogni testo che zing invia a un'API di LLM — sonde di chat, il prompt del giudice,
schemi degli strumenti, input di embedding / rerank / immagine / audio — si trova
in `zing/prompts/en.json` e si legge con `zing.prompts.text()` / `get()`.
`{{name}}` indica un valore inserito a runtime. La lingua delle sonde è fissata
all'inglese (`PROBE_LANG`), indipendentemente dalla lingua dell'interfaccia,
perché i controlli delle risposte e le stime dei token sono calibrati su quei
testi esatti. Le sonde la cui lingua *è* la misura (per es. scioltezza in cinese,
tokenizer o autoidentificazione dei modelli cinesi) vivono con le loro risposte
attese nella base di conoscenza e dichiarano `prompt_lang` e un motivo
`language_bound`. Il runner registra le lingue usate in `prompt_languages`.

### Rapporti

`zing/report/render.py` renderizza un `AuditReport` in JSON, JSON compatto per
agenti, Markdown e HTML; `dimensions.py` e `performance.py` renderizzano i
**Dimension details** e la sezione prestazioni; `pdf.py` impagina il PDF con
ReportLab a partire dagli stessi dati e funzioni (puro Python; solo i font PDF
standard, con il font CID STSong-Light per il cinese, quindi nulla di
incorporato; senza mai caricare risorse esterne), condiviso da CLI e interfaccia
web;
`writer.py` scrive i file. Tutto il testo controllato dal relay viene oscurato ed
escapato (HTML / Markdown) prima dell'output. `POST /api/report/export`
dell'interfaccia web riusa questi renderer per la riga **Scarica il rapporto**,
con i testi leggibili tradotti nella lingua dell'interfaccia.

### Verificatori autonomi

Embedding/rerank (`embed_audit.py`) e immagini/audio (`media_audit.py`) non sono
superfici di chat, quindi hanno i propri piccoli verificatori con un proprio
verdetto invece della pipeline dei rilevatori. Condividono le impostazioni HTTP
dei client, la base di conoscenza (dimensioni native, formati immagine, voci) e
la libreria dei prompt. Tutta la decodifica (intestazioni delle immagini, WAV) usa
solo la libreria standard.

### Server web

`zing/web/server.py` è un'app FastAPI creata da `create_app()`:

- **Pagine.** L'interfaccia classica (`/`, `/console`, `/history`, `/watches`,
  `/tools`) e la nuova interfaccia (`/v2/`, `/v2/history`, `/v2/watches`,
  `/v2/tools`, `/v2/kb`) sono file HTML statici. `?ui=v2` / `?ui=v1` passa
  dall'una all'altra e un cookie ricorda la scelta, così un URL classico
  reindirizza al suo equivalente nuovo una volta scelta la nuova interfaccia.
- **API.** `/api/audit/stream` esegue una verifica e ne trasmette gli eventi via
  SSE; `/api/models` elenca i modelli di un relay; `/api/report/export`
  renderizza un rapporto; `/api/history…`, `/api/watches…`, `/api/kb…`,
  `/api/embed` e `/api/rerank` servono le altre pagine.
- **Relay.** `POST /api/kb/relays` salva un relay `{name, base_url}` (400 per un
  input non valido, 409 se il nome o l'URL sono già noti).
- **Analisi.** `GET /api/analytics/options` (relay, modelli, suite, modalità di
  stream, API e intervallo di date della cronologia), `/api/analytics/summary`
  (KPI di `from`–`to` rispetto all'intervallo precedente di pari durata),
  `/api/analytics/series` (`metric` per `group=relay|model|relay_model`, fino a
  4 `keys`, in intervalli `bucket=hour|day|week|dow_hour` nel fuso orario
  dell'utente, `tz` o `tz_offset`) e `/api/analytics/leaderboard` (`model=` per
  i suoi relay, oppure `relay=` per i suoi modelli). Tutti accettano i filtri
  `from`, `to`, `suite`, `stream_mode`, `api`, `source=all|manual|monitor`,
  `relay` e `model`. `zing/web/analytics.py` calcola tutto in Python da
  `history.analytics_runs()`: gli id delle metriche vengono da un elenco fisso,
  i relay sono raggruppati per voce della base di conoscenza al momento della
  query, un valore che un'esecuzione non ha misurato resta escluso (ogni valore
  ha il suo `n` e la sua `coverage`) e gli intervalli con meno di `MIN_RUNS` (3)
  esecuzioni sono marcati `low_n`. Un parametro non valido risponde 400; le
  risposte sono `Cache-Control: no-store`.
- **Pannelli di analisi.** `/api/analytics/breakdown` (fino a 8 `metrics` per
  `group=relay|model|relay_model|all` nel periodo), `/api/analytics/errors` (le
  chiamate di completamento al target per classe di esito
  `success|client_4xx|rate_limited|server_5xx|timeout|network|other`, per
  `group=relay|model` e per `bucket`, contate in SQL da
  `history.analytics_request_classes()` senza caricare le righe delle
  richieste; l'ora di una chiamata è l'inizio del suo audit più il suo offset,
  al minuto; `covered` = audit con registri delle richieste) e
  `/api/analytics/integrity` (conteggi di superati / avvisi / falliti dei
  rilevatori di identità, capacità, visione, streaming, protocollo, integrità,
  prompt iniettato e connettività per relay × modello, la quota di modelli
  divergenti e il rapporto mediano finestra di contesto misurata / dichiarata).
  `/api/analytics/series` accetta anche `group=all`. Stessi filtri ed errori di
  sopra.
- **Verifiche in background.** `jobs.py` esegue ogni verifica come job del
  server. `POST /api/jobs` ne accoda uno, `GET /api/jobs` elenca i job in coda,
  in corso e appena conclusi (e i monitor in esecuzione) con l'avanzamento,
  `GET /api/jobs/{id}/events` riproduce il registro degli eventi e poi lo segue
  dal vivo via SSE, e `POST /api/jobs/{id}/cancel` lo ferma. La nuova
  interfaccia li usa, quindi una verifica sopravvive alla pagina;
  `/api/audit/stream` (interfaccia classica) avvolge lo stesso job e lo annulla
  alla chiusura del flusso. Un blocco per relay lascia usare un relay a una sola
  verifica (o esecuzione di monitor) alla volta, per nome host, con tutti gli
  indirizzi loopback come un solo host; al massimo `ZING_MAX_PARALLEL_AUDITS`
  (predefinito 4) insieme, in ordine di arrivo.
- **Scheduler dei monitor.** Il lifespan dell'app avvia un ciclo in background che
  avvia ogni monitor in scadenza come task a sé, così i monitor su relay diversi
  eseguono le verifiche contemporaneamente; il blocco per relay resta valido,
  quindi i monitor possono occupare i posti di `ZING_MAX_PARALLEL_AUDITS` e una
  verifica avviata a mano può finire in coda dietro di loro. Il `last_run_ts` di
  un'esecuzione è il momento in cui inizia la sua verifica (dopo l'attesa del suo
  relay). Ogni esecuzione è registrata nella cronologia; il controllo di
  regressione la confronta con l'esecuzione salvata più recente dello stesso
  obiettivo e modello (`history.latest_for()`, una sola ricerca indicizzata) e
  invia gli avvisi via webhook (`zing/notify.py`) in parallelo al superamento di
  una soglia o a un peggioramento. `POST /api/watches/{id}/run` risponde 409
  se lo scheduler ha appena avviato quel monitor; un reset della chiave
  principale annulla le esecuzioni pianificate non ancora iniziate, e lo
  spegnimento annulla quelle in corso.
- **Compressione e cache.** `caching.py` comprime con gzip le risposte da 1 KiB in
  su (tranne i Server-Sent Events) per i client che lo accettano (`gzip;q=0` lo
  rifiuta). Le pagine e `/locales.js` vengono compressi una sola volta quando
  sono generati e serviti già compressi con `Content-Encoding: gzip`,
  `Vary: Accept-Encoding` e un ETag distinto che termina in `-gz`; le pagine
  sono servite tramite `html_page(page, request.scope)`, così seguono quel
  percorso e rispondono 304 alle richieste condizionali. Gli URL locali di
  script e fogli di stile nelle pagine portano un `?v=<hash del contenuto>` e
  sono messi in cache come immutabili.
- **Sicurezza.** `security.py` determina l'indirizzo di ascolto (solo loopback,
  tranne in un container rilevato con `ZING_CONTAINER=1`) e installa
  `LocalOnlyMiddleware`: un elenco di host ammessi contro il DNS rebinding,
  controlli di `Origin` e `Sec-Fetch-Site` contro il CSRF, corpi di richiesta solo
  JSON e intestazioni anti-frame / no-sniff / no-referrer. L'interfaccia non ha
  login per scelta.

### Frontend web

Il frontend è HTML, CSS e JavaScript da browser semplici, senza moduli né fase di
build. Le pagine classiche sono in `zing/web/static/`; la nuova interfaccia, in
`zing/web/static/v2/`, condivide un'intestazione (`nav.js`), il renderer del
rapporto (`report.js`), il selettore del tema (`theme.js`) e gli stili
(`zing.css`, `fields.css`, `report.css`, `perf.css`). Gli script condivisi sono
serviti dalla radice: `lang.js` (cambio lingua), `locales.js` (dati di
traduzione), `i18n.js` (traduzione delle rilevazioni), `icons.js`,
`modelpicker.js` (**Recupera modelli**), `secretfield.js` e `perf.js` (grafici
delle prestazioni).

Le pagine v2 **Verifica** e **Strumenti** configurano i relay con
`v2/relaycfg.js`: scelta relay/provider → URL di base → i modelli del relay
(`/api/models`, al cambiamento, in cache per URL/chiave/protocollo) → modello
dichiarato dalla base di conoscenza (`/api/kb/resolve` lo preseleziona) →
provider derivato, più **Salva nella base** (`POST /api/kb/relays`). Le sue
funzioni pure sono testate con node; le pagine classiche mantengono
`modelpicker.js`.

La pagina v2 **Analisi** (`v2/analytics.html`) legge solo `/api/analytics/*`
(`options` elenca anche le coppie relay × modello, `relay_models`, per la scelta
delle serie). Ha una `<section class="card panel">` per pannello sotto un'unica
barra dei filtri, quindi si possono aggiungere pannelli; filtri e vista stanno
nel frammento dell'URL (`#range=30&metric=score&…`) e in `localStorage`. I
grafici vengono da `v2/charts.js` (`ZingCharts.timeChart`: SVG inline disegnato
a mano con linea mediana, fascia p25–p75, vuoti per gli intervalli senza dati,
marcatori attenuati per gli intervalli `low_n`, linee di annotazione e tooltip
al passaggio del puntatore; `fmt` / `fmtDelta` formattano i valori per unità) e
da `v2/charts.css` (quattro colori di serie validati per tema, distinguibili
anche dalla forma del marcatore). Ogni grafico esiste anche come tabella di
dati.

Ogni pannello è autonomo: un registro `PANELS` nello script della pagina
indica l'id della sua sezione, `load()` (caricare con i filtri e la vista
correnti, poi disegnare) e `render()` (ridisegnare dai dati caricati, ad es. al
cambio di lingua), così i pannelli si possono riordinare senza toccarsi a
vicenda. `ZingCharts.heatmap` disegna la griglia giorno della settimana × ora
(scala sequenziale a una tinta in cinque livelli per tema, celle tratteggiate
per `low_n`, celle vuote solo con contorno), `ZingCharts.stackBars` le barre di
errore impilate, e `timeChart` accetta una linea `ref` (rapporto di
fatturazione del 100%).

L'intestazione della pagina e il pannello dei filtri stanno sopra cinque schede
interne (`v2/tabs.js`, come in Strumenti e Conoscenza): ogni voce di
`PANELS` indica la sua `tab`, e si caricano solo i pannelli della scheda
visibile; una modifica dei filtri ricarica quella scheda e segna le altre come
non aggiornate (`activate()` le carica quando vengono mostrate). Qui `tabs.js`
riceve `writeHash: false`, perché la pagina scrive da sé l'intera vista nel
frammento — `#tab=trends&range=30&suite=…&metric=…` (`stateQuery()`), che
**Copia il link a questa vista** copia (un campo di sola lettura selezionato se
l'API degli appunti manca o rifiuta); un frammento senza `tab` apre la
Panoramica, e un link incollato (`hashchange`) rilegge la vista. Il pannello dei
filtri richiudibile è `v2/filterpanel.js` + `v2/filterpanel.css`, condiviso con
la Cronologia: `ZingFilterPanel.create(section, {label, title, storeKey, open,
onReset})` restituisce `render({body, foot, count, summary})`,
`sync({count, summary})`, `setOpen()` e `focusStart()`; la pagina gestisce i
propri filtri e campi, il pannello il pulsante con il badge dei filtri attivi,
il riepilogo di una riga mostrato da chiuso, lo stato aperto memorizzato e
**Reimposta filtri**.

**Convenzione di traduzione.** Il testo cinese scritto nell'HTML è l'originale e
resta intatto; ogni elemento porta il suo testo inglese in `data-en` (e
`data-en-placeholder`, `data-en-title`, `data-en-aria-label`). Il testo inglese è
la chiave di ricerca per tutte le altre lingue. Gli script usano `T(zh, en)` per
il testo dinamico e `ZING_LANG.server(text)` per il testo proveniente dal backend
(nomi dei rilevatori, raccomandazioni, frasi del verdetto).

### Dati locali

`zing/datadir.py` gestisce `$ZING_DATA_DIR` (predefinito `~/.zing`), creato con
`0700`, con file SQLite `0600`: `history.db` (`web/history.py`), `watches.db`
(`web/watches.py`, che conserva cifrate le chiavi API dei monitor) e `kb.db`
(`knowledge/store.py`). Ogni chiamata apre una connessione di breve durata,
quindi gli archivi sono sicuri nel pool di thread di FastAPI. L'opzione globale
`--data-dir` (anche su `zing serve`) imposta semplicemente `ZING_DATA_DIR` sul
percorso assoluto, e `zing data-dir` stampa la directory risolta. Una directory
già esistente mantiene i suoi permessi; solo il `~/.zing` predefinito viene
ristretto a `0700`. Le righe della cronologia sono indicizzate per obiettivo e
modello (`idx_history_target`), che `history.latest_for()` usa per trovare
l'esecuzione precedente di un monitor.

Dalla versione 2 dello schema (`PRAGMA user_version`) `history.db` contiene
anche le tabelle di analisi, definite in `web/analytics_store.py`:
`history_metrics` (una riga di metriche estratte per esecuzione: ora di inizio,
tassi, percentili di latenza/TTFT/decodifica, rapporti di fatturazione, numero di
rilevazioni e altro; NULL dove l'esecuzione non ha misurato un valore),
`history_dimensions` (punteggi di dimensioni e rilevatori) e `history_requests` (i
record delle richieste dell'esecuzione, obiettivo e baseline, nell'ordine della
lista). I `performance.requests` di un rapporto stanno solo lì: `save()` li toglie
da `report_json` (`requests_split` marca la riga) e `get()` / `latest_for()` li
rimettono al loro posto, così un rapporto si rilegge identico a come è stato
salvato; ciò che le colonne non possono riprodurre esattamente finisce nella
colonna JSON `extra`. `extract_metrics()` è pura e versionata
(`EXTRACT_VERSION`). Dopo la migrazione un backfill a lotti (una transazione
breve per lotto, idempotente) sposta i record delle righe più vecchie, ne
estrae le metriche e riestrae le righe scritte da una `EXTRACT_VERSION`
precedente; `history.backfill_analytics()` lo riesegue su richiesta. L'ora di
inizio di un'esecuzione è lo `started_at` del rapporto; i rapporti precedenti a
quel campo ricevono `generated_at` meno l'intervallo coperto dai loro record
delle richieste (`started_at_estimated` = 1).

Le chiavi API salvate sono cifrate da `zing/secretbox.py` (Fernet, salvate come
`enc:v1:…`; i riferimenti `env:`/`file:` restano come sono). La chiave
principale non viene mai salvata: `web/masterkey.py` (`Vault`, condiviso dal
server e da `zing secret`) la tiene nella memoria del server appena arriva da
`ZING_SECRET_KEY`, da un vecchio `secret.key` o dall'utente nella pagina
Monitor, e `watches.db` conserva solo un valore di controllo (`secret_meta`) che
rifiuta una chiave sbagliata. Una nuova chiave ricifra ogni chiave salvata e
riscrive il valore di controllo in un'unica transazione. La chiave vive nella
memoria di un solo processo, quindi esegui un server per directory dei dati.

## Contribuire

### Pull request

- Mantieni verdi `pytest`, `ruff check zing tests` e `mypy zing` (la CI li esegue
  tutti e tre con Python 3.10–3.13).
- Descrivi il trucco del relay o il falso positivo che la modifica affronta.
- Aggiorna `CHANGELOG.md` sotto `[Unreleased]`.
- Aggiorna la documentazione interessata — README, questa guida, la Metodologia —
  in **ogni lingua** (vedi [Documentazione](#documentazione)).

Contribuendo accetti che i tuoi contributi siano rilasciati sotto la licenza
[Apache-2.0](LICENSE) del progetto.

### Aggiungere un rilevatore

1. Crea `zing/detectors/<name>.py` e importalo in `zing/detectors/__init__.py`.
2. Definisci la sua `SCALE` (`Scale` o `DeductionScale` da `scale.py`) con ogni
   esito di ogni controllo, e crea le rilevazioni solo tramite essa.
3. Estendi `Detector`; imposta `id`, `name`, `dimension`, `min_suite` e
   `cost_hint`; imposta `requires_judge = True` o `requires_baseline = True` se
   serve un giudice o un riferimento, oppure ridefinisci `applies()` per altre
   condizioni. Decora la classe con `@register`.
4. Implementa `async def run(self, ctx) -> DetectorResult` partendo da
   `self.new_result(scoring=SCALE.scoring())`. Invia le richieste tramite
   `ctx.client` e prendi ogni prompt da `zing/prompts/en.json`.
5. Aggiungi test di comportamento sia per il percorso segnalato sia per quello
   pulito, con il relay simulato di `tests/conftest.py`.
6. Traduci i nuovi titoli e riepiloghi delle rilevazioni (vedi
   [Traduzioni](#traduzioni)) e documenta il rilevatore e la sua scala in ogni file
   di [Metodologia](docs/METHODOLOGY.it.md).

### Modificare la base di conoscenza

I profili sono in `zing/knowledge/data/<provider>.yaml`, un file per fornitore.
Ogni modello riporta finestra di contesto nativa, output massimo, data di cutoff
delle conoscenze, tokenizer, modalità, capacità, parametri non supportati, parole
chiave d'identità e impronte (vedi `zing/knowledge/schema.py`). Quando modifichi
un campo numerico, **cita una fonte autorevole** (la scheda ufficiale del modello,
i prezzi o la documentazione del fornitore) nella pull request: un valore errato
causa falsi positivi contro relay onesti. `zing kb-import --check <file>` esegue
gli stessi controlli dell'importazione utente (schema, limiti, espressioni
regolari pericolose, prompt, collisioni di id).

Compila sempre `identity_keywords` con le parole del produttore e della
famiglia con cui il modello si identifica. Il controllo d'identità conta anche
la chiave del provider, il nome visualizzato e l'id del modello come marchio
autentico, estesi agli altri nomi del produttore in `VENDOR_BRANDS`
(`zing/knowledge/identity.py`, che è anche l'elenco dei marchi rivali del
detector); l'importazione completa le parole chiave vuote a partire da questi
nomi con un avviso. Le parole di marchio di un nuovo produttore vanno aggiunte
lì come un gruppo.

### Modificare i prompt delle sonde

I testi delle sonde sono dati di calibrazione. Modificarne uno in
`zing/prompts/en.json` può cambiare i controlli delle risposte, le stime dei
token e quindi i verdetti; adegua il rilevatore e i suoi test e cita la modifica
nel CHANGELOG. Non far mai seguire a una sonda la lingua dell'interfaccia.

### Traduzioni

L'interfaccia e gli avvisi via webhook condividono un unico insieme di traduzioni
in `zing/i18n/locales/<code>.json`:

- `meta` — codice, il nome della lingua nella lingua stessa per il menu, lingua
  `html`, impostazioni locali delle date e ordine nel menu;
- `strings` — testo inglese → traduzione (`en.json` è la mappa identità e
  l'elenco di riferimento dei testi traducibili);
- `findings` — id della rilevazione → `[titolo, modello del riepilogo]`
  (`zh.json` contiene il catalogo cinese originale).

Le funzionalità possono fornire i propri testi come frammenti,
`zing/i18n/locales/fragments/<feature>/<code>.json` con `{"strings": {…}}`,
uniti alla lingua al caricamento. `/locales.js` invia solo la lingua scelta
(`?lang=<code>` o il cookie `zing_lang` impostato da `lang.js`; senza nessuno dei
due, tutte le lingue), generato e compresso con gzip una volta per variante e
rivalidato tramite `ETag`; un cambio di lingua carica la nuova su richiesta.

- **Nuovo testo dell'interfaccia:** scrivi il cinese nell'HTML e l'inglese in
  `data-en` (o usa `T(zh, en)`), poi aggiungi la chiave inglese a `en.json` o a
  un frammento e la sua traduzione in ogni altra lingua.
- **Nuova lingua:** aggiungi `zing/i18n/locales/<code>.json` (copia `de.json`) e
  un file per frammento; il menu, le pagine, gli avvisi e `--alert-lang` la
  recepiscono.
- `tests/test_web_locales.py` fallisce finché ogni testo dell'interfaccia e ogni
  rilevazione non sono tradotti con segnaposto e markup intatti.

**Terminologia.** Ogni termine ha una sola traduzione per lingua. Riusa la
terminologia che l'interfaccia usa già (nomi delle pagine, nomi delle dimensioni,
etichette di rischio, etichette dei pulsanti) nei nuovi testi e nella
documentazione.

### Documentazione

La documentazione esiste in sette lingue — inglese, cinese (`zh-CN`), francese,
spagnolo, portoghese, italiano e tedesco:

| File | Destinatari |
|---|---|
| `README.md`, `README.<lang>.md` | Utenti: cosa fa zing, installazione, uso della CLI e dell'interfaccia web |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Contributori: architettura, ambiente, contributi, Docker, rilasci |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Tutti: ogni controllo, la sua scala dei punteggi e le sue avvertenze |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Pagine di riferimento (in inglese) |

I file inglesi sono il riferimento. Quando ne modifichi uno, modifica gli altri
nella stessa pull request e usa in ogni lingua la terminologia dell'interfaccia
(cerca il termine in `zing/i18n/locales/`). I file METHODOLOGY riportano le scale
dei punteggi con la formulazione che l'interfaccia mostra sotto **Scala dei
punteggi**.

## Test

```bash
pytest                       # tutto
pytest tests/test_billing.py # un modulo
pytest -k streaming          # per parola chiave
pytest -n auto               # in parallelo, un worker per CPU (pytest-xdist)
```

- `tests/conftest.py` fornisce `MockServer`, un endpoint compatibile OpenAI su
  `httpx.MockTransport` con manopole per ogni scostamento che zing cerca (modello
  servito, autoidentificazione, troncamento del contesto, streaming finto,
  consumo assente o gonfiato, chiamate di strumenti, modalità JSON, …). Ogni
  manopola ha per impostazione predefinita il comportamento di un relay onesto.
- I client Anthropic e Responses hanno test propri (`test_anthropic.py`,
  `test_responses.py`); il server web è testato con il client di test di FastAPI
  (`test_web*.py`), comprese le protezioni per l'uso locale
  (`test_web_security.py`).
- Gli script del browser (`lang.js`, `modelpicker.js`, `v2/relaycfg.js`, `perf.js`,
  `secretfield.js`, `v2/report.js`, le traduzioni) vengono valutati con `node` in
  `test_web_*_js.py` e `test_web_locales.py`; senza Node.js vengono saltati.
- Nessun test può accedere alla rete.
- `test_cli_startup.py` mantiene rapido l'avvio della CLI: importare `zing.cli`
  non deve caricare i client HTTP, il runner, il caricatore della base di
  conoscenza, i renderer dei rapporti (ReportLab) né il server web. Importali
  dentro il comando che ne ha bisogno.
- `test_filler_perf.py` fissa il testo di riempimento byte per byte e fallisce
  quando la sonda della finestra di contesto blocca l'event loop.
- `tests/a11y/` verifica la nuova interfaccia web (v2) rispetto a BITV 2.0 /
  EN 301 549 / WCAG 2.1 AA in un browser reale (Playwright + axe-core), in ogni
  lingua dell'interfaccia e con entrambi i temi:
  `pip install -e '.[web,a11y]' && playwright install chromium`, poi
  `pytest -m a11y`. Senza Playwright la directory viene saltata. Cosa è
  automatizzato e cosa richiede ancora una revisione BITV manuale è descritto in
  [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md) (in inglese).
- `ZING_A11Y_PAGES=history,kb` esegue solo i test a11y di quelle pagine (più i
  controlli che riguardano tutte le pagine); `python -m tests.a11y.affected
  --base origin/main --head HEAD` mostra le pagine toccate da una modifica.
  Entrambi usano un'unica corrispondenza, `tests/a11y/pages.py`: una nuova
  pagina va aggiunta ai suoi `PAGES` e `RULES`
  ([tests/a11y/README.md](tests/a11y/README.md)).

## Docker

Il `Dockerfile` costruisce un'immagine dell'interfaccia web (Python 3.12 slim con
l'extra `web`; i rapporti PDF non richiedono pacchetti di sistema). Gira con un utente
non privilegiato e la directory dei dati in `/data`.

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# apri http://localhost:8000
```

**Pubblica sempre su `127.0.0.1`.** Un semplice `-p 8000:8000` pubblica
l'interfaccia — e ogni chiave API digitata al suo interno o salvata in un monitor
— sulla tua rete. Nel container il server deve ascoltare su tutte le interfacce;
è consentito solo se `ZING_CONTAINER=1` è impostato (l'immagine lo imposta) *e*
viene rilevato un ambiente container.

| Variabile | Predefinito | Scopo |
|---|---|---|
| `ZING_CONTAINER` | non impostata (`1` nell'immagine) | Consente l'ascolto fuori da loopback in un container rilevato |
| `ZING_HOST` | `127.0.0.1` (`0.0.0.0` nell'immagine) | Indirizzo di ascolto; `--host` prevale |
| `ZING_PORT` | `8000` | Porta; `--port` prevale |
| `ZING_DATA_DIR` | `~/.zing` (`/data` nell'immagine) | Cronologia, monitor (con le loro chiavi cifrate) e le tue voci della base di conoscenza; monta qui un volume. `--data-dir` ha la precedenza |
| `ZING_SECRET_KEY` | non impostata | Chiave principale delle chiavi API salvate dei monitor (una chiave, oppure `file:/run/secrets/…` / `env:VAR`); se non impostata, la pagina Monitor la chiede dopo ogni avvio. Mai salvata in `ZING_DATA_DIR` |
| `ZING_KB_DIR` | non impostata | Directory YAML aggiuntiva per la base di conoscenza, per es. `-v ./profiles:/kb:ro -e ZING_KB_DIR=/kb` |
| `ZING_NO_USER_KB` | non impostata | `1` ignora le tue voci della base di conoscenza (`kb.db`) |
| `ZING_ALLOWED_HOSTS` | non impostata | Nomi host aggiuntivi a cui l'interfaccia risponde, separati da virgole |

[docs/DOCKER.md](docs/DOCKER.md) è il riferimento completo (in inglese), comprese
le protezioni dell'interfaccia.

## Integrazione continua

| Workflow | Si avvia con | Cosa fa |
|---|---|---|
| `.github/workflows/ci.yml` | push e pull request verso `main` (e i branch di integrazione `a11y/integration`, `perf/integration`); ogni notte e manuale (solo accessibilità) | `ruff`, `mypy` e `pytest` con Python 3.10–3.13 e gli extra `dev` e `web`; costruisce wheel e sdist e verifica che la wheel si installi e carichi la base di conoscenza; esegue la suite di accessibilità (informativa, non fa mai fallire l'esecuzione) e ne carica i risultati: tutte le pagine sui push e nelle esecuzioni notturne e manuali (con il rapporto di conformità BITV), nelle pull request solo le pagine toccate dalla modifica (nessuna se cambia solo la documentazione) — tranne nelle pull request verso `perf/integration`, dove la lenta suite nel browser viene saltata (gira sui push di quel branch e sulla sua pull request verso `main`) |
| `.github/workflows/release.yml` | un tag `v*` | costruisce, esegue `twine check` e pubblica su PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | pianificazione giornaliera, manuale | esempio di verifica pianificata di un relay con l'action |

L'action composita è `action.yml`, documentata in [docs/CI.md](docs/CI.md).

## Rilasci

1. Rinomina `[Unreleased]` in `CHANGELOG.md` con la nuova versione e incrementa
   `version` in `pyproject.toml`.
2. Esegui il commit, crea il tag `vX.Y.Z` e fanne il push; `release.yml` pubblica
   su PyPI.
3. Crea la release su GitHub con le note del CHANGELOG e aggiorna la versione
   fissata dell'action nei README e in `docs/CI.md`.

La configurazione iniziale di PyPI e la procedura manuale sono in
[docs/PUBLISHING.md](docs/PUBLISHING.md).

## Sicurezza

Segnala le vulnerabilità in privato, come descritto in [SECURITY.md](SECURITY.md).
Rientrano nell'ambito soprattutto: una chiave o un segreto che finisce in un
rapporto, testo controllato dal relay che inietta markup in un rapporto o
nell'interfaccia, traffico verso qualcosa di diverso dagli endpoint configurati,
e modi per aggirare le protezioni per l'uso locale dell'interfaccia web.

## Licenza

[Apache-2.0](LICENSE)
