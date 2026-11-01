# Schnellstart

> [🇬🇧 English](../../../guide/quickstart.md) · [🇨🇳 中文](../../zh-CN/guide/quickstart.md) · [🇫🇷 Français](../../fr/guide/quickstart.md) · [🇪🇸 Español](../../es/guide/quickstart.md) · [🇵🇹 Português](../../pt/guide/quickstart.md) · [🇮🇹 Italiano](../../it/guide/quickstart.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/quickstart.md)

```bash
# 1) ein Relay gegen seine Angaben prüfen (Modell-ID + Anbieterhinweis)
export EKTE_API_KEY=sk-ihr-relay-schluessel
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) die stärkste Prüfung: Vergleich mit einer vertrauenswürdigen Referenz desselben Modells
export OPENAI_API_KEY=sk-ihr-openai-schluessel
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) ein natives Anthropic-Relay (Messages API) prüfen — das Protokoll wird anhand von
#    base_url/model automatisch erkannt oder mit --api anthropic erzwungen
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) einen vermuteten Austausch bestätigen: die ECHTE Modell-ID des Relays gegen das Profil
#    prüfen, unter dem es verkauft wird (hier: ein Doubao-Modell, ausgegeben als deepseek-v4-flash)
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) die Modelle auflisten, die ein Endpunkt bewirbt
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) die Wissensbasis ansehen
ekte kb            # alle Profile, mit ihrer Quelle
ekte kb deepseek   # ein Anbieter

# 7) eine Konfiguration zum Einchecken erzeugen
ekte init          # schreibt ekte.yaml
ekte check -c ekte.yaml
```

API-Schlüssel lassen sich direkt, als `env:VAR` oder als `file:/pfad` angeben;
Berichte enthalten immer nur einen Fingerabdruck des Schlüssels. Eine vollständige
Konfigurationsdatei finden Sie in [`examples/ekte.yaml`](../../../../examples/ekte.yaml).

Die Datei hat eine Formatversion (`version: 1`; eine Datei ohne Version gilt als Format 1). Falsche Typen und ungültige Werte werden mit Datei, Zeile und Schlüssel abgelehnt; unbekannte Schlüssel werden bis ekte 1.0.0 mit einer Warnung ignoriert, ab dann abgelehnt. `ekte config migrate` aktualisiert eine ältere Datei. Das Schema ist [`docs/schemas/config.schema.json`](../../../schemas/config.schema.json).

## Als Werkzeug für ein LLM / einen Agenten

ekte ist dafür gebaut, von einem anderen Programm oder Modell gesteuert zu werden.
Alles geht als JSON nach stdout, auch Fehler, und der Exit-Code dient als Schranke.

```bash
# schlankes, agentenfreundliches Urteil (~5x kleiner als --json: ohne umfangreiche Belege)
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# vollständiger strukturierter Bericht, wenn Sie die Belege jedes Befunds brauchen
ekte check --base-url ... --model gpt-4o --json

# erst das Budget: welche Detektoren laufen + geschätzte API-Aufrufe, OHNE einen auszuführen
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# Schranke über den Exit-Code (1 bei Risiko >= medium oder einer Bewertung unter --fail-under);
# Konfigurations-/Aufruffehler enden mit 2, als JSON
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# maschinenlesbare Erkundung
ekte kb --json                      # die gesamte Wissensbasis
ekte models --base-url ... --json   # was ein Endpunkt bewirbt
```

Im Modus `--json`/`--compact` gibt eine fehlerhafte Konfiguration `{"error": {...}}`
(Exit-Code 2) statt einer Meldung für Menschen aus, sodass eine Pipeline Fehler
einheitlich auswerten kann.
