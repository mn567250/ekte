# Prestazioni

> [🇬🇧 English](../../../guide/performance.md) · [🇨🇳 中文](../../zh-CN/guide/performance.md) · [🇫🇷 Français](../../fr/guide/performance.md) · [🇪🇸 Español](../../es/guide/performance.md) · [🇵🇹 Português](../../pt/guide/performance.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/performance.md) · [🇳🇴 Norsk](../../nb/guide/performance.md)

Ogni rapporto contiene una sezione **performance**: latenza, tempo al primo token
(TTFT), token/s di decodifica e end-to-end, latenza e jitter tra frammenti, tassi
di errore/timeout/429, una scomposizione di rete (connessione TCP, TLS, un giro
`GET /models`, tempo del server) e avvio a freddo, ciascuno come count / min /
mean / p50 / p75 / p90 / p95 / p99 / max / stdev.

Quando la sonda dedicata viene eseguita, assegna il punteggio alla dimensione
**Prestazioni**. Il punteggio misura la **costanza**, non la velocità pura, quindi
un endpoint lento ma costante (un modello locale o self-hosted) non viene
penalizzato per non essere un data center; i controlli e i loro punti sono nella
[Metodologia](methodology.md#performance--prestazioni). Le rilevazioni sulle prestazioni sono al massimo di gravità bassa: spostano il
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

Gli audit eseguiti contemporaneamente in `ekte serve` (più schede del browser,
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
