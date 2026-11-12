# Interfaccia web (`ekte serve`)

> [🇬🇧 English](../../../guide/web-ui.md) · [🇨🇳 中文](../../zh-CN/guide/web-ui.md) · [🇫🇷 Français](../../fr/guide/web-ui.md) · [🇪🇸 Español](../../es/guide/web-ui.md) · [🇵🇹 Português](../../pt/guide/web-ui.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/web-ui.md) · [🇳🇴 Norsk](../../nb/guide/web-ui.md)

Preferisci cliccare? Un'interfaccia web locale avvolge lo stesso motore — senza
riga di comando.

```bash
pip install 'ekte[web]'     # oppure: uv tool install 'ekte[web]'
ekte serve                        # apre http://localhost:8000
```

Il modulo guida la configurazione:

1. Scegli il **Relay / provider**: un fornitore della base di conoscenza o un
   relay che hai salvato. Il suo URL di base viene compilato (gli altri URL noti
   del fornitore sono offerti come suggerimenti). Per qualsiasi altro relay
   scegli **Altro (inserisci l'URL)** e inserisci l'**URL dell'intermediario**.
2. Aggiungi la **Chiave API** se il relay ne richiede una.
3. ekte elenca da solo i modelli del relay (alla scelta di un relay e ogni volta
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
affidabile (**Confronta con un riferimento affidabile**) e le verifiche di
embedding e rerank si configurano allo stesso modo.

Poi **Avvia
verifica** e segui i controlli **in tempo reale**: ogni controllo mostra il suo
punteggio e quanto è durato, e un controllo con rilevazioni si espande per
mostrare le prove. Il risultato è un rapporto con il verdetto da condividere:
voto, **Controlli per dimensione** con le loro scale dei punteggi, rilevazioni in
linguaggio chiaro, la sezione prestazioni e un **Registro di esecuzione** di ogni
rilevatore.

Tutto gira sulla tua macchina: una chiave digitata nel browser raggiunge solo il
tuo server ekte locale e il relay che verifichi, mai terze parti. Vedi
[Privacy e dati locali](privacy.md#privacy-e-dati-locali).

## Pagine

L'interfaccia web è servita alla radice dell'indirizzo che `ekte serve` apre, con la pagina di verifica in `/`. Gli indirizzi precedenti rimandano alla pagina corrispondente fino alla 1.0.0 (vedi [Indirizzi dell'interfaccia web](../../../reference/stability.md#surface-web-addresses)).

| Pagina | Indirizzo | A cosa serve |
|---|---|---|
| **Verifica** | `/` | Verificare un relay (eventualmente rispetto a un riferimento) e leggere il rapporto; anche le verifiche di embedding e rerank partono da qui, con il selettore del tipo di endpoint |
| **Monitor** | `/watches` | Verifiche ripetute pianificate con avvisi via webhook |
| **Cronologia** | `/history` | Ogni verifica eseguita su questa macchina, raggruppata per relay + modello dichiarato, con tendenze |
| **Analisi** | `/analytics` | Relay e modelli confrontati nel tempo: indicatori, grafici con tabelle di dati, classifiche |
| **Conoscenza** | `/kb` | La base di conoscenza in tre schede — modelli, fornitori, relay: sfogliare, attivare/disattivare, aggiungere i propri |
| **Accessibilità** | `/accessibility` | Il rapporto di conformità e la dichiarazione di accessibilità (l'icona accanto al selettore della lingua); ancora senza revisione manuale da una persona (limitazione nota) |

Inoltre, nelle pagine: filtri e tendenze configurabili (punteggio, voto,
latenza p50, velocità di decodifica p50) nella **Cronologia**; **Pianifica come monitor** e **Riesegui audit** su ogni
esecuzione della Cronologia; **Scarica il rapporto** in tutti i formati; e un
selettore del tema (Automatico / Chiaro / Scuro).
Ogni pagina tranne Accessibilità ha un avviso subito sotto l'introduzione,
colorato secondo l'importanza (informazione, successo, avviso, critico): ad es.
l'ultimo audit concluso in **Verifica**, la chiave principale in **Monitor**, le
esecuzioni ancora in elaborazione in **Cronologia** e **Analisi**, le voci
saltate in **Conoscenza**.

**Audit in background.** Un audit avviato dalla pagina
**Audit** continua quando cambi pagina o chiudi la scheda; **Continua in
background** ce lo manda di proposito. La **Cronologia** elenca ogni audit in
coda e in corso (e ogni monitor in esecuzione) con il suo avanzamento; **Guarda
dal vivo** riapre la vista live, che recupera tutto ciò che è già successo. Gli
audit dello stesso relay vengono eseguiti uno dopo l'altro, così non falsano i
rispettivi risultati di latenza o affidabilità (tutti gli indirizzi loopback
contano come un solo host, quindi anche i modelli serviti dalla tua macchina
attendono); gli audit di relay diversi vengono eseguiti in parallelo, al massimo
quattro alla volta (`EKTE_MAX_PARALLEL_AUDITS`). I monitor attendono il loro
relay allo stesso modo.

**Richieste e risposte grezze.** Un'esecuzione salvata nella **Cronologia**
conserva ogni richiesta e risposta grezza scambiata (vedi [Privacy](privacy.md)).
Nel suo rapporto, **Mostra prove** sotto un rilievo elenca le richieste del
controllo corrispondente; ognuna apre la richiesta così come è stata inviata e
la risposta così come è stata ricevuta, con l'arrivo dei suoi blocchi, e
**Prove grezze** → **File delle prove** le scarica tutte. L'opzione
**Richieste/risposte grezze** del modulo di verifica (**Conserva** / **Non
conservare**) lo decide per esecuzione; ogni monitor ha la stessa opzione in
**Monitor**.

Sotto un rilievo l'elenco contiene solo le richieste su cui si basa. Ogni
coppia, e l'intera esecuzione, si scarica anche come HAR o come script curl
che invia di nuovo le richieste (`EKTE_API_KEY` fornisce la chiave).

**Rivaluta con questa versione** su un'esecuzione salvata con prove la
riproduce allo stesso modo e salva il risultato come nuova esecuzione nella
**Cronologia**; il suo rapporto indica quale esecuzione ha riprodotto.

**Analisi.** `/analytics` trasforma la cronologia
locale in confronti: indicatori per il periodo scelto (esecuzioni, punteggio
mediano, quota ad alto rischio, tasso di successo, TTFT, velocità di output,
rapporti di fatturazione) con la variazione rispetto al periodo precedente di
pari durata; un grafico di qualsiasi metrica per relay, modello o relay ×
modello, per ora, giorno o settimana (linea mediana con la fascia p25–p75, fino
a quattro serie, ogni grafico anche come tabella di dati); e una classifica dei
relay per un modello o dei modelli di un relay. I relay sono raggruppati per
voce della base di conoscenza (relay salvati e fornitori), quindi rinominare un relay
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
più token di quanti ne abbia contati ekte; più le quote di token di
ragionamento e di input in cache) e **sovraccarico del relay** (il tempo di
elaborazione dichiarato dal relay accanto al round trip di rete).

**Previsione (Analisi › Tendenze).** *Confronto nel tempo* ha una scelta
**Previsione**, disattivata per impostazione predefinita: le prossime 12 o 24
ore, 3 o 7 giorni, o 2 o 4 settimane, a seconda degli intervalli. Ogni serie
prosegue allora come linea tratteggiata con una banda tenue, su un'area chiara
etichettata «Previsione». La linea è una retta attraverso le mediane degli
intervalli (pesata per esecuzioni, intervalli anomali esclusi) e parte
dall'ultimo intervallo con 3 o più esecuzioni, così si collega allo storico;
la banda è la metà centrale delle esecuzioni (p25–p75), più larga quanto più
avanti arriva. Una nota sotto il grafico dice per ogni serie se sale o scende
e di quanto per intervallo, se è un miglioramento o un peggioramento e dove
dovrebbe trovarsi alla fine della previsione. L'adattamento ricomincia dopo un
segno di versione di ekte o di profilo della knowledge base e dopo un salto
nei dati (come un cambio di backend o di modello), perché i valori precedenti
non sono confrontabili. Nessuna previsione per una serie con meno di 6
intervalli con 3 o più esecuzioni da allora (più esecuzioni — un monitor — o
un'altra dimensione degli intervalli aiutano), né per tassi aggregati come il
tasso di successo, che non hanno banda p25–p75. La tabella dei dati aggiunge
gli intervalli previsti come righe segnate «Previsione (stima)». Una
previsione è una stima, non una misura.

**Schede e link da condividere (Analisi).** I pannelli sono in cinque schede —
**Panoramica** (indicatori, classifica), **Andamenti** (confronto nel tempo, ore
di punta), **Affidabilità** (errori, overhead del relay), **Integrità del
modello** e **Fatturazione** — sotto l’intestazione della pagina e un pannello
dei filtri comune; si carica solo la scheda che stai guardando. L’URL conserva
la scheda, i filtri e ogni opzione dei grafici
(`?tab=reliability&range=30d&relay=…&errors.bucket=dow_hour`), e **Copia il link a questa
vista** lo copia (o lo mostra in un campo da copiare se il browser non lo
consente): il link apre esattamente quella vista. Il pannello dei filtri è lo
stesso in **Cronologia**, **Monitor** e **Analisi**: chiuso, indica quanti filtri sono
attivi e li nomina in una riga (ad es. «Ultimi 30 giorni · standard · Streaming
· Example Relay»), così una vista condivisa dice cosa mostra.

**Tassi di successo, di errore, di 429 e di richieste compromesse.** Ogni richiesta che ekte invia al relay durante un'esecuzione ha esattamente un esito: un successo, un errore del relay (un timeout in attesa del relay, una risposta 5xx o 4xx o un'altra risposta difettosa), un limite di frequenza (HTTP 429) o un errore che non ha mai raggiunto il relay (la rete tra te e il relay, o ekte stesso). I tentativi ripetuti contano una volta. Il relay è giudicato solo sulle richieste che lo hanno raggiunto: il **tasso di successo**, il **tasso di errore** e il **tasso di 429** sono successi, errori del relay e limiti di frequenza divisi per quelle richieste, e sommano sempre al 100%. La **quota compromessa** è la parte di tutte le richieste fallite prima di raggiungere il relay: dice quanto ci si può fidare dell'esecuzione stessa, non quanto è buono il relay; se è alta, ripeti l'audit. Su più esecuzioni i tassi sono aggregati (tutte le richieste insieme), così un'esecuzione cattiva tra molte buone resta visibile (nove esecuzioni allo 0% e una al 40% danno circa il 4%, non lo 0%); punteggi, latenze, velocità e rapporti di fatturazione sono la mediana delle esecuzioni. Cronologia, Analisi e il report mostrano gli stessi numeri per le stesse esecuzioni, e una singola esecuzione mostra esattamente i valori del suo report. Il controllo di affidabilità del report ha un tasso proprio («Tasso di successo del controllo di affidabilità»), che conta solo per il punteggio.

## Lingue

Un menu della lingua nell'intestazione di ogni pagina passa l'interfaccia tra
**🇬🇧 inglese** (predefinito), **🇨🇳 cinese** (l'interfaccia originale),
**🇫🇷 francese**, **🇪🇸 spagnolo**, **🇵🇹 portoghese**, **🇮🇹 italiano**,
**🇩🇪 tedesco** e **🇳🇴 norvegese** (bokmål); la scelta è ricordata per browser.

I rapporti scaricati dall'interfaccia (**Scarica il rapporto**: JSON, Markdown,
HTML o PDF) seguono la lingua scelta: le chiavi JSON, i valori enumerati
(`risk_level`, `status`, `severity`, …), gli id e le prove restano esattamente
come nel rapporto della CLI (il JSON resta un rapporto ekte valido), mentre i
valori leggibili (titolo e riepilogo del verdetto, titoli e riepiloghi delle
rilevazioni, raccomandazioni, nomi dei rilevatori, note) vengono tradotti, e il
nome del file porta la lingua (`ekte-report.it.json`, `ekte-report.it.pdf`). I
titoli di sezione dei file Markdown/HTML/PDF sono in inglese. I rapporti della
CLI con `--format json|md|html|pdf` restano in inglese.

**I prompt inviati all'endpoint verificato non seguono la lingua
dell'interfaccia.** Ogni testo che ekte invia a un'API di LLM è in inglese, così
lo stesso relay riceve lo stesso verdetto chiunque legga il rapporto (i controlli
delle risposte e le stime dei token sono calibrati su quei testi esatti). Le sole
eccezioni sono le impronte della base di conoscenza la cui lingua *è* la misura —
per esempio le sonde di scioltezza in cinese, di tokenizer e di
autoidentificazione dei modelli cinesi. Ogni rapporto registra le lingue di sonda
effettivamente usate (`prompt_languages`, per es. `["en", "zh"]`).
Ogni rapporto registra anche come è stato interrogato l'endpoint: il protocollo
(`target.api`: `openai`, `anthropic` o `responses`), se `--api auto` lo ha
rilevato (`target.api_auto`) e la modalità di richiesta della sonda delle
prestazioni (`stream_mode`: `stream`, `non_stream` o `both` per la suite completa).
La pagina della cronologia dell'interfaccia web può filtrare su tutti e tre.
`started_at` registra quando è iniziata la verifica (UTC); lo `start_ms` di ogni
record di richiesta conta da quel momento.
