# zing — Methodik

> [🇬🇧 English](METHODOLOGY.md) · [🇨🇳 中文](METHODOLOGY.zh-CN.md) · [🇫🇷 Français](METHODOLOGY.fr.md) · [🇪🇸 Español](METHODOLOGY.es.md) · [🇵🇹 Português](METHODOLOGY.pt.md) · [🇮🇹 Italiano](METHODOLOGY.it.md) · **🇩🇪 Deutsch**

Dieses Dokument erklärt, wie **zing** zu seinem Urteil kommt: welche
Black-Box-Tests jeder Detektor sendet, wie aus ihren Ergebnissen Punkte werden,
wie aus Punkten Dimensionsbewertungen und eine Gesamtbewertung werden und wie
das Risikourteil entschieden wird. Es beschreibt die aktuelle Implementierung;
jede Bewertungstabelle unten ist die veröffentlichte Skala des Detektors
(`SCALE` in `zing/detectors/*.py`) mit demselben Wortlaut, den die
Weboberfläche unter **Bewertungsskala** zeigt.

> zing liefert **Black-Box-Belege für Abweichungen und Risiken, keinen
> kryptografischen Betrugsnachweis.** Siehe [Grenzen & verantwortungsvoller Einsatz](#grenzen--verantwortungsvoller-einsatz).

---

## Grundhaltung

Ein Relay kann aus legitimen Gründen abweichen, Snapshots aktualisieren,
Kapazität bündeln oder einen Upstream puffern, der nicht streamen kann. zing
behandelt deshalb jedes einzelne Signal als *Risikohinweis*, nie als Urteil:
Befunde stützen sich auf Belege, sind vorsichtig formuliert, und ein unklares
Ergebnis bleibt **nicht eindeutig**, statt in Bestanden oder Fehlgeschlagen
gezwungen zu werden. Das Risikourteil erreicht „hoch“ nur bei harten Belegen mit
hohem Schweregrad, und der stärkste Weg zur Bestätigung ist immer der
**Vergleichsmodus** (`zing compare`): dieselben Tests gleichzeitig gegen eine
*vertrauenswürdige Referenz des angegebenen Modells* ausführen.

## Wie zing bewertet

### Detektorbewertung

Jeder Detektor veröffentlicht seine **Bewertungsskala**
(`DetectorResult.scoring`, erstellt mit `zing/detectors/scale.py`): jedes
mögliche Ergebnis jeder seiner Prüfungen mit Status, Schweregrad und Wirkung
auf die Bewertung. Jeder Befund hält das `outcome` fest, das er getroffen hat,
sodass Bericht und Verhalten nicht auseinanderlaufen können. Eine Skala nutzt
eine von zwei Methoden:

- **Mittelwert der Prüfungen** (`Scale`, Methode `mean_of_checks`): jede
  Prüfung vergibt Punkte; die Detektorbewertung ist der Mittelwert der
  gewerteten Prüfungen. Ein Ergebnis mit **Nicht gewertet** (typischerweise
  eine nicht eindeutige Prüfung) hebt und senkt die Bewertung nicht.
- **Abzüge** (`DeductionScale`, Methode `deductions`): die Bewertung beginnt
  bei 100, Befunde ziehen Punkte ab (`Finding.deduction`) und/oder begrenzen sie
  (`Finding.cap`); die niedrigste Obergrenze gilt.

Eine *parametrisierte* Prüfung wendet einen Zeilensatz auf viele Gegenstände an
(zum Beispiel jedes Antwortattribut): jeder Gegenstand wird einzeln bewertet,
die Skala wird einmal je Prüfung veröffentlicht, und Berichte listen die
Gegenstände unter ihrer Prüfung.

### Bewertung und Status einer Dimension

zing bewertet zehn Dimensionen. Die Bewertung einer Dimension ist der
**gleich gewichtete Mittelwert der Bewertungen ihrer Detektoren**: ein Detektor
mit vielen Prüfungen wiegt nicht schwerer als einer mit wenigen, und ein
Detektor ohne numerische Bewertung bleibt außen vor. Ihr Status ist der
schlechteste Status, den ihre Detektoren ermittelt haben — außer dass ein Befund
mit Schweregrad HOCH/KRITISCH **Fehlgeschlagen** erzwingt und ein Befund mit
Schweregrad MITTEL **Bestanden** auf **Warnung** anhebt, unabhängig von der
Bewertung. Jeder Bericht hält das je Dimension fest (`DimensionScore.breakdown`:
die Bewertung jedes Detektors, ob sie gewertet wurde, und eine etwaige
Statusänderung samt auslösender Befunde) und zeigt es unter **Dimension
details** (Markdown/HTML/PDF) und in den aufklappbaren Zeilen von **Prüfungen
je Dimension** in der Weboberfläche. Ein abstürzender Detektor erscheint mit
Status **Fehler** und bricht die Prüfung nie ab.

### Gesamtbewertung, Note und Gewichte

Der **Gesamt-Health-Score** ist der gewichtete Mittelwert über die Dimensionen,
die eine Bewertung ergeben haben (`DIMENSION_WEIGHTS` in `zing/scoring.py`).
Eine Dimension, die nicht lief (nicht in der Suite oder in einem
`custom`-Lauf nicht ausgewählt), fällt heraus, und die übrigen Gewichte werden
neu normiert. Die Note ist A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) oder F.

| Dimension | Kennung | Gewicht | Rolle |
|---|---|---|---|
| Modellidentität | `model_identity` | 21 | Kern |
| Kontextfenster | `context_window` | 19 | Kern |
| Angegebene Fähigkeiten | `capability` | 13 | Kern |
| Protokollkonformität | `protocol` | 8 |  |
| Abrechnung & Verbrauch | `billing` | 8 |  |
| Konnektivität | `connectivity` | 7 |  |
| Echtheit des Streamings | `streaming` | 6 |  |
| Zuverlässigkeit unter Parallellast | `reliability` | 6 |  |
| Transportsicherheit | `security` | 6 |  |
| Leistung | `performance` | 6 |  |

Die drei **Kerndimensionen** sind jene, deren Scheitern einen
Etikettenschwindel am direktesten aufdeckt.

### Risikourteil

Die Risikostufe richtet sich nach dem **Schweregrad der Befunde**, nicht nach
der Bewertung. Befunde der Dimension Konnektivität zählen dabei nicht: ein
Relay, das nicht erreichbar ist oder drosselt, konnte nicht beurteilt werden —
das ist kein Beleg für ein anderes Modell.
Auch die **Transport-Hinweise** zählen nicht (`ADVISORY_CHECKS` in
`zing/scoring.py`: `security.tls`, `reliability.success_rate`, `reliability.latency`): Klartext-HTTP, Fehler oder
Langsamkeit unter Last zeigen, wie das Relay erreicht wird, nicht welches
Modell es ausliefert. Sie senken weiterhin Bewertung und Status ihrer
Dimension, stehen in den wichtigsten Befunden nach den Substitutionsbefunden,
und die Zusammenfassung nennt sie als Hinweise. Manipulation der Antwort
(Integrität) und ein zurückgegebener API-Schlüssel heben das Risiko weiterhin an.

| Risiko | Bezeichnung in der UI | Wann |
|---|---|---|
| `inconclusive` | Unzureichendes Signal | Keine Kerndimension lieferte ein verwertbares Ergebnis (Bestanden, Warnung oder Fehlgeschlagen) — etwa weil das Relay nicht erreichbar ist, das Modell kein Profil hat oder ein `custom`-Lauf keine Kerndimension auswählte |
| `high` | Etikettenschwindel | Ein Befund KRITISCH, ein Befund HOCH/KRITISCH in einer Kerndimension oder zwei oder mehr Befunde HOCH |
| `medium` | Abweichungen gefunden | Genau ein Befund HOCH außerhalb der Kerndimensionen oder ein Befund MITTEL in einer Kerndimension |
| `low` | Weitgehend vertrauenswürdig | Jeder andere Befund MITTEL |
| `clean` | Konsistent (wahrscheinlich echt) | Nichts davon |

### Konfidenz des Urteils

- **Niedrig** — das angegebene Modell steht nicht in der Wissensbasis, passt
  nur unscharf zu einem Profil (`match_confidence` `fuzzy`; die
  Zusammenfassung sagt es), oder weniger als zwei Kerndimensionen lieferten ein verwertbares Ergebnis;
- **Mittel** — mindestens zwei Kerndimensionen lieferten ein verwertbares
  Ergebnis;
- **Hoch** — eine Referenz wurde genutzt *und* alle drei Kerndimensionen
  lieferten ein verwertbares Ergebnis, oder die Konfidenz war mittel und der
  LLM-Judge gab ein verwertbares Urteil ab.

## Suiten, Detektoren und Modi

