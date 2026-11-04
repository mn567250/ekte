# Rapporti

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` e `ekte compare` stampano un verdetto e scrivono il rapporto in
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

## File delle prove

Con `--evidence PATH` (`check`, `compare`, `image`, `audio`), e per
impostazione predefinita per ogni esecuzione salvata nella cronologia, ekte
scrive anche ogni richiesta e risposta HTTP grezza dell'esecuzione in un file:
JSON Lines in un flusso zstd, `<run_id>.jsonl.zst` (una directory indicata come
`PATH` riceve questo nome). La prima riga descrive l'esecuzione; ogni riga
successiva è una richiesta con la sua risposta, compreso il momento in cui è
arrivato ogni blocco della risposta. Il `seq` di una riga è il `seq` della
richiesta in `performance.requests` del rapporto, quindi ogni richiesta
elencata dal rapporto può essere ritrovata. Il campo `evidence` del rapporto
indica il file con il suo SHA-256 e il numero di scambi.

```bash
ekte check --base-url https://relay.example.com/v1 --model gpt-4o --evidence reports/
zstd -dc reports/<run_id>.jsonl.zst | jq -c 'select(.seq == 12)'
```

Ogni rilievo indica le richieste su cui si basa (`evidence_seqs`; vuoto quando
non si basa su nessuna, come il controllo TLS). `ekte evidence-export` prende
il file (o l'id di un'esecuzione salvata) e lo trasforma in HAR per un
visualizzatore HAR o gli strumenti per sviluppatori del browser
(`--as har`), in uno script curl che invia di nuovo le richieste
(`--as curl`; imposta prima `EKTE_API_KEY`, il file non contiene mai la
chiave) o in un unico documento JSON (`--as json`); `--seq` sceglie le
richieste.

`ekte rescore` rivaluta un'esecuzione registrata con la versione di ekte
installata: ripete la stessa verifica, ma risponde a ogni richiesta con la
risposta registrata (con i tempi registrati) invece di contattare
l'intermediario, così i controlli migliorati valgono anche per le vecchie
esecuzioni. Accetta l'id di un'esecuzione salvata (e salva il risultato come
nuova esecuzione, salvo con `--no-save`) o un file di rapporto con
`--evidence PATH`. Un controllo che ora chiede qualcosa che l'esecuzione
registrata non ha mai chiesto resta inconcludente invece di essere valutato su
un'ipotesi; il campo `rescored_from` del rapporto indica quante richieste sono
state riprodotte e quali controlli non ne avevano.

Le chiavi e le intestazioni sensibili vengono rimosse prima di scrivere
qualsiasi cosa (vedi [Privacy](privacy.md)). Ogni riga rispetta
`ekte/schemas/evidence.schema.json` ([Schemi](../../../reference/schemas.md)).
Nell'interfaccia web, **Mostra prove** sotto un rilievo di un'esecuzione
salvata elenca le richieste del controllo corrispondente e apre ogni richiesta
e risposta grezza.
