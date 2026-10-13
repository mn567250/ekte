# zing — Metodologia

> [🇬🇧 English](METHODOLOGY.md) · [🇨🇳 中文](METHODOLOGY.zh-CN.md) · [🇫🇷 Français](METHODOLOGY.fr.md) · [🇪🇸 Español](METHODOLOGY.es.md) · [🇵🇹 Português](METHODOLOGY.pt.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](METHODOLOGY.de.md)

Questo documento spiega come **zing** arriva al suo verdetto: quali sonde
black-box invia ogni rilevatore, come i loro esiti diventano punti, come i punti
diventano punteggi di dimensione e un punteggio complessivo, e come viene deciso
il verdetto di rischio. Descrive l'implementazione attuale; ogni tabella di
punteggio qui sotto è la scala pubblicata del rilevatore (`SCALE` in
`zing/detectors/*.py`), con la stessa formulazione che l'interfaccia web mostra
in **Scala dei punteggi**.

> zing fornisce **prove black-box di scostamenti e rischi, non una prova
> crittografica di frode.** Vedi [Limiti e uso responsabile](#limiti-e-uso-responsabile).

---

## Posizione di fondo

Un relay può, per motivi legittimi, discostarsi, aggiornare gli snapshot,
condividere capacità o bufferizzare un upstream che non supporta lo streaming.
Per questo zing tratta ogni singolo segnale come un *indicatore di rischio*, mai
come un verdetto: le rilevazioni si basano su prove, sono formulate con cautela,
e un risultato ambiguo resta **non conclusivo** invece di essere forzato in
superato o fallito. Il verdetto di rischio arriva ad «alto» solo con prove
solide di gravità alta, e la conferma più forte è sempre la **modalità di
confronto** (`zing compare`): eseguire le stesse sonde, nello stesso momento,
contro un *riferimento affidabile del modello dichiarato*.

## Come zing assegna i punteggi

### Punteggio del rilevatore

Ogni rilevatore pubblica la propria **scala dei punteggi**
(`DetectorResult.scoring`, costruita con `zing/detectors/scale.py`): ogni esito
possibile di ciascuno dei suoi controlli, con stato, gravità ed effetto sul
punteggio. Ogni rilevazione registra l'`outcome` raggiunto, quindi rapporto e
comportamento non possono divergere. Una scala usa uno di due metodi:

- **Media dei controlli** (`Scale`, metodo `mean_of_checks`): ogni controllo
  assegna punti; il punteggio del rilevatore è la media dei controlli
  conteggiati. Un esito segnato **Non conteggiato** (tipicamente un controllo
  non conclusivo) non alza né abbassa il punteggio.
- **Detrazioni** (`DeductionScale`, metodo `deductions`): il punteggio parte da
  100, le rilevazioni tolgono punti (`Finding.deduction`) e/o lo limitano
  (`Finding.cap`); vale il tetto più basso.

Un controllo *parametrizzato* applica uno stesso insieme di righe a molti
soggetti (per esempio ogni attributo della risposta): ogni soggetto riceve un
punteggio a sé, la scala è pubblicata una volta per controllo e i rapporti
elencano i soggetti sotto il loro controllo.

### Punteggio e stato di una dimensione

zing assegna un punteggio a dieci dimensioni. Il punteggio di una dimensione è
la **media a pari peso dei punteggi dei suoi rilevatori**: un rilevatore con
molti controlli non pesa più di uno con pochi, e un rilevatore senza punteggio
numerico resta escluso. Il suo stato è il peggiore stato concluso dai suoi
rilevatori, tranne che una rilevazione di gravità ALTA/CRITICA impone
**Fallito** e una rilevazione di gravità MEDIA porta **Superato** ad **Avviso**,
qualunque sia il punteggio. Ogni rapporto registra questo calcolo per dimensione
(`DimensionScore.breakdown`: il punteggio di ogni rilevatore, se è stato
conteggiato, ed eventuali cambi di stato con le rilevazioni che li hanno
causati) e lo mostra in **Dimension details** (Markdown/HTML/PDF) e nelle righe
espandibili dei **Controlli per dimensione** dell'interfaccia web. Un
rilevatore che va in errore compare con stato **Errore** e non interrompe mai
l'audit.

### Punteggio complessivo, voto e pesi

Il **punteggio di salute complessivo** è la media ponderata delle dimensioni che
hanno prodotto un punteggio (`DIMENSION_WEIGHTS` in `zing/scoring.py`). Una
dimensione che non è stata eseguita (fuori dalla suite, o non selezionata in
un'esecuzione `custom`) esce dal calcolo e i pesi restanti vengono
rinormalizzati. Il voto è A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) o F.

| Dimensione | Id | Peso | Ruolo |
|---|---|---|---|
| Identità del modello | `model_identity` | 21 | centrale |
| Finestra di contesto | `context_window` | 19 | centrale |
| Capacità dichiarate | `capability` | 13 | centrale |
| Conformità del protocollo | `protocol` | 8 |  |
| Fatturazione e consumo | `billing` | 8 |  |
| Connettività | `connectivity` | 7 |  |
| Autenticità dello streaming | `streaming` | 6 |  |
| Affidabilità in concorrenza | `reliability` | 6 |  |
| Sicurezza del trasporto | `security` | 6 |  |
| Prestazioni | `performance` | 6 |  |

Le tre **dimensioni centrali** sono quelle il cui fallimento rivela più
direttamente una merce non conforme.

### Verdetto di rischio

Il livello di rischio dipende dalla **gravità delle rilevazioni**, non dal
punteggio. Le rilevazioni della dimensione connettività sono escluse: un relay
irraggiungibile o limitato non ha potuto essere valutato, e questo non prova che
risponda un altro modello.

| Rischio | Etichetta nell'interfaccia | Quando |
|---|---|---|
| `inconclusive` | Segnale insufficiente | Nessuna dimensione centrale ha prodotto un risultato utilizzabile (Superato, Avviso o Fallito) — per esempio relay irraggiungibile, modello senza profilo, o esecuzione `custom` senza dimensioni centrali |
| `high` | Merce non conforme | Una rilevazione CRITICA, una rilevazione ALTA/CRITICA in una dimensione centrale, o due o più rilevazioni ALTE |
| `medium` | Scostamenti rilevati | Esattamente una rilevazione ALTA fuori dalle dimensioni centrali, o una rilevazione MEDIA in una dimensione centrale |
| `low` | Per lo più affidabile | Qualsiasi altra rilevazione MEDIA |
| `clean` | Coerente (probabilmente autentico) | Nessuno dei casi precedenti |

### Affidabilità del verdetto

- **Bassa** — il modello dichiarato non è nella base di conoscenza, oppure meno
  di due dimensioni centrali hanno prodotto un risultato utilizzabile;
- **Media** — almeno due dimensioni centrali hanno prodotto un risultato
  utilizzabile;
- **Alta** — è stato usato un riferimento *e* tutte e tre le dimensioni centrali
  hanno prodotto un risultato utilizzabile, oppure l'affidabilità era media e il
  giudice LLM ha restituito un verdetto utilizzabile.

## Suite, rilevatori e modalità

| Rilevatore | Id | Dimensione | Dalla suite |
|---|---|---|---|
| Connettività e completamento di base | `connectivity` | Connettività | `smoke` |
| Conformità alla compatibilità OpenAI | `protocol` | Conformità del protocollo | `standard` |
| Supporto degli attributi di richiesta | `protocol_request` | Conformità del protocollo | `standard` |
| Disponibilità degli attributi di risposta | `protocol_response` | Conformità del protocollo | `standard` |
| Determinismo e correttezza della cache | `determinism` | Conformità del protocollo | `deep` |
| Finestra di contesto reale e troncamento | `context_window` | Finestra di contesto | `deep` |
| Identità del modello e impronta di declassamento | `model_identity` | Identità del modello | `standard` |
| Valutazione di qualità / declassamento da parte di un LLM giudice | `quality_judge` | Identità del modello | `deep` (solo con `--judge`) |
| Verifica delle capacità dichiarate | `capability` | Capacità dichiarate | `standard` |
| Verifica della capacità multimodale (visione) | `vision` | Capacità dichiarate | `deep` |
| Autenticità dello streaming | `streaming` | Autenticità dello streaming | `standard` |
| Verifica della fatturazione dei token | `billing` | Fatturazione e consumo | `standard` |
| Affidabilità e latenza in concorrenza | `reliability` | Affidabilità in concorrenza | `standard` |
| Segnali di trasporto e gestione dei segreti | `security` | Sicurezza del trasporto | `smoke` |
| Rilevamento di prompt di sistema iniettato | `injected_prompt` | Sicurezza del trasporto | `deep` |
| Integrità delle risposte / manomissione | `integrity` | Sicurezza del trasporto | `deep` |
| Cache del prefisso del prompt (tempi) | `prompt_cache` | Sicurezza del trasporto | `deep` |
| Sonda delle prestazioni | `performance` | Prestazioni | `deep` (in `standard` solo con un riferimento, 5 richieste) |

- **smoke** esegue connettività e sicurezza; **standard** aggiunge i rilevatori
  di protocollo, identità, capacità, streaming, fatturazione e affidabilità;
  **deep** aggiunge le sonde di contesto lungo, determinismo, visione, prompt
  iniettato, integrità, cache del prompt e prestazioni (e il giudice con
  `--judge`); **full** esegue gli stessi rilevatori di deep e misura le
  prestazioni con e senza streaming; **custom** esegue tutti i rilevatori delle
  dimensioni selezionate, con la profondità di deep.
- **Solo codice (predefinita):** tutti i rilevatori tranne `quality_judge`
  decidono con codice deterministico — controlli di testo e di espressioni
  regolari, aritmetica, statistiche sui tempi. Nessun secondo modello
  necessario.
- **Ibrida codice + LLM (`--judge`):** `quality_judge` chiede a un modello
  giudice affidabile, configurato a parte (mai l'obiettivo), se le risposte
  dell'obiettivo somigliano al modello dichiarato. Senza `--judge-base-url`, la
  modalità di confronto usa il riferimento come giudice.
- **Modalità di confronto** (`zing compare`) dà alle sonde un riferimento
  affidabile: `model_identity` registra l'autoidentificazione del riferimento
  accanto a quella dell'obiettivo, `protocol_request` reinvia al riferimento i
  parametri rifiutati, `integrity` porta a CRITICA una sostituzione che il
  riferimento non fa, `quality_judge` mostra entrambi i lati al giudice e
  `performance` sonda i due endpoint a turno. L'affidabilità può essere alta
  solo con un riferimento.
- **Base di conoscenza:** il profilo del modello dichiarato
  (`zing/knowledge/data/*.yaml` più le tue voci in `kb.db`) fornisce la finestra
  di contesto dichiarata, l'output massimo, il tokenizer, le capacità, le parole
  chiave di identità e le impronte comportamentali con cui vengono valutate le
  sonde. Ogni rapporto registra il profilo usato (`knowledge`).
- **Lingua dei prompt:** ogni testo di sonda si trova in `zing/prompts/en.json`
  ed è in inglese, qualunque sia la lingua dell'interfaccia; solo le impronte la
  cui lingua *è* la misura dichiarano `prompt_lang` e `language_bound`. Ogni
  rapporto elenca le lingue delle sonde usate (`prompt_languages`).
- **Modelli di ragionamento:** una sonda breve che termina al proprio limite di
  output con la risposta assente, o troncata dopo che il ragionamento ha usato
  almeno metà del limite (`reasoning_tokens` riportati), viene ripetuta una
  volta con un limite di 4.096 token, così un modello che pensa prima di
  rispondere non viene letto come un errore. Le sonde il cui limite o la cui
  temporizzazione è la misura (prestazioni, cache dei prompt, affidabilità,
  prompt iniettato, output massimo, l'attributo di richiesta `max_tokens`) non
  vengono mai ripetute. Una volta noto che un endpoint ragiona (il suo profilo
  indica `reasoning: true`, o dopo la sua prima ripetizione di questo tipo), le
  sonde brevi partono subito con il limite di 4.096 token invece che due volte.

---

## `connectivity` — Connettività

**Rileva.** Nessun trucco direttamente: è la porta da cui dipendono tutti gli
altri rilevatori. Separa una chiave morta o mal configurata da un relay che vale
la pena verificare.

**Come funziona.** `GET /v1/models` (annota se il modello dichiarato è elencato)
e una chat completion a `temperature=0` che chiede al modello di ripetere un
canary esatto; registra la latenza e il campo `model` restituito.

**Scala dei punteggi** (`zing/detectors/connectivity.py`):

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `connectivity.models` | L'elenco dei modelli (/v1/models) ha risposto. | Superato | 100 pt |
|  | L'elenco dei modelli (/v1/models) non ha risposto; alcuni relay lo disattivano. | Avviso · Bassa | 60 pt |
| `connectivity.chat` | Una chat completion ha restituito contenuto e ripetuto il canary. | Superato | 100 pt |
|  | Una chat completion ha restituito contenuto, ma non ha ripetuto il canary. | Superato | 85 pt |
|  | La chat completion non è riuscita o non ha restituito contenuto. | Fallito · Alta | 0 pt |

**Avvertenze.** L'assenza di `/v1/models` è innocua; molti relay la
disattivano. Un errore di rete temporaneo o un 5xx può far fallire il controllo
della chat: riesegui. La connettività non prova nulla su *quale* modello abbia
risposto. Le sue rilevazioni non alzano mai il verdetto di rischio.

---

## `protocol` — Conformità del protocollo

**Rileva.** Relay il cui middleware rompe il contratto del protocollo (turni
persi, sequenze di stop ignorate, errori malformati, campi di risposta mancanti
o a zero, parametri di richiesta rimossi) e, tramite il determinismo,
`cache.ignore-temperature`. Copre in parte `capability.json-tool-fakery`.

### `protocol` — Conformità alla compatibilità OpenAI

**Come funziona.** Tre sonde: una conversazione a più turni che deve ricordare
un colore da un turno precedente; una sequenza `stop` che deve troncare
l'output; e una richiesta volutamente non valida (`messages` vuoto) che deve
essere rifiutata con un 4xx, idealmente con un corpo d'errore in stile OpenAI.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `protocol.multi_turn` | Il colore di un turno precedente è stato ricordato. | Superato | 100 pt |
|  | Il colore di un turno precedente non è stato ricordato. | Avviso · Media | 55 pt |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Non conteggiato |
| `protocol.stop` | L'output si è fermato alla sequenza di stop. | Superato | 100 pt |
|  | Non è stato possibile confermare la gestione dello stop dal testo. | Avviso · Bassa | 70 pt |
|  | È stato restituito testo dopo la sequenza di stop. | Avviso · Bassa | 60 pt |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Non conteggiato |
| `protocol.error_schema` | Rifiutata con un 4xx e un corpo di errore in stile OpenAI. | Superato | 100 pt |
|  | Rifiutata con un 4xx, ma il corpo non è in stile OpenAI. | Avviso · Bassa | 80 pt |
|  | Nessuna risposta HTTP; non è stato possibile confermare la gestione degli errori client. | Avviso · Bassa | 55 pt |
|  | Un altro stato HTTP; non è stato possibile confermare la gestione degli errori client. | Avviso · Bassa | 55 pt |
|  | La richiesta non valida ha causato un errore del server (5xx). | Fallito · Media | 35 pt |
|  | La richiesta non valida è stata accettata (2xx). | Fallito · Media | 30 pt |

### `protocol_response` — Disponibilità degli attributi di risposta

**Come funziona.** Una normale chiamata senza streaming; ogni attributo del
protocollo dell'obiettivo (OpenAI Chat Completions, Anthropic Messages o OpenAI
Responses; catalogo in `zing/detectors/wire_attrs.py`) viene valutato sul corpo
grezzo. Gli attributi principali sono per esempio `model`,
`choices[0].message.role/content`, `finish_reason`, `usage.prompt_tokens`,
`usage.completion_tokens` e `usage.total_tokens` (che deve essere la somma dei
due); quelli secondari sono `id`, `object`, `created`/`created_at`,
`choices[0].index` e `type`. Uno zero dove un conteggio deve essere positivo
(`completion_tokens: 0` per una risposta non vuota) vale come zero, non come
valido.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `protocol_response.core` (Attributi di risposta principali) | Presente con un valore valido. | Superato | 100 pt |
|  | Presente ma zero o vuoto (ad es. completion_tokens: 0). | Fallito · Media | 20 pt |
|  | Presente con tipo o valore errato (ad es. totale ≠ somma delle parti). | Avviso · Media | 40 pt |
|  | Assente dalla risposta. | Fallito · Media | 0 pt |
| `protocol_response.minor` (Attributi di risposta secondari) | Presente con un valore valido. | Superato | 100 pt |
|  | Presente ma zero o vuoto. | Avviso · Bassa | 50 pt |
|  | Presente con tipo o valore errato. | Avviso · Bassa | 70 pt |
|  | Assente dalla risposta. | Avviso · Bassa | 60 pt |
| `protocol_response.call` (Prova degli attributi di risposta) | La chiamata di prova non ha restituito un corpo di risposta da valutare. | Non conclusivo · Bassa | Non conteggiato |

### `protocol_request` — Supporto degli attributi di richiesta

**Come funziona.** Viene inviato ogni parametro di richiesta del protocollo
(circa cinque chiamate). I parametri con un effetto osservabile hanno una
chiamata propria e devono mostrarlo: `system`/`instructions` seguito, il limite
di output termina con `finish_reason: length`, `n: 2` restituisce due scelte,
`logprobs` viene restituito. I parametri che devono solo essere accettati
(`temperature`, `top_p`, `seed`, penalità, `user`, `top_k`, `metadata`)
condividono una chiamata e vengono ritentati uno per uno solo se questa viene
rifiutata. Un 4xx conta come limite del modello (non conteggiato) anziché come
rifiuto quando la base di conoscenza elenca il parametro in
`unsupported_params`, quando un parametro di campionamento viene inviato a un
modello di ragionamento o quando anche un riferimento con lo stesso protocollo
lo rifiuta. Strumenti e modalità JSON restano a `capability`, `stop` a
`protocol`, l'utilizzo in streaming a `streaming`.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `protocol_request.param` (Parametri di richiesta) | Accettato, e il suo effetto è visibile nella risposta. | Superato | 100 pt |
|  | Accettato (il suo effetto non è osservabile da una sola risposta). | Superato | 100 pt |
|  | Accettato, ma il suo effetto manca nella risposta. | Avviso · Bassa | 50 pt |
|  | Rifiutato con un 4xx (forse un limite del modello stesso). | Avviso · Bassa | 40 pt |
|  | Rifiutato con un 4xx, mentre il riferimento lo accetta. | Fallito · Media | 15 pt |
|  | Rifiutato, ma il modello stesso non lo supporta; non conteggiato. | Info | Non conteggiato |
|  | Errore del server o nessuna risposta; non conteggiato. | Non conclusivo · Bassa | Non conteggiato |

### `determinism` — Determinismo e correttezza della cache

**Come funziona.** Quattro prompt creativi identici a `temperature=1.0` (senza
seed): un modello autentico varia; un output identico byte per byte in tutti i
campioni indica una cache delle risposte che ignora il campionamento. Il
verdetto è soppresso per i modelli di ragionamento, che ignorano legittimamente
la temperatura. Due domande fattuali identiche a `temperature=0` sono solo
informative.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `determinism.temp1_variability` | I campioni ripetuti con temperature=1.0 erano diversi, come in un vero campionamento. | Superato | 100 pt |
|  | I campioni erano identici, ma i modelli di ragionamento ignorano legittimamente temperature. | Info | 100 pt |
|  | Tutti i campioni con temperature=1.0 erano identici byte per byte, il che suggerisce risposte in cache. | Avviso · Media | 55 pt |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Non conteggiato |
| `determinism.temp0_stability` | Risposte identiche con temperature=0 (previsto); solo informativo, non conteggiato. | Info | Non conteggiato |
|  | Le risposte differivano con temperature=0; solo informativo, non conteggiato. | Info | Non conteggiato |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Non conteggiato |

**Avvertenze.** I gateway possono aggiungere campi specifici del fornitore;
vengono segnalati solo campi obbligatori mancanti o non validi. La traduzione
tra i dialetti Anthropic e OpenAI rimodella legittimamente alcune strutture.
Conferma un difetto sospetto ripetendolo e, se possibile, in modalità di
confronto.

---

## `context_window` — Finestra di contesto

**Rileva.** `context.window-truncation` (un relay dichiara 128K/200K/1M ma
tronca il prompt in silenzio) e `context.lost-in-middle-rag` (uno strato
economico di RAG/riassunto inoltra solo parti del prompt).

**Come funziona.** Richiamo di un ago nel pagliaio a `temperature=0`: un
marcatore univoco viene inserito in un testo di riempimento non ripetitivo,
dimensionato con la stima euristica dei token di zing, e il modello deve
restituirlo.

1. Una scala crescente che raddoppia da 2K token fino alla finestra dichiarata,
   limitata da `--max-context-tokens` (200K predefinito), con un gradino vicino
   al 90 % del massimo (al più sette dimensioni). Ogni dimensione viene sondata
   prima con l'ago all'**inizio** (profondità 0,0): un troncamento che conserva
   la domanda in fondo al prompt può scartarne solo l'inizio (un server locale
   che taglia il prompt alla sua lunghezza di contesto ne conserva la fine),
   quindi un richiamo lì supera la dimensione con una sola chiamata. Un
   fallimento viene verificato alla fine (profondità 0,95); se la fine viene
   richiamata, l'inizio viene sondato ancora una volta con un ago nuovo, e un
   secondo fallimento boccia la dimensione come **troncamento in testa**
   (indicato nelle evidenze del verdetto). Al più tre chiamate per dimensione;
   la scala si ferma al primo fallimento confermato.
2. Un passo di ricerca binaria tra l'ultima dimensione richiamata e la prima
   fallita.
3. Perdita nel mezzo: a min(32K, finestra misurata) l'ago viene posto alle
   profondità 0,1, 0,5 e 0,9; inizio e fine richiamati ma non il mezzo è una
   rilevazione.
4. Un 4xx il cui messaggio cita la lunghezza del contesto è un rifiuto per
   dimensione; un rifiuto di `max_tokens` (modelli di ragionamento) viene
   ritentato con `max_completion_tokens` e non viene mai letto come un tetto.
5. Una sonda andata in timeout chiude la scala senza contare come fallimento:
   la finestra oltre l'ultima dimensione ricordata è riportata come non
   verificata (non conclusiva), mai come troncamento.

La finestra misurata viene confrontata con quella dichiarata. Senza finestra
dichiarata la misura viene riportata ma non valutata.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `context_window.window` (Finestra di contesto effettiva) | Il richiamo ha tenuto fino ad almeno il 90% della finestra dichiarata; toglie la quota di finestra non richiamata. | Superato | fino a −10 pt |
|  | Il richiamo ha tenuto fino al 50–90% della finestra dichiarata; toglie la quota di finestra non richiamata. | Avviso · Media | fino a −50 pt |
|  | Il richiamo è fallito sotto metà della finestra dichiarata; toglie la quota di finestra non richiamata. | Fallito · Alta | fino a −100 pt |
|  | Nemmeno la dimensione di sonda più piccola ha richiamato l'ago. | Fallito · Alta | −100 pt |
| `context_window.lost_in_middle` | L'inizio e la fine sono stati richiamati, ma non la parte centrale. | Avviso · Media | −15 pt |
| `context_window.rejected_below_claim` | Un prompt ben al di sotto della finestra dichiarata è stato rifiutato come troppo lungo. | Fallito · Alta | Nessuna detrazione |
| `context_window.measured` | Nessuna finestra dichiarata con cui confrontare: solo misurata, non conteggiata. | Info | Nessuna detrazione |
| `context_window.no_ladder` | Nessuna dimensione di sonda rientrava tra il minimo e il limite. | Non conclusivo · Bassa | Nessuna detrazione |
| `context_window.timed_out` | Una sonda è andata in timeout prima di raggiungere la finestra dichiarata: un endpoint lento, non una prova di troncamento. | Non conclusivo · Bassa | Nessuna detrazione |

**Avvertenze.** Anche i veri modelli a contesto lungo perdono aghi nel mezzo;
per questo solo un fallimento al **bordo** viene letto come troncamento. Il
richiamo vicino al tetto è probabilistico; riesegui prima di trarre
conclusioni. La sonda è limitata da `--max-context-tokens`, quindi una finestra
più grande non viene esercitata del tutto. Confronta con un riferimento
affidabile per separare il comportamento del modello da quello di uno strato
intermedio.

---

## `model_identity` — Identità del modello

**Rileva.** `downgrade.silent-substitution` (un nome premium su un backend più
economico o aperto), oltre ai segnali di `downgrade.reasoning-collapse`,
`downgrade.quantized-distilled` e `downgrade.partial-probabilistic-routing`
quando cambiano il comportamento.

### `model_identity` — Identità del modello e impronta di declassamento

**Come funziona.** Tre segnali indipendenti:

1. **Autoidentificazione** a `temperature=0`, confrontata a parole intere con le
   parole chiave di identità del profilo (il marchio autentico) e con un elenco
   di marchi rivali (`identity_forbidden` del profilo più un elenco integrato).
   Un marchio rivale conta solo se manca quello autentico; «Sono Claude, non
   GPT» è un contrasto innocuo.
   Il marchio autentico sono le `identity_keywords` del profilo più i suoi
   nomi: la chiave del provider, il nome iniziale del nome visualizzato del
   provider, la prima parola dell'id e della famiglia del modello, e gli altri
   nomi di quel produttore nell'elenco integrato (`z.ai` copre anche `zhipu`).
   Un modello che nomina il proprio produttore non è quindi mai un marchio
   rivale, anche quando `identity_keywords` è vuoto. I nomi derivati non
   prevalgono mai su `identity_forbidden`, le parole generiche («ai»,
   «platform», …) non contano mai, e il marchio proprio di una piattaforma non
   conta per il modello di un altro produttore che serve.
   Le parole di marca che sono anche parole comuni (`step`, `command`, `seed`, `spark`, `meta`, `yi`, `grok`) contano
   solo in questa autoidentificazione e solo scritte come nome («Meta»,
   «Command R»; a inizio frase solo con una versione attaccata,
   «Step-2»); nelle risposte delle impronte non contano mai, quindi
   «let me think step by step» non è un marchio concorrente. Un produttore
   a cui appartiene una di queste parole la mantiene come propria.
2. **Impronte comportamentali** dalla base di conoscenza (data limite delle
   conoscenze, particolarità del tokenizer, formattazione, sonde legate a una
   lingua, …): fino a sei sonde di solo codice, verificate con
   `expect_contains`, `expect_contains_any`, `expect_not_contains` o
   `expect_regex`; output limitato a 512 token. Una sonda che
   richiede più output (ad esempio una verifica dell'output massimo) viene
   saltata, indicata come Info, e un'altra sonda ne prende il posto.
   Un'impronta che si discosta
   toglie la sua quota di peso su 100 punti (al più 25); da sola resta BASSA,
   due o più aggiungono una rilevazione aggregata MEDIA.
3. **Campo `model` restituito** da una chiamata semplice: suffissi di snapshot e
   alias sono tollerati; una parola di fascia inferiore (`mini`, `flash`,
   `lite`, `8b`, …) o una famiglia diversa viene segnalata.

Senza profilo nella base di conoscenza il rilevatore è non conclusivo.
È inoltre non conclusivo e senza punteggio (`model_identity.no_evidence`)
quando né l'autoidentificazione né alcuna impronta hanno dato una risposta
utilizzabile e il campo `model` restituito non diverge: un relay che
rifiuta o svuota ogni richiesta non fornisce prove d'identità, e l'eco del
nome richiesto da solo non prova nulla. Prove parziali vengono valutate
normalmente.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `model_identity.self_id` | L'autodescrizione ha nominato il marchio autentico. | Superato | Nessuna detrazione |
|  | L'autodescrizione ha nominato un marchio concorrente e non quello autentico. | Fallito · Alta | tetto 20 |
|  | L'autodescrizione ha nominato il marchio autentico e un concorrente (di solito un confronto innocuo). | Avviso · Bassa | Nessuna detrazione |
|  | L'autodescrizione non ha nominato né il marchio autentico né un concorrente. | Avviso · Bassa | Nessuna detrazione |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo | Nessuna detrazione |
| `model_identity.fp` (Impronte comportamentali) | La risposta corrispondeva al comportamento nativo del modello dichiarato. | Superato | Nessuna detrazione |
|  | La risposta si è discostata dal comportamento nativo: toglie la quota di peso della sonda su 100 punti. | Avviso · Bassa | fino a −25 pt |
|  | La risposta ha nominato un marchio concorrente e non quello autentico: toglie la quota di peso della sonda. | Fallito · Alta | fino a −25 pt · tetto 20 |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo | Nessuna detrazione |
|  | La sonda richiede più output del limite di identità di 512 token; non eseguita. | Info | Nessuna detrazione |
| `model_identity.fp_aggregate` | Due o più impronte comportamentali si sono discostate. | Avviso · Media | Nessuna detrazione |
| `model_identity.model_field` | Il campo model restituito corrispondeva al modello richiesto. | Superato | Nessuna detrazione |
|  | Il campo model restituito indica un modello diverso o più piccolo. | Avviso · Media | Nessuna detrazione |
|  | La risposta non aveva un campo model utilizzabile. | Non conclusivo | Nessuna detrazione |
| `model_identity.no_evidence` | Né l'autoidentificazione né alcuna impronta hanno dato una risposta utilizzabile e il campo model non divergeva: non valutato. | Non conclusivo | Nessuna detrazione |

### `quality_judge` — Valutazione di qualità / declassamento da parte di un LLM giudice

**Come funziona.** Solo con `--judge` (da deep in su). Una breve serie di prompt
che distinguono le fasce (ragionamento in più passaggi, un compito di codice
preciso, istruzioni con sfumature) va all'obiettivo e, in modalità di confronto,
al riferimento; un giudice affidabile separato vede solo le risposte e
restituisce un verdetto con la sua affidabilità. Un verdetto del giudice è ALTO
solo se un riferimento ha confermato la differenza e il giudice non ha indicato
un'affidabilità bassa o media.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `quality_judge.verdict` (Verdetto del giudice LLM) | Il giudice ha trovato le risposte coerenti con il modello dichiarato. | Superato | 95 pt |
|  | Il giudice ha trovato le risposte diverse dal modello dichiarato (confidenza bassa/media). | Avviso · Media | 50 pt |
|  | Il giudice è sicuro che le risposte differiscono dal modello dichiarato (nessuna baseline). | Avviso · Media | 25 pt |
|  | Il giudice è sicuro e una baseline affidabile ha confermato la differenza. | Fallito · Alta | 25 pt |
|  | Il giudice non ha indicato una confidenza e una baseline affidabile ha confermato la differenza. | Fallito · Alta | 50 pt |
|  | Il giudice non è riuscito a esprimere un verdetto. | Non conclusivo · Bassa | Non conteggiato |
|  | Nessuna risposta del target da giudicare. | Non conclusivo · Bassa | Non conteggiato |

**Avvertenze.** Le API ufficiali aggiornano gli snapshot in silenzio, quindi uno
scostamento può essere una deriva innocua — zing riporta «divergente», mai
«sostituzione provata». I modelli allucinano il proprio nome, quindi
l'autoidentificazione da sola non decide mai. Un relay potrebbe memorizzare una
serie fissa di sonde. Un verdetto ad alta affidabilità richiede la modalità di
confronto con lo snapshot esatto dichiarato.

**Non implementato.** L'impronta tramite distanza di embedding (stile LLMmap), i
test statistici a due campioni e il campionamento su larga scala contro
l'instradamento probabilistico sono filoni di ricerca, non controlli attuali.

---

## `capability` — Capacità dichiarate

**Rileva.** `capability.json-tool-fakery`: chiamate a strumenti, modalità JSON,
schemi rigorosi, lunghezza dell'output o visione dichiarati ma non forniti — o
forniti *in eccesso*, indizio di un sostituto.

### `capability` — Verifica delle capacità dichiarate

**Come funziona.** Quattro sonde a `temperature=0`, ciascuna valutata rispetto
alle capacità del profilo:

- **Strumenti:** viene offerto uno strumento con `tool_choice: "auto"` e una
  richiesta esplicita di usarlo; deve tornare una chiamata a strumento.
  Argomenti consegnati come oggetto invece che come la stringa JSON restituita da
  OpenAI vengono segnalati come motore non OpenAI.
- **Modalità JSON:** `response_format: json_object` deve restituire un oggetto
  analizzabile con il valore richiesto.
- **Schema rigoroso:** un `json_schema` rigoroso; la conformità viene verificata
  se il modello la dichiara e solo annotata (informativa) se no. Saltato senza
  profilo.
- **Output massimo:** una generazione lunga limitata a min(output massimo
  dichiarato, 2048) token; raggiungere il limite o una lunghezza plausibile è
  superato, fermarsi sotto un quarto viene segnalato.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `capability.tools` | È tornata una chiamata a strumento per una richiesta esplicita di strumento. | Superato | 100 pt |
|  | Le chiamate a strumenti sono dichiarate ma non è tornata alcuna chiamata. | Fallito · Media | 0 pt |
|  | Non è tornata alcuna chiamata a strumento, e la capacità non è dichiarata. | Info | Non conteggiato |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Non conteggiato |
| `capability.tools.encoding` | Gli argomenti dello strumento sono arrivati come oggetto, non come la stringa JSON di OpenAI. | Avviso · Bassa | Non conteggiato |
| `capability.json_mode` | La modalità JSON ha restituito un oggetto analizzabile con il valore richiesto. | Superato | 100 pt |
|  | È tornato un oggetto JSON con il valore sbagliato; la modalità JSON non è dichiarata. | Info | 70 pt |
|  | Non è tornato alcun oggetto JSON analizzabile; la modalità JSON non è dichiarata. | Avviso | 50 pt |
|  | La modalità JSON è dichiarata ma non è tornato un oggetto valido con il valore. | Fallito · Media | 0 pt |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Non conteggiato |
| `capability.json_schema` | Lo schema rigoroso è dichiarato e la risposta lo rispettava. | Superato | 100 pt |
|  | Lo schema rigoroso non è stato applicato, in linea con quanto dichiarato. | Info | 100 pt |
|  | La risposta lo rispettava anche se il modello dichiarato non ha schemi rigorosi. | Info | 90 pt |
|  | Lo schema rigoroso è dichiarato ma la risposta non lo rispettava. | Avviso · Bassa | 40 pt |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Non conteggiato |
| `capability.max_output` | L'output è proseguito fino al limite di token richiesto. | Superato | 100 pt |
|  | L'output si è fermato prima del limite con una lunghezza plausibile. | Superato | 90 pt |
|  | L'output si è fermato sotto un quarto della lunghezza richiesta. | Avviso · Bassa | 70 pt |
|  | L'output si è fermato sotto un quarto della richiesta nonostante un massimo dichiarato elevato. | Avviso · Bassa | 60 pt |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Non conteggiato |

### `vision` — Verifica della capacità multimodale (visione)

**Come funziona.** Da deep in su e solo se il profilo dichiara la visione: un
piccolo PNG arancione a tinta unita, generato in esecuzione, viene inviato inline
con una domanda di una parola sul suo colore. Un sostituto solo testuale non può
nominare il colore in modo affidabile.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `vision.color` | Il modello ha nominato il colore dell'immagine di prova. | Superato | 100 pt |
|  | La visione è dichiarata ma il modello non ha nominato il colore dell'immagine. | Avviso · Media | 0 pt |
|  | Nessuna risposta utilizzabile per valutare. | Non conclusivo | Non conteggiato |
| `vision.not_claimed` | La visione non è dichiarata, quindi non è stata inviata alcuna immagine. | Info | Non conteggiato |

**Avvertenze.** Anche i modelli autentici a volte saltano uno strumento o
emettono JSON non valido; una sonda per capacità è un segnale, non un tasso. La
traduzione tra dialetti rimodella legittimamente il JSON delle chiamate a
strumenti. La sonda dell'output massimo non esercita tutto il tetto dichiarato.
Una sola immagine è un indizio, non una prova.

---

## `streaming` — Autenticità dello streaming

**Rileva.** `stream.fake-streaming`: il relay bufferizza tutta la risposta
dell'upstream e la riproduce in uno o pochi frammenti, perdendo il vantaggio di
latenza.

**Come funziona.** Una richiesta in streaming (`max_tokens` 256,
`stream_options.include_usage`) di cui si registra l'orario di arrivo di ogni
frammento. Tre segnali di buffering: **pochi frammenti** (due o meno) e **primo
token tardivo** (TTFT oltre il 90 % della durata totale), valutati solo quando
sono arrivati almeno 220 caratteri, e **intervalli uniformi** (quattro o più
frammenti con intervalli quasi uguali, CV < 0,1, e sotto i 2 ms: scaricati in
blocco). Un flusso senza frammento di utilizzo viene segnalato a parte.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `streaming.healthy` | Molti chunk, un primo token precoce e intervalli distribuiti: vero streaming. | Superato | Nessuna detrazione |
| `streaming.few_chunks` | Segnale di buffering: il primo toglie 40 punti, un secondo 20, i successivi nulla. | Avviso · Media | fino a −40 pt |
| `streaming.late_ttft` | Segnale di buffering: il primo toglie 40 punti, un secondo 20, i successivi nulla. | Avviso · Media | fino a −40 pt |
| `streaming.uniform_gaps` | Segnale di buffering: il primo toglie 40 punti, un secondo 20, i successivi nulla. | Avviso · Media | fino a −40 pt |
| `streaming.no_usage` | Nessun chunk di utilizzo nello stream: toglie 15 punti se nulla è in buffer. | Avviso · Bassa | fino a −15 pt |
| `streaming.failed` | La richiesta in streaming non è riuscita. | Fallito · Alta | tetto 0 |

Cioè: autentico 100 · utilizzo mancante 85 · un segnale di buffering 60 · due o
più 40 · fallito 0.

**Avvertenze.** Output brevi, un modello piccolo e veloce o il jitter di rete
possono sembrare una raffica. Un upstream che non supporta lo streaming
costringe il relay a bufferizzare in modo legittimo; leggilo come «il relay non
fa streaming», non come malafede. Riesegui e confronta con un riferimento che
fa davvero streaming.

---

## `billing` — Fatturazione e consumo

**Rileva.** `billing.usage-inflation` (token di prompt o di completion
gonfiati), `billing.missing-usage` (`usage` mancante, parziale o incoerente) e,
come segnale di conferma, `prompt.injected-system-prompt`.

**Come funziona.** Una chiamata deterministica (un paragrafo noto da
riassumere, `temperature=0`). Il prompt e la risposta visibile vengono contati
in modo indipendente con un'euristica sensibile alla lingua (circa ±25 %), per
ogni famiglia di modelli: zing non usa alcuna libreria di tokenizer e non ne
scarica. Token di prompt riportati oltre 2,5× la stima e più di 50 token sopra
contano come gonfiamento. I token di completion di un modello di ragionamento
includono legittimamente token di ragionamento nascosti e non vengono
segnalati; altrimenti token di completion oltre 3× la stima e più di 80 token
sopra sono un avviso lieve, mai un fallimento, perché la stima di una risposta
breve è imprecisa. `total` deve essere `prompt + completion` (±2), e un totale
senza ripartizione viene segnalato. Un conteggio inferiore (sotto la metà della
stima) è informativo (non danneggia l'acquirente).

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `billing.request-failed` | Nessuna risposta utilizzabile per valutare. | Non conclusivo · Bassa | Nessuna detrazione |
| `billing.missing-usage` | La risposta non riportava alcun utilizzo di token. | Avviso · Media | tetto 75 |
| `billing.usage-inflation` | I token di prompt dichiarati superano di molto la stima indipendente. | Fallito · Alta | tetto 55 |
| `billing.usage-inflation-completion` | I token di completion dichiarati sono molto sopra una stima euristica. | Avviso · Media | tetto 70 |
| `billing.reasoning-tokens` | I token di completion superano il testo visibile, come previsto per un modello di ragionamento. | Info | Nessuna detrazione |
| `billing.usage-undercount-prompt` | I token di prompt dichiarati sono molto sotto la stima (non danneggia l'acquirente). | Info | Nessuna detrazione |
| `billing.usage-undercount-completion` | I token di completion dichiarati sono molto sotto la stima (non danneggia l'acquirente). | Info | Nessuna detrazione |
| `billing.total-mismatch` | Il totale dichiarato non è uguale ai token di prompt + completion. | Avviso · Bassa | tetto 90 |
| `billing.partial-usage` | L'utilizzo riporta un totale senza la suddivisione prompt/completion. | Avviso · Media | tetto 80 |
| `billing.usage-consistent` | L'utilizzo dichiarato rientra nella tolleranza della stima indipendente. | Superato | Nessuna detrazione |

Una richiesta di sonda fallita lascia il rilevatore senza punteggio.

**Avvertenze.** I template di chat e i token speciali aggiungono un piccolo
scarto fisso; non ci si aspetta una corrispondenza esatta. Se il modello servito
differisce da quello dichiarato, il tokenizer «giusto» è sconosciuto. I token di
ragionamento nascosti non si possono contare dall'esterno. Una sonda misura una
dimensione; un moltiplicatore che cresce con la dimensione richiede esecuzioni
ripetute o la modalità di confronto.

---

## `reliability` — Affidabilità in concorrenza

**Rileva.** Parte di `throttle.rate-limit-quality`: un relay che fallisce o
arranca con un parallelismo modesto.

**Come funziona.** Una raffica di piccole richieste identiche
(`--reliability-requests`, 8 predefinite) a concorrenza limitata
(`--concurrency`, 3 predefinita). Il tasso di successo è calcolato sulle
richieste effettivamente tentate: un HTTP 429 è una limitazione onesta e viene
conteggiato a parte. Il punteggio toglie la quota fallita; una latenza p95
oltre i 30 s mantiene l'85 % del resto.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `reliability.success_rate` | Tutte le richieste tentate nella raffica sono riuscite. | Superato | Nessuna detrazione |
|  | Fino al 10% delle richieste tentate è fallito; toglie la quota fallita. | Avviso · Bassa | fino a −10 pt |
|  | Oltre il 10% delle richieste tentate è fallito; toglie la quota fallita. | Fallito · Media | fino a −100 pt |
|  | Tutte le richieste sono state limitate (HTTP 429): non conteggiato. | Non conclusivo · Bassa | Nessuna detrazione |
| `reliability.latency` | Latenza p95 oltre 30 s sotto carico; toglie il 15% del punteggio rimanente. | Avviso · Bassa | fino a −15 pt |
| `reliability.rate_limited` | Parte della raffica è stata limitata: limitazione legittima, non conteggiata. | Info | Nessuna detrazione |
| `reliability.skipped` | La sonda di affidabilità era disattivata. | Info | Nessuna detrazione |

Le misure di velocità dedicate appartengono alla dimensione `performance`.

**Avvertenze.** Anche i fornitori autentici rallentano e restituiscono 429 sotto
carico reale. Un'istantanea non coglie il comportamento legato all'orario;
`zing watch` ripete l'audit secondo una pianificazione.

**Non implementato.** La misura della qualità nel tempo e sotto carico
variabile, e i segnali di chiave upstream condivisa
(`infra.shared-upstream-key`: quota che cala a riposo, ID di richiesta upstream
trapelati) sono nella roadmap.

---

## `security` — Sicurezza del trasporto

**Rileva.** `prompt.injected-system-prompt`, `integrity.response-tampering`,
indizi di `privacy.prompt-logging-leakage` (cache per prefisso) e l'igiene di
base di trasporto e segreti.

### `security` — Segnali di trasporto e gestione dei segreti

**Come funziona.** Verifica che l'endpoint usi HTTPS, che la chiave API non
compaia mai letteralmente in una risposta e quali intestazioni di risposta
rivelino un upstream o un proxy (`server`, `via`, `x-powered-by`,
`x-upstream-*`, `x-litellm-*`, …; informativo). Ricorda anche il limite: il
logging dei prompt e le chiavi upstream condivise non sono dimostrabili
dall'esterno.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `security.tls` | L'endpoint usa HTTPS. | Superato | Nessuna detrazione |
|  | L'endpoint non usa HTTPS; la chiave API viaggia in chiaro. | Fallito · Alta | tetto 40 |
| `security.key_echo` | La chiave API non compare nella risposta. | Superato | Nessuna detrazione |
|  | La chiave API compare alla lettera nella risposta. | Fallito · Alta | tetto 30 |
| `security.headers` | Nessun header di risposta rivela l'upstream (solo informativo). | Superato | Nessuna detrazione |
|  | Gli header di risposta rivelano l'upstream o il proxy (solo informativo). | Info · Bassa | Nessuna detrazione |
|  | Nessun header di risposta da ispezionare. | Non conclusivo | Nessuna detrazione |
| `security.note` | Il logging dei prompt e le chiavi upstream condivise non sono dimostrabili dall'esterno. | Info | Nessuna detrazione |

### `injected_prompt` — Rilevamento di prompt di sistema iniettato

**Come funziona.** Due indizi indipendenti. (1) Un **overhead fisso di token in
input**: due messaggi utente di dimensioni diverse senza messaggio di sistema; i
`prompt_tokens` riportati meno la stima indipendente devono restare piccoli. Un
overhead di almeno 30 token che resta costante (entro 16) in entrambe le
dimensioni indica un prompt nascosto anteposto e non un gonfiamento
proporzionale. (2) Una **sonda di fuga** che chiede al modello di ripetere ogni
istruzione precedente. Solo entrambi insieme arrivano a MEDIA.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `injected_prompt.verdict` (Prompt di sistema iniettato) | Il sovraccarico di token in ingresso è piccolo e non sono trapelate istruzioni nascoste. | Superato | 100 pt |
|  | Su richiesta è trapelato un testo simile a istruzioni (debole da solo). | Info · Bassa | 85 pt |
|  | Un grande sovraccarico fisso di token in ingresso, costante al variare del messaggio. | Avviso · Bassa | 75 pt |
|  | Un sovraccarico fisso di token in ingresso e un preambolo trapelato, insieme. | Avviso · Media | 55 pt |
|  | Nessun conteggio utilizzabile di token di prompt per misurare il sovraccarico. | Non conclusivo | Non conteggiato |

### `integrity` — Integrità delle risposte / manomissione

**Come funziona.** Canary a risposta nota con valori sensibili — un URL di
installazione e un pacchetto `pip install` fissato — devono tornare
letteralmente. Un'eco esatta è superata, la mancanza di eco (parafrasi, rifiuto)
è non conclusiva, e solo una **sostituzione del valore** che preserva la
struttura conta come manomissione. In modalità di confronto, una sostituzione
che il riferimento affidabile non fa è CRITICA.
Una risposta troncata al limite di output è non conclusiva, non una sostituzione.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `integrity.verdict` (Integrità delle risposte) | I canary a risposta nota sono tornati intatti. | Superato | 100 pt |
|  | Un valore canary è stato sostituito (non ancora confermato da una baseline). | Fallito · Media | 45 pt |
|  | Un valore canary è stato sostituito mentre la baseline affidabile lo ha mantenuto intatto. | Fallito · Critica | 10 pt |
|  | Nessun canary è stato ripetuto alla lettera, quindi la manomissione non è valutabile. | Non conclusivo | Non conteggiato |

### `prompt_cache` — Cache del prefisso del prompt (tempi)

**Come funziona.** Un prefisso univoco di circa 1.200 token viene inviato due
volte in streaming (a freddo, poi a caldo) e un prefisso di controllo diverso
una volta. Se il TTFT a caldo è sotto la metà del TTFT a freddo e di quello di
controllo, e almeno 150 ms più veloce che a freddo, la cache per prefisso è
attiva. Sempre informativo: la cache per prefisso è un'ottimizzazione legittima.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `prompt_cache.verdict` (Cache per prefisso di prompt) | Un prefisso di prompt ripetuto è tornato molto più velocemente: la cache per prefisso è attiva. | Info | Non conteggiato |
|  | Un prefisso di prompt ripetuto non è stato nettamente più veloce. | Info | Non conteggiato |
|  | Una o più sonde di temporizzazione non hanno restituito un tempo utilizzabile. | Non conclusivo | Non conteggiato |

**Avvertenze.** I modelli inventano falsi «prompt di sistema» quando si chiede
loro di rivelarli; una fuga da sola resta BASSA. La traduzione tra dialetti
rimodella il JSON delle chiamate a strumenti; conta solo una sostituzione del
*valore*. Una manomissione condizionale (solo per certe parole chiave, certi
client o dopo un riscaldamento) può sfuggire a un numero finito di sonde. Il
logging black-box è **indimostrabile** dal client, e zing non può mostrare una
cache condivisa *tra utenti* con una sola chiave: l'assenza di un segnale
temporale non prova che i prompt non vengano registrati.

---

## `performance` — Prestazioni

**Cosa misura.** Quanto è **costante** l'endpoint, non quanto è veloce. Un
modello locale o self-hosted lento ma costante ottiene un buon punteggio; la
velocità pura conta solo rispetto a un riferimento.

**Come funziona.** La sonda dedicata viene eseguita in deep, full e custom, e in
standard solo in modalità di confronto (5 richieste per lato, troppo poche per i
controlli di costanza). Per endpoint: tre ping `GET /models`, una richiesta di
riscaldamento (riportata come avvio a freddo), `--performance-requests`
richieste uniformi (100 predefinite) di `--performance-max-tokens` token di
output (128 predefiniti), poi in deep/full una raffica a `--concurrency`. Ogni
richiesta è non memorizzabile in cache: un ID di richiesta casuale apre il
prompt, gli argomenti ruotano e non vengono inviati parametri di cache né di
ragionamento; una risposta che arriva comunque da una cache viene segnalata ed
esclusa dalle statistiche. La sonda usa lo streaming per impostazione
predefinita (`--performance-non-streaming` per i relay che non lo supportano);
full misura entrambe le modalità, alternate. In modalità di confronto obiettivo
e riferimento si alternano, così la deriva della rete colpisce entrambi allo
stesso modo.
I token di input in cache contano solo se coprono almeno metà del prompt: i
server locali (Ollama, llama.cpp, LM Studio) riusano il template di chat in
cache di ogni prompt, che non è una risposta memorizzata.
Ogni chiamata della verifica viene conservata come record di richiesta
(`performance.requests`, solo numeri, mai testo del prompt o della risposta);
il suo `start_ms` conta dallo `started_at` del rapporto (UTC), così l'ora di
ogni chiamata si può ricostruire.

La costanza usa rapporti di coda (p90 ÷ p50 per latenza e TTFT, p50 ÷ p10 per il
throughput), che una richiesta anomala non sposta come sposta una deviazione
standard; servono almeno 10 campioni puliti. Il riferimento è il riferimento
affidabile, altrimenti l'intervallo `performance.decode_tps` del profilo nella
base di conoscenza.

| Controllo | Esito | Stato | Effetto |
|---|---|---|---|
| `performance.summary` | Latenza, TTFT e throughput sono stati misurati. | Info | Non conteggiato |
|  | Nessuna delle richieste di sonda è riuscita. | Non conclusivo | Non conteggiato |
| `performance.latency_consistency` | La latenza è costante (rapporto di coda al massimo 1,3). | Superato | 100 pt |
|  | La latenza è stabile (rapporto di coda al massimo 1,75). | Superato | 85 pt |
|  | La latenza varia sensibilmente (rapporto di coda al massimo 2,5). | Avviso · Bassa | 65 pt |
|  | La latenza è irregolare (rapporto di coda oltre 2,5). | Fallito · Bassa | 40 pt |
|  | Troppi pochi campioni per giudicare la costanza della latenza. | Info | Non conteggiato |
| `performance.ttft_consistency` | Il tempo al primo token è costante (rapporto di coda al massimo 1,3). | Superato | 100 pt |
|  | Il tempo al primo token è stabile (rapporto di coda al massimo 1,75). | Superato | 85 pt |
|  | Il tempo al primo token varia sensibilmente (rapporto di coda al massimo 2,5). | Avviso · Bassa | 65 pt |
|  | Il tempo al primo token è irregolare (rapporto di coda oltre 2,5). | Fallito · Bassa | 40 pt |
|  | Troppi pochi campioni per giudicare la costanza del tempo al primo token. | Info | Non conteggiato |
| `performance.throughput_consistency` | Il throughput è costante (rapporto di coda al massimo 1,3). | Superato | 100 pt |
|  | Il throughput è stabile (rapporto di coda al massimo 1,75). | Superato | 85 pt |
|  | Il throughput varia sensibilmente (rapporto di coda al massimo 2,5). | Avviso · Bassa | 65 pt |
|  | Il throughput è irregolare (rapporto di coda oltre 2,5). | Fallito · Bassa | 40 pt |
|  | Troppi pochi campioni per giudicare la costanza del throughput. | Info | Non conteggiato |
| `performance.errors` | Al massimo il 2% delle richieste della sonda è fallito. | Superato | 100 pt |
|  | Fino al 10% delle richieste della sonda è fallito o scaduto. | Avviso · Bassa | 80 pt |
|  | Molte richieste della sonda sono fallite o scadute. | Fallito · Bassa | 50 pt |
| `performance.load_stability` | La latenza regge sotto carico concorrente (al massimo 1,5x). | Superato | 100 pt |
|  | La latenza aumenta sotto carico concorrente (fino a 3x). | Avviso · Bassa | 80 pt |
|  | La latenza peggiora nettamente sotto carico concorrente (oltre 3x). | Fallito · Bassa | 55 pt |
| `performance.cache_hit` | Prompt di sonda unici sono tornati da una cache (esclusi dalle statistiche). | Avviso · Bassa | 60 pt |
|  | Il riferimento ha servito prompt unici da una cache (non valutato). | Info | Non conteggiato |
| `performance.reference` | Il throughput è in linea con il riferimento per questo modello. | Superato | 100 pt |
|  | Più lento del riferimento (ad es. locale o hardware più piccolo); non è un fallimento. | Info | 80 pt |
|  | Molto più veloce del riferimento (compatibile con un modello più piccolo). | Avviso · Bassa | 60 pt |
| `performance.reasoning` | Il modello spende token di ragionamento nascosti; il TTFT include il ragionamento. | Info | Non conteggiato |
| `performance.relay_overhead` | Latenza confrontata con la baseline affidabile (solo informativo). | Info | Non conteggiato |
| `performance.skipped` | La sonda delle prestazioni era disattivata. | Info | Non conteggiato |

**Avvertenze.** La latenza dipende dal percorso di rete e dal carico del
fornitore in quel momento; ripeti un cattivo risultato di costanza in un altro
momento. Gli intervalli della base di conoscenza sono mediane volutamente ampie
delle API native, e un obiettivo più lento non è mai un fallimento. Tutte le
rilevazioni sono al massimo di gravità BASSA: questa dimensione muove il
punteggio, mai il verdetto di rischio.

---

## Corrispondenza trucco → rilevatore

I 16 trucchi dei relay individuati dalla ricerca si distribuiscono così in zing.

| # | Trucco (id) | Gravità | Rilevatore/i | Copertura attuale |
|---|---|---|---|---|
| 1 | `downgrade.silent-substitution` | critical | `model_identity`, `quality_judge` | autoidentificazione, impronte, campo `model`; giudice; modalità di confronto |
| 2 | `downgrade.reasoning-collapse` | critical | `model_identity`, `quality_judge` | solo impronte e giudice; ancora nessuna scala di difficoltà dedicata |
| 3 | `downgrade.quantized-distilled` | high | `quality_judge`, `model_identity` | giudice con riferimento; ancora nessun test di distribuzione |
| 4 | `downgrade.partial-probabilistic-routing` | high | `model_identity` | solo se le richieste campionate colpiscono il sostituto; il campionamento su larga scala è nella roadmap |
| 5 | `context.window-truncation` | high | `context_window` | scala con ago al bordo + ricerca binaria; misurata vs dichiarata |
| 6 | `context.lost-in-middle-rag` | high | `context_window` | profondità 0,1/0,5/0,9 a una dimensione media |
| 7 | `stream.fake-streaming` | medium | `streaming` | numero di frammenti, momento del primo token, uniformità degli intervalli |
| 8 | `billing.usage-inflation` | high | `billing` | stima euristica indipendente dei token di una sonda nota |
| 9 | `billing.missing-usage` | medium | `billing`, `protocol_response`, `streaming` | presenza, ripartizione e aritmetica dell'utilizzo; frammento di utilizzo del flusso |
| 10 | `privacy.prompt-logging-leakage` | high | `prompt_cache` | cache per prefisso tramite TTFT (informativo); condivisione tra utenti e logging restano indimostrabili con una chiave |
| 11 | `infra.shared-upstream-key` | high | — | roadmap (quota che cala a riposo, ID di richiesta upstream trapelati) |
| 12 | `cache.ignore-temperature` | medium | `determinism` | output identico byte per byte a temperatura 1,0; soppresso per i modelli di ragionamento |
| 13 | `prompt.injected-system-prompt` | medium | `injected_prompt`, `billing` | overhead fisso di token in input (due dimensioni) + sonda di fuga |
| 14 | `throttle.rate-limit-quality` | medium | `reliability`, `performance` | tasso di successo (429 a parte), latenza di coda, stabilità sotto carico; la misura nel tempo è nella roadmap |
| 15 | `capability.json-tool-fakery` | medium | `capability`, `protocol_request` | strumenti, modalità JSON, schema rigoroso, parametri; una sonda ciascuno, non tassi |
| 16 | `integrity.response-tampering` | critical | `integrity` | canary di URL/pacchetto a risposta nota; CRITICA quando un riferimento lo conferma |

---

## Limiti e uso responsabile

**zing riporta scostamenti e rischi, non prove di frode.** Il verdetto usa un
linguaggio prudente (clean / low / medium / high / inconclusive), lascia non
conclusivi i risultati ambigui e sale ad «alto» solo con prove solide di gravità
alta.

**Ciò che un audit black-box non può dimostrare:**

- **Logging dei prompt o conservazione dei dati.** Un segnale temporale prova
  una cache; la sua assenza non prova che i prompt non vengano registrati.
- **Integrità delle risposte** senza risposte firmate dal fornitore: una
  manomissione condizionale può sfuggire a un numero finito di sonde.
- **Chiavi condivise o rubate:** al più un *rischio* di pool condiviso.
- **Deriva innocua o sostituzione:** le API ufficiali aggiornano gli snapshot in
  silenzio.
- **Instradamento costante:** un relay può instradare in modo probabilistico, e
  un audit vede solo le richieste che ha inviato.

**Metodo.** Le rilevazioni che dipendono da un confronto esatto usano
`temperature=0` e prompt vincolati. Ogni rilevazione porta le proprie prove
(input, valori osservati, conteggi, tempi) e ogni rapporto registra il profilo,
le lingue dei prompt e le impostazioni con cui è stato eseguito, così che un
risultato si possa verificare in modo indipendente. Un relay può accorgersi dei
test: riesegui in altri momenti e preferisci la modalità di confronto con un
riferimento affidabile dello **snapshot esatto dichiarato** — è il modo più
solido per separare il comportamento del modello da quello del relay, e l'unico
per arrivare ad alta affidabilità.

**Divulgazione responsabile.** **Non accusare pubblicamente un fornitore** sulla
base di un rapporto di zing. Prima di agire: riesegui con più campioni e in
altri momenti, conferma con la modalità di confronto ed escludi spiegazioni di
deriva, rete e carico. Se resta un dubbio serio, parlane prima in privato con il
fornitore, sotto forma di domande sul comportamento osservato e non di accuse.
