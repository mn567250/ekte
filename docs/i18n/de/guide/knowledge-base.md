# Wissensbasis

> [🇬🇧 English](../../../guide/knowledge-base.md) · [🇨🇳 中文](../../zh-CN/guide/knowledge-base.md) · [🇫🇷 Français](../../fr/guide/knowledge-base.md) · [🇪🇸 Español](../../es/guide/knowledge-base.md) · [🇵🇹 Português](../../pt/guide/knowledge-base.md) · [🇮🇹 Italiano](../../it/guide/knowledge-base.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/knowledge-base.md)

ekte beurteilt ein Relay anhand des **Profils** des angegebenen Modells: natives
Kontextfenster, maximale Ausgabe, Wissensstichtag, Tokenizer, Fähigkeitsflags,
Identitätsschlüsselwörter und Verhaltens-Fingerabdrücke. Die mitgelieferten
Profile decken OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM und Moonshot
ab (`ekte kb` listet sie). Es gibt drei Ebenen; spätere haben Vorrang:

1. **Mitgelieferte** Profile, eine YAML-Datei pro Anbieter in
   [`ekte/knowledge/data/`](../../../../ekte/knowledge/data).
2. **Ein Verzeichnis eigener YAML-Dateien**: `--kb-dir ./my-profiles`
   (wiederholbar) oder `EKTE_KB_DIR`.
3. **Ihre Einträge** (`kb.db` im Datenverzeichnis), hinzugefügt ohne YAML-Dateien
   oder editierbare Installation:
   - auf der Seite **Wissen** der Weboberfläche (`/kb`), mit je einem Tab für
     **Modelle**, **Anbieter** und **Relays**. Jeder Tab listet den vollständigen
     Bestand — mitgeliefert, `EKTE_KB_DIR` und eigene (markiert mit **Eigener**) —
     mit Filter, einem Ein-/Aus-Schalter pro Element und einem Formular
     **… hinzufügen**: **Modell hinzufügen** → **Recherche-Prompt kopieren** und in
     den KI-Assistenten Ihrer Wahl einfügen, das YAML seiner Antwort hochladen oder
     einfügen, dann **Prüfen und speichern**; **Anbieter hinzufügen** nimmt
     Anbieter-YAML auf dieselbe Weise; **Relay hinzufügen** nimmt Namen und
     Basis-URL. **Welches Profil verwendet eine Modell-ID?** zeigt, wie eine ID
     aufgelöst wird; Ihre Einträge lassen sich als YAML exportieren;
   - auf der Seite **Prüfung** der Weboberfläche: **In der
     Wissensbasis speichern** behält Namen und Basis-URL eines Relays (ein
     Anbieter-Eintrag ohne Modelle), aufgeführt unter **Wissen → Relays**;
   - auf der Kommandozeile: `ekte kb-prompt <model>`, `ekte kb-import <file>`
     (mit `--check` nur prüfen) und `ekte kb-export`.

Vor dem Speichern prüft ekte einen Eintrag: Schema und Grenzen, unsichere
reguläre Ausdrücke, jeden Prompt, den er senden würde, und Modell-IDs, die zu
einem anderen Profil aufgelöst würden. Ein eigenes Modell mit der ID eines
mitgelieferten ersetzt dieses (als *Überschattung* ausgewiesen), ändert aber nie
die Einstellungen eines mitgelieferten Anbieters; Fingerabdrücke werden anhand
ihrer ID zusammengeführt. Das Ausschalten eines mitgelieferten Modells, Anbieters
oder Relays auf der Seite **Wissen** wird ebenfalls in `kb.db` gespeichert: eine
ausgeschaltete Modell-ID wird nicht mehr aufgelöst, ein ausgeschalteter Anbieter
nimmt seine Modelle und Basis-URLs mit. `ekte check` und `ekte serve` nutzen genau
dieselben Profile; `--no-user-kb` (oder `EKTE_NO_USER_KB=1`) lässt Ihre Einträge
und Schalter weg.

Ein Modell mit leeren `identity_keywords` wird so nicht gespeichert: ekte
ergänzt seine eigenen Markenwörter aus den Namen von Anbieter und Modell (etwa
`glm` und `z.ai`) und zeigt eine Warnung,
sie zu prüfen, denn ohne sie könnte die Identitätsprüfung den eigenen Hersteller
des Modells für eine Konkurrenzmarke halten. Der Recherche-Prompt verlangt sie
ausdrücklich vom KI-Assistenten.

Jeder Bericht hält fest, gegen welches Profil er geprüft hat (`knowledge`:
Anbieter, Modell, wie die ID zugeordnet wurde, ihre Quelle und ein vollständiger
Schnappschuss mit Inhalts-Hash), sodass ein Bericht auch nach Änderungen an der
Wissensbasis überprüfbar bleibt.
