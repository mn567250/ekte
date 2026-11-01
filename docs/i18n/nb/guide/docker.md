# Kjøre nettgrensesnittet i Docker

> [🇬🇧 English](../../../guide/docker.md) · [🇨🇳 中文](../../zh-CN/guide/docker.md) · [🇫🇷 Français](../../fr/guide/docker.md) · [🇪🇸 Español](../../es/guide/docker.md) · [🇵🇹 Português](../../pt/guide/docker.md) · [🇮🇹 Italiano](../../it/guide/docker.md) · [🇩🇪 Deutsch](../../de/guide/docker.md) · **🇳🇴 Norsk**

`ekte serve` er et verktøy for én bruker uten innlogging. Utenfor en container
lytter det bare på loopback (`127.0.0.1`, `::1`, `localhost`) og avviser alle
andre bindingsadresser. En container er det ene unntaket: serveren må lytte på
containerens egne grensesnitt for at Dockers portpublisering skal nå den.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# åpne http://localhost:8000
```

**Publiser alltid på `127.0.0.1`** (`-p 127.0.0.1:8000:8000`, ikke `-p 8000:8000`).
En naken `-p 8000:8000` publiserer grensesnittet — og hver API-nøkkel som tastes
inn i det eller lagres i en overvåking — til nettverket ditt.

## Miljøvariabler

| Variabel | Standard | Formål |
|---|---|---|
| `EKTE_CONTAINER` | ikke satt (`1` i bildet) | Tillater binding til annet enn loopback. ekte kontrollerer også at den virkelig kjører i en container (`/.dockerenv`, `/run/.containerenv` eller Kubernetes); å sette den på en vanlig maskin åpner ikke serveren. |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` i bildet) | Bindingsadresse. Alt annet enn loopback krever `EKTE_CONTAINER=1`. `--host` går foran. |
| `EKTE_PORT` | `8000` | Port inne i containeren. `--port` går foran. |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` i bildet) | Revisjonshistorikk, overvåkinger (med API-nøklene deres) og dine egne oppføringer i kunnskapsbasen. Monter et volum her for å beholde dem. |
| `EKTE_SECRET_KEY` | ikke satt | Hovednøkkel som krypterer overvåkingenes lagrede API-nøkler: nøkkelen **Overvåking**-siden (eller `ekte secret rotate`) viste deg, eller `file:/run/secrets/ekte_key` / `env:VAR`. Er den ikke satt, oppgir du nøkkelen på **Overvåking**-siden etter hver oppstart av containeren. Lagres aldri i `EKTE_DATA_DIR`. Satt på en ny datamappe velger den kryptert lagring av nøkler; uten den lagres ikke overvåkingenes API-nøkler i det hele tatt og må oppgis på nytt etter hver oppstart av containeren. Se nedenfor. |
| `EKTE_KB_DIR` | ikke satt | Ekstra YAML-mappe for kunnskapsbasen, for eksempel montert skrivebeskyttet (`-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb`). |
| `EKTE_NO_USER_KB` | ikke satt | `1` ignorerer oppføringene du har lagt til i kunnskapsbasen i grensesnittet (`kb.db`). |
| `EKTE_ALLOWED_HOSTS` | ikke satt | Kommaseparerte ekstra vertsnavn grensesnittet svarer på, hvis du når det under et annet navn enn `localhost`/`127.0.0.1`. |

**Fra zing-bildet.** Gi `-e ZING_*`-alternativer nytt navn til `EKTE_*`. ekte
leser fortsatt en `ZING_*`-variabel når `EKTE_*`-navnet ikke er satt, men bildet
setter selv `EKTE_CONTAINER`, `EKTE_HOST`, `EKTE_PORT` og `EKTE_DATA_DIR`, så en
gammel `ZING_HOST`, `ZING_PORT` eller `ZING_DATA_DIR` har ingen virkning i
containeren. Datavolumet blir værende på `/data`, og den uprivilegerte brukeren
beholder uid 10001, så et eksisterende `zing-data`-volum kan monteres som det er
(`-v zing-data:/data`). `ZING_*`-reserveløsningen er foreldet og fjernes i ekte
1.0.0 (se [retningslinjene for stabilitet](../../../reference/stability.md#deprecation-zing)).

## Hva som beskytter grensesnittet

- **Liste over tillatte verter.** Forespørsler der `Host`-hodet ikke er
  `localhost`, `127.0.0.1`, `[::1]` eller står i `EKTE_ALLOWED_HOSTS`, avvises.
  Dette stopper DNS-rebinding, der et nettsted peker sitt eget domene mot
  `127.0.0.1` for å snakke med lokale servere. Porten kontrolleres ikke, så
  enhver publisert vertsport fungerer.
- **Kontroll av opphav og JSON.** Forespørsler som endrer tilstand fra et annet
  opphav avvises, og forespørselskropper må være `application/json`, så et annet
  nettsted ikke kan sende skjemaer til det lokale API-et.
- **Sikkerhetshoder.** Grensesnittet kan ikke rammes inn av andre nettsteder
  (`X-Frame-Options`, `frame-ancestors`), og ingen referrer forlater siden.
- **Krypterte overvåkingsnøkler.** Lagrede API-nøkler krypteres med en
  hovednøkkel som aldri skrives til datavolumet, så en kopi av volumet avslører
  ingen API-nøkkel. Uten `EKTE_SECRET_KEY` viser **Overvåking**-siden nøkkelen
  én gang når den opprettes, og ber om den etter hver oppstart av containeren;
  overvåkinger som trenger den, venter til da. For omstarter uten tilsyn sender
  du den inn som en Docker-hemmelighet (serveren holder den i minnet; kjør én
  serverprosess per datavolum):

  ```bash
  # nøkkelen Overvåking-siden viste deg, eller en ny: ekte secret rotate
  docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data \
    -v "$PWD/ekte_key:/run/secrets/ekte_key:ro" \
    -e EKTE_SECRET_KEY=file:/run/secrets/ekte_key ekte
  ```

  En `EKTE_SECRET_KEY` som ikke er nøkkelen de lagrede API-nøklene bruker,
  avvises (grensesnittet sier fra). Roter med `ekte secret rotate`; en tapt
  nøkkel kan bare tilbakestilles på **Overvåking**-siden, noe som forkaster de
  lagrede API-nøklene.
- **Data bare for eieren.** Datamappen opprettes med `0700`, og hver databasefil
  har `0600`; bildet kjører som en uprivilegert bruker.