| Detektor | Kennung | Dimension | Ab Suite |
|---|---|---|---|
| Konnektivität & einfache Vervollständigung | `connectivity` | Konnektivität | `smoke` |
| Konformität der OpenAI-Kompatibilität | `protocol` | Protokollkonformität | `standard` |
| Unterstützung der Anfrageattribute | `protocol_request` | Protokollkonformität | `standard` |
| Verfügbarkeit der Antwortattribute | `protocol_response` | Protokollkonformität | `standard` |
| Determinismus & Cache-Korrektheit | `determinism` | Protokollkonformität | `deep` |
| Echtes Kontextfenster & Kürzung | `context_window` | Kontextfenster | `deep` |
| Modellidentität & Herabstufungs-Fingerprinting | `model_identity` | Modellidentität | `standard` |
| Qualitäts-/Herabstufungsbewertung durch ein LLM | `quality_judge` | Modellidentität | `deep` (nur mit `--judge`) |
| Prüfung der angegebenen Fähigkeiten | `capability` | Angegebene Fähigkeiten | `standard` |
| Prüfung der multimodalen Fähigkeit (Vision) | `vision` | Angegebene Fähigkeiten | `deep` |
| Echtheit des Streamings | `streaming` | Echtheit des Streamings | `standard` |
| Prüfung der Token-Abrechnung | `billing` | Abrechnung & Verbrauch | `standard` |
| Zuverlässigkeit & Latenz unter Parallellast | `reliability` | Zuverlässigkeit unter Parallellast | `standard` |
| Signale zu Transport & Geheimnisbehandlung | `security` | Transportsicherheit | `smoke` |
| Erkennung eingeschleuster System-Prompts | `injected_prompt` | Transportsicherheit | `deep` |
| Antwortintegrität / Manipulation | `integrity` | Transportsicherheit | `deep` |
| Prompt-Präfix-Cache (Timing) | `prompt_cache` | Transportsicherheit | `deep` |
| Leistungsmessung | `performance` | Leistung | `deep` (bei `standard` nur mit Referenz, 5 Anfragen) |

- **smoke** führt Konnektivität und Sicherheit aus; **standard** ergänzt die
  Detektoren für Protokoll, Identität, Fähigkeiten, Streaming, Abrechnung und
  Zuverlässigkeit; **deep** ergänzt die Tests für langen Kontext, Determinismus,
  Vision, injizierte Prompts, Integrität, Prompt-Cache und Leistung (sowie den
  Judge mit `--judge`); **full** führt dieselben Detektoren wie deep aus und
  misst die Leistung mit und ohne Streaming; **custom** führt jeden Detektor der
  ausgewählten Dimensionen in der Tiefe von deep aus.
- **Reiner Code (Standard):** jeder Detektor außer `quality_judge` entscheidet
  per deterministischem Code — Text- und Regex-Prüfungen, Arithmetik,
  Timing-Statistik. Kein zweites Modell nötig.
- **Hybrid aus Code + LLM (`--judge`):** `quality_judge` fragt ein separat
  konfiguriertes, vertrauenswürdiges Richtermodell (niemals das Ziel), ob die
  Antworten des Ziels wie das angegebene Modell klingen. Ohne
  `--judge-base-url` nutzt der Vergleichsmodus die Referenz als Richter.
- **Vergleichsmodus** (`zing compare`) gibt den Tests eine vertrauenswürdige
  Referenz: `model_identity` hält die Selbstidentifikation der Referenz neben
  der des Ziels fest, `protocol_request` sendet abgelehnte Parameter erneut an
  die Referenz, `integrity` stuft einen Austausch, den die Referenz nicht zeigt,
  auf KRITISCH hoch, `quality_judge` zeigt dem Richter beide Seiten, und
  `performance` misst beide Endpunkte abwechselnd. Hohe Konfidenz ist nur mit
  Referenz erreichbar.
- **Wissensbasis:** das Profil des angegebenen Modells
  (`zing/knowledge/data/*.yaml` plus Ihre eigenen Einträge in `kb.db`) liefert
  das angegebene Kontextfenster, die maximale Ausgabe, den Tokenizer, die
  Fähigkeitsflags, die Identitätsschlüsselwörter und die
  Verhaltens-Fingerprints, an denen die Tests gemessen werden. Jeder Bericht
  hält das verwendete Profil fest (`knowledge`).
- **Prompt-Sprache:** jeder Testtext liegt in `zing/prompts/en.json` und ist
  Englisch, unabhängig von der UI-Sprache; nur Fingerprints, deren Sprache
  selbst die Messung *ist*, deklarieren `prompt_lang` und `language_bound`.
  Jeder Bericht listet die verwendeten Sprachen der Sonden
  (`prompt_languages`).
- **Reasoning-Modelle:** Eine kurze Probe, die an ihrem Ausgabelimit endet und
  deren Antwort fehlt oder abgeschnitten wurde, nachdem das Nachdenken
  mindestens die Hälfte des Limits verbraucht hat (`reasoning_tokens` gemeldet), wird einmal mit
  einem Limit von 4.096 Token wiederholt, damit ein Modell, das vor der Antwort
  nachdenkt, nicht als fehlerhaft gilt. Proben, deren Limit oder Timing die
  Messung ist (Leistung, Prompt-Cache, Zuverlässigkeit, injizierter Prompt, maximale
  Ausgabe, das Anfrageattribut `max_tokens`), werden nie wiederholt. Sobald
  bekannt ist, dass ein Endpunkt nachdenkt (sein Profil sagt
  `reasoning: true`, oder nach seiner ersten solchen Wiederholung), gehen kurze
  Proben gleich mit dem Limit von 4.096 Token hinaus statt zweimal.

---

## `connectivity` — Konnektivität

**Deckt auf.** Keinen Trick direkt: sie ist das Tor, von dem alle anderen
Detektoren abhängen. Sie trennt einen toten oder falsch konfigurierten Schlüssel
von einem Relay, das eine Prüfung lohnt.

**Vorgehen.** `GET /v1/models` (hält fest, ob das angegebene Modell gelistet
ist) und eine Chat-Completion mit `temperature=0`, die das Modell bittet,
einen exakten Canary-Marker zurückzugeben; erfasst Latenz und das
zurückgegebene `model`-Feld.

**Bewertungsskala** (`zing/detectors/connectivity.py`):

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `connectivity.models` | Die Modellliste (/v1/models) hat geantwortet. | Bestanden | 100 Pkt. |
|  | Die Modellliste (/v1/models) hat nicht geantwortet; manche Relays deaktivieren sie. | Warnung · Niedrig | 60 Pkt. |
| `connectivity.chat` | Eine Chat-Completion lieferte Inhalt und gab das Canary zurück. | Bestanden | 100 Pkt. |
|  | Eine Chat-Completion lieferte Inhalt, gab das Canary aber nicht zurück. | Bestanden | 85 Pkt. |
|  | Die Chat-Completion schlug fehl oder lieferte keinen Inhalt. | Fehlgeschlagen · Hoch | 0 Pkt. |

Der Status des Detektors ist der schlechteste seiner Prüfungen: ein
deaktiviertes `/v1/models` ergibt eine Warnung, auch wenn der Chat funktioniert.

**Einschränkungen.** Ein fehlendes `/v1/models` ist harmlos; viele Relays
schalten es ab. Ein vorübergehender Netzwerkfehler oder 5xx kann die
Chat-Prüfung scheitern lassen: erneut ausführen. Konnektivität beweist nichts
darüber, *welches* Modell geantwortet hat. Ihre Befunde heben das Risikourteil
nie an.

---

## `protocol` — Protokollkonformität

**Deckt auf.** Relays, deren Middleware den Protokollvertrag bricht (verlorene
Dialogrunden, ignorierte Stoppsequenzen, fehlerhafte Fehlermeldungen, fehlende
oder genullte Antwortfelder, entfernte Anfrageparameter) und, über den
Determinismus, `cache.ignore-temperature`. Deckt `capability.json-tool-fakery`
teilweise ab.

### `protocol` — Konformität der OpenAI-Kompatibilität

**Vorgehen.** Drei Tests: ein Mehrfachdialog, der sich an eine Farbe aus einer
früheren Runde erinnern muss; eine `stop`-Sequenz, die die Ausgabe abschneiden
muss; und eine absichtlich ungültige Anfrage (leeres `messages`), die mit einem
4xx abgelehnt werden muss, idealerweise mit einem Fehlerkörper im OpenAI-Stil.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `protocol.multi_turn` | Die Farbe aus einer früheren Runde wurde wiedergegeben. | Bestanden | 100 Pkt. |
|  | Die Farbe aus einer früheren Runde wurde nicht wiedergegeben. | Warnung · Mittel | 55 Pkt. |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Nicht gewertet |
| `protocol.stop` | Die Ausgabe endete an der Stoppsequenz. | Bestanden | 100 Pkt. |
|  | Die Stopp-Behandlung ließ sich anhand des Textes nicht bestätigen. | Warnung · Niedrig | 70 Pkt. |
|  | Text nach der Stoppsequenz wurde zurückgegeben. | Warnung · Niedrig | 60 Pkt. |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Nicht gewertet |
| `protocol.error_schema` | Mit einem 4xx und einem Fehlerobjekt im OpenAI-Stil abgelehnt. | Bestanden | 100 Pkt. |
|  | Mit einem 4xx abgelehnt, aber der Body entspricht nicht dem OpenAI-Stil. | Warnung · Niedrig | 80 Pkt. |
|  | Keine HTTP-Antwort; die Behandlung von Client-Fehlern ließ sich nicht bestätigen. | Warnung · Niedrig | 55 Pkt. |
|  | Ein anderer HTTP-Status; die Behandlung von Client-Fehlern ließ sich nicht bestätigen. | Warnung · Niedrig | 55 Pkt. |
|  | Die ungültige Anfrage verursachte einen Serverfehler (5xx). | Fehlgeschlagen · Mittel | 35 Pkt. |
|  | Die ungültige Anfrage wurde angenommen (2xx). | Fehlgeschlagen · Mittel | 30 Pkt. |

