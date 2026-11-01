# Umstieg von zing

> [🇬🇧 English](../../../guide/migrating-from-zing.md) · [🇨🇳 中文](../../zh-CN/guide/migrating-from-zing.md) · [🇫🇷 Français](../../fr/guide/migrating-from-zing.md) · [🇪🇸 Español](../../es/guide/migrating-from-zing.md) · [🇵🇹 Português](../../pt/guide/migrating-from-zing.md) · [🇮🇹 Italiano](../../it/guide/migrating-from-zing.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/migrating-from-zing.md)

ekte setzt [zing](https://github.com/cenbonew/zing) (letztes Release 0.11.0)
unter neuem Namen fort. Was sich für eine bestehende Installation ändert:

- **Paket und Befehl.** `pip install ekte` (bisher `zing-audit`), der Befehl
  `ekte` (bisher `zing`), das Python-Paket `ekte`. Extras behalten ihre Namen,
  z. B. `pip install 'ekte[web]'`. Die beiden Pakete teilen weder Befehl noch
  Modul, `zing-audit` kann also neben ekte installiert bleiben.
- **Umgebungsvariablen.** `EKTE_*` ersetzt `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). Eine alte `ZING_*`-Variable wirkt weiter,
  solange ihr `EKTE_*`-Name nicht gesetzt ist; ekte nennt sie einmal auf stderr.
- **Datenverzeichnis.** Beim ersten Start kopiert ekte `~/.zing` nach `~/.ekte`
  (Verlauf, Überwachungen, Wissensbasis), falls `~/.ekte` noch nicht existiert, und
  arbeitet ab dann nur noch mit `~/.ekte`. `~/.zing` bleibt unverändert, für
  zing, falls es noch läuft; löschen Sie es selbst, sobald Sie es nicht mehr
  brauchen. Ein mit `EKTE_DATA_DIR`, `ZING_DATA_DIR` oder `--data-dir`
  gesetztes Verzeichnis wird so verwendet, wie es ist.
- **Weboberfläche.** Sprache, Design und Filter sowie ein im Passwortmanager
  des Browsers gespeicherter Hauptschlüssel werden übernommen. Die klassische
  Oberfläche von zing gibt es nicht mehr: Ihre Adressen (`/tools`, `/console`) öffnen die Prüfseite (`/`).
- **Berichte und Prüfanfragen.** Berichte, Webhooks und Dateinamen heißen
  `ekte` (z. B. `"tool": "ekte"`, `ekte-report.json`), ebenso die Prüfanfragen
  an Relays. Skripte, die darin nach `zing` suchen, müssen angepasst werden.
- **Zeitplan.** Die gesamte Kompatibilitätsschicht (der `ZING_*`-Fallback, die Kopie von `~/.zing`, die Übernahme von Browsereinstellungen, Cookies und dem gespeicherten Hauptschlüssel sowie die Adressen der klassischen Oberfläche) ist veraltet und wird in ekte **1.0.0** entfernt (1.0.0rc1 ist die erste Version ohne sie). Bis dahin funktioniert jeder Teil weiter, und sein Hinweis nennt diese Version; auch die alten Seitenadressen `/v2/…` leiten bis 1.0.0 weiter. ekte löscht ein altes `~/.zing` nie, auch nicht, wenn die Kopie entfernt ist.
