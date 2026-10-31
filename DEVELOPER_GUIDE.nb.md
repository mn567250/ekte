# ekte — Utviklerveiledning

> [🇬🇧 English](DEVELOPER_GUIDE.md) · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md) · **🇳🇴 Norsk**

Denne veiledningen er for dem som endrer ekte: hvordan den er bygget, hvordan du
setter opp et utviklingsmiljø, hvordan du bidrar, og hvordan den pakkes, kjøres i
Docker og utgis. Hva ekte gjør og hvordan den brukes, står i
[README](README.nb.md); hvordan hver kontroll fungerer og gis score, står i
[Metodikken](docs/METHODOLOGY.nb.md).

---

## Innhold

- [Prinsipper](#prinsipper)
- [Utviklingsoppsett](#utviklingsoppsett)
- [Oppbygging av repoet](#oppbygging-av-repoet)
- [Arkitektur](#arkitektur)
  - [Revisjonsløpet](#revisjonsløpet)
  - [Klienter](#klienter)
  - [Detektorer og scoreskalaer](#detektorer-og-scoreskalaer)
  - [Score og konklusjon](#score-og-konklusjon)
  - [Kunnskapsbase](#kunnskapsbase)
  - [Promptbibliotek](#promptbibliotek)
  - [Rapporter](#rapporter)
  - [Overflater](#overflater)
  - [Frittstående revisorer](#frittstående-revisorer)
  - [Nettserver](#nettserver)
  - [HTTP API v1](#http-api-v1)
  - [Nettgrensesnittets frontend](#nettgrensesnittets-frontend)
  - [Lokale data](#lokale-data)
- [Bidra](#bidra)
  - [Pull requests](#pull-requests)
  - [Legge til en detektor](#legge-til-en-detektor)
  - [Redigere kunnskapsbasen](#redigere-kunnskapsbasen)
  - [Endre probeprompter](#endre-probeprompter)
  - [Oversettelser](#oversettelser)
  - [Dokumentasjon](#dokumentasjon)
- [Testing](#testing)
- [Docker](#docker)
- [Kontinuerlig integrasjon](#kontinuerlig-integrasjon)
- [Utgivelser](#utgivelser)
- [Sikkerhet](#sikkerhet)
- [Lisens](#lisens)

## Prinsipper

ekte er et hjelpemiddel for black box-revisjon: korrekthet og **å ikke anklage
ærlige releer feilaktig** betyr mer enn å fange hvert eneste triks. Ha den
standarden i tankene ved enhver endring.

- **Bevis framfor anklage.** Funn rapporterer *avvik og risiko*, aldri «svindel».
  Velg heller *uavklart* enn en gjetning. En ny vei til HIGH-alvorlighet trenger
  harde, reproduserbare bevis og må være vanskelig å utløse mot et ærlig
  endepunkt.
- **Ikke noe nettverk i testene.** Detektortester kjører mot den
  prosessinterne falske serveren i `tests/conftest.py` (httpx `MockTransport`),
  aldri mot et ekte API.
- **Hemmeligheter forlater aldri maskinen.** API-nøkler får et fingeravtrykk og
  lagres aldri i rapporter. Hver ny utdatavei må sende tekst som reléet styrer,
  gjennom `ekte.utils.redact` og escape den for sitt format.
- **Samme prober for alle.** Probetekstene er på engelsk og faste, uansett
  grensesnittspråk, så samme relé får samme konklusjon (se
  [Promptbibliotek](#promptbibliotek)).
- **Bare lokalt.** ekte kontakter bare endepunktene brukeren setter opp, og
  nettgrensesnittet lytter bare på loopback (se [Nettserver](#nettserver)).

## Utviklingsoppsett

Krever Python 3.11+. Node.js er valgfritt: testene av nettleser-JavaScript kjører
under `node` og hoppes over uten det.

```bash
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e '.[dev,web]'   # redigerbar installasjon med utviklerverktøyene og nettgrensesnittet
pytest                        # testsettet
ruff check ekte tests         # lint
mypy ekte                     # typekontroll
```

Med uv: `uv venv && uv pip install -e '.[dev,web]'`. Ingen systembiblioteker
trengs, heller ikke for PDF-rapporter.

Kjør fra kildekoden med `ekte …` eller `python -m ekte …`. `ekte serve` leverer
nettgrensesnittet rett fra `ekte/web/static/`, så en ny innlasting i nettleseren
plukker opp endringer i frontenden; det finnes ikke noe byggetrinn.

## Oppbygging av repoet

```text
ekte/
  cli.py               Typer-CLI: check, compare, models, kb*, serve, watch, embed, rerank, image, audio
  config.py            YAML-konfigurasjon, hemmelighetsreferanser (env:/file:), AuditOptions
  runner.py            run_audit(): kobler alt sammen og kjører detektorene
  context.py           AuditContext som gis til hver detektor
  models.py            pydantic-datakontrakter: TargetConfig, Finding, DetectorResult, AuditReport, …
  scoring.py           dimensjonsscorer, vekter, samlet score, risikokonklusjon, sikkerhet
  clients/             HTTP-klienter: OpenAI-kompatibel, Anthropic Messages, OpenAI Responses
  detectors/           én fil per detektor, pluss base.py (register), scale.py, helpers.py
  judge/               den pålitelige LLM-dommeren som quality_judge bruker
  knowledge/           skjema for kunnskapsbasen, laster, brukerlager (kb.db), import, undersøkelsesprompt, øyeblikksbilder
    data/              medfølgende leverandørprofiler (*.yaml)
  prompts/en.json      all tekst ekte sender til et LLM-API
  perf/                opptaker per forespørsel og rapportens ytelsesdel
  report/              JSON-/Markdown-/HTML-/PDF-gjengivere og skriveren
  embed_audit.py       frittstående revisor for embedding og rerank
  media_audit.py       frittstående revisor for bilde og lyd (TTS)
  notify.py            webhook-varsler (Slack / Feishu / DingTalk / generisk JSON)
  datadir.py           den lokale datamappen og SQLite-filene i den
  legacy.py            ZING_*-innstillingene og kopien av ~/.zing fra før navnebyttet
  secretbox.py         kryptering av lagrede hemmeligheter; hovednøkkelen som holdes i minnet
  i18n/                oversettelser som deles av nettgrensesnittet og varslene
    locales/           <code>.json per språk, fragments/<feature>/<code>.json
  utils/               sladding, SSE-tolking, statistikk, tokenanslag
  web/
    server.py          FastAPI-app: sider, JSON-API, SSE-strøm for revisjoner, planlegger for overvåkinger
    jobs.py            revisjonsjobber i bakgrunnen og porten per relé
    security.py        loopback-binding, tillatelsesliste for Host, Origin-/JSON-kontroller, hoder
    history.py         lager for revisjonshistorikk (history.db)
    analytics_store.py analysetabellene: måltall per kjøring, forespørselsposter
    analytics.py       analysespørringer: nøkkeltall, tidsserier, rangeringslister
    watches.py         lager for overvåkinger (watches.db)
    masterkey.py       hovednøkkelens tilstander og handlinger (server og `ekte secret`)
    static/            skript som deles av alle sider (lang.js, i18n.js, icons.js, …)
    static/v2/         nettgrensesnittets sider, stiler og skript
tests/                 pytest-testsett; conftest.py inneholder det falske reléet
docs/                  METHODOLOGY (8 språk), CI.md, DOCKER.md, PUBLISHING.md
examples/ekte.yaml     kommentert konfigurasjonsfil
action.yml             den sammensatte GitHub-handlingen
Dockerfile             image for nettgrensesnittet
```

## Arkitektur

### Revisjonsløpet

`ekte check`, `ekte compare`, `ekte watch`, nettgrensesnittets revisjonsstrøm og
planleggeren for overvåkinger ender alle i samme funksjon,
`ekte.runner.run_audit()`:

1. **Konfigurasjon.** `ekte/config.py` slår sammen YAML-konfigurasjonen med
   kommandolinjevalgene til `TargetConfig` (mål, valgfri referanse og dommer) og
   `AuditOptions` (testsett, dimensjoner, probestørrelser, utdata). API-nøkler
   oppgitt som `env:VAR` eller `file:/sti` løses opp her.
2. **Kunnskapsbase.** `load_knowledge_base()` laster de medfølgende profilene,
   `--kb-dir`/`EKTE_KB_DIR` og brukerens `kb.db`, og slår opp den **oppgitte**
   modellen (standard er den forespurte) til en profil. En overvåking sender i
   stedet sitt festede øyeblikksbilde.
3. **Klienter.** `make_client()` lager en klient for målet (og referansen) for
   den valgte eller automatisk gjenkjente protokollen. En `RequestRecorder` pakker
   inn hvert kall for ytelsesdelen.
4. **Detektorer.** `select_detectors()` velger de registrerte detektorene for
   testsettet (eller de egendefinerte dimensjonene) og dropper dem som trenger en
   dommer eller en referanse som mangler. De kjøres **etter hverandre**, med
   vilje: samtidige forespørsler ville utløst strupinger og forstyrret
   tidsmålingene (pålitelighets- og ytelsesprobene styrer sin egen avgrensede
   samtidighet). `run_detector()` tar tiden på hver av dem og gjør et krasj om til
   et resultat med status **Feil**, så ett merkelig svar fra et relé aldri avbryter
   revisjonen.
5. **Score.** `scoring.build_dimensions()` og `build_verdict()` gjør
   detektorresultatene om til dimensjonsscorer, samlet score og karakter,
   risikokonklusjonen og sikkerheten i den.
6. **Rapport.** Alt havner i en `AuditReport` (`ekte/models.py`) med sladdet mål,
   øyeblikksbildet av profilen fra kunnskapsbasen, ytelsesdelen og
   probespråkene. Kommandolinjen gjengir og skriver den; nettgrensesnittet
   strømmer den.

`run_audit()` tar et `on_event`-tilbakekall; nettserveren gjør hendelsene
(detektor startet/ferdig med kompakte funn, samlede tidsmålinger per forespørsel)
om til Server-Sent Events for sanntidsvisningen.

### Klienter

`ekte/clients/` har én klient per protokoll — `openai_compatible.py` (Chat
Completions), `anthropic.py` (Messages) og `responses.py` (Responses) — med samme
grensesnitt, bygget på felles HTTP-maskineri i `base.py`. `make_client()` i
`clients/__init__.py` velger én ut fra `--api` eller gjenkjenner den ut fra
basis-URL-en og modellen. Detektorene snakker bare med dette grensesnittet
(`RequestSpec` inn, `CompletionOutcome` ut), så de er uavhengige av protokollen.

Klientene tilpasser også forespørslene til det modellen godtar (`base.py`):
kjøreren fyller `unsupported_params` fra profilen, samplingsparametere som står
der, utelates, og på Chat Completions sendes en oppført `max_tokens` som grensen
`max_completion_tokens`. En 4xx som nevner en slik parameter, legger den til i
settet og gjentar forespørselen én gang tilpasset (det avviste forsøket
registreres med fasen `param_retry`). En probe som vurderer selve avvisningen,
setter `RequestSpec.exact_params`.

### Detektorer og scoreskalaer

En detektor er én selvstendig fil i `ekte/detectors/`: en underklasse av
`Detector` (`base.py`) med en `id`, et `name`, en `dimension`, det første
testsettet den kjører i (`min_suite`), et omtrentlig `cost_hint` for `--dry-run`,
og `async def run(self, ctx) -> DetectorResult`. `@register` legger den til i
registeret; `ekte/detectors/__init__.py` importerer hver modul så registeret er
komplett.

Hver detektor publiserer sin **scoreskala** (`SCALE`, bygget med `scale.py`):
hvert mulige utfall av hver kontroll med poeng, status og alvorlighet. Funn lages
fra skalaen (`SCALE.finding(check, outcome, …)`), så rapporten og atferden ikke
kan være uenige. `Scale` gir gjennomsnittet av kontrollene sine som score;
`DeductionScale` starter på 100 og trekker fra eller setter et tak.
Nettgrensesnittet viser skalaen under **Scoreskala**;
[Metodikken](docs/METHODOLOGY.nb.md) gjengir hver skala. `connectivity.py` er
det kanoniske, korteste eksempelet.

Detektorene deler én hendelsesløkke med alle andre revisjoner i `ekte serve`, så
CPU-tungt arbeid må ikke kjøre på den: en løkke som står fast, forsinker andre
revisjoners forespørsler og blåser opp forsinkelsene de registrerer.
`helpers.build_filler()` bygger fyllteksten i lineær tid og husker de siste
størrelsene, og detektorene for kontekstvindu og prompt-hurtigbuffer kaller den
(og `build_haystack()`) via `asyncio.to_thread`. Tokentellinger kommer fra
`ekte/utils/tokenize.py`, en heuristikk i standardbiblioteket: ekte importerer
ingen tokenizer-bibliotek og laster ikke ned noe under kjøring, så den virker i
begrensede miljøer. Argumentet `tokenizer` til `estimate_tokens()` godtas, men
endrer ikke tellingen, og rapportfeltene `tokens_exact` / `exact_tokenizer`
beholdes for kompatibilitet og er alltid false.

### Score og konklusjon

`ekte/scoring.py` inneholder `DIMENSION_WEIGHTS` og reglene for konklusjonen: en
dimensjonsscore er gjennomsnittet med lik vekt av detektorene, den samlede scoren
det vektede gjennomsnittet av dimensjonene som kjørte, og risikonivået følger
alvorlighetsstigen beskrevet i
[Metodikk → Slik gir ekte score](docs/METHODOLOGY.nb.md#slik-gir-ekte-score). Hver
dimensjon registrerer hvordan den ble beregnet i `DimensionScore.breakdown`, som
mater **Dimension details** i rapportene og radene som kan foldes ut i
**Kontroller per dimensjon** i nettgrensesnittet.

### Kunnskapsbase

`ekte/knowledge/` definerer profilskjemaet (`schema.py`: `ProviderProfile`,
`ModelProfile`, `FingerprintProbe`), laster og slår sammen lagene (`loader.py`:
medfølgende YAML → `EKTE_KB_DIR`/`--kb-dir` → brukerens `kb.db`), lagrer
brukerens oppføringer (`store.py`), kontrollerer og importerer YAML
(`importer.py`), bygger undersøkelsesprompten for eksterne assistenter
(`research.py`) og tar øyeblikksbilde av profilen en kjøring brukte
(`snapshot.py`). Modell-ID-er slås opp eksakt, via aliaser eller etter normalisert
navn, innsnevret av den oppgitte leverandøren. Den omtrentlige reserven tar det
lengste navnet i kunnskapsbasen som påstanden inneholder (en snapshot- eller
dekorert ID), med mindre resten av påstanden nevner et annet nivå eller en annen
variant (`-mini`, `-lite`, `-image`, …); en avkortet påstand slås bare opp når
navnet til én enkelt modell begynner med den, så en tvetydig ID som `gpt-4` ikke
slås opp til noen profil i stedet for et gjettet nivå. Hver rapport registrerer
hvordan ID-en passet.

`load_knowledge_base()` hurtigbufrer sammenslåtte resultater og returnerer som
standard en dyp kopi, så kallerne kan endre det de får. Kallere som bare leser
(nettgrensesnittets lister og katalog, oppslag av en modell), sender
`copy=False` og får den delte bufrede instansen, som de ikke må endre.

Releer er også endepunkter: `relays.py` gjør en leverandørs `base_url_hints` om
til brukbare basis-URL-er (`GET /api/kb` → `base_urls`) og lagrer et relé fra
nettgrensesnittet som en leverandøroppføring i `kb.db` (`origin = relay`: et
`display_name` og én basis-URL, ingen modeller; ingen skjemaendring).

### Promptbibliotek

All tekst ekte sender til et LLM-API — chatprober, dommerens prompt,
verktøyskjemaer, inndata for embedding / rerank / bilde / lyd — ligger i
`ekte/prompts/en.json` og leses med `ekte.prompts.text()` / `get()`. `{{name}}`
markerer en verdi som fylles inn under kjøring. Probespråket er fast satt til
engelsk (`PROBE_LANG`), uavhengig av grensesnittspråket, fordi svarkontroller og
tokenanslag er kalibrert til akkurat disse tekstene. Prober der språket *er*
målingen (f.eks. flyt i kinesisk, tokenizer eller selvidentifikasjon for modeller
med kinesisk opphav), ligger med sine forventede svar i kunnskapsbasen og
oppgir `prompt_lang` og en `language_bound`-begrunnelse. Kjøreren registrerer
språkene som ble brukt, i `prompt_languages`.

### Rapporter

`ekte/report/render.py` gjengir en `AuditReport` som JSON, kompakt agent-JSON,
Markdown og HTML; `dimensions.py` og `performance.py` gjengir **Dimension
details** og ytelsesdelen; `pdf.py` setter PDF-en med ReportLab fra de samme
dataene og hjelperne (ren Python; bare standard PDF-skrifter, med CID-skriften
STSong-Light for kinesisk, så ingenting bygges inn; laster aldri eksterne
ressurser), og kommandolinjen og nettgrensesnittet deler den; `writer.py`
skriver filene. All tekst som reléet styrer, sladdes og escapes (HTML / Markdown)
før utdata. Nettgrensesnittets `POST /api/report/export` gjenbruker disse
gjengiverne for raden **Last ned rapport**, med teksten for mennesker oversatt til
grensesnittspråket.

### Overflater

**Overflaten** (surface) er typen endepunkt som revideres: `chat` (standard),
`embedding` eller `rerank` (`ekte.config.SURFACES`; senere bilde, TTS). Den er en
akse nummer to ved siden av testsettet, båret av `AuditOptions.surface`,
`AuditReport.surface` og en `surface`-kolonne som kan være null, i `history.db` og
`watches.db` (`NULL` og et manglende JSON-felt betyr `chat`; ingen migrering).

- Detektorer oppgir `surface: ClassVar[str]`; `select_detectors` filtrerer på den
  før nivået til testsettet. Detektorene for embedding og rerank gjenbruker de
  eksisterende dimensjonene.
- Scorevekter og settene med profil-, kjerne- og infrastrukturdimensjoner er per
  overflate (`scoring.SURFACE_WEIGHTS`); chat beholder sine verdier.
- Opptakeren merker embedding-kall med `op="embed"` og rerank-kall med
  `op="rerank"` (`ekte.config.SURFACE_OPS`); funksjonene i `perf/summary.py` tar
  en `op`-parameter (standard `complete`).
- `embed_audit.run_embedding_audit()` og `run_rerank_audit()` (brukt av
  `ekte embed` / `ekte rerank`) kjører kjøreren
  med `surface="embedding"` eller `"rerank"`, sender forrige lagrede kjøring av
  samme overflate som `previous_report` (drift) og lagrer rapporten med mindre de
  blir bedt om å la være (`--no-save`).
- Rerank-detektorer: `rerank.connectivity`, `rerank.known_answer` (CAPABILITY),
  `rerank.identity` og `rerank.drift` (MODEL_IDENTITY), `rerank.determinism`
  (RELIABILITY) og `performance.rerank`. Vekter: MODEL_IDENTITY 30,
  CAPABILITY 30, PERFORMANCE 20, RELIABILITY 10, CONNECTIVITY 10.
- Overvåkinger: en overvåkings `surface` og `embedding_dimensions` (0 = fra
  kunnskapsbasen) mater `AuditOptions` i `_run_one_watch_inner`; en overvåking av
  embedding eller rerank leser sin referanse for drift med
  `history.latest_for(..., surface=...)` før revisjonen og sammenligner varsler
  bare med kjøringer av samme overflate. Overflaten settes ved opprettelse
  (`POST /api/watches`, `/api/watches/from-history/{id}`, som også tar
  `embedding_dimensions`) og kan ikke endres med `PATCH`; `PATCH` endrer en
  embedding-overvåkings `embedding_dimensions` (kortet i v2 Overvåking redigerer
  den direkte).

### Frittstående revisorer

Bilde/lyd (`media_audit.py`) er ikke overflater ennå, så de har sine egne små
revisorer med sin egen konklusjons-dict i stedet for detektorløpet. De deler
klientenes HTTP-innstillinger, kunnskapsbasen (egne dimensjoner, bildestørrelser,
stemmer) og promptbiblioteket. All dekoding (bildehoder, WAV) bruker bare
standardbiblioteket.

### Nettserver

`ekte/web/server.py` er en FastAPI-app som lages av `create_app()`:

- **Sider.** Nettgrensesnittet (`/v2/`, `/v2/history`, `/v2/watches`,
  `/v2/analytics`, `/v2/kb`, `/v2/accessibility`) er statisk HTML. Det finnes
  ingen Verktøy-side: revisjoner av embedding og rerank starter på
  revisjonssiden via velgeren for type endepunkt (`/v2/?surface=embedding|rerank`),
  og `/v2/tools` leverer en liten side som sender gamle lenker videre dit
  (`#rerank` velger rerank, `?rerun=` sendes videre). Adressene til det fjernede
  klassiske grensesnittet (`/`, `/history`, `/watches`, `/tools`, `/console`)
  videresender (308) til v2-sidene sine og beholder spørrestrengen.
- **API.** `/api/jobs…` kjører revisjoner (nedenfor); `/api/models` viser et
  relés modeller; `/api/report/export` gjengir en rapport; `/api/history…`,
  `/api/watches…`, `/api/kb…` og `/api/analytics…` står bak de andre sidene. Alle er interne; den offentlige delmengden er [HTTP API v1](#http-api-v1).
- **Releer.** `POST /api/kb/relays` lagrer et relé `{name, base_url}` (400 for
  ugyldig inndata, 409 når navnet eller URL-en allerede er kjent).
- **Analyse.** `GET /api/analytics/options` (releer, modeller, testsett,
  strømmemoduser, API-er og datoområdet i historikken), `/api/analytics/summary`
  (nøkkeltall for `from`–`to` mot forrige område av samme lengde),
  `/api/analytics/series` (`metric` per `group=relay|model|relay_model`, opptil 4
  `keys`, i intervaller `bucket=hour|day|week|dow_hour` i seerens `tz` eller
  `tz_offset`; `dow_hour` tar også `block` (timer per rad) og
  `fold=week|4weeks|month_week`, som faller tilbake til `week` til kjøringene
  dekker 90 eller 180 dager) og `/api/analytics/leaderboard` (`model=` for
  releene, eller `relay=` for modellene). Alle tar filtrene `from`, `to`,
  `suite`, `stream_mode`, `api`, `source=all|manual|monitor`, `relay` og `model`.
  `ekte/web/analytics.py` beregner alt i Python fra `history.analytics_runs()`:
  ID-er for måltall kommer fra en fast tillatelsesliste, releer grupperes etter
  oppføring i kunnskapsbasen når spørringen kjører, en verdi en kjøring ikke
  målte, utelates (hver verdi har sin `n` og `coverage`), og intervaller med
  færre enn `MIN_RUNS` (3) kjøringer flagges `low_n`. En ugyldig parameter gir
  400; svarene har `Cache-Control: no-store`.
- **Analysepaneler.** `/api/analytics/breakdown` (opptil 8 `metrics` per
  `group=relay|model|relay_model|all` over området), `/api/analytics/errors`
  (målets fullføringskall etter utfallsklasse
  `success|client_4xx|rate_limited|server_5xx|timeout|network|other`, per
  `group=relay|model` og per `bucket`, telt i SQL av
  `history.analytics_request_classes()` uten å laste forespørselsrader;
  tidspunktet for et kall er kjøringens start pluss forskyvningen, til minuttet;
  `covered` = kjøringer som har forespørselsposter) og `/api/analytics/integrity`
  (antall bestått / advarsel / ikke bestått for detektorene for identitet,
  egenskaper, syn, strømming, protokoll, integritet, injisert prompt og tilkobling
  per relé × modell, andelen modellavvik og medianen av effektivt / oppgitt
  kontekstvindu). `/api/analytics/series` tar også `group=all`. Samme filtre og
  feil som over.
- **Revisjoner i bakgrunnen.** `jobs.py` kjører hver revisjon som en jobb serveren
  eier. `POST /api/jobs` setter en i kø, `GET /api/jobs` viser jobber i kø, under
  kjøring og nylig ferdige (pluss overvåkinger som kjører) med fremdrift,
  `GET /api/jobs/{id}/events` spiller av jobbens hendelseslogg og følger den så i
  sanntid over SSE, og `POST /api/jobs/{id}/cancel` stopper den.
  Nettgrensesnittet bruker disse, så en revisjon overlever siden. En reléport lar én revisjon (eller overvåkingskjøring) om gangen bruke
  et relé, med vertsnavnet som nøkkel og alle loopback-adresser som én vert, og
  høyst `EKTE_MAX_PARALLEL_AUDITS` (standard 4) kjører samtidig; de som venter,
  betjenes i den rekkefølgen de kom.
- **Planlegger for overvåkinger.** Appens livsløp starter en løkke i bakgrunnen
  som starter hver forfalt overvåking som sin egen oppgave, så overvåkinger på
  ulike releer reviderer samtidig; reléporten gjelder fortsatt, så overvåkinger
  kan fylle plassene i `EKTE_MAX_PARALLEL_AUDITS`, og en manuell revisjon kan havne
  i kø bak dem. En kjørings `last_run_ts` er øyeblikket revisjonen starter (etter
  å ha ventet på reléet). Hver kjøring lagres i historikken; kontrollen av
  forverring sammenligner den med den siste lagrede kjøringen av samme mål og
  modell (`history.latest_for()`, ett indeksert oppslag) og sender
  webhook-varslene (`ekte/notify.py`) samtidig når en terskel krysses eller ved
  forverring. `POST /api/watches/{id}/run` svarer 409 mens planleggeren nettopp har
  startet den overvåkingen; en nullstilling av hovednøkkelen avbryter planlagte
  kjøringer som ikke har startet ennå, og avslutning avbryter kjøringene som
  pågår.
- **Komprimering og hurtigbuffer.** `caching.py` gzipper svar på 1 KiB eller mer
  (unntatt Server-Sent Events) for klienter som godtar det (`gzip;q=0` avslår).
  Sider og `/locales.js` gzippes én gang når de bygges, og leveres
  forhåndskomprimert med `Content-Encoding: gzip`, `Vary: Accept-Encoding` og en
  egen ETag som slutter på `-gz`; sider leveres via `html_page(page,
  request.scope)`, så de får den veien og svarer på betingede forespørsler med
  304. Lokale skript- og stilark-URL-er i sidene har en `?v=<innholdshash>` og
  hurtigbufres som uforanderlige.
- **Sikkerhet.** `security.py` bestemmer bindingsadressen (bare loopback, unntatt
  i en gjenkjent container med `EKTE_CONTAINER=1`) og installerer
  `LocalOnlyMiddleware`: en tillatelsesliste for Host mot DNS-rebinding,
  Origin- og `Sec-Fetch-Site`-kontroller mot CSRF, bare JSON i
  forespørselsbodyer, og hoder mot innramming / sniffing / referrer.
  Grensesnittet har ingen innlogging, med vilje.

### HTTP API v1

Den offentlige delen av HTTP-API-et ligger under `/api/v1/` og følger [stabilitetspolicyen](docs/STABILITY.md#surface-http-api): Den endres bare ukompatibelt i en hovedversjon, etter en utfasingsperiode. Alle andre stier under `/api/` er interne og kan endres i hvilken som helst utgivelse. Interne svar har `X-Ekte-API: internal`, v1-svar `X-Ekte-API: v1`. Nettgrensesnittet bruker de interne stiene.

| Endepunkt | Forespørsel | Svar |
|---|---|---|
| `POST /api/v1/jobs` | JSON-kropp med `base_url`, `model` og eventuelt `api_key`, `claimed_model`, `suite`, `surface`, `dimensions`, `baseline` | 200 og jobben; 400 ved ugyldig inndata |
| `GET /api/v1/jobs/{id}` | ingen | 200 og jobben; 404 for ukjent id |
| `GET /api/v1/jobs/{id}/events` | ingen | 200 og `text/event-stream`: jobbens hendelser så langt, så direkte, til og med `done`; 404 for ukjent id |
| `GET /api/v1/history` | valgfritt `limit` (1–500, standard 50) og `perf` | 200 og en JSON-liste med sammendrag av kjøringer, nyeste først |
| `GET /api/v1/history/{id}` | ingen | 200 og den lagrede rapporten som den er; 404 for ukjent id |

En jobb har `id`, `status` (`queued`, `running`, `done`, `error` eller `cancelled`), fremdriftsfelt, `report_id` når rapporten er lagret, og `error`; API-nøkkelen returneres aldri. Hver hendelse er en SSE-linje `data: {JSON}` med en `type`; hendelsen `report` bærer rapporten og dens `report_id`, og `done` er alltid den siste. Klienter ignorerer hendelsestyper og felt de ikke kjenner.

Hver feil er JSON med ett enkelt felt, `error`, med en lesbar melding, og én av disse statuskodene: 400 (ugyldig forespørsel), 404 (ikke funnet), 403 (forespørsel på tvers av nettsteder eller opprinnelser avvist), 415 (kroppen er ikke JSON), 421 (ukjent vert).

```json
{"error": "not found"}
```

- **Bare lokalt.** Nettserverens beskyttelser gjelder for `/api/v1/` som for alle stier: binding til loopback som standard, vertskontrollen, avvisning av skriving på tvers av nettsteder og kun JSON i kroppen. De svarer i samme feilformat.

### Nettgrensesnittets frontend

Frontenden er ren HTML, CSS og nettleser-JavaScript uten moduler eller
byggetrinn. Sidene ligger i `ekte/web/static/v2/` og deler ett sidehode
(`nav.js`), rapportgjengiveren (`report.js`), temabryteren (`theme.js`) og
stilene (`tokens.css`, `ekte.css`, `fields.css`, `report.css`, `perf.css`).
Delte skript leveres fra roten: `lang.js` (språkbytte), `locales.js`
(oversettelsesdata), `i18n.js` (oversettelse av funn), `icons.js` (med
ekte-logoen), `secretfield.js` og `perf.js` (ytelsesdiagrammer).
Hver farge i v2-grensesnittet, i begge temaer, er et token i `v2/tokens.css`
(skrevet én gang som `light-dark(<light>, <dark>)`); alle andre v2-stiler, sider
og skript bruker bare `var(--…)`, aldri en bokstavelig farge.

Hver v2-side unntatt Tilgjengelighet har én **sidemelding** rett under
toppfeltet (`<div class="znote" id="note">`, tegnet av `v2/notice.js`, stilsatt
av `.znote` i `ekte.css`): `EkteNotice.show(el, {level, title, detail, items,
actions})` der nivået `info`, `success`, `warning` eller `critical` bestemmer
farge, ramme og ikon (critical er `role="alert"`, de andre `role="status"`; å vise
samme melding igjen endrer ingenting). Siden velger den viktigste meldingen og
viser de andre i `items`. Revisjon: serveren kan ikke nås / revisjoner kjører /
den nyeste lagrede kjøringen / kjører lokalt; Historikk: historikken kan ikke
leses / overvåkingskjøringer på pause (hovednøkkelen låst) eller eldre kjøringer
som fortsatt behandles / antall kjøringer; Analyse: dataene kan ikke leses /
kjøringer som ikke er med i diagrammene ennå eller har et anslått starttidspunkt
/ hva den bygger på; Kunnskap: lastefeil / oppføringer som ble hoppet over eller
ignoreres / elementer som er slått av / komplett. Overvåking beholder
hovednøkkellinjen sin (`masterkey.js`), som ser lik ut og står på samme sted. Tall
for hele historikken kommer fra `GET /api/history/status` (`history.status()`:
antall kjøringer, eldste og nyeste kjøring, rader som analysens etterfylling ikke
har behandlet, kjøringer med anslått starttidspunkt).

v2-siden **Revisjon** setter opp releer med `v2/relaycfg.js`: velg
relé/leverandør → basis-URL → reléets modeller (`/api/models`, ved endring,
hurtigbufret per URL/nøkkel/protokoll) → oppgitt modell fra kunnskapsbasen
(`/api/kb/resolve` forhåndsvelger den) → avledet oppgitt leverandør, pluss
**Lagre i kunnskapsbasen** (`POST /api/kb/relays`). De rene hjelperne testes under
node.

v2-siden **Analyse** (`v2/analytics.html`) leser bare `/api/analytics/*`
(`options` viser også parene relé × modell, `relay_models`, for serievelgeren).
Den har én `<section class="card panel">` per panel under én filterlinje, så nye
paneler kan settes inn; filtre og visning ligger i URL-fragmentet
(`#range=30&metric=score&…`) og i `localStorage`. Diagrammene kommer fra
`v2/charts.js` (`EkteCharts.timeChart`: håndtegnet innebygd SVG med medianlinje,
båndet p25–p75, hull for tomme intervaller, blekere markører for `low_n`-intervaller,
merknadslinjer og et verktøytips ved pekeren; `fmt` / `fmtDelta` formaterer verdier
etter enhet) og `v2/charts.css` (fire validerte seriefarger per tema, som også
skilles fra hverandre av markørformen). Hvert diagram gjengis også som datatabell.

Hvert panel er selvstendig: et `PANELS`-register i sideskriptet oppgir
seksjons-ID-en, `load()` (hent med gjeldende filtre og visning, gjengi så) og
`render()` (tegn på nytt fra de lastede dataene, f.eks. ved bytte av språk), så
paneler kan flyttes om uten å berøre hverandre. `EkteCharts.heatmap` tegner
rutenettet ukedag × time (sekvensiell skala med fem trinn i én fargetone per tema,
skraverte celler for `low_n`, tomme celler med omriss), `EkteCharts.stackBars` de
stablede feilstolpene, og `timeChart` tar en `ref`-linje (faktureringsforhold
100 %). `EkteCharts.donut` (en ring av deler av én helhet med en HTML-figur i
midten) og `EkteCharts.meter` (en tynn stolpe av deler) tegner kortet Dekning i
tilgjengelighetsrapporten; `k-*`-fargene deres (hvem som avgjør et trinn: blå
testsettet, fiolett en person) kommer fra `tokens.css`. `v2/chartmotion.js`
(`EkteMotion.enter`) tegner en smultring med klokken og lar målere vokse fra
venstre, som alle andre diagrammer, bare når nye data kommer, og aldri ved
redusert bevegelse eller sidehodets «Bevegelse av».

Sidehodet og filterpanelet står over fem faner på siden (`v2/tabs.js`, som på
Kunnskap): hver `PANELS`-oppføring oppgir sin `tab`, og bare panelene i fanen som
vises, lastes; en filterendring laster den fanen på nytt og merker de andre som
utdaterte (`activate()` laster dem når de vises). `tabs.js` tar
`writeHash: false` her, fordi siden selv skriver hele visningen inn i fragmentet —
`#tab=trends&range=30&suite=…&metric=…` (`stateQuery()`), som **Kopier lenke til
denne visningen** kopierer (et valgt skrivebeskyttet felt der utklipps-API-et
mangler eller nekter); et fragment uten `tab` åpner Oversikt, og en innlimt lenke
(`hashchange`) leser visningen på nytt. Filterpanelet som kan foldes sammen, er
`v2/filterpanel.js` + `v2/filterpanel.css`, delt med Historikk, Overvåking og
Kunnskap: `EkteFilterPanel.create(section, {label, title, storeKey, open,
onReset})` returnerer `render({body, foot, count, summary})`,
`sync({count, summary})`, `setOpen()` og `focusStart()`; siden eier filtrene og
feltene sine, panelet bryteren med merket for aktive filtre, sammendraget på én
linje som vises når det er lukket, den huskede åpne-tilstanden og **Nullstill
filtre**.

**Konvensjon for oversettelse.** Den kinesiske teksten som står i HTML-en, er
originalen og røres ikke; hvert element har sin engelske tekst i `data-en` (og
`data-en-placeholder`, `data-en-title`, `data-en-aria-label`). Den engelske
teksten er oppslagsnøkkelen for alle andre språk. Skriptene bruker `T(zh, en)`
for dynamisk tekst og `EKTE_LANG.server(text)` for tekst som kommer fra bakenden
(detektornavn, anbefalinger, setninger i konklusjonen).

### Lokale data

`ekte/datadir.py` eier `$EKTE_DATA_DIR` (standard `~/.ekte`), opprettet med
`0700`, med SQLite-filer med `0600`: `history.db` (`web/history.py`),
`watches.db` (`web/watches.py`; overvåkingenes API-nøkler bare hvis brukeren
valgte å lagre dem, kryptert) og `kb.db` (`knowledge/store.py`). Hvert kall åpner
en kortlivet tilkobling, så lagrene er trygge i FastAPIs trådpool. Det globale
valget `--data-dir` (også på `ekte serve`) setter bare `EKTE_DATA_DIR` til den
absolutte stien, og `ekte data-dir` skriver ut den oppslåtte mappen. En mappe som
allerede finnes, beholder modusen sin; bare standarden `~/.ekte` strammes inn til
`0700`. Historikkrader er indeksert etter mål og modell (`idx_history_target`),
som `history.latest_for()` bruker for å finne en overvåkings forrige kjøring.

Fra skjemaversjon 2 (`PRAGMA user_version`) har `history.db` også
analysetabellene, definert i `web/analytics_store.py`: `history_metrics` (én rad
med uttrukne måltall per kjøring: starttidspunkt, rater, persentiler for
forsinkelse/TTFT/dekoding, faktureringsforhold, antall funn med mer; NULL der
kjøringen ikke målte en verdi), `history_dimensions` (dimensjons- og
detektorscorer) og `history_requests` (kjøringens forespørselsposter, mål og
referanse, i listerekkefølge). En rapports `performance.requests` tas bare vare på
der: `save()` tar dem ut av `report_json` (`requests_split` merker raden), og
`get()` / `latest_for()` setter dem inn igjen, så en rapport leses tilbake
identisk med den som ble lagret; det kolonnene ikke kan gjenskape nøyaktig, går
inn i JSON-kolonnen `extra`. `extract_metrics()` er ren og versjonert
(`EXTRACT_VERSION`). Etter migreringen flytter en etterfylling i porsjoner (én
kort transaksjon per porsjon, idempotent) eldre raders poster og trekker ut
måltallene deres, og trekker ut på nytt rader skrevet av en eldre
`EXTRACT_VERSION`; `history.backfill_analytics()` kjører den igjen ved behov. En
kjørings starttidspunkt er rapportens `started_at`; rapporter fra før det feltet
får `generated_at` minus spennet av forespørselspostene sine
(`started_at_estimated` = 1).

Hvor overvåkingenes API-nøkler oppbevares, er brukerens valg
(`watches.get_key_storage()`, en `secret_meta`-rad): `memory`, standarden, lagrer
ingen — kolonnen `api_key` har markøren `mem:`, og nøkkelen lever i
`watches._memory_keys` til prosessen stopper (en omstart etterlater raden
`key_missing`, som planleggeren behandler som en låst nøkkel: kjøringen venter,
ikke noe varsel); `encrypted` lagrer dem som nedenfor. Uten noen rad ennå starter
et lager som allerede har krypterte nøkler eller en kontrollverdi, eller en satt
`EKTE_SECRET_KEY` / eldre `secret.key`, i `encrypted`; valget registreres ved
oppstart. `Vault.set_storage()` (`POST /api/secret/storage`) bytter og flytter
nøklene i én transaksjon (`keys_to_memory()` sletter de krypterte og
kontrollverdien og renser filen; `keys_to_store()` forsegler dem som holdes). En
forespørsel kan sende `key_storage: "memory"` for å holde nøkkelen sin utenfor
databasen uansett innstilling; ingenting kan tvinge fram lagring.

Lagrede API-nøkler krypteres av `ekte/secretbox.py` (Fernet, lagret som
`enc:v1:…`; `env:`/`file:`-referanser blir stående som de er). Selve
hovednøkkelen lagres aldri: `web/masterkey.py` (`Vault`, delt av serveren og
`ekte secret`) holder den i serverens minne når den kommer fra
`EKTE_SECRET_KEY`, en eldre `secret.key` eller brukeren på Overvåking-siden, og
`watches.db` tar bare vare på en kontrollverdi (`secret_meta`) som avviser en feil
nøkkel. En ny nøkkel krypterer hver lagret nøkkel på nytt og skriver
kontrollverdien på nytt i én transaksjon. Nøkkelen lever i minnet til én prosess,
så kjør én server per datamappe.

`ekte/legacy.py` holder installasjoner fra før navnebyttet i gang: hver
`EKTE_*`-innstilling leses via `legacy.getenv`, som faller tilbake til det gamle
`ZING_*`-navnet (nevnt én gang på stderr), og `datadir.data_dir()` kopierer
`~/.zing` til `~/.ekte` én gang når bare den gamle mappen finnes (SQLite-filer via
backup-API-et, til en midlertidig søskenmappe som gis nytt navn på plass).
`~/.zing` endres eller slettes aldri. `lang.js` kopierer nettleserens
`zing.*`-innstillinger til `ekte.*` på samme måte, og serveren leser fortsatt
informasjonskapslene `zing_lang` / `zing_ui` til `ekte_*`-kapslene finnes.

## Bidra

### Pull requests

- Hold `pytest`, `ruff check ekte tests` og `mypy ekte` grønne (CI kjører alle tre
  på Python 3.11–3.14).
- Beskriv relétrikset eller den falske positiven en endring tar for seg.
- Oppdater `CHANGELOG.md` under `[Unreleased]`.
- Oppdater dokumentasjonen endringen berører — README, denne veiledningen,
  Metodikken — på **alle språk** (se [Dokumentasjon](#dokumentasjon)).

Ved å bidra godtar du at bidragene dine lisensieres under prosjektets lisens
[Apache-2.0](LICENSE).

### Legge til en detektor

1. Opprett `ekte/detectors/<name>.py` og importer den i
   `ekte/detectors/__init__.py`.
2. Definer dens `SCALE` (`Scale` eller `DeductionScale` fra `scale.py`) med hvert
   utfall av hver kontroll, og lag funn bare via den.
3. Lag en underklasse av `Detector`; sett `id`, `name`, `dimension`, `min_suite`
   og `cost_hint`; sett `requires_judge = True` eller `requires_baseline = True`
   hvis den trenger en av dem, eller overstyr `applies()` for annen avgrensning.
   Dekorer den med `@register`.
4. Implementer `async def run(self, ctx) -> DetectorResult`, med utgangspunkt i
   `self.new_result(scoring=SCALE.scoring())`. Send forespørsler via `ctx.client`
   og ta hver prompt fra `ekte/prompts/en.json`.
5. Legg til atferdstester for både den flaggede og den rene veien, med det falske
   reléet i `tests/conftest.py`.
6. Oversett nye titler og sammendrag for funn (se [Oversettelser](#oversettelser))
   og dokumenter detektoren og skalaen i hver
   [Metodikk](docs/METHODOLOGY.nb.md)-fil.

### Redigere kunnskapsbasen

Profilene ligger i `ekte/knowledge/data/<provider>.yaml`, én fil per
leverandør. Hver modell har sitt eget kontekstvindu, maks utdata,
kunnskapsgrense, tokenizer, modaliteter, egenskapsflagg, parametere som ikke
støttes, identitetsnøkkelord og fingeravtrykk (se `ekte/knowledge/schema.py`).
Når du endrer et numerisk felt, **oppgi en autoritativ kilde** (leverandørens
offisielle modellkort, prisliste eller dokumentasjon) i pull requesten: en feil
verdi gir falske positiver mot ærlige releer. `ekte kb-import --check <file>`
kjører de samme kontrollene som brukerimporten (skjema, grenser, utrygge regulære
uttrykk, prompter, kolliderende ID-er).

`fingerprints` på leverandørnivå kjører på hver modell hos leverandøren. En probe
der forventningen bare gjelder for noen modeller (en kunnskapsgrense, en
kontroll av faktakunnskap på Pro-nivå, en resonneringsfelle), hører hjemme i de
modellenes egne `fingerprints`, ellers regnes et sannferdig svar fra en annen
modell som et avvik.

Fyll alltid `identity_keywords` med leverandør- og modellfamilieordene modellen
bruker om seg selv. Identitetskontrollen regner også leverandørnøkkelen,
visningsnavnet og modell-ID-en som det ekte merket, utvidet med leverandørens
andre navn i `VENDOR_BRANDS` (`ekte/knowledge/identity.py`, som også er
detektorens liste over konkurrerende merker); importen fyller tomme nøkkelord fra
disse navnene med en advarsel. Legg til merkeordene til en ny leverandør der som
én gruppe.

### Endre probeprompter

Probetekster er kalibreringsdata. Å endre en i `ekte/prompts/en.json` kan endre
svarkontroller, tokenanslag og dermed konklusjoner, så juster detektoren og
testene dens samtidig, og nevn endringen i CHANGELOG. La aldri en probe følge
grensesnittspråket.

### Oversettelser

Grensesnittet og webhook-varslene deler ett sett med oversettelser i
`ekte/i18n/locales/<code>.json`:

- `meta` — kode, språkets eget navn for nedtrekkslisten, `html`-lang,
  datolokale og plass i menyen;
- `strings` — engelsk tekst → oversettelse (`en.json` er identitetskartet og den
  kanoniske listen over strenger som kan oversettes);
- `findings` — ID for funn → `[tittel, sammendragsmal]` (`zh.json` har den
  opprinnelige kinesiske katalogen).

Funksjoner kan levere strengene sine som fragmenter,
`ekte/i18n/locales/fragments/<feature>/<code>.json` med `{"strings": {…}}`, som
slås sammen med språket ved lasting. `/locales.js` sender bare det valgte språket
(`?lang=<code>` eller informasjonskapselen `ekte_lang` som `lang.js` setter; alle
språk uten noen av dem), bygget og gzippet én gang per variant og revalidert med
`ETag`; et bytte laster det nye språket ved behov.

- **Grensesnittekst:** skriv det kinesiske i HTML-en og det engelske i `data-en`
  (eller bruk `T(zh, en)`), legg så den engelske nøkkelen til i `en.json` eller et
  fragment og oversettelsen til hvert annet språk.
- **Nytt språk:** legg til `ekte/i18n/locales/<code>.json` (kopier `de.json`) og
  én fil per fragment; nedtrekkslisten, sidene, varslene og `--alert-lang` plukker
  det opp. Norsk (`nb.json`, bokmål) ble lagt til på denne måten.
- `tests/test_web_locales.py` feiler til hver grensesnittstreng og hvert funn er
  oversatt med plassholdere og markup intakt.

**Ordbruk.** Et begrep har én oversettelse per språk. Gjenbruk ordene
grensesnittet allerede bruker (sidenavn, dimensjonsnavn, risikoetiketter,
knappetekster) i nye strenger og i dokumentasjonen. På norsk: *relay* er
«relé», *audit* «revisjon», *monitor* «overvåking», *finding* «funn», *check*
«kontroll», *baseline* «referanse», *bait-and-switch* «falsk vare».

### Dokumentasjon

Brukerdokumentasjonen finnes på åtte språk — engelsk, kinesisk (`zh-CN`), fransk,
spansk, portugisisk, italiensk, tysk og norsk (bokmål, `nb`):

| Fil | Målgruppe |
|---|---|
| `README.md`, `README.<lang>.md` | Brukere: hva ekte gjør, installasjon, bruk av kommandolinjen og nettgrensesnittet |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Bidragsytere: arkitektur, oppsett, bidrag, Docker, utgivelser |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Alle: hver kontroll, scoreskalaen og forbeholdene |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Referansesider (engelsk) |

De engelske filene er referansen. Når du endrer en, endrer du de andre i samme
pull request, og bruker grensesnittets egne ord på hvert språk (slå opp begrepet
i `ekte/i18n/locales/`). METHODOLOGY-filene siterer scoreskalaene med ordene
grensesnittet viser under **Scoreskala**.

## Testing

```bash
pytest                       # alt
pytest tests/test_billing.py # én modul
pytest -k streaming          # etter nøkkelord
pytest -n auto               # parallelt, én arbeider per CPU (pytest-xdist)
```

- `tests/conftest.py` leverer `MockServer`, et OpenAI-kompatibelt endepunkt på
  `httpx.MockTransport` med brytere for hvert avvik ekte jakter på (levert modell,
  selvidentitet, avkorting av kontekst, forfalsket strømming, manglende eller
  oppblåst usage, verktøykall, JSON-modus, …). Hver bryter er som standard et
  ærlig relé.
- Anthropic- og Responses-klientene har egne tester (`test_anthropic.py`,
  `test_responses.py`); nettserveren testes via FastAPIs testklient
  (`test_web*.py`), også beskyttelsene som holder den lokal
  (`test_web_security.py`).
- Nettleserskriptene (`lang.js`, `v2/relaycfg.js`, `perf.js`, `secretfield.js`,
  `v2/report.js`, språkfilene) evalueres under `node` i `test_web_*_js.py` og
  `test_web_locales.py`; de hoppes over uten Node.js.
- Ingen test får nå nettverket.
- `test_cli_startup.py` holder kommandolinjen rask å starte: å importere
  `ekte.cli` må ikke laste HTTP-klientene, kjøreren, kunnskapslasteren,
  rapportgjengiverne (ReportLab) eller nettserveren. Importer dem inne i
  kommandoen som trenger dem.
- `test_filler_perf.py` låser fyllteksten byte for byte og feiler når
  kontekstvindu-proben får hendelsesløkken til å stå fast.
- `tests/a11y/` kontrollerer nettgrensesnitt v2 mot BITV 2.0 / EN 301 549 /
  WCAG 2.1 AA i en ekte nettleser (Playwright + axe-core), på hvert
  grensesnittspråk og i begge temaer: `pip install -e '.[web,a11y]' && playwright
  install chromium`, deretter `pytest -m a11y`. Uten Playwright hoppes mappen
  over. Hva som er automatisert, og hva som fortsatt trenger en manuell
  BITV-gjennomgang, står i [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md).
- `EKTE_A11Y_PAGES=history,kb` kjører bare a11y-testene for de sidene (pluss
  kontrollene som spenner over alle sider); `python -m tests.a11y.affected --base
  origin/main --head HEAD` skriver ut sidene en endring berører. Begge bruker én
  kobling, `tests/a11y/pages.py`: en ny side legges til i `PAGES` og `RULES`
  ([tests/a11y/README.md](tests/a11y/README.md)).

## Docker

`Dockerfile` bygger et image av nettgrensesnittet (Python 3.12 slim med tillegget
`web`; PDF-rapporter trenger ingen systempakker). Det kjører som en bruker uten
privilegier med datamappen i `/data`.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# åpne http://localhost:8000
```

**Publiser alltid på `127.0.0.1`.** En naken `-p 8000:8000` publiserer
grensesnittet — og hver API-nøkkel som skrives inn i det eller lagres i en
overvåking — til nettverket ditt. Inne i containeren må serveren lytte på alle
grensesnitt; det er bare tillatt når `EKTE_CONTAINER=1` er satt (imaget setter
den) *og* en container-kjøretid gjenkjennes.

| Variabel | Standard | Formål |
|---|---|---|
| `EKTE_CONTAINER` | ikke satt (`1` i imaget) | Tillater binding utenom loopback i en gjenkjent container |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` i imaget) | Bindingsadresse; `--host` vinner |
| `EKTE_PORT` | `8000` | Port; `--port` vinner |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` i imaget) | Historikk, overvåkinger (nøklene deres kryptert) og dine oppføringer i kunnskapsbasen; monter et volum her. `--data-dir` vinner |
| `EKTE_SECRET_KEY` | ikke satt | Hovednøkkelen for overvåkingenes lagrede API-nøkler (en nøkkel, eller `file:/run/secrets/…` / `env:VAR`); er den ikke satt, ber Overvåking-siden om den etter hver start. Lagres aldri i `EKTE_DATA_DIR` |
| `EKTE_KB_DIR` | ikke satt | Ekstra YAML-mappe for kunnskapsbasen, f.eks. `-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb` |
| `EKTE_NO_USER_KB` | ikke satt | `1` ignorerer dine egne oppføringer i kunnskapsbasen (`kb.db`) |
| `EKTE_ALLOWED_HOSTS` | ikke satt | Ekstra vertsnavn grensesnittet svarer på, kommaseparert |

[docs/DOCKER.md](docs/DOCKER.md) er den fullstendige referansen, også om hva som
beskytter grensesnittet.

## Kontinuerlig integrasjon

| Arbeidsflyt | Kjører | Gjør |
|---|---|---|
| `.github/workflows/ci.yml` | push og pull request til `main` (og integrasjonsgrenene `a11y/integration`, `perf/integration`); hver natt og manuelt (bare tilgjengelighet) | `ruff`, `mypy` og `pytest` på Python 3.11–3.14 med tilleggene `dev` og `web`; bygger wheel og sdist og kontrollerer at wheelen installeres og laster kunnskapsbasen; kjører tilgjengelighetstestene (til informasjon, får aldri kjøringen til å feile) og laster opp funnene: hver side ved push, nattlige og manuelle kjøringer (med BITV-samsvarsrapporten), ved pull requests bare sidene endringen berører (ingen ved rene dokumentasjonsendringer) — unntatt pull requests inn i `perf/integration`, der de trege nettlesertestene hoppes over (de kjører ved push til den grenen og ved dens pull request inn i `main`) |
| `.github/workflows/release.yml` | en `v*`-tagg | bygger, kjører `twine check` og publiserer til PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | daglig tidsplan, manuelt | eksempel på en planlagt relérevisjon med handlingen |

Selve den sammensatte handlingen er `action.yml`, dokumentert i
[docs/CI.md](docs/CI.md).

### Tredjepartsfiler i distribusjonen

Kildedistribusjonen inneholder testene, men ingen medfølgende tredjepartsfiler. `tests/a11y/vendor/axe.min.js` (axe-core, MPL-2.0) ligger bare i git-repoet; den er utelatt fra sdist (`exclude` under `[tool.hatch.build.targets.sdist]` i `pyproject.toml`) og har aldri vært en del av wheel.

- Tester som trenger en utelatt fil, hoppes over med en tydelig begrunnelse når den mangler; kjør tilgjengelighetssuiten fra en git-utsjekk.
- `NOTICE` lister hver tredjepartsfil og sier om den distribueres. Legg en ny medfølgende fil i `exclude`-listen og i `NOTICE`, eller, hvis den må følge med, skriv i `NOTICE` at den gjør det.
- `scripts/check_dist_contents.py` bygger wheel og sdist (`uv build`) og feiler hvis en utelatt fil, eller en fil som `NOTICE` oppgir som ikke distribuert, er med. Arbeidsflyten `.github/workflows/dist.yml` kjører det i en egen jobb.

## Utgivelser

En utgivelse er en versjonstagg; alt annet er automatisert og kontrollert.
Sjekklisten ligger i [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md), det
engangs PyPI-oppsettet og den manuelle reserveløsningen i
[docs/PUBLISHING.md](docs/PUBLISHING.md).

### Lage en utgivelse

1. Gå gjennom [sjekklisten for utgivelser](docs/RELEASE_CHECKLIST.md): versjon og
   endringslogg, støttede Python-versjoner og systemer, ferskhet i kunnskapsbasen,
   oppgraderingsfixture, tilgjengelighetsgjennomgang ved UI-endringer, dokumentasjon
   på alle språk, sikkerhetsvarsler.
2. Sett `version` i `pyproject.toml` og gi `[Unreleased]` i `CHANGELOG.md` nytt navn
   `[X.Y.Z] - ÅÅÅÅ-MM-DD`. Sjekk lokalt med
   `python scripts/release_check.py version vX.Y.Z` og `... notes vX.Y.Z`.
3. Flett, tagg commiten og push taggen:
   `git tag -a vX.Y.Z -m "ekte vX.Y.Z"`, `git push origin vX.Y.Z`.
4. `release.yml` kontrollerer først med `scripts/release_check.py` at taggen
   samsvarer med pakkeversjonen, at `CHANGELOG.md` har en seksjon for den og at CI er
   grønn for den taggede commiten (den venter på en CI som kjører). Feiler en
   kontroll, stopper workflowen og ingenting publiseres. Deretter bygger den,
   publiserer til PyPI via Trusted Publishing med proveniensattester og lager
   GitHub-utgivelsen med endringslogg-seksjonen som notater.

### Utgivelseskandidater

Tagg `vX.Y.ZrcN` (med `version = "X.Y.ZrcN"` i `pyproject.toml`). PyPI behandler den
som en PEP 440-forhåndsversjon: `pip install ekte` ignorerer den, `pip install --pre ekte`
finner den; GitHub merker utgivelsen som «Pre-release». I endringsloggen holder
seksjonen `[X.Y.ZrcN]`, `[X.Y.Z]` eller `[Unreleased]`.

### Hvis en publisering feiler halvveis

PyPI godtar aldri samme fil to ganger, og en versjon kan ikke gjenbrukes; det
avgjørende er hvor langt kjøringen kom (Actions, «Release to PyPI»):

- **En kontroll feilet (jobben verify).** Ingenting ble publisert. Rett årsaken
  (versjon, endringslogg, CI), slett taggen lokalt og på origin
  (`git push origin :refs/tags/vX.Y.Z`) og tagg den rettede commiten på nytt.
- **Bygg eller opplasting feilet før PyPI hadde filer.** Kjør de feilede jobbene på
  nytt; ingen versjon er brukt opp. Må selve den taggede commiten endres, slett
  taggen og lag den på nytt.
- **PyPI har noen av filene** (se <https://pypi.org/project/ekte/#files>). Kjør de
  feilede jobbene på nytt: opplastingen hopper over filer som finnes. Avviker filene
  fra det som skal ut, ikke prøv igjen: «yank» versjonen på PyPI og gi ut neste
  (`X.Y.Z+1` eller `rcN+1`).
- **PyPI er komplett, men GitHub-utgivelsen feilet.** Kjør jobben `GitHub Release`
  på nytt; den oppretter eller oppdaterer utgivelsen idempotent. Eller for hånd:
  `gh release create vX.Y.Z --notes-file <(python scripts/release_check.py notes vX.Y.Z)`.
- **En feilaktig versjon er allerede live.** «Yank» den på PyPI (den kan da bare
  installeres med eksakt versjon), rett opp fremover med en ny versjon og noter det i
  endringsloggen.

## Sikkerhet

Rapporter sårbarheter privat, som beskrevet i [SECURITY.md](SECURITY.md).
Innenfor omfanget er fremfor alt: en nøkkel eller hemmelighet som havner i en
rapport, tekst som reléet styrer, og som injiserer markup i en rapport eller i
grensesnittet, utgående trafikk til noe annet enn de konfigurerte endepunktene,
og måter å omgå nettgrensesnittets beskyttelser som holder det lokalt.

## Lisens

[Apache-2.0](LICENSE)
