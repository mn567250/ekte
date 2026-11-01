# Datenschutz und lokale Daten

> [🇬🇧 English](../../../guide/privacy.md) · [🇨🇳 中文](../../zh-CN/guide/privacy.md) · [🇫🇷 Français](../../fr/guide/privacy.md) · [🇪🇸 Español](../../es/guide/privacy.md) · [🇵🇹 Português](../../pt/guide/privacy.md) · [🇮🇹 Italiano](../../it/guide/privacy.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/privacy.md)

- **Nur lokal.** `ekte serve` lauscht nur auf Loopback (`127.0.0.1`, `::1`,
  `localhost`), antwortet nur unter diesen Hostnamen und weist
  seitenübergreifende Anfragen ab; es hat keine Anmeldung, weil nichts außerhalb
  Ihres Rechners es erreichen kann. ekte kontaktiert nur die Endpunkte, die Sie
  konfigurieren (Ziel, Referenz, Richter, Webhooks); zur Laufzeit lädt es nichts
  herunter, nicht einmal Tokenizer-Dateien.
- **Schlüssel.** Berichte und Verlauf speichern von einem API-Schlüssel nur
  einen Fingerabdruck. Die Schlüssel der Überwachungen liegen verschlüsselt in
  `watches.db`; der Hauptschlüssel, der sie entschlüsselt, wird nie im
  Datenverzeichnis gespeichert (Sie bewahren ihn auf, siehe [Überwachung](monitoring.md)), sodass eine Kopie des Verzeichnisses keinen API-Schlüssel preisgibt.
  Zugriff auf das Verzeichnis haben trotzdem nur Sie.
- **Datenverzeichnis.** `~/.ekte` (oder `EKTE_DATA_DIR`), angelegt mit `0700`
  und Dateien mit `0600`: `history.db` (Prüfverlauf), `watches.db`
  (Überwachungen samt verschlüsselter Schlüssel) und `kb.db` (Ihre
  Wissensbasis-Einträge). Löschen Sie das Verzeichnis, um alles zu entfernen.
  `ekte data-dir` zeigt, wo es liegt; `--data-dir PFAD` wählt für einen Lauf
  ein anderes, z. B. legt `ekte serve --data-dir .` die Datenbanken im
  aktuellen Ordner ab. Es sind normale SQLite-Dateien, die Sie für eigene
  Auswertungen öffnen können (während ekte läuft, am besten nur lesend).
  `history_metrics` enthält eine Zeile Messwerte pro Lauf, `history_requests`
  jeden Anfrage-Datensatz (dort einmal gespeichert, nicht in jedem Bericht).
  Committen Sie `watches.db` nicht, falls der Ordner ein Repository ist.

## Verantwortungsvoller Einsatz

ekte ist ein Hilfsmittel für Black-Box-Prüfungen. Es **kann nicht beweisen**,

- dass ein Anbieter Ihre Prompts speichert oder damit trainiert,
- dass er immer an genau ein bestimmtes Modell weiterleitet (Relays können probabilistisch routen),
- Abrechnungsbetrug über das hinaus, was die unabhängige Token-Schätzung nahelegen kann.

Nutzen Sie die Berichte für Ihre eigene Sorgfaltsprüfung. **Beschuldigen Sie einen
Anbieter nicht öffentlich** auf Grundlage eines einzelnen Laufs, ohne
Stichprobengröße, Kosteneinstellungen und lokales Recht zu prüfen. Führen Sie
`ekte compare` gegen eine vertrauenswürdige Referenz aus, bevor Sie weitreichende
Schlüsse ziehen.
