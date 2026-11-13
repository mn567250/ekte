# Weboberfläche (`ekte serve`)

> [🇬🇧 English](../../../guide/web-ui.md) · [🇨🇳 中文](../../zh-CN/guide/web-ui.md) · [🇫🇷 Français](../../fr/guide/web-ui.md) · [🇪🇸 Español](../../es/guide/web-ui.md) · [🇵🇹 Português](../../pt/guide/web-ui.md) · [🇮🇹 Italiano](../../it/guide/web-ui.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/web-ui.md)

Lieber klicken? Eine lokale Weboberfläche nutzt dieselbe Engine — ganz ohne
Kommandozeile.

```bash
pip install 'ekte[web]'     # oder: uv tool install 'ekte[web]'
ekte serve                        # öffnet http://localhost:8000
```

Das Formular führt durch die Konfiguration:

1. Wählen Sie **Relay / Anbieter**: einen Anbieter der Wissensbasis oder ein von
   Ihnen gespeichertes Relay. Seine Basis-URL wird ausgefüllt (weitere bekannte
   URLs des Anbieters werden als Vorschläge angeboten). Für jedes andere Relay
   wählen Sie **Andere (URL eingeben)** und geben die **Relay-URL** ein.
2. Ergänzen Sie den **API-Schlüssel**, falls das Relay einen braucht.
3. ekte listet die Modelle des Relays selbst auf (bei der Auswahl eines Relays
   und immer, wenn sich URL oder Schlüssel ändern; **Modelle neu laden** fragt
   erneut). Wählen Sie das **Angefragte Modell**. Ein Relay ohne Modellliste
   fällt auf die Eingabe der ID zurück (**Manuell eingeben**).
4. Wählen Sie optional das **Angegebene Modell** aus den Modellen der
   Wissensbasis: das Modell, das das Relay zu liefern behauptet. Ist das
   angefragte Modell in der Wissensbasis, ist es vorausgewählt; ändern Sie es
   nur, wenn das Relay das Modell unter anderem Namen verkauft. Das
   Anbieterprofil, gegen das ekte prüft, ergibt sich daraus.

Ein Relay, das noch nicht in der Liste steht, lässt sich mit **In der
Wissensbasis speichern** unter einem Namen Ihrer Wahl behalten; beim nächsten Mal
ist es eine Auswahl entfernt. Die vertrauenswürdige Referenz (**Mit
vertrauenswürdiger Referenz vergleichen**) sowie die Embedding- und
Rerank-Prüfungen werden genauso konfiguriert.

Dann
**Prüfung starten** und die Prüfungen **live** verfolgen: jede Prüfung zeigt ihre
Bewertung und Dauer, und eine Prüfung mit Befunden klappt auf und zeigt die
Belege. Das Ergebnis ist ein teilbarer Urteilsbericht: Note, die **Prüfungen je
Dimension** mit ihren Bewertungsskalen, Befunde in verständlicher Sprache und der
Leistungsabschnitt sowie ein **Ausführungsprotokoll** aller Detektoren.

