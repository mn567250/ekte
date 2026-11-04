# Personvern og lokale data

> [🇬🇧 English](../../../guide/privacy.md) · [🇨🇳 中文](../../zh-CN/guide/privacy.md) · [🇫🇷 Français](../../fr/guide/privacy.md) · [🇪🇸 Español](../../es/guide/privacy.md) · [🇵🇹 Português](../../pt/guide/privacy.md) · [🇮🇹 Italiano](../../it/guide/privacy.md) · [🇩🇪 Deutsch](../../de/guide/privacy.md) · **🇳🇴 Norsk**

- **Bare lokalt.** `ekte serve` lytter bare på loopback (`127.0.0.1`, `::1`,
  `localhost`), svarer bare på de vertsnavnene og avviser forespørsler på tvers av
  nettsteder; den har ingen innlogging fordi ingenting utenfor maskinen din kan nå
  den. ekte kontakter bare endepunktene du setter opp (mål, referanse, dommer,
  webhooker); den laster ikke ned noe under kjøring, ikke engang
  tokenizer-filer.
- **Nøkler.** Rapporter og historikk tar bare vare på et fingeravtrykk av en
  API-nøkkel. Overvåkingenes nøkler lagres ikke som standard (de blir værende i
  serverens minne). Velger du å lagre dem, krypteres de i `watches.db`, og
  hovednøkkelen som dekrypterer dem, skrives aldri til datamappen (du tar vare
  på den, se [Overvåking](monitoring.md)). Uansett avslører en kopi av mappen ingen
  API-nøkkel. Mappen er likevel bare tilgjengelig for eieren.
- **Datamappe.** `~/.ekte` (eller `EKTE_DATA_DIR`), opprettet med `0700` og filer
  med `0600`: `history.db` (revisjonshistorikk), `watches.db` (overvåkinger;
  nøklene deres bare hvis du valgte å lagre dem, kryptert) og `kb.db` (dine
  oppføringer i kunnskapsbasen). Slett mappen for å fjerne alt. `ekte data-dir`
  skriver ut hvor den er; `--data-dir STI` velger en annen for én enkelt kjøring,
  f.eks. holder `ekte serve --data-dir .` databasene i gjeldende mappe. Det er
  vanlige SQLite-filer, så du kan åpne dem (skrivebeskyttet er tryggest mens ekte
  kjører) for din egen analyse: `history_metrics` har én rad med målte verdier
  per kjøring og `history_requests` hver forespørselspost (lagret der én gang,
  ikke inne i hver lagrede rapport). Ikke legg `watches.db` inn i
  versjonskontroll hvis den mappen er et repo.
- **Bevisfiler.** En kjøring som lagres i historikken (nettgrensesnittet,
  overvåking, `ekte watch`, `ekte embed`, `ekte rerank`) beholder også hver rå
  forespørsel og hvert svar den utvekslet, i `evidence/<run_id>.jsonl.zst` i
  datakatalogen, slik at hvert funn kan kontrolleres mot nøyaktig det som ble
  sendt og mottatt. API-nøklene dine, verdiene til `--header`, `Authorization`,
  informasjonskapsler og de andre sensitive hodene fjernes før noe skrives;
  prompter og svar beholdes som de var. Sletter du en kjøring, slettes filen.
  Slå det av per kjøring (innstillingen **Rå forespørsler/svar** i
  revisjonsskjemaet, eller `"evidence": false` i `POST /api/v1/jobs`), per
  overvåking eller for hele serveren (`ekte serve --no-evidence`,
  `EKTE_NO_EVIDENCE=1`). `ekte check`, `compare`, `image` og `audio` beholder
  ingenting uten `--evidence PATH` (se [Rapporter](reports.md)).

## Ansvarlig bruk

ekte er et hjelpemiddel for black box-revisjon. Den **kan ikke bevise**:

- at en leverandør lagrer eller trener på promptene dine,
- at den alltid ruter til én bestemt modell (releer kan rute tilfeldig),
- svindel med fakturering utover det et uavhengig tokenanslag kan antyde.

Bruk rapporter til din egen aktsomhetsvurdering. **Ikke anklag en leverandør
offentlig** på grunnlag av én enkelt kjøring uten å ha vurdert utvalgsstørrelse,
kostnadsinnstillinger og lokal lovgivning. Kjør `ekte compare` mot en pålitelig
referanse før du trekker sterke konklusjoner.