### `protocol_response` — Verfügbarkeit der Antwortattribute

**Vorgehen.** Ein normaler Aufruf ohne Streaming; jedes Attribut des
Protokolls des Ziels (OpenAI Chat Completions, Anthropic Messages oder OpenAI
Responses; Katalog in `zing/detectors/wire_attrs.py`) wird am rohen
Antwortkörper beurteilt. Zentrale Attribute sind z. B. `model`,
`choices[0].message.role/content`, `finish_reason`, `usage.prompt_tokens`,
`usage.completion_tokens` und `usage.total_tokens` (muss die Summe der beiden
sein); nebensächliche sind `id`, `object`, `created`/`created_at`,
`choices[0].index` und `type`. Eine Null, wo eine Anzahl positiv sein muss
(`completion_tokens: 0` bei einer nicht leeren Antwort), zählt als null, nicht
als gültig.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `protocol_response.core` (Zentrale Antwortattribute) | Vorhanden mit gültigem Wert. | Bestanden | 100 Pkt. |
|  | Vorhanden, aber null oder leer (z. B. completion_tokens: 0). | Fehlgeschlagen · Mittel | 20 Pkt. |
|  | Vorhanden mit falschem Typ oder Wert (z. B. Summe ≠ Summe der Teile). | Warnung · Mittel | 40 Pkt. |
|  | Fehlt in der Antwort. | Fehlgeschlagen · Mittel | 0 Pkt. |
| `protocol_response.minor` (Nebensächliche Antwortattribute) | Vorhanden mit gültigem Wert. | Bestanden | 100 Pkt. |
|  | Vorhanden, aber null oder leer. | Warnung · Niedrig | 50 Pkt. |
|  | Vorhanden mit falschem Typ oder Wert. | Warnung · Niedrig | 70 Pkt. |
|  | Fehlt in der Antwort. | Warnung · Niedrig | 60 Pkt. |
| `protocol_response.call` (Test der Antwortattribute) | Die Testanfrage lieferte keinen auswertbaren Antwortinhalt. | Nicht eindeutig · Niedrig | Nicht gewertet |

### `protocol_request` — Unterstützung der Anfrageattribute

**Vorgehen.** Jeder Anfrageparameter des Protokolls wird gesendet (etwa fünf
Aufrufe). Parameter mit beobachtbarer Wirkung bekommen einen eigenen Aufruf und
müssen sie zeigen: `system`/`instructions` befolgt, das Ausgabelimit endet mit
`finish_reason: length`, `n: 2` liefert zwei Auswahlen, `logprobs` kommen
zurück. Parameter, die nur akzeptiert werden müssen (`temperature`, `top_p`,
`seed`, Penalties, `user`, `top_k`, `metadata`), teilen sich einen Aufruf und
werden nur einzeln wiederholt, wenn er abgelehnt wird. Ein 4xx zählt als
Modellgrenze (nicht gewertet) statt als Ablehnung, wenn die Wissensbasis den
Parameter unter `unsupported_params` führt, wenn ein Sampling-Parameter an ein
Reasoning-Modell geht oder wenn eine Referenz mit demselben Protokoll ihn
ebenfalls ablehnt. Tools und JSON-Modus bleiben bei `capability`, `stop` bei
`protocol`, Stream-Usage bei `streaming`.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `protocol_request.param` (Anfrageparameter) | Akzeptiert, und die Wirkung ist in der Antwort sichtbar. | Bestanden | 100 Pkt. |
|  | Akzeptiert (die Wirkung ist an einer Antwort nicht beobachtbar). | Bestanden | 100 Pkt. |
|  | Akzeptiert, aber die Wirkung fehlt in der Antwort. | Warnung · Niedrig | 50 Pkt. |
|  | Mit 4xx abgelehnt (möglicherweise eine Grenze des Modells selbst). | Warnung · Niedrig | 40 Pkt. |
|  | Mit 4xx abgelehnt, während die Baseline ihn akzeptiert. | Fehlgeschlagen · Mittel | 15 Pkt. |
|  | Abgelehnt, aber das Modell selbst unterstützt ihn nicht; nicht gewertet. | Info | Nicht gewertet |
|  | Serverfehler oder keine Antwort; nicht gewertet. | Nicht eindeutig · Niedrig | Nicht gewertet |

### `determinism` — Determinismus & Cache-Korrektheit

**Vorgehen.** Vier identische kreative Prompts mit `temperature=1.0` (ohne
Seed): ein echtes Modell variiert; byte-identische Ausgabe über alle Proben
deutet auf einen Antwort-Cache hin, der das Sampling ignoriert. Für
Reasoning-Modelle, die die Temperatur legitim ignorieren, wird das Urteil
unterdrückt. Zwei identische Faktenfragen mit `temperature=0` dienen nur zur
Information.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `determinism.temp1_variability` | Wiederholte Samples bei temperature=1.0 unterschieden sich, wie bei echtem Sampling. | Bestanden | 100 Pkt. |
|  | Die Samples waren identisch, aber Reasoning-Modelle ignorieren temperature berechtigterweise. | Info | 100 Pkt. |
|  | Alle Samples bei temperature=1.0 waren byte-identisch, was auf zwischengespeicherte Antworten hindeutet. | Warnung · Mittel | 55 Pkt. |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Nicht gewertet |
| `determinism.temp0_stability` | Identische Antworten bei temperature=0 (erwartet); nur zur Information, nicht gewertet. | Info | Nicht gewertet |
|  | Die Antworten unterschieden sich bei temperature=0; nur zur Information, nicht gewertet. | Info | Nicht gewertet |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Nicht gewertet |

**Einschränkungen.** Gateways können anbieterspezifische Zusatzfelder
mitschicken; markiert werden nur fehlende oder ungültige Pflichtfelder. Die
Übersetzung zwischen Anthropic- und OpenAI-Dialekt formt manche Strukturen
legitim um. Einen vermuteten Mangel bestätigen Sie durch Wiederholung und, wo
möglich, im Vergleichsmodus.

---

## `context_window` — Kontextfenster

**Deckt auf.** `context.window-truncation` (ein Relay bewirbt 128K/200K/1M,
kürzt den Prompt aber stillschweigend) und `context.lost-in-middle-rag` (eine
billige RAG-/Zusammenfassungs-Zwischenschicht reicht nur Teile des Prompts
weiter).

**Vorgehen.** Abruf einer Nadel im Heuhaufen mit `temperature=0`: ein
eindeutiger Marker steckt in nicht repetitivem Fülltext, der mit der
heuristischen Token-Schätzung von zing bemessen ist, und das Modell muss ihn
zurückgeben.

1. Eine aufsteigende, sich verdoppelnde Leiter ab 2K Token bis zum angegebenen
   Fenster, begrenzt durch `--max-context-tokens` (Standard 200K), mit einer
   Stufe bei etwa 90 % des Maximums (höchstens sieben Größen). Jede Größe wird
   zuerst mit der Nadel am **Anfang** getestet (Tiefe 0,0): eine Kürzung, die
   die Frage am Ende des Prompts behält, kann nur dessen Anfang verwerfen (ein
   lokaler Server, der den Prompt auf seine Kontextlänge kürzt, behält das
   Ende), daher besteht die Größe bei einem Treffer dort mit einem Aufruf. Ein
   Fehlschlag wird am Ende geprüft (Tiefe 0,95); wird das Ende erinnert, wird
   der Anfang noch einmal mit einer frischen Nadel getestet, und ein zweiter
   Fehlschlag lässt die Größe als **Kürzung von vorn** scheitern (in den Belegen
   des Urteils vermerkt). Höchstens drei Aufrufe pro Größe; die Leiter endet
   beim ersten bestätigten Fehlschlag.
2. Ein Schritt binärer Suche zwischen der letzten abgerufenen und der ersten
   gescheiterten Größe.
3. Lost in the Middle: bei min(32K, gemessenes Fenster) liegt die Nadel in
   Tiefe 0,1, 0,5 und 0,9; Anfang und Ende abgerufen, die Mitte nicht, ist ein
   Befund.
4. Ein 4xx, dessen Meldung die Kontextlänge nennt, ist eine Ablehnung wegen der
   Größe; eine Ablehnung von `max_tokens` (Reasoning-Modelle) wird mit
   `max_completion_tokens` wiederholt und nie als Obergrenze gelesen.
