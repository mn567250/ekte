# Overvåking

> [🇬🇧 English](../../../guide/monitoring.md) · [🇨🇳 中文](../../zh-CN/guide/monitoring.md) · [🇫🇷 Français](../../fr/guide/monitoring.md) · [🇪🇸 Español](../../es/guide/monitoring.md) · [🇵🇹 Português](../../pt/guide/monitoring.md) · [🇮🇹 Italiano](../../it/guide/monitoring.md) · [🇩🇪 Deutsch](../../de/guide/monitoring.md) · **🇳🇴 Norsk**

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
[Docker](docker.md)); `ekte secret status | export | rotate`
håndterer den på kommandolinjen.
