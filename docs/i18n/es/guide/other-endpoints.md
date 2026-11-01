# Auditorías de embeddings, rerank, imagen y audio

> [🇬🇧 English](../../../guide/other-endpoints.md) · [🇨🇳 中文](../../zh-CN/guide/other-endpoints.md) · [🇫🇷 Français](../../fr/guide/other-endpoints.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/other-endpoints.md) · [🇮🇹 Italiano](../../it/guide/other-endpoints.md) · [🇩🇪 Deutsch](../../de/guide/other-endpoints.md) · [🇳🇴 Norsk](../../nb/guide/other-endpoints.md)

Estos endpoints devuelven vectores, clasificaciones, imágenes o audio en lugar de
chat, así que ekte los audita con sondas específicas en lugar de los prompts de
chat. Cada uno imprime un veredicto y admite `--json` y `--fail-on-risk`.

## Tipo de endpoint (superficie), monitores de embeddings y rerank

Cada auditoría, fila del historial y monitor tiene un **tipo de endpoint**
(`surface`): `chat` (por defecto), `embedding` o `rerank`. Es independiente de la
suite. Las auditorías de embeddings y rerank pasan por el mismo runner, la misma
puntuación (0–100, A–F), el historial, la analítica y los monitores que las de
chat; solo cambian los detectores. El historial y la analítica filtran por tipo de
endpoint, y la analítica muestra solo las métricas que aplican.

Para vigilar un endpoint de embeddings o rerank, audítalo en la página
**Auditoría** (elige **Embeddings** o **Reordenación** en el selector de tipo de
endpoint) y elige
**Monitorizar**, o **Programar como monitor** en su fila
del historial. El monitor repite la auditoría según su calendario, con la misma
fijación de la base de conocimiento, el mismo umbral de alerta y las mismas
alertas de regresión que un monitor de chat, y comprueba la **deriva** frente a
su ejecución anterior (los vectores de una sonda de embeddings, la clasificación y
las puntuaciones de una sonda de rerank). La dimensión declarada de un monitor de
embeddings se puede cambiar en su tarjeta (vacía o 0: de la base de
conocimiento). Las sondas de velocidad (embeddings: latencia, arranque en frío,
entradas/s, escalado por lotes; rerank: latencia, arranque en frío, documentos/s,
4 frente a 32 documentos) solo se ejecutan en las suites deep, full o custom, o en
standard con una referencia.

## Embeddings y rerank

```bash
# La dimensión de vector esperada se resuelve desde la base de conocimiento para el modelo declarado.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# O indicar directamente la dimensión esperada:
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: una sonda integrada de respuesta conocida — un reranker auténtico debe poner
# primero el documento evidentemente relevante.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Más a fondo: añade la sonda de velocidad de rerank; --no-save deja la ejecución fuera del historial.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# Ver antes las comprobaciones y las llamadas estimadas, sin enviar ninguna petición:
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` comprueba la conectividad, la **sonda de respuesta conocida** (el
documento obviamente relevante debe quedar primero), el campo `model` devuelto,
el determinismo (la misma consulta dos veces da la misma clasificación y las
mismas puntuaciones) y la **deriva de la clasificación** frente a la ejecución
guardada anterior. `ekte embed` y `ekte rerank` aceptan `--suite`,
`--save/--no-save` (se guarda por defecto, para que la siguiente ejecución tenga
una referencia de deriva) y `--dry-run`.

`embed` comprueba la conectividad, la **coincidencia de dimensión** (longitud del
vector devuelto frente a la dimensión nativa del modelo declarado — la señal
principal de «gato por liebre»: un relay que declara `text-embedding-3-large` de
3072-d pero devuelve 1024-d sirve un sustituto), el determinismo (misma entrada →
coseno ≈ 1), la distinción (entradas sin relación → coseno claramente inferior a
1) y el campo `model` devuelto. Perfiles integrados: OpenAI
`text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Ambos están también en la interfaz web: empiezan en la página **Auditoría** con
el selector de tipo de endpoint (**Embeddings**, **Reordenación**). La auditoría de rerank usa
siempre las sondas integradas, para que cada ejecución siga siendo comparable para
la deriva y la monitorización.

## Generación de imagen y audio (TTS)

Generación de imágenes (`POST /v1/images/generations`) y texto a voz
(`POST /v1/audio/speech`), decodificados solo con la biblioteca estándar de
Python — dimensiones de imagen a partir de los bytes de cabecera
(PNG/JPEG/GIF/WebP), duración WAV mediante `wave`.

```bash
# ¿Un relay que declara DALL·E 3 devuelve de verdad el 1792x1024 pedido? Una imagen
# reducida o de tamaño incorrecto (o fuera de los tamaños nativos del modelo declarado,
# según la base de conocimiento) es la señal principal de «gato por liebre».
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# ¿Un relay que declara tts-1-hd devuelve audio real cuya duración crece con la entrada
# (no un marcador fijo, ni HTML/JSON disfrazado de audio)?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
```

`image` comprueba la conectividad, un formato válido y decodificable, la
**coincidencia de tamaño** (ancho × alto decodificados frente a la petición y a
los tamaños nativos del modelo declarado — FAIL/HIGH si no coinciden), la
distinción (dos prompts → imágenes distintas, para descubrir un marcador fijo),
el número y el campo `model`. `audio` comprueba la conectividad, la validez del
contenedor/formato, que se respete el formato, una duración no trivial que crece
con la entrada, la distinción y el campo `model`. La base de conocimiento incluye
OpenAI DALL·E 2/3, gpt-image-1, tts-1/tts-1-hd/gpt-4o-mini-tts y perfiles de
imagen/TTS de Qwen.
