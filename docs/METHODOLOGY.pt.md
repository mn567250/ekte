# zing — Metodologia

> [🇬🇧 English](METHODOLOGY.md) · [🇨🇳 中文](METHODOLOGY.zh-CN.md) · [🇫🇷 Français](METHODOLOGY.fr.md) · [🇪🇸 Español](METHODOLOGY.es.md) · **🇵🇹 Português** · [🇮🇹 Italiano](METHODOLOGY.it.md) · [🇩🇪 Deutsch](METHODOLOGY.de.md)

Este documento explica como o **zing** chega ao seu veredito: que sondas de
caixa-preta cada detector envia, como os seus resultados se tornam pontos, como
os pontos se tornam pontuações de dimensão e uma pontuação global, e como é
decidido o veredito de risco. Descreve a implementação atual; cada tabela de
pontuação abaixo é a escala publicada do detector (`SCALE` em
`zing/detectors/*.py`), com a mesma redação que a interface web mostra em
**Escala de pontuação**.

> O zing fornece **evidências de caixa-preta de desvios e riscos, não uma prova
> criptográfica de fraude.** Consulte [Limites e utilização responsável](#limites-e-utilização-responsável).

---

## Posição de princípio

Um relay pode, por razões legítimas, desviar-se, atualizar snapshots, partilhar
capacidade ou fazer buffer de um upstream que não suporta streaming. Por isso o
zing trata cada sinal isolado como um *indicador de risco*, nunca como um
veredito: as constatações assentam em evidências, são formuladas com cautela, e
um resultado ambíguo fica **inconclusivo** em vez de ser forçado a aprovado ou
falha. O veredito de risco só chega a «alto» com evidências sólidas de
gravidade alta, e a confirmação mais forte é sempre o **modo de comparação**
(`zing compare`): executar as mesmas sondas, ao mesmo tempo, contra uma
*referência de confiança do modelo declarado*.

## Como o zing pontua

### Pontuação do detector

Cada detector publica a sua **escala de pontuação** (`DetectorResult.scoring`,
construída com `zing/detectors/scale.py`): cada resultado possível de cada uma
das suas verificações, com estado, gravidade e efeito na pontuação. Cada
constatação regista o `outcome` atingido, pelo que relatório e comportamento
não podem divergir. Uma escala usa um de dois métodos:

- **Média das verificações** (`Scale`, método `mean_of_checks`): cada
  verificação dá pontos; a pontuação do detector é a média das verificações
  contabilizadas. Um resultado marcado **Não contabilizado** (tipicamente uma
  verificação inconclusiva) não sobe nem desce a pontuação.
- **Deduções** (`DeductionScale`, método `deductions`): a pontuação começa em
  100, as constatações descontam pontos (`Finding.deduction`) e/ou limitam-na
  (`Finding.cap`); vale o teto mais baixo.

Uma verificação *parametrizada* aplica um mesmo conjunto de linhas a muitos
sujeitos (por exemplo, cada atributo da resposta): cada sujeito é pontuado à
parte, a escala é publicada uma vez por verificação e os relatórios listam os
sujeitos sob a sua verificação.

### Pontuação e estado de uma dimensão

O zing pontua dez dimensões. A pontuação de uma dimensão é a **média com peso
igual das pontuações dos seus detectores**: um detector com muitas verificações
não pesa mais do que um com poucas, e um detector sem pontuação numérica fica de
fora. O seu estado é o pior estado concluído pelos seus detectores, exceto que
uma constatação de gravidade ALTA/CRÍTICA impõe **Falha** e uma constatação de
gravidade MÉDIA eleva **Aprovado** a **Aviso**, seja qual for a pontuação. Cada
relatório regista este cálculo por dimensão (`DimensionScore.breakdown`: a
pontuação de cada detector, se foi contabilizada, e qualquer alteração de estado
com as constatações que a causaram) e mostra-o em **Dimension details**
(Markdown/HTML/PDF) e nas linhas expansíveis de **Verificações por dimensão**
da interface web. Um detector que falha internamente aparece com o estado
**Erro** e nunca interrompe a auditoria.

### Pontuação global, nota e pesos

A **pontuação de saúde global** é a média ponderada das dimensões que
produziram uma pontuação (`DIMENSION_WEIGHTS` em `zing/scoring.py`). Uma
dimensão que não foi executada (fora da suite, ou não selecionada numa execução
`custom`) sai do cálculo e os pesos restantes são renormalizados. A nota é
A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) ou F.

| Dimensão | Id | Peso | Papel |
|---|---|---|---|
| Identidade do modelo | `model_identity` | 21 | núcleo |
| Janela de contexto | `context_window` | 19 | núcleo |
| Capacidades declaradas | `capability` | 13 | núcleo |
| Conformidade do protocolo | `protocol` | 8 |  |
| Faturação e utilização | `billing` | 8 |  |
| Conectividade | `connectivity` | 7 |  |
| Autenticidade do streaming | `streaming` | 6 |  |
| Fiabilidade em concorrência | `reliability` | 6 |  |
| Segurança do transporte | `security` | 6 |  |
| Desempenho | `performance` | 6 |  |

As três **dimensões núcleo** são aquelas cuja falha revela mais diretamente um
«gato por lebre».

### Veredito de risco

O nível de risco depende da **gravidade das constatações**, não da pontuação.
As constatações da dimensão de conectividade ficam de fora: um relay em baixo
ou limitado não pôde ser avaliado, o que não prova que responda outro modelo.

| Risco | Rótulo na interface | Quando |
|---|---|---|
| `inconclusive` | Sinal insuficiente | Nenhuma dimensão núcleo produziu um resultado utilizável (Aprovado, Aviso ou Falha) — por exemplo, relay inacessível, modelo sem perfil ou execução `custom` sem dimensão núcleo |
| `high` | Gato por lebre | Uma constatação CRÍTICA, uma constatação ALTA/CRÍTICA numa dimensão núcleo, ou duas ou mais constatações ALTAS |
| `medium` | Desvios detetados | Exatamente uma constatação ALTA fora das dimensões núcleo, ou uma constatação MÉDIA numa dimensão núcleo |
| `low` | Globalmente fiável | Qualquer outra constatação MÉDIA |
| `clean` | Coerente (provavelmente autêntico) | Nenhum dos casos acima |

### Confiança do veredito

- **Baixa** — o modelo declarado não está na base de conhecimento, ou menos de
  duas dimensões núcleo produziram um resultado utilizável;
- **Média** — pelo menos duas dimensões núcleo produziram um resultado
  utilizável;
- **Alta** — foi usada uma referência *e* as três dimensões núcleo produziram
  um resultado utilizável, ou a confiança era média e o juiz LLM devolveu um
  veredito utilizável.

## Suites, detectores e modos

