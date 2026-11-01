# Auditorias de embeddings, rerank, imagem e áudio

> [🇬🇧 English](../../../guide/other-endpoints.md) · [🇨🇳 中文](../../zh-CN/guide/other-endpoints.md) · [🇫🇷 Français](../../fr/guide/other-endpoints.md) · [🇪🇸 Español](../../es/guide/other-endpoints.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/other-endpoints.md) · [🇩🇪 Deutsch](../../de/guide/other-endpoints.md) · [🇳🇴 Norsk](../../nb/guide/other-endpoints.md)

Estes endpoints devolvem vetores, classificações, imagens ou áudio em vez de chat,
por isso o ekte audita-os com sondas dedicadas em vez dos prompts de chat. Cada um
imprime um veredito e suporta `--json` e `--fail-on-risk`.

## Tipo de endpoint (superfície), monitores de embeddings e rerank

Cada auditoria, linha do histórico e monitor tem um **tipo de endpoint**
(`surface`): `chat` (por omissão), `embedding` ou `rerank`. É independente da
suite. As auditorias de embeddings e rerank passam pelo mesmo runner, a mesma
pontuação (0–100, A–F), o histórico, a análise e os monitores das auditorias de
chat; só os detetores mudam. O histórico e a análise filtram por tipo de endpoint,
e a análise mostra apenas as métricas aplicáveis.

Para monitorizar um endpoint de embeddings ou rerank, audite-o na página
**Auditoria** (escolha **Embeddings** ou **Reordenação** no seletor de tipo de
endpoint) e escolha
**Monitorar**, ou **Agendar como monitor** na sua linha
do histórico. O monitor repete a auditoria segundo o agendamento, com a mesma
fixação da base de conhecimento, o mesmo limiar de alerta e os mesmos alertas de
regressão de um monitor de chat, e verifica a **deriva** face à sua execução
anterior (os vetores de uma sonda de embeddings, a classificação e as pontuações
de uma sonda de rerank). A dimensão declarada de um monitor de embeddings altera-se
no seu cartão (vazia ou 0: da base de conhecimento). As sondas de velocidade
(embeddings: latência, arranque a frio, entradas/s, escala por lotes; rerank:
latência, arranque a frio, documentos/s, 4 contra 32 documentos) só correm nas
suites deep, full ou custom, ou em standard com uma referência.

## Embeddings e rerank

```bash
# A dimensão de vetor esperada é obtida da base de conhecimento para o modelo declarado.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Ou indicar diretamente a dimensão esperada:
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: uma sonda integrada de resposta conhecida — um reranker genuíno tem de pôr
# em primeiro o documento obviamente relevante.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Mais a fundo: junta a sonda de velocidade do rerank; --no-save deixa a execução fora do histórico.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# Ver primeiro as verificações e as chamadas estimadas, sem enviar pedidos:
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` verifica a conectividade, a **sonda de resposta conhecida** (o documento
obviamente relevante tem de ficar em primeiro), o campo `model` devolvido, o
determinismo (a mesma consulta duas vezes dá a mesma classificação e as mesmas
pontuações) e a **deriva da classificação** face à execução guardada anterior.
`ekte embed` e `ekte rerank` aceitam `--suite`, `--save/--no-save` (guardado por
omissão, para que a execução seguinte tenha uma referência de deriva) e
`--dry-run`.

`embed` verifica a conectividade, a **correspondência de dimensão** (comprimento
do vetor devolvido face à dimensão nativa do modelo declarado — o principal sinal
de «gato por lebre»: um relay que declara `text-embedding-3-large` de 3072-d mas
devolve 1024-d serve um substituto), o determinismo (mesma entrada → cosseno ≈
1), a distinção (entradas sem relação → cosseno claramente abaixo de 1) e o campo
`model` devolvido. Perfis integrados: OpenAI `text-embedding-3-small` (1536),
`text-embedding-3-large` (3072), `text-embedding-ada-002` (1536), Qwen
`text-embedding-v3`/`-v4` (1024).

Ambos estão também na interface web: começam na página **Auditoria** com o
seletor de tipo de endpoint (**Embeddings**, **Reordenação**). A auditoria de rerank usa sempre as sondas
integradas, para que cada execução continue comparável para a deriva e a
monitorização.

## Geração de imagem e áudio (TTS)

Geração de imagens (`POST /v1/images/generations`) e texto para voz
(`POST /v1/audio/speech`), descodificados apenas com a biblioteca padrão do
Python — dimensões da imagem a partir dos bytes de cabeçalho (PNG/JPEG/GIF/WebP),
duração WAV através de `wave`.

```bash
# Um relay que declara DALL·E 3 devolve mesmo o 1792x1024 pedido? Uma imagem reduzida
# ou de tamanho errado (ou fora dos tamanhos nativos do modelo declarado, segundo a
# base de conhecimento) é o principal sinal de «gato por lebre».
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Um relay que declara tts-1-hd devolve áudio real cuja duração cresce com a entrada
# (não um marcador fixo, nem HTML/JSON disfarçado de áudio)?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
```

`image` verifica a conectividade, um formato válido e descodificável, a
**correspondência de tamanho** (largura × altura descodificadas face ao pedido e
aos tamanhos nativos do modelo declarado — FAIL/HIGH se não corresponderem), a
distinção (dois prompts → imagens diferentes, para desmascarar um marcador fixo),
o número e o campo `model`. `audio` verifica a conectividade, a validade do
contentor/formato, que o formato é respeitado, uma duração não trivial que cresce
com a entrada, a distinção e o campo `model`. A base de conhecimento inclui
OpenAI DALL·E 2/3, gpt-image-1, tts-1/tts-1-hd/gpt-4o-mini-tts e perfis de
imagem/TTS da Qwen.
