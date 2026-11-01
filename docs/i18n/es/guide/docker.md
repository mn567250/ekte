# Ejecutar la interfaz web en Docker

> [🇬🇧 English](../../../guide/docker.md) · [🇨🇳 中文](../../zh-CN/guide/docker.md) · [🇫🇷 Français](../../fr/guide/docker.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/docker.md) · [🇮🇹 Italiano](../../it/guide/docker.md) · [🇩🇪 Deutsch](../../de/guide/docker.md) · [🇳🇴 Norsk](../../nb/guide/docker.md)

`ekte serve` es una herramienta de un solo usuario sin inicio de sesión. Fuera de
un contenedor solo escucha en loopback (`127.0.0.1`, `::1`, `localhost`) y
rechaza cualquier otra dirección de escucha. Un contenedor es la única excepción:
el servidor tiene que escuchar en las interfaces propias del contenedor para que
la publicación de puertos de Docker llegue a él.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# abre http://localhost:8000
```

**Publica siempre en `127.0.0.1`** (`-p 127.0.0.1:8000:8000`, no `-p 8000:8000`).
Un simple `-p 8000:8000` publica la interfaz — y cada clave API que se escriba en
ella o se guarde en un monitor — en tu red.

## Variables de entorno

| Variable | Valor por defecto | Para qué sirve |
|---|---|---|
| `EKTE_CONTAINER` | sin definir (`1` en la imagen) | Permite escuchar fuera de loopback. ekte comprueba además que de verdad se ejecuta en un contenedor (`/.dockerenv`, `/run/.containerenv` o Kubernetes); definirla en un host normal no abre el servidor. |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` en la imagen) | Dirección de escucha. Todo lo que no sea loopback requiere `EKTE_CONTAINER=1`. `--host` tiene prioridad sobre ella. |
| `EKTE_PORT` | `8000` | Puerto dentro del contenedor. `--port` tiene prioridad sobre ella. |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` en la imagen) | Historial de auditorías, monitores (incluidas sus claves API) y tus propias entradas de la base de conocimiento. Monta aquí un volumen para conservarlos. |
| `EKTE_SECRET_KEY` | sin definir | Clave maestra que cifra las claves API guardadas de los monitores: la clave que te mostró la página **Monitores** (o `ekte secret rotate`), o `file:/run/secrets/ekte_key` / `env:VAR`. Sin definir, introduces la clave en la página **Monitores** tras cada arranque del contenedor. Nunca se guarda en `EKTE_DATA_DIR`. Definirla en un directorio de datos nuevo selecciona el almacenamiento cifrado de claves; sin ella, las claves API de los monitores no se guardan en absoluto y hay que volver a introducirlas tras cada arranque del contenedor. Consulta más abajo. |
| `EKTE_KB_DIR` | sin definir | Directorio YAML adicional de la base de conocimiento, montado por ejemplo en solo lectura (`-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb`). |
| `EKTE_NO_USER_KB` | sin definir | `1` ignora las entradas de la base de conocimiento que añadiste en la interfaz (`kb.db`). |
| `EKTE_ALLOWED_HOSTS` | sin definir | Nombres de host adicionales, separados por comas, a los que responde la interfaz, si accedes a ella con otro nombre que `localhost`/`127.0.0.1`. |

**Si vienes de la imagen de zing.** Renombra las opciones `-e ZING_*` a `EKTE_*`.
ekte sigue leyendo una variable `ZING_*` cuyo nombre `EKTE_*` no está definido,
pero la imagen define ella misma `EKTE_CONTAINER`, `EKTE_HOST`, `EKTE_PORT` y
`EKTE_DATA_DIR`, así que un antiguo `ZING_HOST`, `ZING_PORT` o `ZING_DATA_DIR`
no tiene efecto en el contenedor. El volumen de datos sigue en `/data` y el
usuario sin privilegios conserva el uid 10001, así que un volumen `zing-data`
existente puede montarse tal cual (`-v zing-data:/data`). La alternativa
`ZING_*` está obsoleta y se elimina en ekte 1.0.0 (consulta la
[política de estabilidad](../../../reference/stability.md#deprecation-zing)).

## Qué protege la interfaz

- **Lista de hosts permitidos.** Se rechazan las peticiones cuya cabecera `Host`
  no sea `localhost`, `127.0.0.1`, `[::1]` ni figure en `EKTE_ALLOWED_HOSTS`.
  Esto impide el DNS rebinding, en el que un sitio web apunta su propio dominio
  a `127.0.0.1` para hablar con servidores locales. El puerto no se comprueba,
  así que cualquier puerto publicado en el host funciona.
- **Comprobaciones de origen y JSON.** Se rechazan las peticiones que modifican
  el estado desde otro origen, y los cuerpos de las peticiones deben ser
  `application/json`, así que otro sitio web no puede enviar formularios a la
  API local.
- **Cabeceras de seguridad.** Otros sitios no pueden incrustar la interfaz en un
  marco (`X-Frame-Options`, `frame-ancestors`), y ningún referrer sale de la
  página.
- **Claves de monitores cifradas.** Las claves API guardadas se cifran con una
  clave maestra que nunca se escribe en el volumen de datos, así que una copia
  del volumen no revela ninguna clave API. Sin `EKTE_SECRET_KEY`, la página
  **Monitores** muestra la clave una vez al crearla y la pide tras cada arranque
  del contenedor; los monitores que la necesitan esperan hasta entonces. Para
  reinicios desatendidos, pásala como secreto de Docker (el servidor la mantiene
  en memoria; ejecuta un solo proceso de servidor por volumen de datos):

  ```bash
  # la clave que te mostró la página Monitores, o una nueva: ekte secret rotate
  docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data \
    -v "$PWD/ekte_key:/run/secrets/ekte_key:ro" \
    -e EKTE_SECRET_KEY=file:/run/secrets/ekte_key ekte
  ```

  Se rechaza una `EKTE_SECRET_KEY` que no sea la clave que usan las claves API
  guardadas (la interfaz lo indica). Rótala con `ekte secret rotate`; una clave
  perdida solo puede restablecerse en la página **Monitores**, lo que descarta
  las claves API guardadas.
- **Datos solo para el propietario.** El directorio de datos se crea con `0700`
  y cada archivo de base de datos con `0600`; la imagen se ejecuta como un
  usuario sin privilegios.