| Detector | Id | Dimensão | A partir da suite |
|---|---|---|---|
| Conectividade e conclusão básica | `connectivity` | Conectividade | `smoke` |
| Conformidade de compatibilidade com a OpenAI | `protocol` | Conformidade do protocolo | `standard` |
| Suporte aos atributos de pedido | `protocol_request` | Conformidade do protocolo | `standard` |
| Disponibilidade dos atributos de resposta | `protocol_response` | Conformidade do protocolo | `standard` |
| Determinismo e correção da cache | `determinism` | Conformidade do protocolo | `deep` |
| Janela de contexto real e truncagem | `context_window` | Janela de contexto | `deep` |
| Identidade do modelo e impressão digital de degradação | `model_identity` | Identidade do modelo | `standard` |
| Avaliação de qualidade / degradação por um LLM juiz | `quality_judge` | Identidade do modelo | `deep` (só com `--judge`) |
| Verificação das capacidades declaradas | `capability` | Capacidades declaradas | `standard` |
| Verificação da capacidade multimodal (visão) | `vision` | Capacidades declaradas | `deep` |
| Autenticidade do streaming | `streaming` | Autenticidade do streaming | `standard` |
| Auditoria de faturação de tokens | `billing` | Faturação e utilização | `standard` |
| Fiabilidade e latência em concorrência | `reliability` | Fiabilidade em concorrência | `standard` |
| Sinais de transporte e gestão de segredos | `security` | Segurança do transporte | `smoke` |
| Deteção de prompt de sistema injetado | `injected_prompt` | Segurança do transporte | `deep` |
| Integridade das respostas / adulteração | `integrity` | Segurança do transporte | `deep` |
| Cache de prefixo de prompt (tempos) | `prompt_cache` | Segurança do transporte | `deep` |
| Sonda de desempenho | `performance` | Desempenho | `deep` (em `standard` só com uma referência, 5 pedidos) |

- **smoke** executa conectividade e segurança; **standard** acrescenta os
  detectores de protocolo, identidade, capacidades, streaming, faturação e
  fiabilidade; **deep** acrescenta as sondas de contexto longo, determinismo,
  visão, prompt injetado, integridade, cache de prompt e desempenho (e o juiz
  com `--judge`); **full** executa os mesmos detectores que deep e mede o
  desempenho com e sem streaming; **custom** executa todos os detectores das
  dimensões selecionadas, com a profundidade de deep.
- **Código puro (por omissão):** todos os detectores exceto `quality_judge`
  decidem com código determinístico — verificações de texto e de expressões
  regulares, aritmética, estatística de tempos. Não é necessário um segundo
  modelo.
- **Híbrido código + LLM (`--judge`):** `quality_judge` pergunta a um modelo
  juiz de confiança, configurado à parte (nunca o alvo), se as respostas do
  alvo se parecem com o modelo declarado. Sem `--judge-base-url`, o modo de
  comparação usa a referência como juiz.
- **Modo de comparação** (`zing compare`) dá às sondas uma referência de
  confiança: `model_identity` regista a autoidentificação da referência ao lado
  da do alvo, `protocol_request` reenvia à referência os parâmetros rejeitados,
  `integrity` eleva a CRÍTICA uma substituição que a referência não faz,
  `quality_judge` mostra os dois lados ao juiz e `performance` sonda os dois
  endpoints alternadamente. A confiança só pode ser alta com uma referência.
- **Base de conhecimento:** o perfil do modelo declarado
  (`zing/knowledge/data/*.yaml` mais as suas próprias entradas em `kb.db`)
  fornece a janela de contexto declarada, a saída máxima, o tokenizer, as
  capacidades, as palavras-chave de identidade e as impressões comportamentais
  com que as sondas são avaliadas. Cada relatório regista o perfil usado
  (`knowledge`).
- **Idioma dos prompts:** cada texto de sonda está em `zing/prompts/en.json` e
  é em inglês, seja qual for o idioma da interface; só as impressões cujo idioma
  *é* a medida declaram `prompt_lang` e `language_bound`. Cada relatório lista
  os idiomas das sondas usadas (`prompt_languages`).
- **Modelos de raciocínio:** uma sonda curta que termina no seu limite de saída
  com a resposta em falta, ou cortada depois de o raciocínio usar pelo
  menos metade do limite (`reasoning_tokens` reportados), é repetida uma vez
  com um limite de 4.096 tokens, para que um modelo que pensa antes de responder
  não seja lido como falha. As sondas cujo limite ou tempo é a medida
  (desempenho, cache de prompts, fiabilidade, prompt injetado, saída máxima, o
  atributo de pedido `max_tokens`) nunca são repetidas. Assim que se sabe que um
  endpoint raciocina (o seu perfil indica `reasoning: true`, ou após a sua
  primeira repetição deste tipo), as sondas curtas são enviadas desde o início
  com o limite de 4.096 tokens em vez de duas vezes.

---

## `connectivity` — Conectividade

**Deteta.** Nenhum truque diretamente: é a porta de que dependem todos os
outros detectores. Separa uma chave morta ou mal configurada de um relay que
merece ser auditado.

**Como funciona.** `GET /v1/models` (regista se o modelo declarado aparece) e
uma completion de chat a `temperature=0` que pede ao modelo para repetir um
canário exato; regista a latência e o campo `model` devolvido.

**Escala de pontuação** (`zing/detectors/connectivity.py`):

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `connectivity.models` | A lista de modelos (/v1/models) respondeu. | Aprovado | 100 pts |
|  | A lista de modelos (/v1/models) não respondeu; alguns relays a desativam. | Aviso · Baixa | 60 pts |
| `connectivity.chat` | Uma completion de chat devolveu conteúdo e repetiu o canário. | Aprovado | 100 pts |
|  | Uma completion de chat devolveu conteúdo, mas não repetiu o canário. | Aprovado | 85 pts |
|  | A completion de chat falhou ou não devolveu conteúdo. | Falha · Alta | 0 pts |

**Ressalvas.** A ausência de `/v1/models` é benigna; muitos relays
desativam-na. Um erro de rede passageiro ou um 5xx pode fazer falhar a
verificação de chat: volte a executar. A conectividade não prova nada sobre
*qual* modelo respondeu. As suas constatações nunca elevam o veredito de risco.

---

## `protocol` — Conformidade do protocolo

**Deteta.** Relays cujo middleware quebra o contrato do protocolo (turnos
perdidos, sequências de paragem ignoradas, erros malformados, campos de
resposta em falta ou a zero, parâmetros de pedido removidos) e, através do
determinismo, `cache.ignore-temperature`. Cobre em parte
`capability.json-tool-fakery`.

### `protocol` — Conformidade de compatibilidade com a OpenAI

**Como funciona.** Três sondas: uma conversa com várias interações que tem de
recordar uma cor de uma interação anterior; uma sequência `stop` que tem de
cortar a saída; e um pedido deliberadamente inválido (`messages` vazio) que tem
de ser rejeitado com um 4xx, idealmente com um corpo de erro ao estilo OpenAI.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `protocol.multi_turn` | A cor de um turno anterior foi lembrada. | Aprovado | 100 pts |
|  | A cor de um turno anterior não foi lembrada. | Aviso · Média | 55 pts |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Não contabilizado |
| `protocol.stop` | A saída parou na sequência de parada. | Aprovado | 100 pts |
|  | Não foi possível confirmar o tratamento da parada pelo texto. | Aviso · Baixa | 70 pts |
|  | Foi devolvido texto após a sequência de parada. | Aviso · Baixa | 60 pts |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Não contabilizado |
| `protocol.error_schema` | Rejeitada com um 4xx e um corpo de erro no estilo OpenAI. | Aprovado | 100 pts |
|  | Rejeitada com um 4xx, mas o corpo não segue o estilo OpenAI. | Aviso · Baixa | 80 pts |
|  | Sem resposta HTTP; não foi possível confirmar o tratamento de erros do cliente. | Aviso · Baixa | 55 pts |
|  | Outro estado HTTP; não foi possível confirmar o tratamento de erros do cliente. | Aviso · Baixa | 55 pts |
|  | A solicitação inválida causou um erro de servidor (5xx). | Falha · Média | 35 pts |
|  | A solicitação inválida foi aceita (2xx). | Falha · Média | 30 pts |

