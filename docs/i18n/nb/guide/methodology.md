# ekte — Metodikk

> [🇬🇧 English](../../../guide/methodology.md) · [🇨🇳 中文](../../zh-CN/guide/methodology.md) · [🇫🇷 Français](../../fr/guide/methodology.md) · [🇪🇸 Español](../../es/guide/methodology.md) · [🇵🇹 Português](../../pt/guide/methodology.md) · [🇮🇹 Italiano](../../it/guide/methodology.md) · [🇩🇪 Deutsch](../../de/guide/methodology.md) · **🇳🇴 Norsk**

Dette dokumentet forklarer hvordan **ekte** kommer fram til konklusjonen sin:
hvilke black box-prober hver detektor sender, hvordan utfallene blir til poeng,
hvordan poengene blir til dimensjonsscorer og en samlet score, og hvordan
risikokonklusjonen avgjøres. Det beskriver den nåværende implementasjonen; hver
scoretabell nedenfor er detektorens publiserte skala (`SCALE` i
`ekte/detectors/*.py`) med de samme ordene som nettgrensesnittet viser under
**Scoreskala**.

> ekte rapporterer **black box-bevis på avvik og risiko, ikke kryptografiske
> bevis på svindel.** Se [Begrensninger og ansvarlig bruk](#begrensninger-og-ansvarlig-bruk).

---

## Grunnholdning

Et relé kan helt legitimt drive, oppdatere snapshots, samle kapasitet eller
bufre et oppstrøms endepunkt som ikke kan strømme. ekte behandler derfor hvert
enkelt signal som en *risikoindikator*, aldri som en konklusjon: funn bygger på
bevis først, er forsiktig formulert, og et tvetydig resultat forblir
**uavklart** i stedet for å presses inn i bestått eller ikke bestått.
Risikokonklusjonen når bare HIGH på harde bevis med høy alvorlighet, og den
sterkeste veien til bekreftelse er alltid **sammenligningsmodus**
(`ekte compare`): kjør de samme probene mot en *pålitelig referanse for den
oppgitte modellen* samtidig.

## Slik gir ekte score

### Detektorscore

Hver detektor publiserer sin **scoreskala** (`DetectorResult.scoring`, bygget med
`ekte/detectors/scale.py`): hvert mulige utfall av hver av kontrollene, med
status, alvorlighet og virkning på scoren. Hvert funn registrerer `outcome` det
traff, så rapport og atferd ikke kan være uenige. En skala bruker én av to
metoder:

- **Gjennomsnitt av kontroller** (`Scale`, metoden `mean_of_checks`): hver
  kontroll gir poeng; detektorscoren er gjennomsnittet av de telte kontrollene.
  Et utfall merket **Telles ikke** (typisk en uavklart kontroll) verken hever
  eller senker scoren.
- **Fradrag** (`DeductionScale`, metoden `deductions`): scoren starter på 100,
  funn trekker fra poeng (`Finding.deduction`) og/eller setter et tak på scoren
  (`Finding.cap`); det laveste taket gjelder.

En *parametrisert* kontroll bruker ett sett med rader på mange subjekter (for
eksempel hvert svarattributt): hvert subjekt gis score for seg, skalaen
publiseres én gang per kontroll, og rapportene viser subjektene under
kontrollen sin.

### Dimensjonsscore og status

ekte gir score i ti dimensjoner. En dimensjons score er **gjennomsnittet med lik
vekt av detektorenes scorer**: en detektor med mange kontroller veier ikke mer
enn en med få, og en detektor uten numerisk score utelates. Statusen er den
verste statusen detektorene konkluderte med, bortsett fra at et
HIGH/CRITICAL-funn tvinger fram **Ikke bestått** og et MEDIUM-funn hever
**Bestått** til **Advarsel**, uansett score. Hver rapport registrerer dette per
dimensjon (`DimensionScore.breakdown`: hver detektors score, om den ble telt, og
eventuell overstyring av status med funnene som forårsaket den) og viser det
under **Dimension details** (Markdown/HTML/PDF) og i radene som kan foldes ut i
**Kontroller per dimensjon** i nettgrensesnittet. En detektor som krasjer,
rapporteres med status **Feil** og avbryter aldri revisjonen.

### Samlet score, karakter og vekter

Den **samlede helsescoren** er det vektede gjennomsnittet over dimensjonene som
ga en score (`DIMENSION_WEIGHTS` i `ekte/scoring.py`). En dimensjon som ikke
kjørte (ikke i testsettet, eller ikke valgt i en `custom`-kjøring), faller ut,
og de gjenværende vektene normaliseres på nytt. Karakteren er A (≥ 90),
B (≥ 80), C (≥ 70), D (≥ 60) eller F.

| Dimensjon | ID | Vekt | Rolle |
|---|---|---|---|
| Modellidentitet | `model_identity` | 21 | kjerne |
| Kontekstvindu | `context_window` | 19 | kjerne |
| Påståtte egenskaper | `capability` | 13 | kjerne |
| Protokollsamsvar | `protocol` | 8 |  |
| Fakturering og forbruk | `billing` | 8 | kjerne |
| Tilkobling | `connectivity` | 7 |  |
| Ekte strømming | `streaming` | 6 |  |
| Pålitelighet ved samtidighet | `reliability` | 6 |  |
| Transportsikkerhet | `security` | 6 |  |
| Ytelse | `performance` | 6 |  |

Konklusjonen vurderes på dimensjonene som **kjørte** — en `custom`-kjøring
kontrollerer bare utvalget sitt. To grupper av dimensjoner betyr noe:

- **profildimensjonene** (modellidentitet, kontekstvindu, påståtte egenskaper)
  vurderes mot den oppgitte modellens profil i kunnskapsbasen;
- **kjernedimensjonene** er profildimensjonene pluss fakturering og forbruk:
  svikter de, leverer ikke reléet det det annonserer (en annen modell, et mindre
  kontekstvindu, manglende egenskaper, oppblåst fakturering).

### Risikokonklusjon

Risikonivået styres av **funnenes alvorlighet**, ikke av scoren. Funn i
tilkoblingsdimensjonen holdes utenfor stigen: et relé som er nede eller strupes,
kunne ikke vurderes, og det er ikke bevis på en annen modell.
**Transportrådene** holdes også utenfor (`ADVISORY_CHECKS` i `ekte/scoring.py`:
`security.tls`, `reliability.success_rate`, `reliability.latency`): ren HTTP,
feil eller treghet under last sier hvordan reléet nås, ikke hvilken modell det
leverer. De senker fortsatt score og status i dimensjonen sin, vises etter
funnene om bytte blant de viktigste funnene og nevnes i sammendraget som råd når
de er Middels eller høyere. Manipulering av integriteten og en gjengitt
API-nøkkel trapper fortsatt opp.

| Risiko | Etikett i grensesnittet | Når |
|---|---|---|
| `inconclusive` | For lite grunnlag | Ingenting brukbart å vurdere etter: når en profildimensjon kjørte, ga ingen av dem et brukbart resultat (Bestått, Advarsel eller Ikke bestått) — reléet kan ikke nås eller modellen har ingen profil; ellers ga ingen annen dimensjon enn tilkobling et slikt resultat |
| `high` | Falsk vare | Et CRITICAL-funn, et HIGH/CRITICAL-funn i en kjernedimensjon, eller to eller flere HIGH-funn |
| `medium` | Avvik funnet | Nøyaktig ett HIGH-funn utenfor kjernedimensjonene, eller et MEDIUM-funn i en kjernedimensjon |
| `low` | Stort sett pålitelig | Alle andre MEDIUM-funn |
| `clean` | Konsistent (trolig ekte) | Ingen av delene over |

Konklusjonen registrerer dimensjonene der funnene satte risikoen
(`verdict.drivers`), og dimensjonene som ga et brukbart resultat
(`verdict.checked`). Overskriften følger dem: den snakker om den oppgitte
modellen bare når modellidentitet er blant driverne, og nevner ellers driverne
(«Sterke bevis for at reléet ikke leverer det som annonseres: Kontekstvindu.»).
En konklusjon på ren eller lav uten et brukbart resultat for modellidentitet sier
at modellidentiteten ikke ble verifisert.

### Sikkerhet i konklusjonen

- **lav** — en profildimensjon kjørte, og den oppgitte modellen finnes ikke i
  kunnskapsbasen eller passet bare omtrentlig med en profil
  (`match_confidence` `fuzzy`; sammendraget sier det), eller for få dimensjoner
  ga et brukbart resultat;
- **middels** — minst to kjernedimensjoner ga et brukbart resultat (eller, i en
  kjøring uten kjernedimensjoner, minst to dimensjoner gjorde det);
- **høy** — en referanse ble brukt, *og* hver kjernedimensjon som kjørte, ga et
  brukbart resultat, eller sikkerheten var middels og LLM-dommeren returnerte en
  brukbar konklusjon.

## Testsett, detektorer og moduser

| Detektor | ID | Dimensjon | Fra testsett |
|---|---|---|---|
| Tilkobling og enkel fullføring | `connectivity` | Tilkobling | `smoke` |
| Samsvar med OpenAI-kompatibilitet | `protocol` | Protokollsamsvar | `standard` |
| Støtte for forespørselsattributter | `protocol_request` | Protokollsamsvar | `standard` |
| Tilgjengelighet av svarattributter | `protocol_response` | Protokollsamsvar | `standard` |
| Determinisme og korrekt hurtigbuffer | `determinism` | Protokollsamsvar | `deep` |
| Reelt kontekstvindu og avkorting | `context_window` | Kontekstvindu | `deep` |
| Modellidentitet og fingeravtrykk for nedgradering | `model_identity` | Modellidentitet | `standard` |
| Kvalitets-/nedgraderingsvurdering ved LLM-dommer | `quality_judge` | Modellidentitet | `deep` (bare med `--judge`) |
| Verifisering av påståtte egenskaper | `capability` | Påståtte egenskaper | `standard` |
| Verifisering av multimodale (syn-)egenskaper | `vision` | Påståtte egenskaper | `deep` |
| Ekte strømming | `streaming` | Ekte strømming | `standard` |
| Revisjon av token-/forbruksfakturering | `billing` | Fakturering og forbruk | `standard` |
| Pålitelighet og forsinkelse ved samtidighet | `reliability` | Pålitelighet ved samtidighet | `standard` |
| Signaler om transport og hemmelighetshåndtering | `security` | Transportsikkerhet | `smoke` |
| Påvisning av injisert systemprompt | `injected_prompt` | Transportsikkerhet | `deep` |
| Svarintegritet / manipulering | `integrity` | Transportsikkerhet | `deep` |
| Prefiks-hurtigbuffer for prompt (tidsmåling) | `prompt_cache` | Transportsikkerhet | `deep` |
| Ytelsesprobe | `performance` | Ytelse | `deep` (på `standard` bare i sammenligningsmodus, 5 forespørsler) |

- **smoke** kjører tilkobling og sikkerhet; **standard** legger til detektorene
  for protokoll, identitet, egenskaper, strømming, fakturering og pålitelighet;
  **deep** legger til probene for lang kontekst, determinisme, syn, injisert
  prompt, integritet, prompt-hurtigbuffer og ytelse (og dommeren med
  `--judge`); **full** kjører de samme detektorene som deep og måler ytelsen både
  med og uten strømming; **custom** kjører hver detektor i de valgte
  dimensjonene med dybden deep.
- **Ren kode (standard):** alle detektorer unntatt `quality_judge` avgjør med
  deterministisk kode — streng- og regex-kontroller, regning, tidsstatistikk.
  Ingen ekstra modell trengs.
- **Hybrid av kode og LLM (`--judge`):** `quality_judge` spør en separat
  konfigurert, pålitelig dommermodell (aldri målet) om målets svar leses som den
  oppgitte modellen. Uten `--judge-base-url` bruker sammenligningsmodus
  referansen som dommer.
- **Sammenligningsmodus** (`ekte compare`) gir probene en pålitelig referanse:
  `model_identity` registrerer referansens selvidentifikasjon ved siden av
  målets, `protocol_request` sender avviste parametere på nytt til referansen,
  `integrity` trapper et bytte som referansen ikke gjør, opp til CRITICAL,
  `quality_judge` viser dommeren begge sider, og `performance` prober begge
  endepunktene vekselvis. Sikkerheten kan bare nå høy med en referanse.
- **Kunnskapsbase:** den oppgitte modellens profil (`ekte/knowledge/data/*.yaml`
  pluss dine egne oppføringer i `kb.db`) leverer det oppgitte kontekstvinduet,
  maks utdata, tokenizer, egenskapsflagg, identitetsnøkkelord og
  atferdsfingeravtrykk som probene vurderes mot. Hver rapport registrerer
  profilen den brukte (`knowledge`). Den oppgitte ID-en passer med en profil
  etter eksakt ID, alias eller normalisert navn, ellers omtrentlig: etter det
  lengste profilnavnet den inneholder (`gpt-4o-2024-11-20-custom` → `gpt-4o`),
  med mindre resten av ID-en nevner et annet nivå eller en annen variant
  (`gpt-5-mini` er ikke `gpt-5`), eller, for en avkortet ID, bare når navnet til
  én enkelt modell begynner med den. En generisk eller tvetydig ID (`gpt-4`,
  `claude`, `gemini-2.5`) får derfor ingen profil i stedet for et gjettet, ofte
  billigere nivå. Fingeravtrykk for hele leverandøren gjelder for hver modell hos
  leverandøren; et som bare passer for noen modeller (en kunnskapsgrense, et
  størrelsesnivå), står bare på de modellene.
- **Promptspråk:** hver probetekst ligger i `ekte/prompts/en.json` og er på
  engelsk uansett grensesnittspråk; bare fingeravtrykk der språket *er* målingen,
  oppgir `prompt_lang` og `language_bound`. Hver rapport viser probespråkene den
  brukte (`prompt_languages`).
- **Resonnerende modeller:** en kort probe som ender ved utdatagrensen uten
  svaret, eller som kuttes etter at resonneringen tok minst halve grensen
  (`reasoning_tokens` rapportert), gjentas én gang med en grense på 4 096 tokens,
  så en modell som tenker før den svarer, ikke leses som at den feiler. Prober der
  grensen eller tidsmålingen er målingen (ytelse, prompt-hurtigbuffer,
  pålitelighet, injisert prompt, maks utdata, forespørselsattributtet
  `max_tokens`), gjentas aldri. Når et endepunkt er kjent for å resonnere
  (profilen sier `reasoning: true`, eller etter den første slike gjentakelsen),
  sendes korte prober med grensen på 4 096 tokens fra starten i stedet for to
  ganger.
- **Forespørselsparametere:** resonnerende modeller avviser noen parametere: på
  Chat Completions `max_tokens` (de tar `max_completion_tokens`), og på alle
  protokoller samplingsparametere som `temperature`. Klienten utelater
  parameterne profilen oppgir under `unsupported_params`, og sender
  utdatagrensen som `max_completion_tokens` når `max_tokens` står der. Et
  endepunkt uten profil som nevner en slik parameter i en 4xx, får forespørselen
  én gang til, tilpasset, og hver senere forespørsel går ut tilpasset fra
  starten; det avviste forsøket telles ikke som en reléfeil. Probene i
  `protocol_request` sendes nøyaktig slik de er bygget, siden det er selve
  avvisningen de vurderer.

---

## `connectivity` — Tilkobling

**Fanger.** Ingen triks direkte: det er porten alle andre detektorer avhenger av.
Den skiller en død eller feilkonfigurert nøkkel fra et relé som er verdt å
revidere.

**Slik virker den.** `GET /v1/models` (registrerer om den oppgitte modellen er
oppført) og én chat-fullføring ved `temperature=0` som ber modellen gjenta en
eksakt kanarimarkør; registrerer forsinkelse og det gjengitte `model`-feltet.

**Scoreskala** (`ekte/detectors/connectivity.py`):

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `connectivity.models` | Modellisten (/v1/models) svarte. | Bestått | 100 poeng |
|  | Modellisten (/v1/models) svarte ikke; noen releer slår den av. | Advarsel · Lav | 60 poeng |
| `connectivity.chat` | En chat-fullføring returnerte innhold og gjentok kanarien. | Bestått | 100 poeng |
|  | En chat-fullføring returnerte innhold, men gjentok ikke kanarien. | Bestått | 85 poeng |
|  | Chat-fullføringen mislyktes eller returnerte ikke innhold. | Ikke bestått · Høy | 0 poeng |

Detektorstatusen er den verste av kontrollene, så en avslått `/v1/models` gjør
den til en Advarsel selv når chat virker.

**Forbehold.** En manglende `/v1/models` er harmløs; mange releer slår den av. En
forbigående nettverksfeil eller 5xx kan få chat-kontrollen til å feile: kjør på
nytt. Tilkobling beviser ingenting om *hvilken* modell som svarte. Funnene hever
aldri risikokonklusjonen.

---

## `protocol` — Protokollsamsvar

**Fanger.** Releer der mellomvaren bryter protokollkontrakten (droppede turer,
ignorerte stoppsekvenser, feilformede feil, manglende eller tomme (null) svarfelt,
fjernede forespørselsparametere) og, via determinisme,
`cache.ignore-temperature`. Den dekker delvis `capability.json-tool-fakery`.

### `protocol` — Samsvar med OpenAI-kompatibilitet

**Slik virker den.** Tre prober: en samtale over flere turer som må huske en
farge fra en tidligere tur; en `stop`-sekvens som må kutte utdataen; og en
bevisst ugyldig forespørsel (tom `messages`) som må avvises med en 4xx, helst
med en feilbody i OpenAI-stil. Responses API har ingen `stop`-parameter, så mot
et mål med Responses API sendes ikke stopp-proben, og kontrollen noteres som
ikke aktuell (telles ikke) i stedet for å legge skylden på reléet.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `protocol.multi_turn` | Fargen fra en tidligere tur ble husket. | Bestått | 100 poeng |
|  | Fargen fra en tidligere tur ble ikke husket. | Advarsel · Middels | 55 poeng |
|  | Ikke noe brukbart svar å vurdere. | Uavklart · Lav | Telles ikke |
| `protocol.stop` | Utdataen stoppet ved stoppsekvensen. | Bestått | 100 poeng |
|  | Håndteringen av stopp kunne ikke bekreftes ut fra teksten. | Advarsel · Lav | 70 poeng |
|  | Tekst etter stoppsekvensen ble returnert. | Advarsel · Lav | 60 poeng |
|  | Ikke noe brukbart svar å vurdere. | Uavklart · Lav | Telles ikke |
|  | Responses API har ingen stop-parameter; ikke kontrollert, telles ikke. | Info | Telles ikke |
| `protocol.error_schema` | Avvist med en 4xx og en feilbody i OpenAI-stil. | Bestått | 100 poeng |
|  | Avvist med en 4xx, men bodyen er ikke i OpenAI-stil. | Advarsel · Lav | 80 poeng |
|  | Ikke noe HTTP-svar; håndteringen av klientfeil kunne ikke bekreftes. | Advarsel · Lav | 55 poeng |
|  | En annen HTTP-status; håndteringen av klientfeil kunne ikke bekreftes. | Advarsel · Lav | 55 poeng |
|  | Den ugyldige forespørselen førte til en serverfeil (5xx). | Ikke bestått · Middels | 35 poeng |
|  | Den ugyldige forespørselen ble godtatt (2xx). | Ikke bestått · Middels | 30 poeng |

### `protocol_response` — Tilgjengelighet av svarattributter

**Slik virker den.** Ett vanlig kall uten strømming; hvert attributt i målets
protokoll (OpenAI Chat Completions, Anthropic Messages eller OpenAI Responses;
katalog i `ekte/detectors/wire_attrs.py`) vurderes på den rå bodyen. Sentrale
attributter er f.eks. `model`, `choices[0].message.role/content`,
`finish_reason`, `usage.prompt_tokens`, `usage.completion_tokens` og
`usage.total_tokens` (som må være lik summen av de to); mindre attributter er
`id`, `object`, `created`/`created_at`, `choices[0].index` og `type`. En null der
et antall må være positivt (`completion_tokens: 0` for et ikke-tomt svar), gis
score som null, ikke som gyldig.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `protocol_response.core` (Sentrale svarattributter) | Til stede med en gyldig verdi. | Bestått | 100 poeng |
|  | Til stede, men null eller tom (f.eks. completion_tokens: 0). | Ikke bestått · Middels | 20 poeng |
|  | Til stede med feil type eller verdi (f.eks. total ≠ summen av delene). | Advarsel · Middels | 40 poeng |
|  | Mangler i svaret. | Ikke bestått · Middels | 0 poeng |
| `protocol_response.minor` (Mindre svarattributter) | Til stede med en gyldig verdi. | Bestått | 100 poeng |
|  | Til stede, men null eller tom. | Advarsel · Lav | 50 poeng |
|  | Til stede med feil type eller verdi. | Advarsel · Lav | 70 poeng |
|  | Mangler i svaret. | Advarsel · Lav | 60 poeng |
| `protocol_response.call` (Probe for svarattributter) | Probekallet returnerte ingen svarbody å vurdere. | Uavklart · Lav | Telles ikke |

### `protocol_request` — Støtte for forespørselsattributter

**Slik virker den.** Hver forespørselsparameter i protokollen sendes (omtrent fem
kall). Parametere med en observerbar effekt får sitt eget kall og må vise den:
`system`/`instructions` fulgt, utdatagrensen som ender med
`finish_reason: length`, `n: 2` som returnerer to valg, `logprobs` returnert.
Parametere som bare skal godtas (`temperature`, `top_p`, `seed`, straffer,
`user`, `top_k`, `metadata`), deler ett kall og prøves én og én på nytt bare når
det avvises. En 4xx regnes som en begrensning i modellen (telles ikke) heller enn
en avvisning når kunnskapsbasen oppgir parameteren under `unsupported_params`,
når en samplingsparameter sendes til en resonnerende modell, eller når en
referanse på samme protokoll også avviser den. Verktøy og JSON-modus hører til
`capability`, `stop` til `protocol`, usage i strømmen til `streaming`.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `protocol_request.param` (Forespørselsparametere) | Godtatt, og effekten er synlig i svaret. | Bestått | 100 poeng |
|  | Godtatt (effekten kan ikke observeres fra ett svar). | Bestått | 100 poeng |
|  | Godtatt, men effekten mangler i svaret. | Advarsel · Lav | 50 poeng |
|  | Avvist med en 4xx (muligens en begrensning i selve modellen). | Advarsel · Lav | 40 poeng |
|  | Avvist med en 4xx, mens referansen godtar den. | Ikke bestått · Middels | 15 poeng |
|  | Avvist, men selve modellen støtter den ikke; telles ikke. | Info | Telles ikke |
|  | Serverfeil eller ikke noe svar; telles ikke. | Uavklart · Lav | Telles ikke |

### `determinism` — Determinisme og korrekt hurtigbuffer

**Slik virker den.** Fire identiske kreative prompter ved `temperature=1.0`
(uten seed): en ekte modell varierer, og byte-identisk utdata i alle prøvene tyder
på en hurtigbuffer for svar som ignorerer sampling. Minst tre av de fire prøvene
må være brukbare (og alle brukbare identiske) for å konkludere med bufring; med
færre er kontrollen uavklart. Konklusjonen undertrykkes for resonnerende
modeller, som med rette ignorerer temperaturen. To identiske faktaprompter ved
`temperature=0` er bare til informasjon.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `determinism.temp1_variability` | Gjentatte prøver ved temperature=1.0 var forskjellige, slik ekte sampling gir. | Bestått | 100 poeng |
|  | Prøvene var identiske, men resonnerende modeller ignorerer med rette temperaturen. | Info | 100 poeng |
|  | Alle brukbare prøver (minst 3) ved temperature=1.0 var byte-identiske, noe som tyder på bufring av svar. | Advarsel · Middels | 55 poeng |
|  | Færre enn 3 brukbare prøver ved temperature=1.0 å vurdere. | Uavklart · Lav | Telles ikke |
| `determinism.temp0_stability` | Identiske svar ved temperature=0 (forventet); til informasjon, gir ikke score. | Info | Telles ikke |
|  | Svarene var forskjellige ved temperature=0; til informasjon, gir ikke score. | Info | Telles ikke |
|  | Ikke noe brukbart svar å vurdere. | Uavklart · Lav | Telles ikke |

**Forbehold.** Gatewayer kan legge til leverandørspesifikke ekstrafelt; bare
manglende eller ugyldige påkrevde felt flagges. Oversettelse mellom dialektene
Anthropic↔OpenAI omformer med rette noen strukturer. Bekreft en mistenkt feil
ved å gjenta den og, der det er mulig, i sammenligningsmodus.

---

## `context_window` — Kontekstvindu

**Fanger.** `context.window-truncation` (et relé annonserer 128K/200K/1M, men
kutter prompten i det stille) og `context.lost-in-middle-rag` (et billig
RAG-/oppsummeringsmellomledd sender bare deler av prompten videre).

**Slik virker den.** Gjenkalling av en nål i høystakken ved `temperature=0`: en
unik markør bygges inn i fylltekst uten gjentakelser, og modellen må returnere
den.

- **Probet vindu.** Proben kjører opp til `upper` = det oppgitte vinduet, begrenset
  av `--max-context-tokens` (standard 200K). Hver konklusjon vurderes mot
  `upper`, aldri mot delen av et større oppgitt vindu over taket.
- **Størrelsene er ekte tokens.** ektes innebygde tokenanslag teller denne
  fyllteksten omtrent 12 % (o200k) til 15 % (cl100k) for lavt sammenlignet med
  ekte tokenizere, så hver prompt bygges med størrelse ÷ 1,2 etter anslaget (nål
  og spørsmål inkludert): et trinn på størrelse N holder seg innenfor N ekte
  tokens. Størrelsene i bevisene (`size`, `effective_window`, `top_rung`) er
  disse budsjettene i ekte tokens; radene i stigen har også anslaget en prompt ble
  bygget etter (`heuristic_tokens`).

1. En stige med høyst sju størrelser, som halveres nedover fra et **øverste trinn
   på 90 % av `upper`** (så ingen trinn når hele vinduet, og det blir plass til
   svaret og chat-malen) til et gulv på 1K (`context_probe_floor_tokens`); et lite
   vindu senker gulvet til en firedel av øverste trinn (et vindu på 2K prober
   ~460, ~920 og ~1,8K). Hver størrelse probes med nålen ved **start**-kanten
   (dybde 0,0) først: en avkorting som beholder spørsmålet på slutten av prompten,
   kan bare droppe starten (en lokal server som kutter prompten til sin
   kontekstlengde, beholder slutten), så en gjenkalling der godkjenner størrelsen
   i ett kall. En bom bekreftes ved sluttkanten (dybde 0,95); huskes slutten,
   probes starten én gang til med en ny nål, og en bom nummer to gir størrelsen
   ikke bestått som **avkorting foran** (nevnt i konklusjonens bevis). Høyst tre
   kall per størrelse; stigen stopper ved den første bekreftede feilen.
2. To trinn med binærsøk mellom den siste huskede og den første feilende
   størrelsen.
3. Lost-in-the-middle: ved min(32K, målt vindu) plasseres nålen på dybdene 0,1,
   0,5 og 0,9. Huskes start og slutt, men ikke midten, probes midten én gang til
   med en ny nål; bare en bom nummer to er et funn.
4. En 4xx der meldingen nevner kontekstlengden, er en avvisning av størrelsen; en
   avvisning av `max_tokens` (resonnerende modeller) prøves på nytt med
   `max_completion_tokens` og leses aldri som et tak.
5. En probe som får tidsavbrudd, eller som får en feil som svar (en annen avvist
   parameter, en HTTP-feil, en 5xx, et tomt eller feilformet svar), avslutter
   stigen uten å telle som en feil: vinduet over den siste huskede størrelsen
   rapporteres som ikke verifisert (uavklart, gir ikke score), aldri som
   avkorting eller `no_recall`. Bare et svar uten nålen er en bom.

Det målte vinduet (den største huskede størrelsen) sammenlignes med `upper`:
gjenkalling på øverste trinn er konsistent (eller, når det oppgitte vinduet er
større enn taket, **verifisert opp til taket**: vinduet over det ble ikke prøvd);
under det trekker konklusjonen fra andelen av øverste trinn som ikke ble husket —
en WARN fra halvparten av `upper` og opp, en FAIL under halvparten. Uten et
oppgitt vindu rapporteres målingen, men gir ikke score.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `context_window.window` (Effektivt kontekstvindu) | Gjenkallingen holdt på øverste trinn (90 % av det probede vinduet): ingen fradrag. | Bestått | Ingen fradrag |
|  | Gjenkallingen er verifisert opp til probens tak; det oppgitte vinduet over det ble ikke prøvd. | Bestått | Ingen fradrag |
|  | Gjenkallingen holdt opp til 50–90 % av det probede vinduet; trekker fra andelen av øverste trinn som ikke ble husket. | Advarsel · Middels | opptil −50 poeng |
|  | Gjenkallingen sviktet under halvparten av det probede vinduet; trekker fra andelen av øverste trinn som ikke ble husket. | Ikke bestått · Høy | opptil −100 poeng |
|  | Ikke engang den minste probestørrelsen fikk nålen husket. | Ikke bestått · Høy | −100 poeng |
| `context_window.lost_in_middle` | Starten og slutten ble husket, men ikke midten, to ganger. | Advarsel · Middels | −15 poeng |
| `context_window.rejected_below_claim` | En prompt godt under det oppgitte vinduet ble avvist som for lang. | Ikke bestått · Høy | Ingen fradrag |
| `context_window.measured` | Ikke noe oppgitt vindu å sammenligne med: bare målt, gir ikke score. | Info | Ingen fradrag |
| `context_window.no_ladder` | Ingen probestørrelse passet mellom gulvet og taket. | Uavklart · Lav | Ingen fradrag |
| `context_window.timed_out` | En probe fikk tidsavbrudd før det oppgitte vinduet ble nådd: et tregt endepunkt, ikke bevis på avkorting. | Uavklart · Lav | Ingen fradrag |
| `context_window.probe_error` | En probe fikk en feil som svar (en avvist parameter, en HTTP- eller serverfeil) før øverste trinn: ikke bevis på avkorting. | Uavklart · Lav | Ingen fradrag |

**Forbehold.** Ekte modeller med lang kontekst mister også nåler i midten, så bare
en feil ved **kanten** leses som avkorting. Gjenkalling nær taket er
sannsynlighetsbasert; kjør på nytt før du konkluderer. Proben begrenses av
`--max-context-tokens`, så et større vindu prøves ikke i sin helhet (øk det for å
probe videre). Øverste trinn ligger på 90 % av vinduet, og tokenbudsjettet er
forsiktig, så de siste ~10–15 % av et vindu probes aldri. Sammenlign med en
pålitelig referanse for å skille modellens atferd fra mellomleddets.

---

## `model_identity` — Modellidentitet

**Fanger.** `downgrade.silent-substitution` (et premiumnavn på en billigere eller
åpen bakende), og signaler om `downgrade.reasoning-collapse`,
`downgrade.quantized-distilled` og `downgrade.partial-probabilistic-routing` når
de endrer atferden.

### `model_identity` — Modellidentitet og fingeravtrykk for nedgradering

**Slik virker den.** Tre uavhengige signaler:

1. **Selvidentifikasjon** ved `temperature=0`, sammenlignet som hele ord mot
   profilens identitetsnøkkelord (det ekte merket) og en liste over konkurrerende
   merker (profilens `identity_forbidden` pluss en innebygd liste). Et
   konkurrerende merke teller bare når det ekte merket mangler; «I am Claude, not
   GPT» er en harmløs sammenligning.
   Det ekte merket er profilens `identity_keywords` pluss profilens egne navn:
   leverandørnøkkelen, det første navnet i leverandørens visningsnavn, det første
   ordet i modell-ID-en og familien, og den leverandørens andre navn i den
   innebygde listen (`z.ai` dekker også `zhipu`). En modell som nevner sin egen
   leverandør, er derfor aldri et konkurrerende merke, selv når
   `identity_keywords` er tom. Avledede navn overstyrer aldri
   `identity_forbidden`, generiske ord («ai», «platform», …) teller aldri, og en
   plattforms eget merke teller ikke for en annen leverandørs modell som den
   leverer.
   Merkeord som også er hverdagsord (`step`, `command`, `seed`, `spark`, `meta`,
   `yi`, `grok`), teller bare i dette svaret om selvidentifikasjon og bare skrevet
   som et navn («made by Meta», «Command R», «grok-2»; i starten av en setning
   eller et listepunkt bare med en versjon, «Step-2»); fingeravtrykkssvar teller
   dem aldri, så «let me think step by step» er ikke et konkurrerende merke. En
   leverandør som eier et slikt ord, beholder det som sitt eget.
2. **Atferdsfingeravtrykk** fra kunnskapsbasen (kunnskapsgrense, særegenheter i
   tokenizeren, formatering, språkbundne prober, …): opptil seks prober i ren kode,
   hver kontrollert med `expect_contains`, `expect_contains_any`,
   `expect_not_contains` eller `expect_regex`; utdata begrenset til 512 tokens. En
   probe som trenger mer utdata (som en kontroll av maks utdata), hoppes over,
   oppføres som Info, og en annen probe tar plassen. Et avvikende fingeravtrykk
   trekker fra sin vektandel av 100 poeng (høyst 25); ett alene forblir LOW, to
   eller flere legger til et samlet MEDIUM-funn.
3. **Gjengitt `model`-felt** fra et vanlig kall: snapshot-suffikser og aliaser
   tåles; et ord for et mindre nivå (`mini`, `flash`, `lite`, `8b`, …) eller en
   annen familie flagges.

Uten en profil i kunnskapsbasen er detektoren uavklart. Den er også uavklart og
uten score (`model_identity.no_evidence`) når verken selvidentifikasjonen eller
noe fingeravtrykk returnerte et brukbart svar og det gjengitte `model`-feltet
ikke avviker: et relé som avviser eller tømmer hver forespørsel, gir ingen
identitetsbevis, og et ekko av det forespurte navnet beviser ingenting alene.
Delvise bevis gir score som vanlig.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `model_identity.self_id` | Selvbeskrivelsen nevnte det ekte merket. | Bestått | Ingen fradrag |
|  | Selvbeskrivelsen nevnte et konkurrerende merke og ikke det ekte. | Ikke bestått · Høy | tak 20 |
|  | Selvbeskrivelsen nevnte det ekte merket og et konkurrerende (vanligvis en harmløs sammenligning). | Advarsel · Lav | Ingen fradrag |
|  | Selvbeskrivelsen nevnte verken det ekte merket eller et konkurrerende. | Advarsel · Lav | Ingen fradrag |
|  | Ikke noe brukbart svar å vurdere. | Uavklart | Ingen fradrag |
| `model_identity.fp` (Atferdsfingeravtrykk) | Svaret stemte med den oppgitte modellens egen atferd. | Bestått | Ingen fradrag |
|  | Svaret avvek fra den egne atferden: trekker fra probens vektandel av 100 poeng. | Advarsel · Lav | opptil −25 poeng |
|  | Svaret nevnte et konkurrerende merke og ikke det ekte: trekker fra probens vektandel. | Ikke bestått · Høy | opptil −25 poeng · tak 20 |
|  | Ikke noe brukbart svar å vurdere. | Uavklart | Ingen fradrag |
|  | Proben trenger mer utdata enn identitetstaket på 512 tokens; ikke kjørt. | Info | Ingen fradrag |
| `model_identity.fp_aggregate` | To eller flere atferdsfingeravtrykk avvek. | Advarsel · Middels | Ingen fradrag |
| `model_identity.model_field` | Det gjengitte model-feltet stemte med den forespurte modellen. | Bestått | Ingen fradrag |
|  | Det gjengitte model-feltet nevner en annen eller mindre modell. | Advarsel · Middels | Ingen fradrag |
|  | Svaret hadde ikke noe brukbart model-felt. | Uavklart | Ingen fradrag |
| `model_identity.no_evidence` | Ingen selvidentifikasjon eller fingeravtrykkssvar var brukbart, og model-feltet avvek ikke: gir ikke score. | Uavklart | Ingen fradrag |

### `quality_judge` — Kvalitets-/nedgraderingsvurdering ved LLM-dommer

**Slik virker den.** Bare med `--judge` (deep og oppover). Et kort sett med
prompter som skiller nivåer (resonnering i flere steg, en presis
programmeringsoppgave, nyansert etterlevelse av instruksjoner), går til målet og,
i sammenligningsmodus, til referansen; en separat pålitelig dommer ser bare
svarene og returnerer en konklusjon og en sikkerhet. Dommeren får vite den
oppgitte modellen (`claimed_model` når den er satt, ellers den forespurte
ID-en). En dommerkonklusjon er HIGH bare når dommeren oppga **høy** sikkerhet og
en brukbar referanse bekreftet forskjellen — en som returnerte et ikke-tomt svar
for hver probe målet svarte på. En lav, middels, manglende eller ukjent sikkerhet
forblir MEDIUM, og det gjør også en referanse som feilet eller lot prober stå
ubesvart.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `quality_judge.verdict` (LLM-dommerens konklusjon) | Dommeren fant svarene i samsvar med den oppgitte modellen. | Bestått | 95 poeng |
|  | Dommeren fant svarene ulike den oppgitte modellen (lav, middels eller ingen oppgitt sikkerhet). | Advarsel · Middels | 50 poeng |
|  | Dommeren er sikker på at svarene er ulike den oppgitte modellen (ingen brukbar referanse). | Advarsel · Middels | 25 poeng |
|  | Dommeren er sikker, og en pålitelig referanse bekreftet forskjellen. | Ikke bestått · Høy | 25 poeng |
|  | Dommeren kunne ikke legge seg fast på en konklusjon. | Uavklart · Lav | Telles ikke |
|  | Ingen svar fra målet å vurdere. | Uavklart · Lav | Telles ikke |

**Forbehold.** Offisielle API-er oppdaterer snapshots i det stille, så avvik kan
være harmløs drift; ekte rapporterer «avvikende», aldri «bevist bytte». Modeller
hallusinerer sine egne navn, så selvidentifikasjon alene avgjør aldri. Et relé
kan memorere et fast sett med prober. En konklusjon med høy sikkerhet krever
sammenligningsmodus mot det nøyaktige oppgitte snapshotet.

**Ikke implementert.** Fingeravtrykk via embedding-avstand (i LLMmap-stil),
fordelingsbaserte tester med to utvalg og sampling i stort volum for
sannsynlighetsbasert ruting er forskningsretninger, ikke nåværende kontroller.

---

## `capability` — Påståtte egenskaper

**Fanger.** `capability.json-tool-fakery`: verktøykall, JSON-modus, strenge
skjemaer, utdatalengde eller syn som påstås, men ikke leveres — eller
*over*oppfylles, et hint om en erstatning.

### `capability` — Verifisering av påståtte egenskaper

**Slik virker den.** Fire prober ved `temperature=0`, hver vurdert mot profilens
egenskapsflagg:

- **Verktøy:** ett verktøy tilbudt med `tool_choice: "auto"` og en uttrykkelig
  forespørsel om å bruke det; et verktøykall må komme tilbake. Argumenter levert
  som et objekt i stedet for JSON-strengen OpenAI returnerer, flagges som en motor
  som ikke er OpenAI.
- **JSON-modus:** `response_format: json_object` må returnere et objekt som kan
  tolkes, med den forespurte verdien.
- **Strengt skjema:** et strengt `json_schema`; samsvar verifiseres når modellen
  påstår det, og noteres (til informasjon) når den ikke gjør det. Hoppes over uten
  profil.
- **Maks utdata:** en lang generering begrenset til min(oppgitt maks utdata,
  2048) tokens; å nå taket eller en troverdig lengde er bestått, å stoppe under en
  firedel av det flagges.

En observasjon uten en påstand å verifisere — ikke noe verktøykall eller
JSON-objekt når funksjonen ikke påstås, eller et hvilket som helst resultat for
strengt skjema når profilen sier at modellen mangler strenge skjemaer — noteres,
men telles ikke, så en modell aldri trekkes ned for noe ingen har påstått.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `capability.tools` | Et verktøykall kom tilbake for en uttrykkelig forespørsel om verktøybruk. | Bestått | 100 poeng |
|  | Verktøykall er påstått, men ikke noe verktøykall kom tilbake. | Ikke bestått · Middels | 0 poeng |
|  | Ikke noe verktøykall kom tilbake, og verktøykall er ikke påstått. | Info | Telles ikke |
|  | Ikke noe brukbart svar å vurdere. | Uavklart · Lav | Telles ikke |
| `capability.tools.encoding` | Verktøyargumentene kom som et objekt, ikke som JSON-strengen OpenAI returnerer. | Advarsel · Lav | Telles ikke |
| `capability.json_mode` | JSON-modus returnerte et objekt som kan tolkes, med den forespurte verdien. | Bestått | 100 poeng |
|  | Et JSON-objekt kom tilbake med feil verdi; JSON-modus er ikke påstått. | Info | Telles ikke |
|  | Ikke noe JSON-objekt som kan tolkes, kom tilbake; JSON-modus er ikke påstått. | Info | Telles ikke |
|  | JSON-modus er påstått, men ikke noe gyldig objekt med verdien kom tilbake. | Ikke bestått · Middels | 0 poeng |
|  | Ikke noe brukbart svar å vurdere. | Uavklart · Lav | Telles ikke |
| `capability.json_schema` | Det strenge skjemaet er påstått, og svaret fulgte det. | Bestått | 100 poeng |
|  | Det strenge skjemaet ble ikke håndhevet, i samsvar med påstanden. | Info | Telles ikke |
|  | Svaret fulgte skjemaet selv om den oppgitte modellen mangler strenge skjemaer. | Info | Telles ikke |
|  | Det strenge skjemaet er påstått, men svaret fulgte det ikke. | Advarsel · Lav | 40 poeng |
|  | Ikke noe brukbart svar å vurdere. | Uavklart · Lav | Telles ikke |
| `capability.max_output` | Utdataen fortsatte opp til det forespurte tokentaket. | Bestått | 100 poeng |
|  | Utdataen stoppet før taket ved en troverdig lengde. | Bestått | 90 poeng |
|  | Utdataen stoppet under en firedel av den forespurte lengden. | Advarsel · Lav | 70 poeng |
|  | Utdataen stoppet under en firedel av forespørselen til tross for et stort oppgitt maksimum. | Advarsel · Lav | 60 poeng |
|  | Ikke noe brukbart svar å vurdere. | Uavklart · Lav | Telles ikke |

### `vision` — Verifisering av multimodale (syn-)egenskaper

**Slik virker den.** Deep og oppover, og bare når profilen påstår syn: en liten
ensfarget oransje PNG generert under kjøring sendes innebygd med et spørsmål om
fargen som skal besvares med ett ord. En ren tekstmodell som erstatning kan ikke
pålitelig nevne fargen.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `vision.color` | Modellen nevnte fargen på testbildet. | Bestått | 100 poeng |
|  | Syn er påstått, men modellen nevnte ikke fargen på bildet. | Advarsel · Middels | 0 poeng |
|  | Ikke noe brukbart svar å vurdere. | Uavklart | Telles ikke |
| `vision.not_claimed` | Syn er ikke påstått, så ikke noe bilde ble sendt. | Info | Telles ikke |

**Forbehold.** Ekte modeller hopper av og til over et verktøy eller gir ugyldig
JSON; én probe per egenskap er et signal, ikke en rate. Oversettelse mellom
dialekter omformer med rette JSON for verktøykall. Proben for maks utdata prøver
ikke hele det oppgitte taket. Ett bilde er en indikasjon, ikke bevis.

---

## `streaming` — Ekte strømming

**Fanger.** `stream.fake-streaming`: reléet bufrer hele svaret fra oppstrøms og
spiller det av igjen som én eller noen få biter, så gevinsten i forsinkelse
forsvinner.

**Slik virker den.** Én strømmet forespørsel (`max_tokens` 256,
`stream_options.include_usage`) der ankomsttidene for bitene registreres. Tre
signaler på bufring: **få biter** (to eller færre) og **sent første token** (TTFT
over 90 % av total varighet), begge vurdert bare når minst 220 tegn kom tilbake,
og **jevne opphold** (fire eller flere biter der oppholdene er nesten like,
CV < 0,1, og under 2 ms: sluppet ut samlet). TTFT er det første synlige
innholdstokenet, så for en resonnerende modell (påstått av kunnskapsbasen, eller
som rapporterer resonneringstokens i usage), som tenker før den svarer, noteres et
sent første token bare og telles ikke som bufring; signalene få biter og jevne
opphold teller fortsatt. En strøm uten usage-bit flagges for seg. En strøm som
lykkes, men ikke leverer noe innhold, er uavklart og gir ikke score.
Når modellen strømmer resonneringen sin (resonneringsdeltaer, tenkeblokker,
resonneringshendelser i Responses), måles i stedet det første tokenet av begge
slag: en ekte strøm begynner å resonnere tidlig, så en strøm der både
resonneringen og svaret kommer helt til slutt, er bufring også for en
resonnerende modell.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `streaming.healthy` | Mange biter, et tidlig første token og spredte opphold: ekte strømming. | Bestått | Ingen fradrag |
| `streaming.few_chunks` | Tegn på bufring: det første trekker fra 40 poeng, et andre 20, flere ingenting. | Advarsel · Middels | opptil −40 poeng |
| `streaming.late_ttft` | Tegn på bufring: det første trekker fra 40 poeng, et andre 20, flere ingenting. | Advarsel · Middels | opptil −40 poeng |
| `streaming.reasoning_ttft` | Sent første token fra en resonnerende modell (den tenker før den svarer): til informasjon, telles ikke som bufring. | Info | Ingen fradrag |
| `streaming.uniform_gaps` | Tegn på bufring: det første trekker fra 40 poeng, et andre 20, flere ingenting. | Advarsel · Middels | opptil −40 poeng |
| `streaming.no_usage` | Ingen usage-bit i strømmen: trekker fra 15 poeng når ingenting er bufret. | Advarsel · Lav | opptil −15 poeng |
| `streaming.no_content` | Strømmen lyktes, men leverte ikke noe innhold å vurdere; gir ikke score. | Uavklart · Lav | Telles ikke |
| `streaming.failed` | Strømmeforespørselen mislyktes. | Ikke bestått · Høy | tak 0 |

Altså: ekte 100 · usage mangler 85 · ett signal på bufring 60 · to eller flere 40
· mislyktes 0 · ikke noe innhold: ingen score.

**Forbehold.** Korte utdata, en rask liten modell eller variasjon i nettverket kan
likne et støt. Et oppstrøms endepunkt som ikke kan strømme, tvinger reléet til å
bufre helt legitimt; les det som «reléet strømmer ikke», ikke som ond vilje. Kjør
på nytt og sammenlign med en referanse som er kjent for å strømme.

---

## `billing` — Fakturering og forbruk

**Fanger.** `billing.usage-inflation` (for høyt rapporterte prompt- eller
fullføringstokens), `billing.missing-usage` (ingen, delvis eller inkonsistent
`usage`) og, som støttende signal, `prompt.injected-system-prompt`.

**Slik virker den.** Ett deterministisk kall (et kjent avsnitt som skal
oppsummeres, `temperature=0`). Prompten og det synlige svaret telles uavhengig
med en språkbevisst heuristikk (omtrent ±25 %), for hver modellfamilie: ekte
bruker ikke noe tokenizer-bibliotek og laster ikke ned noe. Rapporterte
prompttokens over 2,5× anslaget og mer enn 50 tokens over det regnes som
oppblåsing. Fullføringstokens fra en resonnerende modell inkluderer med rette
skjulte resonneringstokens og flagges ikke; ellers er fullføringstokens over 3×
anslaget og mer enn 80 tokens over det en myk advarsel, aldri en feil, fordi
anslaget for et kort svar er usikkert. `total` må være lik `prompt + completion`
(±2), og en total uten fordelingen flagges. En undertelling (under halvparten av
anslaget) er til informasjon (ikke til skade for kjøperen).

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `billing.request-failed` | Ikke noe brukbart svar å vurdere. | Uavklart · Lav | Ingen fradrag |
| `billing.missing-usage` | Svaret inneholdt ikke noe tokenforbruk i det hele tatt. | Advarsel · Middels | tak 75 |
| `billing.usage-inflation` | Rapporterte prompttokens er langt over det uavhengige anslaget. | Ikke bestått · Høy | tak 55 |
| `billing.usage-inflation-completion` | Rapporterte fullføringstokens er langt over et heuristisk anslag. | Advarsel · Middels | tak 70 |
| `billing.reasoning-tokens` | Fullføringstokens overstiger den synlige teksten, som forventet for en resonnerende modell. | Info | Ingen fradrag |
| `billing.usage-undercount-prompt` | Rapporterte prompttokens er godt under anslaget (ikke til skade for kjøperen). | Info | Ingen fradrag |
| `billing.usage-undercount-completion` | Rapporterte fullføringstokens er godt under anslaget (ikke til skade for kjøperen). | Info | Ingen fradrag |
| `billing.total-mismatch` | Rapportert total er ikke lik prompt- + fullføringstokens. | Advarsel · Lav | tak 90 |
| `billing.partial-usage` | Usage oppgir en total uten fordeling på prompt/fullføring. | Advarsel · Middels | tak 80 |
| `billing.usage-consistent` | Rapportert forbruk er innenfor toleransen til det uavhengige anslaget. | Bestått | Ingen fradrag |

En mislykket probeforespørsel etterlater detektoren uten score.

**Forbehold.** Chat-maler og spesialtokens legger til en liten fast forskyvning,
så et nøyaktig samsvar forventes ikke. Hvis den leverte modellen er en annen enn
den oppgitte, er den «riktige» tokenizeren ukjent. Skjulte resonneringstokens kan
ikke telles utenfra. Én probe måler én størrelse; en multiplikator som skalerer
med størrelsen, krever gjentatte kjøringer eller sammenligningsmodus.

---

## `reliability` — Pålitelighet ved samtidighet

**Fanger.** Deler av `throttle.rate-limit-quality`: et relé som feiler eller kryper
ved moderat parallellitet.

**Slik virker den.** Et støt av identiske små forespørsler
(`--reliability-requests`, standard 8) med avgrenset samtidighet
(`--concurrency`, standard 3). Suksessraten beregnes over forespørslene som
faktisk ble forsøkt: HTTP 429 er ærlig struping og telles for seg. Scoren trekker
fra den mislykkede andelen; en p95-forsinkelse over 30 s beholder 85 % av det som
er igjen. Én mislykket forespørsel (altså én forbigående 5xx av standardens 8),
eller høyst 10 % av et større støt, er en Advarsel så lenge minst 80 % lyktes;
flere er Ikke bestått. Detektorstatusen er den verste av funnene. Disse funnene er
transportråd: de hever aldri risikokonklusjonen.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `reliability.success_rate` | Alle forsøkte forespørsler i støtet lyktes. | Bestått | Ingen fradrag |
|  | Én forespørsel, eller høyst 10 % av de forsøkte, mislyktes (80 %+ lyktes); trekker fra den mislykkede andelen. | Advarsel · Lav | opptil −20 poeng |
|  | Flere forespørsler enn det mislyktes; trekker fra den mislykkede andelen. | Ikke bestått · Middels | opptil −100 poeng |
|  | Alle forespørsler ble strupet (HTTP 429): gir ikke score. | Uavklart · Lav | Ingen fradrag |
| `reliability.latency` | p95-forsinkelse over 30 s under last; trekker fra 15 % av gjenværende score. | Advarsel · Lav | opptil −15 poeng |
| `reliability.rate_limited` | Deler av støtet ble strupet: ærlig struping, telles ikke. | Info | Ingen fradrag |
| `reliability.skipped` | Pålitelighetsproben var slått av. | Info | Ingen fradrag |

De egne hastighetsmålingene hører til dimensjonen `performance`.

**Forbehold.** Ekte leverandører blir også tregere og returnerer 429 under reell
last. Ett øyeblikksbilde går glipp av atferd etter tid på døgnet; `ekte watch`
reviderer på nytt etter en tidsplan.

**Ikke implementert.** Kvalitetsprober over tid og under bestemte lastforhold og
signalene for delte nøkler oppstrøms (`infra.shared-upstream-key`: kvote som synker
i ro, lekkede forespørsels-ID-er fra oppstrøms) står på veikartet.

---

## `security` — Transportsikkerhet

**Fanger.** `prompt.injected-system-prompt`, `integrity.response-tampering`,
bevis i retning av `privacy.prompt-logging-leakage` (prefiksbufring), og
grunnleggende hygiene for transport og hemmeligheter.

### `security` — Signaler om transport og hemmelighetshåndtering

**Slik virker den.** Kontrollerer at endepunktet bruker HTTPS, at API-nøkkelen
aldri vises ordrett i et svar, og hvilke svarhoder som avslører en oppstrøms
tjeneste eller proxy (`server`, `via`, `x-powered-by`, `x-upstream-*`,
`x-litellm-*`, …; til informasjon). Den oppgir også grensen: logging av prompter
og delte nøkler oppstrøms kan ikke bevises utenfra. Ren HTTP til denne maskinen
eller et privat nettverk (`localhost`, `127.x`, `192.168.x`, `*.local`, … — en
selvdriftet modell) er bare en Advarsel uten tak, siden nøkkelen ikke krysser
internett; ren HTTP til andre verter forblir Ikke bestått · Høy. Uansett er
`security.tls` et transportråd og hever aldri risikokonklusjonen.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `security.tls` | Endepunktet bruker HTTPS. | Bestått | Ingen fradrag |
|  | Endepunktet bruker ikke HTTPS; API-nøkkelen sendes i klartekst. | Ikke bestått · Høy | tak 40 |
|  | Ren HTTP til en vert på lokalt eller privat nettverk; API-nøkkelen krysser ikke internett. | Advarsel · Lav | Ingen fradrag |
| `security.key_echo` | API-nøkkelen vises ikke i svaret. | Bestått | Ingen fradrag |
|  | API-nøkkelen vises ordrett i svaret. | Ikke bestått · Høy | tak 30 |
| `security.headers` | Ingen svarhoder avslører oppstrøms (til informasjon). | Bestått | Ingen fradrag |
|  | Svarhoder avslører oppstrøms eller proxy (til informasjon). | Info · Lav | Ingen fradrag |
|  | Ingen svarhoder å undersøke. | Uavklart | Ingen fradrag |
| `security.note` | Logging av prompter og delte nøkler oppstrøms kan ikke bevises utenfra. | Info | Ingen fradrag |

### `injected_prompt` — Påvisning av injisert systemprompt

**Slik virker den.** To uavhengige tegn. (1) En **fast overhead i
inndatatokens**: to brukermeldinger av ulik størrelse uten systemmelding;
rapporterte `prompt_tokens` minus det uavhengige anslaget må holde seg lite. En
overhead på minst 30 tokens som holder seg konstant (innenfor 16) på tvers av
begge størrelsene, leses som en skjult prompt foran heller enn proporsjonal
oppblåsing. (2) En **lekkasjeprobe** som ber modellen gjenta eventuelle
foregående instruksjoner. Bare begge sammen når MEDIUM.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `injected_prompt.verdict` (Injisert systemprompt) | Overheaden i inndatatokens er liten, og ingen skjulte instruksjoner lekket. | Bestått | 100 poeng |
|  | Instruksjonsaktig tekst lekket når det ble spurt (svakt alene). | Info · Lav | 85 poeng |
|  | En stor fast overhead i inndatatokens, konstant på tvers av meldingsstørrelser. | Advarsel · Lav | 75 poeng |
|  | En fast overhead i inndatatokens og en lekket innledning sammen. | Advarsel · Middels | 55 poeng |
|  | Ingen brukbare tellinger av prompttokens til å måle overheaden. | Uavklart | Telles ikke |

### `integrity` — Svarintegritet / manipulering

**Slik virker den.** Kanarier med kjent svar der verdiene er følsomme — en
installasjons-URL og en `pip install`-pakke med fast versjon — må komme tilbake
ordrett. Et eksakt ekko er bestått, et manglende ekko (omskrivning, avvisning) er
uavklart, og bare en **utbytting av verdier** som bevarer strukturen, regnes som
manipulering. I sammenligningsmodus er et bytte som den pålitelige referansen ikke
gjør, CRITICAL. Bare en referanse som returnerer kanarien uendret, bekrefter: en
referanse som feiler eller ikke returnerer noe brukbart, bekrefter ingenting, så
byttet forblir MEDIUM (beviset `baseline_unavailable`). Et svar som kuttes ved
utdatagrensen, er uavklart, ikke et bytte.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `integrity.verdict` (Svarintegritet) | Kanarier med kjent svar kom tilbake uendret. | Bestått | 100 poeng |
|  | En kanariverdi ble byttet ut (ennå ikke bekreftet av en referanse). | Ikke bestått · Middels | 45 poeng |
|  | En kanariverdi ble byttet ut, mens den pålitelige referansen beholdt den uendret. | Ikke bestått · Kritisk | 10 poeng |
|  | Ingen kanari ble gjentatt ordrett, så manipulering kunne ikke vurderes. | Uavklart | Telles ikke |

### `prompt_cache` — Prefiks-hurtigbuffer for prompt (tidsmåling)

**Slik virker den.** Et unikt prefiks på ~1 200 tokens strømmes to ganger (kaldt,
så varmt) og et annet kontrollprefiks én gang. Når den varme TTFT er under
halvparten av både den kalde og kontrollens TTFT, og minst 150 ms raskere enn den
kalde, er prefiksbufring aktiv. Alltid til informasjon: prefiksbufring er en
legitim optimalisering.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `prompt_cache.verdict` (Bufring av promptprefiks) | Et gjentatt promptprefiks kom tilbake mye raskere: prefiksbufring er aktiv. | Info | Telles ikke |
|  | Et gjentatt promptprefiks var ikke tydelig raskere. | Info | Telles ikke |
|  | En eller flere tidsprober returnerte ingen brukbar tidsmåling. | Uavklart | Telles ikke |

**Forbehold.** Modeller dikter opp falske «systemprompter» når de blir bedt om å
lekke, så en lekkasje alene forblir LOW. Oversettelse mellom dialekter omformer
JSON for verktøykall; bare en utbytting av *verdier* teller. Betinget manipulering
(bare for noen nøkkelord, klienter eller etter en oppvarming) kan unngå et
begrenset sett med prober. Logging er **umulig å bevise** med black box-tester fra
klienten, og ekte kan ikke vise deling av hurtigbuffer *mellom brukere* med én
nøkkel: at et tidssignal mangler, beviser ikke at prompter ikke logges.

---

## `performance` — Ytelse

**Hva den måler.** Hvor **jevnt** endepunktet er, ikke hvor raskt. En lokal eller
selvdriftet modell som er treg, men stødig, får god score; rå hastighet teller
bare mot en referanse.

**Slik virker den.** Den egne proben kjører på deep, full og custom, og på
standard bare i sammenligningsmodus (5 forespørsler per side, for få for
jevnhetskontrollene). Per endepunkt: tre `GET /models`-ping, én
oppvarmingsforespørsel (rapportert som kaldstart), `--performance-requests` like
forespørsler (standard 100) med `--performance-max-tokens` utdatatokens
(standard 128), og så på deep/full et støt med `--concurrency`. Hver forespørsel
kan ikke bufres: en tilfeldig forespørsels-ID innleder prompten, emnene roterer,
og ingen parametere for hurtigbuffer eller resonnering sendes; et svar som likevel
kommer bufret tilbake, flagges og holdes utenfor statistikken. Proben strømmer som
standard (`--performance-non-streaming` for releer som ikke kan strømme); full
måler begge modusene, vekselvis. I sammenligningsmodus veksler mål og referanse,
så drift i nettverket rammer begge likt.
Bufrede inndatatokens teller bare når de dekker minst halve prompten: lokale
servere (Ollama, llama.cpp, LM Studio) gjenbruker den bufrede chat-malen for hver
prompt, og det er ikke et lagret svar.
Hvert kall i revisjonen tas vare på som en forespørselspost
(`performance.requests`, bare tall, aldri tekst fra prompt eller svar); `start_ms`
regnes fra rapportens `started_at` (UTC), så tidspunktet for hvert kall kan
gjenskapes.

Jevnheten bruker haleforhold (p90 ÷ p50 for forsinkelse og TTFT, p50 ÷ p10 for
gjennomstrømning), som én enkelt avvikende forespørsel ikke kan flytte slik den
flytter et standardavvik; de krever minst 10 rene prøver. Referansen er den
pålitelige referansen, ellers området `performance.decode_tps` i profilen fra
kunnskapsbasen.

| Kontroll | Utfall | Status | Effekt |
|---|---|---|---|
| `performance.summary` | Forsinkelse, TTFT og gjennomstrømning ble målt. | Info | Telles ikke |
|  | Ingen av probeforespørslene lyktes. | Uavklart | Telles ikke |
| `performance.latency_consistency` | Forsinkelsen er jevn (haleforhold høyst 1,3). | Bestått | 100 poeng |
|  | Forsinkelsen er stabil (haleforhold høyst 1,75). | Bestått | 85 poeng |
|  | Forsinkelsen varierer merkbart (haleforhold høyst 2,5). | Advarsel · Lav | 65 poeng |
|  | Forsinkelsen er ujevn (haleforhold over 2,5). | Ikke bestått · Lav | 40 poeng |
|  | For få prøver til å vurdere hvor jevn forsinkelsen er. | Info | Telles ikke |
| `performance.ttft_consistency` | Tiden til første token er jevn (haleforhold høyst 1,3). | Bestått | 100 poeng |
|  | Tiden til første token er stabil (haleforhold høyst 1,75). | Bestått | 85 poeng |
|  | Tiden til første token varierer merkbart (haleforhold høyst 2,5). | Advarsel · Lav | 65 poeng |
|  | Tiden til første token er ujevn (haleforhold over 2,5). | Ikke bestått · Lav | 40 poeng |
|  | For få prøver til å vurdere hvor jevn tiden til første token er. | Info | Telles ikke |
| `performance.throughput_consistency` | Gjennomstrømningen er jevn (haleforhold høyst 1,3). | Bestått | 100 poeng |
|  | Gjennomstrømningen er stabil (haleforhold høyst 1,75). | Bestått | 85 poeng |
|  | Gjennomstrømningen varierer merkbart (haleforhold høyst 2,5). | Advarsel · Lav | 65 poeng |
|  | Gjennomstrømningen er ujevn (haleforhold over 2,5). | Ikke bestått · Lav | 40 poeng |
|  | For få prøver til å vurdere hvor jevn gjennomstrømningen er. | Info | Telles ikke |
| `performance.errors` | Høyst 2 % av probeforespørslene mislyktes. | Bestått | 100 poeng |
|  | Opptil 10 % av probeforespørslene mislyktes eller fikk tidsavbrudd. | Advarsel · Lav | 80 poeng |
|  | Mange probeforespørsler mislyktes eller fikk tidsavbrudd. | Ikke bestått · Lav | 50 poeng |
| `performance.load_stability` | Forsinkelsen holder seg under samtidig last (høyst 1,5x). | Bestått | 100 poeng |
|  | Forsinkelsen øker under samtidig last (opptil 3x). | Advarsel · Lav | 80 poeng |
|  | Forsinkelsen forverres kraftig under samtidig last (over 3x). | Ikke bestått · Lav | 55 poeng |
| `performance.cache_hit` | Unike probeprompter kom tilbake fra en hurtigbuffer (holdt utenfor statistikken). | Advarsel · Lav | 60 poeng |
|  | Referansen leverte unike probeprompter fra en hurtigbuffer (gir ikke score). | Info | Telles ikke |
| `performance.reference` | Gjennomstrømningen er på linje med referansen for denne modellen. | Bestått | 100 poeng |
|  | Tregere enn referansen (f.eks. lokal eller mindre maskinvare); ikke en feil. | Info | Telles ikke |
|  | Mye raskere enn referansen (forenlig med en mindre modell). | Advarsel · Lav | 60 poeng |
| `performance.reasoning` | Modellen bruker skjulte resonneringstokens; TTFT inkluderer tenking. | Info | Telles ikke |
| `performance.relay_overhead` | Forsinkelse sammenlignet med den pålitelige referansen (til informasjon). | Info | Telles ikke |
| `performance.skipped` | Ytelsesproben var slått av. | Info | Telles ikke |

**Forbehold.** Forsinkelse avhenger av nettverksveien og leverandørens last i
øyeblikket; gjenta et dårlig jevnhetsresultat på et annet tidspunkt. Områdene i
kunnskapsbasen er bevisst brede medianer fra de egne API-ene, og et tregere mål
noteres, gis aldri score. Alle funn har høyst LOW-alvorlighet, så denne
dimensjonen flytter scoren, aldri risikokonklusjonen.

---

## Embedding-overflaten

En revisjons **overflate** (`chat` som standard, eller `embedding`) velger
detektorene; testsettet bestemmer fortsatt dybden. En embedding-revisjon sender
bare `POST /embeddings`-forespørsler og gjenbruker chat-dimensjonene og den felles
scoren 0–100 og karakteren A–F, med vekter per overflate. Et dimensjonsavvik
(MODEL_IDENTITY, HIGH) gjør risikoen HIGH, slik en byttet modell gjør i chat.

| Kontroll | ID | Dimensjon | Hva den tester |
|---|---|---|---|
| Tilkobling | `embed.connectivity` | Tilkobling | endepunktet returnerer velformede vektorer |
| Vektordimensjon | `embed.dimension` | Modellidentitet | returnert lengde mot den oppgitte modellens egen dimensjon (kunnskapsbasen, eller `claimed_dimensions`) |
| Gjengitt modell | `embed.model_field` | Modellidentitet | svarets `model`-felt nevner den oppgitte modellen |
| Vektordrift | `embed.drift` | Modellidentitet | vektoren for den faste probeinndataen mot forrige lagrede kjøring |
| Determinisme | `embed.determinism` | Pålitelighet ved samtidighet | samme inndata to ganger gir cosinus ≥ 0,9999 |
| Atskillelse | `embed.distinctness` | Påståtte egenskaper | urelaterte inndata gir cosinus under 0,98 |
| Ytelsesprobe | `performance.embed` | Ytelse | forsinkelse, kaldstart, gjennomstrømning, batchskalering |

**Vektordrift.** Hver kjøring lagrer de første 64 komponentene av enhetsvektoren
for én fast inndata. Neste kjøring av samme mål og oppgitte modell (`ekte embed`,
en embedding-revisjon startet på nettgrensesnittets Revisjon-side via velgeren for
type endepunkt, eller en embedding-overvåking) sammenligner vektoren sin med den
prøven: cosinus **≥ 0,995** er stabil (PASS), **0,95 til 0,995** har flyttet seg
(WARN, MEDIUM: en ny utrulling eller kvantisering), under **0,95** eller en annen
lengde betyr at modellen er byttet (FAIL, HIGH). Den første kjøringen har ikke noe
å sammenligne med og registrerer referansen (INFO).

**Ytelsesprobe.** Avgrenset som chat-proben: den kjører på deep, full og custom,
og på standard bare med en referanse. Etter et ping og en oppvarmingsforespørsel
(kaldstart) sender den like forespørsler med én inndata, batcher med 16 inndata og,
på deep/full, et samtidig støt. Hver inndata har en tilfeldig nonce; identiske
vektorer for ulike inndata flagges som bufret og holdes utenfor statistikken. Den
rapporterer forsinkelse p50/p95, kaldstart, inndata/s og inndatatokens/s,
jevnheten i forsinkelse/gjennomstrømning, feil og stabilitet under last.
**Batchskalering** sammenligner en batchs forsinkelse per inndata med en
enkeltforespørsels: ved 0,6x eller mer deles batchen opp eller serialiseres
(lineært, WARN LOW). Det finnes ingen hastighetsreferanse i kunnskapsbasen; rå
hastighet teller bare mot en referanse.

**Ytelsesprobe for rerank** (`performance.rerank`, overflaten `rerank`). Samme
probe for `POST /rerank`, avgrenset som chat-proben. Hver runde sender én spørring
over 4 dokumenter og én over 32; støtet bruker 4. Hver spørring og hvert dokument
har forespørselens tilfeldige nonce; finmaskede scorer (ikke et rundt tall med 3
desimaler) som gjentas nøyaktig for et annet sett med dokumenter, flagges som
bufret og holdes utenfor statistikken (en deterministisk scorer kan gjenta dem for
de samme dokumentene); en 200 som lar dokumenter stå uten score, regnes som en
mislykket forespørsel. Den rapporterer forsinkelse p50/p95, kaldstart,
dokumenter/s og inndatatokens/s, jevnheten i forsinkelse/gjennomstrømning, feil og
stabilitet under last. **Skalering med antall dokumenter** sammenligner
forsinkelsen per dokument for 32 dokumenter med den for 4: ved 0,6x eller mer
deles dokumentene opp eller serialiseres (lineært, WARN LOW).

---

## Rerank-overflaten

En rerank-revisjon (`surface` `rerank`) sender bare `POST /rerank`-forespørsler og
gis score på den felles skalaen 0–100 og karakteren A–F med egne vekter:
modellidentitet 30, påståtte egenskaper 30, ytelse 20, pålitelighet ved
samtidighet 10, tilkobling 10. En mislykket rangering med kjent svar (påståtte
egenskaper, HIGH) eller en byttet modell (modellidentitet, HIGH) gjør risikoen
HIGH.

| Kontroll | ID | Dimensjon | Hva den tester |
|---|---|---|---|
| Tilkobling | `rerank.connectivity` | Tilkobling | endepunktet returnerer en velformet rangering |
| Kjent svar | `rerank.known_answer` | Påståtte egenskaper | en probe med ett åpenbart relevant dokument rangerer det først |
| Gjengitt modell | `rerank.identity` | Modellidentitet | svarets `model`-felt nevner den oppgitte modellen |
| Rangeringsdrift | `rerank.drift` | Modellidentitet | den faste probens rangering og scorer mot forrige lagrede kjøring |
| Determinisme | `rerank.determinism` | Pålitelighet ved samtidighet | samme spørring to ganger gir samme rangering og scorer |
| Ytelsesprobe | `performance.rerank` | Ytelse | forsinkelse, kaldstart, dokumenter/s, skalering med antall dokumenter |

**Rangeringsdrift.** Hver kjøring lagrer rangeringen og de avrundede scorene for
én fast probe med gradert relevans. Neste kjøring av samme mål og oppgitte modell
sammenligner med den: samme rangering med scorer innenfor **0,01** (den største
endringen i score, relativt til scoren bare der den er over 1) er stabil (PASS),
**0,01 til 0,1** har flyttet seg (WARN, MEDIUM), en annen rangering eller en
endring på mer enn **0,1** betyr at modellen er byttet (FAIL, HIGH). Den første
kjøringen registrerer referansen (INFO); en endret probe tas aldri for drift.

**Ytelsesprobe.** `performance.rerank`, beskrevet sammen med de andre probene
over: avgrenset som chat-proben (deep, full og custom; på standard bare med en
referanse), 4 mot 32 dokumenter per spørring, spørringer variert med nonce for å
oppdage bufring, og et svar som lar dokumenter stå uten score, regnes som en
mislykket forespørsel. Det finnes ingen hastighetsreferanse i kunnskapsbasen; rå
hastighet teller bare mot en referanse.

---

## Triks → detektor

De 16 relétriksene fra undersøkelsen fordeler seg slik på ekte.

| # | Triks (ID) | Alvorlighet | Detektor(er) | Nåværende dekning |
|---|---|---|---|---|
| 1 | `downgrade.silent-substitution` | kritisk | `model_identity`, `quality_judge` | selvidentifikasjon, fingeravtrykk, `model`-felt; dommer; sammenligningsmodus |
| 2 | `downgrade.reasoning-collapse` | kritisk | `model_identity`, `quality_judge` | bare fingeravtrykk og dommer; ingen egen vanskelighetsstige ennå |
| 3 | `downgrade.quantized-distilled` | høy | `quality_judge`, `model_identity` | dommer med en referanse; ingen fordelingstest ennå |
| 4 | `downgrade.partial-probabilistic-routing` | høy | `model_identity` | bare hvis de utvalgte forespørslene treffer erstatningen; sampling i stort volum står på veikartet |
| 5 | `context.window-truncation` | høy | `context_window` | stige med nål ved kanten + binærsøk; målt mot oppgitt |
| 6 | `context.lost-in-middle-rag` | høy | `context_window` | dybdene 0,1/0,5/0,9 ved en middels størrelse |
| 7 | `stream.fake-streaming` | middels | `streaming` | antall biter, tidspunkt for første token, jevnhet i oppholdene |
| 8 | `billing.usage-inflation` | høy | `billing` | uavhengig heuristisk tokenanslag for én kjent probe |
| 9 | `billing.missing-usage` | middels | `billing`, `protocol_response`, `streaming` | om usage finnes, fordelingen og regnestykket; usage-bit i strømmen |
| 10 | `privacy.prompt-logging-leakage` | høy | `prompt_cache` | prefiksbufring etter TTFT (til informasjon); deling mellom brukere og logging kan fortsatt ikke bevises med én nøkkel |
| 11 | `infra.shared-upstream-key` | høy | — | veikart (kvote som synker i ro, lekkede forespørsels-ID-er fra oppstrøms) |
| 12 | `cache.ignore-temperature` | middels | `determinism` | byte-identisk utdata ved temperatur 1,0; undertrykt for resonnerende modeller |
| 13 | `prompt.injected-system-prompt` | middels | `injected_prompt`, `billing` | fast overhead i inndatatokens (to størrelser) + lekkasjeprobe |
| 14 | `throttle.rate-limit-quality` | middels | `reliability`, `performance` | suksessrate (429 for seg), haleforsinkelse, stabilitet under last; prober over tid står på veikartet |
| 15 | `capability.json-tool-fakery` | middels | `capability`, `protocol_request` | verktøy, JSON-modus, strengt skjema, parametere; én probe hver, ikke rater |
| 16 | `integrity.response-tampering` | kritisk | `integrity` | kanarier med kjent URL/pakke; CRITICAL når en referanse bekrefter |

---

## Begrensninger og ansvarlig bruk

**ekte rapporterer avvik og risiko, ikke bevis på svindel.** Konklusjonen bruker
forsiktig språk (ren / lav / middels / høy / uavklart), holder tvetydige resultater
uavklart og trapper bare opp til høy på harde bevis med høy alvorlighet.

**Hva black box-revisjon ikke kan bevise:**

- **Logging av prompter eller lagring av data.** Et tidssignal er bevis på
  bufring; at det mangler, beviser ikke at prompter ikke logges.
- **Svarintegritet** uten svar signert av leverandøren: betinget manipulering kan
  unngå et begrenset sett med prober.
- **Delte nøkler eller nøkkeltyveri:** høyst en *risiko* for en delt pool.
- **Harmløs drift mot bytte:** offisielle API-er oppdaterer snapshots i det stille.
- **Konstant ruting:** et relé kan rute tilfeldig, og én revisjon ser bare
  forespørslene den sendte.

**Metode.** Funn som avhenger av nøyaktig sammenligning, bruker `temperature=0` og
avgrensede prompter. Hvert funn har med seg bevisene sine (inndata, observerte
verdier, antall, tidsmålinger), og hver rapport registrerer profilen,
promptspråkene og innstillingene den kjørte med, så et resultat kan kontrolleres
uavhengig. Et relé kan være testbevisst: kjør på nytt på andre tidspunkter, og
foretrekk sammenligningsmodus mot en pålitelig referanse for **nøyaktig det
oppgitte snapshotet** — det er den sterkeste måten å skille modellens atferd fra
reléets atferd på, og den eneste måten å nå høy sikkerhet.

**Ansvarlig varsling.** **Ikke** anklag en leverandør offentlig på grunnlag av en
ekte-rapport. Før du handler, kjør på nytt med flere prøver og på andre
tidspunkter, bekreft med sammenligningsmodus, og utelukk drift, nettverk og last
som forklaringer. Hvis en alvorlig bekymring består, ta det først opp privat med
leverandøren, som spørsmål om observert atferd og ikke som anklager.
