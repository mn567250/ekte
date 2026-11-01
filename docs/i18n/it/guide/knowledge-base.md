# Base di conoscenza

> [🇬🇧 English](../../../guide/knowledge-base.md) · [🇨🇳 中文](../../zh-CN/guide/knowledge-base.md) · [🇫🇷 Français](../../fr/guide/knowledge-base.md) · [🇪🇸 Español](../../es/guide/knowledge-base.md) · [🇵🇹 Português](../../pt/guide/knowledge-base.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/knowledge-base.md) · [🇳🇴 Norsk](../../nb/guide/knowledge-base.md)

ekte giudica un relay in base al **profilo** del modello che dichiara: finestra di
contesto nativa, output massimo, data di cutoff delle conoscenze, tokenizer,
capacità, parole chiave d'identità e impronte comportamentali. I profili integrati
coprono OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM e Moonshot
(`ekte kb` li elenca). Ci sono tre livelli; i successivi prevalgono:

1. Profili **integrati**, un file YAML per fornitore in
   [`ekte/knowledge/data/`](../../../../ekte/knowledge/data).
2. **Una directory con i tuoi file YAML**: `--kb-dir ./my-profiles` (ripetibile)
   o `EKTE_KB_DIR`.
3. **Le tue voci** (`kb.db` nella directory dei dati), aggiunte senza file YAML né
   installazione modificabile:
   - nella pagina **Conoscenza** dell'interfaccia web (`/kb`), con una scheda
     per **Modelli**, **Provider** e **Relay**. Ogni scheda elenca l'insieme
     completo — inclusi, `EKTE_KB_DIR` e tuoi (contrassegnati **Tuo**) — con un
     filtro, un interruttore per elemento e un modulo **Aggiungi …**: **Aggiungi un
     modello** → **Copia il prompt di ricerca** nell'assistente IA che preferisci,
     carica o incolla lo YAML con cui risponde, poi **Verifica e salva**;
     **Aggiungi un provider** accetta YAML di fornitore allo stesso modo; **Aggiungi
     un relay** chiede un nome e un URL di base. **Quale profilo usa un ID di
     modello?** mostra come si risolve un id; le tue voci si possono esportare in
     YAML;
   - nella pagina **Verifica** dell'interfaccia web: **Salva
     nella base** conserva nome e URL di base di un relay (una voce di provider
     senza modelli), elencato in **Conoscenza → Relay**;
   - da riga di comando: `ekte kb-prompt <model>`, `ekte kb-import <file>`
     (aggiungi `--check` per limitarti a verificarlo) e `ekte kb-export`.

Prima di salvare una voce ekte la controlla: schema e limiti, espressioni regolari
pericolose, ogni prompt che invierebbe e id di modello che verrebbero risolti in un
altro profilo. Un tuo modello con l'id di uno integrato lo sostituisce (segnalato
come *oscuramento*), ma non modifica mai le impostazioni proprie di un fornitore
integrato; le impronte vengono unite per id. Disattivare un modello, provider o
relay incluso nella pagina **Conoscenza** viene salvato anch'esso in `kb.db`: un id
di modello disattivato non viene più risolto, un fornitore disattivato porta con sé
i suoi modelli e URL di base. `ekte check` e `ekte serve` usano esattamente gli
stessi profili; `--no-user-kb` (o `EKTE_NO_USER_KB=1`) esclude le tue voci e i tuoi
interruttori.

Un modello con `identity_keywords` vuoto non viene salvato così: ekte completa
le sue parole di marchio a partire dai nomi del fornitore e del modello (per
esempio `glm` e `z.ai`) e mostra un avviso
per controllarle, perché senza di esse il controllo d'identità potrebbe
scambiare il produttore del modello per un marchio rivale. Il prompt di ricerca
le chiede esplicitamente all'assistente IA.

Ogni rapporto registra il profilo rispetto a cui ha verificato (`knowledge`:
fornitore, modello, come è stato risolto l'id, la sua origine e un'istantanea
completa con il suo hash del contenuto), così un rapporto resta verificabile anche
dopo che la base di conoscenza è cambiata.
