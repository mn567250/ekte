# Rapporter

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · **🇳🇴 Norsk**

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

## Bevisfiler

Med `--evidence PATH` (`check`, `compare`, `image`, `audio`), og som standard
for hver kjøring som lagres i historikken, skriver ekte også hver rå
HTTP-forespørsel og hvert svar fra kjøringen til én fil: JSON Lines i én
zstd-strøm, `<run_id>.jsonl.zst` (en katalog oppgitt som `PATH` får dette
navnet). Første linje beskriver kjøringen; hver videre linje er én forespørsel
med svaret, inkludert når hver del av svaret kom. `seq` på en linje er
forespørselens `seq` i rapportens `performance.requests`, så hver forespørsel
rapporten lister kan slås opp. Rapportens `evidence` navngir filen med SHA-256
og antall utvekslinger.

```bash
ekte check --base-url https://relay.example.com/v1 --model gpt-4o --evidence reports/
zstd -dc reports/<run_id>.jsonl.zst | jq -c 'select(.seq == 12)'
```

Hvert funn oppgir forespørslene det bygger på (`evidence_seqs`; tom når det
ikke bygger på noen, som TLS-kontrollen). `ekte evidence-export` tar filen
(eller id-en til en lagret kjøring) og gjør den om til HAR for en HAR-viser
eller nettleserens utviklerverktøy (`--as har`), et curl-skript som sender
forespørslene på nytt (`--as curl`; sett `EKTE_API_KEY` først, filen
inneholder aldri nøkkelen) eller ett JSON-dokument (`--as json`); `--seq`
velger forespørsler.

Nøkler og sensitive hoder fjernes før noe skrives (se [Personvern](privacy.md)).
Hver linje følger `ekte/schemas/evidence.schema.json`
([Skjemaer](../../../reference/schemas.md)). I nettgrensesnittet lister **Vis
bevis** under et funn i en lagret kjøring forespørslene i kontrollen bak det og
åpner hver rå forespørsel og hvert svar.