### `protocol_response` — Disponibilidade dos atributos de resposta

**Como funciona.** Uma chamada normal sem streaming; cada atributo do protocolo
do alvo (OpenAI Chat Completions, Anthropic Messages ou OpenAI Responses;
catálogo em `zing/detectors/wire_attrs.py`) é avaliado no corpo em bruto. Os
atributos principais são, por exemplo, `model`,
`choices[0].message.role/content`, `finish_reason`, `usage.prompt_tokens`,
`usage.completion_tokens` e `usage.total_tokens` (que tem de ser a soma dos
dois); os secundários são `id`, `object`, `created`/`created_at`,
`choices[0].index` e `type`. Um zero onde uma contagem tem de ser positiva
(`completion_tokens: 0` para uma resposta não vazia) conta como zero, não como
válido.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `protocol_response.core` (Atributos de resposta principais) | Presente com um valor válido. | Aprovado | 100 pts |
|  | Presente mas zero ou vazio (p. ex. completion_tokens: 0). | Falha · Média | 20 pts |
|  | Presente com tipo ou valor errado (p. ex. total ≠ soma das partes). | Aviso · Média | 40 pts |
|  | Ausente da resposta. | Falha · Média | 0 pts |
| `protocol_response.minor` (Atributos de resposta secundários) | Presente com um valor válido. | Aprovado | 100 pts |
|  | Presente mas zero ou vazio. | Aviso · Baixa | 50 pts |
|  | Presente com tipo ou valor errado. | Aviso · Baixa | 70 pts |
|  | Ausente da resposta. | Aviso · Baixa | 60 pts |
| `protocol_response.call` (Sonda dos atributos de resposta) | A chamada de sonda não devolveu um corpo de resposta para avaliar. | Inconclusivo · Baixa | Não contabilizado |

### `protocol_request` — Suporte aos atributos de pedido

**Como funciona.** É enviado cada parâmetro de pedido do protocolo (cerca de
cinco chamadas). Os parâmetros com efeito observável têm a sua própria chamada
e têm de o mostrar: `system`/`instructions` seguido, o limite de saída termina
em `finish_reason: length`, `n: 2` devolve duas escolhas, `logprobs` é
devolvido. Os parâmetros que só têm de ser aceites (`temperature`, `top_p`,
`seed`, penalizações, `user`, `top_k`, `metadata`) partilham uma chamada e só
são repetidos um a um se esta for rejeitada. Um 4xx conta como limite do modelo
(não contabilizado) em vez de rejeição quando a base de conhecimento lista o
parâmetro em `unsupported_params`, quando um parâmetro de amostragem é enviado a
um modelo de raciocínio ou quando uma referência com o mesmo protocolo também o
rejeita. Ferramentas e modo JSON ficam em `capability`, `stop` em `protocol`, a
utilização em streaming em `streaming`.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `protocol_request.param` (Parâmetros de pedido) | Aceite, e o seu efeito é visível na resposta. | Aprovado | 100 pts |
|  | Aceite (o seu efeito não é observável numa única resposta). | Aprovado | 100 pts |
|  | Aceite, mas o seu efeito está ausente da resposta. | Aviso · Baixa | 50 pts |
|  | Rejeitado com um 4xx (possivelmente um limite do próprio modelo). | Aviso · Baixa | 40 pts |
|  | Rejeitado com um 4xx, enquanto a referência o aceita. | Falha · Média | 15 pts |
|  | Rejeitado, mas o próprio modelo não o suporta; não contado. | Info | Não contabilizado |
|  | Erro do servidor ou sem resposta; não contado. | Inconclusivo · Baixa | Não contabilizado |

### `determinism` — Determinismo e correção da cache

**Como funciona.** Quatro prompts criativos idênticos a `temperature=1.0` (sem
seed): um modelo genuíno varia; uma saída idêntica byte a byte em todas as
amostras aponta para uma cache de respostas que ignora a amostragem. O veredito
é suprimido para modelos de raciocínio, que ignoram legitimamente a
temperatura. Duas perguntas factuais idênticas a `temperature=0` são apenas
informativas.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `determinism.temp1_variability` | As amostras repetidas com temperature=1.0 diferiram, como numa amostragem real. | Aprovado | 100 pts |
|  | As amostras foram idênticas, mas modelos de raciocínio ignoram legitimamente temperature. | Info | 100 pts |
|  | Todas as amostras com temperature=1.0 foram idênticas byte a byte, o que sugere respostas em cache. | Aviso · Média | 55 pts |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Não contabilizado |
| `determinism.temp0_stability` | Respostas idênticas com temperature=0 (esperado); apenas informativo, não pontua. | Info | Não contabilizado |
|  | As respostas diferiram com temperature=0; apenas informativo, não pontua. | Info | Não contabilizado |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Não contabilizado |

**Ressalvas.** Os gateways podem acrescentar campos próprios do fornecedor; só
são assinalados campos obrigatórios em falta ou inválidos. A tradução entre os
dialetos Anthropic e OpenAI remodela legitimamente algumas estruturas. Confirme
um defeito suspeito repetindo-o e, se possível, no modo de comparação.

---

## `context_window` — Janela de contexto

**Deteta.** `context.window-truncation` (um relay anuncia 128K/200K/1M mas
corta o prompt em silêncio) e `context.lost-in-middle-rag` (uma camada barata de
RAG/resumo só reencaminha partes do prompt).

**Como funciona.** Recuperação de uma agulha num palheiro a `temperature=0`: um
marcador único é inserido num texto de enchimento não repetitivo dimensionado
com a estimativa heurística de tokens do zing, e o modelo tem de o devolver.

1. Uma escada ascendente que duplica a partir de 2K tokens até à janela
   declarada, limitada por `--max-context-tokens` (200K por omissão), com um
   degrau perto de 90 % do máximo (sete tamanhos no máximo). Cada tamanho é
   sondado primeiro com a agulha no **início** (profundidade 0,0): uma truncagem
   que mantém a pergunta no fim do prompt só pode descartar o seu início (um
   servidor local que corta o prompt ao seu comprimento de contexto mantém o
   fim), por isso uma recuperação aí aprova o tamanho numa só chamada. Uma falha
   é verificada no fim (profundidade 0,95); se o fim for recuperado, o início é
   sondado mais uma vez com uma agulha nova, e uma segunda falha reprova o
   tamanho como **truncagem pelo início** (indicada nas evidências do
   veredicto). No máximo três chamadas por tamanho; a escada para na primeira
   falha confirmada.
2. Um passo de pesquisa binária entre o último tamanho recuperado e o primeiro
   que falhou.
3. Perda no meio: com min(32K, janela medida), a agulha é colocada nas
   profundidades 0,1, 0,5 e 0,9; recuperar o início e o fim mas não o meio é uma
   constatação.
4. Um 4xx cuja mensagem refere o comprimento do contexto é uma rejeição por
   tamanho; uma rejeição de `max_tokens` (modelos de raciocínio) é repetida com
   `max_completion_tokens` e nunca é lida como um teto.
5. Uma sonda que esgota o tempo encerra a escada sem contar como falha: a
   janela acima do último tamanho recordado é reportada como não verificada
   (inconclusiva), nunca como truncamento.

