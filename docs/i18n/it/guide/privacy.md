# Privacy e dati locali

> [🇬🇧 English](../../../guide/privacy.md) · [🇨🇳 中文](../../zh-CN/guide/privacy.md) · [🇫🇷 Français](../../fr/guide/privacy.md) · [🇪🇸 Español](../../es/guide/privacy.md) · [🇵🇹 Português](../../pt/guide/privacy.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/privacy.md) · [🇳🇴 Norsk](../../nb/guide/privacy.md)

- **Solo locale.** `ekte serve` ascolta solo su loopback (`127.0.0.1`, `::1`,
  `localhost`), risponde solo a quei nomi host e rifiuta le richieste
  cross-site; non ha login perché nulla al di fuori della tua macchina può
  raggiungerlo. ekte contatta solo gli endpoint che configuri (obiettivo,
  riferimento, giudice, webhook); non scarica nulla in fase di esecuzione,
  nemmeno file di tokenizer.
- **Chiavi.** I rapporti e la cronologia conservano solo un'impronta di una
  chiave API. Le chiavi dei monitor sono salvate cifrate in `watches.db`; la
  chiave principale che le decifra non viene mai scritta nella directory dei
  dati (la conservi tu, vedi [Monitoraggio](monitoring.md)), quindi una copia della
  directory non rivela alcuna chiave API. La directory resta comunque
  accessibile solo al tuo utente.
- **Directory dei dati.** `~/.ekte` (o `EKTE_DATA_DIR`), creata con `0700` e
  file con `0600`: `history.db` (cronologia delle verifiche), `watches.db`
  (monitor, chiavi cifrate comprese) e `kb.db` (le tue voci della base di
  conoscenza). Elimina la directory per rimuovere tutto.
  `ekte data-dir` mostra dove si trova; `--data-dir PERCORSO` ne sceglie
  un'altra per una singola esecuzione, ad es. `ekte serve --data-dir .` tiene
  i database nella cartella corrente. Sono normali file SQLite che puoi aprire
  per le tue analisi (meglio in sola lettura mentre ekte è in esecuzione). Non
  fare commit di `watches.db` se quella cartella è un repository.
  `history_metrics` contiene una riga di valori misurati per esecuzione e
  `history_requests` ogni record di richiesta (salvato lì una sola volta, non
  dentro ogni rapporto).
- **File delle prove.** Un'esecuzione salvata nella cronologia (interfaccia
  web, monitor, `ekte watch`, `ekte embed`, `ekte rerank`) conserva anche ogni
  richiesta e risposta grezza scambiata, in `evidence/<run_id>.jsonl.zst` nella
  directory dei dati, così ogni rilievo può essere verificato rispetto a ciò che
  è stato davvero inviato e ricevuto. Le tue chiavi API, i valori di `--header`,
  `Authorization`, i cookie e le altre intestazioni sensibili vengono rimossi
  prima di scrivere qualsiasi cosa; prompt e risposte restano come erano.
  Eliminare un'esecuzione elimina il suo file. Si disattiva per esecuzione
  (l'opzione **Richieste/risposte grezze** del modulo di verifica, o
  `"evidence": false` in `POST /api/v1/jobs`), per monitor o per tutto il
  server (`ekte serve --no-evidence`, `EKTE_NO_EVIDENCE=1`). `ekte check`,
  `compare`, `image` e `audio` non ne conservano, salvo con `--evidence PATH`
  (vedi [Rapporti](reports.md)).

## Uso responsabile

ekte è un aiuto alla verifica black-box. **Non può dimostrare**:

- che un fornitore conservi i tuoi prompt o li usi per l'addestramento,
- che instradi sempre verso un unico modello esatto (i relay possono instradare in modo probabilistico),
- frodi di fatturazione oltre quanto la stima indipendente dei token può suggerire.

Usa i rapporti per la tua due diligence. **Non accusare pubblicamente un
fornitore** sulla base di una singola esecuzione senza aver valutato la dimensione
del campione, le impostazioni di costo e la legge locale. Esegui `ekte compare`
contro un riferimento affidabile prima di trarre conclusioni forti.
