# ekte — Guida per sviluppatori

> [🇬🇧 English](DEVELOPER_GUIDE.md) · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md) · [🇳🇴 Norsk](DEVELOPER_GUIDE.nb.md)

Questa guida è per chi modifica ekte: com'è costruito, come preparare un ambiente
di sviluppo, come contribuire e come viene pacchettizzato, eseguito in Docker e
pubblicato. Cosa fa ekte e come usarlo è nel [README](README.it.md); come
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
  - [Superfici](#superfici)
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

ekte è un aiuto alla verifica black-box: la correttezza e **non accusare a torto
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
  controllato dal relay da `ekte.utils.redact` ed eseguirne l'escape per il suo
  formato.
- **Le stesse sonde per tutti.** I testi delle sonde sono in inglese e fissi,
  qualunque sia la lingua dell'interfaccia, così lo stesso relay riceve lo stesso
  verdetto (vedi [Libreria dei prompt](#libreria-dei-prompt)).
- **Solo locale.** ekte contatta solo gli endpoint configurati dall'utente, e
  l'interfaccia web ascolta solo su loopback (vedi [Server web](#server-web)).

## Ambiente di sviluppo

Richiede Python 3.11+. Linux, macOS e Windows sono testati in CI; i test sensati solo su POSIX vengono saltati su Windows con un motivo esplicito (`skipif(sys.platform == "win32", reason=...)`). Usa `pathlib`, passa `encoding="utf-8"` all'I/O di testo e non scrivere mai `/tmp` fisso. Node.js è facoltativo: i test del JavaScript del browser
girano con `node` e vengono saltati senza.

```bash
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e '.[dev,web]'   # installazione modificabile con gli strumenti di sviluppo e l'interfaccia web
pytest                        # suite di test
ruff check ekte tests         # lint
mypy ekte                     # controllo dei tipi
```

Con uv: `uv venv && uv pip install -e '.[dev,web]'`. Non servono
librerie di sistema, nemmeno per i rapporti PDF.

Esegui dai sorgenti con `ekte …` o `python -m ekte …`. `ekte serve` serve
l'interfaccia web direttamente da `ekte/web/static/`, quindi ricaricare il browser
applica le modifiche al frontend; non c'è una fase di build.

## Struttura del repository

```text
ekte/
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
  prompts/en.json      ogni testo che ekte invia a un'API di LLM
  perf/                registrazione per richiesta e la sezione prestazioni del rapporto
  report/              renderer JSON / Markdown / HTML / PDF e scrittura
  embed_audit.py       verificatore autonomo di embedding e rerank
  media_audit.py       verificatore autonomo di immagini e audio (TTS)
  notify.py            avvisi via webhook (Slack / Feishu / DingTalk / JSON generico)
  datadir.py           la directory dei dati locale e i suoi file SQLite
  legacy.py            le impostazioni ZING_* e la copia di ~/.zing di prima del cambio di nome
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
    masterkey.py       stati e azioni della chiave principale (server e `ekte secret`)
    static/            script condivisi da tutte le pagine (lang.js, i18n.js, icons.js, …)
    static/v2/         pagine, stili e script dell'interfaccia web
tests/                 suite pytest; conftest.py contiene il relay simulato
docs/                  METHODOLOGY (8 lingue), CI.md, DOCKER.md, PUBLISHING.md
examples/ekte.yaml     file di configurazione commentato
action.yml             l'action composita di GitHub
Dockerfile             immagine dell'interfaccia web
```

## Architettura

### Flusso di una verifica

`ekte check`, `ekte compare`, `ekte watch`, il flusso di verifica
dell'interfaccia web e il suo scheduler dei monitor finiscono tutti nella stessa
funzione, `ekte.runner.run_audit()`:

1. **Configurazione.** `ekte/config.py` unisce la configurazione YAML e le
   opzioni da riga di comando in `TargetConfig` (obiettivo, riferimento e giudice
   facoltativi) e `AuditOptions` (suite, dimensioni, dimensione delle sonde,
   output). Le chiavi API indicate come `env:VAR` o `file:/percorso` vengono
   risolte qui.
2. **Base di conoscenza.** `load_knowledge_base()` carica i profili integrati,
   `--kb-dir`/`EKTE_KB_DIR` e il `kb.db` dell'utente, e risolve il modello
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
6. **Rapporto.** Tutto confluisce in un `AuditReport` (`ekte/models.py`) con
   l'obiettivo oscurato, l'istantanea del profilo della base di conoscenza, la
   sezione prestazioni e le lingue delle sonde. La CLI lo renderizza e lo scrive;
   l'interfaccia web lo trasmette.

`run_audit()` accetta una callback `on_event`; il server web trasforma i suoi
eventi (rilevatore avviato/terminato con rilevazioni compatte, tempi per
richiesta raggruppati) in Server-Sent Events per la vista in tempo reale.

### Client

`ekte/clients/` ha un client per protocollo — `openai_compatible.py` (Chat
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

Un rilevatore è un file autonomo in `ekte/detectors/`: una sottoclasse di
`Detector` (`base.py`) con un `id`, un `name`, una `dimension`, la prima suite in
cui gira (`min_suite`), un `cost_hint` approssimativo per `--dry-run` e
`async def run(self, ctx) -> DetectorResult`. `@register` lo aggiunge al
registro; `ekte/detectors/__init__.py` importa ogni modulo così il registro è
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
`ekte serve`, quindi il lavoro che impegna la CPU non deve girarci sopra: un loop
bloccato ritarda le richieste delle altre verifiche e gonfia le latenze che
registrano. `helpers.build_filler()` costruisce il testo di riempimento in tempo
lineare e memorizza in cache le ultime dimensioni, e i rilevatori della finestra
di contesto e della cache dei prompt lo chiamano (insieme a `build_haystack()`)
tramite `asyncio.to_thread`. I conteggi dei token vengono da
`ekte/utils/tokenize.py`, un'euristica basata solo sulla libreria standard: ekte
non importa alcuna libreria di tokenizer e non scarica nulla in fase di
esecuzione, quindi funziona in ambienti con accesso limitato. L'argomento
`tokenizer` di `estimate_tokens()` è accettato ma non cambia il conteggio, e i
campi del rapporto `tokens_exact` / `exact_tokenizer` sono mantenuti per
compatibilità e valgono sempre false.

### Punteggio e verdetto

`ekte/scoring.py` contiene `DIMENSION_WEIGHTS` e le regole del verdetto: il
punteggio di una dimensione è la media a pari peso dei suoi rilevatori, il
punteggio complessivo la media ponderata delle dimensioni eseguite, e il livello
di rischio segue la scala di gravità descritta in
[Metodologia → Come ekte assegna i punteggi](docs/METHODOLOGY.it.md#come-ekte-assegna-i-punteggi).
Ogni dimensione registra come è stata calcolata in `DimensionScore.breakdown`,
che alimenta i **Dimension details** dei rapporti e le righe espandibili dei
**Controlli per dimensione** dell'interfaccia web.

### Base di conoscenza

`ekte/knowledge/` definisce lo schema dei profili (`schema.py`:
`ProviderProfile`, `ModelProfile`, `FingerprintProbe`), carica e unisce i livelli
(`loader.py`: YAML integrato → `EKTE_KB_DIR`/`--kb-dir` → il `kb.db`
dell'utente), salva le voci dell'utente (`store.py`), controlla e importa YAML
(`importer.py`), costruisce il prompt di ricerca per gli assistenti esterni
(`research.py`) e fotografa il profilo usato da un'esecuzione (`snapshot.py`). Gli
id di modello si risolvono in modo esatto, tramite alias o per nome normalizzato,
ristretti dal fornitore dichiarato. Il ripiego approssimato prende il nome della
KB più lungo contenuto nell'id dichiarato (un id di snapshot o decorato), a meno
che il resto dell'id nomini un altro livello o variante (`-mini`, `-lite`,
`-image`, …); un id troncato si risolve solo quando il nome di un unico modello
inizia con esso, quindi un id ambiguo come `gpt-4` non ottiene alcun profilo
invece di un livello indovinato. Ogni rapporto registra come è stato risolto
l'id.

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

Ogni testo che ekte invia a un'API di LLM — sonde di chat, il prompt del giudice,
schemi degli strumenti, input di embedding / rerank / immagine / audio — si trova
in `ekte/prompts/en.json` e si legge con `ekte.prompts.text()` / `get()`.
`{{name}}` indica un valore inserito a runtime. La lingua delle sonde è fissata
all'inglese (`PROBE_LANG`), indipendentemente dalla lingua dell'interfaccia,
perché i controlli delle risposte e le stime dei token sono calibrati su quei
testi esatti. Le sonde la cui lingua *è* la misura (per es. scioltezza in cinese,
tokenizer o autoidentificazione dei modelli cinesi) vivono con le loro risposte
attese nella base di conoscenza e dichiarano `prompt_lang` e un motivo
`language_bound`. Il runner registra le lingue usate in `prompt_languages`.

### Rapporti

`ekte/report/render.py` renderizza un `AuditReport` in JSON, JSON compatto per
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

### Superfici

La **superficie** è il tipo di endpoint verificato: `chat` (predefinito),
`embedding` o `rerank` (`ekte.config.SURFACES`; in seguito immagini, TTS). È un
secondo asse accanto alla suite, portato da `AuditOptions.surface`,
`AuditReport.surface` e da una colonna `surface` annullabile in `history.db` e
`watches.db` (`NULL` e un campo JSON mancante valgono `chat`; nessuna migrazione).

- I rilevatori dichiarano `surface: ClassVar[str]`; `select_detectors` filtra su
  di essa prima del livello di suite. I rilevatori di embedding e rerank
  riutilizzano le dimensioni esistenti.
- I pesi del punteggio e gli insiemi di dimensioni profilo / centrali /
  infrastruttura sono per superficie (`scoring.SURFACE_WEIGHTS`); la chat mantiene
  i suoi valori.
- Il registratore marca le chiamate di embedding con `op="embed"` e quelle di
  rerank con `op="rerank"` (`ekte.config.SURFACE_OPS`); le funzioni di
  `perf/summary.py` accettano un parametro `op` (predefinito `complete`).
- `embed_audit.run_embedding_audit()` e `run_rerank_audit()` (usate da
  `ekte embed` / `ekte rerank` e `/api/embed` / `/api/rerank`) eseguono il runner
  con `surface="embedding"` o `"rerank"`, passano l'esecuzione salvata precedente
  della stessa superficie come `previous_report` (deriva) e salvano il rapporto
  salvo indicazione contraria (`--no-save`).
- Rilevatori di rerank: `rerank.connectivity`, `rerank.known_answer`
  (CAPABILITY), `rerank.identity` e `rerank.drift` (MODEL_IDENTITY),
  `rerank.determinism` (RELIABILITY) e `performance.rerank`. Pesi:
  MODEL_IDENTITY 30, CAPABILITY 30, PERFORMANCE 20, RELIABILITY 10,
  CONNECTIVITY 10.
- Monitor: `surface` ed `embedding_dimensions` (0 = dalla base di conoscenza) di
  un monitor alimentano `AuditOptions` in `_run_one_watch_inner`; un monitor di
  embedding o rerank legge il suo riferimento di deriva con
  `history.latest_for(..., surface=...)` prima della verifica e confronta gli
  avvisi solo con esecuzioni della stessa superficie. La superficie si fissa alla
  creazione (`POST /api/watches`, `/api/watches/from-history/{id}`, che accetta
  anche `embedding_dimensions`) e `PATCH` non la cambia; `PATCH` cambia
  `embedding_dimensions` di un monitor di embedding (la scheda dei monitor v2 la
  modifica in linea).

### Verificatori autonomi

Immagini/audio (`media_audit.py`) non sono ancora superfici, quindi hanno i propri
piccoli verificatori con il proprio verdetto invece della pipeline dei
rilevatori. Condividono le impostazioni HTTP dei client, la base di conoscenza
(dimensioni native, formati immagine, voci) e la libreria di prompt. Tutta la
decodifica (intestazioni delle immagini, WAV) usa solo la libreria standard.

### Server web

`ekte/web/server.py` è un'app FastAPI creata da `create_app()`:

- **Pagine.** L'interfaccia web (`/v2/`, `/v2/history`, `/v2/watches`,
  `/v2/analytics`, `/v2/kb`, `/v2/accessibility`) è HTML statico. Non c'è una
  pagina Strumenti: le verifiche di embedding e rerank partono dalla pagina di verifica
  con il selettore del tipo di endpoint (`/v2/?surface=embedding|rerank`), e
  `/v2/tools` serve una piccola pagina che vi rimanda i vecchi link (`#rerank`
  sceglie il rerank, `?rerun=` viene passato). Gli indirizzi dell'interfaccia
  classica rimossa (`/`, `/history`, `/watches`, `/tools`, `/console`)
  reindirizzano (308) alle loro pagine v2, con la query string.
- **API.** `/api/jobs…` esegue le verifiche (vedi sotto); `/api/models` elenca i
  modelli di un relay; `/api/report/export` renderizza un rapporto;
  `/api/history…`, `/api/watches…`, `/api/kb…` e `/api/analytics…` servono le
  altre pagine. `/api/audit/stream` (una verifica trasmessa via SSE), `/api/embed`
  e `/api/rerank` (una verifica sincrona di embedding / rerank) non sono più usati
  dall'interfaccia web; il loro futuro è seguito nelle issue #3 e #4.
- **Relay.** `POST /api/kb/relays` salva un relay `{name, base_url}` (400 per un
  input non valido, 409 se il nome o l'URL sono già noti).
- **Analisi.** `GET /api/analytics/options` (relay, modelli, suite, modalità di
  stream, API e intervallo di date della cronologia), `/api/analytics/summary`
  (KPI di `from`–`to` rispetto all'intervallo precedente di pari durata),
  `/api/analytics/series` (`metric` per `group=relay|model|relay_model`, fino a
  4 `keys`, in intervalli `bucket=hour|day|week|dow_hour` nel fuso orario
  dell'utente, `tz` o `tz_offset`; `dow_hour` accetta anche `block` (ore per riga) e
  `fold=week|4weeks|month_week`, che torna a `week` finché le esecuzioni non
  coprono 90 o 180 giorni) e `/api/analytics/leaderboard` (`model=` per
  i suoi relay, oppure `relay=` per i suoi modelli). Tutti accettano i filtri
  `from`, `to`, `suite`, `stream_mode`, `api`, `source=all|manual|monitor`,
  `relay` e `model`. `ekte/web/analytics.py` calcola tutto in Python da
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
  dal vivo via SSE, e `POST /api/jobs/{id}/cancel` lo ferma. L'interfaccia web
  li usa, quindi una verifica sopravvive alla pagina; `/api/audit/stream`
  avvolge lo stesso job e lo annulla
  alla chiusura del flusso. Un blocco per relay lascia usare un relay a una sola
  verifica (o esecuzione di monitor) alla volta, per nome host, con tutti gli
  indirizzi loopback come un solo host; al massimo `EKTE_MAX_PARALLEL_AUDITS`
  (predefinito 4) insieme, in ordine di arrivo.
- **Scheduler dei monitor.** Il lifespan dell'app avvia un ciclo in background che
  avvia ogni monitor in scadenza come task a sé, così i monitor su relay diversi
  eseguono le verifiche contemporaneamente; il blocco per relay resta valido,
  quindi i monitor possono occupare i posti di `EKTE_MAX_PARALLEL_AUDITS` e una
  verifica avviata a mano può finire in coda dietro di loro. Il `last_run_ts` di
  un'esecuzione è il momento in cui inizia la sua verifica (dopo l'attesa del suo
  relay). Ogni esecuzione è registrata nella cronologia; il controllo di
  regressione la confronta con l'esecuzione salvata più recente dello stesso
  obiettivo e modello (`history.latest_for()`, una sola ricerca indicizzata) e
  invia gli avvisi via webhook (`ekte/notify.py`) in parallelo al superamento di
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
  tranne in un container rilevato con `EKTE_CONTAINER=1`) e installa
  `LocalOnlyMiddleware`: un elenco di host ammessi contro il DNS rebinding,
  controlli di `Origin` e `Sec-Fetch-Site` contro il CSRF, corpi di richiesta solo
  JSON e intestazioni anti-frame / no-sniff / no-referrer. L'interfaccia non ha
  login per scelta.

### Frontend web

Il frontend è HTML, CSS e JavaScript da browser semplici, senza moduli né fase di
build. Le pagine sono in `ekte/web/static/v2/` e condividono un'intestazione (`nav.js`), il renderer del
rapporto (`report.js`), il selettore del tema (`theme.js`) e gli stili
(`tokens.css`, `ekte.css`, `fields.css`, `report.css`, `perf.css`). Gli script condivisi sono
serviti dalla radice: `lang.js` (cambio lingua), `locales.js` (dati di
traduzione), `i18n.js` (traduzione delle rilevazioni), `icons.js` (con il logo di
ekte), `secretfield.js` e `perf.js` (grafici delle prestazioni).

Ogni pagina v2 tranne Accessibilità ha un **avviso di pagina** subito sotto
l'hero (`<div class="znote" id="note">`, disegnato da `v2/notice.js`, con lo
stile `.znote` in `ekte.css`): `EkteNotice.show(el, {level, title, detail,
items, actions})`; il livello `info`, `success`, `warning` o `critical` imposta
tinta, bordo e icona (critical è `role="alert"`, gli altri `role="status"`;
mostrare di nuovo lo stesso avviso non cambia nulla). La pagina sceglie il
messaggio più importante ed elenca gli altri in `items`. Verifica: server non
raggiungibile / audit in corso / l'esecuzione salvata più recente / eseguito in
locale; Cronologia: cronologia illeggibile / esecuzioni dei monitor in pausa
(chiave master bloccata) o esecuzioni precedenti ancora in elaborazione / numero
di esecuzioni; Analisi: dati illeggibili / esecuzioni non ancora nei grafici o
con orario di inizio stimato / su cosa si basa; Conoscenza: errore di
caricamento / voci saltate o ignorate / elementi disattivati / completa. Monitor
mantiene la sua barra della chiave master (`masterkey.js`), con lo stesso aspetto
e posto. I numeri dell'intera cronologia vengono da `GET /api/history/status`
(`history.status()`: numero di esecuzioni, la più vecchia e la più recente,
righe non ancora elaborate dal backfill delle analisi, esecuzioni con orario di
inizio stimato).

La pagina v2 **Verifica** configura i relay con
`v2/relaycfg.js`: scelta relay/provider → URL di base → i modelli del relay
(`/api/models`, al cambiamento, in cache per URL/chiave/protocollo) → modello
dichiarato dalla base di conoscenza (`/api/kb/resolve` lo preseleziona) →
provider derivato, più **Salva nella base** (`POST /api/kb/relays`). Le sue
funzioni pure sono testate con node.

La pagina v2 **Analisi** (`v2/analytics.html`) legge solo `/api/analytics/*`
(`options` elenca anche le coppie relay × modello, `relay_models`, per la scelta
delle serie). Ha una `<section class="card panel">` per pannello sotto un'unica
barra dei filtri, quindi si possono aggiungere pannelli; filtri e vista stanno
nel frammento dell'URL (`#range=30&metric=score&…`) e in `localStorage`. I
grafici vengono da `v2/charts.js` (`EkteCharts.timeChart`: SVG inline disegnato
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
vicenda. `EkteCharts.heatmap` disegna la griglia giorno della settimana × ora
(scala sequenziale a una tinta in cinque livelli per tema, celle tratteggiate
per `low_n`, celle vuote solo con contorno), `EkteCharts.stackBars` le barre di
errore impilate, e `timeChart` accetta una linea `ref` (rapporto di
fatturazione del 100%). `EkteCharts.donut` (un anello di parti di un intero con
una cifra HTML al centro) e `EkteCharts.meter` (una barra sottile di parti)
disegnano la scheda Copertura del rapporto di accessibilità; i loro colori
`k-*` (chi decide un passo: blu la suite di test, viola una persona) vengono da
`tokens.css`. `v2/chartmotion.js` (`EkteMotion.enter`) disegna un anello in
senso orario e fa crescere le barre da sinistra, come per gli altri grafici,
solo quando arrivano dati nuovi e mai con il movimento ridotto o con
l'animazione disattivata nell'intestazione.

L'intestazione della pagina e il pannello dei filtri stanno sopra cinque schede
interne (`v2/tabs.js`, come in Conoscenza): ogni voce di
`PANELS` indica la sua `tab`, e si caricano solo i pannelli della scheda
visibile; una modifica dei filtri ricarica quella scheda e segna le altre come
non aggiornate (`activate()` le carica quando vengono mostrate). Qui `tabs.js`
riceve `writeHash: false`, perché la pagina scrive da sé l'intera vista nel
frammento — `#tab=trends&range=30&suite=…&metric=…` (`stateQuery()`), che
**Copia il link a questa vista** copia (un campo di sola lettura selezionato se
l'API degli appunti manca o rifiuta); un frammento senza `tab` apre la
Panoramica, e un link incollato (`hashchange`) rilegge la vista. Il pannello dei
filtri richiudibile è `v2/filterpanel.js` + `v2/filterpanel.css`, condiviso con
la Cronologia, Monitor e Conoscenza: `EkteFilterPanel.create(section, {label, title, storeKey, open,
onReset})` restituisce `render({body, foot, count, summary})`,
`sync({count, summary})`, `setOpen()` e `focusStart()`; la pagina gestisce i
propri filtri e campi, il pannello il pulsante con il badge dei filtri attivi,
il riepilogo di una riga mostrato da chiuso, lo stato aperto memorizzato e
**Reimposta filtri**.

**Convenzione di traduzione.** Il testo cinese scritto nell'HTML è l'originale e
resta intatto; ogni elemento porta il suo testo inglese in `data-en` (e
`data-en-placeholder`, `data-en-title`, `data-en-aria-label`). Il testo inglese è
la chiave di ricerca per tutte le altre lingue. Gli script usano `T(zh, en)` per
il testo dinamico e `EKTE_LANG.server(text)` per il testo proveniente dal backend
(nomi dei rilevatori, raccomandazioni, frasi del verdetto).

### Dati locali

`ekte/datadir.py` gestisce `$EKTE_DATA_DIR` (predefinito `~/.ekte`), creato con
`0700`, con file SQLite `0600`: `history.db` (`web/history.py`), `watches.db`
(`web/watches.py`, che conserva cifrate le chiavi API dei monitor) e `kb.db`
(`knowledge/store.py`). Ogni chiamata apre una connessione di breve durata,
quindi gli archivi sono sicuri nel pool di thread di FastAPI. L'opzione globale
`--data-dir` (anche su `ekte serve`) imposta semplicemente `EKTE_DATA_DIR` sul
percorso assoluto, e `ekte data-dir` stampa la directory risolta. Una directory
già esistente mantiene i suoi permessi; solo il `~/.ekte` predefinito viene
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

Dove vengono conservate le chiavi API dei monitor lo sceglie l'utente
(`watches.get_key_storage()`, una riga di `secret_meta`): `memory`, il valore
predefinito, non ne salva nessuna — la colonna `api_key` contiene solo il
marcatore `mem:` e la chiave vive in `watches._memory_keys` finché il processo non
termina (dopo un riavvio la riga è `key_missing`, che lo scheduler tratta come una
chiave bloccata: l'esecuzione attende, nessun avviso); `encrypted` le salva come
descritto sotto. Senza riga, un archivio che ha già chiavi cifrate o un valore di
controllo, o con `EKTE_SECRET_KEY` / un vecchio `secret.key`, parte in
`encrypted`; la scelta viene registrata all'avvio. `Vault.set_storage()`
(`POST /api/secret/storage`) cambia modalità e sposta le chiavi in una transazione
(`keys_to_memory()` cancella quelle cifrate e il valore di controllo e ripulisce il
file; `keys_to_store()` sigilla quelle in memoria). Una richiesta può passare
`key_storage: "memory"` per tenere la sua chiave fuori dal database qualunque sia
l'impostazione; niente può forzare il salvataggio.

Le chiavi API salvate sono cifrate da `ekte/secretbox.py` (Fernet, salvate come
`enc:v1:…`; i riferimenti `env:`/`file:` restano come sono). La chiave
principale non viene mai salvata: `web/masterkey.py` (`Vault`, condiviso dal
server e da `ekte secret`) la tiene nella memoria del server appena arriva da
`EKTE_SECRET_KEY`, da un vecchio `secret.key` o dall'utente nella pagina
Monitor, e `watches.db` conserva solo un valore di controllo (`secret_meta`) che
rifiuta una chiave sbagliata. Una nuova chiave ricifra ogni chiave salvata e
riscrive il valore di controllo in un'unica transazione. La chiave vive nella
memoria di un solo processo, quindi esegui un server per directory dei dati.

`ekte/legacy.py` mantiene funzionanti le installazioni di prima del cambio di
nome: ogni impostazione `EKTE_*` viene letta con `legacy.getenv`, che ripiega
sul vecchio nome `ZING_*` (segnalato una volta su stderr), e
`datadir.data_dir()` copia una sola volta `~/.zing` in `~/.ekte` quando esiste
solo la vecchia directory (i file SQLite tramite l'API di backup, in una
directory temporanea accanto poi rinominata). `~/.zing` non viene mai modificata
né eliminata. `lang.js` copia allo stesso modo le impostazioni `zing.*` del
browser in `ekte.*`, e il server legge ancora i cookie `zing_lang` / `zing_ui`
finché non esistono quelli `ekte_*`.

## Contribuire

### Pull request

- Mantieni verdi `pytest`, `ruff check ekte tests` e `mypy ekte` (la CI li esegue
  tutti e tre con Python 3.11–3.14).
- Descrivi il trucco del relay o il falso positivo che la modifica affronta.
- Aggiorna `CHANGELOG.md` sotto `[Unreleased]`.
- Aggiorna la documentazione interessata — README, questa guida, la Metodologia —
  in **ogni lingua** (vedi [Documentazione](#documentazione)).

Contribuendo accetti che i tuoi contributi siano rilasciati sotto la licenza
[Apache-2.0](LICENSE) del progetto.

### Aggiungere un rilevatore

1. Crea `ekte/detectors/<name>.py` e importalo in `ekte/detectors/__init__.py`.
2. Definisci la sua `SCALE` (`Scale` o `DeductionScale` da `scale.py`) con ogni
   esito di ogni controllo, e crea le rilevazioni solo tramite essa.
3. Estendi `Detector`; imposta `id`, `name`, `dimension`, `min_suite` e
   `cost_hint`; imposta `requires_judge = True` o `requires_baseline = True` se
   serve un giudice o un riferimento, oppure ridefinisci `applies()` per altre
   condizioni. Decora la classe con `@register`.
4. Implementa `async def run(self, ctx) -> DetectorResult` partendo da
   `self.new_result(scoring=SCALE.scoring())`. Invia le richieste tramite
   `ctx.client` e prendi ogni prompt da `ekte/prompts/en.json`.
5. Aggiungi test di comportamento sia per il percorso segnalato sia per quello
   pulito, con il relay simulato di `tests/conftest.py`.
6. Traduci i nuovi titoli e riepiloghi delle rilevazioni (vedi
   [Traduzioni](#traduzioni)) e documenta il rilevatore e la sua scala in ogni file
   di [Metodologia](docs/METHODOLOGY.it.md).

### Modificare la base di conoscenza

I profili sono in `ekte/knowledge/data/<provider>.yaml`, un file per fornitore.
Ogni modello riporta finestra di contesto nativa, output massimo, data di cutoff
delle conoscenze, tokenizer, modalità, capacità, parametri non supportati, parole
chiave d'identità e impronte (vedi `ekte/knowledge/schema.py`). Quando modifichi
un campo numerico, **cita una fonte autorevole** (la scheda ufficiale del modello,
i prezzi o la documentazione del fornitore) nella pull request: un valore errato
causa falsi positivi contro relay onesti. `ekte kb-import --check <file>` esegue
gli stessi controlli dell'importazione utente (schema, limiti, espressioni
regolari pericolose, prompt, collisioni di id).

Le `fingerprints` a livello di fornitore girano su ogni suo modello. Una sonda la
cui attesa vale solo per alcuni modelli (una data di cutoff, una verifica di
conoscenze del livello Pro, una trappola di ragionamento) va nelle
`fingerprints` di quei modelli, altrimenti la risposta veritiera di un altro
modello conta come divergenza.

Compila sempre `identity_keywords` con le parole del produttore e della
famiglia con cui il modello si identifica. Il controllo d'identità conta anche
la chiave del provider, il nome visualizzato e l'id del modello come marchio
autentico, estesi agli altri nomi del produttore in `VENDOR_BRANDS`
(`ekte/knowledge/identity.py`, che è anche l'elenco dei marchi rivali del
detector); l'importazione completa le parole chiave vuote a partire da questi
nomi con un avviso. Le parole di marchio di un nuovo produttore vanno aggiunte
lì come un gruppo.

### Modificare i prompt delle sonde

I testi delle sonde sono dati di calibrazione. Modificarne uno in
`ekte/prompts/en.json` può cambiare i controlli delle risposte, le stime dei
token e quindi i verdetti; adegua il rilevatore e i suoi test e cita la modifica
nel CHANGELOG. Non far mai seguire a una sonda la lingua dell'interfaccia.

### Traduzioni

L'interfaccia e gli avvisi via webhook condividono un unico insieme di traduzioni
in `ekte/i18n/locales/<code>.json`:

- `meta` — codice, il nome della lingua nella lingua stessa per il menu, lingua
  `html`, impostazioni locali delle date e ordine nel menu;
- `strings` — testo inglese → traduzione (`en.json` è la mappa identità e
  l'elenco di riferimento dei testi traducibili);
- `findings` — id della rilevazione → `[titolo, modello del riepilogo]`
  (`zh.json` contiene il catalogo cinese originale).

Le funzionalità possono fornire i propri testi come frammenti,
`ekte/i18n/locales/fragments/<feature>/<code>.json` con `{"strings": {…}}`,
uniti alla lingua al caricamento. `/locales.js` invia solo la lingua scelta
(`?lang=<code>` o il cookie `ekte_lang` impostato da `lang.js`; senza nessuno dei
due, tutte le lingue), generato e compresso con gzip una volta per variante e
rivalidato tramite `ETag`; un cambio di lingua carica la nuova su richiesta.

- **Nuovo testo dell'interfaccia:** scrivi il cinese nell'HTML e l'inglese in
  `data-en` (o usa `T(zh, en)`), poi aggiungi la chiave inglese a `en.json` o a
  un frammento e la sua traduzione in ogni altra lingua.
- **Nuova lingua:** aggiungi `ekte/i18n/locales/<code>.json` (copia `de.json`) e
  un file per frammento; il menu, le pagine, gli avvisi e `--alert-lang` la
  recepiscono.
- `tests/test_web_locales.py` fallisce finché ogni testo dell'interfaccia e ogni
  rilevazione non sono tradotti con segnaposto e markup intatti.

**Terminologia.** Ogni termine ha una sola traduzione per lingua. Riusa la
terminologia che l'interfaccia usa già (nomi delle pagine, nomi delle dimensioni,
etichette di rischio, etichette dei pulsanti) nei nuovi testi e nella
documentazione.

### Documentazione

La documentazione esiste in otto lingue — inglese, cinese (`zh-CN`), francese,
spagnolo, portoghese, italiano, tedesco e norvegese (bokmål, `nb`):

| File | Destinatari |
|---|---|
| `README.md`, `README.<lang>.md` | Utenti: cosa fa ekte, installazione, uso della CLI e dell'interfaccia web |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Contributori: architettura, ambiente, contributi, Docker, rilasci |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Tutti: ogni controllo, la sua scala dei punteggi e le sue avvertenze |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Pagine di riferimento (in inglese) |

I file inglesi sono il riferimento. Quando ne modifichi uno, modifica gli altri
nella stessa pull request e usa in ogni lingua la terminologia dell'interfaccia
(cerca il termine in `ekte/i18n/locales/`). I file METHODOLOGY riportano le scale
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
  `httpx.MockTransport` con manopole per ogni scostamento che ekte cerca (modello
  servito, autoidentificazione, troncamento del contesto, streaming finto,
  consumo assente o gonfiato, chiamate di strumenti, modalità JSON, …). Ogni
  manopola ha per impostazione predefinita il comportamento di un relay onesto.
- I client Anthropic e Responses hanno test propri (`test_anthropic.py`,
  `test_responses.py`); il server web è testato con il client di test di FastAPI
  (`test_web*.py`), comprese le protezioni per l'uso locale
  (`test_web_security.py`).
- Gli script del browser (`lang.js`, `v2/relaycfg.js`, `perf.js`,
  `secretfield.js`, `v2/report.js`, le traduzioni) vengono valutati con `node` in
  `test_web_*_js.py` e `test_web_locales.py`; senza Node.js vengono saltati.
- Nessun test può accedere alla rete.
- `test_cli_startup.py` mantiene rapido l'avvio della CLI: importare `ekte.cli`
  non deve caricare i client HTTP, il runner, il caricatore della base di
  conoscenza, i renderer dei rapporti (ReportLab) né il server web. Importali
  dentro il comando che ne ha bisogno.
- `test_filler_perf.py` fissa il testo di riempimento byte per byte e fallisce
  quando la sonda della finestra di contesto blocca l'event loop.
- `tests/a11y/` verifica l'interfaccia web (v2) rispetto a BITV 2.0 /
  EN 301 549 / WCAG 2.1 AA in un browser reale (Playwright + axe-core), in ogni
  lingua dell'interfaccia e con entrambi i temi:
  `pip install -e '.[web,a11y]' && playwright install chromium`, poi
  `pytest -m a11y`. Senza Playwright la directory viene saltata. Cosa è
  automatizzato e cosa richiede ancora una revisione BITV manuale è descritto in
  [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md) (in inglese).
- `EKTE_A11Y_PAGES=history,kb` esegue solo i test a11y di quelle pagine (più i
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
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# apri http://localhost:8000
```

**Pubblica sempre su `127.0.0.1`.** Un semplice `-p 8000:8000` pubblica
l'interfaccia — e ogni chiave API digitata al suo interno o salvata in un monitor
— sulla tua rete. Nel container il server deve ascoltare su tutte le interfacce;
è consentito solo se `EKTE_CONTAINER=1` è impostato (l'immagine lo imposta) *e*
viene rilevato un ambiente container.

| Variabile | Predefinito | Scopo |
|---|---|---|
| `EKTE_CONTAINER` | non impostata (`1` nell'immagine) | Consente l'ascolto fuori da loopback in un container rilevato |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` nell'immagine) | Indirizzo di ascolto; `--host` prevale |
| `EKTE_PORT` | `8000` | Porta; `--port` prevale |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` nell'immagine) | Cronologia, monitor (con le loro chiavi cifrate) e le tue voci della base di conoscenza; monta qui un volume. `--data-dir` ha la precedenza |
| `EKTE_SECRET_KEY` | non impostata | Chiave principale delle chiavi API salvate dei monitor (una chiave, oppure `file:/run/secrets/…` / `env:VAR`); se non impostata, la pagina Monitor la chiede dopo ogni avvio. Mai salvata in `EKTE_DATA_DIR` |
| `EKTE_KB_DIR` | non impostata | Directory YAML aggiuntiva per la base di conoscenza, per es. `-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb` |
| `EKTE_NO_USER_KB` | non impostata | `1` ignora le tue voci della base di conoscenza (`kb.db`) |
| `EKTE_ALLOWED_HOSTS` | non impostata | Nomi host aggiuntivi a cui l'interfaccia risponde, separati da virgole |

[docs/DOCKER.md](docs/DOCKER.md) è il riferimento completo (in inglese), comprese
le protezioni dell'interfaccia.

## Integrazione continua

| Workflow | Si avvia con | Cosa fa |
|---|---|---|
| `.github/workflows/ci.yml` | push e pull request verso `main` (e i branch di integrazione `a11y/integration`, `perf/integration`); ogni notte e manuale (solo accessibilità) | `ruff`, `mypy` e `pytest` con Python 3.11–3.14 e gli extra `dev` e `web`; costruisce wheel e sdist e verifica che la wheel si installi e carichi la base di conoscenza; esegue la suite di accessibilità (informativa, non fa mai fallire l'esecuzione) e ne carica i risultati: tutte le pagine sui push e nelle esecuzioni notturne e manuali (con il rapporto di conformità BITV), nelle pull request solo le pagine toccate dalla modifica (nessuna se cambia solo la documentazione) — tranne nelle pull request verso `perf/integration`, dove la lenta suite nel browser viene saltata (gira sui push di quel branch e sulla sua pull request verso `main`) |
| `.github/workflows/release.yml` | un tag `v*` | costruisce, esegue `twine check` e pubblica su PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | pianificazione giornaliera, manuale | esempio di verifica pianificata di un relay con l'action |

L'action composita è `action.yml`, documentata in [docs/CI.md](docs/CI.md).

### File di terze parti nella distribuzione

La distribuzione dei sorgenti contiene i test, ma nessun file di terze parti incluso. `tests/a11y/vendor/axe.min.js` (axe-core, MPL-2.0) è solo nel repository git; è escluso dallo sdist (`exclude` in `[tool.hatch.build.targets.sdist]` di `pyproject.toml`) e non è mai stato parte del wheel.

- I test che richiedono un file escluso vengono saltati con un motivo chiaro se manca; esegui la suite di accessibilità da un checkout git.
- `NOTICE` elenca ogni file di terze parti e dice se è distribuito. Aggiungi un nuovo file incluso alla lista `exclude` e a `NOTICE`, oppure, se deve essere distribuito, dichiaralo in `NOTICE`.
- `scripts/check_dist_contents.py` costruisce wheel e sdist (`uv build`) e fallisce se è presente un file escluso o un file che `NOTICE` indica come non distribuito. Il workflow `.github/workflows/dist.yml` lo esegue in un job separato.

## Rilasci

Un rilascio è un tag di versione; tutto il resto è automatizzato e verificato. La
checklist è in [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md), la
configurazione una tantum di PyPI e la procedura manuale in
[docs/PUBLISHING.md](docs/PUBLISHING.md).

### Creare un rilascio

1. Percorrere la [checklist di rilascio](docs/RELEASE_CHECKLIST.md): versione e
   changelog, versioni di Python e sistemi supportati, aggiornamento della base di
   conoscenza, fixture di aggiornamento, revisione di accessibilità per le modifiche
   alla UI, documentazione in tutte le lingue, avvisi di sicurezza.
2. Impostare `version` in `pyproject.toml` e rinominare `[Unreleased]` in
   `CHANGELOG.md` in `[X.Y.Z] - AAAA-MM-GG`. Verificare in locale con
   `python scripts/release_check.py version vX.Y.Z` e `... notes vX.Y.Z`.
3. Fare il merge, taggare il commit e inviare il tag:
   `git tag -a vX.Y.Z -m "ekte vX.Y.Z"`, `git push origin vX.Y.Z`.
4. `release.yml` verifica prima, con `scripts/release_check.py`, che il tag
   corrisponda alla versione del pacchetto, che `CHANGELOG.md` abbia una sezione per
   essa e che la CI sia verde per il commit taggato (attende una CI in corso). Se un
   controllo fallisce, il workflow si ferma e non viene pubblicato nulla. Poi
   compila, pubblica su PyPI tramite Trusted Publishing con attestazioni di
   provenienza e crea la GitHub Release con la sezione del changelog come note.

### Release candidate

Taggare `vX.Y.ZrcN` (con `version = "X.Y.ZrcN"` in `pyproject.toml`). PyPI la tratta
come pre-release PEP 440: `pip install ekte` la ignora, `pip install --pre ekte` la
trova; GitHub contrassegna la release come «Pre-release». Nel changelog basta la
sezione `[X.Y.ZrcN]`, `[X.Y.Z]` o `[Unreleased]`.

### Se una pubblicazione fallisce a metà

PyPI non accetta mai due volte lo stesso file e una versione non si può riutilizzare;
conta quanto è andata avanti l'esecuzione (Actions, «Release to PyPI»):

- **Un controllo è fallito (job verify).** Non è stato pubblicato nulla. Correggere
  la causa (versione, changelog, CI), eliminare il tag in locale e su origin
  (`git push origin :refs/tags/vX.Y.Z`) e taggare di nuovo il commit corretto.
- **Build o upload falliti prima che PyPI avesse file.** Rieseguire i job falliti;
  nessuna versione è stata consumata. Se il commit taggato deve cambiare, eliminare
  il tag e ricrearlo.
- **PyPI ha una parte dei file** (vedi <https://pypi.org/project/ekte/#files>).
  Rieseguire i job falliti: l'upload salta i file già presenti. Se i file differiscono
  da quanto si vuole rilasciare, non riprovare: fare «yank» della versione su PyPI e
  rilasciare la successiva (`X.Y.Z+1` o `rcN+1`).
- **PyPI è completo ma la GitHub Release è fallita.** Rieseguire il job
  `GitHub Release`; crea o aggiorna la release in modo idempotente. Oppure a mano:
  `gh release create vX.Y.Z --notes-file <(python scripts/release_check.py notes vX.Y.Z)`.
- **Una versione difettosa è già online.** Fare «yank» su PyPI (resta installabile
  solo con versione esatta), correggere in avanti con una nuova versione e annotarlo
  nel suo changelog.

## Sicurezza

Segnala le vulnerabilità in privato, come descritto in [SECURITY.md](SECURITY.md).
Rientrano nell'ambito soprattutto: una chiave o un segreto che finisce in un
rapporto, testo controllato dal relay che inietta markup in un rapporto o
nell'interfaccia, traffico verso qualcosa di diverso dagli endpoint configurati,
e modi per aggirare le protezioni per l'uso locale dell'interfaccia web.

## Licenza

[Apache-2.0](LICENSE)
