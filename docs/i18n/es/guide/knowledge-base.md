# Base de conocimiento

> [🇬🇧 English](../../../guide/knowledge-base.md) · [🇨🇳 中文](../../zh-CN/guide/knowledge-base.md) · [🇫🇷 Français](../../fr/guide/knowledge-base.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/knowledge-base.md) · [🇮🇹 Italiano](../../it/guide/knowledge-base.md) · [🇩🇪 Deutsch](../../de/guide/knowledge-base.md) · [🇳🇴 Norsk](../../nb/guide/knowledge-base.md)

ekte juzga un relay según el **perfil** del modelo que declara: ventana de
contexto nativa, salida máxima, fecha de corte del conocimiento, tokenizer,
capacidades, palabras clave de identidad y huellas de comportamiento. Los
perfiles integrados cubren OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM
y Moonshot (`ekte kb` los lista). Hay tres capas; las posteriores prevalecen:

1. Perfiles **integrados**, un archivo YAML por proveedor en
   [`ekte/knowledge/data/`](../../../../ekte/knowledge/data).
2. **Un directorio con tus propios archivos YAML**: `--kb-dir ./my-profiles`
   (repetible) o `EKTE_KB_DIR`.
3. **Tus entradas** (`kb.db` en el directorio de datos), añadidas sin archivos
   YAML ni instalación editable:
   - en la página **Conocimiento** de la interfaz web (`/kb`), con una pestaña
     para **Modelos**, **Proveedores** y **Relays**. Cada pestaña lista el conjunto
     completo —incluidos, `EKTE_KB_DIR` y los tuyos (marcados **Tuyo**)— con un
     filtro, un interruptor por elemento y un formulario **Añadir …**: **Añadir un
     modelo** → **Copiar el prompt de investigación** en el asistente de IA que
     prefieras, subir o pegar el YAML con el que responde y después **Comprobar y
     guardar**; **Añadir un proveedor** acepta YAML de proveedor del mismo modo;
     **Añadir un relay** pide un nombre y una URL base. **¿Qué perfil usa un ID de
     modelo?** muestra cómo se resuelve un id; tus entradas se pueden exportar
     como YAML;
   - en la página **Auditoría** de la interfaz web:
     **Guardar en la base** conserva el nombre y la URL base de un relay (una
     entrada de proveedor sin modelos), que aparece en **Conocimiento → Relays**;
   - en la línea de comandos: `ekte kb-prompt <model>`, `ekte kb-import <file>`
     (añade `--check` para solo comprobarlo) y `ekte kb-export`.

Antes de guardar una entrada, ekte la comprueba: esquema y límites, expresiones
regulares peligrosas, cada prompt que enviaría e ids de modelo que se
resolverían a otro perfil. Un modelo tuyo con el id de uno integrado lo sustituye
(se indica que lo *oculta*), pero nunca cambia los ajustes propios de un
proveedor integrado; las huellas se fusionan por id. Desactivar un modelo,
proveedor o relay incluido en la página **Conocimiento** también se guarda en
`kb.db`: un id de modelo desactivado ya no se resuelve y un proveedor desactivado
se lleva sus modelos y URL base. `ekte check` y `ekte serve` usan exactamente los
mismos perfiles; `--no-user-kb` (o `EKTE_NO_USER_KB=1`) deja fuera tus entradas e
interruptores.

Un modelo con `identity_keywords` vacío no se guarda así: ekte completa sus
propias palabras de marca a partir de los nombres del proveedor y del modelo
(por ejemplo `glm` y `z.ai`) y muestra una
advertencia para que las revises, ya que sin ellas la comprobación de identidad
podría tomar a su propio fabricante por una marca rival. El prompt de
investigación se las pide expresamente al asistente de IA.

Cada informe registra el perfil contra el que auditó (`knowledge`: proveedor,
modelo, cómo se resolvió el id, su origen y una instantánea completa con su hash
de contenido), de modo que un informe sigue siendo verificable después de que
cambie la base de conocimiento.
