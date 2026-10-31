# ekte — realitetssjekk for LLM-releer

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md) · **🇳🇴 Norsk**

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**ekte** er et verktøy som kjører lokalt og reviderer om et API-relé
(forhandler / proxy) faktisk leverer modellen det sier det leverer — eller i det
stille bytter den ut med en billigere, kutter kontekstvinduet ditt, forfalsker
strømming eller blåser opp tokenfaktureringen. Kort sagt: får du det du har betalt
for? Den snakker **OpenAI Chat Completions API**, **Anthropic Messages API** og
**OpenAI Responses API** (`/v1/responses`) — gjenkjent automatisk, eller tvunget
med `--api openai|anthropic|responses`.

Du peker den mot et reléendepunkt og modellen det sier det leverer; ekte kjører
et sett med black box-prober, sammenligner det den observerer med en medfølgende
kunnskapsbase med **98 modellprofiler fra 7 leverandører**, og gir en tydelig
konklusjon underbygd med bevis — på kommandolinjen, i et lokalt nettgrensesnitt
eller som JSON for et annet verktøy eller en LLM.

> ekte rapporterer **black box-bevis på avvik og risiko, ikke kryptografiske
> bevis på svindel.** Se [Ansvarlig bruk](#ansvarlig-bruk).

Denne README-en er for dem som **bruker** ekte. Hvordan ekte bygges, testes og
utgis, står i [Utviklerveiledningen](DEVELOPER_GUIDE.nb.md); hvordan hver
kontroll fungerer og gis score, står i [Metodikken](docs/METHODOLOGY.nb.md).

Hva som er stabilt i ekte, hva som regnes som en brytende endring og hvordan funksjoner fases ut: [Retningslinjer for stabilitet og kompatibilitet](docs/STABILITY.md) (på engelsk).

---

## Innhold

- [Hvorfor](#hvorfor)
- [Installasjon](#installasjon)
- [Kom i gang](#kom-i-gang)
- [Nettgrensesnitt (`ekte serve`)](#nettgrensesnitt-ekte-serve)
- [Hva den kontrollerer](#hva-den-kontrollerer)
- [Slik kommer konklusjonen i stand](#slik-kommer-konklusjonen-i-stand)
- [Testsett](#testsett)
- [Ytelse](#ytelse)
- [Sammenligningsmodus og LLM-dommeren](#sammenligningsmodus-og-llm-dommeren)
- [Overvåking](#overvåking)
- [Revisjon av embedding, rerank, bilde og lyd](#revisjon-av-embedding-rerank-bilde-og-lyd)
- [Bruk i CI (GitHub Action)](#bruk-i-ci-github-action)
- [Kunnskapsbase](#kunnskapsbase)
- [Rapporter](#rapporter)
- [Personvern og lokale data](#personvern-og-lokale-data)
- [Ansvarlig bruk](#ansvarlig-bruk)
- [Mer dokumentasjon](#mer-dokumentasjon)
- [Fra zing](#fra-zing)
- [Lisens](#lisens)

## Hvorfor

Markedet for relénøkler er fullt av tilbud om «GPT-4o til en tidel av prisen».
Mange er ærlige. Noen er det ikke — og de uærlige er vanskelige å avsløre med det
blotte øye:

- Du ber om `gpt-4o`; i det stille får du `gpt-4o-mini` eller en åpen modell.
- Reléet annonserer en kontekst på 1M tokens, men kutter stille ned til 32K.
- «Strømming» er hele svaret bufret og delt opp på nytt, uten noen gevinst i forsinkelse.
- De rapporterte `usage`-tokenene er blåst opp, så saldoen din brennes raskere enn den burde.
- En modell som skal støtte verktøykall / JSON-modus, gjør det i det stille ikke.

ekte gjør «dette føles feil» om til en reproduserbar rapport.

## Installasjon

Krever Python 3.11+. Kjører på Linux, macOS og Windows (Docker-bildet er Linux); på Windows har eier-modusene til datamappen ingen virkning, se [Støttede operativsystemer](docs/STABILITY.md#os). Alle alternativene nedenfor gir deg kommandoen `ekte`.

### Med pip

```bash
# fra PyPI
pip install ekte

# eller fra kildekoden
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

### Med [uv](https://docs.astral.sh/uv/)

```bash
# fra PyPI, som et frittstående verktøy på PATH
uv tool install ekte

# eller kjør den én gang uten å installere
uvx --from ekte ekte --help

# eller fra kildekoden, inn i et virtuelt miljø lokalt i prosjektet
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Du kan også installere rett fra Git-repoet uten å klone:
`uv tool install git+https://github.com/mn567250/ekte`.

### Valgfrie tillegg

- `web` — det lokale nettgrensesnittet (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, fra PyPI
pip install -e '.[web]'            # pip, fra kildekoden
uv tool install 'ekte[web]'  # uv, fra PyPI
uv pip install -e '.[web]'         # uv, fra kildekoden
```

Tillegget `tokenizers` trengs ikke lenger: det er tomt og beholdes bare så eldre
installasjonskommandoer fortsatt virker. ekte teller tokens med en innebygd
heuristikk og laster ikke ned noe under kjøring (ingen tokenizer-filer), så den
kjører også i begrensede eller frakoblede miljøer som bare når releene du
reviderer.

PDF-rapporter (`--format pdf`, og PDF-nedlastingen i nettgrensesnittet) trenger
ikke noe tillegg: de settes med [ReportLab](https://www.reportlab.com/opensource/),
en ren Python-avhengighet som ikke trenger systembiblioteker på Linux, macOS eller
Windows.

### Med Docker (bare nettgrensesnittet)

Fra en utsjekk av kildekoden:

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# åpne http://localhost:8000
```

Publiser alltid porten på `127.0.0.1` som vist. Detaljer og miljøvariabler:
[Utviklerveiledning → Docker](DEVELOPER_GUIDE.nb.md#docker) og
[docs/DOCKER.md](docs/DOCKER.md).

## Kom i gang

```bash
# 1) revider et relé mot det det påstår (modell-ID + leverandørhint)
export EKTE_API_KEY=sk-your-relay-key
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) den sterkeste kontrollen: sammenlign med en pålitelig referanse for samme modell
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) revider et Anthropic-relé (Messages API) — protokollen gjenkjennes automatisk
#    fra base_url/modellen, eller tvinges med --api anthropic
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) bekreft et mistenkt bytte: revider reléets EKTE modell-ID mot profilen den
#    selges som (her: en Doubao-modell som utgis for å være deepseek-v4-flash)
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) vis modellene et endepunkt annonserer
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) se i kunnskapsbasen
ekte kb            # alle profiler, med kilde
ekte kb deepseek   # én leverandør

# 7) lag en konfigurasjon du kan legge inn i versjonskontroll
ekte init          # skriver ekte.yaml
ekte check -c ekte.yaml
```

API-nøkler kan oppgis direkte, som `env:VAR` eller som `file:/sti`; rapporter
inneholder bare et fingeravtrykk av nøkkelen. En fullstendig konfigurasjonsfil
ligger i [`examples/ekte.yaml`](examples/ekte.yaml).

Filen har en formatversjon (`version: 1`; en fil uten versjon er format 1). Feil typer og ugyldige verdier avvises med fil, linje og nøkkel; ukjente nøkler ignoreres med en advarsel frem til ekte 1.0.0, som avviser dem. `ekte config migrate` oppdaterer en eldre fil. Skjemaet er [`docs/schemas/config.schema.json`](docs/schemas/config.schema.json).

### Som verktøy for en LLM / agent

ekte er laget for å styres av et annet program eller en annen modell. Alt går til
stdout som JSON, også feil, og avslutningskoden er porten.

```bash
# slank, agentvennlig konklusjon (~5x mindre enn --json: uten de store bevisene)
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# full strukturert rapport når du trenger bevisene for hvert funn
ekte check --base-url ... --model gpt-4o --json

# budsjett først: hvilke detektorer som kjører + anslått antall API-kall, UTEN å gjøre noen
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# port på avslutningskoden (1 hvis risiko >= medium, eller scoren er under --fail-under);
# konfigurasjons-/bruksfeil avslutter med 2, som JSON
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# maskinlesbar oppdagelse
ekte kb --json                      # hele kunnskapsbasen
ekte models --base-url ... --json   # hva et endepunkt annonserer
```

I modusene `--json`/`--compact` skriver en dårlig konfigurasjon ut
`{"error": {...}}` (avslutningskode 2) i stedet for en melding for mennesker, så en
pipeline kan tolke feil på samme måte.

## Nettgrensesnitt (`ekte serve`)

Foretrekker du pek og klikk? Et lokalt nettgrensesnitt pakker inn den samme
motoren — ingen kommandolinje trengs.

```bash
pip install 'ekte[web]'     # eller: uv tool install 'ekte[web]'
ekte serve                        # åpner http://localhost:8000
```

Skjemaet leder deg gjennom konfigurasjonen:

1. Velg **Relé / leverandør**: en leverandør fra kunnskapsbasen eller et relé du
   har lagret. Basis-URL-en fylles ut (andre kjente URL-er for leverandøren tilbys
   som forslag). For andre releer velger du **Annet** og oppgir **Relé-URL**.
2. Legg til **API-nøkkel** hvis reléet trenger en.
3. ekte henter reléets modeller selv (når du velger et relé, og hver gang URL-en
   eller nøkkelen endres; **Oppdater modeller** spør på nytt). Velg **Modell som
   forespørres**. Et relé uten modelliste faller tilbake på at du skriver inn
   ID-en (**Skriv inn manuelt**).
4. Velg eventuelt **Oppgitt modell** blant modellene i kunnskapsbasen: modellen
   reléet sier det leverer. Når den forespurte modellen finnes i kunnskapsbasen,
   er den forhåndsvalgt; endre den bare hvis reléet selger modellen under et annet
   navn. Leverandørprofilen ekte reviderer mot, følger av den.

Et relé som ikke står i listen ennå, kan tas vare på med **Lagre i
kunnskapsbasen** under et navn du gir det; neste gang er det bare ett valg unna.
Den pålitelige referansen (**Sammenlign med en pålitelig referanse**) og
revisjonene av embedding og rerank settes opp på samme måte.

Trykk så **Start revisjon** og se kontrollene kjøre **i sanntid**: hver kontroll
viser scoren sin og hvor lang tid den tok, og en kontroll med funn foldes ut for å
vise bevisene. Resultatet er en konklusjonsrapport du kan dele: karakter,
kontrollene per dimensjon med scoreskalaene sine, funn i klarspråk og
ytelsesdelen, og en **Kjøringslogg** for hver detektor.

Alt kjører på maskinen din: en nøkkel du skriver i nettleseren, når bare din
lokale ekte-server og reléet du reviderer, aldri en tredjepart. Se
[Personvern og lokale data](#personvern-og-lokale-data).

### Sider

Nettgrensesnittet leveres fra roten av adressen `ekte serve` åpner, med revisjonssiden på `/`. Adressene som ble brukt til nå (`/v2/…`, f.eks. `/v2/history`) og adressene til det tidligere klassiske grensesnittet (`/tools`, `/console`) videresendes permanent til tilsvarende side og beholder spørrestrengen; disse videresendingene er foreldet og fjernes i 1.0.0.

| Side | Adresse | Hva den er til |
|---|---|---|
| **Revisjon** | `/` | Revider et relé (eventuelt mot en referanse) og les rapporten; revisjoner av embedding og rerank starter også her, via velgeren for type endepunkt |
| **Overvåking** | `/watches` | Planlagte nye revisjoner med webhook-varsler |
| **Historikk** | `/history` | Hver revisjon kjørt på denne maskinen, gruppert etter relé + oppgitt modell, med trender |
| **Analyse** | `/analytics` | Releer og modeller sammenlignet over tid: nøkkeltall, diagrammer med datatabeller, rangeringslister |
| **Kunnskap** | `/kb` | Kunnskapsbasen i tre faner — modeller, leverandører, releer: bla gjennom, slå av/på, legg til dine egne |

På tvers av sidene: filtre og konfigurerbare trender (score, karakter,
forsinkelse p50, tokens/s) på **Historikk**; **Planlegg som overvåking** og
**Kjør revisjonen på nytt** på hver kjøring i Historikk; **Last ned rapport** i
alle formater; og en temabryter (Automatisk tema / Lyst / Mørkt). Alle sider
unntatt Tilgjengelighet har én melding rett under innledningen, farget etter
viktighet (informasjon, suksess, advarsel, kritisk): f.eks. den sist fullførte
revisjonen på **Revisjon**, hovednøkkelen på **Overvåking**, kjøringer som
fortsatt behandles på **Historikk** og **Analyse**, oppføringer som ble hoppet
over på **Kunnskap**.

**Revisjoner i bakgrunnen.** En revisjon startet på **Revisjon**-siden fortsetter
å kjøre når du bytter side eller lukker fanen; **Fortsett i bakgrunnen** sender den
dit med vilje. **Historikk** viser hver revisjon i kø og under kjøring (og hver
overvåking som kjører) med fremdrift; **Følg i sanntid** åpner sanntidsvisningen
igjen, som tar igjen alt som allerede har skjedd. Revisjoner av samme relé kjøres
etter hverandre, så de aldri forstyrrer hverandres resultater for forsinkelse eller
pålitelighet (alle loopback-adresser regnes som én vert, så modeller som leveres
fra din egen maskin, settes også i kø); revisjoner av ulike releer kjøres
parallelt, høyst fire om gangen (`EKTE_MAX_PARALLEL_AUDITS`). Overvåkinger venter
på reléet sitt på samme måte.

**Analyse.** `/analytics` gjør den lokale historikken om til sammenligninger:
nøkkeltall for valgt periode (kjøringer, medianscore, andel høy risiko,
suksessrate, TTFT, dekodehastighet, faktureringsforhold) med endringen mot like
lang periode før; et diagram over et hvilket som helst måltall per relé, modell
eller relé × modell per time, dag eller uke (medianlinje med båndet p25–p75,
opptil fire serier, hvert diagram også som datatabell); og en rangeringsliste over
releene for en modell, eller modellene for et relé. Releer grupperes etter
oppføringen sin i kunnskapsbasen (lagrede releer og leverandører), så å gi nytt
navn til et relé grupperer historikken på nytt. Intervaller med færre enn 3
kjøringer tegnes blekere — én enkelt revisjon kan være et avvik; en overvåking gir
regelmessige målinger. Eldre kjøringer viser det de målte: siden sier hvor mange
kjøringer en verdi bygger på. Som standard sammenligner den ett testsett og én
probemodus (de vanligste), så ulike kjøringer ikke blandes; filtrene og visningen
ligger i URL-en, så en visning kan bokmerkes eller deles. Ingenting forlater
maskinen.

Flere paneler svarer på smalere spørsmål: **topptider** (et varmekart ukedag ×
time over TTFT, forsinkelse og dekodehastighet (median og halene p95 / p5),
variasjon mellom tokens, nettverks- og relétider, suksess- eller feilrate i din
tidssone — blir et relé tregere eller feiler oftere når det er travelt? Per
ukedag, eller med 90 dager med kjøringer over en 4-ukerssyklus og med 180 dager
per uke i måneden), **feil og pålitelighet** (mislykkede kall etter årsak —
strupinger (HTTP 429), serverfeil (5xx), tidsavbrudd, nettverksfeil — over tid og
per relé eller modell, fra de lagrede forespørselspostene, med hvor mange
kjøringer som har dem), **modellintegritet** (resultater fra identitets-,
kontekstvindu- og egenskapskontrollene per relé × modell, andelen kjøringer der
den gjengitte modellen avviker, og den målte andelen av det oppgitte
kontekstvinduet), **fakturering og tokens** (faktureringsforhold over tid mot
100 %-linjen — over den rapporterer reléet flere tokens enn ekte talte — pluss
andeler resonneringstokens og bufret inndata) og **reléoverhead**
(behandlingstiden et relé rapporterer, ved siden av tur-retur i nettverket til
det).

**Faner og delingslenker (Analyse).** Panelene ligger i fem faner —
**Oversikt** (nøkkeltall, rangeringsliste), **Trender** (sammenligning over tid,
topptider), **Pålitelighet** (feil, reléoverhead), **Modellintegritet** og
**Fakturering** — under sidehodet og ett filterpanel som deles av alle; bare
fanen du ser på, lastes. URL-en tar vare på fanen, filtrene og hvert
diagramvalg (`#tab=reliability&range=30&relay=…&eb=dow_hour`), og **Kopier lenke
til denne visningen** kopierer den (eller viser den i et felt du kan kopiere fra
der nettleseren ikke tillater det): å åpne lenken viser akkurat den visningen.
Filterpanelet er det samme på **Historikk**, **Overvåking** og **Analyse**:
lukket viser det hvor mange filtre som er aktive, og navngir dem på én linje
(f.eks. «Siste 30 dager · standard · Strømming · Example Relay»), så en delt
visning sier hva den viser.

### Språk

En nedtrekksliste for språk i sidehodet på hver side bytter grensesnittet mellom
**🇬🇧 engelsk** (standard), **🇨🇳 kinesisk** (det opprinnelige grensesnittet),
**🇫🇷 fransk**, **🇪🇸 spansk**, **🇵🇹 portugisisk**, **🇮🇹 italiensk**,
**🇩🇪 tysk** og **🇳🇴 norsk** (bokmål); valget huskes per nettleser.

Rapporter lastet ned fra grensesnittet (**Last ned rapport**: JSON, Markdown, HTML
eller PDF) følger valgt språk: JSON-nøklene, enum-verdiene (`risk_level`,
`status`, `severity`, …), ID-ene og bevisene er nøyaktig som i rapporten fra
kommandolinjen (JSON-en er fortsatt en gyldig ekte-rapport), mens verdiene for
mennesker (konklusjonens overskrift og sammendrag, titler og sammendrag for funn,
anbefalinger, detektornavn, merknader) oversettes, og filnavnet har språket med
(`ekte-report.nb.json`, `ekte-report.nb.pdf`). Seksjonsoverskriftene i
Markdown-/HTML-/PDF-filene er på engelsk. Kommandolinjens egne rapporter med
`--format json|md|html|pdf` forblir på engelsk.

**Promptene som sendes til endepunktet som revideres, følger ikke
grensesnittspråket.** All tekst ekte sender til et LLM-API, er på engelsk, så
samme relé får samme konklusjon uansett hvem som leser rapporten
(svarkontrollene og tokenanslagene er kalibrert til akkurat disse tekstene). De
eneste unntakene er fingeravtrykk i kunnskapsbasen der språket *er* målingen —
for eksempel probene for flyt i kinesisk, tokenizer og selvidentifikasjon for
modeller med kinesisk opphav. Hver rapport registrerer probespråkene den faktisk
brukte (`prompt_languages`, f.eks. `["en", "zh"]`).

Hver rapport registrerer også hvordan endepunktet ble snakket til:
protokollen (`target.api`: `openai`, `anthropic` eller `responses`), om
`--api auto` gjenkjente den (`target.api_auto`), og ytelsesprobens
forespørselsmodus (`stream_mode`: `stream`, `non_stream` eller `both` for
testsettet full). Historikksiden i nettgrensesnittet kan filtrere på alle tre.
`started_at` registrerer når revisjonen startet (UTC); `start_ms` i hver
forespørselspost regnes fra den.

## Hva den kontrollerer

ekte gir score i ti dimensjoner. De fire **kjernedimensjonene** — modellidentitet,
kontekstvindu, påståtte egenskaper og fakturering og forbruk — avslører mest
direkte en falsk vare. Navnene er de nettgrensesnittet og rapportene bruker.

| Dimensjon | ID | Vekt | Hva den fanger |
|---|---|---|---|
| **Modellidentitet** | `model_identity` | 21 | Stille nedgradering eller bytte av modell — selvidentifikasjon, kunnskapsgrense, tokenizer-fingeravtrykk, det gjengitte `model`-feltet; eventuelt en LLM-dommer |
| **Kontekstvindu** | `context_window` | 19 | Stille avkorting av kontekst (påstår 1M, gjenkallingen svikter ved 32K) og lost-in-the-middle fra billige RAG-/oppsummeringsmellomledd, via nål i høystakken og binærsøk |
| **Påståtte egenskaper** | `capability` | 13 | Påstander om verktøykall / JSON-modus / JSON-skjema / maks utdata som ikke innfris (eller *over*oppfylles, et hint om en erstatning); **syn** — en modell som påstår bildeinndata, må lese et generert bilde med kjent svar |
| **Protokollsamsvar** | `protocol` | 8 | Samsvar på linjen: flere turer, stoppsekvenser, feilskjema; hver forespørselsparameter godtatt (og respektert der det synes), hvert svarattributt til stede; bufring av svar som ignorerer temperature/seed |
| **Fakturering og forbruk** | `billing` | 8 | Oppblåst token-/forbruk og manglende eller uverifiserbart forbruksregnskap, via et uavhengig heuristisk tokenanslag |
| **Tilkobling** | `connectivity` | 7 | Om endepunktet kan nås, og den annonserte `/v1/models`-listen |
| **Ekte strømming** | `streaming` | 6 | Forfalsket strømming (bufre og så dele opp), ut fra antall biter og tidsbruk mellom bitene |
| **Pålitelighet ved samtidighet** | `reliability` | 6 | Suksessrate og forsinkelse under samtidig last (HTTP 429-struping telles for seg) |
| **Transportsikkerhet** | `security` | 6 | HTTPS, hygiene i hoder, ekko av hemmeligheter; en skjult injisert systemprompt; manipulering av svar og verktøykall underveis (kanarier med kjent svar); bufring av promptprefiks (tidsmåling) |
| **Ytelse** | `performance` | 6 | Hvor *jevne* forsinkelse, tid til første token og gjennomstrømning er, feilraten og nedbremsingen under last; hastighet bare mot en referanse (se [Ytelse](#ytelse)) |

[Metodikken](docs/METHODOLOGY.nb.md) beskriver hver probe, hvilket relétriks den
svarer til, scoreskalaen og forbeholdene mot falske positiver.

## Slik kommer konklusjonen i stand

Kort fortalt ([Metodikken](docs/METHODOLOGY.nb.md#slik-gir-ekte-score) har
detaljene):

- Hver detektor publiserer sin **scoreskala** — hvert mulige utfall av hver
  kontroll med poengene sine — og nettgrensesnittet viser den under
  **Scoreskala**.
- En **dimensjonsscore** er gjennomsnittet med lik vekt av detektorenes scorer.
  Et HIGH/CRITICAL-funn tvinger fram **Ikke bestått**, og et MEDIUM-funn hever
  **Bestått** til **Advarsel**, uansett score. Rapportene forklarer dette per
  dimensjon under **Dimension details**; i nettgrensesnittet foldes hver rad i
  **Kontroller per dimensjon** ut til de samme detaljene.
- Den **samlede helsescoren** er det vektede gjennomsnittet av dimensjonene som
  kjørte (vektene over), med karakter A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60)
  eller F.
- **Risikokonklusjonen** styres av funnenes alvorlighet, ikke av scoren:

| Risiko | Etikett i grensesnittet | Når |
|---|---|---|
| `inconclusive` | For lite grunnlag | Ingenting brukbart å vurdere etter: verken modellidentitet, kontekstvindu eller påståtte egenskaper ga et brukbart resultat da de kjørte (reléet kunne ikke nås, modellen finnes ikke i kunnskapsbasen), eller ingen dimensjon utenom tilkobling gjorde det |
| `high` | Falsk vare | Et CRITICAL-funn, et HIGH/CRITICAL-funn i en kjernedimensjon, eller to eller flere HIGH-funn |
| `medium` | Avvik funnet | Nøyaktig ett HIGH-funn utenfor kjernedimensjonene, eller et MEDIUM-funn i en kjernedimensjon |
| `low` | Stort sett pålitelig | Alle andre MEDIUM-funn |
| `clean` | Konsistent (trolig ekte) | Ingen av delene over |

Funn i tilkoblingsdimensjonen hever aldri risikoen: et relé som er nede eller
strupes, kunne ikke vurderes, og det er ikke bevis på en annen modell.
Transportråd — ren HTTP (`security.tls`) og feil eller trege haler under last
(`reliability.*`) — senker scoren i dimensjonen sin, men hever heller ikke
risikoen for bytte; sammendraget viser dem som råd. Manipulering av integriteten
og en gjengitt API-nøkkel gjør det fortsatt. Ren HTTP til denne maskinen eller et
privat nettverk er bare en advarsel med lav alvorlighet, siden nøkkelen aldri
forlater det.
Overskriften nevner dimensjonene som satte risikoen: den snakker om den oppgitte
modellen bare når modellidentitet er blant dem (et avkortet kontekstvindu gir
«leverer ikke det som annonseres: Kontekstvindu»), og en konklusjon uten resultat
for modellidentitet sier at modellidentiteten ikke ble verifisert.
Konklusjonens **sikkerhet** (lav / middels / høy) øker med antall
kjernedimensjoner som ga et resultat, en referanse og LLM-dommeren; en modell-ID
som bare passet omtrentlig med en profil i kunnskapsbasen, begrenser den til lav.
En detektor som ikke fikk noe brukbart svar (f.eks. at alle prober for
modellidentitet mislyktes), er uavklart og regnes som manglende signal, aldri som
bestått.

## Testsett

| Testsett | Detektorer | Kostnad |
|---|---|---|
| `smoke` | connectivity, security | svært lav |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | lav–middels |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (med `--judge`) | høyere (prober for lang kontekst og tidsmåling koster tokens) |
| `full` | detektorene i `deep`, med ytelsen målt både med og uten strømming | høyest |
| `custom` | bare dimensjonene du velger, med dybden `deep` | avhenger av utvalget |

Kontekstvindu-proben begrenses av `--max-context-tokens` (standard 200K), så det
holder seg rimelig å revidere en modell med 1M tokens; et vindu større enn taket
rapporteres som *verifisert opp til taket*, aldri som avkortet. `--only` /
`--skip` kjører eller utelater enkeltdetektorer etter ID.

### Egendefinert testsett

Kjør bare dimensjonene du bryr deg om; det sparer tid og tokens. Hver detektor i
hver valgte dimensjon kjøres, som på `deep`:

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` kan gjentas eller kommaseparereres og innebærer
`--suite custom`; i en konfigurasjonsfil bruker du
`run.dimensions: [protocol, performance]`. Dimensjonene er `connectivity`,
`protocol`, `context_window`, `model_identity`, `capability`, `streaming`,
`billing`, `reliability`, `security` og `performance`. I nettgrensesnittet åpner
knappen for testsettet `custom` det samme valget (**Dimensjoner som skal
kjøres**) på revisjonssiden og på overvåkingene.

Den **samlede scoren er det vektede gjennomsnittet av bare de valgte
dimensjonene**; dimensjoner du utelot, rapporteres som «ikke valgt».
Risikokonklusjonen vurderes også på de valgte dimensjonene: uten
modellidentitet dekker den bare dem, ikke hvilken modell som leveres, og sier det.

## Ytelse

Hver rapport har en **ytelsesdel**: forsinkelse, tid til første token (TTFT),
dekode- og ende-til-ende-tokens/s, forsinkelse og variasjon mellom biter,
rater for feil/tidsavbrudd/429, en nettverksoppdeling (TCP-tilkobling, TLS, en
tur-retur med `GET /models`, servertid) og kaldstart, hver som antall / min /
gjennomsnitt / p50 / p75 / p90 / p95 / p99 / maks / standardavvik.

Når den egne proben kjører, gir den score i dimensjonen **Ytelse**. Scoren
handler om **jevnhet**, ikke rå hastighet, så et tregt, men stødig endepunkt (en
lokal eller selvdriftet modell) trekkes ikke ned for ikke å være et datasenter:

| Kontroll | Score basert på |
|---|---|
| jevnhet i forsinkelse / TTFT | haleforhold p90 ÷ p50 (≤ 1,3 jevn 100 · ≤ 1,75 stabil 85 · ≤ 2,5 varierende 65 · over: ujevn 40); krever ≥ 10 prøver |
| jevnhet i gjennomstrømning | haleforhold p50 ÷ p10 for tokens/s, samme bånd |
| feil | mislykkede probeforespørsler: ≤ 2 % 100 · ≤ 10 % 80 · over: 50 (429 telles ikke) |
| stabilitet under last | forsinkelse p50 i støtet ÷ sekvensiell p50: ≤ 1,5x 100 · ≤ 3x 80 · over: 55 |
| treff i hurtigbuffer | unike prompter besvart fra en hurtigbuffer: 60 |
| referanse | tokens/s mot den pålitelige referansen, ellers kunnskapsbasens publiserte område for modellen: på linje 100 · tregere: telles ikke (til informasjon, aldri en feil) · ≥ 2x raskere 60 (hint om en mindre modell) · ingen referanse: telles ikke |

Ytelsesfunn har høyst lav alvorlighet: de flytter scoren, aldri
risikokonklusjonen. Uten proben (`standard` uten referanse, `smoke`) kjører ikke
dimensjonen, og den faller ut av den samlede scoren.

- **standard** samler delen fra revisjonens egne forespørsler.
- **deep / full / custom** legger til en egen probe: 100 forespørsler som ikke kan
  bufres, med 128 utdatatokens (en tilfeldig forespørsels-ID innleder hver prompt;
  ingen parametere for hurtigbuffer eller resonnering sendes), pluss et støt med
  `--concurrency`. Juster den med `--performance-requests` (0 slår den av) og
  `--performance-max-tokens`.
- Proben strømmer som standard; `--performance-non-streaming` (eller bryteren
  **Strømming / Uten strømming** i nettgrensesnittet) måler releer som ikke kan
  strømme. **full** måler begge modusene, vekselvis, og rapporterer dem side om
  side.
- **compare** kjører proben mot begge endepunktene, med vekslende forespørsler, og
  legger til en tabell mål mot referanse (5 forespørsler per side på `standard`,
  for få for jevnhetskontrollene) der forskjellene er merket grønt ✓ der målet er
  bedre og rødt ✗ der det er dårligere.

Tokens telles to ganger — fra reléets `usage` og lokalt — så gjennomstrømningen
kan måles selv når `usage` mangler. Den lokale tellingen er et anslag fra en
innebygd heuristikk (omtrent ±15–20 %; ingen tokenizer brukes eller lastes ned),
og delen sier alltid det. En persentil vises bare med nok prøver (p90 fra 10, p95
fra 20, p99 fra 100). JSON-rapporten tar vare på tidsmålingene for hver
forespørsel (bare tall, ingen tekst); HTML-rapporten og nettgrensesnittet viser
dem i diagram over revisjonens tidslinje.

Revisjoner som kjører samtidig i `ekte serve` (flere nettleserfaner,
overvåkinger), forvrenger ikke hverandres tidsmålinger: CPU-tung forberedelse,
som å bygge de lange promptene til kontekstvindu-proben, kjøres utenfor serverens
hendelsesløkke.

**Tidsavbrudd for forespørsler.** `timeout_sec` (`--timeout`, standard 60 s) er
grunnlaget; hver forespørsel får mer etter promptstørrelse og utdatabudsjett, så
en lang kontekstvindu-probe eller en treg selvdriftet modell ikke kuttes etter ett
minutt. Lokale og private verter (`localhost`, `127.x`, `192.168.x`,
`host.docker.internal`, …) får minst 300 s. `max_request_sec`
(`--max-request-time`, standard 900 s) er det harde taket for hver enkelt
forespørsel, strømmer inkludert, så ingen forespørsel kan henge for alltid. En
kontekstvindu-probe som likevel får tidsavbrudd, rapporteres som uavklart, ikke
som avkorting.

## Sammenligningsmodus og LLM-dommeren

ekte har to deteksjonsmoduser:

- **Ren kode (standard):** alle detektorer unntatt `quality_judge` avgjør med
  deterministisk kode — fingeravtrykk, kontekstsveipet, faktureringsregning,
  tidsmåling av strømming. Ingen ekstra modell trengs; resultatene er
  reproduserbare.
- **Hybrid av kode og LLM (`--judge`):** spør i tillegg en *pålitelig*
  dommermodell (satt opp separat, aldri målet) om målets svar leses som den
  oppgitte modellen — uklare signaler som kvalitet og resonneringsdybde som ren
  kode ikke kan avgjøre. Dette er detektoren `quality_judge`.

```bash
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

**Sammenligningsmodus** (`ekte compare`, eller **Sammenlign med en pålitelig
referanse** i nettgrensesnittet) kjører de samme probene mot en pålitelig
referanse for den oppgitte modellen samtidig. Det er den sterkeste veien til
bekreftelse: identitetssvar, avviste forespørselsparametere, kanarier for
manipulering og ytelse vurderes side om side, og bare en referanse lar
konklusjonens sikkerhet nå *høy*. Uten `--judge-base-url` bruker
sammenligningsmodus referansen som dommer.

## Overvåking

Releer kan levere den ekte modellen i dag og i det stille bytte den ut neste uke.
`ekte watch` reviderer på nytt etter en tidsplan, registrerer hver kjøring i
historikken og varsler en webhook når risikoen krysser en terskel eller
**forverres** sammenlignet med forrige kjøring.

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang nb                                     # eller --once for cron
```

Varsler formateres for **Slack / Feishu / DingTalk / generisk JSON**, gjenkjent
automatisk fra webhook-URL-en, og skrives på varslingsspråket — engelsk som
standard; `--alert-lang en|zh|fr|es|pt|it|de|nb`. Den generiske JSON-lasten
holder nøklene og maskinverdiene (`risk_level`, `score`, …) språknøytrale,
oversetter dem som er for mennesker (`text`, `headline`, `key_findings`), og
oppgir `language`.

**I nettgrensesnittet** kjører `ekte serve` de samme overvåkingene i en
planlegger i bakgrunnen inne i serverprosessen, lagrer hver kjøring i
**Historikk** og sender de samme webhook-varslene. Åpne en kjøring i
**Historikk** og velg **Planlegg som overvåking**. ekte kopierer kjøringens
konfigurasjon (relé, modell, oppgitt modell, leverandør, testsett, egendefinerte
dimensjoner) til en overvåking på pause på **Overvåking**-siden; angi intervall og
API-nøkkel der (Historikk lagrer aldri nøkler) og slå den på. Intervall, nøkkel,
**Varslingsterskel**, webhooker og **Varslingsspråk** kan redigeres direkte på
hver overvåking. Klikk på navnet til en overvåking for å folde kortet sammen til
navn, status og siste kjøring (**Fold sammen alle** / **Fold ut alle** over
listen; huskes per nettleser), og snevre inn en lang liste med filterpanelet
(søk, status, siste risiko, type endepunkt, relé, testsett) som på **Historikk**.

Hver overvåking har sitt eget varslingsspråk (standard er grensesnittspråket),
kan kjøres nå, settes på pause eller slettes, og fester profilen fra
kunnskapsbasen den ble opprettet med, til du fester den på nytt.

Overvåkinger som forfaller, kjøres samtidig, hver som sin egen revisjon, men
aldri mer enn én revisjon per relévert om gangen og høyst
`EKTE_MAX_PARALLEL_AUDITS` totalt; en kjøring venter på en ledig plass (en
revisjon du starter for hånd, kan også havne i kø bak overvåkinger som kjører).
Tidspunktet for en kjøring er når revisjonen starter, etter eventuell venting.
Kontrollen av forverring sammenligner med den siste lagrede kjøringen av samme
relé og modell, uansett hvor mange andre kjøringer som er lagret siden.
Varslingswebhookene for en kjøring sendes samtidig, så en treg eller død webhook
ikke holder igjen de andre. API-nøkler sendes aldri tilbake til nettleseren.

**Lagring av API-nøkler.** Som standard **lagrer ikke** ekte overvåkingenes
API-nøkler: en nøkkel du oppgir, blir bare værende i minnet til `ekte serve` og
skrives aldri til disk. Etter en omstart viser **Overvåking**-siden hvilke
overvåkinger som trenger nøkkelen sin igjen, og de venter (ingen mislykket
kjøring, ikke noe varsel) til du oppgir den; overvåkinger uten nøkkel og
`env:`/`file:`-referanser fortsetter å kjøre. For at nøkler skal overleve
omstarter, velger du **Lagre kryptert på denne maskinen** under **Lagring av
API-nøkler** på **Overvåking**-siden: nøklene oppbevares da i `watches.db`,
kryptert med en hovednøkkel. Å bytte tilbake flytter de lagrede nøklene til
minnet og sletter dem fra `watches.db`. Meldingen på siden sier hvilken modus som
gjelder, spør før et bytte og rapporterer hva som ble flyttet. En installasjon som
allerede har lagret krypterte nøkler, eller som setter `EKTE_SECRET_KEY`,
fortsetter å lagre dem til du bytter.

**Hovednøkkel.** Når nøkler lagres, krypteres de med en hovednøkkel som ekte
aldri skriver til disk. Første gang du velger å lagre nøkler, oppretter
**Overvåking**-siden den og viser den én gang: kopier eller last den ned, oppbevar
den i en passordbehandler (nettleseren din kan lagre den), og lim den så inn igjen
for å bekrefte. Etter hver omstart av `ekte serve` ber siden om den igjen
(nettleseren kan fylle den inn); inntil da venter overvåkinger som trenger den,
mens overvåkinger uten nøkkel og `env:`/`file:`-nøkler fortsetter å kjøre.
Statuslinjen på **Overvåking**-siden tilbyr også **Lås**, **Roter** og **Glemt
nøkkelen?** (forkaster de krypterte API-nøklene så du kan oppgi dem igjen). For
bruk uten tilsyn eller i Docker sender du nøkkelen som `EKTE_SECRET_KEY` (se
[docs/DOCKER.md](docs/DOCKER.md)); `ekte secret status | export | rotate`
håndterer den på kommandolinjen.

## Revisjon av embedding, rerank, bilde og lyd

Disse endepunktene returnerer vektorer, rangeringer, bilder eller lyd i stedet for
chat, så ekte reviderer dem med målrettede prober i stedet for chatpromptene. Hver
av dem skriver ut en konklusjon og støtter `--json` og `--fail-on-risk`.

### Type endepunkt (surface), overvåking av embedding og rerank

Hver revisjon, historikkrad og overvåking har en **type endepunkt** (`surface`):
`chat` (standard), `embedding` eller `rerank`. Den er uavhengig av testsettet.
Revisjoner av embedding og rerank går gjennom samme kjører, scoring (0–100, A–F),
Historikk, Analyse og Overvåking som chat-revisjoner; bare detektorene er
forskjellige. Historikk og Analyse filtrerer etter type endepunkt, og Analyse
viser bare måltallene som gjelder.

For å overvåke et embeddings- eller rerank-endepunkt kjører du det på
**Revisjon**-siden (velg **Embeddinger** eller **Rerank** i velgeren for type
endepunkt) og velger **Overvåk dette**, eller **Planlegg som overvåking** på
raden i Historikk. Overvåkingen kjører revisjonen på nytt etter tidsplanen sin,
med samme festing til kunnskapsbasen, varslingsterskel og varsler om forverring
som en chat-overvåking, og kontrollerer **drift** mot forrige kjøring (vektorene
fra en embedding-probe, rangeringen og scorene fra en rerank-probe). Den oppgitte
dimensjonen til en embedding-overvåking kan endres på kortet (tom eller 0: fra
kunnskapsbasen). Hastighetsprobene (embeddinger: forsinkelse, kaldstart,
inndata/s, batchskalering; rerank: forsinkelse, kaldstart, dokumenter/s, 4 mot 32
dokumenter) kjøres bare med testsettene deep, full eller egendefinert, eller med
standard og en referanse.

### Embeddinger og rerank

```bash
# Forventet vektordimensjon slås opp i kunnskapsbasen for den oppgitte modellen.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Eller oppgi forventet dimensjon direkte:
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: en innebygd probe med kjent svar — en ekte reranker må rangere det
# åpenbart relevante dokumentet først.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Dypere: legger til hastighetsproben for rerank; --no-save holder kjøringen utenfor Historikk.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# Se kontrollene og anslått antall kall først, uten å sende en forespørsel:
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` kontrollerer tilkobling, **proben med kjent svar** (det åpenbart
relevante dokumentet må rangeres først), det gjengitte `model`-feltet,
determinisme (samme spørring to ganger gir samme rangering og scorer) og
**rangeringsdrift** mot forrige lagrede kjøring. `ekte embed` og `ekte rerank`
tar `--suite` og `--save/--no-save` (lagres som standard, så neste kjøring har en
referanse for drift) og `--dry-run`.

`embed` kontrollerer tilkobling, **samsvar i dimensjon** (den returnerte
vektorlengden mot den oppgitte modellens egen dimensjon — hovedtegnet på falsk
vare: et relé som påstår 3072-d `text-embedding-3-large`, men returnerer 1024-d,
leverer en erstatning), determinisme (samme inndata → cosinus ≈ 1), atskillelse
(urelaterte inndata → cosinus godt under 1) og det gjengitte `model`-feltet.
Medfølgende profiler: OpenAI `text-embedding-3-small` (1536),
`text-embedding-3-large` (3072), `text-embedding-ada-002` (1536), Qwen
`text-embedding-v3`/`-v4` (1024).

Begge finnes også i nettgrensesnittet: de starter på **Revisjon**-siden via
velgeren for type endepunkt (**Embeddinger**, **Rerank**). Rerank-revisjonen
bruker alltid de innebygde probene, så hver kjøring kan sammenlignes med tanke på
drift og overvåking.

### Generering av bilde og lyd (TTS)

Bildegenerering (`POST /v1/images/generations`) og tekst til tale
(`POST /v1/audio/speech`), dekodet bare med Pythons standardbibliotek —
bildedimensjoner fra hodebytene (PNG/JPEG/GIF/WebP), WAV-varighet via `wave`.

```bash
# Returnerer et relé som påstår DALL·E 3, faktisk den forespurte 1792x1024? Et
# nedskalert bilde eller et bilde i feil størrelse (eller en størrelse utenfor den
# oppgitte modellens egne størrelser, fra kunnskapsbasen) er hovedtegnet på falsk vare.
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Returnerer et relé som påstår tts-1-hd, ekte lyd der lengden skalerer med
# inndataen (ikke en fast plassholder, ikke HTML/JSON forkledd som lyd)?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
```

`image` kontrollerer tilkobling, et gyldig format som kan dekodes, **samsvar i
størrelse** (dekodet bredde × høyde mot forespørselen og den oppgitte modellens
egne størrelser — FAIL/HIGH ved avvik), atskillelse (to prompter → ulike bilder,
fanger en fast plassholder), antall og `model`-feltet. `audio` kontrollerer
tilkobling, gyldig beholder/format, at formatet respekteres, en ikke-triviell
varighet som skalerer med inndataen, atskillelse og `model`-feltet.
Kunnskapsbasen har med profiler for OpenAI DALL·E 2/3, gpt-image-1,
tts-1/tts-1-hd/gpt-4o-mini-tts og Qwen bilde/TTS.

## Bruk i CI (GitHub Action)

La en hvilken som helst arbeidsflyt avhenge av en relérevisjon med den
medfølgende sammensatte handlingen. Den kjører
`ekte check --compact --fail-on-risk`, eksponerer `risk` / `score` / `rating` som
utdata, skriver et sammendrag til kjøringen og får jobben til å feile når
risikoporten slår til.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@vX.Y.Z       # fest til en utgivelsestagg
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # hemmelighet fra kalleren; ekkoes aldri
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

Relénøkkelen sendes videre gjennom en miljøvariabel (`--api-key env:…`), så den
aldri vises på en kommandolinje. Se [docs/CI.md](docs/CI.md) for alle inndata og
utdata og et eksempel der en utrulling avhenger av revisjonen.

## Kunnskapsbase

ekte vurderer et relé mot **profilen** til modellen det oppgir: eget
kontekstvindu, maks utdata, kunnskapsgrense, tokenizer, egenskapsflagg,
identitetsnøkkelord og atferdsfingeravtrykk. De medfølgende profilene dekker
OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM og Moonshot (`ekte kb` viser
dem). Det finnes tre lag, der de senere vinner:

1. **Medfølgende** profiler, én YAML-fil per leverandør i
   [`ekte/knowledge/data/`](ekte/knowledge/data).
2. **En mappe med dine egne YAML-filer**: `--kb-dir ./my-profiles` (kan gjentas)
   eller `EKTE_KB_DIR`.
3. **Dine oppføringer** (`kb.db` i datamappen), lagt til uten YAML-filer eller
   redigerbar installasjon:
   - på nettgrensesnittets **Kunnskap**-side (`/kb`), med én fane hver for
     **Modeller**, **Leverandører** og **Releer**. Hver fane viser hele settet —
     medfølgende, `EKTE_KB_DIR` og dine (merket **Dine**) — med et filter, en
     av/på-bryter per element og et **Legg til …**-skjema: **Legg til en modell**
     → **Kopier undersøkelsesprompten** inn i KI-assistenten du foretrekker, last
     opp eller lim inn YAML-en den svarer med, og velg så **Kontroller og
     lagre**; **Legg til en leverandør** tar leverandør-YAML på samme måte;
     **Legg til et relé** tar et navn og en basis-URL. **Hvilken profil bruker en
     modell-ID?** viser hvordan en ID slås opp; oppføringene dine kan eksporteres
     som YAML;
   - på nettgrensesnittets **Revisjon**-side: **Lagre i kunnskapsbasen** tar vare
     på et relés navn og basis-URL (en leverandøroppføring uten modeller), oppført
     under **Kunnskap → Releer**;
   - på kommandolinjen: `ekte kb-prompt <model>`, `ekte kb-import <file>` (legg
     til `--check` for bare å kontrollere den) og `ekte kb-export`.

Før en oppføring lagres, kontrollerer ekte den: skjema og grenser, utrygge
regulære uttrykk, hver prompt den ville sende, og modell-ID-er som ville blitt
slått opp til en annen profil. En modell av deg med en medfølgende ID erstatter den
(rapportert som at den *skygger* for den), men endrer aldri en medfølgende
leverandørs egne innstillinger; fingeravtrykk slås sammen etter ID. Å slå av en
medfølgende modell, leverandør eller et relé på **Kunnskap**-siden lagres også i
`kb.db`: en modell-ID som er slått av, slås ikke lenger opp, og en leverandør som
er slått av, tar modellene og basis-URL-ene sine med seg. `ekte check` og
`ekte serve` bruker nøyaktig de samme profilene; `--no-user-kb` (eller
`EKTE_NO_USER_KB=1`) holder oppføringene og bryterne dine utenfor.

En modell med tomme `identity_keywords` lagres ikke slik: ekte fyller inn dens
egne merkeord fra leverandør- og modellnavnene (for eksempel `glm` og `z.ai`) og
viser en advarsel om å kontrollere dem, siden identitetskontrollen uten dem kunne
tatt modellen som nevner sin egen leverandør, for et konkurrerende merke.
Undersøkelsesprompten ber KI-assistenten uttrykkelig om dem.

Hver rapport registrerer profilen den reviderte mot (`knowledge`: leverandør,
modell, hvordan ID-en passet, kilden, og et fullstendig øyeblikksbilde med
innholdshash), så en rapport kan verifiseres også etter at kunnskapsbasen er
endret.

## Rapporter

`ekte check` og `ekte compare` skriver ut en konklusjon og skriver rapporten til
`reports/` (`--out-dir`) som JSON, Markdown, HTML og PDF (`--format all`,
standard); `--format json|md|html|pdf` skriver ett format. `--json` og
`--compact` skriver til stdout i stedet.

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

En rapport inneholder konklusjonen (risiko, sikkerhet, score, karakter), de
viktigste funnene med anbefalinger, scorene per dimensjon og **Dimension
details**, funnene fra hver detektor med bevis, ytelsesdelen, profilen fra
kunnskapsbasen som ble brukt, og probespråkene. Tekst som reléet styrer, sladdes
og escapes før den skrives.

## Personvern og lokale data

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
  på den, se **Overvåking** over). Uansett avslører en kopi av mappen ingen
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

## Ansvarlig bruk

ekte er et hjelpemiddel for black box-revisjon. Den **kan ikke bevise**:

- at en leverandør lagrer eller trener på promptene dine,
- at den alltid ruter til én bestemt modell (releer kan rute tilfeldig),
- svindel med fakturering utover det et uavhengig tokenanslag kan antyde.

Bruk rapporter til din egen aktsomhetsvurdering. **Ikke anklag en leverandør
offentlig** på grunnlag av én enkelt kjøring uten å ha vurdert utvalgsstørrelse,
kostnadsinnstillinger og lokal lovgivning. Kjør `ekte compare` mot en pålitelig
referanse før du trekker sterke konklusjoner.

## Mer dokumentasjon

| Dokument | Til |
|---|---|
| [Metodikk](docs/METHODOLOGY.nb.md) | Hvordan hver kontroll fungerer, scoreskalaen og forbeholdene |
| [Utviklerveiledning](DEVELOPER_GUIDE.nb.md) | Arkitektur, utviklingsoppsett, bidrag, oversettelser, Docker, utgivelser |
| [docs/CI.md](docs/CI.md) | GitHub Action: inndata, utdata, eksempler (på engelsk) |
| [docs/DOCKER.md](docs/DOCKER.md) | Kjøre nettgrensesnittet i en container (på engelsk) |
| [Stabilitet og kompatibilitet](docs/STABILITY.md) | Hva semver beskytter, utfasing, støttede Python-versjoner og systemer, oppgraderinger og nedgraderinger (på engelsk) |
| [docs/CLI.md](docs/CLI.md) | Alle kommandoer og alternativer, og avslutningskodene (engelsk) |
| [docs/SCHEMAS.md](docs/SCHEMAS.md) | JSON-formatene for rapport og webhook og deres `schema_version` (engelsk) |
| [CHANGELOG.md](CHANGELOG.md) | Hva som er endret i hver utgivelse (på engelsk) |
| [SECURITY.md](SECURITY.md) | Rapportere en sårbarhet (på engelsk) |

## Fra zing

ekte viderefører [zing](https://github.com/cenbonew/zing) (siste utgivelse var
0.11.0) under et nytt navn. Dette endres for en eksisterende installasjon:

- **Pakke og kommando.** `pip install ekte` (var `zing-audit`), kommandoen `ekte`
  (var `zing`), Python-pakken `ekte`. Tilleggene beholder navnene sine, f.eks.
  `pip install 'ekte[web]'`. De to pakkene deler ingen kommando eller modul, så
  `zing-audit` kan bli installert ved siden av ekte.
- **Miljøvariabler.** `EKTE_*` erstatter `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). En gammel `ZING_*`-variabel virker fortsatt
  så lenge `EKTE_*`-navnet ikke er satt; ekte nevner den én gang på stderr.
- **Datamappe.** Ved første kjøring kopierer ekte `~/.zing` til `~/.ekte`
  (historikk, overvåkinger, kunnskapsbase) hvis `~/.ekte` ikke finnes ennå, og
  jobber deretter bare fra `~/.ekte`. `~/.zing` blir stående som den er, for zing
  hvis den fortsatt kjører; slett den selv når du ikke lenger trenger den. En
  mappe satt med `EKTE_DATA_DIR`, `ZING_DATA_DIR` eller `--data-dir` brukes som den
  er.
- **Nettgrensesnitt.** Innstillinger for språk, tema og filtre og en hovednøkkel
  lagret i nettleserens passordbehandler følger med over. zings klassiske
  grensesnitt er borte: adressene (`/tools`, `/console`) åpner revisjonssiden (`/`).
- **Rapporter og prober.** Rapporter, webhooker og filnavn sier `ekte` (f.eks.
  `"tool": "ekte"`, `ekte-report.json`), og det gjør også probene som sendes til
  releer. Skript som ser etter `zing` i dem, må oppdateres.
- **Tidsplan.** Hele kompatibilitetslaget (`ZING_*`-reserveløsningen, kopien av `~/.zing`, overføringen av nettleserinnstillinger, informasjonskapsler og den lagrede hovednøkkelen, og adressene til det klassiske grensesnittet) er foreldet og fjernes i ekte **1.0.0** (1.0.0rc1 er første utgivelse uten det). Fram til da fungerer hver del som før, og varselet nevner denne versjonen; de gamle sideadressene `/v2/…` videresendes også til 1.0.0. ekte sletter aldri en gammel `~/.zing`, heller ikke når kopien er fjernet.

## Lisens

[Apache-2.0](LICENSE)
