# Leistung

> [🇬🇧 English](../../../guide/performance.md) · [🇨🇳 中文](../../zh-CN/guide/performance.md) · [🇫🇷 Français](../../fr/guide/performance.md) · [🇪🇸 Español](../../es/guide/performance.md) · [🇵🇹 Português](../../pt/guide/performance.md) · [🇮🇹 Italiano](../../it/guide/performance.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/performance.md)

Jeder Bericht enthält einen Abschnitt **performance**: Latenz, Zeit bis zum
ersten Token (TTFT), Decode- und End-to-End-Token/s, Latenz und Jitter zwischen
Chunks, Fehler-/Timeout-/429-Raten, eine Netzwerkaufschlüsselung
(TCP-Verbindung, TLS, ein `GET /models`-Roundtrip, Serverzeit) und Kaltstart,
jeweils als count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev.

Läuft die eigene Messung, bewertet sie die Dimension **Leistung**. Die Bewertung
misst **Gleichmäßigkeit**, nicht reine Geschwindigkeit: ein langsamer, aber
gleichmäßiger Endpunkt (ein lokales oder selbst gehostetes Modell) wird nicht
dafür abgewertet, dass er kein Rechenzentrum ist; die Prüfungen und ihre Punkte
stehen in der [Methodik](methodology.md#performance--leistung). Leistungsbefunde haben höchstens niedrigen Schweregrad: sie bewegen die
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

Audits, die in `ekte serve` gleichzeitig laufen (mehrere Browser-Tabs,
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

**Fehlgeschlagene Anfragen.** ekte unterscheidet, wo eine Anfrage scheiterte.
Ein Fehler des **Relays** (ein HTTP-Fehlerstatus, eine Zeitüberschreitung beim
Warten auf das Relay, eine abgebrochene oder fehlerhafte Antwort) zählt gegen
das Relay und wird nie wiederholt. Ein **Netzwerk**fehler (der Proxy, über den
ekte geht, DNS, Verbindungsaufbau oder TLS, bevor das Relay antworten konnte)
und ein **lokaler** Fehler (in ekte selbst) gehen nicht auf das Relay zurück:
Die Anfrage wird wiederholt, standardmäßig einmal (`EKTE_NON_RELAY_RETRIES`, 0
bis 10), und scheitert sie weiter, wird sie gesondert gezählt (`network_errors`,
`local_errors`) und bleibt aus den Fehlerquoten heraus. Eine Prüfung, deren
Anfragen alle so scheiterten, gilt als nicht eindeutig statt bewertet zu werden,
und der Bericht warnt, dass der Lauf beeinträchtigt war. Jeder Anfrage-Datensatz
trägt seine Klasse (`error_class`) und ob er wiederholt wurde (`retried`); bei
früher gespeicherten Läufen leitet die Weboberfläche die Klasse aus dem
gespeicherten Fehler ab. Die Zeitverlaufsdiagramme zeichnen sie getrennt: ein
Fehler beim Relay ist ein rotes ×, ein Netzwerk- oder ekte-Fehler eine graue ◇,
und ein Versuch, der nie zählt (ein wiederholter), eine kleinere graue Marke
derselben Form; ein Hinweis über der Legende nennt, wie viele Anfragen auf dem
Netzwerkweg oder in ekte fehlgeschlagen sind.

Hinter einem HTTPS-Proxy schlägt eine Anfrage, für die der Proxy keinen Tunnel
öffnet, mit `ProxyError` fehl. ekte behält die Antwort des Proxys auf das
`CONNECT`: Der Datensatz trägt ihren Status (`proxy_status`) und wie lange der
Proxy für die Antwort brauchte (`proxy_wait_ms`); die Beweisdatei behält ihre
Header und die Fehlerseite (unter `proxy`; die von Squid nennt den errno und die
versuchte Adresse). Der Status sagt, wessen Problem es ist, und Datentabelle,
Warnung zum beeinträchtigten Lauf und Zuverlässigkeitsempfehlung sagen es auch:
**502/503/504** — „Relay-Host über den Proxy nicht erreichbar“, meist nach dem
eigenen Verbindungs-Timeout des Proxys (oft 60 s): Der Proxy erreichte den
Relay-Host nicht, prüfen Sie also dessen Erreichbarkeit vom Proxy aus (DNS und
Adressen, IPv6, eine Firewall oder WAF, die die Adresse des Proxys verwirft,
Load-Balancer-Knoten), nicht nur den Proxy; **4xx** (407, 403) — „der Proxy hat
den Tunnel abgelehnt“: seine Authentifizierung oder Richtlinie. In beiden Fällen
bleibt es ein Netzwerkfehler, wird wiederholt und nicht gegen das Relay gezählt.
