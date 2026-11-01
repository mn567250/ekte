# Überwachung

> [🇬🇧 English](../../../guide/monitoring.md) · [🇨🇳 中文](../../zh-CN/guide/monitoring.md) · [🇫🇷 Français](../../fr/guide/monitoring.md) · [🇪🇸 Español](../../es/guide/monitoring.md) · [🇵🇹 Português](../../pt/guide/monitoring.md) · [🇮🇹 Italiano](../../it/guide/monitoring.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/monitoring.md)

Ein Relay kann heute das echte Modell liefern und es nächste Woche
stillschweigend austauschen. `ekte watch` wiederholt die Prüfung nach Zeitplan,
speichert jeden Lauf im Verlauf und alarmiert einen Webhook, wenn das Risiko eine
Schwelle überschreitet oder sich gegenüber dem vorherigen Lauf
**verschlechtert**.

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang de                                     # oder --once für cron
```

Warnungen werden für **Slack / Feishu / DingTalk / generisches JSON** formatiert,
automatisch anhand der Webhook-URL erkannt, und in der Warnsprache verfasst —
standardmäßig Englisch; `--alert-lang en|zh|fr|es|pt|it|de|nb`. Die generische
JSON-Nutzlast hält ihre Schlüssel und Maschinenwerte (`risk_level`, `score`, …)
sprachneutral, übersetzt die für Menschen lesbaren (`text`, `headline`,
`key_findings`) und gibt die `language` an.

**In der Weboberfläche** führt `ekte serve` dieselben Überwachungen in einem
Hintergrund-Scheduler im Serverprozess aus, speichert jeden Lauf im **Verlauf**
und sendet dieselben Webhook-Warnungen. Einen Lauf im **Verlauf** öffnen und **Als Überwachung
einplanen** wählen. ekte übernimmt die Konfiguration dieses Laufs (Relay,
Modell, angegebenes Modell, Anbieter, Suite, benutzerdefinierte Dimensionen) in
eine pausierte Überwachung auf der Seite **Überwachung**; dort Intervall und
API-Schlüssel setzen (der Verlauf speichert nie Schlüssel) und sie
einschalten. Intervall, Schlüssel, **Warnschwelle**, Webhooks und **Sprache der
Warnungen** lassen sich auf jeder Überwachung direkt bearbeiten. Ein Klick auf
den Namen klappt die Karte auf Name, Status und letzten Lauf zusammen
(**Alle einklappen** / **Alle aufklappen** über der Liste; pro Browser
gemerkt), und das Filterpanel (Suche, Status, letztes Risiko, Endpunkttyp,
Relay, Suite) grenzt eine lange Liste ein wie im **Verlauf**.

Jede Überwachung hat ihre eigene Warnsprache (standardmäßig die Sprache der
Oberfläche), lässt sich sofort ausführen, pausieren oder löschen und bleibt an
das Wissensbasis-Profil gebunden, mit dem sie angelegt wurde, bis Sie es neu
binden.

Fällige Überwachungen laufen gleichzeitig, jede als eigenes Audit, aber nie mehr
als ein Audit pro Relay-Host auf einmal und insgesamt höchstens
`EKTE_MAX_PARALLEL_AUDITS`; ein Lauf wartet auf einen freien Platz (auch ein von
Hand gestartetes Audit kann sich hinter laufenden Überwachungen einreihen). Die
Zeit eines Laufs ist der Start seines Audits, nach einer etwaigen Wartezeit. Die
Prüfung auf Verschlechterung vergleicht mit dem zuletzt gespeicherten Lauf
desselben Relays und Modells, egal wie viele andere Läufe seitdem gespeichert
wurden. Die Warn-Webhooks eines Laufs werden gleichzeitig gesendet, sodass ein
langsamer oder toter Webhook die anderen nicht aufhält. Schlüssel werden
verschlüsselt in Ihrem lokalen Datenverzeichnis gespeichert und nie an den Browser zurückgegeben.

**Speicherung der API-Schlüssel.** Standardmäßig **speichert** ekte die
API-Schlüssel der Überwachungen **nicht**: Ein eingegebener Schlüssel bleibt nur
im Arbeitsspeicher von `ekte serve` und wird nie auf die Festplatte geschrieben.
Nach einem Neustart nennt die Seite **Überwachung** die Überwachungen, die
ihren Schlüssel erneut brauchen; sie warten (kein Fehllauf, kein Alarm), bis Sie
ihn eingeben. Überwachungen ohne Schlüssel und `env:`/`file:`-Verweise laufen
weiter. Sollen Schlüssel Neustarts überstehen, wählen Sie auf der Seite
**Überwachung** unter **Speicherung der API-Schlüssel** die Option
**Verschlüsselt auf diesem Rechner speichern**: Die Schlüssel liegen dann mit
einem Hauptschlüssel verschlüsselt in `watches.db`. Zurückschalten verschiebt die
gespeicherten Schlüssel in den Arbeitsspeicher und löscht sie aus `watches.db`.
Der Seitenhinweis zeigt den aktiven Modus, fragt vor dem Umschalten nach und
meldet, was verschoben wurde. Installationen, die bereits verschlüsselte Schlüssel
speichern oder `EKTE_SECRET_KEY` setzen, speichern sie weiter, bis Sie umschalten.

**Hauptschlüssel.** Die API-Schlüssel der Überwachungen sind mit einem
Hauptschlüssel verschlüsselt, den ekte nie auf die Festplatte schreibt. Wenn Sie
zum ersten Mal einen API-Schlüssel speichern, erstellt die Seite **Überwachung**
ihn und zeigt ihn ein einziges Mal: kopieren oder herunterladen, in einem
Passwortmanager aufbewahren (Ihr Browser kann ihn speichern) und zur Bestätigung
wieder einfügen. Nach jedem Neustart von `ekte serve` fragt die Seite erneut
danach (der Browser kann ihn ausfüllen); bis dahin warten Überwachungen, die ihn
brauchen, während Überwachungen ohne Schlüssel oder mit
`env:`/`file:`-Schlüsseln weiterlaufen. Die Statusleiste der Seite bietet
außerdem **Sperren**, **Wechseln** und **Schlüssel vergessen?** (verwirft die
verschlüsselten API-Schlüssel, damit Sie sie neu eingeben können). Für
unbeaufsichtigten Betrieb oder Docker übergeben Sie den Schlüssel als
`EKTE_SECRET_KEY` (siehe [Docker](docker.md));
`ekte secret status | export | rotate` verwalten ihn auf der Kommandozeile.
