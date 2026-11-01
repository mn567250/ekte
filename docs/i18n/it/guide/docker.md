# Eseguire l'interfaccia web in Docker

> [🇬🇧 English](../../../guide/docker.md) · [🇨🇳 中文](../../zh-CN/guide/docker.md) · [🇫🇷 Français](../../fr/guide/docker.md) · [🇪🇸 Español](../../es/guide/docker.md) · [🇵🇹 Português](../../pt/guide/docker.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/docker.md) · [🇳🇴 Norsk](../../nb/guide/docker.md)

`ekte serve` è uno strumento per un solo utente, senza login. Fuori da un
container ascolta solo su loopback (`127.0.0.1`, `::1`, `localhost`) e rifiuta
qualsiasi altro indirizzo di ascolto. Il container è l'unica eccezione: il server
deve ascoltare sulle interfacce del container perché la pubblicazione delle porte
di Docker possa raggiungerlo.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# apri http://localhost:8000
```

**Pubblica sempre su `127.0.0.1`** (`-p 127.0.0.1:8000:8000`, non `-p 8000:8000`).
Un semplice `-p 8000:8000` espone alla tua rete l'interfaccia — e ogni chiave API
digitata al suo interno o salvata in un monitor.

## Variabili d'ambiente

| Variabile | Predefinito | Scopo |
|---|---|---|
| `EKTE_CONTAINER` | non impostata (`1` nell'immagine) | Consente l'ascolto su un indirizzo diverso da loopback. ekte verifica anche di essere davvero in un container (`/.dockerenv`, `/run/.containerenv` o Kubernetes); impostarla su un host normale non apre il server. |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` nell'immagine) | Indirizzo di ascolto. Qualsiasi indirizzo diverso da loopback richiede `EKTE_CONTAINER=1`. `--host` ha la precedenza. |
| `EKTE_PORT` | `8000` | Porta all'interno del container. `--port` ha la precedenza. |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` nell'immagine) | Cronologia delle verifiche, monitor (comprese le loro chiavi API) e le tue voci della base di conoscenza. Monta qui un volume per conservarli. |
| `EKTE_SECRET_KEY` | non impostata | Chiave principale che cifra le chiavi API salvate dei monitor: la chiave che ti ha mostrato la pagina **Monitor** (o `ekte secret rotate`), oppure `file:/run/secrets/ekte_key` / `env:VAR`. Se non è impostata, inserisci la chiave nella pagina **Monitor** dopo ogni avvio del container. Non viene mai salvata in `EKTE_DATA_DIR`. Impostarla su una directory dei dati nuova seleziona l'archiviazione cifrata delle chiavi; senza di essa le chiavi API dei monitor non vengono salvate affatto e vanno reinserite dopo ogni avvio del container. Vedi sotto. |
| `EKTE_KB_DIR` | non impostata | Directory YAML aggiuntiva della base di conoscenza, montata per esempio in sola lettura (`-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb`). |
| `EKTE_NO_USER_KB` | non impostata | `1` ignora le voci della base di conoscenza che hai aggiunto nell'interfaccia (`kb.db`). |
| `EKTE_ALLOWED_HOSTS` | non impostata | Nomi host aggiuntivi, separati da virgole, a cui l'interfaccia risponde, se la raggiungi con un nome diverso da `localhost`/`127.0.0.1`. |

**Se arrivi dall'immagine di zing.** Rinomina le opzioni `-e ZING_*` in `EKTE_*`.
ekte legge ancora una variabile `ZING_*` il cui nome `EKTE_*` non è impostato, ma
l'immagine imposta da sé `EKTE_CONTAINER`, `EKTE_HOST`, `EKTE_PORT` e
`EKTE_DATA_DIR`, quindi un vecchio `ZING_HOST`, `ZING_PORT` o `ZING_DATA_DIR` non
ha effetto nel container. Il volume dei dati resta in `/data` e l'utente non
privilegiato mantiene l'uid 10001, quindi un volume `zing-data` esistente può
essere montato così com'è (`-v zing-data:/data`). Il ripiego su `ZING_*` è
obsoleto e viene rimosso in ekte 1.0.0 (vedi la
[politica di stabilità](../../../reference/stability.md#deprecation-zing)).

## Cosa protegge l'interfaccia

- **Elenco di host consentiti.** Le richieste la cui intestazione `Host` non è
  `localhost`, `127.0.0.1`, `[::1]` o un nome elencato in `EKTE_ALLOWED_HOSTS`
  vengono rifiutate. Questo impedisce il DNS rebinding, in cui un sito web fa
  puntare il proprio dominio a `127.0.0.1` per parlare con i server locali. La
  porta non viene controllata, quindi funziona qualsiasi porta pubblicata
  sull'host.
- **Controlli di origine e JSON.** Le richieste che modificano lo stato
  provenienti da un'altra origine vengono rifiutate, e i corpi delle richieste
  devono essere `application/json`, così un altro sito web non può inviare moduli
  all'API locale.
- **Intestazioni di sicurezza.** L'interfaccia non può essere incorporata in
  frame da altri siti (`X-Frame-Options`, `frame-ancestors`), e nessun referrer
  lascia la pagina.
- **Chiavi dei monitor cifrate.** Le chiavi API salvate sono cifrate con una
  chiave principale che non viene mai scritta nel volume dei dati, quindi una
  copia del volume non rivela alcuna chiave API. Senza `EKTE_SECRET_KEY` la
  pagina **Monitor** mostra la chiave una sola volta, quando viene creata, e la
  chiede dopo ogni avvio del container; i monitor che ne hanno bisogno aspettano
  fino ad allora. Per riavvii non presidiati, passala come segreto Docker (il
  server la tiene in memoria; esegui un solo processo server per volume dei
  dati):

  ```bash
  # la chiave che ti ha mostrato la pagina Monitor, o una nuova: ekte secret rotate
  docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data \
    -v "$PWD/ekte_key:/run/secrets/ekte_key:ro" \
    -e EKTE_SECRET_KEY=file:/run/secrets/ekte_key ekte
  ```

  Un `EKTE_SECRET_KEY` che non è la chiave usata dalle chiavi API salvate viene
  rifiutato (l'interfaccia lo segnala). Ruotala con `ekte secret rotate`; una
  chiave persa si può solo reimpostare nella pagina **Monitor**, che scarta le
  chiavi API salvate.
- **Dati riservati al proprietario.** La directory dei dati viene creata con
  `0700` e ogni file di database con `0600`; l'immagine gira con un utente non
  privilegiato.