A janela medida é comparada com a declarada. Sem janela declarada, a medida é
reportada mas não pontuada.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `context_window.window` (Janela de contexto efetiva) | A recordação se manteve até pelo menos 90% da janela declarada; desconta a parte da janela não recordada. | Aprovado | até −10 pts |
|  | A recordação se manteve até 50–90% da janela declarada; desconta a parte da janela não recordada. | Aviso · Média | até −50 pts |
|  | A recordação falhou abaixo da metade da janela declarada; desconta a parte da janela não recordada. | Falha · Alta | até −100 pts |
|  | Nem o menor tamanho de sonda recordou a agulha. | Falha · Alta | −100 pts |
| `context_window.lost_in_middle` | O início e o fim foram recordados, mas o meio não. | Aviso · Média | −15 pts |
| `context_window.rejected_below_claim` | Um prompt bem abaixo da janela declarada foi rejeitado como longo demais. | Falha · Alta | Sem dedução |
| `context_window.measured` | Não há janela declarada para comparar: apenas medido, não pontua. | Info | Sem dedução |
| `context_window.no_ladder` | Nenhum tamanho de sonda coube entre o mínimo e o limite. | Inconclusivo · Baixa | Sem dedução |
| `context_window.timed_out` | Uma sonda esgotou o tempo antes de atingir a janela declarada: um endpoint lento, não uma prova de truncamento. | Inconclusivo · Baixa | Sem dedução |

**Ressalvas.** Os modelos genuínos de contexto longo também perdem agulhas no
meio; por isso só uma falha na **extremidade** é lida como truncagem. A
recuperação perto do teto é probabilística; volte a executar antes de concluir.
A sonda é limitada por `--max-context-tokens`, pelo que uma janela maior não é
exercitada por completo. Compare com uma referência de confiança para separar
o comportamento do modelo do de uma camada intermédia.

---

## `model_identity` — Identidade do modelo

**Deteta.** `downgrade.silent-substitution` (um nome premium sobre um backend
mais barato ou aberto), bem como sinais de `downgrade.reasoning-collapse`,
`downgrade.quantized-distilled` e `downgrade.partial-probabilistic-routing`
quando alteram o comportamento.

### `model_identity` — Identidade do modelo e impressão digital de degradação

**Como funciona.** Três sinais independentes:

1. **Autoidentificação** a `temperature=0`, comparada por palavras inteiras com
   as palavras-chave de identidade do perfil (a marca genuína) e com uma lista
   de marcas rivais (`identity_forbidden` do perfil mais uma lista incorporada).
   Uma marca rival só conta se a genuína estiver ausente; «Sou o Claude, não o
   GPT» é um contraste benigno.
   A marca genuína são as `identity_keywords` do perfil mais os seus próprios
   nomes: a chave do fornecedor, o nome inicial do nome de apresentação do
   fornecedor, a primeira palavra do id e da família do modelo, e os restantes
   nomes desse fabricante na lista incorporada (`z.ai` também abrange `zhipu`).
   Um modelo que nomeia o seu próprio fabricante nunca é, por isso, uma marca
   rival, mesmo quando `identity_keywords` está vazio. Os nomes derivados
   nunca se sobrepõem a `identity_forbidden`, as palavras genéricas («ai»,
   «platform», …) nunca contam, e a marca própria de uma plataforma não conta
   para o modelo de outro fabricante que serve.
   Palavras de marca que também são palavras comuns (`step`, `command`, `seed`, `spark`, `meta`, `yi`, `grok`) só contam
   nesta autoidentificação e só escritas como nome (“Meta”, “Command R”,
   “grok-2”; no início de uma frase ou item de lista só com uma versão
   anexada, “Step-2”); nas
   respostas de impressão digital nunca contam, portanto “let me think step
   by step” não é uma marca concorrente. Um fornecedor dono de uma dessas
   palavras a mantém como própria.
2. **Impressões comportamentais** da base de conhecimento (data-limite do
   conhecimento, particularidades do tokenizer, formatação, sondas ligadas a um
   idioma, …): até seis sondas de código puro, verificadas com
   `expect_contains`, `expect_contains_any`, `expect_not_contains` ou
   `expect_regex`; saída limitada a 512 tokens. Uma sonda que
   precisa de mais saída (por exemplo, uma verificação da saída máxima) é
   ignorada, aparece como Info e outra sonda ocupa o seu lugar. Uma
   impressão que se desvia
   desconta a sua parte do peso sobre 100 pontos (25 no máximo); sozinha fica
   BAIXA, duas ou mais acrescentam uma constatação agregada MÉDIA.
3. **Campo `model` devolvido** por uma chamada simples: sufixos de snapshot e
   aliases são tolerados; uma palavra de gama inferior (`mini`, `flash`,
   `lite`, `8b`, …) ou uma família diferente é assinalada.

Sem perfil na base de conhecimento, o detector é inconclusivo.
Também é inconclusivo e sem pontuação (`model_identity.no_evidence`)
quando nem a autoidentificação nem nenhuma impressão digital deram uma
resposta utilizável e o campo `model` devolvido não diverge: um relay que
rejeita ou esvazia cada requisição não fornece evidência de identidade, e o
eco do nome solicitado sozinho não prova nada. Evidência parcial pontua
normalmente.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `model_identity.self_id` | A autodescrição nomeou a marca genuína. | Aprovado | Sem dedução |
|  | A autodescrição nomeou uma marca rival e não a genuína. | Falha · Alta | teto 20 |
|  | A autodescrição nomeou a marca genuína e uma rival (geralmente uma comparação inofensiva). | Aviso · Baixa | Sem dedução |
|  | A autodescrição não nomeou nem a marca genuína nem uma rival. | Aviso · Baixa | Sem dedução |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo | Sem dedução |
| `model_identity.fp` (Impressões comportamentais) | A resposta correspondeu ao comportamento nativo do modelo declarado. | Aprovado | Sem dedução |
|  | A resposta desviou do comportamento nativo: desconta a parcela de peso da sonda em 100 pontos. | Aviso · Baixa | até −25 pts |
|  | A resposta nomeou uma marca rival e não a genuína: desconta a parcela de peso da sonda. | Falha · Alta | até −25 pts · teto 20 |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo | Sem dedução |
|  | A sonda precisa de mais saída do que o limite de identidade de 512 tokens; não executada. | Info | Sem dedução |
| `model_identity.fp_aggregate` | Duas ou mais impressões comportamentais desviaram. | Aviso · Média | Sem dedução |
| `model_identity.model_field` | O campo model devolvido correspondeu ao modelo solicitado. | Aprovado | Sem dedução |
|  | O campo model devolvido indica um modelo diferente ou menor. | Aviso · Média | Sem dedução |
|  | A resposta não tinha um campo model utilizável. | Inconclusivo | Sem dedução |
| `model_identity.no_evidence` | Nem a autoidentificação nem nenhuma impressão digital deram uma resposta utilizável e o campo model não divergiu: sem pontuação. | Inconclusivo | Sem dedução |

### `quality_judge` — Avaliação de qualidade / degradação por um LLM juiz

