# ekte — Realitätscheck für LLM-Relays

> [🇬🇧 English](../../../README.md) · [🇨🇳 中文](../zh-CN/README.md) · [🇫🇷 Français](../fr/README.md) · [🇪🇸 Español](../es/README.md) · [🇵🇹 Português](../pt/README.md) · [🇮🇹 Italiano](../it/README.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../nb/README.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](../../../LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](../../../pyproject.toml)

**ekte** ist ein Local-first-Werkzeug, das prüft, ob ein API-Relay
(Wiederverkäufer / Proxy) tatsächlich das Modell liefert, das es angibt — oder ob
es stillschweigend ein billigeres unterschiebt, das Kontextfenster kürzt,
Streaming vortäuscht oder die Token-Abrechnung aufbläht. Kurz: Bekommen Sie, wofür
Sie bezahlen? Es spricht die **OpenAI Chat Completions API**, die **Anthropic
Messages API** und die **OpenAI Responses API** (`/v1/responses`) — automatisch
erkannt oder erzwungen mit `--api openai|anthropic|responses`.

Sie geben ihm den Endpunkt eines Relays und das Modell, das es angeblich liefert;
ekte führt eine Reihe von Black-Box-Tests aus, vergleicht das beobachtete
Verhalten mit einer mitgelieferten Wissensbasis von **98 Modellprofilen von 7
Anbietern** und gibt ein klares, mit Belegen untermauertes Urteil aus — auf der
Kommandozeile, in einer lokalen Weboberfläche oder als JSON für ein anderes
Werkzeug oder LLM.

