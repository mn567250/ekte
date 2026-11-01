# Suiten und Vergleichsmodus

> [🇬🇧 English](../../../guide/suites.md) · [🇨🇳 中文](../../zh-CN/guide/suites.md) · [🇫🇷 Français](../../fr/guide/suites.md) · [🇪🇸 Español](../../es/guide/suites.md) · [🇵🇹 Português](../../pt/guide/suites.md) · [🇮🇹 Italiano](../../it/guide/suites.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/suites.md)

| Suite | Detektoren | Kosten |
|---|---|---|
| `smoke` | connectivity, security | sehr gering |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | gering–mittel |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (mit `--judge`) | höher (Langkontext- und Timing-Tests kosten Token) |
| `full` | die Detektoren von `deep`, Leistung mit und ohne Streaming gemessen | am höchsten |
| `custom` | nur die gewählten Dimensionen, in `deep`-Tiefe | je nach Auswahl |

Der Kontextfenster-Test ist durch `--max-context-tokens` (Standard 200K)
begrenzt, sodass die Prüfung eines Modells mit 1M Token bezahlbar bleibt.
`--only` / `--skip` führen einzelne Detektoren anhand ihrer Kennung aus oder
lassen sie weg.
Ein Fenster oberhalb der `--max-context-tokens`-Grenze wird als *bis zur Grenze verifiziert* gemeldet, nie als gekürzt.

## Benutzerdefinierte Suite

Führen Sie nur die Dimensionen aus, die Sie interessieren — das spart Zeit und
Token. Jeder Detektor jeder gewählten Dimension läuft wie bei `deep`:

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` ist wiederholbar oder kommagetrennt und impliziert
`--suite custom`; in einer Konfigurationsdatei `run.dimensions: [protocol, performance]`.
Die Dimensionen sind `connectivity`, `protocol`, `context_window`,
`model_identity`, `capability`, `streaming`, `billing`, `reliability`, `security`
und `performance`. In der Weboberfläche öffnet die Suite-Schaltfläche `custom`
dieselbe Auswahl (**Auszuführende Dimensionen**) auf der Prüfseite
und bei den Überwachungen.

Die **Gesamtbewertung ist der gewichtete Mittelwert allein der gewählten
Dimensionen**; ausgelassene Dimensionen werden als „nicht ausgewählt“
ausgewiesen. Auch das Risikourteil beruht auf den gewählten Dimensionen: ohne
Modellidentität gilt es nur für sie, nicht dafür, welches Modell bereitgestellt
wird, und sagt das.

## Vergleichsmodus und LLM-Richter

ekte hat zwei Erkennungsmodi:

- **Reiner Code (Standard):** jeder Detektor außer `quality_judge` entscheidet per
  deterministischem Code — Fingerabdrücke, Kontext-Durchlauf,
  Abrechnungsberechnung, Streaming-Timing. Kein zweites Modell nötig; die
  Ergebnisse sind reproduzierbar.
- **Hybrid aus Code + LLM (`--judge`):** fragt zusätzlich ein *vertrauenswürdiges*
  Richtermodell (separat konfiguriert, niemals das Ziel), ob die Antworten des
  Ziels wie das angegebene Modell klingen — unscharfe Signale wie Qualität und
  Denktiefe, die reiner Code nicht entscheiden kann. Das ist der Detektor
  `quality_judge`.

```bash
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

Der **Vergleichsmodus** (`ekte compare` oder **Mit vertrauenswürdiger Referenz
vergleichen** in der Weboberfläche) führt dieselben Tests gleichzeitig gegen eine
vertrauenswürdige Referenz des angegebenen Modells aus. Er ist der stärkste Weg
zur Bestätigung: Identitätsantworten, abgelehnte Anfrageparameter,
Manipulations-Canaries und Leistung werden Seite an Seite beurteilt, und nur eine
Referenz lässt die Konfidenz des Urteils *hoch* werden. Ohne `--judge-base-url`
nutzt der Vergleichsmodus die Referenz als Richter.