5. Eine Probe mit Zeitüberschreitung beendet die Leiter, ohne als Fehlschlag zu
   zählen: das Fenster oberhalb der letzten erinnerten Größe gilt als nicht
   geprüft (nicht eindeutig), nie als Kürzung.

Das gemessene Fenster wird mit dem angegebenen verglichen. Ohne angegebenes
Fenster wird die Messung berichtet, aber nicht bewertet.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `context_window.window` (Effektives Kontextfenster) | Recall hielt bis mindestens 90 % des angegebenen Fensters; zieht den Anteil des Fensters ab, der nicht erinnert wurde. | Bestanden | bis zu −10 Pkt. |
|  | Recall hielt bis 50–90 % des angegebenen Fensters; zieht den Anteil des Fensters ab, der nicht erinnert wurde. | Warnung · Mittel | bis zu −50 Pkt. |
|  | Recall versagte unter der Hälfte des angegebenen Fensters; zieht den Anteil des Fensters ab, der nicht erinnert wurde. | Fehlgeschlagen · Hoch | bis zu −100 Pkt. |
|  | Nicht einmal die kleinste Probengröße erinnerte die Nadel. | Fehlgeschlagen · Hoch | −100 Pkt. |
| `context_window.lost_in_middle` | Anfang und Ende wurden erinnert, die Mitte aber nicht. | Warnung · Mittel | −15 Pkt. |
| `context_window.rejected_below_claim` | Ein Prompt weit unter dem angegebenen Fenster wurde als zu lang abgelehnt. | Fehlgeschlagen · Hoch | Kein Abzug |
| `context_window.measured` | Kein angegebenes Fenster zum Vergleich: nur gemessen, nicht gewertet. | Info | Kein Abzug |
| `context_window.no_ladder` | Keine Probengröße passte zwischen Unter- und Obergrenze. | Nicht eindeutig · Niedrig | Kein Abzug |
| `context_window.timed_out` | Eine Probe lief vor Erreichen des angegebenen Fensters in eine Zeitüberschreitung: ein langsamer Endpunkt, kein Hinweis auf Kürzung. | Nicht eindeutig · Niedrig | Kein Abzug |

**Einschränkungen.** Auch echte Langkontext-Modelle verlieren Nadeln in der
Mitte; deshalb gilt nur ein Fehlschlag am **Rand** als Kürzung. Der Abruf nahe
der Grenze ist probabilistisch; vor einem Schluss erneut ausführen. Der Test ist
durch `--max-context-tokens` begrenzt, ein größeres Fenster wird also nicht
vollständig ausgereizt. Vergleichen Sie mit einer vertrauenswürdigen Referenz,
um Modellverhalten von Zwischenschicht-Verhalten zu trennen.

---

## `model_identity` — Modellidentität

**Deckt auf.** `downgrade.silent-substitution` (ein Premium-Name auf einem
billigeren oder offenen Backend) sowie Signale von
`downgrade.reasoning-collapse`, `downgrade.quantized-distilled` und
`downgrade.partial-probabilistic-routing`, sofern sie das Verhalten ändern.

### `model_identity` — Modellidentität & Herabstufungs-Fingerprinting

**Vorgehen.** Drei unabhängige Signale:

1. **Selbstidentifikation** mit `temperature=0`, als ganze Wörter abgeglichen
   mit den Identitätsschlüsselwörtern des Profils (die echte Marke) und einer
   Liste konkurrierender Marken (`identity_forbidden` des Profils plus eine
   eingebaute Liste). Eine Konkurrenzmarke zählt nur, wenn die echte Marke
   fehlt; „Ich bin Claude, nicht GPT“ ist ein harmloser Kontrast.
   Die echte Marke sind die `identity_keywords` des Profils plus seine eigenen
   Namen: der Anbieter-Schlüssel, der führende Name im Anzeigenamen des
   Anbieters, das erste Wort von Modell-ID und Familie sowie die übrigen Namen
   dieses Herstellers in der eingebauten Liste (`z.ai` deckt auch `zhipu` ab).
   Ein Modell, das seinen eigenen Hersteller nennt, ist daher nie eine
   Konkurrenzmarke, auch wenn `identity_keywords` leer ist. Abgeleitete Namen
   heben `identity_forbidden` nie auf, allgemeine Wörter („ai“, „platform“, …)
   zählen nie, und die eigene Marke einer Plattform zählt nicht für das Modell
   eines anderen Herstellers, das sie anbietet.
2. **Verhaltens-Fingerprints** aus der Wissensbasis (Wissensstichtag,
   Tokenizer-Eigenheiten, Formatierung, sprachgebundene Tests, …): bis zu sechs
   Tests in reinem Code, geprüft mit `expect_contains`, `expect_contains_any`,
   `expect_not_contains` oder `expect_regex`; Ausgabe auf 512 Token begrenzt.
   Ein Test, der mehr Ausgabe braucht (etwa eine Prüfung der maximalen
   Ausgabe), wird übersprungen und als Info aufgeführt; ein anderer Test
   rückt nach.
   Ein abweichender Fingerprint zieht seinen Gewichtsanteil an 100 Punkten ab
   (höchstens 25); einer allein bleibt NIEDRIG, zwei oder mehr ergeben einen
   zusammenfassenden Befund MITTEL.
3. **Zurückgegebenes `model`-Feld** eines einfachen Aufrufs: Snapshot-Suffixe
   und Aliasse werden toleriert; ein Wort einer kleineren Stufe (`mini`,
   `flash`, `lite`, `8b`, …) oder eine andere Modellfamilie wird markiert.

Ohne Profil in der Wissensbasis ist der Detektor nicht eindeutig.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `model_identity.self_id` | Die Selbstbeschreibung nannte die echte Marke. | Bestanden | Kein Abzug |
|  | Die Selbstbeschreibung nannte eine Konkurrenzmarke und nicht die echte. | Fehlgeschlagen · Hoch | Obergrenze 20 |
|  | Die Selbstbeschreibung nannte die echte Marke und eine Konkurrenzmarke (meist ein harmloser Vergleich). | Warnung · Niedrig | Kein Abzug |
|  | Die Selbstbeschreibung nannte weder die echte Marke noch eine Konkurrenzmarke. | Warnung · Niedrig | Kein Abzug |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig | Kein Abzug |
| `model_identity.fp` (Verhaltens-Fingerprints) | Die Antwort entsprach dem nativen Verhalten des angegebenen Modells. | Bestanden | Kein Abzug |
|  | Die Antwort wich vom nativen Verhalten ab: zieht den Gewichtsanteil der Probe an 100 Punkten ab. | Warnung · Niedrig | bis zu −25 Pkt. |
|  | Die Antwort nannte eine Konkurrenzmarke und nicht die echte: zieht den Gewichtsanteil der Probe ab. | Fehlgeschlagen · Hoch | bis zu −25 Pkt. · Obergrenze 20 |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig | Kein Abzug |
|  | Die Probe braucht mehr Ausgabe als die Identitäts-Obergrenze von 512 Token; nicht ausgeführt. | Info | Kein Abzug |
| `model_identity.fp_aggregate` | Zwei oder mehr Verhaltens-Fingerprints wichen ab. | Warnung · Mittel | Kein Abzug |
| `model_identity.model_field` | Das zurückgegebene model-Feld entsprach dem angefragten Modell. | Bestanden | Kein Abzug |
|  | Das zurückgegebene model-Feld nennt ein anderes oder kleineres Modell. | Warnung · Mittel | Kein Abzug |
|  | Die Antwort enthielt kein verwertbares model-Feld. | Nicht eindeutig | Kein Abzug |

### `quality_judge` — Qualitäts-/Herabstufungsbewertung durch ein LLM

**Vorgehen.** Nur mit `--judge` (ab deep). Eine kurze Reihe von Prompts, die
Leistungsstufen unterscheiden (mehrstufiges Denken, eine präzise
Programmieraufgabe, feines Befolgen von Anweisungen), geht an das Ziel und im
Vergleichsmodus an die Referenz; ein separater, vertrauenswürdiger Richter sieht
nur die Antworten und gibt ein Urteil samt Konfidenz ab. Ein Richterurteil ist
nur HOCH, wenn eine Referenz den Unterschied bestätigt hat und der Richter keine
niedrige oder mittlere Konfidenz angab.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `quality_judge.verdict` (Urteil des LLM-Judge) | Der Judge fand die Antworten passend zum angegebenen Modell. | Bestanden | 95 Pkt. |
|  | Der Judge fand die Antworten dem angegebenen Modell unähnlich (niedrige/mittlere Sicherheit). | Warnung · Mittel | 50 Pkt. |
|  | Der Judge ist sicher, dass die Antworten dem angegebenen Modell unähnlich sind (keine Baseline). | Warnung · Mittel | 25 Pkt. |
|  | Der Judge ist sicher, und eine vertrauenswürdige Baseline bestätigte den Unterschied. | Fehlgeschlagen · Hoch | 25 Pkt. |
|  | Der Judge nannte keine Sicherheit, und eine vertrauenswürdige Baseline bestätigte den Unterschied. | Fehlgeschlagen · Hoch | 50 Pkt. |
|  | Der Judge kam zu keinem Urteil. | Nicht eindeutig · Niedrig | Nicht gewertet |
|  | Keine Antworten des Ziels zum Beurteilen. | Nicht eindeutig · Niedrig | Nicht gewertet |

