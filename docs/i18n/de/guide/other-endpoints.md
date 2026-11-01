# Prüfungen für Embedding, Rerank, Bild und Audio

> [🇬🇧 English](../../../guide/other-endpoints.md) · [🇨🇳 中文](../../zh-CN/guide/other-endpoints.md) · [🇫🇷 Français](../../fr/guide/other-endpoints.md) · [🇪🇸 Español](../../es/guide/other-endpoints.md) · [🇵🇹 Português](../../pt/guide/other-endpoints.md) · [🇮🇹 Italiano](../../it/guide/other-endpoints.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/other-endpoints.md)

Diese Endpunkte liefern Vektoren, Rangfolgen, Bilder oder Audio statt Chat, daher
prüft ekte sie mit fokussierten Tests statt mit den Chat-Prompts. Jeder gibt ein
Urteil aus und unterstützt `--json` und `--fail-on-risk`.

## Endpunkttyp (Surface), Embedding- und Rerank-Monitore

Jede Prüfung, jede Verlaufszeile und jeder Monitor hat einen **Endpunkttyp**
(`surface`): `chat` (Standard), `embedding` oder `rerank`. Er ist unabhängig von
der Suite. Embedding- und Rerank-Prüfungen laufen über denselben Runner, dieselbe
Bewertung (0–100, A–F), denselben Verlauf, dieselbe Analyse und dieselben Monitore
wie Chat-Prüfungen; nur die Detektoren unterscheiden sich. Verlauf und Analyse
filtern nach Endpunkttyp, und die Analyse zeigt nur die Kennzahlen, die zutreffen.

Um einen Embeddings- oder Rerank-Endpunkt zu überwachen, prüfen Sie ihn auf der
Seite **Prüfung** (Endpunkttyp **Embeddings** oder **Reranking** wählen) und wählen **Überwachen**, oder **Als Überwachung einplanen** in
seiner Verlaufszeile. Der Monitor wiederholt die Prüfung nach Zeitplan, mit
derselben Fixierung der Wissensbasis, derselben Alarmschwelle und denselben
Regressionsalarmen wie ein Chat-Monitor, und prüft die **Drift** gegenüber
seinem vorigen Lauf (die Vektoren eines Embedding-Tests, Rangfolge und Scores
eines Rerank-Tests). Die angegebene Dimension eines Embedding-Monitors lässt sich
auf seiner Karte ändern (leer oder 0: aus der Wissensbasis). Die
Geschwindigkeitsmessungen (Embeddings: Latenz, Kaltstart, Eingaben/s,
Batch-Skalierung; Rerank: Latenz, Kaltstart, Dokumente/s, 4 gegen 32 Dokumente)
laufen nur in den Suiten deep, full oder custom oder in standard mit Referenz.

## Embeddings und Rerank

```bash
# Die erwartete Vektordimension wird für das angegebene Modell aus der Wissensbasis ermittelt.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Oder die erwartete Dimension direkt vorgeben:
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: ein eingebauter Test mit bekannter Antwort — ein echter Reranker muss das
# offensichtlich relevante Dokument an erster Stelle einordnen.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Gründlicher: mit der Rerank-Geschwindigkeitsmessung; --no-save hält den Lauf aus dem Verlauf.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# Zuerst die Prüfungen und die geschätzten Aufrufe ansehen, ohne Anfrage:
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` prüft Konnektivität, den **Test mit bekannter Antwort** (das
offensichtlich relevante Dokument muss an erster Stelle stehen), das
zurückgegebene `model`-Feld, Determinismus (dieselbe Anfrage zweimal ergibt
dieselbe Rangfolge und dieselben Scores) und die **Rangfolge-Drift** gegenüber
dem vorigen gespeicherten Lauf. `ekte embed` und `ekte rerank` nehmen `--suite`,
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

Beide gibt es auch in der Weboberfläche: Sie starten auf der Seite **Prüfung**
über die Auswahl des Endpunkttyps (**Embeddings**, **Reranking**). Die Rerank-Prüfung nutzt immer die
eingebauten Tests, damit jeder Lauf für Drift und Überwachung vergleichbar bleibt.

## Bild- und Audio-Generierung (TTS)

Bildgenerierung (`POST /v1/images/generations`) und Sprachsynthese
(`POST /v1/audio/speech`), dekodiert allein mit der Python-Standardbibliothek —
Bildabmessungen aus den Header-Bytes (PNG/JPEG/GIF/WebP), WAV-Dauer über `wave`.

```bash
# Liefert ein Relay, das DALL·E 3 angibt, wirklich das angeforderte 1792x1024? Ein
# verkleinertes Bild oder eines in falscher Größe (oder außerhalb der nativen Größen des
# angegebenen Modells laut Wissensbasis) ist das Hauptsignal für einen Etikettenschwindel.
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Liefert ein Relay, das tts-1-hd angibt, echtes Audio, dessen Länge mit der Eingabe
# wächst (kein fester Platzhalter, kein als Audio getarntes HTML/JSON)?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
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
