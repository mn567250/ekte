# Monitorización

> [🇬🇧 English](../../../guide/monitoring.md) · [🇨🇳 中文](../../zh-CN/guide/monitoring.md) · [🇫🇷 Français](../../fr/guide/monitoring.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/monitoring.md) · [🇮🇹 Italiano](../../it/guide/monitoring.md) · [🇩🇪 Deutsch](../../de/guide/monitoring.md) · [🇳🇴 Norsk](../../nb/guide/monitoring.md)

Un relay puede servir el modelo real hoy y cambiarlo en silencio la semana que
viene. `ekte watch` vuelve a auditar según un calendario, guarda cada ejecución
en el historial y avisa a un webhook cuando el riesgo cruza un umbral o
**empeora** respecto a la ejecución anterior.

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang es                                     # o --once para cron
```

Las alertas se formatean para **Slack / Feishu / DingTalk / JSON genérico**,
detectados automáticamente a partir de la URL del webhook, y se redactan en el
idioma de las alertas — inglés por defecto; `--alert-lang en|zh|fr|es|pt|it|de|nb`.
La carga JSON genérica mantiene neutrales sus claves y valores de máquina
(`risk_level`, `score`, …), traduce los legibles (`text`, `headline`,
`key_findings`) e indica el `language`.

**En la interfaz web**, `ekte serve` ejecuta los mismos monitores en un
planificador en segundo plano dentro del proceso del servidor, guarda cada
ejecución en el **Historial** y envía las mismas alertas por webhook. Abre una ejecución en el **Historial** y elige **Programar
como monitor**. ekte copia la configuración de esa ejecución (relay, modelo,
modelo declarado, proveedor, suite, dimensiones personalizadas) en un monitor
en pausa de la página **Monitores**; allí fija su intervalo y su clave API (el
Historial nunca guarda claves) y actívalo. Intervalo, clave, **Umbral de
alerta**, webhooks e **Idioma de las alertas** se editan directamente en cada
monitor. Al pulsar el nombre de un monitor su tarjeta se pliega a nombre,
estado y última ejecución (**Contraer todo** / **Expandir todo** sobre la
lista; se recuerda por navegador), y el panel de filtros (búsqueda, estado,
último riesgo, tipo de endpoint, relay, suite) acota una lista larga como en
el **Historial**.

Cada monitor tiene su propio idioma de alertas (por defecto, el de la interfaz),
puede ejecutarse ahora, pausarse o eliminarse, y queda anclado al perfil de la
base de conocimiento con el que se creó hasta que lo vuelvas a anclar.

Los monitores a los que les toca ejecutarse lo hacen a la vez, cada uno como su
propia auditoría, pero nunca más de una auditoría a la vez por host de relay y
como máximo `EKTE_MAX_PARALLEL_AUDITS` en total; una ejecución espera a que haya
un hueco libre (una auditoría que lances a mano también puede quedar en cola
detrás de los monitores en curso). La hora de una ejecución es la de inicio de
su auditoría, tras cualquier espera. La comprobación de regresiones compara con
la ejecución guardada más reciente del mismo relay y modelo, por muchas otras
ejecuciones que se hayan guardado desde entonces. Los webhooks de alerta de una
ejecución se envían a la vez, así que uno lento o caído no retrasa a los demás.
Las claves se guardan cifradas en tu directorio de datos local y nunca se devuelven
al navegador.

**Almacenamiento de claves API.** Por defecto ekte **no guarda** las claves API
de los monitores: una clave que introduces permanece solo en la memoria de
`ekte serve` y nunca se escribe en el disco. Tras un reinicio, la página
**Monitores** indica qué monitores necesitan de nuevo su clave; esperan (sin
ejecución fallida ni alerta) hasta que la introduzcas. Los monitores sin clave y
las referencias `env:`/`file:` siguen funcionando. Para que las claves
sobrevivan a los reinicios, elige **Guardar cifradas en este equipo** en
**Almacenamiento de claves API** de la página **Monitores**: las claves se
guardan entonces en `watches.db`, cifradas con una clave maestra. Volver atrás
mueve las claves guardadas a la memoria y las borra de `watches.db`. El aviso de
la página muestra el modo activo, pide confirmación antes de cambiar e informa de
lo que se movió. Una instalación que ya guardaba claves cifradas, o que define `EKTE_SECRET_KEY`,
las sigue guardando hasta que cambies.

**Clave maestra.** Las claves API de los monitores se cifran con una clave
maestra que ekte nunca escribe en disco. La primera vez que guardas una clave
API, la página **Monitores** la crea y la muestra una sola vez: cópiala o
descárgala, guárdala en un gestor de contraseñas (tu navegador puede guardarla)
y pégala de nuevo para confirmar. Tras cada reinicio de `ekte serve` la página
vuelve a pedirla (el navegador puede rellenarla); hasta entonces, los monitores
que la necesitan esperan, mientras que los monitores sin clave o con claves
`env:`/`file:` siguen ejecutándose. La barra de estado de la página también
ofrece **Bloquear**, **Rotar** y **¿Olvidaste la clave?** (descarta las claves
API cifradas para que puedas volver a introducirlas). Para uso desatendido o en
Docker, pasa la clave como `EKTE_SECRET_KEY` (consulta
[Docker](docker.md)); `ekte secret status | export | rotate` la
gestionan desde la línea de comandos.
