# Fra zing

> [🇬🇧 English](../../../guide/migrating-from-zing.md) · [🇨🇳 中文](../../zh-CN/guide/migrating-from-zing.md) · [🇫🇷 Français](../../fr/guide/migrating-from-zing.md) · [🇪🇸 Español](../../es/guide/migrating-from-zing.md) · [🇵🇹 Português](../../pt/guide/migrating-from-zing.md) · [🇮🇹 Italiano](../../it/guide/migrating-from-zing.md) · [🇩🇪 Deutsch](../../de/guide/migrating-from-zing.md) · **🇳🇴 Norsk**

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