**Como funciona.** Só com `--judge` (a partir de deep). Uma curta série de
prompts que distinguem gamas (raciocínio em vários passos, uma tarefa de código
precisa, seguimento de instruções com nuances) vai para o alvo e, no modo de
comparação, para a referência; um juiz de confiança separado só vê as respostas
e devolve um veredito com a sua confiança. O juiz recebe o modelo declarado (`claimed_model` se estiver definido; caso
contrário, o id pedido). Um veredito do juiz só é ALTO se o juiz tiver
indicado confiança **alta** e uma referência utilizável tiver corroborado a
diferença — uma que devolveu uma resposta não vazia a cada sonda que o alvo
respondeu. Uma confiança baixa, média, ausente ou desconhecida fica em
MÉDIA, tal como uma referência que falhou ou deixou sondas sem resposta.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `quality_judge.verdict` (Veredito do juiz LLM) | O juiz considerou as respostas compatíveis com o modelo declarado. | Aprovado | 95 pts |
|  | O juiz considerou as respostas diferentes do modelo declarado (confiança baixa, média ou não indicada). | Aviso · Média | 50 pts |
|  | O juiz tem certeza de que as respostas diferem do modelo declarado (sem referência utilizável). | Aviso · Média | 25 pts |
|  | O juiz tem certeza e uma referência confiável corroborou a diferença. | Falha · Alta | 25 pts |
|  | O juiz não conseguiu chegar a um veredito. | Inconclusivo · Baixa | Não contabilizado |
|  | Não há respostas do alvo para julgar. | Inconclusivo · Baixa | Não contabilizado |

**Ressalvas.** As API oficiais atualizam os snapshots em silêncio; um desvio
pode ser deriva benigna — o zing reporta «divergente», nunca «substituição
provada». Os modelos alucinam o próprio nome, pelo que a autoidentificação
sozinha nunca decide. Um relay poderia memorizar uma série fixa de sondas. Um
veredito de confiança alta exige o modo de comparação contra o snapshot exato
declarado.

**Não implementado.** A impressão digital por distância de embeddings (estilo
LLMmap), os testes estatísticos de duas amostras e a amostragem em grande volume
contra o encaminhamento probabilístico são linhas de investigação, não
verificações atuais.

---

## `capability` — Capacidades declaradas

**Deteta.** `capability.json-tool-fakery`: chamadas de ferramentas, modo JSON,
esquemas estritos, comprimento de saída ou visão anunciados mas não cumpridos —
ou *sobre*cumpridos, sinal de um substituto.

### `capability` — Verificação das capacidades declaradas

**Como funciona.** Quatro sondas a `temperature=0`, cada uma avaliada face às
capacidades do perfil:

- **Ferramentas:** é oferecida uma ferramenta com `tool_choice: "auto"` e um
  pedido explícito para a usar; tem de voltar uma chamada de ferramenta.
  Argumentos entregues como objeto em vez da string JSON que a OpenAI devolve
  são assinalados como um motor que não é da OpenAI.
- **Modo JSON:** `response_format: json_object` tem de devolver um objeto
  analisável com o valor pedido.
- **Esquema estrito:** um `json_schema` estrito; a conformidade é verificada se
  o modelo a declara e apenas registada (informativo) se não. É omitida sem
  perfil.
- **Saída máxima:** uma geração longa limitada a min(saída máxima declarada,
  2048) tokens; atingir o limite ou um comprimento plausível é aprovado, parar
  abaixo de um quarto é assinalado.

Uma observação sem declaração a verificar — nenhuma chamada de ferramenta ou
objeto JSON quando a função não é declarada, ou qualquer resultado do esquema
estrito quando o perfil diz que o modelo não tem esquemas estritos — é registada
mas não contabilizada: um modelo nunca perde pontos pelo que ninguém declara.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `capability.tools` | Voltou uma chamada de ferramenta para um pedido explícito de ferramenta. | Aprovado | 100 pts |
|  | A chamada de ferramentas é declarada, mas nenhuma chamada voltou. | Falha · Média | 0 pts |
|  | Nenhuma chamada de ferramenta voltou, e essa capacidade não é declarada. | Info | Não contabilizado |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Não contabilizado |
| `capability.tools.encoding` | Os argumentos da ferramenta chegaram como objeto, não como a string JSON da OpenAI. | Aviso · Baixa | Não contabilizado |
| `capability.json_mode` | O modo JSON devolveu um objeto analisável com o valor pedido. | Aprovado | 100 pts |
|  | Voltou um objeto JSON com o valor errado; o modo JSON não é declarado. | Info | Não contabilizado |
|  | Não voltou nenhum objeto JSON analisável; o modo JSON não é declarado. | Info | Não contabilizado |
|  | O modo JSON é declarado, mas não voltou um objeto válido com o valor. | Falha · Média | 0 pts |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Não contabilizado |
| `capability.json_schema` | O esquema estrito é declarado e a resposta o seguiu. | Aprovado | 100 pts |
|  | O esquema estrito não foi aplicado, de acordo com o declarado. | Info | Não contabilizado |
|  | A resposta o seguiu embora o modelo declarado não tenha esquemas estritos. | Info | Não contabilizado |
|  | O esquema estrito é declarado, mas a resposta não o seguiu. | Aviso · Baixa | 40 pts |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Não contabilizado |
| `capability.max_output` | A saída continuou até o limite de tokens pedido. | Aprovado | 100 pts |
|  | A saída terminou antes do limite com um comprimento plausível. | Aprovado | 90 pts |
|  | A saída terminou abaixo de um quarto do comprimento pedido. | Aviso · Baixa | 70 pts |
|  | A saída terminou abaixo de um quarto do pedido apesar de um máximo declarado grande. | Aviso · Baixa | 60 pts |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Não contabilizado |

### `vision` — Verificação da capacidade multimodal (visão)

**Como funciona.** A partir de deep e só se o perfil declarar visão: um pequeno
PNG laranja liso, gerado em tempo de execução, é enviado em linha com uma
pergunta de uma palavra sobre a sua cor. Um substituto só de texto não consegue
nomear a cor de forma fiável.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `vision.color` | O modelo nomeou a cor da imagem de teste. | Aprovado | 100 pts |
|  | A visão é declarada, mas o modelo não nomeou a cor da imagem. | Aviso · Média | 0 pts |
|  | Nenhuma resposta utilizável para avaliar. | Inconclusivo | Não contabilizado |
| `vision.not_claimed` | A visão não é declarada, então nenhuma imagem foi enviada. | Info | Não contabilizado |

**Ressalvas.** Os modelos genuínos às vezes omitem uma ferramenta ou emitem JSON
inválido; uma sonda por capacidade é um sinal, não uma taxa. A tradução entre
dialetos remodela legitimamente o JSON das chamadas de ferramentas. A sonda de
saída máxima não exercita todo o teto declarado. Uma só imagem é um indício,
não uma prova.

---

## `streaming` — Autenticidade do streaming

**Deteta.** `stream.fake-streaming`: o relay faz buffer de toda a resposta do
upstream e reprodu-la num ou em poucos fragmentos, perdendo a vantagem de
latência.

**Como funciona.** Um pedido em streaming (`max_tokens` 256,
`stream_options.include_usage`) de que se regista a hora de chegada de cada
fragmento. Três sinais de buffer: **poucos fragmentos** (dois ou menos) e
**primeiro token tardio** (TTFT acima de 90 % da duração total), avaliados só
quando chegaram pelo menos 220 caracteres, e **intervalos uniformes** (quatro ou
mais fragmentos com intervalos quase iguais, CV < 0,1, e abaixo de 2 ms:
despejados de uma vez). Um fluxo sem fragmento de utilização é assinalado à
parte.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `streaming.healthy` | Muitos fragmentos, um primeiro token cedo e intervalos espalhados: streaming real. | Aprovado | Sem dedução |
| `streaming.few_chunks` | Sinal de buffer: o primeiro desconta 40 pontos, um segundo 20, os seguintes nada. | Aviso · Média | até −40 pts |
| `streaming.late_ttft` | Sinal de buffer: o primeiro desconta 40 pontos, um segundo 20, os seguintes nada. | Aviso · Média | até −40 pts |
| `streaming.uniform_gaps` | Sinal de buffer: o primeiro desconta 40 pontos, um segundo 20, os seguintes nada. | Aviso · Média | até −40 pts |
| `streaming.no_usage` | Nenhum fragmento de uso no stream: desconta 15 pontos se nada estiver em buffer. | Aviso · Baixa | até −15 pts |
| `streaming.failed` | A requisição em streaming falhou. | Falha · Alta | teto 0 |

