# Nettgrensesnitt (`ekte serve`)

> [🇬🇧 English](../../../guide/web-ui.md) · [🇨🇳 中文](../../zh-CN/guide/web-ui.md) · [🇫🇷 Français](../../fr/guide/web-ui.md) · [🇪🇸 Español](../../es/guide/web-ui.md) · [🇵🇹 Português](../../pt/guide/web-ui.md) · [🇮🇹 Italiano](../../it/guide/web-ui.md) · [🇩🇪 Deutsch](../../de/guide/web-ui.md) · **🇳🇴 Norsk**

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
[Personvern og lokale data](privacy.md#personvern-og-lokale-data).

## Sider

Nettgrensesnittet leveres fra roten av adressen `ekte serve` åpner, med revisjonssiden på `/`. Tidligere adresser videresendes til tilsvarende side frem til 1.0.0 (se [Adresser i nettgrensesnittet](../../../reference/stability.md#surface-web-addresses)).

| Side | Adresse | Hva den er til |
|---|---|---|
| **Revisjon** | `/` | Revider et relé (eventuelt mot en referanse) og les rapporten; revisjoner av embedding og rerank starter også her, via velgeren for type endepunkt |
| **Overvåking** | `/watches` | Planlagte nye revisjoner med webhook-varsler |
| **Historikk** | `/history` | Hver revisjon kjørt på denne maskinen, gruppert etter relé + oppgitt modell, med trender |
| **Analyse** | `/analytics` | Releer og modeller sammenlignet over tid: nøkkeltall, diagrammer med datatabeller, rangeringslister |
| **Kunnskap** | `/kb` | Kunnskapsbasen i tre faner — modeller, leverandører, releer: bla gjennom, slå av/på, legg til dine egne |
| **Tilgjengelighet** | `/accessibility` | Samsvarsrapporten og tilgjengelighetserklæringen (ikonet ved siden av språkvelgeren); ennå uten manuell gjennomgang utført av et menneske (kjent begrensning) |

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

## Språk

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