**Einschränkungen.** Offizielle APIs aktualisieren Snapshots stillschweigend;
eine Abweichung kann also harmloser Drift sein — zing meldet „abweichend“, nie
„Austausch bewiesen“. Modelle halluzinieren ihren eigenen Namen, die
Selbstidentifikation allein entscheidet daher nie. Ein Relay könnte eine feste
Testreihe auswendig lernen. Ein Urteil mit hoher Konfidenz erfordert den
Vergleichsmodus gegen genau den angegebenen Snapshot.

**Nicht implementiert.** Fingerprinting über Embedding-Abstände (LLMmap-Stil),
verteilungsbasierte Zwei-Stichproben-Tests und Stichproben in großer Zahl gegen
probabilistisches Routing sind Forschungsrichtungen, keine aktuellen Prüfungen.

---

## `capability` — Angegebene Fähigkeiten

**Deckt auf.** `capability.json-tool-fakery`: Tool-Calling, JSON-Modus, strikte
Schemas, Ausgabelänge oder Vision werden beworben, aber nicht geliefert — oder
*über*erfüllt, ein Hinweis auf ein Ersatzmodell.

### `capability` — Prüfung der angegebenen Fähigkeiten

**Vorgehen.** Vier Tests mit `temperature=0`, jeweils an den Fähigkeitsflags
des Profils gemessen:

- **Tools:** ein Tool wird mit `tool_choice: "auto"` und einer ausdrücklichen
  Bitte, es zu nutzen, angeboten; ein Tool-Call muss zurückkommen. Argumente als
  Objekt statt als JSON-String, wie OpenAI sie liefert, werden als Hinweis auf
  eine Nicht-OpenAI-Engine markiert.
- **JSON-Modus:** `response_format: json_object` muss ein parsebares Objekt mit
  dem angeforderten Wert liefern.
- **Striktes Schema:** ein striktes `json_schema`; die Einhaltung wird geprüft,
  wenn das Modell es angibt, und nur vermerkt (informativ), wenn nicht. Ohne
  Profil entfällt diese Prüfung.
- **Maximale Ausgabe:** eine lange Generierung, begrenzt auf min(angegebene
  maximale Ausgabe, 2048) Token; das Erreichen der Grenze oder eine plausible
  Länge besteht, ein Abbruch unter einem Viertel davon wird markiert.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `capability.tools` | Auf eine ausdrückliche Tool-Anfrage kam ein Tool-Aufruf zurück. | Bestanden | 100 Pkt. |
|  | Tool-Aufrufe werden angegeben, aber es kam kein Tool-Aufruf zurück. | Fehlgeschlagen · Mittel | 0 Pkt. |
|  | Es kam kein Tool-Aufruf zurück, und Tool-Aufrufe werden nicht angegeben. | Info | Nicht gewertet |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Nicht gewertet |
| `capability.tools.encoding` | Die Tool-Argumente kamen als Objekt, nicht als der JSON-String, den OpenAI liefert. | Warnung · Niedrig | Nicht gewertet |
| `capability.json_mode` | Der JSON-Modus lieferte ein parsebares Objekt mit dem angefragten Wert. | Bestanden | 100 Pkt. |
|  | Ein JSON-Objekt kam mit falschem Wert zurück; der JSON-Modus wird nicht angegeben. | Info | 70 Pkt. |
|  | Es kam kein parsebares JSON-Objekt zurück; der JSON-Modus wird nicht angegeben. | Warnung | 50 Pkt. |
|  | Der JSON-Modus wird angegeben, aber es kam kein gültiges Objekt mit dem Wert zurück. | Fehlgeschlagen · Mittel | 0 Pkt. |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Nicht gewertet |
| `capability.json_schema` | Das strikte Schema wird angegeben und die Antwort entsprach ihm. | Bestanden | 100 Pkt. |
|  | Das strikte Schema wurde nicht durchgesetzt, passend zur Angabe. | Info | 100 Pkt. |
|  | Die Antwort entsprach dem Schema, obwohl dem angegebenen Modell strikte Schemas fehlen. | Info | 90 Pkt. |
|  | Das strikte Schema wird angegeben, aber die Antwort entsprach ihm nicht. | Warnung · Niedrig | 40 Pkt. |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Nicht gewertet |
| `capability.max_output` | Die Ausgabe lief bis zur angefragten Token-Obergrenze. | Bestanden | 100 Pkt. |
|  | Die Ausgabe endete vor der Obergrenze bei plausibler Länge. | Bestanden | 90 Pkt. |
|  | Die Ausgabe endete unter einem Viertel der angefragten Länge. | Warnung · Niedrig | 70 Pkt. |
|  | Die Ausgabe endete unter einem Viertel der Anfrage trotz großem angegebenem Maximum. | Warnung · Niedrig | 60 Pkt. |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Nicht gewertet |

### `vision` — Prüfung der multimodalen Fähigkeit (Vision)

**Vorgehen.** Ab deep und nur, wenn das Profil Vision angibt: ein kleines,
einfarbig oranges PNG, zur Laufzeit erzeugt, wird eingebettet mit einer
Ein-Wort-Frage nach der Farbe gesendet. Ein reines Textmodell als Ersatz kann
die Farbe nicht zuverlässig nennen.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `vision.color` | Das Modell nannte die Farbe des Testbilds. | Bestanden | 100 Pkt. |
|  | Vision wird angegeben, aber das Modell nannte die Farbe des Bildes nicht. | Warnung · Mittel | 0 Pkt. |
|  | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig | Nicht gewertet |
| `vision.not_claimed` | Vision wird nicht angegeben, daher wurde kein Bild gesendet. | Info | Nicht gewertet |

**Einschränkungen.** Auch echte Modelle lassen gelegentlich ein Tool aus oder
liefern ungültiges JSON; ein Test je Fähigkeit ist ein Signal, keine Quote. Die
Dialektübersetzung formt Tool-Call-JSON legitim um. Der Test der maximalen
Ausgabe reizt die angegebene Obergrenze nicht aus. Ein einzelnes Bild ist ein
Hinweis, kein Beweis.

---

## `streaming` — Echtheit des Streamings

**Deckt auf.** `stream.fake-streaming`: das Relay puffert die ganze Antwort des
Upstreams und spielt sie in einem oder wenigen Chunks ab; der Latenzvorteil geht
verloren.

**Vorgehen.** Eine gestreamte Anfrage (`max_tokens` 256,
`stream_options.include_usage`), deren Chunk-Ankunftszeiten erfasst werden. Drei
Puffersignale: **wenige Chunks** (zwei oder weniger) und **spätes erstes Token**
(TTFT über 90 % der Gesamtdauer), beide erst beurteilt, sobald mindestens 220
Zeichen zurückkamen, sowie **gleichförmige Abstände** (vier oder mehr Chunks mit
fast gleichen Abständen, CV < 0,1, und unter 2 ms: gebündelt ausgeliefert). Ein
Stream ohne Usage-Chunk wird gesondert markiert.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `streaming.healthy` | Viele Chunks, ein früher erster Token und verteilte Abstände: echtes Streaming. | Bestanden | Kein Abzug |
| `streaming.few_chunks` | Pufferungssignal: das erste zieht 40 Punkte ab, ein zweites 20, jedes weitere nichts. | Warnung · Mittel | bis zu −40 Pkt. |
| `streaming.late_ttft` | Pufferungssignal: das erste zieht 40 Punkte ab, ein zweites 20, jedes weitere nichts. | Warnung · Mittel | bis zu −40 Pkt. |
| `streaming.uniform_gaps` | Pufferungssignal: das erste zieht 40 Punkte ab, ein zweites 20, jedes weitere nichts. | Warnung · Mittel | bis zu −40 Pkt. |
| `streaming.no_usage` | Kein Usage-Chunk im Stream: zieht 15 Punkte ab, wenn nichts gepuffert ist. | Warnung · Niedrig | bis zu −15 Pkt. |
| `streaming.failed` | Die Streaming-Anfrage schlug fehl. | Fehlgeschlagen · Hoch | Obergrenze 0 |

Also: echt 100 · Usage fehlt 85 · ein Puffersignal 60 · zwei oder mehr 40 ·
fehlgeschlagen 0.

**Einschränkungen.** Kurze Ausgaben, ein schnelles kleines Modell oder
Netzwerk-Jitter können einem Burst ähneln. Ein Upstream, der nicht streamen
kann, zwingt das Relay zu legitimem Puffern; lesen Sie das als „das Relay
streamt nicht“, nicht als böse Absicht. Erneut ausführen und mit einer Referenz
vergleichen, die nachweislich streamt.