Ou seja: autêntico 100 · utilização em falta 85 · um sinal de buffer 60 · dois
ou mais 40 · falha 0.

**Ressalvas.** Saídas curtas, um modelo pequeno e rápido ou a instabilidade da
rede podem parecer uma rajada. Um upstream que não suporta streaming obriga o
relay a fazer buffer de forma legítima; leia-o como «o relay não faz
streaming», não como má-fé. Volte a executar e compare com uma referência que
faça streaming de facto.

---

## `billing` — Faturação e utilização

**Deteta.** `billing.usage-inflation` (tokens de prompt ou de completion
inflacionados), `billing.missing-usage` (`usage` em falta, parcial ou
incoerente) e, como sinal de corroboração, `prompt.injected-system-prompt`.

**Como funciona.** Uma chamada determinística (um parágrafo conhecido para
resumir, `temperature=0`). O prompt e a resposta visível são contados de forma
independente com uma heurística sensível ao idioma (cerca de ±25 %), para
todas as famílias de modelos: o zing não usa nenhuma biblioteca de tokenizer e
não descarrega nenhuma. Tokens de prompt reportados acima de 2,5× a estimativa
e mais de 50 tokens acima contam como inflação. Os tokens de completion de um
modelo de raciocínio incluem legitimamente tokens de raciocínio ocultos e não
são assinalados; caso contrário, tokens de completion acima de 3× a estimativa
e mais de 80 tokens acima são um aviso leve, nunca uma falha, porque a
estimativa de uma resposta curta é imprecisa. `total` tem de ser
`prompt + completion` (±2), e um total sem discriminação é assinalado. Uma
contagem abaixo (menos de metade da estimativa) é informativa (não prejudica o
comprador).

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `billing.request-failed` | Nenhuma resposta utilizável para avaliar. | Inconclusivo · Baixa | Sem dedução |
| `billing.missing-usage` | A resposta não trazia nenhum uso de tokens. | Aviso · Média | teto 75 |
| `billing.usage-inflation` | Os tokens de prompt declarados excedem em muito a estimativa independente. | Falha · Alta | teto 55 |
| `billing.usage-inflation-completion` | Os tokens de completion declarados estão muito acima de uma estimativa heurística. | Aviso · Média | teto 70 |
| `billing.reasoning-tokens` | Os tokens de completion excedem o texto visível, como esperado para um modelo de raciocínio. | Info | Sem dedução |
| `billing.usage-undercount-prompt` | Os tokens de prompt declarados estão muito abaixo da estimativa (não prejudica o comprador). | Info | Sem dedução |
| `billing.usage-undercount-completion` | Os tokens de completion declarados estão muito abaixo da estimativa (não prejudica o comprador). | Info | Sem dedução |
| `billing.total-mismatch` | O total declarado não é igual aos tokens de prompt + completion. | Aviso · Baixa | teto 90 |
| `billing.partial-usage` | O uso informa um total sem a divisão prompt/completion. | Aviso · Média | teto 80 |
| `billing.usage-consistent` | O uso declarado está dentro da tolerância da estimativa independente. | Aprovado | Sem dedução |

Um pedido de sonda falhado deixa o detector sem pontuação.

**Ressalvas.** Os modelos de chat e os tokens especiais acrescentam um pequeno
desvio fixo; não se espera uma correspondência exata. Se o modelo servido
diferir do declarado, o tokenizer «certo» é desconhecido. Os tokens de
raciocínio ocultos não se contam de fora. Uma sonda mede um tamanho; um
multiplicador que cresce com o tamanho exige execuções repetidas ou o modo de
comparação.

---

## `reliability` — Fiabilidade em concorrência

**Deteta.** Parte de `throttle.rate-limit-quality`: um relay que falha ou se
arrasta com um paralelismo moderado.

**Como funciona.** Uma rajada de pequenos pedidos idênticos
(`--reliability-requests`, 8 por omissão) com concorrência limitada
(`--concurrency`, 3 por omissão). A taxa de sucesso é calculada sobre os pedidos
realmente tentados: um HTTP 429 é uma limitação honesta e é contabilizado à
parte. A pontuação desconta a parte falhada; uma latência p95 acima de 30 s
mantém 85 % do resto.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `reliability.success_rate` | Todas as requisições tentadas na rajada tiveram sucesso. | Aprovado | Sem dedução |
|  | Até 10% das requisições tentadas falharam; desconta a parcela falha. | Aviso · Baixa | até −10 pts |
|  | Mais de 10% das requisições tentadas falharam; desconta a parcela falha. | Falha · Média | até −100 pts |
|  | Todas as requisições foram limitadas (HTTP 429): não pontua. | Inconclusivo · Baixa | Sem dedução |
| `reliability.latency` | Latência p95 acima de 30 s sob carga; desconta 15% da pontuação restante. | Aviso · Baixa | até −15 pts |
| `reliability.rate_limited` | Parte da rajada foi limitada: limitação legítima, não contabilizada. | Info | Sem dedução |
| `reliability.skipped` | A sonda de confiabilidade estava desativada. | Info | Sem dedução |

As medições de velocidade dedicadas pertencem à dimensão `performance`.

**Ressalvas.** Os fornecedores genuínos também abrandam e devolvem 429 sob carga
real. Um instantâneo não capta o comportamento consoante a hora; `zing watch`
volta a auditar segundo um calendário.

**Não implementado.** A medição da qualidade ao longo do tempo e com carga
variável, e os sinais de chave upstream partilhada
(`infra.shared-upstream-key`: quota que desce em repouso, identificadores de
pedido upstream divulgados) estão no roteiro.

---

## `security` — Segurança do transporte

**Deteta.** `prompt.injected-system-prompt`, `integrity.response-tampering`,
indícios de `privacy.prompt-logging-leakage` (cache por prefixo) e a higiene
básica de transporte e segredos.

### `security` — Sinais de transporte e gestão de segredos

**Como funciona.** Verifica que o endpoint usa HTTPS, que a chave de API nunca
aparece literalmente numa resposta e que cabeçalhos de resposta denunciam um
upstream ou proxy (`server`, `via`, `x-powered-by`, `x-upstream-*`,
`x-litellm-*`, …; informativo). Também lembra o limite: o registo de prompts e
as chaves upstream partilhadas não podem ser provados de fora.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `security.tls` | O endpoint usa HTTPS. | Aprovado | Sem dedução |
|  | O endpoint não usa HTTPS; a chave de API trafega em texto puro. | Falha · Alta | teto 40 |
| `security.key_echo` | A chave de API não aparece na resposta. | Aprovado | Sem dedução |
|  | A chave de API aparece literalmente na resposta. | Falha · Alta | teto 30 |
| `security.headers` | Nenhum cabeçalho de resposta revela o upstream (apenas informativo). | Aprovado | Sem dedução |
|  | Cabeçalhos de resposta revelam o upstream ou o proxy (apenas informativo). | Info · Baixa | Sem dedução |
|  | Não há cabeçalhos de resposta para inspecionar. | Inconclusivo | Sem dedução |
| `security.note` | O registro de prompts e as chaves upstream compartilhadas não são comprováveis de fora. | Info | Sem dedução |

