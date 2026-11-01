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
