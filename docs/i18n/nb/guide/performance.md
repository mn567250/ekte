# Ytelse

> [🇬🇧 English](../../../guide/performance.md) · [🇨🇳 中文](../../zh-CN/guide/performance.md) · [🇫🇷 Français](../../fr/guide/performance.md) · [🇪🇸 Español](../../es/guide/performance.md) · [🇵🇹 Português](../../pt/guide/performance.md) · [🇮🇹 Italiano](../../it/guide/performance.md) · [🇩🇪 Deutsch](../../de/guide/performance.md) · **🇳🇴 Norsk**

Hver rapport har en **ytelsesdel**: forsinkelse, tid til første token (TTFT),
dekode- og ende-til-ende-tokens/s, forsinkelse og variasjon mellom biter,
rater for feil/tidsavbrudd/429, en nettverksoppdeling (TCP-tilkobling, TLS, en
tur-retur med `GET /models`, servertid) og kaldstart, hver som antall / min /
gjennomsnitt / p50 / p75 / p90 / p95 / p99 / maks / standardavvik.

Når den egne proben kjører, gir den score i dimensjonen **Ytelse**. Scoren
handler om **jevnhet**, ikke rå hastighet, så et tregt, men stødig endepunkt (en
lokal eller selvdriftet modell) trekkes ikke ned for ikke å være et datasenter;
kontrollene og poengene deres står i
[Metodikken](methodology.md#performance--ytelse). Ytelsesfunn har høyst lav alvorlighet: de flytter scoren, aldri
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

**Mislykkede forespørsler.** ekte skiller mellom hvor en forespørsel feilet. En
feil hos **reléet** (en HTTP-feilstatus, et tidsavbrudd mens ekte venter på
reléet, et avbrutt eller misformet svar) teller mot reléet og gjentas aldri. En
**nettverks**feil (proxyen ekte går gjennom, DNS, tilkobling eller TLS, før
reléet kunne svare) og en **lokal** feil (i ekte selv) skyldes ikke reléet:
forespørselen gjentas, én gang som standard (`EKTE_NON_RELAY_RETRIES`, 0 til
10), og feiler den fortsatt, telles den for seg (`network_errors`,
`local_errors`) og holdes utenfor feilratene. En sjekk der alle forespørslene
feilet slik, blir uavklart i stedet for å bli vurdert, og rapporten varsler at
kjøringen var svekket. Hver forespørselspost har sin klasse (`error_class`) og
om den ble gjentatt (`retried`); for kjøringer lagret tidligere utleder
webgrensesnittet klassen fra den lagrede feilen. Tidslinjediagrammene tegner dem
hver for seg: en feil hos reléet er et rødt ×, en nettverks- eller ekte-feil en
grå ◇, og et forsøk som aldri telles (et gjentatt) et mindre grått merke med
samme form; en merknad over forklaringen sier hvor mange forespørsler som
mislyktes på nettverksveien eller i ekte.

Bak en HTTPS-proxy feiler en forespørsel som proxyen ikke åpner en tunnel for,
med `ProxyError`. ekte tar vare på proxyens svar på `CONNECT`: posten har
statusen (`proxy_status`) og hvor lang tid proxyen brukte på å svare
(`proxy_wait_ms`), og bevisfilen beholder overskriftene og feilsiden (under
`proxy`; Squids feilside oppgir errno og adressen den prøvde). Statusen sier
hvem sitt problem det er, og datatabellen, varselet om svekket kjøring og
pålitelighetsrådet sier det samme: **502/503/504** — «relé-verten er utilgjengelig via
proxyen», vanligvis etter proxyens egen tilkoblingstidsgrense (ofte 60 s):
proxyen nådde ikke relé-verten, så sjekk om verten kan nås fra proxyen (DNS og
adresser, IPv6, en brannmur eller WAF som forkaster proxyens adresse,
lastbalanseringsnoder), ikke bare proxyen; **4xx** (407, 403) — «proxyen avviste
tunnelen»: autentiseringen eller policyen dens. Uansett er det fortsatt en
nettverksfeil som gjentas og ikke telles mot reléet.