### `injected_prompt` — Deteção de prompt de sistema injetado

**Como funciona.** Dois indícios independentes. (1) Uma **sobrecarga fixa de
tokens de entrada**: duas mensagens de utilizador de tamanhos diferentes sem
mensagem de sistema; os `prompt_tokens` reportados menos a estimativa
independente têm de continuar pequenos. Uma sobrecarga de pelo menos 30 tokens
que se mantém constante (com margem de 16) nos dois tamanhos indica um prompt
oculto acrescentado no início e não uma inflação proporcional. (2) Uma **sonda
de fuga** que pede ao modelo para repetir quaisquer instruções anteriores. Só os
dois juntos chegam a MÉDIA.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `injected_prompt.verdict` (Prompt de sistema injetado) | A sobrecarga de tokens de entrada é pequena e nenhuma instrução oculta vazou. | Aprovado | 100 pts |
|  | Vazou texto com cara de instrução quando pedido (fraco por si só). | Info · Baixa | 85 pts |
|  | Uma grande sobrecarga fixa de tokens de entrada, constante com o tamanho da mensagem. | Aviso · Baixa | 75 pts |
|  | Uma sobrecarga fixa de tokens de entrada e um preâmbulo vazado, juntos. | Aviso · Média | 55 pts |
|  | Não há contagens de tokens de prompt utilizáveis para medir a sobrecarga. | Inconclusivo | Não contabilizado |

### `integrity` — Integridade das respostas / adulteração

**Como funciona.** Canários de resposta conhecida com valores sensíveis — um
URL de instalação e um pacote `pip install` fixado — têm de voltar
literalmente. Um eco exato é aprovado, a falta de eco (paráfrase, recusa) é
inconclusiva, e só uma **substituição do valor** que preserva a estrutura conta
como adulteração. No modo de comparação, uma substituição que a referência de
confiança não faz é CRÍTICA.
Só corrobora uma referência que devolve o canário intacto: se falhar ou não
devolver nada utilizável, não confirma nada e a substituição fica em MÉDIA
(evidência `baseline_unavailable`).
Uma resposta cortada no limite de saída é inconclusiva, não uma substituição.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `integrity.verdict` (Integridade das respostas) | Os canários de resposta conhecida voltaram intactos. | Aprovado | 100 pts |
|  | Um valor canário foi substituído (ainda não confirmado por uma referência). | Falha · Média | 45 pts |
|  | Um valor canário foi substituído enquanto a referência confiável o manteve intacto. | Falha · Crítica | 10 pts |
|  | Nenhum canário foi repetido literalmente, então a adulteração não pôde ser avaliada. | Inconclusivo | Não contabilizado |

### `prompt_cache` — Cache de prefixo de prompt (tempos)

**Como funciona.** Um prefixo único de cerca de 1200 tokens é enviado duas
vezes em streaming (a frio e depois a quente) e um prefixo de controlo diferente
uma vez. Se o TTFT a quente for inferior a metade do TTFT a frio e do de
controlo, e pelo menos 150 ms mais rápido do que a frio, a cache por prefixo
está ativa. Sempre informativo: a cache por prefixo é uma otimização legítima.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `prompt_cache.verdict` (Cache por prefixo de prompt) | Um prefixo de prompt repetido voltou muito mais rápido: o cache por prefixo está ativo. | Info | Não contabilizado |
|  | Um prefixo de prompt repetido não foi claramente mais rápido. | Info | Não contabilizado |
|  | Uma ou mais sondas de tempo não devolveram um tempo utilizável. | Inconclusivo | Não contabilizado |

**Ressalvas.** Os modelos inventam falsos «prompts de sistema» quando se lhes
pede para os divulgar; uma fuga sozinha fica BAIXA. A tradução entre dialetos
remodela o JSON das chamadas de ferramentas; só conta uma substituição do
*valor*. Uma adulteração condicional (só para certas palavras-chave, clientes
ou após um aquecimento) pode escapar a um número finito de sondas. O registo em
caixa-preta é **impossível de provar** a partir do cliente, e o zing não
consegue mostrar uma cache partilhada *entre utilizadores* com uma só chave: a
ausência de um sinal temporal não prova que os prompts não são registados.

---

## `performance` — Desempenho

**O que mede.** Quão **constante** é o endpoint, não quão rápido. Um modelo
local ou auto-alojado, lento mas constante, pontua bem; a velocidade bruta só
conta face a uma referência.

**Como funciona.** A sonda dedicada é executada em deep, full e custom, e em
standard só no modo de comparação (5 pedidos por lado, demasiado poucos para as
verificações de constância). Por endpoint: três pings `GET /models`, um pedido
de aquecimento (reportado como arranque a frio), `--performance-requests`
pedidos uniformes (100 por omissão) de `--performance-max-tokens` tokens de
saída (128 por omissão) e, em deep/full, uma rajada a `--concurrency`. Cada
pedido é não armazenável em cache: um identificador de pedido aleatório abre o
prompt, os temas rodam e não são enviados parâmetros de cache nem de raciocínio;
uma resposta que mesmo assim venha de uma cache é assinalada e excluída das
estatísticas. A sonda usa streaming por omissão (`--performance-non-streaming`
para relays que não suportam streaming); full mede os dois modos, intercalados.
No modo de comparação, alvo e referência alternam para que a deriva da rede
afete ambos por igual.
Os tokens de entrada em cache só contam quando cobrem pelo menos metade do
prompt: os servidores locais (Ollama, llama.cpp, LM Studio) reutilizam o modelo
de chat em cache de cada prompt, o que não é uma resposta guardada.
Cada chamada da auditoria fica guardada como registo de pedido
(`performance.requests`, só números, nunca texto do prompt ou da resposta); o
seu `start_ms` conta a partir do `started_at` do relatório (UTC), por isso a
hora de cada chamada pode ser reconstruída.

A constância usa rácios de cauda (p90 ÷ p50 para latência e TTFT, p50 ÷ p10 para
a vazão), que um pedido atípico não desloca como desloca um desvio-padrão;
precisam de pelo menos 10 amostras limpas. A referência é a referência de
confiança ou, na sua falta, o intervalo `performance.decode_tps` do perfil na
base de conhecimento.

