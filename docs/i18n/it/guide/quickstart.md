# Avvio rapido

> [🇬🇧 English](../../../guide/quickstart.md) · [🇨🇳 中文](../../zh-CN/guide/quickstart.md) · [🇫🇷 Français](../../fr/guide/quickstart.md) · [🇪🇸 Español](../../es/guide/quickstart.md) · [🇵🇹 Português](../../pt/guide/quickstart.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/quickstart.md) · [🇳🇴 Norsk](../../nb/guide/quickstart.md)

```bash
# 1) verificare un relay rispetto a ciò che dichiara (id del modello + indizio sul fornitore)
export EKTE_API_KEY=sk-la-tua-chiave-del-relay
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) il controllo più forte: confronto con un riferimento affidabile dello stesso modello
export OPENAI_API_KEY=sk-la-tua-chiave-openai
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) verificare un relay nativo Anthropic (API Messages) — il protocollo è rilevato
#    automaticamente da base_url/model, o forzato con --api anthropic
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) confermare una sostituzione sospetta: verificare l'id REALE del modello del relay rispetto
#    al profilo con cui viene venduto (qui: un modello Doubao spacciato per deepseek-v4-flash)
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) elencare i modelli che un endpoint pubblicizza
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) consultare la base di conoscenza
ekte kb            # tutti i profili, con la loro origine
ekte kb deepseek   # un fornitore

# 7) generare una configurazione da versionare
ekte init          # scrive ekte.yaml
ekte check -c ekte.yaml
```

Le chiavi API si possono indicare in chiaro, come `env:VAR` o come
`file:/percorso`; i rapporti contengono sempre e solo un'impronta della chiave.
Un file di configurazione completo è in [`examples/ekte.yaml`](../../../../examples/ekte.yaml).

Il file ha una versione del formato (`version: 1`; un file senza versione è nel formato 1). Tipi errati e valori non validi vengono rifiutati indicando file, riga e chiave; le chiavi sconosciute vengono ignorate con un avviso fino a ekte 1.0.0, che le rifiuta. `ekte config migrate` aggiorna un file più vecchio. Lo schema è [`docs/schemas/config.schema.json`](../../../schemas/config.schema.json).

## Come strumento per un LLM / agente

ekte è pensato per essere pilotato da un altro programma o modello. Tutto va su
stdout in JSON, errori compresi, e il codice di uscita fa da barriera.

```bash
# verdetto snello, adatto agli agenti (~5x più piccolo di --json: senza le prove voluminose)
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# rapporto strutturato completo quando ti servono le prove di ogni rilevazione
ekte check --base-url ... --model gpt-4o --json

# prima il budget: quali rilevatori girano + chiamate API stimate, SENZA farne nessuna
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# barriera sul codice di uscita (1 se il rischio >= medium, o il punteggio è sotto --fail-under);
# gli errori di configurazione/uso escono con 2, in JSON
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# scoperta leggibile dalle macchine
ekte kb --json                      # l'intera base di conoscenza
ekte models --base-url ... --json   # cosa pubblicizza un endpoint
```

In modalità `--json`/`--compact` una configurazione errata stampa
`{"error": {...}}` (codice di uscita 2) invece di un messaggio per persone,
così una pipeline può gestire i fallimenti in modo uniforme.
