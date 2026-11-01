# Privacidad y datos locales

> [🇬🇧 English](../../../guide/privacy.md) · [🇨🇳 中文](../../zh-CN/guide/privacy.md) · [🇫🇷 Français](../../fr/guide/privacy.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/privacy.md) · [🇮🇹 Italiano](../../it/guide/privacy.md) · [🇩🇪 Deutsch](../../de/guide/privacy.md) · [🇳🇴 Norsk](../../nb/guide/privacy.md)

- **Solo local.** `ekte serve` escucha solo en loopback (`127.0.0.1`, `::1`,
  `localhost`), responde solo a esos nombres de host y rechaza peticiones entre
  sitios; no tiene inicio de sesión porque nada fuera de tu máquina puede
  alcanzarlo. ekte solo contacta los endpoints que configuras (objetivo,
  referencia, juez, webhooks); no descarga nada en tiempo de ejecución, ni
  siquiera archivos de tokenizer.
- **Claves.** Los informes y el historial solo guardan una huella de una clave
  API. Las claves de los monitores se guardan cifradas en `watches.db`; la clave
  maestra que las descifra nunca se escribe en el directorio de datos (la
  guardas tú, consulta [Monitorización](monitoring.md)), así que una copia del
  directorio no revela ninguna clave API. Aun así, solo tú tienes acceso al
  directorio.
- **Directorio de datos.** `~/.ekte` (o `EKTE_DATA_DIR`), creado con `0700` y
  archivos con `0600`: `history.db` (historial de auditorías), `watches.db`
  (monitores, con sus claves cifradas) y `kb.db` (tus entradas de la base de
  conocimiento). Borra el directorio para eliminarlo todo.
  `ekte data-dir` muestra dónde está; `--data-dir RUTA` elige otro para una
  ejecución, p. ej. `ekte serve --data-dir .` guarda las bases de datos en la
  carpeta actual. Son archivos SQLite normales que puedes abrir para tus
  propios análisis (mejor solo lectura mientras ekte se ejecuta). No hagas
  commit de `watches.db` si esa carpeta es un repositorio.
  `history_metrics` guarda una fila de valores medidos por ejecución y
  `history_requests` cada registro de petición (guardado ahí una sola vez, no
  dentro de cada informe).

## Uso responsable

ekte es una ayuda de auditoría de caja negra. **No puede probar**:

- que un proveedor guarde tus prompts o entrene con ellos,
- que siempre enrute a un único modelo exacto (los relays pueden enrutar de forma probabilística),
- un fraude de facturación más allá de lo que la estimación independiente de tokens puede sugerir.

Usa los informes para tu propia diligencia debida. **No acuses públicamente a un
proveedor** basándote en una sola ejecución sin revisar el tamaño de la muestra,
la configuración de costes y la legislación local. Ejecuta `ekte compare` contra
una referencia de confianza antes de sacar conclusiones firmes.
