# zing — Realitätscheck für LLM-Relays

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · **🇩🇪 Deutsch**

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** ist ein Local-first-Werkzeug, das prüft, ob ein API-Relay
(Wiederverkäufer / Proxy) tatsächlich das Modell liefert, das es angibt — oder ob
es stillschweigend ein billigeres unterschiebt, das Kontextfenster kürzt,
Streaming vortäuscht oder die Token-Abrechnung aufbläht. Kurz: Bekommen Sie, wofür
Sie bezahlen? Es spricht die **OpenAI Chat Completions API**, die **Anthropic
Messages API** und die **OpenAI Responses API** (`/v1/responses`) — automatisch
erkannt oder erzwungen mit `--api openai|anthropic|responses`.

Sie geben ihm den Endpunkt eines Relays und das Modell, das es angeblich liefert;
zing führt eine Reihe von Black-Box-Tests aus, vergleicht das beobachtete
Verhalten mit einer mitgelieferten Wissensbasis von **98 Modellprofilen von 7
Anbietern** und gibt ein klares, mit Belegen untermauertes Urteil aus — auf der
Kommandozeile, in einer lokalen Weboberfläche oder als JSON für ein anderes
Werkzeug oder LLM.

> zing liefert **Black-Box-Belege für Abweichungen und Risiken, keinen
> kryptografischen Betrugsnachweis.** Siehe [Verantwortungsvoller Einsatz](#verantwortungsvoller-einsatz).

Dieses README richtet sich an alle, die zing **nutzen**. Wie zing aufgebaut,
getestet und veröffentlicht wird, steht im [Entwicklerhandbuch](DEVELOPER_GUIDE.de.md);
wie jede Prüfung funktioniert und bewertet wird, in der
[Methodik](docs/METHODOLOGY.de.md).

---

## Inhalt

- [Warum](#warum)
- [Installation](#installation)
- [Schnellstart](#schnellstart)
- [Weboberfläche (`zing serve`)](#weboberfläche-zing-serve)
- [Was geprüft wird](#was-geprüft-wird)
- [Wie das Urteil zustande kommt](#wie-das-urteil-zustande-kommt)
- [Suiten](#suiten)
- [Leistung](#leistung)
- [Vergleichsmodus und LLM-Richter](#vergleichsmodus-und-llm-richter)
- [Überwachung](#überwachung)
- [Prüfungen für Embedding, Rerank, Bild und Audio](#prüfungen-für-embedding-rerank-bild-und-audio)
- [Einsatz in CI (GitHub Action)](#einsatz-in-ci-github-action)
- [Wissensbasis](#wissensbasis)
- [Berichte](#berichte)
- [Datenschutz und lokale Daten](#datenschutz-und-lokale-daten)
- [Verantwortungsvoller Einsatz](#verantwortungsvoller-einsatz)
- [Weitere Dokumentation](#weitere-dokumentation)
- [Lizenz](#lizenz)

## Warum

Der Markt für Relay-Schlüssel ist voller Angebote wie „GPT-4o für ein Zehntel des
Preises“. Viele sind ehrlich. Manche nicht — und die unehrlichen sind mit bloßem
Auge schwer zu erkennen:

- Sie fordern `gpt-4o` an und bekommen stillschweigend `gpt-4o-mini` oder ein offenes Modell.
- Das Relay bewirbt 1M Token Kontext, kürzt aber stillschweigend auf 32K.
- „Streaming“ ist die komplett gepufferte und neu zerstückelte Antwort, ganz ohne Latenzvorteil.
- Die gemeldeten `usage`-Token sind aufgebläht, sodass Ihr Guthaben schneller schwindet als nötig.
- Ein Modell, das Tool-Calling / JSON-Modus unterstützen sollte, tut es stillschweigend nicht.

zing macht aus „da stimmt doch was nicht“ einen reproduzierbaren Bericht.

## Installation

Erfordert Python 3.10+. Jede der folgenden Varianten stellt den Befehl `zing` bereit.

### Mit pip

```bash
# von PyPI
pip install zing-audit

# oder aus dem Quellcode
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Mit [uv](https://docs.astral.sh/uv/)

```bash
# von PyPI, als eigenständiges Werkzeug in Ihrem PATH
uv tool install zing-audit

# oder einmalig ausführen, ohne zu installieren
uvx --from zing-audit zing --help

# oder aus dem Quellcode, in eine projektlokale virtuelle Umgebung
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Sie können auch direkt aus dem Git-Repository installieren, ohne es zu klonen:
`uv tool install git+https://github.com/cenbonew/zing`.

### Optionale Extras

- `web` — die lokale Weboberfläche (`zing serve`).

```bash
pip install 'zing-audit[web]'      # pip, von PyPI
pip install -e '.[web]'            # pip, aus dem Quellcode
uv tool install 'zing-audit[web]'  # uv, von PyPI
uv pip install -e '.[web]'         # uv, aus dem Quellcode
```

Das Extra `tokenizers` wird nicht mehr gebraucht: Seit 0.19.0 ist es leer und
bleibt nur erhalten, damit ältere Installationsbefehle weiter funktionieren. zing
zählt Token mit einer eingebauten Heuristik und lädt zur Laufzeit nichts herunter
(keine Tokenizer-Dateien), läuft also auch in eingeschränkten oder Offline-Umgebungen,
die nur die geprüften Relays erreichen.

PDF-Berichte (`--format pdf` und der PDF-Download in der Weboberfläche) brauchen
kein Extra: Sie werden mit [ReportLab](https://www.reportlab.com/opensource/)
gesetzt, einer reinen Python-Abhängigkeit ohne Systembibliotheken unter Linux, macOS
und Windows.

### Mit Docker (nur Weboberfläche)

Aus einem Checkout des Quellcodes:

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# http://localhost:8000 öffnen
```

Veröffentlichen Sie den Port immer wie gezeigt an `127.0.0.1`. Details und
Umgebungsvariablen: [Entwicklerhandbuch → Docker](DEVELOPER_GUIDE.de.md#docker)
und [docs/DOCKER.md](docs/DOCKER.md).

## Schnellstart

```bash
# 1) ein Relay gegen seine Angaben prüfen (Modell-ID + Anbieterhinweis)
export ZING_API_KEY=sk-ihr-relay-schluessel
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) die stärkste Prüfung: Vergleich mit einer vertrauenswürdigen Referenz desselben Modells
export OPENAI_API_KEY=sk-ihr-openai-schluessel
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) ein natives Anthropic-Relay (Messages API) prüfen — das Protokoll wird anhand von
#    base_url/model automatisch erkannt oder mit --api anthropic erzwungen
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) einen vermuteten Austausch bestätigen: die ECHTE Modell-ID des Relays gegen das Profil
#    prüfen, unter dem es verkauft wird (hier: ein Doubao-Modell, ausgegeben als deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) die Modelle auflisten, die ein Endpunkt bewirbt
zing models --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY

# 6) die Wissensbasis ansehen
zing kb            # alle Profile, mit ihrer Quelle
zing kb deepseek   # ein Anbieter

# 7) eine Konfiguration zum Einchecken erzeugen
zing init          # schreibt zing.yaml
zing check -c zing.yaml
```

API-Schlüssel lassen sich direkt, als `env:VAR` oder als `file:/pfad` angeben;
Berichte enthalten immer nur einen Fingerabdruck des Schlüssels. Eine vollständige
Konfigurationsdatei finden Sie in [`examples/zing.yaml`](examples/zing.yaml).

### Als Werkzeug für ein LLM / einen Agenten

zing ist dafür gebaut, von einem anderen Programm oder Modell gesteuert zu werden.
Alles geht als JSON nach stdout, auch Fehler, und der Exit-Code dient als Schranke.

```bash
# schlankes, agentenfreundliches Urteil (~5x kleiner als --json: ohne umfangreiche Belege)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# vollständiger strukturierter Bericht, wenn Sie die Belege jedes Befunds brauchen
zing check --base-url ... --model gpt-4o --json

# erst das Budget: welche Detektoren laufen + geschätzte API-Aufrufe, OHNE einen auszuführen
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# Schranke über den Exit-Code (1 bei Risiko >= medium oder einer Bewertung unter --fail-under);
# Konfigurations-/Aufruffehler enden mit 2, als JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# maschinenlesbare Erkundung
zing kb --json                      # die gesamte Wissensbasis
zing models --base-url ... --json   # was ein Endpunkt bewirbt
```

Im Modus `--json`/`--compact` gibt eine fehlerhafte Konfiguration `{"error": {...}}`
(Exit-Code 2) statt einer Meldung für Menschen aus, sodass eine Pipeline Fehler
einheitlich auswerten kann.

## Weboberfläche (`zing serve`)

Lieber klicken? Eine lokale Weboberfläche nutzt dieselbe Engine — ganz ohne
Kommandozeile.

```bash
pip install 'zing-audit[web]'     # oder: uv tool install 'zing-audit[web]'
zing serve                        # öffnet http://localhost:8000
```

In der neuen Oberfläche führt das Formular durch die Konfiguration:

1. Wählen Sie **Relay / Anbieter**: einen Anbieter der Wissensbasis oder ein von
   Ihnen gespeichertes Relay. Seine Basis-URL wird ausgefüllt (weitere bekannte
   URLs des Anbieters werden als Vorschläge angeboten). Für jedes andere Relay
   wählen Sie **Andere (URL eingeben)** und geben die **Relay-URL** ein.
2. Ergänzen Sie den **API-Schlüssel**, falls das Relay einen braucht.
3. zing listet die Modelle des Relays selbst auf (bei der Auswahl eines Relays
   und immer, wenn sich URL oder Schlüssel ändern; **Modelle neu laden** fragt
   erneut). Wählen Sie das **Angefragte Modell**. Ein Relay ohne Modellliste
   fällt auf die Eingabe der ID zurück (**Manuell eingeben**).
4. Wählen Sie optional das **Angegebene Modell** aus den Modellen der
   Wissensbasis: das Modell, das das Relay zu liefern behauptet. Ist das
   angefragte Modell in der Wissensbasis, ist es vorausgewählt; ändern Sie es
   nur, wenn das Relay das Modell unter anderem Namen verkauft. Das
   Anbieterprofil, gegen das zing prüft, ergibt sich daraus.

Ein Relay, das noch nicht in der Liste steht, lässt sich mit **In der
Wissensbasis speichern** unter einem Namen Ihrer Wahl behalten; beim nächsten Mal
ist es eine Auswahl entfernt. Die vertrauenswürdige Referenz (**Mit
vertrauenswürdiger Referenz vergleichen**) und die Seite **Werkzeuge** werden
genauso konfiguriert. Die klassische Oberfläche behält die einfachen Felder mit
**Modelle abrufen**.

Dann
**Prüfung starten** und die Prüfungen **live** verfolgen: jede Prüfung zeigt ihre
Bewertung und Dauer, und eine Prüfung mit Befunden klappt auf und zeigt die
Belege. Das Ergebnis ist ein teilbarer Urteilsbericht: Note, die **Prüfungen je
Dimension** mit ihren Bewertungsskalen, Befunde in verständlicher Sprache und der
Leistungsabschnitt (in der neuen Oberfläche zusätzlich ein
**Ausführungsprotokoll** aller Detektoren).

Alles läuft auf Ihrem Rechner: ein im Browser eingegebener Schlüssel erreicht nur
Ihren lokalen zing-Server und das geprüfte Relay, niemals Dritte. Siehe
[Datenschutz und lokale Daten](#datenschutz-und-lokale-daten).

### Seiten

Die Weboberfläche gibt es in zwei Versionen mit demselben Server und denselben
Daten. Die **klassische Oberfläche** öffnet unter `/`; ihr Link **Neue Oberfläche
testen** wechselt zur **neuen Oberfläche** unter `/v2/`, deren Link **Klassische
Oberfläche** zurückführt. Die Wahl wird pro Browser gespeichert.

| Seite | Klassische Oberfläche | Neue Oberfläche | Wofür |
|---|---|---|---|
| **Prüfung** | `/` | `/v2/` | Ein Relay prüfen (optional gegen eine Referenz) und den Bericht lesen |
| **Konsole** | `/console` | — | Dieselbe Prüfung als kompakte Konsole im Log-Stil |
| **Werkzeuge** | `/tools` | `/v2/tools` | Embedding- und Rerank-Prüfungen |
| **Verlauf** | `/history` | `/v2/history` | Jede Prüfung auf diesem Rechner, gruppiert nach Relay + angegebenem Modell, mit Trends |
| **Analyse** | — | `/v2/analytics` | Relays und Modelle im Zeitverlauf verglichen: Kennzahlen, Diagramme mit Datentabellen, Ranglisten |
| **Überwachung** | `/watches` | `/v2/watches` | Geplante Wiederholungsprüfungen mit Webhook-Warnungen |
| **Wissen** | — | `/v2/kb` | Die Wissensbasis in drei Tabs — Modelle, Anbieter, Relays: durchsuchen, ein-/ausschalten, Eigenes hinzufügen |

Die neue Oberfläche bietet zusätzlich: Filter und konfigurierbare Trends
(Bewertung, Note, Latenz p50, Token/s) im **Verlauf**; **Als Überwachung
einplanen** und **Audit erneut ausführen** bei jedem Lauf im Verlauf; **Bericht herunterladen** in jedem Format;
eine Designauswahl (Automatisch / Hell / Dunkel); und die Seite **Wissen**.

**Audits im Hintergrund (neue Oberfläche).** Ein auf der Seite **Audit**
gestartetes Audit läuft weiter, wenn Sie die Seite wechseln oder den Tab
schließen; **Im Hintergrund fortsetzen** schickt es bewusst dorthin. Der
**Verlauf** zeigt jedes wartende und laufende Audit (und jede laufende
Überwachung) mit Fortschritt; **Live ansehen** öffnet die Live-Ansicht wieder
und holt alles bisher Geschehene nach. Audits desselben Relays laufen
nacheinander, damit sie Latenz- und Zuverlässigkeitswerte nicht gegenseitig
verfälschen (alle Loopback-Adressen zählen als ein Host, also warten auch
Modelle auf Ihrem eigenen Rechner); Audits verschiedener Relays laufen parallel,
höchstens vier gleichzeitig (`ZING_MAX_PARALLEL_AUDITS`). Überwachungen warten
ebenso auf ihr Relay.

**Analyse (neue UI).** `/v2/analytics` macht aus dem lokalen Verlauf
Vergleiche: Kennzahlen für den gewählten Zeitraum (Läufe, Median-Score, Anteil
hohes Risiko, Erfolgsquote, TTFT, Ausgabegeschwindigkeit,
Abrechnungsverhältnisse) mit der Änderung gegenüber dem gleich langen Zeitraum
davor; ein Diagramm jeder Kennzahl pro Relay, Modell oder Relay × Modell nach
Stunde, Tag oder Woche (Median-Linie mit p25–p75-Band, bis zu vier Reihen, jedes
Diagramm auch als Datentabelle); und eine Rangliste der Relays für ein Modell
oder der Modelle eines Relays. Relays werden nach ihrem Eintrag in der
Wissensbasis gruppiert (gespeicherte Relays und Anbieter), ein umbenanntes Relay
gruppiert also seinen Verlauf neu. Abschnitte mit weniger als 3 Läufen werden
blass gezeichnet — ein einzelnes Audit kann ein Ausreißer sein; eine
Überwachung liefert regelmäßige Messungen. Ältere Läufe zeigen, was sie
gemessen haben: die Seite sagt, auf wie vielen Läufen ein Wert beruht.
Standardmäßig vergleicht sie eine Suite und einen Probe-Modus (die häufigsten),
damit Ungleiches nicht vermischt wird; Filter und Ansicht stehen in der URL, eine
Ansicht lässt sich also als Lesezeichen speichern oder teilen. Nichts verlässt
den Rechner.

Weitere Bereiche beantworten engere Fragen: **Stoßzeiten** (eine Heatmap
Wochentag × Stunde von TTFT, Latenz und Dekodiertempo (Median und p95-/p5-Ausläufer),
Jitter zwischen Tokens, Netzwerk- und Relay-Zeiten, Erfolgs- oder Fehlerquote in Ihrer
Zeitzone — wird ein Relay zu Stoßzeiten langsamer oder fehleranfälliger? Nach Wochentag,
oder ab 90 Tagen mit Läufen über einen 4-Wochen-Zyklus und ab 180 Tagen nach
Woche im Monat),
**Fehler und Zuverlässigkeit** (fehlgeschlagene Aufrufe nach Ursache —
Ratenbegrenzung (HTTP 429), Serverfehler (5xx), Zeitüberschreitungen,
Netzwerkfehler — im Zeitverlauf und pro Relay oder Modell, aus den
gespeicherten Anfragedaten, mit der Zahl der Läufe, die sie haben),
**Modellechtheit** (Ergebnisse der Identitäts-, Kontextfenster- und
Fähigkeitsprüfungen pro Relay × Modell, der Anteil der Läufe mit abweichend
zurückgemeldetem Modell und der gemessene Anteil am angegebenen
Kontextfenster), **Abrechnung und Tokens** (Abrechnungsverhältnisse im
Zeitverlauf gegen die 100-%-Linie — darüber meldet das Relay mehr Tokens, als
zing gezählt hat — sowie Anteile von Reasoning- und gecachten Eingabe-Tokens)
und **Relay-Overhead** (die vom Relay gemeldete Verarbeitungszeit neben der
Netzwerk-Umlaufzeit dorthin).

**Tabs und Links zum Teilen (Analyse).** Die Panels liegen in fünf Tabs —
**Überblick** (Kennzahlen, Rangliste), **Trends** (Vergleich im Zeitverlauf,
Stoßzeiten), **Zuverlässigkeit** (Fehler, Relay-Overhead),
**Modellechtheit** und **Abrechnung** — unter dem Seitenkopf und einem
gemeinsamen Filterpanel; geladen wird nur der Tab, den Sie ansehen. Die URL
enthält Tab, Filter und jede Diagrammoption
(`#tab=reliability&range=30&relay=…&eb=dow_hour`), und **Link zu dieser
Ansicht kopieren** kopiert sie (oder zeigt sie in einem Feld zum Kopieren, wo
der Browser das nicht erlaubt): Der Link öffnet genau diese Ansicht. Das
Filterpanel ist auf **Verlauf** und **Analyse** dasselbe: Geschlossen zeigt es,
wie viele Filter aktiv sind, und nennt sie in einer Zeile (z. B. „Letzte 30
Tage · standard · Streaming · Example Relay“), so sagt eine geteilte Ansicht,
was sie zeigt.

### Sprachen

Ein Sprachmenü in der Kopfzeile jeder Seite schaltet die Oberfläche zwischen
**🇬🇧 Englisch** (Standard), **🇨🇳 Chinesisch** (die ursprüngliche Oberfläche),
**🇫🇷 Französisch**, **🇪🇸 Spanisch**, **🇵🇹 Portugiesisch**, **🇮🇹 Italienisch** und
**🇩🇪 Deutsch** um; die Wahl wird pro Browser gespeichert.

Aus der Oberfläche heruntergeladene Berichte (**Bericht herunterladen**: JSON,
Markdown, HTML oder PDF) folgen der gewählten Sprache: JSON-Schlüssel,
Enum-Werte (`risk_level`, `status`, `severity`, …), IDs und Belege bleiben exakt
wie im Bericht der CLI (das JSON ist weiterhin ein gültiger zing-Bericht),
während die für Menschen lesbaren Werte (Überschrift und Zusammenfassung des
Urteils, Titel und Zusammenfassungen der Befunde, Empfehlungen, Detektornamen,
Hinweise) übersetzt werden und der Dateiname die Sprache trägt
(`zing-report.de.json`, `zing-report.de.pdf`). Die Abschnittsüberschriften der
Markdown-/HTML-/PDF-Dateien sind englisch. Die Berichte der CLI mit
`--format json|md|html|pdf` bleiben englisch.

**An den geprüften Endpunkt gesendete Prompts folgen nicht der Sprache der
Oberfläche.** Jeder Text, den zing an eine LLM-API sendet, ist englisch, damit
dasselbe Relay dasselbe Urteil erhält, egal wer den Bericht liest
(Antwortprüfungen und Token-Schätzungen sind auf genau diese Texte kalibriert).
Die einzigen Ausnahmen sind Fingerabdrücke der Wissensbasis, deren Sprache
*selbst* die Messgröße ist — z. B. die Tests zu chinesischer Sprachgewandtheit,
Tokenizer und Selbstidentifikation chinesischer Modelle. Jeder Bericht vermerkt
die tatsächlich verwendeten Testsprachen (`prompt_languages`, z. B. `["en", "zh"]`).
`started_at` vermerkt, wann die Prüfung begann (UTC); `start_ms` jedes
Anfrage-Datensatzes zählt ab diesem Zeitpunkt.

## Was geprüft wird

zing bewertet zehn Dimensionen. Die vier **Kerndimensionen** — Modellidentität,
Kontextfenster, angegebene Fähigkeiten und Abrechnung & Verbrauch — decken einen
Etikettenschwindel am direktesten auf. Die Namen sind die der
Weboberfläche und der Berichte.

| Dimension | Kennung | Gewicht | Was sie aufdeckt |
|---|---|---|---|
| **Modellidentität** | `model_identity` | 21 | Stillschweigende Herabstufung oder Austausch des Modells — Selbstidentifikation, Wissensstichtag, Tokenizer-Fingerabdrücke, das zurückgegebene `model`-Feld; optional ein LLM-Richter |
| **Kontextfenster** | `context_window` | 19 | Stillschweigende Kontextkürzung (1M angegeben, Abruf scheitert bei 32K) und „Lost in the Middle“ durch billige RAG-/Zusammenfassungs-Zwischenschichten, per Nadel im Heuhaufen und binärer Suche |
| **Angegebene Fähigkeiten** | `capability` | 13 | Angaben zu Tool-Calling / JSON-Modus / JSON-Schema / maximaler Ausgabe, die nicht geliefert (oder *über*erfüllt, ein Hinweis auf ein Ersatzmodell) werden; **Vision** — ein Modell, das Bildeingabe angibt, muss ein generiertes Bild mit bekannter Antwort lesen |
| **Protokollkonformität** | `protocol` | 8 | Konformität auf der Leitung: Mehrfachdialoge, Stoppsequenzen, Fehlerschema; jeder Anfrageparameter angenommen (und beachtet, wo sichtbar), jedes Antwortattribut vorhanden; Antwort-Caches, die temperature/seed ignorieren |
| **Abrechnung & Verbrauch** | `billing` | 8 | Aufgeblähte Token/Nutzung und fehlende oder nicht überprüfbare Nutzungsabrechnung, per unabhängiger heuristischer Token-Schätzung |
| **Konnektivität** | `connectivity` | 7 | Erreichbarkeit des Endpunkts und die beworbene `/v1/models`-Liste |
| **Echtheit des Streamings** | `streaming` | 6 | Vorgetäuschtes Streaming (erst puffern, dann zerstückeln), erkannt an Anzahl und zeitlichem Abstand der Chunks |
| **Zuverlässigkeit unter Parallellast** | `reliability` | 6 | Erfolgsquote und Latenz unter paralleler Last (HTTP-429-Drosselung wird gesondert gezählt) |
| **Transportsicherheit** | `security` | 6 | HTTPS, Header-Hygiene, Echo von Geheimnissen; ein versteckt eingeschleuster System-Prompt; Manipulation von Antworten und Tool-Calls unterwegs (Kanarien mit bekannter Antwort); Prompt-Präfix-Caching (Timing) |
| **Leistung** | `performance` | 6 | Wie *gleichmäßig* Latenz, Zeit bis zum ersten Token und Durchsatz sind, Fehlerquote und Verlangsamung unter Last; das Tempo nur im Vergleich zu einer Referenz (siehe [Leistung](#leistung)) |

Die [Methodik](docs/METHODOLOGY.de.md) beschreibt jeden Test, den Relay-Trick, dem
er entspricht, seine Bewertungsskala und seine Einschränkungen bezüglich
Fehlalarmen.

## Wie das Urteil zustande kommt

Kurz gefasst (Details in der [Methodik](docs/METHODOLOGY.de.md#wie-zing-bewertet)):

- Jeder Detektor veröffentlicht seine **Bewertungsskala** — jedes mögliche
  Ergebnis jeder Prüfung mit seinen Punkten —, und die Weboberfläche zeigt sie
  unter **Bewertungsskala**.
- Die **Bewertung einer Dimension** ist der gleich gewichtete Mittelwert der
  Bewertungen ihrer Detektoren. Ein Befund HOCH/KRITISCH erzwingt
  **Fehlgeschlagen**, ein Befund MITTEL hebt **Bestanden** auf **Warnung** an,
  unabhängig von der Bewertung. Berichte erklären das je Dimension unter
  **Dimension details**; in der Weboberfläche klappt jede Zeile der **Prüfungen je
  Dimension** zu denselben Details auf.
- Der **Gesamt-Health-Score** ist der gewichtete Mittelwert der gelaufenen
  Dimensionen (Gewichte oben), benotet mit A (≥ 90), B (≥ 80), C (≥ 70),
  D (≥ 60) oder F.
- Das **Risikourteil** richtet sich nach dem Schweregrad der Befunde, nicht nach
  der Bewertung:

| Risiko | Bezeichnung in der UI | Wann |
|---|---|---|
| `inconclusive` | Unzureichendes Signal | Nichts Verwertbares zu beurteilen: Modellidentität, Kontextfenster und angegebene Fähigkeiten liefen, aber keine lieferte ein verwertbares Ergebnis (Relay nicht erreichbar, Modell nicht in der Wissensbasis), oder keine Dimension außer der Konnektivität lieferte eines |
| `high` | Etikettenschwindel | Ein Befund KRITISCH, ein Befund HOCH/KRITISCH in einer Kerndimension oder zwei oder mehr Befunde HOCH |
| `medium` | Abweichungen gefunden | Genau ein Befund HOCH außerhalb der Kerndimensionen oder ein Befund MITTEL in einer Kerndimension |
| `low` | Weitgehend vertrauenswürdig | Jeder andere Befund MITTEL |
| `clean` | Konsistent (wahrscheinlich echt) | Nichts davon |

Befunde der Dimension Konnektivität erhöhen das Risiko nie: ein Relay, das nicht
erreichbar ist oder drosselt, konnte nicht beurteilt werden — das ist kein Beleg
für ein anderes Modell. Die **Konfidenz** des Urteils (niedrig / mittel / hoch)
steigt mit der Zahl der Kerndimensionen, die ein Ergebnis lieferten, mit einer
Referenz und mit dem LLM-Richter.

Transport-Hinweise — Klartext-HTTP (`security.tls`) und Ausfälle oder langsame
Ausreißer unter Last (`reliability.*`) — senken die Punktzahl ihrer Dimension,
erhöhen aber das Substitutionsrisiko ebenfalls nicht; die Zusammenfassung führt
sie als Hinweise. Manipulierte Antworten und ein zurückgespiegelter API-Schlüssel
tun es weiterhin. Klartext-HTTP zu diesem Rechner oder einem privaten Netz ist nur
eine Warnung niedriger Schwere, da der Schlüssel es nie verlässt. Ein nur unscharf
(fuzzy) zugeordnetes Wissensbasis-Profil begrenzt die Konfidenz auf niedrig, und
ein Detektor ohne verwertbare Antwort ist nicht schlüssig — nie ein Bestehen.

## Suiten

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

### Benutzerdefinierte Suite

Führen Sie nur die Dimensionen aus, die Sie interessieren — das spart Zeit und
Token. Jeder Detektor jeder gewählten Dimension läuft wie bei `deep`:

```bash
zing check --base-url ... --model gpt-4o -D protocol -D performance
zing check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` ist wiederholbar oder kommagetrennt und impliziert
`--suite custom`; in einer Konfigurationsdatei `run.dimensions: [protocol, performance]`.
Die Dimensionen sind `connectivity`, `protocol`, `context_window`,
`model_identity`, `capability`, `streaming`, `billing`, `reliability`, `security`
und `performance`. In der Weboberfläche öffnet die Suite-Schaltfläche `custom`
dieselbe Auswahl (**Auszuführende Dimensionen**) auf der Prüfseite, in der
Konsole und bei den Überwachungen.

Die **Gesamtbewertung ist der gewichtete Mittelwert allein der gewählten
Dimensionen**; ausgelassene Dimensionen werden als „nicht ausgewählt“
ausgewiesen. Auch das Risikourteil beruht auf den gewählten Dimensionen: ohne
Modellidentität gilt es nur für sie, nicht dafür, welches Modell bereitgestellt
wird, und sagt das.

## Leistung

Jeder Bericht enthält einen Abschnitt **performance**: Latenz, Zeit bis zum
ersten Token (TTFT), Decode- und End-to-End-Token/s, Latenz und Jitter zwischen
Chunks, Fehler-/Timeout-/429-Raten, eine Netzwerkaufschlüsselung
(TCP-Verbindung, TLS, ein `GET /models`-Roundtrip, Serverzeit) und Kaltstart,
jeweils als count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev.

Läuft die eigene Messung, bewertet sie die Dimension **Leistung**. Die Bewertung
misst **Gleichmäßigkeit**, nicht reine Geschwindigkeit: ein langsamer, aber
gleichmäßiger Endpunkt (ein lokales oder selbst gehostetes Modell) wird nicht
dafür abgewertet, dass er kein Rechenzentrum ist:

| Prüfung | Bewertet nach |
|---|---|
| Gleichmäßigkeit von Latenz / TTFT | Verhältnis p90 ÷ p50 (≤ 1,3 gleichmäßig 100 · ≤ 1,75 stabil 85 · ≤ 2,5 schwankend 65 · darüber: sprunghaft 40); braucht ≥ 10 Stichproben |
| Gleichmäßigkeit des Durchsatzes | Verhältnis p50 ÷ p10 der Token/s, dieselben Stufen |
| Fehler | fehlgeschlagene Messanfragen: ≤ 2 % 100 · ≤ 10 % 80 · darüber: 50 (429 nicht mitgezählt) |
| Stabilität unter Last | p50-Latenz im Burst ÷ sequenzielle p50: ≤ 1,5x 100 · ≤ 3x 80 · darüber: 55 |
| Cache-Treffer | eindeutige Prompts aus einem Cache beantwortet: 60 |
| Referenz | Token/s im Vergleich zur vertrauenswürdigen Referenz, sonst zum veröffentlichten Bereich des Modells in der Wissensbasis: im Rahmen 100 · langsamer: nicht gewertet (nur Hinweis, nie ein Fehlschlag) · ≥ 2x schneller 60 (Hinweis auf ein kleineres Modell) · keine Referenz: nicht gewertet |

Leistungsbefunde haben höchstens niedrigen Schweregrad: sie bewegen die
Bewertung, nie das Risikourteil. Ohne die Messung (`standard` ohne Referenz,
`smoke`) läuft die Dimension nicht und fällt aus der Gesamtbewertung heraus.

- **standard** erhebt den Abschnitt aus den eigenen Anfragen der Prüfung.
- **deep / full / custom** fügen eine eigene Messung hinzu: 100 nicht cachebare
  Anfragen mit 128 Ausgabe-Token (eine zufällige Anfrage-ID eröffnet jeden
  Prompt; es werden keine Cache- oder Reasoning-Parameter gesendet) sowie einen
  Burst mit `--concurrency`. Einstellbar über `--performance-requests` (0
  deaktiviert sie) und `--performance-max-tokens`.
- Die Messung streamt standardmäßig; `--performance-non-streaming` (oder der
  Schalter **Streaming / Ohne Streaming** in der Weboberfläche) misst Relays, die
  nicht streamen können. **full** misst beide Modi verschränkt und stellt sie
  nebeneinander dar.
- **compare** führt die Messung auf beiden Endpunkten mit abwechselnden Anfragen
  aus und ergänzt eine Tabelle Ziel-vs.-Referenz (5 Anfragen je Seite bei
  `standard`, zu wenige für die Gleichmäßigkeitsprüfungen), deren Unterschiede
  grün ✓ markiert sind, wo das Ziel besser ist, und rot ✗, wo es schlechter ist.

Token werden doppelt gezählt — aus der `usage` des Relays und lokal —, sodass der
Durchsatz auch ohne `usage` messbar ist. Die lokale Zählung ist eine Schätzung
mit einer eingebauten Heuristik (etwa ±15-20 %; kein Tokenizer wird verwendet
oder heruntergeladen), und der Abschnitt weist immer darauf hin. Ein Perzentil
wird nur bei ausreichend Stichproben angezeigt (p90 ab 10, p95 ab 20, p99 ab 100). Der JSON-Bericht
speichert die Zeiten jeder Anfrage (nur Zahlen, kein Text); HTML-Bericht und
Weboberfläche stellen sie entlang der Zeitachse der Prüfung dar.

Audits, die in `zing serve` gleichzeitig laufen (mehrere Browser-Tabs,
Überwachungen), verfälschen sich nicht gegenseitig die Zeiten: CPU-intensive
Vorbereitung, etwa das Erstellen der langen Kontextfenster-Prompts, läuft
außerhalb der Event-Loop des Servers.

**Request-Timeouts.** `timeout_sec` (`--timeout`, Standard 60 s) ist die Basis;
jede Anfrage bekommt zusätzlich Zeit für Prompt-Größe und Ausgabebudget, damit
eine lange Kontextfenster-Probe oder ein langsames selbst gehostetes Modell nicht
nach einer Minute abbricht. Lokale und private Hosts (`localhost`, `127.x`,
`192.168.x`, `host.docker.internal`, …) bekommen mindestens 300 s.
`max_request_sec` (`--max-request-time`, Standard 900 s) ist die harte Obergrenze
jeder einzelnen Anfrage, Streams eingeschlossen, sodass keine Anfrage endlos
hängen kann. Eine Kontextfenster-Probe, die trotzdem in ein Timeout läuft, gilt
als nicht eindeutig, nicht als Kürzung.

## Vergleichsmodus und LLM-Richter

zing hat zwei Erkennungsmodi:

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
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

Der **Vergleichsmodus** (`zing compare` oder **Mit vertrauenswürdiger Referenz
vergleichen** in der Weboberfläche) führt dieselben Tests gleichzeitig gegen eine
vertrauenswürdige Referenz des angegebenen Modells aus. Er ist der stärkste Weg
zur Bestätigung: Identitätsantworten, abgelehnte Anfrageparameter,
Manipulations-Kanarien und Leistung werden Seite an Seite beurteilt, und nur eine
Referenz lässt die Konfidenz des Urteils *hoch* werden. Ohne `--judge-base-url`
nutzt der Vergleichsmodus die Referenz als Richter.

## Überwachung

Ein Relay kann heute das echte Modell liefern und es nächste Woche
stillschweigend austauschen. `zing watch` wiederholt die Prüfung nach Zeitplan,
speichert jeden Lauf im Verlauf und alarmiert einen Webhook, wenn das Risiko eine
Schwelle überschreitet oder sich gegenüber dem vorherigen Lauf
**verschlechtert**.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang de                                     # oder --once für cron
```

Warnungen werden für **Slack / Feishu / DingTalk / generisches JSON** formatiert,
automatisch anhand der Webhook-URL erkannt, und in der Warnsprache verfasst —
standardmäßig Englisch; `--alert-lang en|zh|fr|es|pt|it|de`. Die generische
JSON-Nutzlast hält ihre Schlüssel und Maschinenwerte (`risk_level`, `score`, …)
sprachneutral, übersetzt die für Menschen lesbaren (`text`, `headline`,
`key_findings`) und gibt die `language` an.

**In der Weboberfläche** führt `zing serve` dieselben Überwachungen in einem
Hintergrund-Scheduler im Serverprozess aus, speichert jeden Lauf im **Verlauf**
und sendet dieselben Webhook-Warnungen:

- **Neue Oberfläche:** einen Lauf im **Verlauf** öffnen und **Als Überwachung
  einplanen** wählen. zing übernimmt die Konfiguration dieses Laufs (Relay,
  Modell, angegebenes Modell, Anbieter, Suite, benutzerdefinierte Dimensionen) in
  eine pausierte Überwachung auf der Seite **Überwachung**; dort Intervall und
  API-Schlüssel setzen (der Verlauf speichert nie Schlüssel) und sie
  einschalten. Intervall, Schlüssel, **Warnschwelle**, Webhooks und **Sprache der
  Warnungen** lassen sich auf jeder Überwachung direkt bearbeiten.
- **Klassische Oberfläche:** das Formular auf der Seite **Überwachung** ausfüllen
  und **Überwachung hinzufügen**.

Jede Überwachung hat ihre eigene Warnsprache (standardmäßig die Sprache der
Oberfläche), lässt sich sofort ausführen, pausieren oder löschen und bleibt an
das Wissensbasis-Profil gebunden, mit dem sie angelegt wurde, bis Sie es neu
binden.

Fällige Überwachungen laufen gleichzeitig, jede als eigenes Audit, aber nie mehr
als ein Audit pro Relay-Host auf einmal und insgesamt höchstens
`ZING_MAX_PARALLEL_AUDITS`; ein Lauf wartet auf einen freien Platz (auch ein von
Hand gestartetes Audit kann sich hinter laufenden Überwachungen einreihen). Die
Zeit eines Laufs ist der Start seines Audits, nach einer etwaigen Wartezeit. Die
Prüfung auf Verschlechterung vergleicht mit dem zuletzt gespeicherten Lauf
desselben Relays und Modells, egal wie viele andere Läufe seitdem gespeichert
wurden. Die Warn-Webhooks eines Laufs werden gleichzeitig gesendet, sodass ein
langsamer oder toter Webhook die anderen nicht aufhält. Schlüssel werden
verschlüsselt in Ihrem lokalen Datenverzeichnis gespeichert und nie an den Browser zurückgegeben.

**Hauptschlüssel.** Die API-Schlüssel der Überwachungen sind mit einem
Hauptschlüssel verschlüsselt, den zing nie auf die Festplatte schreibt. Wenn Sie
zum ersten Mal einen API-Schlüssel speichern, erstellt die Seite **Überwachung**
ihn und zeigt ihn ein einziges Mal: kopieren oder herunterladen, in einem
Passwortmanager aufbewahren (Ihr Browser kann ihn speichern) und zur Bestätigung
wieder einfügen. Nach jedem Neustart von `zing serve` fragt die Seite erneut
danach (der Browser kann ihn ausfüllen); bis dahin warten Überwachungen, die ihn
brauchen, während Überwachungen ohne Schlüssel oder mit
`env:`/`file:`-Schlüsseln weiterlaufen. Die Statusleiste der Seite bietet
außerdem **Sperren**, **Wechseln** und **Schlüssel vergessen?** (verwirft die
verschlüsselten API-Schlüssel, damit Sie sie neu eingeben können). Für
unbeaufsichtigten Betrieb oder Docker übergeben Sie den Schlüssel als
`ZING_SECRET_KEY` (siehe [docs/DOCKER.md](docs/DOCKER.md));
`zing secret status | export | rotate` verwalten ihn auf der Kommandozeile.

## Prüfungen für Embedding, Rerank, Bild und Audio

Diese Endpunkte liefern Vektoren, Rangfolgen, Bilder oder Audio statt Chat, daher
prüft zing sie mit fokussierten Tests statt mit den Chat-Prompts. Jeder gibt ein
Urteil aus und unterstützt `--json` und `--fail-on-risk`.

### Endpunkttyp (Surface), Embedding- und Rerank-Monitore

Jede Prüfung, jede Verlaufszeile und jeder Monitor hat einen **Endpunkttyp**
(`surface`): `chat` (Standard), `embedding` oder `rerank`. Er ist unabhängig von
der Suite. Embedding- und Rerank-Prüfungen laufen über denselben Runner, dieselbe
Bewertung (0–100, A–F), denselben Verlauf, dieselbe Analyse und dieselben Monitore
wie Chat-Prüfungen; nur die Detektoren unterscheiden sich. Verlauf und Analyse
filtern nach Endpunkttyp, und die Analyse zeigt nur die Kennzahlen, die zutreffen.

Um einen Embeddings- oder Rerank-Endpunkt zu überwachen, prüfen Sie ihn auf der
Seite **Werkzeuge** und wählen **Überwachen**, oder **Als Überwachung einplanen** in
seiner Verlaufszeile. Der Monitor wiederholt die Prüfung nach Zeitplan, mit
derselben Fixierung der Wissensbasis, derselben Alarmschwelle und denselben
Regressionsalarmen wie ein Chat-Monitor, und prüft die **Drift** gegenüber
seinem vorigen Lauf (die Vektoren eines Embedding-Tests, Rangfolge und Scores
eines Rerank-Tests). Die angegebene Dimension eines Embedding-Monitors lässt sich
auf seiner Karte ändern (leer oder 0: aus der Wissensbasis). Die
Geschwindigkeitsmessungen (Embeddings: Latenz, Kaltstart, Eingaben/s,
Batch-Skalierung; Rerank: Latenz, Kaltstart, Dokumente/s, 4 gegen 32 Dokumente)
laufen nur in den Suiten deep, full oder custom oder in standard mit Baseline.

### Embeddings und Rerank

```bash
# Die erwartete Vektordimension wird für das angegebene Modell aus der Wissensbasis ermittelt.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Oder die erwartete Dimension direkt vorgeben:
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: ein eingebauter Test mit bekannter Antwort — ein echter Reranker muss das
# offensichtlich relevante Dokument an erster Stelle einordnen.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank

# Gründlicher: mit der Rerank-Geschwindigkeitsmessung; --no-save hält den Lauf aus dem Verlauf.
zing rerank --base-url ... --model my-rerank --suite deep --no-save
# Zuerst die Prüfungen und die geschätzten Aufrufe ansehen, ohne Anfrage:
zing rerank --base-url ... --model my-rerank --dry-run
```

`rerank` prüft Konnektivität, den **Test mit bekannter Antwort** (das
offensichtlich relevante Dokument muss an erster Stelle stehen), das
zurückgegebene `model`-Feld, Determinismus (dieselbe Anfrage zweimal ergibt
dieselbe Rangfolge und dieselben Scores) und die **Rangfolge-Drift** gegenüber
dem vorigen gespeicherten Lauf. `zing embed` und `zing rerank` nehmen `--suite`,
`--save/--no-save` (standardmäßig gespeichert, damit der nächste Lauf eine
Drift-Referenz hat) und `--dry-run`.

`embed` prüft Konnektivität, **Übereinstimmung der Dimension** (Länge des
zurückgegebenen Vektors gegenüber der nativen Dimension des angegebenen Modells —
das Hauptsignal für einen Etikettenschwindel: ein Relay, das
`text-embedding-3-large` mit 3072-d angibt, aber 1024-d zurückgibt, liefert ein
Ersatzmodell), Determinismus (gleiche Eingabe → Kosinus ≈ 1),
Unterscheidbarkeit (unzusammenhängende Eingaben → Kosinus deutlich unter 1) und
das zurückgegebene `model`-Feld. Mitgelieferte Profile: OpenAI
`text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Beide gibt es auch auf der Seite **Werkzeuge** der Weboberfläche
(**Embedding-Prüfung**, **Rerank-Prüfung**). Die Rerank-Prüfung nutzt immer die
eingebauten Tests, damit jeder Lauf für Drift und Überwachung vergleichbar bleibt.

### Bild- und Audio-Generierung (TTS)

Bildgenerierung (`POST /v1/images/generations`) und Sprachsynthese
(`POST /v1/audio/speech`), dekodiert allein mit der Python-Standardbibliothek —
Bildabmessungen aus den Header-Bytes (PNG/JPEG/GIF/WebP), WAV-Dauer über `wave`.

```bash
# Liefert ein Relay, das DALL·E 3 angibt, wirklich das angeforderte 1792x1024? Ein
# verkleinertes Bild oder eines in falscher Größe (oder außerhalb der nativen Größen des
# angegebenen Modells laut Wissensbasis) ist das Hauptsignal für einen Etikettenschwindel.
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Liefert ein Relay, das tts-1-hd angibt, echtes Audio, dessen Länge mit der Eingabe
# wächst (kein fester Platzhalter, kein als Audio getarntes HTML/JSON)?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` prüft Konnektivität, ein gültiges und dekodierbares Format,
**Übereinstimmung der Größe** (dekodierte Breite × Höhe gegenüber der Anfrage und
den nativen Größen des angegebenen Modells — FAIL/HIGH bei Abweichung),
Unterscheidbarkeit (zwei Prompts → verschiedene Bilder, um einen festen
Platzhalter zu entlarven), Anzahl und das `model`-Feld. `audio` prüft
Konnektivität, Gültigkeit von Container/Format, Einhaltung des Formats, eine
nicht triviale Dauer, die mit der Eingabe wächst, Unterscheidbarkeit und das
`model`-Feld. Die Wissensbasis enthält OpenAI DALL·E 2/3, gpt-image-1,
tts-1/tts-1-hd/gpt-4o-mini-tts sowie Bild-/TTS-Profile von Qwen.

## Einsatz in CI (GitHub Action)

Machen Sie jeden Workflow mit der mitgelieferten Composite Action von einer
Relay-Prüfung abhängig. Sie führt `zing check --compact --fail-on-risk` aus,
stellt `risk` / `score` / `rating` als Ausgaben bereit, schreibt eine
Zusammenfassung in den Lauf und lässt den Job fehlschlagen, wenn die
Risikoschranke auslöst.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.20.0         # auf ein Release-Tag festlegen
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # Secret des Aufrufers; wird nie ausgegeben
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

Der Relay-Schlüssel wird über eine Umgebungsvariable weitergereicht
(`--api-key env:…`) und erscheint daher nie auf einer Kommandozeile. Siehe
[docs/CI.md](docs/CI.md) für alle Ein- und Ausgaben und ein Beispiel für eine
Deployment-Schranke.

## Wissensbasis

zing beurteilt ein Relay anhand des **Profils** des angegebenen Modells: natives
Kontextfenster, maximale Ausgabe, Wissensstichtag, Tokenizer, Fähigkeitsflags,
Identitätsschlüsselwörter und Verhaltens-Fingerabdrücke. Die mitgelieferten
Profile decken OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM und Moonshot
ab (`zing kb` listet sie). Es gibt drei Ebenen; spätere haben Vorrang:

1. **Mitgelieferte** Profile, eine YAML-Datei pro Anbieter in
   [`zing/knowledge/data/`](zing/knowledge/data).
2. **Ein Verzeichnis eigener YAML-Dateien**: `--kb-dir ./my-profiles`
   (wiederholbar) oder `ZING_KB_DIR`.
3. **Ihre Einträge** (`kb.db` im Datenverzeichnis), hinzugefügt ohne YAML-Dateien
   oder editierbare Installation:
   - auf der Seite **Wissen** der Weboberfläche (`/v2/kb`), mit je einem Tab für
     **Modelle**, **Anbieter** und **Relays**. Jeder Tab listet den vollständigen
     Bestand — mitgeliefert, `ZING_KB_DIR` und eigene (markiert mit **Eigener**) —
     mit Filter, einem Ein/Aus-Schalter pro Element und einem Formular
     **… hinzufügen**: **Modell hinzufügen** → **Recherche-Prompt kopieren** und in
     den KI-Assistenten Ihrer Wahl einfügen, das YAML seiner Antwort hochladen oder
     einfügen, dann **Prüfen und speichern**; **Anbieter hinzufügen** nimmt
     Anbieter-YAML auf dieselbe Weise; **Relay hinzufügen** nimmt Namen und
     Basis-URL. **Welches Profil verwendet eine Modell-ID?** zeigt, wie eine ID
     aufgelöst wird; Ihre Einträge lassen sich als YAML exportieren;
   - auf den Seiten **Prüfung** und **Werkzeuge** der Weboberfläche: **In der
     Wissensbasis speichern** behält Namen und Basis-URL eines Relays (ein
     Anbieter-Eintrag ohne Modelle), aufgeführt unter **Wissen → Relays**;
   - auf der Kommandozeile: `zing kb-prompt <model>`, `zing kb-import <file>`
     (mit `--check` nur prüfen) und `zing kb-export`.

Vor dem Speichern prüft zing einen Eintrag: Schema und Grenzen, unsichere
reguläre Ausdrücke, jeden Prompt, den er senden würde, und Modell-IDs, die zu
einem anderen Profil aufgelöst würden. Ein eigenes Modell mit der ID eines
mitgelieferten ersetzt dieses (als *Überschattung* ausgewiesen), ändert aber nie
die Einstellungen eines mitgelieferten Anbieters; Fingerabdrücke werden anhand
ihrer ID zusammengeführt. Das Ausschalten eines mitgelieferten Modells, Anbieters
oder Relays auf der Seite **Wissen** wird ebenfalls in `kb.db` gespeichert: eine
ausgeschaltete Modell-ID wird nicht mehr aufgelöst, ein ausgeschalteter Anbieter
nimmt seine Modelle und Basis-URLs mit. `zing check` und `zing serve` nutzen genau
dieselben Profile; `--no-user-kb` (oder `ZING_NO_USER_KB=1`) lässt Ihre Einträge
und Schalter weg.

Ein Modell mit leeren `identity_keywords` wird so nicht gespeichert: zing
ergänzt seine eigenen Markenwörter aus den Namen von Anbieter und Modell (etwa
`glm` und `z.ai`) und zeigt eine Warnung,
sie zu prüfen, denn ohne sie könnte die Identitätsprüfung den eigenen Hersteller
des Modells für eine Konkurrenzmarke halten. Der Recherche-Prompt verlangt sie
ausdrücklich vom KI-Assistenten.

Jeder Bericht hält fest, gegen welches Profil er geprüft hat (`knowledge`:
Anbieter, Modell, wie die ID zugeordnet wurde, ihre Quelle und ein vollständiger
Schnappschuss mit Inhalts-Hash), sodass ein Bericht auch nach Änderungen an der
Wissensbasis überprüfbar bleibt.

## Berichte

`zing check` und `zing compare` geben ein Urteil aus und schreiben den Bericht nach
`reports/` (`--out-dir`) als JSON, Markdown, HTML und PDF (`--format all`, der
Standard); `--format json|md|html|pdf` schreibt ein einzelnes Format. `--json` und
`--compact` geben stattdessen auf stdout aus.

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

Ein Bericht enthält das Urteil (Risiko, Konfidenz, Bewertung, Note), die
wichtigsten Befunde mit Empfehlungen, die Bewertungen je Dimension und
**Dimension details**, die Befunde jedes Detektors mit Belegen, den
Leistungsabschnitt, das verwendete Wissensbasis-Profil und die Testsprachen. Vom
Relay kontrollierter Text wird vor dem Schreiben geschwärzt und maskiert.

## Datenschutz und lokale Daten

- **Nur lokal.** `zing serve` lauscht nur auf Loopback (`127.0.0.1`, `::1`,
  `localhost`), antwortet nur unter diesen Hostnamen und weist
  seitenübergreifende Anfragen ab; es hat keine Anmeldung, weil nichts außerhalb
  Ihres Rechners es erreichen kann. zing kontaktiert nur die Endpunkte, die Sie
  konfigurieren (Ziel, Referenz, Richter, Webhooks); zur Laufzeit lädt es nichts
  herunter, nicht einmal Tokenizer-Dateien.
- **Schlüssel.** Berichte und Verlauf speichern von einem API-Schlüssel nur
  einen Fingerabdruck. Die Schlüssel der Überwachungen liegen verschlüsselt in
  `watches.db`; der Hauptschlüssel, der sie entschlüsselt, wird nie im
  Datenverzeichnis gespeichert (Sie bewahren ihn auf, siehe **Überwachung**
  oben), sodass eine Kopie des Verzeichnisses keinen API-Schlüssel preisgibt.
  Zugriff auf das Verzeichnis haben trotzdem nur Sie.
- **Datenverzeichnis.** `~/.zing` (oder `ZING_DATA_DIR`), angelegt mit `0700`
  und Dateien mit `0600`: `history.db` (Prüfverlauf), `watches.db`
  (Überwachungen samt verschlüsselter Schlüssel) und `kb.db` (Ihre
  Wissensbasis-Einträge). Löschen Sie das Verzeichnis, um alles zu entfernen.
  `zing data-dir` zeigt, wo es liegt; `--data-dir PFAD` wählt für einen Lauf
  ein anderes, z. B. legt `zing serve --data-dir .` die Datenbanken im
  aktuellen Ordner ab. Es sind normale SQLite-Dateien, die Sie für eigene
  Auswertungen öffnen können (während zing läuft, am besten nur lesend).
  `history_metrics` enthält eine Zeile Messwerte pro Lauf, `history_requests`
  jeden Anfrage-Datensatz (dort einmal gespeichert, nicht in jedem Bericht).
  Committen Sie `watches.db` nicht, falls der Ordner ein Repository ist.

## Verantwortungsvoller Einsatz

zing ist ein Hilfsmittel für Black-Box-Prüfungen. Es **kann nicht beweisen**,

- dass ein Anbieter Ihre Prompts speichert oder damit trainiert,
- dass er immer an genau ein bestimmtes Modell weiterleitet (Relays können probabilistisch routen),
- Abrechnungsbetrug über das hinaus, was die unabhängige Token-Schätzung nahelegen kann.

Nutzen Sie die Berichte für Ihre eigene Sorgfaltsprüfung. **Beschuldigen Sie einen
Anbieter nicht öffentlich** auf Grundlage eines einzelnen Laufs, ohne
Stichprobengröße, Kosteneinstellungen und lokales Recht zu prüfen. Führen Sie
`zing compare` gegen eine vertrauenswürdige Referenz aus, bevor Sie weitreichende
Schlüsse ziehen.

## Weitere Dokumentation

| Dokument | Wofür |
|---|---|
| [Methodik](docs/METHODOLOGY.de.md) | Wie jede Prüfung funktioniert, ihre Bewertungsskala und ihre Einschränkungen |
| [Entwicklerhandbuch](DEVELOPER_GUIDE.de.md) | Architektur, Entwicklungsumgebung, Mitwirken, Übersetzungen, Docker, Releases |
| [docs/CI.md](docs/CI.md) | Die GitHub Action: Ein- und Ausgaben, Beispiele (englisch) |
| [docs/DOCKER.md](docs/DOCKER.md) | Die Weboberfläche in einem Container betreiben (englisch) |
| [CHANGELOG.md](CHANGELOG.md) | Was sich in jeder Version geändert hat (englisch) |
| [SECURITY.md](SECURITY.md) | Eine Sicherheitslücke melden (englisch) |

## Lizenz

[Apache-2.0](LICENSE)
