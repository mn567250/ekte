# Si vienes de zing

> [🇬🇧 English](../../../guide/migrating-from-zing.md) · [🇨🇳 中文](../../zh-CN/guide/migrating-from-zing.md) · [🇫🇷 Français](../../fr/guide/migrating-from-zing.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/migrating-from-zing.md) · [🇮🇹 Italiano](../../it/guide/migrating-from-zing.md) · [🇩🇪 Deutsch](../../de/guide/migrating-from-zing.md) · [🇳🇴 Norsk](../../nb/guide/migrating-from-zing.md)

ekte continúa [zing](https://github.com/cenbonew/zing) (su última versión fue la
0.11.0) con un nombre nuevo. Qué cambia en una instalación existente:

- **Paquete y comando.** `pip install ekte` (antes `zing-audit`), el comando
  `ekte` (antes `zing`), el paquete de Python `ekte`. Los extras conservan su
  nombre, p. ej. `pip install 'ekte[web]'`. Los dos paquetes no comparten
  comando ni módulo, así que `zing-audit` puede seguir instalado junto a ekte.
- **Variables de entorno.** `EKTE_*` sustituye a `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). Una variable `ZING_*` antigua sigue
  funcionando mientras su nombre `EKTE_*` no esté definido; ekte la menciona una
  vez en stderr.
- **Directorio de datos.** En su primera ejecución, ekte copia `~/.zing` a
  `~/.ekte` (historial, monitores, base de conocimiento) si `~/.ekte` aún no
  existe, y desde entonces trabaja solo con `~/.ekte`. `~/.zing` queda tal cual,
  para zing si todavía se ejecuta; bórralo tú cuando ya no lo necesites. Un
  directorio indicado con `EKTE_DATA_DIR`, `ZING_DATA_DIR` o `--data-dir` se usa
  tal como está.
- **Interfaz web.** Se conservan el idioma, el tema y los filtros, y una clave
  maestra guardada en el gestor de contraseñas del navegador. La interfaz clásica
  de zing ya no existe: sus direcciones (`/tools`, `/console`) abren la página de auditoría (`/`).
- **Informes y sondeos.** Los informes, los webhooks y los nombres de archivo
  dicen `ekte` (p. ej. `"tool": "ekte"`, `ekte-report.json`), igual que los
  sondeos enviados a los relays. Los scripts que buscan `zing` en ellos deben
  actualizarse.
- **Calendario.** Toda la capa de compatibilidad (la lectura de `ZING_*`, la copia de `~/.zing`, el traspaso de ajustes del navegador, cookies y la clave maestra guardada, y las direcciones de la interfaz clásica) está obsoleta y se elimina en ekte **1.0.0** (1.0.0rc1 es la primera versión sin ella). Hasta entonces cada parte sigue funcionando y su aviso nombra esta versión; las antiguas direcciones de página `/v2/…` también redirigen hasta 1.0.0. ekte nunca borra un `~/.zing` antiguo, tampoco cuando se elimina la copia.