> ekte liefert **Black-Box-Belege für Abweichungen und Risiken, keinen
> kryptografischen Betrugsnachweis.** Siehe [Verantwortungsvoller Einsatz](guide/privacy.md#verantwortungsvoller-einsatz).

## Warum

Der Markt für Relay-Schlüssel ist voller Angebote wie „GPT-4o für ein Zehntel des
Preises“. Viele sind ehrlich. Manche nicht — und die unehrlichen sind mit bloßem
Auge schwer zu erkennen:

- Sie fordern `gpt-4o` an und bekommen stillschweigend `gpt-4o-mini` oder ein offenes Modell.
- Das Relay bewirbt 1M Token Kontext, kürzt aber stillschweigend auf 32K.
- „Streaming“ ist die komplett gepufferte und neu zerstückelte Antwort, ganz ohne Latenzvorteil.
- Die gemeldeten `usage`-Token sind aufgebläht, sodass Ihr Guthaben schneller schwindet als nötig.
- Ein Modell, das Tool-Calling / JSON-Modus unterstützen sollte, tut es stillschweigend nicht.

ekte macht aus „da stimmt doch was nicht“ einen reproduzierbaren Bericht.

## Installation

Erfordert Python 3.11+ unter Linux, macOS oder Windows.

```bash
pip install 'ekte[web]'          # oder: uv tool install 'ekte[web]'
```

Das Extra `web` fügt die lokale Weboberfläche hinzu; lassen Sie es weg, wenn Sie
nur die Kommandozeile brauchen. Aus dem Quellcode, mit uv oder in Docker:
[Installation](guide/install.md).

## Schnellstart

```bash
export EKTE_API_KEY=sk-your-relay-key

# ein Relay gegen das Modell prüfen, das es angeblich liefert
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard

# die stärkste Prüfung: Vergleich mit einer vertrauenswürdigen Referenz desselben Modells
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o

# oder per Mausklick: die lokale Weboberfläche
ekte serve
```

Weitere Beispiele, Konfigurationsdateien und die Nutzung aus Skripten oder durch
LLM-Agenten: [Schnellstart](guide/quickstart.md). Die Weboberfläche:
[Weboberfläche](guide/web-ui.md).

## Was geprüft wird

ekte bewertet zehn Dimensionen. Die vier **Kerndimensionen** — Modellidentität,
Kontextfenster, angegebene Fähigkeiten und Abrechnung & Verbrauch — decken einen
Etikettenschwindel am direktesten auf. Die Namen sind die der
Weboberfläche und der Berichte.

| Dimension | Kennung | Was sie aufdeckt |
|---|---|---|
| **Modellidentität** | `model_identity` | Stillschweigende Herabstufung oder Austausch des Modells |
| **Kontextfenster** | `context_window` | Stillschweigende Kontextkürzung und „Lost in the Middle“ |
| **Angegebene Fähigkeiten** | `capability` | Tool-Calling, JSON-Modus, maximale Ausgabe oder Vision, die nicht geliefert werden |
| **Protokollkonformität** | `protocol` | Anfrageparameter und Antwortattribute, die verworfen oder ignoriert werden |
| **Abrechnung & Verbrauch** | `billing` | Aufgeblähter oder fehlender Token-Verbrauch |
| **Konnektivität** | `connectivity` | Erreichbarkeit des Endpunkts und die beworbene Modellliste |
| **Echtheit des Streamings** | `streaming` | Vorgetäuschtes Streaming (erst puffern, dann zerstückeln) |
| **Zuverlässigkeit unter Parallellast** | `reliability` | Fehler und Verlangsamung unter paralleler Last |
| **Transportsicherheit** | `security` | Unverschlüsseltes HTTP, Echo von Geheimnissen, eingeschleuste System-Prompts, Manipulation |
| **Leistung** | `performance` | Wie gleichmäßig Latenz, Zeit bis zum ersten Token und Durchsatz sind |

Wie jede Prüfung funktioniert und wie das Urteil zustande kommt:
[Methodik](guide/methodology.md).

## Dokumentation

| Benutzerhandbuch | |
|---|---|
| [Installation](guide/install.md) | pip, uv, aus dem Quellcode, optionale Extras |
| [Schnellstart](guide/quickstart.md) | Erste Prüfungen, Konfigurationsdateien, Nutzung durch Skripte und LLM-Agenten |
| [Weboberfläche](guide/web-ui.md) | Seiten, Prüfungen im Hintergrund, Auswertungen, Sprachen |
| [Suiten und Vergleichsmodus](guide/suites.md) | Suiten, benutzerdefinierte Suite, vertrauenswürdige Referenz, LLM-Richter |
| [Leistung](guide/performance.md) | Der Leistungsabschnitt, die Messung und die Zeitlimits für Anfragen |
| [Überwachung](guide/monitoring.md) | Geplante Wiederholungsprüfungen, Webhook-Warnungen, Speicherung der API-Schlüssel |
| [Prüfungen für Embedding, Rerank, Bild und Audio](guide/other-endpoints.md) | Prüfungen von Endpunkten, die kein Chat sind |
| [Wissensbasis](guide/knowledge-base.md) | Modellprofile und eigene Ergänzungen |
| [Berichte](guide/reports.md) | Berichtsformate und -inhalte |
| [Datenschutz und lokale Daten](guide/privacy.md) | Was auf Ihrem Rechner bleibt; verantwortungsvoller Einsatz |
| [GitHub Action](guide/github-action.md) | Einen CI-Workflow an eine Relay-Prüfung koppeln |
| [Docker](guide/docker.md) | Die Weboberfläche in einem Container betreiben |
| [Methodik](guide/methodology.md) | Jede Prüfung, ihre Bewertungsskala und ihre Einschränkungen |
| [Umstieg von zing](guide/migrating-from-zing.md) | Was sich für eine bestehende zing-Installation ändert |

| Referenz (auf Englisch) | |
|---|---|
| [Kommandozeile](../../reference/cli.md) | Alle Befehle und Optionen sowie die Exit-Codes |
| [Bericht- und Webhook-Schemas](../../reference/schemas.md) | Die JSON-Formate und ihre `schema_version` |
| [Stabilität und Kompatibilität](../../reference/stability.md) | Was SemVer schützt, Abkündigung, unterstützte Python-Versionen und Systeme |
| [Änderungsprotokoll](../../../CHANGELOG.md) | Was sich in jeder Version geändert hat |

Mitwirken: [Leitfaden für Beiträge](../../CONTRIBUTING.md) und
[Entwicklerhandbuch](../../dev/developer-guide.md) (auf Englisch).
Sicherheitsprobleme: [Sicherheitsrichtlinie](../../SECURITY.md).

## Lizenz

[Apache-2.0](../../../LICENSE)
