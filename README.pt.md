# zing — verificação da realidade dos relays de LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · **🇵🇹 Português** · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

O **zing** é uma ferramenta local-first que audita se um relay de API
(revendedor / proxy) serve realmente o modelo que declara — ou se o substitui
discretamente por um mais barato, trunca a sua janela de contexto, simula o
streaming ou inflaciona a faturação de tokens. Em suma: recebe aquilo por que
paga? Fala a **API OpenAI Chat Completions**, a **API Anthropic Messages** e a
**API OpenAI Responses** (`/v1/responses`) — com deteção automática, ou forçada
com `--api openai|anthropic|responses`.

Indica-lhe o endpoint de um relay e o modelo que ele diz servir; o zing executa
uma bateria de sondas de caixa-preta, compara o comportamento observado com uma
base de conhecimento integrada de **98 perfis de modelos de 7 fornecedores** e
dá um veredito claro, apoiado em evidências — na linha de comandos, numa
interface web local ou em JSON para outra ferramenta ou LLM.

> O zing fornece **evidências de caixa-preta de desvios e riscos, não uma prova
> criptográfica de fraude.** Consulte [Utilização responsável](#utilização-responsável).

Este README é para quem **utiliza** o zing. A forma como o zing é construído,
testado e publicado está no [Guia do programador](DEVELOPER_GUIDE.pt.md); como
cada verificação funciona e é pontuada, na [Metodologia](docs/METHODOLOGY.pt.md).

---

## Índice

- [Porquê](#porquê)
- [Instalação](#instalação)
- [Início rápido](#início-rápido)
- [Interface web (`zing serve`)](#interface-web-zing-serve)
- [O que é verificado](#o-que-é-verificado)
- [Como se chega ao veredito](#como-se-chega-ao-veredito)
- [Suites](#suites)
- [Desempenho](#desempenho)
- [Modo de comparação e juiz LLM](#modo-de-comparação-e-juiz-llm)
- [Monitorização](#monitorização)
- [Auditorias de embeddings, rerank, imagem e áudio](#auditorias-de-embeddings-rerank-imagem-e-áudio)
- [Utilização em CI (GitHub Action)](#utilização-em-ci-github-action)
- [Base de conhecimento](#base-de-conhecimento)
- [Relatórios](#relatórios)
- [Privacidade e dados locais](#privacidade-e-dados-locais)
- [Utilização responsável](#utilização-responsável)
- [Mais documentação](#mais-documentação)
- [Licença](#licença)

## Porquê

O mercado de chaves de relay está cheio de ofertas de «GPT-4o a um décimo do
preço». Muitas são honestas. Outras não — e as desonestas são difíceis de
detetar a olho nu:

- Pede `gpt-4o`; discretamente, servem-lhe `gpt-4o-mini` ou um modelo aberto.
- O relay anuncia um contexto de 1M de tokens mas trunca discretamente para 32K.
- O «streaming» é a resposta completa em buffer, voltada a partir em pedaços, sem ganho de latência.
- Os tokens de `usage` reportados estão inflacionados, pelo que o seu saldo se esgota mais depressa do que devia.
- Um modelo que devia suportar chamadas de ferramentas / modo JSON discretamente não o faz.

O zing transforma «há aqui algo que não bate certo» num relatório reproduzível.

## Instalação

Requer Python 3.10+. Qualquer uma das opções abaixo disponibiliza o comando `zing`.

### Com pip

```bash
# a partir do PyPI
pip install zing-audit

# ou a partir do código-fonte
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Com [uv](https://docs.astral.sh/uv/)

```bash
# a partir do PyPI, como ferramenta autónoma no seu PATH
uv tool install zing-audit

# ou executá-lo uma vez sem instalar
uvx --from zing-audit zing --help

# ou a partir do código-fonte, num ambiente virtual local do projeto
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Também pode instalar diretamente a partir do repositório Git sem o clonar:
`uv tool install git+https://github.com/cenbonew/zing`.

### Extras opcionais

- `web` — a interface web local (`zing serve`).

```bash
pip install 'zing-audit[web]'      # pip, a partir do PyPI
pip install -e '.[web]'            # pip, a partir do código-fonte
uv tool install 'zing-audit[web]'  # uv, a partir do PyPI
uv pip install -e '.[web]'         # uv, a partir do código-fonte
```

O extra `tokenizers` já não é necessário: desde a 0.19.0 está vazio e só é
mantido para que os comandos de instalação antigos continuem a funcionar. O zing
conta os tokens com uma heurística integrada e não descarrega nada em tempo de
execução (nenhum ficheiro de tokenizer), pelo que também funciona em ambientes
restritos ou offline que só alcançam os relays que audita.

Os relatórios PDF (`--format pdf` e a transferência em PDF da interface web) não
precisam de nenhum extra: são compostos com
[ReportLab](https://www.reportlab.com/opensource/), uma dependência em Python puro
que não precisa de bibliotecas de sistema em Linux, macOS ou Windows.

### Com Docker (apenas a interface web)

A partir de uma cópia do código-fonte:

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# abra http://localhost:8000
```

Publique sempre a porta em `127.0.0.1`, como acima. Detalhes e variáveis de
ambiente: [Guia do programador → Docker](DEVELOPER_GUIDE.pt.md#docker) e
[docs/DOCKER.md](docs/DOCKER.md).

## Início rápido

```bash
# 1) auditar um relay face ao que declara (id do modelo + pista do fornecedor)
export ZING_API_KEY=sk-a-sua-chave-do-relay
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) a verificação mais forte: comparar com uma referência de confiança do mesmo modelo
export OPENAI_API_KEY=sk-a-sua-chave-openai
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) auditar um relay nativo da Anthropic (API Messages) — o protocolo é detetado
#    automaticamente a partir de base_url/model, ou forçado com --api anthropic
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) confirmar uma substituição suspeita: auditar o id REAL do modelo do relay face ao
#    perfil com que é vendido (aqui: um modelo Doubao vendido como deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) listar os modelos que um endpoint anuncia
zing models --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY

# 6) consultar a base de conhecimento
zing kb            # todos os perfis, com a sua origem
zing kb deepseek   # um fornecedor

# 7) gerar uma configuração que pode versionar
zing init          # escreve zing.yaml
zing check -c zing.yaml
```

As chaves de API podem ser dadas em claro, como `env:VAR` ou como
`file:/caminho`; os relatórios contêm apenas uma impressão da chave. Um ficheiro
de configuração completo está em [`examples/zing.yaml`](examples/zing.yaml).

### Como ferramenta para um LLM / agente

O zing foi feito para ser controlado por outro programa ou modelo. Tudo sai para
stdout em JSON, erros incluídos, e o código de saída serve de barreira.

```bash
# veredito leve, próprio para agentes (~5x mais pequeno que --json: sem as evidências volumosas)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# relatório estruturado completo quando precisa das evidências de cada constatação
zing check --base-url ... --model gpt-4o --json

# primeiro o orçamento: que detectores correm + chamadas à API estimadas, SEM fazer nenhuma
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# barreira pelo código de saída (1 se o risco >= medium, ou a pontuação ficar abaixo de --fail-under);
# os erros de configuração/utilização saem com 2, em JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# descoberta legível por máquina
zing kb --json                      # toda a base de conhecimento
zing models --base-url ... --json   # o que um endpoint anuncia
```

No modo `--json`/`--compact`, uma configuração errada imprime `{"error": {...}}`
(código de saída 2) em vez de uma mensagem para pessoas, para que um pipeline
possa tratar as falhas de forma uniforme.

## Interface web (`zing serve`)

Prefere clicar? Uma interface web local envolve o mesmo motor — sem linha de
comandos.

```bash
pip install 'zing-audit[web]'     # ou: uv tool install 'zing-audit[web]'
zing serve                        # abre http://localhost:8000
```

Na nova interface o formulário guia a configuração:

1. Escolha o **Relay / provedor**: um provedor da base de conhecimento ou um
   relay que guardou. O seu URL base é preenchido (os outros URL conhecidos do
   provedor são oferecidos como sugestões). Para qualquer outro relay escolha
   **Outro (introduzir o URL)** e introduza o **URL do intermediário**.
2. Acrescente a **Chave de API** se o relay precisar de uma.
3. O zing lista sozinho os modelos do relay (ao escolher um relay e sempre que
   o URL ou a chave mudam; **Atualizar modelos** pergunta de novo). Escolha o
   **Modelo pedido**. Um relay sem lista de modelos recorre à introdução do id
   (**Introduzir manualmente**).
4. Opcionalmente escolha o **Modelo declarado** entre os modelos da base de
   conhecimento: o modelo que o relay diz servir. Se o modelo pedido estiver na
   base de conhecimento, fica pré-selecionado; mude-o apenas se o relay vender o
   modelo com outro nome. Dele resulta o perfil do provedor usado na auditoria.

Um relay que ainda não está na lista pode ser mantido com **Salvar na base** com
o nome que lhe der; da próxima vez basta escolhê-lo. A referência confiável
(**Comparar com uma referência confiável**) e as auditorias de embeddings e rerank
são configuradas da mesma forma. A interface clássica mantém os campos simples com
**Obter modelos**.

Depois, **Iniciar auditoria** e acompanhe
as verificações **ao vivo**: cada verificação mostra a sua pontuação e quanto
tempo levou, e uma verificação com constatações expande-se para mostrar as
evidências. O resultado é um relatório de veredito que pode partilhar: nota,
**Verificações por dimensão** com as suas escalas de pontuação, constatações em
linguagem clara e a secção de desempenho (na nova interface, também um
**Registro de execução** de cada detector).

Tudo corre na sua máquina: uma chave escrita no navegador só chega ao seu
servidor zing local e ao relay que audita, nunca a terceiros. Consulte
[Privacidade e dados locais](#privacidade-e-dados-locais).

### Páginas

A interface web tem duas versões que partilham o mesmo servidor e os mesmos
dados. A **interface clássica** abre em `/`; a sua ligação **Experimentar a nova
interface** passa para a **nova interface** em `/v2/`, cuja ligação **Interface
clássica** volta atrás. A escolha é memorizada por navegador.

| Página | Interface clássica | Nova interface | Para que serve |
|---|---|---|---|
| **Auditoria** | `/` | `/v2/` | Auditar um relay (opcionalmente face a uma referência) e ler o relatório |
| **Consola** | `/console` | — | A mesma auditoria como consola compacta, em estilo de registo |
| **Ferramentas** | `/tools` | — | Auditorias de embeddings e rerank; na nova interface começam na página **Auditoria** com o seletor de tipo de endpoint (`/v2/tools` redireciona para lá) |
| **Monitores** | `/watches` | `/v2/watches` | Reauditorias agendadas com alertas por webhook |
| **Histórico** | `/history` | `/v2/history` | Cada auditoria executada nesta máquina, agrupada por relay + modelo declarado, com tendências |
| **Análises** | — | `/v2/analytics` | Relays e modelos comparados ao longo do tempo: indicadores, gráficos com tabelas de dados, classificações |
| **Conhecimento** | — | `/v2/kb` | A base de conhecimento em três separadores — modelos, provedores, relays: explorar, ativar/desativar, adicionar os seus |

A nova interface acrescenta: filtros e tendências configuráveis (pontuação, nota,
latência p50, tokens/s) no **Histórico**; **Agendar como monitor** e **Executar auditoria novamente** em cada
execução do Histórico; **Transferir relatório** em todos os formatos; um seletor
de tema (Automático / Claro / Escuro); e a página **Conhecimento**. Cada página
exceto Acessibilidade tem um aviso logo abaixo da introdução, colorido segundo a
importância (informação, sucesso, aviso, crítico): p. ex. a última auditoria
concluída em **Auditoria**, a chave mestra em **Monitores**, as execuções ainda
em processamento em **Histórico** e **Análises**, as entradas ignoradas em
**Conhecimento**.

**Auditorias em segundo plano (nova interface).** Uma auditoria iniciada na
página **Auditoria** continua quando muda de página ou fecha o separador;
**Continuar em segundo plano** envia-a para lá de propósito. O **Histórico**
lista cada auditoria em fila e em curso (e cada monitor em execução) com o seu
progresso; **Ver em direto** reabre a vista ao vivo, que recupera tudo o que já
aconteceu. Auditorias do mesmo relay correm uma após a outra, para nunca
distorcerem os resultados de latência ou fiabilidade umas das outras (todos os
endereços loopback contam como um só host, por isso modelos servidos pela sua
própria máquina também esperam); auditorias de relays diferentes correm em
paralelo, no máximo quatro de cada vez (`ZING_MAX_PARALLEL_AUDITS`). Os
monitores esperam pelo seu relay da mesma forma.

**Análises (nova interface).** `/v2/analytics` transforma o histórico local em
comparações: indicadores do período escolhido (execuções, pontuação mediana,
proporção de risco alto, taxa de sucesso, TTFT, velocidade de saída, rácios de
faturação) com a variação face ao período anterior de igual duração; um gráfico
de qualquer métrica por relay, modelo ou relay × modelo, por hora, dia ou
semana (linha mediana com a faixa p25–p75, até quatro séries, cada gráfico
também como tabela de dados); e uma classificação dos relays de um modelo ou
dos modelos de um relay. Os relays são agrupados pela sua entrada na base de
conhecimento (relays guardados e provedores), por isso renomear um relay
reagrupa o seu histórico. Intervalos com menos de 3 execuções aparecem
esbatidos — uma única auditoria pode ser um valor atípico; um monitor dá
medições regulares. Execuções mais antigas mostram o que mediram: a página diz
em quantas execuções um valor se baseia. Por omissão compara uma suite e um
modo de sondagem (os mais frequentes), para não misturar execuções diferentes;
filtros e vista ficam no URL, por isso uma vista pode ser guardada nos
favoritos ou partilhada. Nada sai da máquina.

Outros painéis respondem a perguntas mais concretas: **horas de ponta** (um
mapa de calor dia da semana × hora do TTFT, da latência e da velocidade de decodificação (mediana e caudas p95 /
p5), da variação entre tokens, dos tempos de rede e do relay ou da taxa de sucesso ou
de erro no seu fuso horário — um relay fica mais lento ou falha mais nas horas
de maior carga? Por dia da semana ou, com 90 dias de execuções, num ciclo de
4 semanas e, com 180 dias, por semana do mês), **erros e fiabilidade** (chamadas falhadas por causa — limite
de pedidos (HTTP 429), erros do servidor (5xx), tempos esgotados, erros de rede
— ao longo do tempo e por relay ou modelo, a partir dos registos de pedidos
guardados, indicando quantas auditorias os têm), **integridade do modelo**
(resultados das verificações de identidade, janela de contexto e capacidades
por relay × modelo, a proporção de auditorias cujo modelo devolvido difere e a
proporção medida da janela de contexto declarada), **faturação e tokens**
(rácios de faturação ao longo do tempo face à linha dos 100% — acima dela o
relay informa mais tokens do que o zing contou — e as proporções de tokens de
raciocínio e de entrada em cache) e **sobrecarga do relay** (o tempo de
processamento que o relay informa ao lado da ida e volta de rede).

**Separadores e ligações para partilhar (Análises).** Os painéis estão em cinco
separadores — **Visão geral** (indicadores, classificação), **Tendências**
(comparação ao longo do tempo, horas de ponta), **Fiabilidade** (erros,
sobrecarga do relay), **Integridade do modelo** e **Faturação** — sob o
cabeçalho da página e um painel de filtros comum; só o separador que está a ver
é carregado. O URL guarda o separador, os filtros e cada opção dos gráficos
(`#tab=reliability&range=30&relay=…&eb=dow_hour`), e **Copiar a ligação para
esta vista** copia-o (ou mostra-o num campo para copiar quando o navegador não
o permite): a ligação abre exatamente essa vista. O painel de filtros é o mesmo
em **Histórico**, **Monitores** e **Análises**: fechado, indica quantos filtros estão ativos e
nomeia-os numa linha (p. ex. «Últimos 30 dias · standard · Streaming · Example
Relay»), assim uma vista partilhada diz o que mostra.

### Idiomas

Um menu de idioma no cabeçalho de cada página muda a interface entre
**🇬🇧 inglês** (predefinição), **🇨🇳 chinês** (a interface original),
**🇫🇷 francês**, **🇪🇸 espanhol**, **🇵🇹 português**, **🇮🇹 italiano** e
**🇩🇪 alemão**; a escolha é memorizada por navegador.

Os relatórios transferidos a partir da interface (**Transferir relatório**: JSON,
Markdown, HTML ou PDF) seguem o idioma escolhido: as chaves JSON, os valores
enumerados (`risk_level`, `status`, `severity`, …), os ids e as evidências ficam
exatamente como no relatório da CLI (o JSON continua a ser um relatório zing
válido), enquanto os valores legíveis (título e resumo do veredito, títulos e
resumos das constatações, recomendações, nomes dos detectores, notas) são
traduzidos, e o nome do ficheiro leva o idioma (`zing-report.pt.json`,
`zing-report.pt.pdf`). Os títulos de secção dos ficheiros Markdown/HTML/PDF
ficam em inglês. Os relatórios da CLI com `--format json|md|html|pdf` ficam em
inglês.

**Os prompts enviados ao endpoint auditado não seguem o idioma da interface.**
Todo o texto que o zing envia a uma API de LLM está em inglês, para que o mesmo
relay receba o mesmo veredito seja quem for que leia o relatório (as verificações
de respostas e as estimativas de tokens estão calibradas para esses textos
exatos). As únicas exceções são as impressões da base de conhecimento cujo idioma
*é* a medida — por exemplo, as sondas de fluência em chinês, de tokenizer e de
autoidentificação dos modelos chineses. Cada relatório regista os idiomas de
sonda efetivamente usados (`prompt_languages`, p. ex. `["en", "zh"]`).
`started_at` regista quando a auditoria começou (UTC); o `start_ms` de cada
registo de pedido conta a partir desse momento.

## O que é verificado

O zing pontua dez dimensões. As quatro **dimensões núcleo** — identidade do
modelo, janela de contexto, capacidades declaradas e faturação e consumo —
revelam mais diretamente um «gato por lebre». Os nomes são os da interface web e dos
relatórios.

| Dimensão | Id | Peso | O que deteta |
|---|---|---|---|
| **Identidade do modelo** | `model_identity` | 21 | Despromoção ou substituição silenciosa do modelo — autoidentificação, data de corte do conhecimento, impressões de tokenizer, o campo `model` devolvido; opcionalmente um juiz LLM |
| **Janela de contexto** | `context_window` | 19 | Truncagem silenciosa do contexto (declara 1M, a recuperação falha aos 32K) e «lost in the middle» por camadas baratas de RAG/resumo, com agulha num palheiro e pesquisa binária |
| **Capacidades declaradas** | `capability` | 13 | Chamadas de ferramentas / modo JSON / esquema JSON / saída máxima declarados mas não entregues (ou *sobre*-entregues, sinal de um substituto); **visão** — um modelo que declara entrada de imagem tem de ler uma imagem gerada de resposta conhecida |
| **Conformidade do protocolo** | `protocol` | 8 | Conformidade na ligação: múltiplas voltas, sequências de paragem, esquema de erro; cada parâmetro do pedido aceite (e respeitado quando visível), cada atributo da resposta presente; cache de respostas que ignora temperature/seed |
| **Faturação e utilização** | `billing` | 8 | Inflação de tokens/utilização e contabilização ausente ou impossível de verificar, com uma estimativa heurística independente de tokens |
| **Conectividade** | `connectivity` | 7 | Acessibilidade do endpoint e a lista `/v1/models` anunciada |
| **Autenticidade do streaming** | `streaming` | 6 | Streaming falso (buffer e depois partição), a partir do número de fragmentos e do seu espaçamento |
| **Fiabilidade em concorrência** | `reliability` | 6 | Taxa de sucesso e latência sob carga concorrente (a limitação HTTP 429 é contada à parte) |
| **Segurança do transporte** | `security` | 6 | HTTPS, higiene dos cabeçalhos, eco de segredos; um prompt de sistema injetado oculto; adulteração em trânsito de respostas e chamadas de ferramentas (canários de resposta conhecida); cache de prefixo de prompt (tempos) |
| **Desempenho** | `performance` | 6 | Quão *constantes* são a latência, o tempo até ao primeiro token e a vazão, a taxa de falhas e o abrandamento sob carga; a velocidade só face a uma referência (ver [Desempenho](#desempenho)) |

A [Metodologia](docs/METHODOLOGY.pt.md) descreve cada sonda, o truque de relay a
que responde, a sua escala de pontuação e as suas ressalvas quanto a falsos
positivos.

## Como se chega ao veredito

Em resumo (os detalhes estão na [Metodologia](docs/METHODOLOGY.pt.md#como-o-zing-pontua)):

- Cada detector publica a sua **escala de pontuação** — cada resultado possível
  de cada verificação com os seus pontos —, e a interface web mostra-a em
  **Escala de pontuação**.
- A **pontuação de uma dimensão** é a média com peso igual das pontuações dos
  seus detectores. Uma constatação ALTA/CRÍTICA impõe **Falha** e uma
  constatação MÉDIA eleva **Aprovado** a **Aviso**, seja qual for a pontuação.
  Os relatórios explicam-no por dimensão em **Dimension details**; na interface
  web, cada linha das **Verificações por dimensão** expande-se com os mesmos
  detalhes.
- A **pontuação de saúde global** é a média ponderada das dimensões executadas
  (pesos acima), com nota A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) ou F.
- O **veredito de risco** depende da gravidade das constatações, não da
  pontuação:

| Risco | Rótulo na interface | Quando |
|---|---|---|
| `inconclusive` | Sinal insuficiente | Nada utilizável para julgar: identidade do modelo, janela de contexto e capacidades declaradas correram sem resultado utilizável (relay inacessível, modelo fora da base de conhecimento), ou nenhuma dimensão além da conectividade o produziu |
| `high` | Gato por lebre | Uma constatação CRÍTICA, uma constatação ALTA/CRÍTICA numa dimensão núcleo, ou duas ou mais constatações ALTAS |
| `medium` | Desvios detetados | Exatamente uma constatação ALTA fora das dimensões núcleo, ou uma constatação MÉDIA numa dimensão núcleo |
| `low` | Globalmente fiável | Qualquer outra constatação MÉDIA |
| `clean` | Coerente (provavelmente autêntico) | Nenhum dos casos acima |

As constatações da dimensão de conectividade nunca elevam o risco: um relay em
baixo ou limitado não pôde ser avaliado, o que não prova que responda outro
modelo. A **confiança** do veredito (baixa / média / alta) cresce com o número de
dimensões núcleo que produziram resultado, com uma referência e com o juiz LLM.

Os avisos de transporte — HTTP sem cifra (`security.tls`) e falhas ou caudas lentas
sob carga (`reliability.*`) — baixam a pontuação da sua dimensão, mas também não
elevam o risco de substituição; o resumo lista-os como avisos. Respostas
adulteradas e uma chave API devolvida continuam a elevá-lo. HTTP sem cifra para
esta máquina ou uma rede privada é apenas um aviso de gravidade baixa, pois a
chave nunca sai dela. Um perfil da base de conhecimento associado apenas de forma
aproximada (fuzzy) limita a confiança a baixa, e um detetor sem qualquer resposta
utilizável é inconclusivo, nunca uma aprovação.

## Suites

| Suite | Detectores | Custo |
|---|---|---|
| `smoke` | connectivity, security | muito baixo |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | baixo–médio |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (com `--judge`) | mais alto (as sondas de contexto longo e de tempos custam tokens) |
| `full` | os detectores de `deep`, com o desempenho medido com e sem streaming | o mais alto |
| `custom` | apenas as dimensões que escolher, com a profundidade de `deep` | conforme a seleção |

A sonda da janela de contexto é limitada por `--max-context-tokens` (200K por
predefinição), para que auditar um modelo de 1M de tokens continue acessível.
`--only` / `--skip` executam ou excluem detectores individuais pelo seu id.
Uma janela maior do que o limite de `--max-context-tokens` é reportada como *verificada até ao limite*, nunca como truncada.

### Suite personalizada

Execute apenas as dimensões que lhe interessam, poupando tempo e tokens. Cada
detector de cada dimensão escolhida é executado, como em `deep`:

```bash
zing check --base-url ... --model gpt-4o -D protocol -D performance
zing check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` é repetível ou separado por vírgulas e implica
`--suite custom`; num ficheiro de configuração use
`run.dimensions: [protocol, performance]`. As dimensões são `connectivity`,
`protocol`, `context_window`, `model_identity`, `capability`, `streaming`,
`billing`, `reliability`, `security` e `performance`. Na interface web, o botão
de suite `custom` abre a mesma escolha (**Dimensões a executar**) na página de
auditoria, na consola e nos monitores.

A **pontuação global é a média ponderada apenas das dimensões escolhidas**; as
que ficam de fora aparecem como «não selecionadas». O veredito de risco também
se baseia nas dimensões escolhidas: sem a identidade do modelo cobre apenas
essas, não qual modelo é servido, e indica-o.

## Desempenho

Cada relatório inclui uma secção **performance**: latência, tempo até ao
primeiro token (TTFT), tokens/s de descodificação e ponta a ponta, latência e
jitter entre fragmentos, taxas de erro/timeout/429, uma decomposição da rede
(ligação TCP, TLS, uma ida e volta `GET /models`, tempo de servidor) e arranque a
frio, cada um como count / min / mean / p50 / p75 / p90 / p95 / p99 / max /
stdev.

Quando a sonda dedicada corre, pontua a dimensão **Desempenho**. A pontuação mede
a **constância**, não a velocidade bruta, pelo que um endpoint lento mas
constante (um modelo local ou auto-alojado) não é penalizado por não ser um
centro de dados:

| Verificação | Pontuada segundo |
|---|---|
| constância da latência / do TTFT | razão de cauda p90 ÷ p50 (≤ 1,3 constante 100 · ≤ 1,75 estável 85 · ≤ 2,5 variável 65 · acima: errática 40); precisa de ≥ 10 amostras |
| constância da vazão | razão de cauda p50 ÷ p10 dos tokens/s, mesmos escalões |
| erros | pedidos de sonda falhados: ≤ 2 % 100 · ≤ 10 % 80 · acima: 50 (os 429 não contam) |
| estabilidade sob carga | latência p50 em rajada ÷ p50 sequencial: ≤ 1,5x 100 · ≤ 3x 80 · acima: 55 |
| acerto de cache | prompts únicos respondidos a partir de uma cache: 60 |
| referência | tokens/s face à referência de confiança ou, na falta dela, ao intervalo publicado para o modelo na base de conhecimento: em linha 100 · mais lento: não contabilizado (informativo, nunca uma falha) · ≥ 2x mais rápido 60 (sinal de um modelo mais pequeno) · sem referência: não contabilizado |

As constatações de desempenho são no máximo de gravidade baixa: mexem na
pontuação, nunca no veredito de risco. Sem a sonda (`standard` sem referência,
`smoke`), a dimensão não corre e sai da pontuação global.

- **standard** recolhe a secção a partir dos próprios pedidos da auditoria.
- **deep / full / custom** acrescentam uma sonda dedicada: 100 pedidos que não
  podem vir de cache, de 128 tokens de saída (um id de pedido aleatório abre cada
  prompt; não são enviados parâmetros de cache nem de raciocínio) mais uma rajada
  com `--concurrency`. Ajuste-a com `--performance-requests` (0 desativa-a) e
  `--performance-max-tokens`.
- A sonda usa streaming por predefinição; `--performance-non-streaming` (ou o
  seletor **Streaming / Sem streaming** da interface web) mede relays que não
  suportam streaming. **full** mede os dois modos, intercalados, e mostra-os lado
  a lado.
- **compare** corre a sonda nos dois endpoints, alternando pedidos, e acrescenta
  uma tabela alvo-vs-referência (5 pedidos por lado em `standard`, poucos demais
  para as verificações de constância) cujas diferenças são marcadas a verde ✓
  quando o alvo é melhor e a vermelho ✗ quando é pior.

Os tokens são contados duas vezes — a partir do `usage` do relay e localmente —,
pelo que a vazão pode ser medida mesmo sem `usage`. A contagem local é uma
estimativa feita com uma heurística integrada (cerca de ±15-20%; nenhum tokenizer
é usado ou descarregado), e a secção indica-o sempre. Um percentil só é mostrado
com amostras suficientes (p90 a partir de 10, p95 a partir de 20, p99 a partir de
100). O relatório JSON guarda os tempos de cada pedido (só números, sem texto); o
relatório HTML e a interface web representam-nos ao longo da linha temporal da
auditoria.

Auditorias que correm ao mesmo tempo no `zing serve` (vários separadores do
navegador, monitores) não distorcem os tempos umas das outras: a preparação que
exige muito CPU, como construir os prompts longos da janela de contexto, corre
fora do event loop do servidor.

**Tempos limite.** `timeout_sec` (`--timeout`, 60 s por omissão) é a base; cada
requisição recebe mais tempo conforme o tamanho do prompt e o orçamento de
saída, para que uma sonda longa de janela de contexto ou um modelo auto-hospedado
lento não seja interrompido ao fim de um minuto. Hosts locais e privados
(`localhost`, `127.x`, `192.168.x`, `host.docker.internal`, …) recebem pelo menos
300 s. `max_request_sec` (`--max-request-time`, 900 s por omissão) é o teto
absoluto de cada requisição, streams incluídos, para que nenhuma fique pendurada
para sempre. Uma sonda de janela de contexto que ainda assim esgota o tempo é
reportada como inconclusiva, não como truncamento.

## Modo de comparação e juiz LLM

O zing tem dois modos de deteção:

- **Código puro (predefinição):** todos os detectores exceto `quality_judge`
  decidem com código determinista — impressões, varrimento de contexto,
  aritmética de faturação, tempos do streaming. Não é preciso um segundo modelo;
  os resultados são reproduzíveis.
- **Híbrido código + LLM (`--judge`):** pergunta ainda a um modelo juiz *de
  confiança* (configurado à parte, nunca o alvo) se as respostas do alvo se
  parecem com o modelo declarado — sinais difusos como a qualidade e a
  profundidade de raciocínio que o código sozinho não consegue decidir. É o
  detector `quality_judge`.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

O **modo de comparação** (`zing compare`, ou **Comparar com uma referência
confiável** na interface web) executa as mesmas sondas, ao mesmo tempo, contra
uma referência de confiança do modelo declarado. É a via de confirmação mais
forte: respostas de identidade, parâmetros de pedido rejeitados, canários de
adulteração e desempenho são avaliados lado a lado, e só uma referência permite
que a confiança do veredito seja *alta*. Sem `--judge-base-url`, o modo de
comparação usa a referência como juiz.

## Monitorização

Um relay pode servir hoje o modelo verdadeiro e trocá-lo discretamente na semana
seguinte. `zing watch` volta a auditar segundo um calendário, regista cada
execução no histórico e alerta um webhook quando o risco ultrapassa um limite ou
**piora** em relação à execução anterior.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang pt                                     # ou --once para cron
```

Os alertas são formatados para **Slack / Feishu / DingTalk / JSON genérico**,
detetados automaticamente a partir do URL do webhook, e redigidos no idioma dos
alertas — inglês por predefinição; `--alert-lang en|zh|fr|es|pt|it|de`. O payload
JSON genérico mantém neutras as suas chaves e valores de máquina (`risk_level`,
`score`, …), traduz os legíveis (`text`, `headline`, `key_findings`) e indica o
`language`.

**Na interface web**, `zing serve` executa os mesmos monitores num agendador em
segundo plano dentro do processo do servidor, regista cada execução no
**Histórico** e envia os mesmos alertas por webhook:

- **Nova interface:** abra uma execução no **Histórico** e escolha **Agendar como
  monitor**. O zing copia a configuração dessa execução (relay, modelo, modelo
  declarado, fornecedor, suite, dimensões personalizadas) para um monitor em
  pausa na página **Monitores**; defina aí o intervalo e a chave API (o Histórico
  nunca guarda chaves) e ative-o. Intervalo, chave, **Limite de alerta**,
  webhooks e **Idioma dos alertas** editam-se diretamente em cada monitor. Um
  clique no nome recolhe o cartão para nome, estado e última execução
  (**Recolher tudo** / **Expandir tudo** acima da lista; guardado por
  navegador), e o painel de filtros (pesquisa, estado, último risco, tipo de
  endpoint, relay, suite) restringe uma lista longa como no **Histórico**.
- **Interface clássica:** preencha o formulário da página **Monitores** e clique
  em **Adicionar monitor**.

Cada monitor tem o seu próprio idioma de alertas (por predefinição, o da
interface), pode ser executado agora, pausado ou eliminado, e fica fixado ao
perfil da base de conhecimento com que foi criado até o voltar a fixar.

Os monitores cuja hora chegou correm ao mesmo tempo, cada um como uma auditoria
própria, mas nunca mais de uma auditoria de cada vez por host de relay e no
máximo `ZING_MAX_PARALLEL_AUDITS` no total; uma execução espera por uma vaga
livre (uma auditoria que inicie à mão também pode ficar em fila atrás de
monitores em execução). A hora de uma execução é o momento em que a sua
auditoria começa, depois de qualquer espera. A verificação de regressão compara
com a execução guardada mais recente do mesmo relay e modelo, por muitas outras
execuções que tenham sido guardadas entretanto. Os webhooks de alerta de uma
execução são enviados ao mesmo tempo, para que um lento ou inacessível não
atrase os outros. As chaves são guardadas encriptadas no seu diretório de dados
local e nunca são devolvidas ao navegador.

**Armazenamento das chaves de API.** Por omissão, o zing **não guarda** as
chaves de API dos monitores: uma chave introduzida fica apenas na memória do
`zing serve` e nunca é escrita no disco. Após um reinício, a página
**Monitores** indica os monitores que precisam novamente da chave; aguardam (sem
execução falhada nem alerta) até a introduzir. Os monitores sem chave e as
referências `env:`/`file:` continuam a funcionar. Para que as chaves sobrevivam
a reinícios, escolha **Guardar cifradas neste computador** em **Armazenamento
das chaves de API** na página **Monitores** v2: as chaves passam a ser guardadas
em `watches.db`, cifradas com uma chave mestra. Voltar atrás move as chaves
guardadas para a memória e apaga-as de `watches.db`. O aviso da página mostra o
modo ativo, pede confirmação antes de mudar e indica o que foi movido. A
interface clássica (`/watches`) nunca guarda uma chave. Uma instalação que já
guardava chaves cifradas, ou que define `ZING_SECRET_KEY`, continua a guardá-las
até mudar.

**Chave mestra.** As chaves API dos monitores são encriptadas com uma chave
mestra que o zing nunca escreve no disco. Da primeira vez que guarda uma chave
API, a página **Monitores** cria-a e mostra-a uma única vez: copie-a ou
transfira-a, guarde-a num gestor de palavras-passe (o seu navegador pode
guardá-la) e cole-a de novo para confirmar. Após cada reinício do `zing serve` a
página volta a pedi-la (o navegador pode preenchê-la); até lá, os monitores que
precisam dela esperam, enquanto os monitores sem chave ou com chaves
`env:`/`file:` continuam a ser executados. A barra de estado da página oferece
também **Bloquear**, **Rodar** e **Esqueceu a chave?** (descarta as chaves API
encriptadas para que as possa introduzir de novo). Para uso sem supervisão ou em
Docker, passe a chave em `ZING_SECRET_KEY` (consulte
[docs/DOCKER.md](docs/DOCKER.md)); `zing secret status | export | rotate`
gerem-na na linha de comandos.

## Auditorias de embeddings, rerank, imagem e áudio

Estes endpoints devolvem vetores, classificações, imagens ou áudio em vez de chat,
por isso o zing audita-os com sondas dedicadas em vez dos prompts de chat. Cada um
imprime um veredito e suporta `--json` e `--fail-on-risk`.

### Tipo de endpoint (superfície), monitores de embeddings e rerank

Cada auditoria, linha do histórico e monitor tem um **tipo de endpoint**
(`surface`): `chat` (predefinição), `embedding` ou `rerank`. É independente da
suite. As auditorias de embeddings e rerank passam pelo mesmo runner, a mesma
pontuação (0–100, A–F), o histórico, a análise e os monitores das auditorias de
chat; só os detetores mudam. O histórico e a análise filtram por tipo de endpoint,
e a análise mostra apenas as métricas aplicáveis.

Para monitorizar um endpoint de embeddings ou rerank, audite-o na página
**Auditoria** (escolha **Embeddings** ou **Reordenação** no seletor de tipo de
endpoint; na interface clássica, na página **Ferramentas**) e escolha
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

### Embeddings e rerank

```bash
# A dimensão de vetor esperada é obtida da base de conhecimento para o modelo declarado.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Ou indicar diretamente a dimensão esperada:
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: uma sonda integrada de resposta conhecida — um reranker genuíno tem de pôr
# em primeiro o documento obviamente relevante.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank

# Mais a fundo: junta a sonda de velocidade do rerank; --no-save deixa a execução fora do histórico.
zing rerank --base-url ... --model my-rerank --suite deep --no-save
# Ver primeiro as verificações e as chamadas estimadas, sem enviar pedidos:
zing rerank --base-url ... --model my-rerank --dry-run
```

`rerank` verifica a conectividade, a **sonda de resposta conhecida** (o documento
obviamente relevante tem de ficar em primeiro), o campo `model` devolvido, o
determinismo (a mesma consulta duas vezes dá a mesma classificação e as mesmas
pontuações) e a **deriva da classificação** face à execução guardada anterior.
`zing embed` e `zing rerank` aceitam `--suite`, `--save/--no-save` (guardado por
predefinição, para que a execução seguinte tenha uma referência de deriva) e
`--dry-run`.

`embed` verifica a conectividade, a **correspondência de dimensão** (comprimento
do vetor devolvido face à dimensão nativa do modelo declarado — o principal sinal
de «gato por lebre»: um relay que declara `text-embedding-3-large` de 3072-d mas
devolve 1024-d serve um substituto), o determinismo (mesma entrada → cosseno ≈
1), a distinção (entradas sem relação → cosseno claramente abaixo de 1) e o campo
`model` devolvido. Perfis integrados: OpenAI `text-embedding-3-small` (1536),
`text-embedding-3-large` (3072), `text-embedding-ada-002` (1536), Qwen
`text-embedding-v3`/`-v4` (1024).

Ambos estão também na interface web: na nova interface começam na página
**Auditoria** com o seletor de tipo de endpoint (**Embeddings**, **Reordenação**);
na clássica, na página **Ferramentas** (**Auditoria de embeddings**, **Auditoria
de rerank**). A auditoria de rerank usa sempre as sondas
integradas, para que cada execução continue comparável para a deriva e a
monitorização.

### Geração de imagem e áudio (TTS)

Geração de imagens (`POST /v1/images/generations`) e texto para voz
(`POST /v1/audio/speech`), descodificados apenas com a biblioteca padrão do
Python — dimensões da imagem a partir dos bytes de cabeçalho (PNG/JPEG/GIF/WebP),
duração WAV através de `wave`.

```bash
# Um relay que declara DALL·E 3 devolve mesmo o 1792x1024 pedido? Uma imagem reduzida
# ou de tamanho errado (ou fora dos tamanhos nativos do modelo declarado, segundo a
# base de conhecimento) é o principal sinal de «gato por lebre».
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Um relay que declara tts-1-hd devolve áudio real cuja duração cresce com a entrada
# (não um marcador fixo, nem HTML/JSON disfarçado de áudio)?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
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

## Utilização em CI (GitHub Action)

Condicione qualquer workflow a uma auditoria de relay com a action composta
incluída. Ela executa `zing check --compact --fail-on-risk`, expõe `risk` /
`score` / `rating` como saídas, escreve um resumo na execução e faz falhar o job
quando a barreira de risco dispara.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.20.0         # fixar numa tag de versão
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # segredo de quem chama; nunca é mostrado
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

A chave do relay é passada por uma variável de ambiente (`--api-key env:…`), pelo
que nunca aparece numa linha de comandos. Consulte [docs/CI.md](docs/CI.md) para
todas as entradas e saídas e um exemplo de barreira de implementação.

## Base de conhecimento

O zing avalia um relay segundo o **perfil** do modelo que declara: janela de
contexto nativa, saída máxima, data de corte do conhecimento, tokenizer,
capacidades, palavras-chave de identidade e impressões comportamentais. Os perfis
integrados cobrem OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM e
Moonshot (`zing kb` lista-os). Há três camadas; as posteriores prevalecem:

1. Perfis **integrados**, um ficheiro YAML por fornecedor em
   [`zing/knowledge/data/`](zing/knowledge/data).
2. **Um diretório com os seus próprios ficheiros YAML**: `--kb-dir ./my-profiles`
   (repetível) ou `ZING_KB_DIR`.
3. **As suas entradas** (`kb.db` no diretório de dados), adicionadas sem ficheiros
   YAML nem instalação editável:
   - na página **Conhecimento** da interface web (`/v2/kb`), com um separador
     para **Modelos**, **Provedores** e **Relays**. Cada separador lista o conjunto
     completo — incluídos, `ZING_KB_DIR` e os seus (marcados **Seu**) — com um
     filtro, um interruptor por item e um formulário **Adicionar …**: **Adicionar
     um modelo** → **Copiar o prompt de pesquisa** para o assistente de IA da sua
     escolha, carregar ou colar o YAML com que ele responde e depois **Verificar e
     salvar**; **Adicionar um provedor** aceita YAML de provedor da mesma forma;
     **Adicionar um relay** pede um nome e um URL base. **Qual perfil um ID de
     modelo usa?** mostra como um id é resolvido; as suas entradas podem ser
     exportadas como YAML;
   - na página **Auditoria** da interface web (na clássica, também **Ferramentas**): **Salvar na
     base** mantém o nome e o URL base de um relay (uma entrada de provedor sem
     modelos), listado em **Conhecimento → Relays**;
   - na linha de comandos: `zing kb-prompt <model>`, `zing kb-import <file>`
     (acrescente `--check` para apenas verificar) e `zing kb-export`.

Antes de guardar uma entrada, o zing verifica-a: esquema e limites, expressões
regulares perigosas, cada prompt que enviaria e ids de modelo que seriam
resolvidos para outro perfil. Um modelo seu com o id de um integrado substitui-o
(assinalado como *sombreando-o*), mas nunca altera as definições próprias de um
fornecedor integrado; as impressões são fundidas por id. Desativar um modelo,
provedor ou relay incluído na página **Conhecimento** também fica guardado em
`kb.db`: um id de modelo desativado deixa de ser resolvido e um provedor
desativado leva consigo os seus modelos e URLs base. `zing check` e `zing serve`
usam exatamente os mesmos perfis; `--no-user-kb` (ou `ZING_NO_USER_KB=1`) deixa de
fora as suas entradas e interruptores.

Um modelo com `identity_keywords` vazio não é guardado assim: o zing preenche
as suas próprias palavras de marca a partir dos nomes do fornecedor e do modelo
(por exemplo `glm` e `z.ai`) e mostra um
aviso para as verificar, pois sem elas a verificação de identidade poderia
tomar o próprio fabricante do modelo por uma marca rival. O prompt de pesquisa
pede-as explicitamente ao assistente de IA.

Cada relatório regista o perfil contra o qual auditou (`knowledge`: fornecedor,
modelo, como o id foi resolvido, a sua origem e um instantâneo completo com o seu
hash de conteúdo), pelo que um relatório continua verificável depois de a base de
conhecimento mudar.

## Relatórios

`zing check` e `zing compare` imprimem um veredito e escrevem o relatório em
`reports/` (`--out-dir`) como JSON, Markdown, HTML e PDF (`--format all`, a
predefinição); `--format json|md|html|pdf` escreve um único formato. `--json` e
`--compact` imprimem antes em stdout.

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

Um relatório contém o veredito (risco, confiança, pontuação, nota), as
constatações principais com recomendações, as pontuações por dimensão e os
**Dimension details**, as constatações de cada detector com as suas evidências, a
secção de desempenho, o perfil da base de conhecimento usado e os idiomas de
sonda. O texto controlado pelo relay é ocultado e escapado antes de ser escrito.

## Privacidade e dados locais

- **Apenas local.** `zing serve` só escuta em loopback (`127.0.0.1`, `::1`,
  `localhost`), só responde a esses nomes de anfitrião e recusa pedidos entre
  sites; não tem início de sessão porque nada fora da sua máquina o consegue
  alcançar. O zing só contacta os endpoints que configura (alvo, referência,
  juiz, webhooks); não descarrega nada em tempo de execução, nem sequer
  ficheiros de tokenizer.
- **Chaves.** Os relatórios e o histórico guardam apenas uma impressão de uma
  chave API. As chaves dos monitores são guardadas encriptadas em `watches.db`;
  a chave mestra que as desencripta nunca é escrita no diretório de dados
  (guarda-a você, consulte **Monitorização** acima), por isso uma cópia do
  diretório não revela nenhuma chave API. Mesmo assim, só o seu utilizador tem
  acesso ao diretório.
- **Diretório de dados.** `~/.zing` (ou `ZING_DATA_DIR`), criado com `0700` e
  ficheiros com `0600`: `history.db` (histórico de auditorias), `watches.db`
  (monitores, com as suas chaves encriptadas) e `kb.db` (as suas entradas da
  base de conhecimento). Apague o diretório para remover tudo.
  `zing data-dir` mostra onde está; `--data-dir CAMINHO` escolhe outro para uma
  execução, p. ex. `zing serve --data-dir .` guarda as bases de dados na pasta
  atual. São ficheiros SQLite normais que pode abrir para as suas próprias
  análises (de preferência só leitura enquanto o zing corre). Não faça commit
  de `watches.db` se essa pasta for um repositório.
  `history_metrics` guarda uma linha de valores medidos por execução e
  `history_requests` cada registo de pedido (guardado aí uma só vez, não dentro
  de cada relatório).

## Utilização responsável

O zing é uma ajuda de auditoria de caixa-preta. **Não consegue provar**:

- que um fornecedor guarda os seus prompts ou treina com eles,
- que encaminha sempre para um único modelo exato (os relays podem encaminhar de forma probabilística),
- fraude de faturação para lá do que a estimativa independente de tokens pode sugerir.

Use os relatórios para a sua própria diligência. **Não acuse publicamente um
fornecedor** com base numa única execução sem rever o tamanho da amostra, as
definições de custo e a lei local. Execute `zing compare` contra uma referência
de confiança antes de tirar conclusões fortes.

## Mais documentação

| Documento | Para |
|---|---|
| [Metodologia](docs/METHODOLOGY.pt.md) | Como funciona cada verificação, a sua escala de pontuação e as suas ressalvas |
| [Guia do programador](DEVELOPER_GUIDE.pt.md) | Arquitetura, ambiente de desenvolvimento, contribuições, traduções, Docker, versões |
| [docs/CI.md](docs/CI.md) | A GitHub Action: entradas, saídas, exemplos (em inglês) |
| [docs/DOCKER.md](docs/DOCKER.md) | Executar a interface web num contentor (em inglês) |
| [CHANGELOG.md](CHANGELOG.md) | O que mudou em cada versão (em inglês) |
| [SECURITY.md](SECURITY.md) | Reportar uma vulnerabilidade (em inglês) |

## Licença

[Apache-2.0](LICENSE)