---

## `billing` — Abrechnung & Verbrauch

**Deckt auf.** `billing.usage-inflation` (zu hoch gemeldete Prompt- oder
Completion-Token), `billing.missing-usage` (fehlende, unvollständige oder
widersprüchliche `usage`) und, als bestätigendes Signal,
`prompt.injected-system-prompt`.

**Vorgehen.** Ein deterministischer Aufruf (ein bekannter Absatz zum
Zusammenfassen, `temperature=0`). Prompt und sichtbare Antwort werden
unabhängig mit einer sprachbewussten Heuristik (etwa ±25 %) gezählt, für jede
Modellfamilie: zing verwendet keine Tokenizer-Bibliothek und lädt keine herunter.
Gemeldete Prompt-Token über dem 2,5-Fachen der Schätzung und mehr als 50 Token
darüber gelten als aufgebläht. Completion-Token eines Reasoning-Modells
enthalten legitim versteckte Reasoning-Token und werden nicht markiert; sonst
sind Completion-Token über dem 3-Fachen der Schätzung und mehr als 80 Token
darüber nur eine weiche Warnung, nie ein Fehlschlag, weil die Schätzung einer
kurzen Antwort ungenau ist. `total` muss `prompt + completion` entsprechen
(±2), und ein Total ohne Aufteilung wird markiert. Eine Unterzählung (unter der
Hälfte der Schätzung) dient nur zur Information (schadet dem Käufer nicht).

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `billing.request-failed` | Keine verwertbare Antwort zur Beurteilung. | Nicht eindeutig · Niedrig | Kein Abzug |
| `billing.missing-usage` | Die Antwort enthielt überhaupt keine Token-Nutzung. | Warnung · Mittel | Obergrenze 75 |
| `billing.usage-inflation` | Die gemeldeten Prompt-Tokens übersteigen die unabhängige Schätzung deutlich. | Fehlgeschlagen · Hoch | Obergrenze 55 |
| `billing.usage-inflation-completion` | Die gemeldeten Completion-Tokens liegen weit über einer heuristischen Schätzung. | Warnung · Mittel | Obergrenze 70 |
| `billing.reasoning-tokens` | Die Completion-Tokens übersteigen den sichtbaren Text, wie bei einem Reasoning-Modell zu erwarten. | Info | Kein Abzug |
| `billing.usage-undercount-prompt` | Die gemeldeten Prompt-Tokens liegen weit unter der Schätzung (nicht zum Nachteil des Käufers). | Info | Kein Abzug |
| `billing.usage-undercount-completion` | Die gemeldeten Completion-Tokens liegen weit unter der Schätzung (nicht zum Nachteil des Käufers). | Info | Kein Abzug |
| `billing.total-mismatch` | Die gemeldete Summe entspricht nicht Prompt- plus Completion-Tokens. | Warnung · Niedrig | Obergrenze 90 |
| `billing.partial-usage` | Die Nutzung nennt eine Summe ohne Aufteilung in Prompt und Completion. | Warnung · Mittel | Obergrenze 80 |
| `billing.usage-consistent` | Die gemeldete Nutzung liegt innerhalb der Toleranz der unabhängigen Schätzung. | Bestanden | Kein Abzug |

Eine fehlgeschlagene Testanfrage lässt den Detektor unbewertet.

**Einschränkungen.** Chat-Vorlagen und Sondertoken fügen einen kleinen festen
Versatz hinzu; exakte Übereinstimmung ist nicht zu erwarten. Weicht das
gelieferte Modell vom angegebenen ab, ist der „richtige“ Tokenizer unbekannt.
Versteckte Reasoning-Token lassen sich von außen nicht zählen. Ein Test misst
eine Größe; ein mit der Größe wachsender Multiplikator braucht wiederholte Läufe
oder den Vergleichsmodus.

---

## `reliability` — Zuverlässigkeit unter Parallellast

**Deckt auf.** Teile von `throttle.rate-limit-quality`: ein Relay, das unter
mäßiger Parallelität scheitert oder kriecht.

**Vorgehen.** Ein Burst identischer kleiner Anfragen (`--reliability-requests`,
Standard 8) mit begrenzter Parallelität (`--concurrency`, Standard 3). Die
Erfolgsquote bezieht sich auf die tatsächlich versuchten Anfragen: HTTP 429 ist
ehrliche Drosselung und wird gesondert gezählt. Die Bewertung zieht den
gescheiterten Anteil ab; eine p95-Latenz über 30 s behält 85 % des Rests.
Eine fehlgeschlagene Anfrage (also ein vorübergehender 5xx von standardmäßig 8)
oder höchstens 10 % eines größeren Bursts ist eine Warnung, solange mindestens
80 % erfolgreich waren; mehr ist Fehlgeschlagen. Der Status des Detektors ist
der schlechteste seiner Befunde. Diese Befunde sind Transport-Hinweise: Sie
heben das Risikourteil nie an.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `reliability.success_rate` | Jede versuchte Anfrage im Burst war erfolgreich. | Bestanden | Kein Abzug |
|  | Eine Anfrage oder höchstens 10 % der versuchten schlugen fehl (mindestens 80 % erfolgreich); zieht den fehlgeschlagenen Anteil ab. | Warnung · Niedrig | bis zu −20 Pkt. |
|  | Mehr Anfragen schlugen fehl; zieht den fehlgeschlagenen Anteil ab. | Fehlgeschlagen · Mittel | bis zu −100 Pkt. |
|  | Jede Anfrage wurde gedrosselt (HTTP 429): nicht gewertet. | Nicht eindeutig · Niedrig | Kein Abzug |
| `reliability.latency` | p95-Latenz über 30 s unter Last; zieht 15 % der verbleibenden Bewertung ab. | Warnung · Niedrig | bis zu −15 Pkt. |
| `reliability.rate_limited` | Ein Teil des Bursts wurde gedrosselt: ehrliches Throttling, nicht gewertet. | Info | Kein Abzug |
| `reliability.skipped` | Die Zuverlässigkeits-Probe war deaktiviert. | Info | Kein Abzug |

Die eigenen Geschwindigkeitsmessungen gehören zur Dimension `performance`.

**Einschränkungen.** Auch echte Anbieter werden unter realer Last langsamer und
liefern 429. Eine Momentaufnahme verpasst tageszeitabhängiges Verhalten;
`zing watch` prüft nach Zeitplan erneut.

**Nicht implementiert.** Qualitätsmessung über längere Zeit und unter
wechselnder Last sowie die Signale für einen geteilten Upstream-Schlüssel
(`infra.shared-upstream-key`: sinkendes Kontingent im Leerlauf, durchgesickerte
Upstream-Request-IDs) stehen auf der Roadmap.

---

## `security` — Transportsicherheit

**Deckt auf.** `prompt.injected-system-prompt`, `integrity.response-tampering`,
Hinweise auf `privacy.prompt-logging-leakage` (Präfix-Caching) sowie grundlegende
Transport- und Geheimnishygiene.

### `security` — Signale zu Transport & Geheimnisbehandlung

**Vorgehen.** Prüft, dass der Endpunkt HTTPS nutzt, dass der API-Schlüssel nie
wörtlich in einer Antwort erscheint und welche Antwort-Header einen Upstream
oder Proxy verraten (`server`, `via`, `x-powered-by`, `x-upstream-*`,
`x-litellm-*`, …; informativ). Er nennt auch die Grenze: Prompt-Logging und
geteilte Upstream-Schlüssel sind von außen nicht beweisbar. Klartext-HTTP zu
diesem Rechner oder einem privaten Netz (`localhost`, `127.x`, `192.168.x`,
`*.local`, … — ein selbst gehostetes Modell) ist nur eine Warnung ohne
Obergrenze, da der Schlüssel nicht über das Internet geht; Klartext-HTTP zu
jedem anderen Host bleibt Fehlgeschlagen · Hoch. In beiden Fällen ist
`security.tls` ein Transport-Hinweis und hebt das Risikourteil nie an.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `security.tls` | Der Endpunkt nutzt HTTPS. | Bestanden | Kein Abzug |
|  | Der Endpunkt ist nicht HTTPS; der API-Schlüssel wird im Klartext übertragen. | Fehlgeschlagen · Hoch | Obergrenze 40 |
|  | Klartext-HTTP zu einem lokalen Host oder einem im privaten Netz; der API-Schlüssel geht nicht über das Internet. | Warnung · Niedrig | Kein Abzug |
| `security.key_echo` | Der API-Schlüssel erscheint nicht in der Antwort. | Bestanden | Kein Abzug |
|  | Der API-Schlüssel erscheint wörtlich in der Antwort. | Fehlgeschlagen · Hoch | Obergrenze 30 |
| `security.headers` | Kein Antwort-Header verrät das Upstream (nur zur Information). | Bestanden | Kein Abzug |
|  | Antwort-Header verraten das Upstream oder den Proxy (nur zur Information). | Info · Niedrig | Kein Abzug |
|  | Keine Antwort-Header zum Prüfen. | Nicht eindeutig | Kein Abzug |
| `security.note` | Prompt-Logging und geteilte Upstream-Schlüssel sind von außen nicht nachweisbar. | Info | Kein Abzug |

