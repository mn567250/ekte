# zing — Entwicklerhandbuch

> [🇬🇧 English](DEVELOPER_GUIDE.md) · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · **🇩🇪 Deutsch**

Dieses Handbuch richtet sich an alle, die zing verändern: wie es aufgebaut ist,
wie Sie eine Entwicklungsumgebung einrichten, wie Sie mitwirken und wie es
paketiert, in Docker betrieben und veröffentlicht wird. Was zing tut und wie man
es nutzt, steht im [README](README.de.md); wie jede Prüfung funktioniert und
bewertet wird, in der [Methodik](docs/METHODOLOGY.de.md).

---

## Inhalt

- [Grundsätze](#grundsätze)
- [Entwicklungsumgebung](#entwicklungsumgebung)
- [Aufbau des Repositorys](#aufbau-des-repositorys)
- [Architektur](#architektur)
  - [Ablauf einer Prüfung](#ablauf-einer-prüfung)
  - [Clients](#clients)
  - [Detektoren und Bewertungsskalen](#detektoren-und-bewertungsskalen)
  - [Bewertung und Urteil](#bewertung-und-urteil)
  - [Wissensbasis](#wissensbasis)
  - [Prompt-Bibliothek](#prompt-bibliothek)
  - [Berichte](#berichte)
  - [Eigenständige Prüfer](#eigenständige-prüfer)
  - [Webserver](#webserver)
  - [Web-Frontend](#web-frontend)
  - [Lokale Daten](#lokale-daten)
- [Mitwirken](#mitwirken)
  - [Pull Requests](#pull-requests)
  - [Einen Detektor hinzufügen](#einen-detektor-hinzufügen)
  - [Die Wissensbasis bearbeiten](#die-wissensbasis-bearbeiten)
  - [Test-Prompts ändern](#test-prompts-ändern)
  - [Übersetzungen](#übersetzungen)
  - [Dokumentation](#dokumentation)
- [Tests](#tests)
- [Docker](#docker)
- [Continuous Integration](#continuous-integration)
- [Releases](#releases)
- [Sicherheit](#sicherheit)
- [Lizenz](#lizenz)

## Grundsätze

zing ist ein Hilfsmittel für Black-Box-Prüfungen: Korrektheit und **ehrliche
Relays nicht fälschlich zu beschuldigen** sind wichtiger, als jeden möglichen
Trick zu erwischen. Behalten Sie diesen Maßstab bei jeder Änderung im Blick.

- **Belege statt Anschuldigungen.** Befunde melden *Abweichung und Risiko*, nie
  „Betrug“. Lieber *nicht eindeutig* als geraten. Ein neuer Pfad mit Schweregrad
  HOCH braucht harte, reproduzierbare Belege und darf bei einem ehrlichen
  Endpunkt kaum auslösen.
- **Kein Netzwerk in Tests.** Detektortests laufen gegen den prozessinternen
  Mock-Server in `tests/conftest.py` (httpx `MockTransport`), nie gegen eine
  echte API.
- **Geheimnisse bleiben, wo sie sind.** API-Schlüssel werden als Fingerabdruck
  festgehalten, nie in Berichten gespeichert. Jeder neue Ausgabepfad muss vom
  Relay kontrollierten Text durch `zing.utils.redact` leiten und für sein Format
  maskieren.
- **Dieselben Tests für alle.** Testtexte sind englisch und fest, unabhängig von
  der Sprache der Oberfläche, damit dasselbe Relay dasselbe Urteil erhält (siehe
  [Prompt-Bibliothek](#prompt-bibliothek)).
- **Nur lokal.** zing kontaktiert nur die vom Nutzer konfigurierten Endpunkte,
  und die Weboberfläche lauscht nur auf Loopback (siehe [Webserver](#webserver)).

## Entwicklungsumgebung

Erfordert Python 3.10+. Node.js ist optional: die Tests des Browser-JavaScripts
laufen unter `node` und werden ohne es übersprungen.

```bash
git clone https://github.com/cenbonew/zing
cd zing
pip install -e '.[dev,web]'   # editierbare Installation mit Entwicklerwerkzeugen und Weboberfläche
pytest                        # Testsuite
ruff check zing tests         # Lint
mypy zing                     # Typprüfung
```

Mit uv: `uv venv && uv pip install -e '.[dev,web]'`. Systembibliotheken
sind nicht nötig, auch nicht für PDF-Berichte.

Aus dem Quellcode starten Sie mit `zing …` oder `python -m zing …`. `zing serve`
liefert die Weboberfläche direkt aus `zing/web/static/` aus, ein Neuladen im
Browser übernimmt also Änderungen am Frontend; es gibt keinen Build-Schritt.

## Aufbau des Repositorys

```text
zing/
  cli.py               Typer-CLI: check, compare, models, kb*, serve, watch, embed, rerank, image, audio
  config.py            YAML-Konfiguration, Geheimnis-Verweise (env:/file:), AuditOptions
  runner.py            run_audit(): verdrahtet alles und führt die Detektoren aus
  context.py           AuditContext, den jeder Detektor erhält
  models.py            pydantic-Datenverträge: TargetConfig, Finding, DetectorResult, AuditReport, …
  scoring.py           Dimensionsbewertungen, Gewichte, Gesamtbewertung, Risikourteil, Konfidenz
  clients/             HTTP-Clients: OpenAI-kompatibel, Anthropic Messages, OpenAI Responses
  detectors/           eine Datei pro Detektor, dazu base.py (Registry), scale.py, helpers.py
  judge/               der vertrauenswürdige LLM-Richter für quality_judge
  knowledge/           Schema, Loader, Nutzerspeicher (kb.db), Import, Recherche-Prompt, Schnappschüsse
    data/              mitgelieferte Anbieterprofile (*.yaml)
  prompts/en.json      jeder Text, den zing an eine LLM-API sendet
  perf/                Aufzeichnung je Anfrage und der Leistungsabschnitt des Berichts
  report/              Renderer für JSON / Markdown / HTML / PDF und der Writer
  embed_audit.py       eigenständiger Prüfer für Embedding und Rerank
  media_audit.py       eigenständiger Prüfer für Bild und Audio (TTS)
  notify.py            Webhook-Warnungen (Slack / Feishu / DingTalk / generisches JSON)
  datadir.py           das lokale Datenverzeichnis und seine SQLite-Dateien
  secretbox.py         Verschlüsselung gespeicherter Geheimnisse; der Hauptschlüssel im Speicher
  i18n/                Übersetzungen, geteilt von Weboberfläche und Warnungen
    locales/           <code>.json je Sprache, fragments/<feature>/<code>.json
  utils/               Schwärzung, SSE-Parsing, Statistik, Token-Schätzung
  web/
    server.py          FastAPI-App: Seiten, JSON-API, SSE-Prüfstrom, Überwachungs-Scheduler
    jobs.py            Hintergrund-Prüfaufträge und die Relay-Sperre
    security.py        Loopback-Bindung, Host-Allowlist, Origin-/JSON-Prüfung, Header
    history.py         Speicher des Prüfverlaufs (history.db)
    analytics_store.py seine Analysetabellen: Kennzahlen pro Lauf, Anfrage-Datensätze
    analytics.py       Analyseabfragen: Kennzahlen, Zeitreihen, Ranglisten
    watches.py         Speicher der Überwachungen (watches.db)
    masterkey.py       Zustände und Aktionen des Hauptschlüssels (Server und `zing secret`)
    static/            Seiten der klassischen Oberfläche und gemeinsame Skripte (lang.js, i18n.js, …)
    static/v2/         Seiten, Styles und Skripte der neuen Oberfläche
tests/                 pytest-Suite; conftest.py enthält das Mock-Relay
docs/                  METHODOLOGY (7 Sprachen), CI.md, DOCKER.md, PUBLISHING.md
examples/zing.yaml     kommentierte Konfigurationsdatei
prototypes/            statische HTML-Designprototypen der Weboberfläche (nicht ausgeliefert)
action.yml             die GitHub Composite Action
Dockerfile             Image der Weboberfläche
```

## Architektur

### Ablauf einer Prüfung

`zing check`, `zing compare`, `zing watch`, der Prüfstrom der Weboberfläche und
ihr Überwachungs-Scheduler münden alle in dieselbe Funktion,
`zing.runner.run_audit()`:

1. **Konfiguration.** `zing/config.py` führt die YAML-Konfiguration mit den
   Kommandozeilenoptionen zu `TargetConfig` (Ziel, optional Referenz und Richter)
   und `AuditOptions` (Suite, Dimensionen, Umfang der Tests, Ausgabe) zusammen.
   Als `env:VAR` oder `file:/pfad` angegebene API-Schlüssel werden hier aufgelöst.
2. **Wissensbasis.** `load_knowledge_base()` lädt die mitgelieferten Profile,
   `--kb-dir`/`ZING_KB_DIR` und die `kb.db` des Nutzers und löst das
   **angegebene** Modell (standardmäßig das angefragte) zu einem Profil auf. Eine
   Überwachung übergibt stattdessen ihren gebundenen Schnappschuss.
3. **Clients.** `make_client()` erzeugt einen Client für das Ziel (und die
   Referenz) im gewählten oder automatisch erkannten Protokoll. Ein
   `RequestRecorder` umschließt jeden Aufruf für den Leistungsabschnitt.
4. **Detektoren.** `select_detectors()` wählt die registrierten Detektoren für
   die Suite (oder die benutzerdefinierten Dimensionen) und lässt jene weg, denen
   ein Richter oder eine Referenz fehlt. Sie laufen **nacheinander**, mit Absicht:
   parallele Anfragen würden Ratenlimits auslösen und die Zeitmessungen
   verfälschen (die Zuverlässigkeits- und Leistungstests steuern ihre begrenzte
   Parallelität selbst). `run_detector()` misst die Dauer jedes Detektors und
   macht aus einem Absturz ein Ergebnis mit Status **Fehler**, sodass eine
   fehlerhafte Relay-Antwort die Prüfung nie abbricht.
5. **Bewertung.** `scoring.build_dimensions()` und `build_verdict()` machen aus
   den Detektorergebnissen die Dimensionsbewertungen, die Gesamtbewertung und
   Note, das Risikourteil und seine Konfidenz.
6. **Bericht.** Alles landet in einem `AuditReport` (`zing/models.py`) mit dem
   geschwärzten Ziel, dem Schnappschuss des Wissensbasis-Profils, dem
   Leistungsabschnitt und den Testsprachen. Die CLI rendert und schreibt ihn; die
   Weboberfläche streamt ihn.

`run_audit()` nimmt einen Callback `on_event` entgegen; der Webserver macht aus
dessen Ereignissen (Detektor gestartet/beendet mit kompakten Befunden, gebündelte
Zeiten je Anfrage) Server-Sent Events für die Live-Ansicht.

### Clients

`zing/clients/` enthält einen Client je Protokoll — `openai_compatible.py`
(Chat Completions), `anthropic.py` (Messages) und `responses.py` (Responses) —
mit derselben Schnittstelle, gebaut auf der gemeinsamen HTTP-Mechanik in
`base.py`. `make_client()` in `clients/__init__.py` wählt einen anhand von
`--api` oder erkennt ihn an Basis-URL und Modell. Detektoren sprechen nur mit
dieser Schnittstelle (`RequestSpec` hinein, `CompletionOutcome` heraus) und sind
damit protokollunabhängig.

Die Clients passen Anfragen außerdem an, was das Modell annimmt (`base.py`):
der Runner belegt `unsupported_params` aus dem Profil, dort genannte
Sampling-Parameter werden weggelassen, und bei Chat Completions geht das Limit
als `max_completion_tokens` hinaus, wenn `max_tokens` genannt ist. Ein 4xx, das
einen solchen Parameter nennt, fügt ihn hinzu und wiederholt die Anfrage einmal
angepasst (der abgelehnte Versuch wird mit Phase `param_retry` erfasst). Eine
Probe, die die unveränderte Ablehnung bewertet, setzt `RequestSpec.exact_params`.

### Detektoren und Bewertungsskalen

Ein Detektor ist eine eigenständige Datei in `zing/detectors/`: eine
Unterklasse von `Detector` (`base.py`) mit `id`, `name`, `dimension`, der ersten
Suite, in der er läuft (`min_suite`), einem ungefähren `cost_hint` für
`--dry-run` und `async def run(self, ctx) -> DetectorResult`. `@register` trägt
ihn in die Registry ein; `zing/detectors/__init__.py` importiert jedes Modul,
damit die Registry vollständig ist.

Jeder Detektor veröffentlicht seine **Bewertungsskala** (`SCALE`, erstellt mit
`scale.py`): jedes mögliche Ergebnis jeder Prüfung mit Punkten, Status und
Schweregrad. Befunde werden aus der Skala erzeugt
(`SCALE.finding(check, outcome, …)`), sodass Bericht und Verhalten nicht
auseinanderlaufen können. `Scale` bewertet mit dem Mittelwert der Prüfungen;
`DeductionScale` beginnt bei 100 und zieht ab oder begrenzt. Die Weboberfläche
zeigt die Skala unter **Bewertungsskala**; die [Methodik](docs/METHODOLOGY.de.md)
gibt jede Skala wieder. `connectivity.py` ist das kanonische, kürzeste Beispiel.

Detektoren teilen sich in `zing serve` eine Event-Loop mit allen anderen
Prüfungen, daher darf CPU-intensive Arbeit nicht auf ihr laufen: Eine blockierte
Loop verzögert die Anfragen anderer Prüfungen und bläht die Latenzen auf, die sie
messen. `helpers.build_filler()` erzeugt Fülltext in linearer Zeit und merkt sich
die letzten Größen; die Kontextfenster- und Prompt-Cache-Detektoren rufen es (und
`build_haystack()`) über `asyncio.to_thread` auf. Token-Zahlen stammen aus
`zing/utils/tokenize.py`, einer Heuristik nur mit der Standardbibliothek: zing
importiert keine Tokenizer-Bibliothek und lädt zur Laufzeit nichts herunter,
läuft also auch in eingeschränkten Umgebungen. Das Argument `tokenizer` von
`estimate_tokens()` wird angenommen, ändert die Zählung aber nicht, und die
Berichtsfelder `tokens_exact` / `exact_tokenizer` bleiben aus Kompatibilitätsgründen
erhalten und sind immer false.

### Bewertung und Urteil

`zing/scoring.py` enthält `DIMENSION_WEIGHTS` und die Regeln des Urteils: die
Bewertung einer Dimension ist der gleich gewichtete Mittelwert ihrer Detektoren,
die Gesamtbewertung der gewichtete Mittelwert der gelaufenen Dimensionen, und die
Risikostufe folgt der Schweregrad-Leiter aus
[Methodik → Wie zing bewertet](docs/METHODOLOGY.de.md#wie-zing-bewertet). Jede
Dimension hält in `DimensionScore.breakdown` fest, wie sie berechnet wurde;
daraus entstehen **Dimension details** in den Berichten und die aufklappbaren
Zeilen der **Prüfungen je Dimension** in der Weboberfläche.

### Wissensbasis

`zing/knowledge/` definiert das Profilschema (`schema.py`: `ProviderProfile`,
`ModelProfile`, `FingerprintProbe`), lädt und verschmilzt die Ebenen
(`loader.py`: mitgeliefertes YAML → `ZING_KB_DIR`/`--kb-dir` → die `kb.db` des
Nutzers), speichert die Einträge des Nutzers (`store.py`), prüft und importiert
YAML (`importer.py`), erzeugt den Recherche-Prompt für externe Assistenten
(`research.py`) und hält einen Schnappschuss des Profils fest, das ein Lauf
verwendet hat (`snapshot.py`). Modell-IDs werden exakt, über Aliasse oder den
normalisierten Namen aufgelöst, eingegrenzt durch den angegebenen Anbieter. Die
unscharfe Rückfallstufe nimmt den längsten KB-Namen, den die Angabe enthält
(eine Snapshot- oder dekorierte ID), außer der Rest der Angabe nennt eine andere
Stufe oder Variante (`-mini`, `-lite`, `-image`, …); eine gekürzte Angabe wird
nur aufgelöst, wenn genau ein Modellname mit ihr beginnt, sodass eine
mehrdeutige ID wie `gpt-4` kein Profil statt einer geratenen Stufe erhält. Jeder
Bericht vermerkt, wie die ID zugeordnet wurde.

`load_knowledge_base()` speichert zusammengeführte Ergebnisse zwischen und gibt
standardmäßig eine tiefe Kopie zurück, sodass Aufrufer das Erhaltene ändern
dürfen. Aufrufer, die nur lesen (Listen und Katalog der Weboberfläche, das
Auflösen eines Modells), übergeben `copy=False` und erhalten die gemeinsame
zwischengespeicherte Instanz, die sie nicht verändern dürfen.

Relays sind ebenfalls Endpunkte: `relays.py` macht aus den `base_url_hints`
eines Anbieters verwendbare Basis-URLs (`GET /api/kb` → `base_urls`) und speichert
ein Relay aus der Weboberfläche als Anbieter-Eintrag in `kb.db` (`origin =
relay`: ein `display_name` und eine Basis-URL, keine Modelle; keine
Schemaänderung).

### Prompt-Bibliothek

Jeder Text, den zing an eine LLM-API sendet — Chat-Tests, der Prompt des
Richters, Tool-Schemata, Eingaben für Embedding / Rerank / Bild / Audio — liegt
in `zing/prompts/en.json` und wird mit `zing.prompts.text()` / `get()` gelesen.
`{{name}}` markiert einen Wert, der zur Laufzeit eingesetzt wird. Die Testsprache
ist fest auf Englisch gesetzt (`PROBE_LANG`), unabhängig von der Sprache der
Oberfläche, weil Antwortprüfungen und Token-Schätzungen auf genau diese Texte
kalibriert sind. Tests, deren Sprache *selbst* die Messgröße ist (z. B.
chinesische Sprachgewandtheit, Tokenizer oder Selbstidentifikation chinesischer
Modelle), liegen mit ihren erwarteten Antworten in der Wissensbasis und geben
`prompt_lang` und einen `language_bound`-Grund an. Der Runner vermerkt die
verwendeten Sprachen in `prompt_languages`.

### Berichte

`zing/report/render.py` rendert einen `AuditReport` als JSON, kompaktes
Agenten-JSON, Markdown und HTML; `dimensions.py` und `performance.py` rendern
**Dimension details** und den Leistungsabschnitt; `pdf.py` setzt das PDF mit
ReportLab aus denselben Daten und Hilfsfunktionen (reines Python; nur die
PDF-Standardschriften, für Chinesisch die CID-Schrift STSong-Light, also nichts
eingebettet; lädt nie externe Ressourcen), und CLI und Weboberfläche nutzen es
gemeinsam;
`writer.py` schreibt die Dateien. Vom Relay kontrollierter Text wird vor der
Ausgabe geschwärzt und maskiert (HTML / Markdown). `POST /api/report/export` der
Weboberfläche nutzt diese Renderer für die Zeile **Bericht herunterladen**, mit in
die Sprache der Oberfläche übersetzten Texten.

### Eigenständige Prüfer

Embedding/Rerank (`embed_audit.py`) und Bild/Audio (`media_audit.py`) sind
keine Chat-Schnittstellen und haben daher eigene kleine Prüfer mit eigenem
Urteil statt der Detektor-Pipeline. Sie teilen die HTTP-Einstellungen der
Clients, die Wissensbasis (native Dimensionen, Bildgrößen, Stimmen) und die
Prompt-Bibliothek. Die gesamte Dekodierung (Bild-Header, WAV) nutzt nur die
Standardbibliothek.

### Webserver

`zing/web/server.py` ist eine FastAPI-App, erzeugt von `create_app()`:

- **Seiten.** Die klassische Oberfläche (`/`, `/console`, `/history`,
  `/watches`, `/tools`) und die neue Oberfläche (`/v2/`, `/v2/history`,
  `/v2/watches`, `/v2/tools`, `/v2/kb`) sind statische HTML-Dateien. `?ui=v2` /
  `?ui=v1` schaltet um, und ein Cookie merkt sich die Wahl, sodass eine klassische
  URL auf ihr neues Gegenstück umleitet, sobald die neue Oberfläche gewählt wurde.
- **API.** `/api/audit/stream` führt eine Prüfung aus und streamt ihre Ereignisse
  per SSE; `/api/models` listet die Modelle eines Relays; `/api/report/export`
  rendert einen Bericht; `/api/history…`, `/api/watches…`, `/api/kb…`,
  `/api/embed` und `/api/rerank` bedienen die übrigen Seiten.
- **Relays.** `POST /api/kb/relays` speichert ein Relay `{name, base_url}` (400
  bei ungültiger Eingabe, 409, wenn Name oder URL schon bekannt sind).
- **Analysen.** `GET /api/analytics/options` (Relays, Modelle, Suites,
  Stream-Modi, APIs und der Zeitraum der Historie), `/api/analytics/summary`
  (Kennzahlen von `from`–`to` gegenüber dem gleich langen Zeitraum davor),
  `/api/analytics/series` (`metric` je `group=relay|model|relay_model`, bis zu
  4 `keys`, in `bucket=hour|day|week|dow_hour`-Intervallen in der Zeitzone des
  Betrachters, `tz` oder `tz_offset`) und `/api/analytics/leaderboard`
  (`model=` für dessen Relays oder `relay=` für dessen Modelle). Alle nehmen die
  Filter `from`, `to`, `suite`, `stream_mode`, `api`,
  `source=all|manual|monitor`, `relay` und `model`. `zing/web/analytics.py`
  rechnet alles in Python aus `history.analytics_runs()`: Metrik-IDs kommen aus
  einer festen Positivliste, Relays werden bei jeder Abfrage nach ihrem Eintrag
  in der Wissensbasis gruppiert, ein Wert, den ein Lauf nicht gemessen hat,
  bleibt außen vor (jeder Wert hat sein `n` und seine `coverage`), und
  Intervalle mit weniger als `MIN_RUNS` (3) Läufen tragen `low_n`. Ein
  ungültiger Parameter ergibt 400; Antworten sind `Cache-Control: no-store`.
- **Analyse-Bereiche.** `/api/analytics/breakdown` (bis zu 8 `metrics` pro
  `group=relay|model|relay_model|all` über den Zeitraum),
  `/api/analytics/errors` (die Completion-Aufrufe an das Ziel nach
  Ergebnisklasse `success|client_4xx|rate_limited|server_5xx|timeout|network|other`,
  pro `group=relay|model` und pro `bucket`, in SQL gezählt von
  `history.analytics_request_classes()`, ohne Anfragezeilen zu laden; die Zeit
  eines Aufrufs ist der Start seines Laufs plus sein Versatz, minutengenau;
  `covered` = Läufe mit Anfragedaten) und `/api/analytics/integrity`
  (Bestanden-/Warnung-/Fehlschlag-Zahlen der Detektoren für Identität,
  Fähigkeiten, Bildverständnis, Streaming, Protokoll, Integrität, eingeschleuste
  Prompts und Konnektivität pro Relay × Modell, der Anteil abweichender Modelle
  und das mediane Verhältnis gemessenes / angegebenes Kontextfenster).
  `/api/analytics/series` nimmt auch `group=all`. Filter und Fehler wie oben.
- **Prüfungen im Hintergrund.** `jobs.py` führt jede Prüfung als Auftrag des
  Servers aus. `POST /api/jobs` stellt einen ein, `GET /api/jobs` listet
  wartende, laufende und kürzlich beendete Aufträge (und laufende
  Überwachungen) mit Fortschritt, `GET /api/jobs/{id}/events` spielt das
  Ereignisprotokoll ab und folgt ihm dann live per SSE, `POST
  /api/jobs/{id}/cancel` bricht ab. Die neue Oberfläche nutzt diese Endpunkte,
  daher überdauert eine Prüfung die Seite; `/api/audit/stream` (klassische
  Oberfläche) verwendet denselben Auftrag und bricht ihn ab, wenn der Strom
  endet. Eine Relay-Sperre lässt je Relay nur eine Prüfung (oder einen
  Überwachungslauf) zu, nach Hostname, alle Loopback-Adressen als ein Host;
  höchstens `ZING_MAX_PARALLEL_AUDITS` (Standard 4) laufen gleichzeitig,
  Wartende in Ankunftsreihenfolge.
- **Überwachungs-Scheduler.** Der Lifespan der App startet eine
  Hintergrundschleife, die jede fällige Überwachung als eigenen Task startet,
  sodass Überwachungen auf verschiedenen Relays gleichzeitig prüfen; die
  Relay-Sperre gilt weiterhin, daher können Überwachungen die
  `ZING_MAX_PARALLEL_AUDITS` Plätze füllen, und eine manuelle Prüfung reiht sich
  womöglich dahinter ein. `last_run_ts` eines Laufs ist der Moment, in dem seine
  Prüfung beginnt (nach dem Warten auf sein Relay). Jeder Lauf wird im Verlauf
  gespeichert; die Prüfung auf Verschlechterung vergleicht ihn mit dem zuletzt
  gespeicherten Lauf desselben Ziels und Modells (`history.latest_for()`, ein
  indizierter Zugriff) und sendet die Webhook-Warnungen (`zing/notify.py`) bei
  Schwellenüberschreitung oder Verschlechterung gleichzeitig.
  `POST /api/watches/{id}/run` antwortet mit 409, solange der Scheduler diese
  Überwachung gerade gestartet hat; ein Zurücksetzen des Hauptschlüssels bricht
  geplante, noch nicht gestartete Läufe ab, und das Herunterfahren bricht
  laufende ab.
- **Komprimierung und Caching.** `caching.py` komprimiert Antworten ab 1 KiB
  (außer Server-Sent Events) mit gzip für Clients, die es akzeptieren
  (`gzip;q=0` lehnt ab). Seiten und `/locales.js` werden beim Erzeugen einmal
  komprimiert und vorkomprimiert mit `Content-Encoding: gzip`,
  `Vary: Accept-Encoding` und einem eigenen, auf `-gz` endenden ETag
  ausgeliefert; Seiten laufen über `html_page(page, request.scope)`, damit sie
  diesen Weg nehmen und bedingte Anfragen mit 304 beantworten. Lokale Skript- und
  Stylesheet-URLs in Seiten tragen ein `?v=<content hash>` und werden als
  unveränderlich gecacht.
- **Sicherheit.** `security.py` bestimmt die Bindungsadresse (nur Loopback,
  außer in einem erkannten Container mit `ZING_CONTAINER=1`) und installiert
  `LocalOnlyMiddleware`: eine Host-Allowlist gegen DNS-Rebinding, Prüfungen von
  Origin und `Sec-Fetch-Site` gegen CSRF, nur JSON als Anfragekörper sowie
  Header gegen Framing, MIME-Sniffing und Referrer. Die Oberfläche hat bewusst
  keine Anmeldung.

### Web-Frontend

Das Frontend ist reines HTML, CSS und Browser-JavaScript ohne Module und ohne
Build-Schritt. Die klassischen Seiten liegen in `zing/web/static/`; die neue
Oberfläche in `zing/web/static/v2/` teilt sich eine Kopfzeile (`nav.js`), den
Bericht-Renderer (`report.js`), die Designauswahl (`theme.js`) und die Styles
(`zing.css`, `fields.css`, `report.css`, `perf.css`). Gemeinsame Skripte werden
von der Wurzel ausgeliefert: `lang.js` (Sprachwahl), `locales.js`
(Übersetzungsdaten), `i18n.js` (Übersetzung der Befunde), `icons.js`,
`modelpicker.js` (**Modelle abrufen**), `secretfield.js` und `perf.js`
(Leistungsdiagramme).

Die v2-Seiten **Prüfung** und **Werkzeuge** konfigurieren Relays mit
`v2/relaycfg.js`: Auswahl Relay/Anbieter → Basis-URL → die Modelle des Relays
(`/api/models`, bei Änderung, zwischengespeichert pro URL/Schlüssel/Protokoll) →
angegebenes Modell aus der Wissensbasis (`/api/kb/resolve` wählt es vor) →
abgeleiteter Anbieter, dazu **In der Wissensbasis speichern** (`POST
/api/kb/relays`). Seine reinen Hilfsfunktionen werden unter node getestet; die
klassischen Seiten behalten `modelpicker.js`.

Die v2-Seite **Analyse** (`v2/analytics.html`) liest nur `/api/analytics/*`
(`options` nennt auch die Paare Relay × Modell, `relay_models`, für die
Reihenauswahl). Sie hat ein `<section class="card panel">` pro Panel unter einer
Filterleiste, neue Panels lassen sich also einfügen; Filter und Ansicht stehen
im URL-Fragment (`#range=30&metric=score&…`) und in `localStorage`. Die
Diagramme kommen aus `v2/charts.js` (`ZingCharts.timeChart`: handgezeichnetes
Inline-SVG mit Median-Linie, p25–p75-Band, Lücken für leere Abschnitte, blassen
Markern für `low_n`-Abschnitte, Markierungslinien und Hover-Tooltip; `fmt` /
`fmtDelta` formatieren Werte nach Einheit) und `v2/charts.css` (vier geprüfte
Reihenfarben je Theme, zusätzlich an der Markerform unterscheidbar). Jedes
Diagramm gibt es auch als Datentabelle.

Jeder Bereich ist in sich geschlossen: eine `PANELS`-Registry im Seitenskript
nennt seine Section-ID, `load()` (mit den aktuellen Filtern und der Ansicht
laden, dann zeichnen) und `render()` (aus den geladenen Daten neu zeichnen,
z. B. beim Sprachwechsel), sodass Bereiche umgestellt werden können, ohne
einander zu berühren. `ZingCharts.heatmap` zeichnet das Raster Wochentag ×
Stunde (fünfstufige einfarbige Skala pro Theme, schraffierte Zellen für
`low_n`, umrandete leere Zellen), `ZingCharts.stackBars` die gestapelten
Fehlerbalken, und `timeChart` nimmt eine `ref`-Linie (100 %
Abrechnungsverhältnis).

Seitenkopf und Filterpanel stehen über fünf seiteninternen Tabs
(`v2/tabs.js`, wie bei Werkzeuge und Wissen): Jeder `PANELS`-Eintrag
nennt seinen `tab`, und nur die Bereiche des angezeigten Tabs laden; eine
Filteränderung lädt diesen Tab neu und markiert die anderen als veraltet
(`activate()` lädt sie beim Anzeigen). `tabs.js` bekommt hier
`writeHash: false`, denn die Seite schreibt die ganze Ansicht selbst ins
Fragment — `#tab=trends&range=30&suite=…&metric=…` (`stateQuery()`), das
**Link zu dieser Ansicht kopieren** kopiert (ein markiertes schreibgeschütztes
Feld, wenn die Zwischenablage-API fehlt oder ablehnt); ein Fragment ohne `tab`
öffnet den Überblick, ein eingefügter Link (`hashchange`) liest die Ansicht neu.
Das einklappbare Filterpanel ist `v2/filterpanel.js` + `v2/filterpanel.css`,
gemeinsam mit dem Verlauf: `ZingFilterPanel.create(section, {label, title,
storeKey, open, onReset})` liefert `render({body, foot, count, summary})`,
`sync({count, summary})`, `setOpen()` und `focusStart()`; die Seite besitzt ihre
Filter und Felder, das Panel den Umschalter mit dem Zähler aktiver Filter, die
einzeilige Zusammenfassung im eingeklappten Zustand, den gemerkten
Offen-Zustand und **Filter zurücksetzen**.

**Übersetzungskonvention.** Der chinesische Text im HTML ist das Original und
bleibt unverändert; jedes Element trägt seinen englischen Text in `data-en` (und
`data-en-placeholder`, `data-en-title`, `data-en-aria-label`). Der englische Text
ist der Suchschlüssel für alle anderen Sprachen. Skripte nutzen `T(zh, en)` für
dynamischen Text und `ZING_LANG.server(text)` für Text aus dem Backend
(Detektornamen, Empfehlungen, Sätze des Urteils).

### Lokale Daten

`zing/datadir.py` verwaltet `$ZING_DATA_DIR` (Standard `~/.zing`), angelegt mit
`0700` und SQLite-Dateien mit `0600`: `history.db` (`web/history.py`),
`watches.db` (`web/watches.py`, enthält die API-Schlüssel der Überwachungen,
verschlüsselt) und `kb.db` (`knowledge/store.py`). Jeder Aufruf öffnet eine
kurzlebige Verbindung, daher sind die Speicher im Threadpool von FastAPI sicher.
Die globale Option `--data-dir` (auch bei `zing serve`) setzt lediglich
`ZING_DATA_DIR` auf den absoluten Pfad, und `zing data-dir` gibt das aufgelöste
Verzeichnis aus. Ein bereits vorhandenes Verzeichnis behält seine Rechte; nur das
Standardverzeichnis `~/.zing` wird auf `0700` verschärft. Verlaufszeilen sind nach Ziel und Modell indiziert (`idx_history_target`), was
`history.latest_for()` nutzt, um den vorigen Lauf einer Überwachung zu finden.

Seit Schemaversion 2 (`PRAGMA user_version`) enthält `history.db` auch die
Analysetabellen, definiert in `web/analytics_store.py`: `history_metrics` (eine
Zeile extrahierter Kennzahlen pro Lauf: Startzeit, Raten, Perzentile von
Latenz/TTFT/Dekodierung, Abrechnungsverhältnisse, Anzahl der Befunde und mehr;
NULL, wo der Lauf einen Wert nicht gemessen hat), `history_dimensions` (Werte
der Dimensionen und Detektoren) und `history_requests` (die Anfrage-Datensätze
des Laufs, Ziel und Baseline, in Listenreihenfolge). Die `performance.requests`
eines Berichts liegen nur dort: `save()` nimmt sie aus `report_json` heraus
(`requests_split` markiert die Zeile), `get()` / `latest_for()` setzen sie
wieder ein, sodass ein Bericht genau so zurückgelesen wird, wie er gespeichert
wurde; was die Spalten nicht exakt wiedergeben können, landet in der
JSON-Spalte `extra`. `extract_metrics()` ist eine reine, versionierte Funktion
(`EXTRACT_VERSION`). Nach der Migration verschiebt ein Backfill in Stapeln (eine
kurze Transaktion pro Stapel, idempotent) die Datensätze älterer Zeilen,
extrahiert ihre Kennzahlen und extrahiert Zeilen einer älteren
`EXTRACT_VERSION` neu; `history.backfill_analytics()` startet ihn bei Bedarf
erneut. Die Startzeit eines Laufs ist `started_at` des Berichts; Berichte von
vor diesem Feld erhalten `generated_at` minus die Zeitspanne ihrer
Anfrage-Datensätze (`started_at_estimated` = 1).

Gespeicherte API-Schlüssel verschlüsselt `zing/secretbox.py` (Fernet,
gespeichert als `enc:v1:…`; `env:`/`file:`-Verweise bleiben unverändert). Der
Hauptschlüssel selbst wird nie gespeichert: `web/masterkey.py` (`Vault`,
gemeinsam genutzt von Server und `zing secret`) hält ihn im Speicher des
Servers, sobald er aus `ZING_SECRET_KEY`, einer alten `secret.key` oder vom
Benutzer auf der Seite Überwachung kommt; `watches.db` enthält nur einen
Prüfwert (`secret_meta`), der einen falschen Schlüssel abweist. Ein neuer
Schlüssel verschlüsselt jeden gespeicherten Schlüssel neu und schreibt den
Prüfwert in einer einzigen Transaktion. Der Schlüssel liegt im Speicher eines
Prozesses, betreiben Sie daher einen Server pro Datenverzeichnis.

## Mitwirken

### Pull Requests

- Halten Sie `pytest`, `ruff check zing tests` und `mypy zing` grün (CI führt alle
  drei unter Python 3.10–3.13 aus).
- Beschreiben Sie den Relay-Trick oder den Fehlalarm, den eine Änderung behebt.
- Aktualisieren Sie `CHANGELOG.md` unter `[Unreleased]`.
- Aktualisieren Sie die betroffene Dokumentation — README, dieses Handbuch, die
  Methodik — in **jeder Sprache** (siehe [Dokumentation](#dokumentation)).

Mit Ihrem Beitrag stimmen Sie zu, dass er unter der
[Apache-2.0](LICENSE)-Lizenz des Projekts steht.

### Einen Detektor hinzufügen

1. Legen Sie `zing/detectors/<name>.py` an und importieren Sie es in
   `zing/detectors/__init__.py`.
2. Definieren Sie seine `SCALE` (`Scale` oder `DeductionScale` aus `scale.py`)
   mit jedem Ergebnis jeder Prüfung, und erzeugen Sie Befunde nur über sie.
3. Leiten Sie von `Detector` ab; setzen Sie `id`, `name`, `dimension`,
   `min_suite` und `cost_hint`; setzen Sie `requires_judge = True` oder
   `requires_baseline = True`, wenn er einen Richter oder eine Referenz braucht,
   oder überschreiben Sie `applies()` für andere Bedingungen. Dekorieren Sie die
   Klasse mit `@register`.
4. Implementieren Sie `async def run(self, ctx) -> DetectorResult`, beginnend mit
   `self.new_result(scoring=SCALE.scoring())`. Senden Sie Anfragen über
   `ctx.client` und nehmen Sie jeden Prompt aus `zing/prompts/en.json`.
5. Schreiben Sie Verhaltenstests für den auffälligen und den unauffälligen Pfad
   mit dem Mock-Relay aus `tests/conftest.py`.
6. Übersetzen Sie neue Titel und Zusammenfassungen von Befunden (siehe
   [Übersetzungen](#übersetzungen)) und dokumentieren Sie den Detektor und seine
   Skala in jeder [Methodik](docs/METHODOLOGY.de.md)-Datei.

### Die Wissensbasis bearbeiten

Profile liegen in `zing/knowledge/data/<provider>.yaml`, eine Datei pro Anbieter.
Jedes Modell enthält sein natives Kontextfenster, die maximale Ausgabe, den
Wissensstichtag, den Tokenizer, Modalitäten, Fähigkeitsflags, nicht unterstützte
Parameter, Identitätsschlüsselwörter und Fingerabdrücke (siehe
`zing/knowledge/schema.py`). Wenn Sie ein numerisches Feld ändern, **nennen Sie
eine maßgebliche Quelle** (die offizielle Modellkarte, Preisliste oder
Dokumentation des Anbieters) im Pull Request: ein falscher Wert verursacht
Fehlalarme gegen ehrliche Relays. `zing kb-import --check <datei>` führt dieselben
Prüfungen aus wie der Import durch Nutzer (Schema, Grenzen, unsichere reguläre
Ausdrücke, Prompts, ID-Kollisionen).

`fingerprints` auf Anbieterebene laufen für jedes Modell des Anbieters. Ein
Test, dessen Erwartung nur für manche Modelle gilt (ein Wissensstichtag, eine
Wissensprüfung der Pro-Stufe, eine Denkfalle), gehört in die `fingerprints`
dieser Modelle, sonst zählt eine wahrheitsgemäße Antwort eines anderen Modells
als Abweichung.

Füllen Sie `identity_keywords` immer mit den Hersteller- und Familienwörtern,
mit denen sich das Modell selbst bezeichnet. Die Identitätsprüfung zählt auch
Anbieter-Schlüssel, Anzeigenamen und Modell-ID als echte Marke, erweitert um die
übrigen Namen des Herstellers in `VENDOR_BRANDS` (`zing/knowledge/identity.py`,
zugleich die Liste konkurrierender Marken des Detektors); der Import ergänzt
leere Schlüsselwörter aus diesen Namen mit einer Warnung. Die Markenwörter eines
neuen Herstellers gehören dort als eine Gruppe hinein.

### Test-Prompts ändern

Testtexte sind Kalibrierdaten. Eine Änderung in `zing/prompts/en.json` kann
Antwortprüfungen, Token-Schätzungen und damit Urteile verändern; passen Sie den
Detektor und seine Tests mit an und nennen Sie die Änderung im CHANGELOG. Lassen
Sie einen Test nie der Sprache der Oberfläche folgen.

### Übersetzungen

Oberfläche und Webhook-Warnungen teilen sich einen Satz Übersetzungen in
`zing/i18n/locales/<code>.json`:

- `meta` — Code, der Eigenname der Sprache für das Menü, `html`-Sprache,
  Datumsformat und Reihenfolge im Menü;
- `strings` — englischer Text → Übersetzung (`en.json` ist die Identitätsabbildung
  und die maßgebliche Liste übersetzbarer Texte);
- `findings` — Befund-ID → `[Titel, Vorlage der Zusammenfassung]` (`zh.json`
  enthält den ursprünglichen chinesischen Katalog).

Features können ihre Texte als Fragmente mitbringen,
`zing/i18n/locales/fragments/<feature>/<code>.json` mit `{"strings": {…}}`, die
beim Laden in die Sprache eingemischt werden. `/locales.js` liefert nur die
gewählte Sprache (`?lang=<code>` oder das Cookie `zing_lang`, das `lang.js`
setzt; ohne beides alle Sprachen), je Variante einmal erzeugt und mit gzip
komprimiert und per `ETag` revalidiert;
ein Sprachwechsel lädt die neue Sprache bei Bedarf nach.

- **Neuer Text in der Oberfläche:** den chinesischen Text ins HTML und den
  englischen in `data-en` schreiben (oder `T(zh, en)` nutzen), dann den
  englischen Schlüssel in `en.json` oder einem Fragment ergänzen und seine
  Übersetzung in jeder anderen Sprache.
- **Neue Sprache:** `zing/i18n/locales/<code>.json` anlegen (`de.json` kopieren)
  und eine Datei je Fragment; Sprachmenü, Seiten, Warnungen und `--alert-lang`
  übernehmen sie.
- `tests/test_web_locales.py` schlägt fehl, bis jeder Text der Oberfläche und
  jeder Befund mit intakten Platzhaltern und intaktem Markup übersetzt ist.

**Wortwahl.** Ein Begriff hat je Sprache genau eine Übersetzung. Verwenden Sie
die Wortwahl, die die Oberfläche bereits nutzt (Seitennamen, Namen der
Dimensionen, Risikobezeichnungen, Beschriftungen von Schaltflächen), in neuen
Texten und in der Dokumentation wieder.

### Dokumentation

Die Dokumentation gibt es in sieben Sprachen — Englisch, Chinesisch (`zh-CN`),
Französisch, Spanisch, Portugiesisch, Italienisch und Deutsch:

| Datei | Zielgruppe |
|---|---|
| `README.md`, `README.<lang>.md` | Nutzer: was zing tut, Installation, Nutzung von CLI und Weboberfläche |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Mitwirkende: Architektur, Einrichtung, Mitwirken, Docker, Releases |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Alle: jede Prüfung, ihre Bewertungsskala und ihre Einschränkungen |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Referenzseiten (englisch) |

Die englischen Dateien sind die Referenz. Wenn Sie eine ändern, ändern Sie die
anderen im selben Pull Request und verwenden Sie in jeder Sprache die Wortwahl der
Oberfläche (schlagen Sie den Begriff in `zing/i18n/locales/` nach). Die
METHODOLOGY-Dateien geben die Bewertungsskalen mit dem Wortlaut wieder, den die
Oberfläche unter **Bewertungsskala** zeigt.

## Tests

```bash
pytest                       # alles
pytest tests/test_billing.py # ein Modul
pytest -k streaming          # nach Stichwort
pytest -n auto               # parallel, ein Worker pro CPU (pytest-xdist)
```

- `tests/conftest.py` stellt `MockServer` bereit, einen OpenAI-kompatiblen
  Endpunkt auf `httpx.MockTransport` mit Stellschrauben für jede Abweichung, die
  zing sucht (geliefertes Modell, Selbstidentifikation, Kontextkürzung,
  vorgetäuschtes Streaming, fehlende oder aufgeblähte Nutzung, Tool-Calls,
  JSON-Modus, …). Jede Stellschraube steht standardmäßig auf ehrlichem Verhalten.
- Die Anthropic- und Responses-Clients haben eigene Tests (`test_anthropic.py`,
  `test_responses.py`); der Webserver wird über den Testclient von FastAPI
  getestet (`test_web*.py`), einschließlich der Schutzmaßnahmen für den lokalen
  Betrieb (`test_web_security.py`).
- Die Browser-Skripte (`lang.js`, `modelpicker.js`, `v2/relaycfg.js`, `perf.js`,
  `secretfield.js`, `v2/report.js`, die Übersetzungen) werden in
  `test_web_*_js.py` und `test_web_locales.py` unter `node` ausgeführt; ohne
  Node.js werden sie übersprungen.
- Kein Test darf das Netzwerk erreichen.
- `test_cli_startup.py` hält den Start der CLI schnell: Der Import von
  `zing.cli` darf weder die HTTP-Clients noch den Runner, den Wissensbasis-Lader,
  die Berichts-Renderer (ReportLab) oder den Webserver laden. Importieren Sie
  diese innerhalb des Befehls, der sie braucht.
- `test_filler_perf.py` legt den Fülltext Byte für Byte fest und schlägt fehl,
  wenn der Kontextfenster-Test die Event-Loop blockiert.
- `tests/a11y/` prüft die neue Oberfläche (v2) gegen BITV 2.0 / EN 301 549 /
  WCAG 2.1 AA in einem echten Browser (Playwright + axe-core), in jeder
  Oberflächensprache und beiden Themes:
  `pip install -e '.[web,a11y]' && playwright install chromium`, dann
  `pytest -m a11y`. Ohne Playwright wird das Verzeichnis übersprungen. Was
  automatisiert ist und was noch eine manuelle BITV-Prüfung braucht, steht in
  [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md) (englisch).
- `ZING_A11Y_PAGES=history,kb` führt nur die a11y-Tests dieser Seiten aus (und
  die seitenübergreifenden Prüfungen); `python -m tests.a11y.affected --base
  origin/main --head HEAD` gibt aus, welche Seiten eine Änderung betrifft. Beide
  nutzen eine Zuordnung, `tests/a11y/pages.py`: Eine neue Seite kommt dort in
  `PAGES` und `RULES` ([tests/a11y/README.md](tests/a11y/README.md)).

## Docker

Das `Dockerfile` baut ein Image der Weboberfläche (Python 3.12 slim mit dem Extra
`web`; PDF-Berichte brauchen keine Systempakete). Es läuft als
unprivilegierter Nutzer mit dem Datenverzeichnis unter `/data`.

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# http://localhost:8000 öffnen
```

**Veröffentlichen Sie immer an `127.0.0.1`.** Ein einfaches `-p 8000:8000`
veröffentlicht die Oberfläche — und jeden darin eingegebenen oder in einer
Überwachung gespeicherten API-Schlüssel — in Ihr Netzwerk. Im Container muss der
Server auf allen Schnittstellen lauschen; das ist nur erlaubt, wenn
`ZING_CONTAINER=1` gesetzt ist (das Image setzt es) *und* eine
Container-Laufzeit erkannt wird.

| Variable | Standard | Zweck |
|---|---|---|
| `ZING_CONTAINER` | nicht gesetzt (`1` im Image) | Erlaubt in einem erkannten Container eine Bindung außerhalb von Loopback |
| `ZING_HOST` | `127.0.0.1` (`0.0.0.0` im Image) | Bindungsadresse; `--host` hat Vorrang |
| `ZING_PORT` | `8000` | Port; `--port` hat Vorrang |
| `ZING_DATA_DIR` | `~/.zing` (`/data` im Image) | Verlauf, Überwachungen (ihre Schlüssel verschlüsselt) und Ihre Wissensbasis-Einträge; hier ein Volume einhängen. `--data-dir` hat Vorrang |
| `ZING_SECRET_KEY` | nicht gesetzt | Hauptschlüssel der gespeicherten API-Schlüssel der Überwachungen (ein Schlüssel oder `file:/run/secrets/…` / `env:VAR`); nicht gesetzt, fragt die Seite Überwachung nach jedem Start danach. Nie in `ZING_DATA_DIR` gespeichert |
| `ZING_KB_DIR` | nicht gesetzt | Zusätzliches YAML-Verzeichnis der Wissensbasis, z. B. `-v ./profiles:/kb:ro -e ZING_KB_DIR=/kb` |
| `ZING_NO_USER_KB` | nicht gesetzt | `1` ignoriert Ihre eigenen Wissensbasis-Einträge (`kb.db`) |
| `ZING_ALLOWED_HOSTS` | nicht gesetzt | Zusätzliche Hostnamen, unter denen die Oberfläche antwortet, kommagetrennt |

[docs/DOCKER.md](docs/DOCKER.md) ist die vollständige Referenz (englisch),
einschließlich der Schutzmaßnahmen der Oberfläche.

## Continuous Integration

| Workflow | Läuft bei | Tut |
|---|---|---|
| `.github/workflows/ci.yml` | Push und Pull Request auf `main` (und die Integrationszweige `a11y/integration`, `perf/integration`); nächtlich und manuell (nur Barrierefreiheit) | `ruff`, `mypy` und `pytest` unter Python 3.10–3.13 mit den Extras `dev` und `web`; baut Wheel und sdist und prüft, dass sich das Wheel installieren lässt und die Wissensbasis lädt; führt die Barrierefreiheits-Suite aus (nur informativ, lässt den Lauf nie fehlschlagen) und lädt ihre Befunde hoch: alle Seiten bei Pushes, nächtlichen und manuellen Läufen (mit dem BITV-Konformitätsbericht), bei Pull Requests nur die Seiten, die die Änderung betrifft (keine bei reinen Doku-Änderungen) — außer bei Pull Requests in `perf/integration`, wo die langsame Browser-Suite übersprungen wird (sie läuft bei Pushes auf diesen Zweig und bei seinem Pull Request in `main`) |
| `.github/workflows/release.yml` | einem Tag `v*` | baut, führt `twine check` aus und veröffentlicht auf PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | täglich, manuell | Beispiel einer geplanten Relay-Prüfung mit der Action |

Die Composite Action selbst ist `action.yml`, dokumentiert in
[docs/CI.md](docs/CI.md).

## Releases

1. `[Unreleased]` in `CHANGELOG.md` auf die neue Version umstellen und `version`
   in `pyproject.toml` erhöhen.
2. Committen, `vX.Y.Z` taggen und das Tag pushen; `release.yml` veröffentlicht auf
   PyPI.
3. Das GitHub-Release mit den Notizen aus dem CHANGELOG anlegen und die
   festgelegte Version der Action in den READMEs und `docs/CI.md` aktualisieren.

Die einmalige Einrichtung bei PyPI und der manuelle Weg stehen in
[docs/PUBLISHING.md](docs/PUBLISHING.md).

## Sicherheit

Melden Sie Sicherheitslücken vertraulich, wie in [SECURITY.md](SECURITY.md)
beschrieben. Relevant ist vor allem: ein Schlüssel oder Geheimnis, das in einen
Bericht gelangt, vom Relay kontrollierter Text, der Markup in einen Bericht oder
die Oberfläche einschleust, Datenverkehr zu etwas anderem als den konfigurierten
Endpunkten, und Wege um die Schutzmaßnahmen der Weboberfläche für den lokalen
Betrieb herum.

## Lizenz

[Apache-2.0](LICENSE)
