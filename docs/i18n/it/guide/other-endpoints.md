# Verifiche di embedding, rerank, immagini e audio

> [🇬🇧 English](../../../guide/other-endpoints.md) · [🇨🇳 中文](../../zh-CN/guide/other-endpoints.md) · [🇫🇷 Français](../../fr/guide/other-endpoints.md) · [🇪🇸 Español](../../es/guide/other-endpoints.md) · [🇵🇹 Português](../../pt/guide/other-endpoints.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/other-endpoints.md) · [🇳🇴 Norsk](../../nb/guide/other-endpoints.md)

Questi endpoint restituiscono vettori, classifiche, immagini o audio invece di
chat, quindi ekte li verifica con sonde mirate invece dei prompt di chat. Ognuno
stampa un verdetto e supporta `--json` e `--fail-on-risk`.

## Tipo di endpoint (superficie), monitor di embedding e rerank

Ogni verifica, riga della cronologia e monitor ha un **tipo di endpoint**
(`surface`): `chat` (predefinito), `embedding` o `rerank`. È indipendente dalla
suite. Le verifiche di embedding e rerank passano per lo stesso runner, lo stesso
punteggio (0–100, A–F), la cronologia, l'analisi e i monitor delle verifiche di
chat; cambiano solo i rilevatori. Cronologia e analisi filtrano per tipo di
endpoint, e l'analisi mostra solo le metriche pertinenti.

Per monitorare un endpoint di embedding o rerank, verificalo nella pagina
**Verifica** (scegli **Embedding** o **Riordinamento** nel selettore del tipo di
endpoint) e scegli
**Monitora**, oppure **Pianifica come monitor** sulla sua
riga della cronologia. Il monitor ripete la verifica secondo la pianificazione, con
lo stesso fissaggio della base di conoscenza, la stessa soglia di avviso e gli
stessi avvisi di regressione di un monitor di chat, e controlla la **deriva**
rispetto alla sua esecuzione precedente (i vettori di una sonda di embedding, la
classifica e i punteggi di una sonda di rerank). La dimensione dichiarata di un
monitor di embedding si modifica sulla sua scheda (vuota o 0: dalla base di
conoscenza). Le sonde di velocità (embedding: latenza, avvio a freddo, input/s,
scalabilità a lotti; rerank: latenza, avvio a freddo, documenti/s, 4 contro 32
documenti) girano solo nelle suite deep, full o custom, o in standard con un
riferimento.

## Embedding e rerank

```bash
# La dimensione del vettore attesa è ricavata dalla base di conoscenza per il modello dichiarato.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Oppure indicare direttamente la dimensione attesa:
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: una sonda integrata a risposta nota — un vero reranker deve mettere
# al primo posto il documento palesemente pertinente.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Più a fondo: aggiunge la sonda di velocità del rerank; --no-save tiene l'esecuzione fuori dalla cronologia.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# Vedere prima i controlli e le chiamate stimate, senza inviare richieste:
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` controlla la connettività, la **sonda a risposta nota** (il documento
chiaramente pertinente deve finire primo), il campo `model` restituito, il
determinismo (la stessa query due volte dà la stessa classifica e gli stessi
punteggi) e la **deriva della classifica** rispetto all'esecuzione salvata
precedente. `ekte embed` e `ekte rerank` accettano `--suite`, `--save/--no-save`
(salvato per impostazione predefinita, così l'esecuzione successiva ha un
riferimento di deriva) e `--dry-run`.

`embed` controlla la connettività, la **corrispondenza della dimensione**
(lunghezza del vettore restituito rispetto alla dimensione nativa del modello
dichiarato — il segnale principale di merce non conforme: un relay che dichiara
`text-embedding-3-large` a 3072-d ma restituisce 1024-d serve un sostituto), il
determinismo (stesso input → coseno ≈ 1), la distinzione (input non correlati →
coseno nettamente sotto 1) e il campo `model` restituito. Profili integrati:
OpenAI `text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024),
Google `gemini-embedding-2` (3072).

Entrambi sono anche nell'interfaccia web: partono dalla pagina **Verifica** con il
selettore del tipo di endpoint (**Embedding**, **Riordinamento**). La verifica rerank usa sempre le sonde
integrate, così ogni esecuzione resta confrontabile per la deriva e il
monitoraggio.

## Generazione di immagini e audio (TTS)

Generazione di immagini (`POST /v1/images/generations`) e sintesi vocale
(`POST /v1/audio/speech`), decodificate con la sola libreria standard di Python —
dimensioni dell'immagine dai byte dell'intestazione (PNG/JPEG/GIF/WebP), durata
WAV tramite `wave`.

```bash
# Un relay che dichiara DALL·E 3 restituisce davvero il 1792x1024 richiesto? Un'immagine
# ridotta o di dimensioni errate (o fuori dalle dimensioni native del modello dichiarato,
# secondo la base di conoscenza) è il segnale principale di merce non conforme.
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Un relay che dichiara tts-1-hd restituisce audio vero la cui durata cresce con l'input
# (non un segnaposto fisso, non HTML/JSON travestito da audio)?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
```

`image` controlla la connettività, un formato valido e decodificabile, la
**corrispondenza delle dimensioni** (larghezza × altezza decodificate rispetto alla
richiesta e alle dimensioni native del modello dichiarato — FAIL/HIGH in caso di
discrepanza), la distinzione (due prompt → immagini diverse, per smascherare un
segnaposto fisso), il numero e il campo `model`. `audio` controlla la
connettività, la validità del contenitore/formato, il rispetto del formato, una
durata non banale che cresce con l'input, la distinzione e il campo `model`. La
base di conoscenza include OpenAI DALL·E 2/3, gpt-image-1, gpt-image-2,
tts-1/tts-1-hd/gpt-4o-mini-tts e profili immagine/TTS di Qwen.