| Verificação | Resultado | Estado | Efeito |
|---|---|---|---|
| `performance.summary` | Latência, TTFT e vazão foram medidos. | Info | Não contabilizado |
|  | Nenhuma das requisições de sonda teve sucesso. | Inconclusivo | Não contabilizado |
| `performance.latency_consistency` | A latência é constante (razão de cauda no máximo 1,3). | Aprovado | 100 pts |
|  | A latência é estável (razão de cauda no máximo 1,75). | Aprovado | 85 pts |
|  | A latência varia visivelmente (razão de cauda no máximo 2,5). | Aviso · Baixa | 65 pts |
|  | A latência é errática (razão de cauda acima de 2,5). | Falha · Baixa | 40 pts |
|  | Poucas amostras para avaliar a constância da latência. | Info | Não contabilizado |
| `performance.ttft_consistency` | O tempo até o primeiro token é constante (razão de cauda no máximo 1,3). | Aprovado | 100 pts |
|  | O tempo até o primeiro token é estável (razão de cauda no máximo 1,75). | Aprovado | 85 pts |
|  | O tempo até o primeiro token varia visivelmente (razão de cauda no máximo 2,5). | Aviso · Baixa | 65 pts |
|  | O tempo até o primeiro token é errático (razão de cauda acima de 2,5). | Falha · Baixa | 40 pts |
|  | Poucas amostras para avaliar a constância do tempo até o primeiro token. | Info | Não contabilizado |
| `performance.throughput_consistency` | A vazão é constante (razão de cauda no máximo 1,3). | Aprovado | 100 pts |
|  | A vazão é estável (razão de cauda no máximo 1,75). | Aprovado | 85 pts |
|  | A vazão varia visivelmente (razão de cauda no máximo 2,5). | Aviso · Baixa | 65 pts |
|  | A vazão é errática (razão de cauda acima de 2,5). | Falha · Baixa | 40 pts |
|  | Poucas amostras para avaliar a constância da vazão. | Info | Não contabilizado |
| `performance.errors` | No máximo 2% das requisições da sonda falharam. | Aprovado | 100 pts |
|  | Até 10% das requisições da sonda falharam ou esgotaram o tempo. | Aviso · Baixa | 80 pts |
|  | Muitas requisições da sonda falharam ou esgotaram o tempo. | Falha · Baixa | 50 pts |
| `performance.load_stability` | A latência se mantém sob carga concorrente (no máximo 1,5x). | Aprovado | 100 pts |
|  | A latência aumenta sob carga concorrente (até 3x). | Aviso · Baixa | 80 pts |
|  | A latência piora muito sob carga concorrente (acima de 3x). | Falha · Baixa | 55 pts |
| `performance.cache_hit` | Prompts de sonda únicos voltaram de um cache (excluídos das estatísticas). | Aviso · Baixa | 60 pts |
|  | A referência serviu prompts únicos a partir de um cache (não pontuado). | Info | Não contabilizado |
| `performance.reference` | A vazão está de acordo com a referência deste modelo. | Aprovado | 100 pts |
|  | Mais lento que a referência (ex.: local ou hardware menor); não é uma falha. | Info | Não contabilizado |
|  | Muito mais rápido que a referência (compatível com um modelo menor). | Aviso · Baixa | 60 pts |
| `performance.reasoning` | O modelo gasta tokens de raciocínio ocultos; o TTFT inclui o raciocínio. | Info | Não contabilizado |
| `performance.relay_overhead` | Latência comparada com a referência confiável (apenas informativo). | Info | Não contabilizado |
| `performance.skipped` | A sonda de desempenho estava desativada. | Info | Não contabilizado |

**Ressalvas.** A latência depende do caminho de rede e da carga do fornecedor
nesse momento; repita um mau resultado de constância noutro momento. Os
intervalos da base de conhecimento são medianas deliberadamente largas das API
nativas, e um alvo mais lento é registado, nunca contabilizado. Todas as constatações são no
máximo de gravidade BAIXA: esta dimensão mexe na pontuação, nunca no veredito de
risco.

---

## Correspondência truque → detector

Os 16 truques de relay da investigação distribuem-se assim no zing.

| # | Truque (id) | Gravidade | Detector(es) | Cobertura atual |
|---|---|---|---|---|
| 1 | `downgrade.silent-substitution` | critical | `model_identity`, `quality_judge` | autoidentificação, impressões, campo `model`; juiz; modo de comparação |
| 2 | `downgrade.reasoning-collapse` | critical | `model_identity`, `quality_judge` | só impressões e juiz; ainda sem escada de dificuldade própria |
| 3 | `downgrade.quantized-distilled` | high | `quality_judge`, `model_identity` | juiz com referência; ainda sem teste de distribuição |
| 4 | `downgrade.partial-probabilistic-routing` | high | `model_identity` | só se os pedidos amostrados atingirem o substituto; a amostragem em grande volume está no roteiro |
| 5 | `context.window-truncation` | high | `context_window` | escada com agulha na extremidade + pesquisa binária; medida vs declarada |
| 6 | `context.lost-in-middle-rag` | high | `context_window` | profundidades 0,1/0,5/0,9 num tamanho médio |
| 7 | `stream.fake-streaming` | medium | `streaming` | número de fragmentos, momento do primeiro token, uniformidade dos intervalos |
| 8 | `billing.usage-inflation` | high | `billing` | estimativa heurística independente de tokens de uma sonda conhecida |
| 9 | `billing.missing-usage` | medium | `billing`, `protocol_response`, `streaming` | presença, discriminação e aritmética da utilização; fragmento de utilização do fluxo |
| 10 | `privacy.prompt-logging-leakage` | high | `prompt_cache` | cache por prefixo via TTFT (informativo); a partilha entre utilizadores e o registo continuam impossíveis de provar com uma chave |
| 11 | `infra.shared-upstream-key` | high | — | roteiro (quota que desce em repouso, identificadores de pedido upstream divulgados) |
| 12 | `cache.ignore-temperature` | medium | `determinism` | saída idêntica byte a byte a temperatura 1,0; suprimido para modelos de raciocínio |
| 13 | `prompt.injected-system-prompt` | medium | `injected_prompt`, `billing` | sobrecarga fixa de tokens de entrada (dois tamanhos) + sonda de fuga |
| 14 | `throttle.rate-limit-quality` | medium | `reliability`, `performance` | taxa de sucesso (429 à parte), latência de cauda, estabilidade sob carga; a medição ao longo do tempo está no roteiro |
| 15 | `capability.json-tool-fakery` | medium | `capability`, `protocol_request` | ferramentas, modo JSON, esquema estrito, parâmetros; uma sonda cada, não taxas |
| 16 | `integrity.response-tampering` | critical | `integrity` | canários de URL/pacote de resposta conhecida; CRÍTICA quando uma referência corrobora |

---

## Limites e utilização responsável

**O zing reporta desvios e riscos, não provas de fraude.** O veredito usa uma
linguagem prudente (clean / low / medium / high / inconclusive), mantém
inconclusivos os resultados ambíguos e só sobe a «alto» com evidências sólidas
de gravidade alta.

**O que uma auditoria de caixa-preta não consegue provar:**

- **Registo de prompts ou retenção de dados.** Um sinal temporal prova uma
  cache; a sua ausência não prova que os prompts não são registados.
- **Integridade das respostas** sem respostas assinadas pelo fornecedor: uma
  adulteração condicional pode escapar a um número finito de sondas.
- **Chaves partilhadas ou roubadas:** no máximo um *risco* de pool partilhado.
- **Deriva benigna ou substituição:** as API oficiais atualizam os snapshots em
  silêncio.
- **Encaminhamento constante:** um relay pode encaminhar de forma
  probabilística, e uma auditoria só vê os pedidos que enviou.

**Método.** As constatações que dependem de uma comparação exata usam
`temperature=0` e prompts restritos. Cada constatação traz as suas evidências
(entradas, valores observados, contagens, tempos) e cada relatório regista o
perfil, os idiomas dos prompts e as definições com que foi executado, para que
um resultado possa ser verificado de forma independente. Um relay pode detetar
os testes: volte a executar noutros momentos e prefira o modo de comparação
contra uma referência de confiança do **snapshot exato declarado** — é a forma
mais sólida de separar o comportamento do modelo do do relay, e a única de
atingir confiança alta.

**Divulgação responsável.** **Não acuse publicamente um fornecedor** com base
num relatório do zing. Antes de agir: volte a executar com mais amostras e
noutros momentos, confirme com o modo de comparação e exclua explicações de
deriva, rede e carga. Se uma dúvida séria persistir, fale primeiro em privado
com o fornecedor, sob a forma de perguntas sobre o comportamento observado e não
de acusações.
