# Revisjon av embedding, rerank, bilde og lyd

> [🇬🇧 English](../../../guide/other-endpoints.md) · [🇨🇳 中文](../../zh-CN/guide/other-endpoints.md) · [🇫🇷 Français](../../fr/guide/other-endpoints.md) · [🇪🇸 Español](../../es/guide/other-endpoints.md) · [🇵🇹 Português](../../pt/guide/other-endpoints.md) · [🇮🇹 Italiano](../../it/guide/other-endpoints.md) · [🇩🇪 Deutsch](../../de/guide/other-endpoints.md) · **🇳🇴 Norsk**

Disse endepunktene returnerer vektorer, rangeringer, bilder eller lyd i stedet for
chat, så ekte reviderer dem med målrettede prober i stedet for chatpromptene. Hver
av dem skriver ut en konklusjon og støtter `--json` og `--fail-on-risk`.

## Type endepunkt (surface), overvåking av embedding og rerank

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

## Embeddinger og rerank

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

## Generering av bilde og lyd (TTS)

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