### `injected_prompt` — Erkennung eingeschleuster System-Prompts

**Vorgehen.** Zwei unabhängige Anzeichen. (1) Ein **fester Mehraufwand an
Eingabe-Token**: zwei Nutzernachrichten unterschiedlicher Größe ohne
Systemnachricht; gemeldete `prompt_tokens` minus unabhängige Schätzung müssen
klein bleiben. Ein Mehraufwand von mindestens 30 Token, der über beide Größen
konstant bleibt (auf 16 genau), deutet auf einen versteckt vorangestellten Prompt
statt auf proportionales Aufblähen. (2) Ein **Leck-Test**, der das Modell bittet,
alle vorangehenden Anweisungen zu wiederholen. Nur beides zusammen erreicht
MITTEL.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `injected_prompt.verdict` (Injizierter System-Prompt) | Der Input-Token-Overhead ist klein und keine versteckten Anweisungen wurden preisgegeben. | Bestanden | 100 Pkt. |
|  | Auf Nachfrage kam anweisungsartiger Text zurück (allein schwach). | Info · Niedrig | 85 Pkt. |
|  | Ein großer fester Input-Token-Overhead, gleich über alle Nachrichtengrößen. | Warnung · Niedrig | 75 Pkt. |
|  | Ein fester Input-Token-Overhead und ein preisgegebener Vorspann zusammen. | Warnung · Mittel | 55 Pkt. |
|  | Keine verwertbaren Prompt-Token-Zahlen, um den Overhead zu messen. | Nicht eindeutig | Nicht gewertet |

### `integrity` — Antwortintegrität / Manipulation

**Vorgehen.** Canaries mit bekannter Antwort, deren Werte heikel sind — eine
Installations-URL und ein festgelegtes `pip install`-Paket — müssen wörtlich
zurückkommen. Ein exaktes Echo besteht, kein Echo (Umschreibung, Verweigerung)
ist nicht eindeutig, und nur ein **Austausch des Werts** bei erhaltener Struktur
gilt als Manipulation. Im Vergleichsmodus ist ein Austausch, den die
vertrauenswürdige Referenz nicht zeigt, KRITISCH.
Eine am Ausgabelimit abgeschnittene Antwort ist nicht eindeutig, kein Austausch.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `integrity.verdict` (Antwortintegrität) | Die Canaries mit bekannter Antwort kamen unverändert zurück. | Bestanden | 100 Pkt. |
|  | Ein Canary-Wert wurde ersetzt (noch nicht durch eine Baseline bestätigt). | Fehlgeschlagen · Mittel | 45 Pkt. |
|  | Ein Canary-Wert wurde ersetzt, während die vertrauenswürdige Baseline ihn unverändert ließ. | Fehlgeschlagen · Kritisch | 10 Pkt. |
|  | Kein Canary wurde wörtlich zurückgegeben, daher ließ sich Manipulation nicht beurteilen. | Nicht eindeutig | Nicht gewertet |

### `prompt_cache` — Prompt-Präfix-Cache (Timing)

**Vorgehen.** Ein eindeutiges Präfix von rund 1.200 Token wird zweimal
gestreamt (kalt, dann warm) und ein anderes Kontrollpräfix einmal. Liegt die
warme TTFT unter der Hälfte der kalten und der Kontroll-TTFT und ist sie
mindestens 150 ms schneller als kalt, ist Präfix-Caching aktiv. Immer nur zur
Information: Präfix-Caching ist eine legitime Optimierung.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `prompt_cache.verdict` (Prompt-Präfix-Caching) | Ein wiederholter Prompt-Präfix kam viel schneller zurück: Präfix-Caching ist aktiv. | Info | Nicht gewertet |
|  | Ein wiederholter Prompt-Präfix war nicht deutlich schneller. | Info | Nicht gewertet |
|  | Eine oder mehrere Timing-Proben lieferten keine verwertbare Zeit. | Nicht eindeutig | Nicht gewertet |

**Einschränkungen.** Modelle erfinden auf Nachfrage falsche „System-Prompts“;
ein Leck allein bleibt daher NIEDRIG. Die Dialektübersetzung formt
Tool-Call-JSON um; nur ein Austausch des *Werts* zählt. Bedingte Manipulation
(nur bei bestimmten Schlüsselwörtern, Clients oder nach einer Aufwärmphase)
kann einer endlichen Zahl von Tests entgehen. Black-Box-Logging ist vom Client
aus **nicht beweisbar**, und zing kann *nutzerübergreifendes* Cache-Teilen mit
einem Schlüssel nicht zeigen: das Fehlen eines Timing-Signals beweist nicht,
dass Prompts nicht protokolliert werden.

---

## `performance` — Leistung

**Was sie misst.** Wie **gleichmäßig** der Endpunkt ist, nicht wie schnell. Ein
lokales oder selbst gehostetes Modell, das langsam, aber stetig ist, schneidet
gut ab; die reine Geschwindigkeit zählt nur im Vergleich zu einer Referenz.

**Vorgehen.** Die eigene Messung läuft bei deep, full und custom und bei
standard nur im Vergleichsmodus (5 Anfragen je Seite, zu wenige für die
Gleichmäßigkeitsprüfungen). Je Endpunkt: drei `GET /models`-Pings, eine
Aufwärmanfrage (als Kaltstart berichtet), `--performance-requests` gleichförmige
Anfragen (Standard 100) mit `--performance-max-tokens` Ausgabe-Token (Standard
128), dann bei deep/full ein Burst mit `--concurrency`. Jede Anfrage ist nicht
cachebar: eine zufällige Anfrage-ID eröffnet den Prompt, die Themen wechseln, es
werden keine Cache- oder Reasoning-Parameter gesendet; eine Antwort, die trotzdem
aus einem Cache kommt, wird markiert und aus der Statistik genommen. Die Messung
streamt standardmäßig (`--performance-non-streaming` für Relays, die nicht
streamen können); full misst beide Modi, verschränkt. Im Vergleichsmodus
wechseln Ziel und Referenz sich ab, sodass Netzwerkschwankungen beide gleich
treffen.
Gecachte Eingabe-Token zählen nur, wenn sie mindestens die Hälfte des Prompts
abdecken: lokale Server (Ollama, llama.cpp, LM Studio) verwenden die gecachte
Chat-Vorlage jedes Prompts wieder, und das ist keine gespeicherte Antwort.
Jeder Aufruf der Prüfung wird als Anfrage-Datensatz festgehalten
(`performance.requests`, nur Zahlen, nie Prompt- oder Antworttext); sein
`start_ms` zählt ab `started_at` des Berichts (UTC), sodass sich der
Zeitpunkt jedes Aufrufs rekonstruieren lässt.

Die Gleichmäßigkeit nutzt Tail-Verhältnisse (p90 ÷ p50 für Latenz und TTFT,
p50 ÷ p10 für den Durchsatz), die eine einzelne Ausreißer-Anfrage nicht so
verschiebt wie eine Standardabweichung; sie brauchen mindestens 10 saubere
Stichproben. Referenz ist die vertrauenswürdige Referenz, sonst der Bereich
`performance.decode_tps` des Profils in der Wissensbasis.

