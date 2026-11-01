# Monitoraggio

> [🇬🇧 English](../../../guide/monitoring.md) · [🇨🇳 中文](../../zh-CN/guide/monitoring.md) · [🇫🇷 Français](../../fr/guide/monitoring.md) · [🇪🇸 Español](../../es/guide/monitoring.md) · [🇵🇹 Português](../../pt/guide/monitoring.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/monitoring.md) · [🇳🇴 Norsk](../../nb/guide/monitoring.md)

Un relay può servire il modello vero oggi e sostituirlo di nascosto la settimana
prossima. `ekte watch` ripete la verifica secondo una pianificazione, registra
ogni esecuzione nella cronologia e avvisa un webhook quando il rischio supera una
soglia o **peggiora** rispetto all'esecuzione precedente.

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang it                                     # oppure --once per cron
```

Gli avvisi sono formattati per **Slack / Feishu / DingTalk / JSON generico**,
rilevati automaticamente dall'URL del webhook, e scritti nella lingua degli avvisi
— inglese per impostazione predefinita; `--alert-lang en|zh|fr|es|pt|it|de|nb`. Il
payload JSON generico mantiene neutri chiavi e valori macchina (`risk_level`,
`score`, …), traduce quelli leggibili (`text`, `headline`, `key_findings`) e
indica la `language`.

**Nell'interfaccia web**, `ekte serve` esegue gli stessi monitor in uno
scheduler in background all'interno del processo del server, registra ogni
esecuzione nella **Cronologia** e invia gli stessi avvisi via webhook. Apri un'esecuzione nella **Cronologia** e scegli
**Pianifica come monitor**. ekte copia la configurazione di quell'esecuzione
(relay, modello, modello dichiarato, fornitore, suite, dimensioni
personalizzate) in un monitor in pausa nella pagina **Monitor**; lì imposta
l'intervallo e la chiave API (la Cronologia non salva mai le chiavi) e
attivalo. Intervallo, chiave, **Soglia di avviso**, webhook e **Lingua degli
avvisi** si modificano direttamente su ogni monitor. Un clic sul nome
comprime la scheda a nome, stato e ultima esecuzione (**Comprimi tutto** /
**Espandi tutto** sopra l'elenco; ricordato per browser), e il pannello dei
filtri (ricerca, stato, ultimo rischio, tipo di endpoint, relay, suite)
restringe un elenco lungo come nella **Cronologia**.

Ogni monitor ha la propria lingua degli avvisi (per impostazione predefinita
quella dell'interfaccia), si può eseguire subito, mettere in pausa o eliminare,
e resta legato al profilo della base di conoscenza con cui è stato creato finché
non lo ricolleghi.

I monitor in scadenza vengono eseguiti contemporaneamente, ciascuno come audit a
sé, ma mai più di un audit alla volta per host di relay e al massimo
`EKTE_MAX_PARALLEL_AUDITS` in totale; un'esecuzione attende che si liberi un posto
(anche un audit avviato a mano può finire in coda dietro ai monitor in
esecuzione). L'orario di un'esecuzione è quello in cui inizia il suo audit, dopo
un'eventuale attesa. Il controllo di regressione confronta con l'esecuzione
salvata più recente dello stesso relay e modello, a prescindere da quante altre
esecuzioni siano state salvate nel frattempo. I webhook di avviso di
un'esecuzione vengono inviati contemporaneamente, così uno lento o non
raggiungibile non blocca gli altri. Le chiavi sono salvate cifrate nella tua
directory dei dati locale e non vengono mai restituite al browser.

**Archiviazione delle chiavi API.** Per impostazione predefinita ekte **non
salva** le chiavi API dei monitor: una chiave inserita resta solo nella memoria
di `ekte serve` e non viene mai scritta su disco. Dopo un riavvio la pagina
**Monitor** indica i monitor che hanno di nuovo bisogno della chiave; attendono
(nessuna esecuzione fallita, nessun avviso) finché non la reinserisci. I monitor
senza chiave e i riferimenti `env:`/`file:` continuano a funzionare. Perché le
chiavi sopravvivano ai riavvii, scegli **Salva cifrate su questo computer** in
**Archiviazione delle chiavi API** nella pagina **Monitor**: le chiavi vengono
allora conservate in `watches.db`, cifrate con una chiave principale. Tornare
indietro sposta le chiavi salvate in memoria e le cancella da `watches.db`. L'avviso
della pagina mostra la modalità attiva, chiede conferma prima di cambiare e
riporta cosa è stato spostato. Un'installazione che salvava già chiavi cifrate, o che imposta
`EKTE_SECRET_KEY`, continua a salvarle finché non cambi.

**Chiave principale.** Le chiavi API dei monitor sono cifrate con una chiave
principale che ekte non scrive mai su disco. La prima volta che salvi una chiave
API, la pagina **Monitor** la crea e la mostra una sola volta: copiala o
scaricala, conservala in un gestore di password (il browser può salvarla) e
incollala di nuovo per confermare. Dopo ogni riavvio di `ekte serve` la pagina
la richiede (il browser può compilarla); fino ad allora i monitor che ne hanno
bisogno aspettano, mentre quelli senza chiave o con chiavi `env:`/`file:`
continuano a girare. La barra di stato della pagina offre anche **Blocca**,
**Ruota** e **Chiave dimenticata?** (scarta le chiavi API cifrate così puoi
reinserirle). Per un uso non presidiato o con Docker, passa la chiave come
`EKTE_SECRET_KEY` (vedi [Docker](docker.md));
`ekte secret status | export | rotate` la gestiscono da riga di comando.
