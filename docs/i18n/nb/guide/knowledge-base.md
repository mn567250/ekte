# Kunnskapsbase

> [🇬🇧 English](../../../guide/knowledge-base.md) · [🇨🇳 中文](../../zh-CN/guide/knowledge-base.md) · [🇫🇷 Français](../../fr/guide/knowledge-base.md) · [🇪🇸 Español](../../es/guide/knowledge-base.md) · [🇵🇹 Português](../../pt/guide/knowledge-base.md) · [🇮🇹 Italiano](../../it/guide/knowledge-base.md) · [🇩🇪 Deutsch](../../de/guide/knowledge-base.md) · **🇳🇴 Norsk**

ekte vurderer et relé mot **profilen** til modellen det oppgir: eget
kontekstvindu, maks utdata, kunnskapsgrense, tokenizer, egenskapsflagg,
identitetsnøkkelord og atferdsfingeravtrykk. De medfølgende profilene dekker
OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM og Moonshot (`ekte kb` viser
dem). Det finnes tre lag, der de senere vinner:

1. **Medfølgende** profiler, én YAML-fil per leverandør i
   [`ekte/knowledge/data/`](../../../../ekte/knowledge/data).
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
slått opp til en annen profil. En modell du har lagt til med en medfølgende ID erstatter den
(rapportert som at den *skygger* for den), men endrer aldri en medfølgende
leverandørs egne innstillinger; fingeravtrykk slås sammen etter ID. Å slå av en
medfølgende modell, leverandør eller et relé på **Kunnskap**-siden lagres også i
`kb.db`: en modell-ID som er slått av, slås ikke lenger opp, og en leverandør som
er slått av, tar modellene og basis-URL-ene sine med seg. `ekte check` og
`ekte serve` bruker nøyaktig de samme profilene; `--no-user-kb` (eller
`EKTE_NO_USER_KB=1`) holder oppføringene og bryterne dine utenfor.

En modell med tomme `identity_keywords` lagres ikke slik: ekte fyller inn modellens
egne merkeord fra leverandør- og modellnavnene (for eksempel `glm` og `z.ai`) og
viser en advarsel om å kontrollere dem, siden identitetskontrollen uten dem kunne
tatt modellen som nevner sin egen leverandør, for et konkurrerende merke.
Undersøkelsesprompten ber KI-assistenten uttrykkelig om dem.

Hver rapport registrerer profilen den reviderte mot (`knowledge`: leverandør,
modell, hvordan ID-en passet, kilden, og et fullstendig øyeblikksbilde med
innholdshash), så en rapport kan verifiseres også etter at kunnskapsbasen er
endret.
