# Die Weboberfläche in Docker betreiben

> [🇬🇧 English](../../../guide/docker.md) · [🇨🇳 中文](../../zh-CN/guide/docker.md) · [🇫🇷 Français](../../fr/guide/docker.md) · [🇪🇸 Español](../../es/guide/docker.md) · [🇵🇹 Português](../../pt/guide/docker.md) · [🇮🇹 Italiano](../../it/guide/docker.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/docker.md)

`ekte serve` ist ein Werkzeug für einen einzelnen Benutzer, ohne Anmeldung.
Außerhalb eines Containers lauscht es nur auf Loopback (`127.0.0.1`, `::1`,
`localhost`) und lehnt jede andere Bind-Adresse ab. Ein Container ist die einzige
Ausnahme: Dort muss der Server auf den Schnittstellen des Containers lauschen,
damit die Portfreigabe von Docker ihn erreicht.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# http://localhost:8000 öffnen
```

**Veröffentlichen Sie immer an `127.0.0.1`** (`-p 127.0.0.1:8000:8000`, nicht
`-p 8000:8000`). Ein bloßes `-p 8000:8000` macht die Oberfläche — und jeden
API-Schlüssel, der dort eingegeben oder in einer Überwachung gespeichert wird —
in Ihrem Netzwerk zugänglich.

## Umgebungsvariablen

| Variable | Standard | Zweck |
|---|---|---|
| `EKTE_CONTAINER` | nicht gesetzt (`1` im Image) | Erlaubt eine Bind-Adresse außerhalb von Loopback. ekte prüft außerdem, ob es wirklich in einem Container läuft (`/.dockerenv`, `/run/.containerenv` oder Kubernetes); auf einem normalen Rechner öffnet das Setzen den Server nicht. |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` im Image) | Bind-Adresse. Alles außer Loopback erfordert `EKTE_CONTAINER=1`. `--host` hat Vorrang. |
| `EKTE_PORT` | `8000` | Port im Container. `--port` hat Vorrang. |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` im Image) | Prüfverlauf, Überwachungen (samt ihren API-Schlüsseln) und Ihre eigenen Einträge in der Wissensbasis. Binden Sie hier ein Volume ein, um sie zu behalten. |
| `EKTE_SECRET_KEY` | nicht gesetzt | Hauptschlüssel, der die gespeicherten API-Schlüssel der Überwachungen verschlüsselt: der Schlüssel, den die Seite Überwachung (oder `ekte secret rotate`) Ihnen angezeigt hat, oder `file:/run/secrets/ekte_key` / `env:VAR`. Ist er nicht gesetzt, geben Sie den Schlüssel nach jedem Containerstart auf der Seite Überwachung ein. Wird nie in `EKTE_DATA_DIR` gespeichert. Auf einem neuen Datenverzeichnis wählt das Setzen die verschlüsselte Schlüsselspeicherung; ohne ihn werden API-Schlüssel von Überwachungen gar nicht gespeichert und müssen nach jedem Containerstart neu eingegeben werden. Siehe unten. |
| `EKTE_KB_DIR` | nicht gesetzt | Zusätzliches YAML-Verzeichnis für die Wissensbasis, zum Beispiel schreibgeschützt eingebunden (`-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb`). |
| `EKTE_NO_USER_KB` | nicht gesetzt | `1` ignoriert die Einträge in der Wissensbasis, die Sie in der Oberfläche hinzugefügt haben (`kb.db`). |
| `EKTE_ALLOWED_HOSTS` | nicht gesetzt | Kommagetrennte zusätzliche Hostnamen, auf die die Oberfläche antwortet, falls Sie sie unter einem anderen Namen als `localhost`/`127.0.0.1` erreichen. |

**Umstieg vom zing-Image.** Benennen Sie `-e ZING_*`-Optionen in `EKTE_*` um.
ekte liest eine `ZING_*`-Variable weiterhin, wenn ihr `EKTE_*`-Name nicht gesetzt
ist, aber das Image setzt `EKTE_CONTAINER`, `EKTE_HOST`, `EKTE_PORT` und
`EKTE_DATA_DIR` selbst, sodass ein altes `ZING_HOST`, `ZING_PORT` oder
`ZING_DATA_DIR` im Container keine Wirkung hat. Das Daten-Volume bleibt unter
`/data`, und der nicht privilegierte Benutzer behält die uid 10001, sodass ein
bestehendes `zing-data`-Volume unverändert eingebunden werden kann
(`-v zing-data:/data`). Der `ZING_*`-Rückfall ist veraltet und wird in ekte
1.0.0 entfernt (siehe [Stabilitätsrichtlinie](../../../reference/stability.md#deprecation-zing)).

## Was die Oberfläche schützt

- **Host-Zulassungsliste.** Anfragen, deren `Host`-Header nicht `localhost`,
  `127.0.0.1`, `[::1]` ist oder in `EKTE_ALLOWED_HOSTS` steht, werden abgelehnt.
  Das verhindert DNS-Rebinding, bei dem eine Website ihre eigene Domain auf
  `127.0.0.1` zeigen lässt, um mit lokalen Servern zu sprechen. Der Port wird
  nicht geprüft, daher funktioniert jeder veröffentlichte Host-Port.
- **Origin- und JSON-Prüfung.** Zustandsändernde Anfragen von einem anderen
  Origin werden abgelehnt, und Anfragekörper müssen `application/json` sein,
  sodass eine andere Website keine Formulare an die lokale API senden kann.
- **Sicherheits-Header.** Die Oberfläche kann nicht in andere Websites
  eingebettet werden (`X-Frame-Options`, `frame-ancestors`), und kein Referrer
  verlässt die Seite.
- **Verschlüsselte Überwachungsschlüssel.** Gespeicherte API-Schlüssel werden mit
  einem Hauptschlüssel verschlüsselt, der nie auf das Daten-Volume geschrieben
  wird, sodass eine Kopie des Volumes keinen API-Schlüssel preisgibt. Ohne
  `EKTE_SECRET_KEY` zeigt die Seite Überwachung den Schlüssel einmal bei seiner
  Erzeugung an und fragt nach jedem Containerstart danach; Überwachungen, die
  ihn brauchen, warten so lange. Für unbeaufsichtigte Neustarts übergeben Sie
  ihn als Docker-Secret (der Server hält ihn im Speicher; betreiben Sie einen
  Serverprozess je Daten-Volume):

  ```bash
  # der Schlüssel, den die Seite Überwachung angezeigt hat, oder ein neuer: ekte secret rotate
  docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data \
    -v "$PWD/ekte_key:/run/secrets/ekte_key:ro" \
    -e EKTE_SECRET_KEY=file:/run/secrets/ekte_key ekte
  ```

  Ein `EKTE_SECRET_KEY`, der nicht der Schlüssel der gespeicherten API-Schlüssel
  ist, wird abgelehnt (die Oberfläche sagt es). Wechseln Sie ihn mit
  `ekte secret rotate`; ein verlorener Schlüssel lässt sich nur auf der Seite
  Überwachung zurücksetzen, wobei die gespeicherten API-Schlüssel verworfen werden.
- **Daten nur für den Besitzer.** Das Datenverzeichnis wird mit `0700` angelegt
  und jede Datenbankdatei mit `0600`; das Image läuft als nicht privilegierter
  Benutzer.