Alles läuft auf Ihrem Rechner: ein im Browser eingegebener Schlüssel erreicht nur
Ihren lokalen ekte-Server und das geprüfte Relay, niemals Dritte. Siehe
[Datenschutz und lokale Daten](privacy.md#datenschutz-und-lokale-daten).

## Seiten

Die Weboberfläche wird an der Wurzel der Adresse ausgeliefert, die `ekte serve` öffnet; die Prüfseite liegt unter `/`. Frühere Adressen leiten bis 1.0.0 auf die passende Seite weiter (siehe [Adressen der Weboberfläche](../../../reference/stability.md#surface-web-addresses)).

| Seite | Adresse | Wofür |
|---|---|---|
| **Prüfung** | `/` | Ein Relay prüfen (optional gegen eine Referenz) und den Bericht lesen; auch Embedding- und Rerank-Prüfungen starten hier, über die Auswahl des Endpunkttyps |
| **Überwachung** | `/watches` | Geplante Wiederholungsprüfungen mit Webhook-Warnungen |
| **Verlauf** | `/history` | Jede Prüfung auf diesem Rechner, gruppiert nach Relay + angegebenem Modell, mit Trends |
| **Analyse** | `/analytics` | Relays und Modelle im Zeitverlauf verglichen: Kennzahlen, Diagramme mit Datentabellen, Ranglisten |
| **Wissen** | `/kb` | Die Wissensbasis in drei Tabs — Modelle, Anbieter, Relays: durchsuchen, ein-/ausschalten, Eigenes hinzufügen |
| **Barrierefreiheit** | `/accessibility` | Der Konformitätsbericht und die Erklärung zur Barrierefreiheit (das Symbol neben der Sprachauswahl); noch ohne manuelle Prüfung durch einen Menschen (bekannte Einschränkung) |

Auf den Seiten außerdem: Filter und konfigurierbare Trends
(Bewertung, Note, Latenz p50, Dekodiertempo p50) im **Verlauf**; **Als Überwachung
einplanen** und **Audit erneut ausführen** bei jedem Lauf im Verlauf; **Bericht herunterladen** in jedem Format;
und eine Designauswahl (Automatisch / Hell / Dunkel).
Jede Seite außer Barrierefreiheit hat direkt unter ihrer Einleitung einen
Hinweis, eingefärbt nach Wichtigkeit (Information, Erfolg, Warnung, kritisch):
z. B. die zuletzt abgeschlossene Prüfung auf **Prüfung**, der Hauptschlüssel auf
**Überwachung**, noch zu verarbeitende Läufe auf **Verlauf** und **Analyse**,
übersprungene Einträge auf **Wissen**.

**Audits im Hintergrund.** Ein auf der Seite **Prüfung**
gestartetes Audit läuft weiter, wenn Sie die Seite wechseln oder den Tab
schließen; **Im Hintergrund fortsetzen** schickt es bewusst dorthin. Der
**Verlauf** zeigt jedes wartende und laufende Audit (und jede laufende
Überwachung) mit Fortschritt; **Live ansehen** öffnet die Live-Ansicht wieder
und holt alles bisher Geschehene nach. Audits desselben Relays laufen
nacheinander, damit sie Latenz- und Zuverlässigkeitswerte nicht gegenseitig
verfälschen (alle Loopback-Adressen zählen als ein Host, also warten auch
Modelle auf Ihrem eigenen Rechner); Audits verschiedener Relays laufen parallel,
höchstens vier gleichzeitig (`EKTE_MAX_PARALLEL_AUDITS`). Überwachungen warten
ebenso auf ihr Relay.

**Rohe Anfragen und Antworten.** Ein im **Verlauf** gespeicherter Lauf behält
jede rohe Anfrage und Antwort, die er ausgetauscht hat (siehe
[Datenschutz](privacy.md)). In seinem Bericht listet **Belege anzeigen** unter
einem Befund die Anfragen der zugehörigen Prüfung auf; jede öffnet die Anfrage,
wie sie gesendet, und die Antwort, wie sie empfangen wurde, samt der Ankunft
ihrer Teile, und **Rohdaten** → **Belegdatei** lädt alle herunter. Die
Einstellung **Rohe Anfragen/Antworten** im Prüfformular (**Behalten** /
**Nicht behalten**) entscheidet das pro Lauf; jede Überwachung hat dieselbe
Einstellung unter **Überwachung**.

Unter einem Befund enthält die Liste nur die Anfragen, auf denen dieser Befund
beruht. Jedes Paar und der ganze Lauf lassen sich auch als HAR oder als
curl-Skript herunterladen, das die Anfragen erneut sendet (`EKTE_API_KEY`
liefert den Schlüssel).

**Mit dieser Version neu bewerten** bei einem gespeicherten Lauf mit Belegen
gibt ihn auf dieselbe Weise wieder und speichert das Ergebnis als neuen Lauf
im **Verlauf**; sein Bericht nennt den wiedergegebenen Lauf.

**Analyse.** `/analytics` macht aus dem lokalen Verlauf
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
ekte gezählt hat — sowie Anteile von Reasoning- und gecachten Eingabe-Tokens)
und **Relay-Overhead** (die vom Relay gemeldete Verarbeitungszeit neben der
Netzwerk-Umlaufzeit dorthin).

**Prognose (Analyse › Trends).** *Vergleich im Zeitverlauf* hat eine Auswahl
**Prognose**, standardmäßig aus: die nächsten 12 oder 24 Stunden, 3 oder 7 Tage
oder 2 oder 4 Wochen, je nach Zeitabschnitt. Jede Reihe geht dann als
gestrichelte Linie mit einem blassen Band weiter, über einer hellen Fläche
„Prognose“. Die Linie ist eine Gerade durch die Mediane der Zeitabschnitte
(nach Läufen gewichtet, Ausreißer-Abschnitte ausgelassen) und beginnt beim
letzten Abschnitt mit 3 oder mehr Läufen, schließt also an den Verlauf an; das
Band ist die mittlere Hälfte der Läufe (p25–p75), umso breiter, je weiter es
vorausreicht. Ein Hinweis unter dem Diagramm nennt je Reihe, ob sie steigt oder
fällt und um wie viel pro Abschnitt, ob das besser oder schlechter ist und wo
sie am Ende der Prognose liegen dürfte. Nach einer Markierung (ekte-Version,
Wissensdatenbank-Profil) und nach einem Sprung in den Daten (etwa ein Wechsel
von Backend oder Modell) beginnt die Anpassung neu, weil frühere Werte nicht
vergleichbar sind. Keine Prognose gibt es für eine Reihe mit weniger als 6
Abschnitten mit 3 oder mehr Läufen seitdem (mehr Läufe — ein Monitor — oder
eine andere Abschnittsgröße helfen) und für zusammengefasste Raten wie die
Erfolgsrate, die kein p25–p75-Band haben. Die Datentabelle führt die
Prognose-Abschnitte als eigene Zeilen, markiert „Prognose (Schätzung)“. Eine
Prognose ist eine Schätzung, keine Messung.

**Tabs und Links zum Teilen (Analyse).** Die Panels liegen in fünf Tabs —
**Überblick** (Kennzahlen, Rangliste), **Trends** (Vergleich im Zeitverlauf,
Stoßzeiten), **Zuverlässigkeit** (Fehler, Relay-Overhead),
**Modellechtheit** und **Abrechnung** — unter dem Seitenkopf und einem
gemeinsamen Filterpanel; geladen wird nur der Tab, den Sie ansehen. Die URL
enthält Tab, Filter und jede Diagrammoption
(`?tab=reliability&range=30d&relay=…&errors.bucket=dow_hour`), und **Link zu dieser
Ansicht kopieren** kopiert sie (oder zeigt sie in einem Feld zum Kopieren, wo
der Browser das nicht erlaubt): Der Link öffnet genau diese Ansicht. Das
Filterpanel ist auf **Verlauf**, **Überwachung** und **Analyse** dasselbe: Geschlossen zeigt es,
wie viele Filter aktiv sind, und nennt sie in einer Zeile (z. B. „Letzte 30
Tage · standard · Streaming · Example Relay“), so sagt eine geteilte Ansicht,
was sie zeigt. **Verlauf** und **Analyse** beginnen mit den letzten 30
Tagen: heute und die 29 Tage davor, ab Mitternacht in deiner Zeitzone
(**Gesamter Zeitraum** zeigt jeden Lauf). Ein geteilter Link behält den
Zeitraum, nicht die Daten: Jeder sieht ihn in seiner eigenen Zeitzone.

**Erfolgs-, Fehler-, 429- und Störungsquote.** Jede Anfrage, die ekte während eines Laufs an das Relay schickt, hat genau ein Ergebnis: Erfolg, Relay-Fehler (Zeitüberschreitung beim Warten auf das Relay, eine 5xx- oder 4xx-Antwort oder eine andere fehlerhafte Antwort), Ratenbegrenzung (HTTP 429) oder ein Fehler, der das Relay nie erreicht hat (das Netz zwischen Ihnen und dem Relay oder ekte selbst). Wiederholte Versuche zählen einmal. Bewertet wird das Relay nur nach den Anfragen, die es erreicht haben: **Erfolgsquote**, **Fehlerquote** und **429-Quote** sind Erfolge, Relay-Fehler bzw. Ratenbegrenzungen geteilt durch diese Anfragen und ergeben zusammen immer 100 %. Der **Störungsanteil** ist der Anteil aller Anfragen, die vor dem Relay scheiterten: Er sagt, wie weit man dem Lauf selbst trauen kann, nicht wie gut das Relay ist; ist er hoch, wiederholen Sie die Prüfung. Über mehrere Läufe werden die Quoten zusammengezählt (alle Anfragen gemeinsam), sodass ein schlechter Lauf unter vielen guten sichtbar bleibt (neun Läufe mit 0 % und einer mit 40 % ergeben etwa 4 %, nicht 0 %); Bewertungen, Latenzen, Geschwindigkeiten und Abrechnungsverhältnisse sind der Median der Läufe. Verlauf, Analysen und Bericht zeigen für dieselben Läufe dieselben Zahlen, und ein einzelner Lauf zeigt genau die Werte seines Berichts. Die Zuverlässigkeitsprüfung im Bericht hat eine eigene Quote („Erfolgsquote der Zuverlässigkeitsprüfung“), die nur in die Bewertung eingeht.

## Sprachen

Ein Sprachmenü in der Kopfzeile jeder Seite schaltet die Oberfläche zwischen
**🇬🇧 Englisch** (Standard), **🇨🇳 Chinesisch** (die ursprüngliche Oberfläche),
**🇫🇷 Französisch**, **🇪🇸 Spanisch**, **🇵🇹 Portugiesisch**, **🇮🇹 Italienisch**,
**🇩🇪 Deutsch** und **🇳🇴 Norwegisch** (Bokmål) um; die Wahl wird pro Browser gespeichert.

Aus der Oberfläche heruntergeladene Berichte (**Bericht herunterladen**: JSON,
Markdown, HTML oder PDF) folgen der gewählten Sprache: JSON-Schlüssel,
Enum-Werte (`risk_level`, `status`, `severity`, …), IDs und Belege bleiben exakt
wie im Bericht der CLI (das JSON ist weiterhin ein gültiger ekte-Bericht),
während die für Menschen lesbaren Werte (Überschrift und Zusammenfassung des
Urteils, Titel und Zusammenfassungen der Befunde, Empfehlungen, Detektornamen,
Hinweise) übersetzt werden und der Dateiname die Sprache trägt
(`ekte-report.de.json`, `ekte-report.de.pdf`). Die Abschnittsüberschriften der
Markdown-/HTML-/PDF-Dateien sind englisch. Die Berichte der CLI mit
`--format json|md|html|pdf` bleiben englisch.

**An den geprüften Endpunkt gesendete Prompts folgen nicht der Sprache der
Oberfläche.** Jeder Text, den ekte an eine LLM-API sendet, ist englisch, damit
dasselbe Relay dasselbe Urteil erhält, egal wer den Bericht liest
(Antwortprüfungen und Token-Schätzungen sind auf genau diese Texte kalibriert).
Die einzigen Ausnahmen sind Fingerabdrücke der Wissensbasis, deren Sprache
*selbst* die Messgröße ist — z. B. die Tests zu chinesischer Sprachgewandtheit,
Tokenizer und Selbstidentifikation chinesischer Modelle. Jeder Bericht vermerkt
die tatsächlich verwendeten Testsprachen (`prompt_languages`, z. B. `["en", "zh"]`).
Jeder Bericht vermerkt außerdem, wie mit dem Endpunkt gesprochen wurde: das Protokoll
(`target.api`: `openai`, `anthropic` oder `responses`), ob `--api auto` es erkannt
hat (`target.api_auto`) und den Anfragemodus der Leistungsprobe (`stream_mode`:
`stream`, `non_stream` oder `both` für die vollständige Suite). Die Verlaufsseite
der Weboberfläche kann nach allen dreien filtern.
`started_at` vermerkt, wann die Prüfung begann (UTC); `start_ms` jedes
Anfrage-Datensatzes zählt ab diesem Zeitpunkt.
