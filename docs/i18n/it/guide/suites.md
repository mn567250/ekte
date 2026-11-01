# Suite e modalità di confronto

> [🇬🇧 English](../../../guide/suites.md) · [🇨🇳 中文](../../zh-CN/guide/suites.md) · [🇫🇷 Français](../../fr/guide/suites.md) · [🇪🇸 Español](../../es/guide/suites.md) · [🇵🇹 Português](../../pt/guide/suites.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/suites.md) · [🇳🇴 Norsk](../../nb/guide/suites.md)

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

## Suite personalizzata

Esegui solo le dimensioni che ti interessano, risparmiando tempo e token. Ogni
rilevatore di ogni dimensione scelta viene eseguito, come in `deep`:

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` è ripetibile o separato da virgole e implica `--suite custom`;
in un file di configurazione usa `run.dimensions: [protocol, performance]`. Le
dimensioni sono `connectivity`, `protocol`, `context_window`, `model_identity`,
`capability`, `streaming`, `billing`, `reliability`, `security` e
`performance`. Nell'interfaccia web il pulsante di suite `custom` apre la stessa
scelta (**Dimensioni da eseguire**) nella pagina di verifica e nei
monitor.

Il **punteggio complessivo è la media ponderata delle sole dimensioni scelte**;
quelle escluse compaiono come «non selezionate». Anche il verdetto di rischio si
basa sulle dimensioni scelte: senza l'identità del modello copre solo quelle,
non quale modello viene servito, e lo dice.

## Modalità di confronto e giudice LLM

ekte ha due modalità di rilevamento:

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
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

La **modalità di confronto** (`ekte compare`, o **Confronta con un riferimento
affidabile** nell'interfaccia web) esegue le stesse sonde, nello stesso momento,
contro un riferimento affidabile del modello dichiarato. È la via di conferma più
forte: risposte d'identità, parametri di richiesta rifiutati, canary di
manomissione e prestazioni vengono giudicati fianco a fianco, e solo un
riferimento permette all'affidabilità del verdetto di essere *alta*. Senza
`--judge-base-url`, la modalità di confronto usa il riferimento come giudice.