| Prüfung | Ergebnis | Status | Wirkung |
|---|---|---|---|
| `performance.summary` | Latenz, TTFT und Durchsatz wurden gemessen. | Info | Nicht gewertet |
|  | Keine der Probe-Anfragen war erfolgreich. | Nicht eindeutig | Nicht gewertet |
| `performance.latency_consistency` | Die Latenz ist gleichmäßig (Tail-Verhältnis höchstens 1,3). | Bestanden | 100 Pkt. |
|  | Die Latenz ist stabil (Tail-Verhältnis höchstens 1,75). | Bestanden | 85 Pkt. |
|  | Die Latenz schwankt merklich (Tail-Verhältnis höchstens 2,5). | Warnung · Niedrig | 65 Pkt. |
|  | Die Latenz ist sprunghaft (Tail-Verhältnis über 2,5). | Fehlgeschlagen · Niedrig | 40 Pkt. |
|  | Zu wenige Messwerte, um die Gleichmäßigkeit der Latenz zu beurteilen. | Info | Nicht gewertet |
| `performance.ttft_consistency` | Die Zeit bis zum ersten Token ist gleichmäßig (Tail-Verhältnis höchstens 1,3). | Bestanden | 100 Pkt. |
|  | Die Zeit bis zum ersten Token ist stabil (Tail-Verhältnis höchstens 1,75). | Bestanden | 85 Pkt. |
|  | Die Zeit bis zum ersten Token schwankt merklich (Tail-Verhältnis höchstens 2,5). | Warnung · Niedrig | 65 Pkt. |
|  | Die Zeit bis zum ersten Token ist sprunghaft (Tail-Verhältnis über 2,5). | Fehlgeschlagen · Niedrig | 40 Pkt. |
|  | Zu wenige Messwerte, um die Gleichmäßigkeit der Zeit bis zum ersten Token zu beurteilen. | Info | Nicht gewertet |
| `performance.throughput_consistency` | Der Durchsatz ist gleichmäßig (Tail-Verhältnis höchstens 1,3). | Bestanden | 100 Pkt. |
|  | Der Durchsatz ist stabil (Tail-Verhältnis höchstens 1,75). | Bestanden | 85 Pkt. |
|  | Der Durchsatz schwankt merklich (Tail-Verhältnis höchstens 2,5). | Warnung · Niedrig | 65 Pkt. |
|  | Der Durchsatz ist sprunghaft (Tail-Verhältnis über 2,5). | Fehlgeschlagen · Niedrig | 40 Pkt. |
|  | Zu wenige Messwerte, um die Gleichmäßigkeit des Durchsatzes zu beurteilen. | Info | Nicht gewertet |
| `performance.errors` | Höchstens 2 % der Messanfragen schlugen fehl. | Bestanden | 100 Pkt. |
|  | Bis zu 10 % der Messanfragen schlugen fehl oder liefen in eine Zeitüberschreitung. | Warnung · Niedrig | 80 Pkt. |
|  | Viele Messanfragen schlugen fehl oder liefen in eine Zeitüberschreitung. | Fehlgeschlagen · Niedrig | 50 Pkt. |
| `performance.load_stability` | Die Latenz hält unter paralleler Last stand (höchstens 1,5x). | Bestanden | 100 Pkt. |
|  | Die Latenz steigt unter paralleler Last (bis 3x). | Warnung · Niedrig | 80 Pkt. |
|  | Die Latenz verschlechtert sich unter paralleler Last stark (über 3x). | Fehlgeschlagen · Niedrig | 55 Pkt. |
| `performance.cache_hit` | Eindeutige Probe-Prompts kamen aus einem Cache (aus der Statistik ausgenommen). | Warnung · Niedrig | 60 Pkt. |
|  | Die Referenz lieferte einmalige Mess-Prompts aus einem Cache (nicht gewertet). | Info | Nicht gewertet |
| `performance.reference` | Der Durchsatz entspricht der Referenz für dieses Modell. | Bestanden | 100 Pkt. |
|  | Langsamer als die Referenz (z. B. lokal oder kleinere Hardware); kein Fehler. | Info | 80 Pkt. |
|  | Viel schneller als die Referenz (passt zu einem kleineren Modell). | Warnung · Niedrig | 60 Pkt. |
| `performance.reasoning` | Das Modell verbraucht versteckte Reasoning-Tokens; die TTFT enthält das Nachdenken. | Info | Nicht gewertet |
| `performance.relay_overhead` | Latenz mit der vertrauenswürdigen Baseline verglichen (nur zur Information). | Info | Nicht gewertet |
| `performance.skipped` | Die Performance-Probe war deaktiviert. | Info | Nicht gewertet |

**Einschränkungen.** Die Latenz hängt vom Netzwerkpfad und der momentanen Last
des Anbieters ab; wiederholen Sie ein schwaches Gleichmäßigkeitsergebnis zu
einer anderen Zeit. Die Bereiche der Wissensbasis sind bewusst weit gefasste
Mediane nativer APIs, und ein langsameres Ziel ist nie ein Fehlschlag. Alle
Befunde haben höchstens Schweregrad NIEDRIG; diese Dimension bewegt also die
Bewertung, nie das Risikourteil.

---

## Zuordnung Trick → Detektor

Die 16 Relay-Tricks aus der Recherche verteilen sich wie folgt auf zing.

| # | Trick (Kennung) | Schweregrad | Detektor(en) | Aktuelle Abdeckung |
|---|---|---|---|---|
| 1 | `downgrade.silent-substitution` | critical | `model_identity`, `quality_judge` | Selbstidentifikation, Fingerprints, `model`-Feld; Richter; Vergleichsmodus |
| 2 | `downgrade.reasoning-collapse` | critical | `model_identity`, `quality_judge` | nur Fingerprints und Richter; noch keine eigene Schwierigkeitsleiter |
| 3 | `downgrade.quantized-distilled` | high | `quality_judge`, `model_identity` | Richter mit Referenz; noch kein Verteilungstest |
| 4 | `downgrade.partial-probabilistic-routing` | high | `model_identity` | nur wenn die Stichproben das Ersatzmodell treffen; Stichproben in großer Zahl sind Roadmap |
| 5 | `context.window-truncation` | high | `context_window` | Leiter mit Nadel am Rand + binäre Suche; gemessen vs. angegeben |
| 6 | `context.lost-in-middle-rag` | high | `context_window` | Tiefen 0,1/0,5/0,9 bei mittlerer Größe |
| 7 | `stream.fake-streaming` | medium | `streaming` | Chunk-Anzahl, Zeitpunkt des ersten Tokens, Gleichförmigkeit der Abstände |
| 8 | `billing.usage-inflation` | high | `billing` | unabhängige heuristische Token-Schätzung eines bekannten Tests |
| 9 | `billing.missing-usage` | medium | `billing`, `protocol_response`, `streaming` | Vorhandensein, Aufteilung und Arithmetik der Usage; Usage-Chunk im Stream |
| 10 | `privacy.prompt-logging-leakage` | high | `prompt_cache` | Präfix-Caching per TTFT (informativ); nutzerübergreifendes Teilen und Logging bleiben mit einem Schlüssel unbeweisbar |
| 11 | `infra.shared-upstream-key` | high | — | Roadmap (sinkendes Kontingent im Leerlauf, durchgesickerte Upstream-Request-IDs) |
| 12 | `cache.ignore-temperature` | medium | `determinism` | byte-identische Ausgabe bei Temperatur 1,0; bei Reasoning-Modellen unterdrückt |
| 13 | `prompt.injected-system-prompt` | medium | `injected_prompt`, `billing` | fester Mehraufwand an Eingabe-Token (zwei Größen) + Leck-Test |
| 14 | `throttle.rate-limit-quality` | medium | `reliability`, `performance` | Erfolgsquote (429 gesondert), Tail-Latenz, Stabilität unter Last; Langzeitmessung ist Roadmap |
| 15 | `capability.json-tool-fakery` | medium | `capability`, `protocol_request` | Tools, JSON-Modus, striktes Schema, Parameter; je ein Test, keine Quoten |
| 16 | `integrity.response-tampering` | critical | `integrity` | Canaries mit bekannter URL/bekanntem Paket; KRITISCH, wenn eine Referenz es bestätigt |

---

## Grenzen & verantwortungsvoller Einsatz

**zing meldet Abweichung und Risiko, keinen Betrugsnachweis.** Das Urteil ist
vorsichtig formuliert (clean / low / medium / high / inconclusive), lässt
unklare Ergebnisse nicht eindeutig und stuft nur bei harten Belegen mit hohem
Schweregrad auf „hoch“.

**Was eine Black-Box-Prüfung nicht beweisen kann:**

- **Prompt-Logging oder Datenspeicherung.** Ein Timing-Signal belegt Caching;
  sein Fehlen beweist nicht, dass Prompts nicht protokolliert werden.
- **Antwortintegrität** ohne vom Anbieter signierte Antworten: bedingte
  Manipulation kann endlich vielen Tests entgehen.
- **Geteilte oder gestohlene Schlüssel:** höchstens ein *Risiko* eines geteilten
  Pools.
- **Harmloser Drift oder Austausch:** offizielle APIs aktualisieren Snapshots
  stillschweigend.
- **Gleichbleibendes Routing:** ein Relay kann probabilistisch routen, und eine
  Prüfung sieht nur die Anfragen, die sie gesendet hat.

**Vorgehensweise.** Befunde, die von exaktem Vergleich abhängen, nutzen
`temperature=0` und eng gefasste Prompts. Jeder Befund trägt seine Belege
(Eingaben, beobachtete Werte, Zählungen, Zeiten), und jeder Bericht hält Profil,
Prompt-Sprachen und Einstellungen fest, mit denen er lief, sodass sich ein
Ergebnis unabhängig nachprüfen lässt. Ein Relay kann Tests erkennen: zu anderen
Zeiten erneut ausführen und den Vergleichsmodus gegen eine vertrauenswürdige
Referenz **genau des angegebenen Snapshots** bevorzugen — der stärkste Weg,
Modellverhalten von Relay-Verhalten zu trennen, und der einzige zu hoher
Konfidenz.

**Verantwortungsvolle Offenlegung.** **Beschuldigen Sie einen Anbieter nicht
öffentlich** auf Grundlage eines zing-Berichts. Bevor Sie handeln: mit mehr
Stichproben und zu anderen Zeiten erneut ausführen, mit dem Vergleichsmodus
bestätigen und Drift, Netzwerk und Last als Erklärung ausschließen. Bleibt ein
ernster Verdacht, sprechen Sie den Anbieter zuerst privat an — als Fragen zum
beobachteten Verhalten, nicht als Vorwürfe.
