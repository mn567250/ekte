# Berichte

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` und `ekte compare` geben ein Urteil aus und schreiben den Bericht nach
`reports/` (`--out-dir`) als JSON, Markdown, HTML und PDF (`--format all`, der
Standard); `--format json|md|html|pdf` schreibt ein einzelnes Format. `--json` und
`--compact` geben stattdessen auf stdout aus.

```text
╭─ ✗ Likely substituted — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · coverage 100% · confidence medium             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

Ein Bericht enthält das Urteil (Risiko, Konfidenz, Bewertung, Note), die
wichtigsten Befunde mit Empfehlungen, die Bewertungen je Dimension und
**Dimension details**, die Befunde jedes Detektors mit Belegen, den
Leistungsabschnitt, das verwendete Wissensbasis-Profil und die Testsprachen. Vom
Relay kontrollierter Text wird vor dem Schreiben geschwärzt und maskiert.

Neben dem Score zeigt jeder Bericht die **Abdeckung**: den Anteil am Gewicht
der ausgeführten Dimensionen, der beurteilt werden konnte. Eine Dimension, die
lief, aber nicht beurteilt werden konnte, nennt die Zusammenfassung des Urteils,
und eine geringe Abdeckung begrenzt die Note oder lässt sie weg („keine Note: zu
wenig wurde beurteilt“); siehe [Gesamtbewertung, Note und Gewichte](methodology.md#gesamtbewertung-note-und-gewichte).

## Belegdateien

Mit `--evidence PATH` (`check`, `compare`, `image`, `audio`) und standardmäßig
für jeden im Verlauf gespeicherten Lauf schreibt ekte zusätzlich jede rohe
HTTP-Anfrage und -Antwort des Laufs in eine Datei: JSON Lines in einem
zstd-Strom, `<run_id>.jsonl.zst` (ein als `PATH` angegebenes Verzeichnis erhält
diesen Namen). Die erste Zeile beschreibt den Lauf; jede weitere Zeile ist eine
Anfrage mit ihrer Antwort, einschließlich des Zeitpunkts, zu dem jeder Teil der
Antwort eintraf. Das `seq` einer Zeile ist das `seq` der Anfrage in
`performance.requests` des Berichts, sodass sich jede Anfrage nachschlagen
lässt, die der Bericht aufführt. `evidence` im Bericht nennt die Datei mit
ihrem SHA-256 und der Zahl ihrer Austausche.

```bash
ekte check --base-url https://relay.example.com/v1 --model gpt-4o --evidence reports/
zstd -dc reports/<run_id>.jsonl.zst | jq -c 'select(.seq == 12)'
```

Jeder Befund nennt die Anfragen, auf denen er beruht (`evidence_seqs`; leer,
wenn er auf keiner beruht, wie die TLS-Prüfung). `ekte evidence-export` nimmt
die Datei (oder die Id eines gespeicherten Laufs) und macht daraus HAR für
einen HAR-Viewer oder die Entwicklerwerkzeuge des Browsers (`--as har`),
ein curl-Skript, das die Anfragen erneut sendet (`--as curl`; zuerst
`EKTE_API_KEY` setzen, die Datei enthält den Schlüssel nie) oder ein
JSON-Dokument (`--as json`); `--seq` wählt Anfragen aus.

`ekte rescore` bewertet einen aufgezeichneten Lauf mit der installierten
ekte-Version neu: Es führt dieselbe Prüfung aus, beantwortet aber jede Anfrage
mit der aufgezeichneten Antwort (im aufgezeichneten Takt), statt das Relay zu
kontaktieren, sodass verbesserte Prüfungen auch für alte Läufe gelten. Es nimmt die Id eines gespeicherten Laufs oder eine Berichtsdatei mit
`--evidence PATH`. Mit `--replace` ersetzt das Ergebnis den gespeicherten Lauf
(gleiche Id, Zeit und Überwachung); ohne wird es weiterhin als neuer Lauf
gespeichert, was veraltet ist und eine Warnung ausgibt (ein späteres ekte
ersetzt standardmäßig; `--no-save` speichert nichts). Eine
Prüfung, die jetzt etwas fragt, das der aufgezeichnete Lauf nie gefragt hat,
bleibt ohne klares Ergebnis, statt auf eine Vermutung hin bewertet zu werden;
`rescored_from` im Bericht nennt, wie viele Anfragen wiedergegeben wurden und
welche Prüfungen keine hatten.

`ekte rescore --all` bewertet jeden gespeicherten Lauf, den eine andere
ekte-Version bewertet hat, nacheinander neu, ersetzt ihn und zeigt sein Urteil
vorher und nachher. Ein Lauf ohne verwendbare Belegdatei wird nicht neu
bewertet: Er behält sein Urteil und wird mit Begründung übersprungen.
`ekte serve` tut dasselbe beim ersten Start nach einem Update im Hintergrund
(siehe [Web-Oberfläche](web-ui.md)).

Die Markdown-, HTML- und PDF-Exporte eines neu bewerteten Berichts nennen
beide Versionen, den Zeitpunkt der Neubewertung und das Ergebnis davor; das
`--compact`-Ergebnis enthält sie als `rescored`.

Schlüssel und sensible Header werden vor dem Schreiben entfernt (siehe
[Datenschutz](privacy.md)). Jede Zeile entspricht
`ekte/schemas/evidence.schema.json` ([Schemas](../../../reference/schemas.md)).
In der Web-UI listet **Belege anzeigen** unter einem Befund eines gespeicherten
Laufs die Anfragen der zugehörigen Prüfung auf und öffnet jede rohe Anfrage und
Antwort.
