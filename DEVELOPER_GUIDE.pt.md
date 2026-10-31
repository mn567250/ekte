# ekte — Guia do programador

> [🇬🇧 English](DEVELOPER_GUIDE.md) · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · **🇵🇹 Português** · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md) · [🇳🇴 Norsk](DEVELOPER_GUIDE.nb.md)

Este guia é para quem altera o ekte: como está construído, como preparar um
ambiente de desenvolvimento, como contribuir e como é empacotado, executado em
Docker e publicado. O que o ekte faz e como usá-lo está no [README](README.pt.md);
como cada verificação funciona e é pontuada, na [Metodologia](docs/METHODOLOGY.pt.md).

---

## Índice

- [Princípios](#princípios)
- [Ambiente de desenvolvimento](#ambiente-de-desenvolvimento)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Arquitetura](#arquitetura)
  - [Fluxo de uma auditoria](#fluxo-de-uma-auditoria)
  - [Clientes](#clientes)
  - [Detectores e escalas de pontuação](#detectores-e-escalas-de-pontuação)
  - [Pontuação e veredito](#pontuação-e-veredito)
  - [Base de conhecimento](#base-de-conhecimento)
  - [Biblioteca de prompts](#biblioteca-de-prompts)
  - [Relatórios](#relatórios)
  - [Superfícies](#superfícies)
  - [Auditores autónomos](#auditores-autónomos)
  - [Servidor web](#servidor-web)
  - [HTTP API v1](#http-api-v1)
  - [Frontend web](#frontend-web)
  - [Dados locais](#dados-locais)
- [Contribuir](#contribuir)
  - [Pull requests](#pull-requests)
  - [Adicionar um detector](#adicionar-um-detector)
  - [Editar a base de conhecimento](#editar-a-base-de-conhecimento)
  - [Manter a base de conhecimento atualizada](#manter-a-base-de-conhecimento-atualizada)
  - [Alterar os prompts das sondas](#alterar-os-prompts-das-sondas)
  - [Alterar o esquema de uma base de dados](#alterar-o-esquema-de-uma-base-de-dados)
  - [Traduções](#traduções)
  - [Documentação](#documentação)
- [Testes](#testes)
- [Docker](#docker)
- [Integração contínua](#integração-contínua)
- [Publicação de versões](#publicação-de-versões)
- [Segurança](#segurança)
- [Licença](#licença)

## Princípios

O ekte é uma ajuda de auditoria de caixa-preta: a correção e **não acusar
injustamente relays honestos** importam mais do que apanhar todos os truques
possíveis. Tenha essa fasquia presente em qualquer alteração.

- **Evidências, não acusações.** As constatações reportam *desvio e risco*, nunca
  «fraude». Mais vale *inconclusivo* do que um palpite. Um novo caminho de
  gravidade ALTA precisa de evidências sólidas e reproduzíveis e deve ser difícil
  de disparar com um endpoint honesto.
- **Sem rede nos testes.** Os testes dos detectores correm contra o servidor
  simulado em processo de `tests/conftest.py` (httpx `MockTransport`), nunca
  contra uma API real.
- **Os segredos não saem.** As chaves de API ficam reduzidas a uma impressão e
  nunca são guardadas nos relatórios. Qualquer novo caminho de saída tem de
  passar o texto controlado pelo relay por `ekte.utils.redact` e escapá-lo para o
  seu formato.
- **As mesmas sondas para todos.** Os textos das sondas estão em inglês e são
  fixos, seja qual for o idioma da interface, para que o mesmo relay receba o
  mesmo veredito (ver [Biblioteca de prompts](#biblioteca-de-prompts)).
- **Apenas local.** O ekte só contacta os endpoints configurados pelo utilizador,
  e a interface web só escuta em loopback (ver [Servidor web](#servidor-web)).

## Ambiente de desenvolvimento

Requer Python 3.11+. Linux, macOS e Windows são testados na CI; os testes que só fazem sentido em POSIX são ignorados no Windows com um motivo explícito (`skipif(sys.platform == "win32", reason=...)`). Use `pathlib`, passe `encoding="utf-8"` na E/S de texto e nunca escreva `/tmp` fixo. O Node.js é opcional: os testes do JavaScript do navegador
correm com `node` e são ignorados sem ele.

```bash
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e '.[dev,web]'   # instalação editável com as ferramentas de desenvolvimento e a interface web
pytest                        # suite de testes
ruff check ekte tests         # lint
mypy ekte                     # verificação de tipos
```

Com uv: `uv venv && uv pip install -e '.[dev,web]'`. Não são precisas
bibliotecas de sistema, nem para os relatórios PDF.

Execute a partir do código-fonte com `ekte …` ou `python -m ekte …`. `ekte serve`
serve a interface web diretamente a partir de `ekte/web/static/`, pelo que
recarregar o navegador apanha as alterações do frontend; não há passo de build.

## Estrutura do repositório

```text
ekte/
  cli.py               CLI Typer: check, compare, models, kb*, serve, watch, embed, rerank, image, audio
  config.py            configuração YAML, referências a segredos (env:/file:), AuditOptions
  runner.py            run_audit(): liga tudo e executa os detectores
  context.py           AuditContext entregue a cada detector
  models.py            contratos de dados pydantic: TargetConfig, Finding, DetectorResult, AuditReport, …
  scoring.py           pontuações de dimensão, pesos, pontuação global, veredito de risco, confiança
  clients/             clientes HTTP: compatível com OpenAI, Anthropic Messages, OpenAI Responses
  detectors/           um ficheiro por detector, mais base.py (registo), scale.py, helpers.py
  judge/               o juiz LLM de confiança usado por quality_judge
  knowledge/           esquema, carregador, armazenamento do utilizador (kb.db), importação, prompt de pesquisa, instantâneos
    data/              perfis de fornecedores integrados (*.yaml)
  prompts/en.json      todo o texto que o ekte envia a uma API de LLM
  perf/                registo por pedido e a secção de desempenho do relatório
  report/              renderizadores JSON / Markdown / HTML / PDF e escrita
  embed_audit.py       auditor autónomo de embeddings e rerank
  media_audit.py       auditor autónomo de imagem e áudio (TTS)
  notify.py            alertas por webhook (Slack / Feishu / DingTalk / JSON genérico)
  datadir.py           o diretório de dados local e os seus ficheiros SQLite
  legacy.py            as definições ZING_* e a cópia de ~/.zing de antes da mudança de nome
  secretbox.py         encriptação dos segredos guardados; a chave mestra em memória
  i18n/                traduções partilhadas pela interface web e pelos alertas
    locales/           <code>.json por idioma, fragments/<feature>/<code>.json
  utils/               ocultação, análise SSE, estatística, estimativa de tokens
  web/
    server.py          app FastAPI: páginas, API JSON, fluxo SSE de auditoria, agendador de monitores
    jobs.py            trabalhos de auditoria em segundo plano e o bloqueio por relay
    security.py        escuta em loopback, lista de anfitriões permitidos, controlos de Origin/JSON, cabeçalhos
    history.py         armazenamento do histórico de auditorias (history.db)
    analytics_store.py as suas tabelas de análise: métricas por execução, registos de pedidos
    analytics.py       consultas de análise: KPI, séries temporais, classificações
    watches.py         armazenamento dos monitores (watches.db)
    masterkey.py       estados e ações da chave mestra (servidor e `ekte secret`)
    static/            scripts partilhados por todas as páginas (lang.js, i18n.js, icons.js, …)
    static/v2/         páginas, estilos e scripts da interface web
tests/                 suite pytest; conftest.py contém o relay simulado
docs/                  METHODOLOGY (8 idiomas), CI.md, DOCKER.md, PUBLISHING.md
examples/ekte.yaml     ficheiro de configuração comentado
action.yml             a action composta do GitHub
Dockerfile             imagem da interface web
```

## Arquitetura

### Fluxo de uma auditoria

`ekte check`, `ekte compare`, `ekte watch`, o fluxo de auditoria da interface web
e o seu agendador de monitores acabam todos na mesma função,
`ekte.runner.run_audit()`:

1. **Configuração.** `ekte/config.py` junta a configuração YAML e as opções de
   linha de comandos em `TargetConfig` (alvo, referência e juiz opcionais) e
   `AuditOptions` (suite, dimensões, dimensão das sondas, saída). As chaves de API
   dadas como `env:VAR` ou `file:/caminho` são resolvidas aqui.
   O formato é definido em `ekte/configfile.py` (uma tabela de chaves, tipos e valores padrão) e publicado como esquema JSON [`docs/schemas/config.schema.json`](docs/schemas/config.schema.json), regenerado com `uv run python -m ekte.configfile` (um teste falha se estiver desatualizado). `ekte/config.py` carrega o arquivo por ele, então todo comando o valida. Uma mudança de formato exige um novo `CURRENT_VERSION`, as renomeações em `RENAMES_FROM` (usadas por `ekte config migrate`) e uma entrada no changelog; uma chave obsoleta vai para `DEPRECATED` com a substituta. Veja a [política de estabilidade](docs/STABILITY.md#surface-config).
2. **Base de conhecimento.** `load_knowledge_base()` carrega os perfis
   integrados, `--kb-dir`/`EKTE_KB_DIR` e o `kb.db` do utilizador, e resolve o
   modelo **declarado** (por predefinição, o pedido) para um perfil. Um monitor
   passa em vez disso o seu instantâneo fixado.
3. **Clientes.** `make_client()` cria um cliente para o alvo (e a referência) no
   protocolo escolhido ou detetado automaticamente. Um `RequestRecorder` envolve
   cada chamada para a secção de desempenho.
4. **Detectores.** `select_detectors()` escolhe os detectores registados para a
   suite (ou as dimensões personalizadas), descartando os que precisam de um juiz
   ou de uma referência em falta. Correm **sequencialmente**, de propósito:
   pedidos concorrentes disparariam limites de taxa e distorceriam as medições de
   tempo (as sondas de fiabilidade e desempenho gerem a sua própria concorrência
   limitada). `run_detector()` cronometra cada um e transforma uma falha interna
   num resultado com estado **Erro**, para que uma resposta anómala do relay
   nunca interrompa a auditoria.
5. **Pontuação.** `scoring.build_dimensions()` e `build_verdict()` transformam os
   resultados dos detectores em pontuações de dimensão, pontuação global e nota,
   veredito de risco e a sua confiança.
6. **Relatório.** Tudo termina num `AuditReport` (`ekte/models.py`) com o alvo
   ocultado, o instantâneo do perfil da base de conhecimento, a secção de
   desempenho e os idiomas das sondas. A CLI renderiza-o e escreve-o; a interface
   web transmite-o.

`run_audit()` aceita um callback `on_event`; o servidor web transforma os seus
eventos (detector iniciado/terminado com constatações compactas, tempos por
pedido agrupados) em Server-Sent Events para a vista ao vivo.

### Clientes

`ekte/clients/` tem um cliente por protocolo — `openai_compatible.py` (Chat
Completions), `anthropic.py` (Messages) e `responses.py` (Responses) — com a
mesma interface, construídos sobre a mecânica HTTP comum de `base.py`.
`make_client()` em `clients/__init__.py` escolhe um conforme `--api` ou deteta-o a
partir do URL base e do modelo. Os detectores só falam com esta interface
(`RequestSpec` à entrada, `CompletionOutcome` à saída), pelo que são
independentes do protocolo.

Os clientes também adaptam os pedidos ao que o modelo aceita (`base.py`): o
runner preenche `unsupported_params` a partir do perfil, os parâmetros de
amostragem aí listados são omitidos e, no Chat Completions, um `max_tokens`
listado envia o limite como `max_completion_tokens`. Um 4xx que nomeia um desses
parâmetros acrescenta-o ao conjunto e repete o pedido uma vez adaptado (a
tentativa recusada é registada com a fase `param_retry`). Uma sonda que julga a
recusa em bruto define `RequestSpec.exact_params`.

### Detectores e escalas de pontuação

Um detector é um ficheiro autocontido em `ekte/detectors/`: uma subclasse de
`Detector` (`base.py`) com um `id`, um `name`, uma `dimension`, a primeira suite
em que corre (`min_suite`), um `cost_hint` aproximado para `--dry-run` e
`async def run(self, ctx) -> DetectorResult`. `@register` adiciona-o ao registo;
`ekte/detectors/__init__.py` importa cada módulo para que o registo fique
completo.

Cada detector publica a sua **escala de pontuação** (`SCALE`, construída com
`scale.py`): cada resultado possível de cada verificação com os seus pontos,
estado e gravidade. As constatações são criadas a partir da escala
(`SCALE.finding(check, outcome, …)`), pelo que relatório e comportamento não
podem divergir. `Scale` pontua com a média das suas verificações;
`DeductionScale` parte de 100 e desconta ou limita. A interface web mostra a
escala em **Escala de pontuação**; a [Metodologia](docs/METHODOLOGY.pt.md)
reproduz cada escala. `connectivity.py` é o exemplo canónico e mais curto.

Os detectores partilham um único event loop com todas as outras auditorias do
`ekte serve`, pelo que o trabalho que exige muito CPU não pode correr nele: um
loop bloqueado atrasa os pedidos das outras auditorias e inflaciona as
latências que registam. `helpers.build_filler()` constrói o texto de
enchimento em tempo linear e guarda em cache os últimos tamanhos, e os
detectores da janela de contexto e da cache de prompts chamam-no (e a
`build_haystack()`) através de `asyncio.to_thread`. As contagens de tokens vêm
de `ekte/utils/tokenize.py`, uma heurística só com a biblioteca padrão: o ekte
não importa nenhuma biblioteca de tokenizer e não descarrega nada em tempo de
execução, pelo que funciona em ambientes restritos. O argumento `tokenizer` de
`estimate_tokens()` é aceite mas não altera a contagem, e os campos do
relatório `tokens_exact` / `exact_tokenizer` são mantidos por compatibilidade e
são sempre false.

### Pontuação e veredito

`ekte/scoring.py` contém `DIMENSION_WEIGHTS` e as regras do veredito: a pontuação
de uma dimensão é a média com peso igual dos seus detectores, a pontuação global a
média ponderada das dimensões executadas, e o nível de risco segue a escala de
gravidade descrita em
[Metodologia → Como o ekte pontua](docs/METHODOLOGY.pt.md#como-o-ekte-pontua).
Cada dimensão regista como foi calculada em `DimensionScore.breakdown`, que
alimenta os **Dimension details** dos relatórios e as linhas expansíveis das
**Verificações por dimensão** da interface web.

### Base de conhecimento

`ekte/knowledge/` define o esquema dos perfis (`schema.py`: `ProviderProfile`,
`ModelProfile`, `FingerprintProbe`), carrega e funde as camadas (`loader.py`:
YAML integrado → `EKTE_KB_DIR`/`--kb-dir` → o `kb.db` do utilizador), guarda as
entradas do utilizador (`store.py`), verifica e importa YAML (`importer.py`),
constrói o prompt de pesquisa para assistentes externos (`research.py`) e tira um
instantâneo do perfil usado por uma execução (`snapshot.py`). Os ids de modelo
resolvem-se de forma exata, através de aliases ou pelo nome normalizado,
restringidos pelo fornecedor declarado. A alternativa aproximada usa o nome da
KB mais longo contido no id declarado (um id de snapshot ou decorado), a menos
que o resto do id nomeie outro nível ou variante (`-mini`, `-lite`, `-image`,
…); um id truncado só se resolve quando o nome de um único modelo começa por
ele, pelo que um id ambíguo como `gpt-4` fica sem perfil em vez de um nível
adivinhado. Cada relatório regista como o id foi resolvido.

`load_knowledge_base()` guarda em cache os resultados fundidos e, por
predefinição, devolve uma cópia profunda, pelo que quem a chama pode alterar o
que recebe. Quem só a lê (as listas e o catálogo da interface web, a resolução
de um modelo) passa `copy=False` e obtém a instância partilhada em cache, que
não pode alterar.

Os relays também são endpoints: `relays.py` transforma os `base_url_hints` de
um provedor em URL base utilizáveis (`GET /api/kb` → `base_urls`) e guarda um
relay a partir da interface web como entrada de provedor em `kb.db` (`origin =
relay`: um `display_name` e um URL base, sem modelos; sem alteração de esquema).

### Biblioteca de prompts

Todo o texto que o ekte envia a uma API de LLM — sondas de chat, o prompt do
juiz, esquemas de ferramentas, entradas de embeddings / rerank / imagem / áudio —
está em `ekte/prompts/en.json` e lê-se com `ekte.prompts.text()` / `get()`.
`{{name}}` marca um valor preenchido em tempo de execução. O idioma das sondas
está fixado em inglês (`PROBE_LANG`), independentemente do idioma da interface,
porque as verificações de respostas e as estimativas de tokens estão calibradas
para esses textos exatos. As sondas cujo idioma *é* a medida (p. ex. fluência em
chinês, tokenizer ou autoidentificação de modelos chineses) vivem com as suas
respostas esperadas na base de conhecimento e declaram `prompt_lang` e um motivo
`language_bound`. O runner regista os idiomas usados em `prompt_languages`.

### Relatórios

`ekte/report/render.py` renderiza um `AuditReport` como JSON, JSON compacto para
agentes, Markdown e HTML; `dimensions.py` e `performance.py` renderizam os
**Dimension details** e a secção de desempenho; `pdf.py` compõe o PDF com o
ReportLab a partir dos mesmos dados e funções (Python puro; apenas os tipos de
letra PDF padrão, com o tipo de letra CID STSong-Light para o chinês, pelo que
nada é incorporado; sem nunca carregar recursos externos), partilhado pela CLI e
pela interface web;
`writer.py` escreve os ficheiros. Todo o texto controlado pelo relay é ocultado e
escapado (HTML / Markdown) antes da saída. `POST /api/report/export` da interface
web reutiliza estes renderizadores para a linha **Transferir relatório**, com os
textos legíveis traduzidos para o idioma da interface.

### Superfícies

A **superfície** é o tipo de endpoint auditado: `chat` (predefinição),
`embedding` ou `rerank` (`ekte.config.SURFACES`; mais tarde imagem, TTS). É um
segundo eixo ao lado da suite, transportado por `AuditOptions.surface`,
`AuditReport.surface` e por uma coluna `surface` anulável em `history.db` e
`watches.db` (`NULL` e um campo JSON em falta significam `chat`; sem migração).

- Os detetores declaram `surface: ClassVar[str]`; `select_detectors` filtra por
  ela antes do nível da suite. Os detetores de embeddings e rerank reutilizam as
  dimensões existentes.
- Os pesos da pontuação e os conjuntos de dimensões de perfil / núcleo /
  infraestrutura são por superfície (`scoring.SURFACE_WEIGHTS`); o chat mantém os
  seus valores.
- O gravador marca as chamadas de embeddings com `op="embed"` e as de rerank com
  `op="rerank"` (`ekte.config.SURFACE_OPS`); as funções de `perf/summary.py`
  aceitam um parâmetro `op` (predefinição `complete`).
- `embed_audit.run_embedding_audit()` e `run_rerank_audit()` (usadas por
  `ekte embed` / `ekte rerank`) executam o runner
  com `surface="embedding"` ou `"rerank"`, passam a execução guardada anterior da
  mesma superfície como `previous_report` (deriva) e guardam o relatório salvo
  indicação em contrário (`--no-save`).
- Detetores de rerank: `rerank.connectivity`, `rerank.known_answer`
  (CAPABILITY), `rerank.identity` e `rerank.drift` (MODEL_IDENTITY),
  `rerank.determinism` (RELIABILITY) e `performance.rerank`. Pesos:
  MODEL_IDENTITY 30, CAPABILITY 30, PERFORMANCE 20, RELIABILITY 10,
  CONNECTIVITY 10.
- Monitores: a `surface` e `embedding_dimensions` (0 = da base de conhecimento) de
  um monitor alimentam `AuditOptions` em `_run_one_watch_inner`; um monitor de
  embeddings ou rerank lê a sua referência de deriva com
  `history.latest_for(..., surface=...)` antes da auditoria e compara os alertas
  apenas com execuções da mesma superfície. A superfície fixa-se na criação
  (`POST /api/watches`, `/api/watches/from-history/{id}`, que também aceita
  `embedding_dimensions`) e o `PATCH` não a altera; o `PATCH` altera
  `embedding_dimensions` de um monitor de embeddings (o cartão de Monitores v2
  edita-o em linha).

### Auditores autónomos

Imagem/áudio (`media_audit.py`) ainda não são superfícies, por isso têm os seus
próprios pequenos auditores com o seu próprio veredito em vez do pipeline de
detetores. Partilham as definições HTTP dos clientes, a base de conhecimento
(dimensões nativas, tamanhos de imagem, vozes) e a biblioteca de prompts. Toda a
descodificação (cabeçalhos de imagem, WAV) usa apenas a biblioteca padrão.

### Servidor web

`ekte/web/server.py` é uma app FastAPI criada por `create_app()`:

- **Páginas.** A interface web (`/`, `/history`, `/watches`,
  `/analytics`, `/kb`, `/accessibility`) é HTML estático servido na raiz; os scripts e
  estilos ficam em `/static/`. Não há página Ferramentas: as auditorias de embeddings e rerank
  começam na página de auditoria com o seletor de tipo de endpoint
  (`/?surface=embedding|rerank`). Até à 1.0.0 os endereços anteriores redirecionam (308) para a
  página na raiz, com a query string: `/v2/…` (`/v2/tools` vai para
  `/?surface=embedding`, e `#rerank` escolhe rerank) e `/tools` e `/console` da interface
  clássica removida. Estes redirecionamentos estão obsoletos e são removidos na 1.0.0.
- **API.** `/api/jobs…` executa as auditorias (ver abaixo); `/api/models` lista
  os modelos de um relay; `/api/report/export` renderiza um relatório;
  `/api/history…`, `/api/watches…`, `/api/kb…` e `/api/analytics…` servem as
  restantes páginas. Todos são internos; o subconjunto público é [HTTP API v1](#http-api-v1).
- **Relays.** `POST /api/kb/relays` guarda um relay `{name, base_url}` (400 para
  dados inválidos, 409 se o nome ou o URL já forem conhecidos).
- **Análises.** `GET /api/analytics/options` (relays, modelos, suites, modos de
  stream, API e o intervalo de datas do histórico), `/api/analytics/summary`
  (KPI de `from`–`to` face ao intervalo anterior com a mesma duração),
  `/api/analytics/series` (`metric` por `group=relay|model|relay_model`, até 4
  `keys`, em intervalos `bucket=hour|day|week|dow_hour` no fuso horário do
  utilizador, `tz` ou `tz_offset`; `dow_hour` aceita também `block` (horas por linha) e
  `fold=week|4weeks|month_week`, que volta a `week` até as execuções cobrirem
  90 ou 180 dias) e `/api/analytics/leaderboard` (`model=` para
  os seus relays, ou `relay=` para os seus modelos). Todos aceitam os filtros
  `from`, `to`, `suite`, `stream_mode`, `api`, `source=all|manual|monitor`,
  `relay` e `model`. `ekte/web/analytics.py` calcula tudo em Python a partir de
  `history.analytics_runs()`: os ids de métrica vêm de uma lista fixa, os relays
  são agrupados pela sua entrada na base de conhecimento no momento da
  consulta, um valor que uma execução não mediu fica de fora (cada valor tem o
  seu `n` e a sua `coverage`) e os intervalos com menos de `MIN_RUNS` (3)
  execuções são marcados `low_n`. Um parâmetro inválido responde 400; as
  respostas são `Cache-Control: no-store`.
- **Painéis de análise.** `/api/analytics/breakdown` (até 8 `metrics` por
  `group=relay|model|relay_model|all` no período), `/api/analytics/errors` (as
  chamadas de conclusão ao destino por classe de resultado
  `success|client_4xx|rate_limited|server_5xx|timeout|network|other`, por
  `group=relay|model` e por `bucket`, contadas em SQL por
  `history.analytics_request_classes()` sem carregar as linhas de pedidos; a
  hora de uma chamada é o início da sua auditoria mais o seu desvio, ao minuto;
  `covered` = auditorias com registos de pedidos) e `/api/analytics/integrity`
  (contagens de aprovado / aviso / falha dos detetores de identidade,
  capacidades, visão, streaming, protocolo, integridade, prompt injetado e
  conectividade por relay × modelo, a proporção de modelos divergentes e a
  mediana da janela de contexto medida / declarada). `/api/analytics/series`
  também aceita `group=all`. Mesmos filtros e erros que acima.
- **Auditorias em segundo plano.** `jobs.py` executa cada auditoria como um
  trabalho do servidor. `POST /api/jobs` coloca um em fila, `GET /api/jobs`
  lista os trabalhos em fila, em curso e acabados há pouco (e os monitores em
  execução) com o progresso, `GET /api/jobs/{id}/events` reproduz o registo de
  eventos e depois segue-o ao vivo por SSE, e `POST /api/jobs/{id}/cancel`
  pára-o. A interface web usa-os, por isso uma auditoria sobrevive à página. Um bloqueio por relay deixa uma só auditoria (ou
  execução de monitor) usar um relay de cada vez, por nome de host, com todos os
  endereços loopback como um host; no máximo `EKTE_MAX_PARALLEL_AUDITS`
  (4 por omissão) em simultâneo, por ordem de chegada.
- **Agendador de monitores.** O lifespan da app lança um ciclo em segundo plano
  que inicia cada monitor devido como uma tarefa própria, pelo que monitores em
  relays diferentes auditam ao mesmo tempo; o bloqueio por relay continua a
  aplicar-se, por isso os monitores podem ocupar as vagas de
  `EKTE_MAX_PARALLEL_AUDITS` e uma auditoria manual pode ficar em fila atrás
  deles. O `last_run_ts` de uma execução é o momento em que a sua auditoria
  começa (depois de esperar pelo seu relay). Cada execução é registada no
  histórico; a verificação de regressão compara-a com a execução guardada mais
  recente do mesmo alvo e modelo (`history.latest_for()`, uma única consulta
  indexada) e envia os alertas por webhook (`ekte/notify.py`) em simultâneo ao
  ultrapassar um limite ou ao piorar. `POST /api/watches/{id}/run` responde 409
  quando o agendador acabou de iniciar esse monitor; uma reposição da chave
  mestra cancela as execuções agendadas que ainda não começaram, e o
  encerramento cancela as execuções em curso.
- **Compressão e cache.** `caching.py` comprime com gzip as respostas de 1 KiB ou
  mais (exceto Server-Sent Events) para os clientes que o aceitam (`gzip;q=0`
  recusa). As páginas e `/locales.js` são comprimidos uma vez quando são gerados
  e servidos já comprimidos com `Content-Encoding: gzip`,
  `Vary: Accept-Encoding` e um ETag próprio terminado em `-gz`; as páginas são
  servidas através de `html_page(page, request.scope)`, pelo que seguem esse
  caminho e respondem 304 a pedidos condicionais. Os URL locais de scripts e
  folhas de estilo nas páginas levam um `?v=<hash do conteúdo>` e ficam em
  cache como imutáveis.
- **Segurança.** `security.py` resolve o endereço de escuta (apenas loopback,
  exceto num contentor detetado com `EKTE_CONTAINER=1`) e instala
  `LocalOnlyMiddleware`: uma lista de anfitriões permitidos contra DNS rebinding,
  controlos de `Origin` e `Sec-Fetch-Site` contra CSRF, corpos de pedido apenas
  JSON e cabeçalhos anti-iframe / no-sniff / no-referrer. A interface não tem
  início de sessão por design.

### HTTP API v1

A parte pública da API HTTP fica em `/api/v1/` e segue a [política de estabilidade](docs/STABILITY.md#surface-http-api): só muda de forma incompatível numa versão maior, após um período de descontinuação. Qualquer outro caminho em `/api/` é interno e pode mudar em qualquer versão. As respostas internas levam `X-Ekte-API: internal` e as de v1 `X-Ekte-API: v1`. A interface web usa os caminhos internos.

| Endpoint | Pedido | Resposta |
|---|---|---|
| `POST /api/v1/jobs` | corpo JSON com `base_url`, `model` e, opcionalmente, `api_key`, `claimed_model`, `suite`, `surface`, `dimensions`, `baseline` | 200 e a tarefa; 400 se a entrada for inválida |
| `GET /api/v1/jobs/{id}` | nenhum | 200 e a tarefa; 404 se o id for desconhecido |
| `GET /api/v1/jobs/{id}/events` | nenhum | 200 e `text/event-stream`: os eventos da tarefa até agora e depois ao vivo, até `done`; 404 se o id for desconhecido |
| `GET /api/v1/history` | `limit` (1–500, predefinição 50) e `perf`, opcionais | 200 e um array JSON de resumos de execuções, as mais recentes primeiro |
| `GET /api/v1/history/{id}` | nenhum | 200 e o relatório guardado tal como está; 404 se o id for desconhecido |

Uma tarefa tem `id`, `status` (`queued`, `running`, `done`, `error` ou `cancelled`), campos de progresso, `report_id` quando o relatório está guardado, e `error`; a chave de API nunca é devolvida. Cada evento é uma linha SSE `data: {JSON}` com um `type`; o evento `report` leva o relatório e o seu `report_id`, e `done` é sempre o último. Os clientes ignoram os tipos de evento e os campos que não conhecem.

Todo o erro é JSON com um único campo, `error`, com uma mensagem legível, e um destes códigos de estado: 400 (pedido inválido), 404 (não encontrado), 403 (pedido entre sites ou entre origens recusado), 415 (o corpo não é JSON), 421 (host desconhecido).

```json
{"error": "not found"}
```

- **Apenas local.** As proteções do servidor web aplicam-se a `/api/v1/` como a qualquer caminho: ligação a loopback por predefinição, a verificação do Host, a recusa de escritas entre sites e corpos apenas JSON. Respondem no mesmo formato de erro.

### Frontend web

O frontend é HTML, CSS e JavaScript de navegador simples, sem módulos nem passo
de build. As páginas estão em `ekte/web/static/v2/` e partilham um cabeçalho (`nav.js`), o renderizador de
relatórios (`report.js`), o seletor de tema (`theme.js`) e os estilos
(`tokens.css`, `ekte.css`, `fields.css`, `report.css`, `perf.css`). Os scripts partilhados são
servidos a partir da raiz: `lang.js` (mudança de idioma), `locales.js` (dados de
tradução), `i18n.js` (tradução das constatações), `icons.js` (com o logótipo do
ekte), `secretfield.js` e `perf.js` (gráficos de desempenho).
Cada cor da interface v2, nos dois temas, é um token em `v2/tokens.css`
(escrito uma só vez como `light-dark(<claro>, <escuro>)`); todos os outros
estilos, páginas e scripts da v2 usam apenas `var(--…)`, nunca uma cor literal.

Cada página v2 exceto Acessibilidade tem um **aviso de página** logo abaixo do
hero (`<div class="znote" id="note">`, desenhado por `v2/notice.js`, com o estilo
`.znote` em `ekte.css`): `EkteNotice.show(el, {level, title, detail, items,
actions})`; o nível `info`, `success`, `warning` ou `critical` define a
tonalidade, a margem e o ícone (critical é `role="alert"`, os outros
`role="status"`; mostrar o mesmo aviso outra vez não muda nada). A página escolhe
a mensagem mais importante e lista as outras em `items`. Auditoria: servidor
inacessível / auditorias em curso / a execução guardada mais recente / executa
localmente; Histórico: histórico ilegível / execuções dos monitores em pausa
(chave mestra bloqueada) ou execuções antigas ainda em processamento / número de
execuções; Análises: dados ilegíveis / execuções ainda fora dos gráficos ou com
hora de início estimada / em que se baseia; Conhecimento: falha ao carregar /
entradas ignoradas / itens desativados / completa. Monitores mantém a sua barra
da chave mestra (`masterkey.js`), com o mesmo aspeto e lugar. Os números de todo
o histórico vêm de `GET /api/history/status` (`history.status()`: número de
execuções, a mais antiga e a mais recente, linhas que o backfill das análises
ainda não processou, execuções com hora de início estimada).

A página v2 **Auditoria** configura relays com
`v2/relaycfg.js`: escolha de relay/provedor → URL base → os modelos do relay
(`/api/models`, ao mudar, em cache por URL/chave/protocolo) → modelo declarado da
base de conhecimento (`/api/kb/resolve` pré-seleciona-o) → provedor derivado,
mais **Salvar na base** (`POST /api/kb/relays`). As suas funções puras são
testadas com node.

A página v2 **Análises** (`v2/analytics.html`) só lê `/api/analytics/*`
(`options` também lista os pares relay × modelo, `relay_models`, para o seletor
de séries). Tem uma `<section class="card panel">` por painel sob uma única
barra de filtros, por isso podem juntar-se painéis; filtros e vista ficam no
fragmento do URL (`#range=30&metric=score&…`) e em `localStorage`. Os gráficos
vêm de `v2/charts.js` (`EkteCharts.timeChart`: SVG inline desenhado à mão com
linha mediana, faixa p25–p75, lacunas para intervalos vazios, marcadores
esbatidos para intervalos `low_n`, linhas de anotação e tooltip ao passar o
ponteiro; `fmt` / `fmtDelta` formatam valores pela unidade) e de
`v2/charts.css` (quatro cores de série validadas por tema, distinguíveis também
pela forma do marcador). Cada gráfico existe também como tabela de dados.

Cada painel é autónomo: um registo `PANELS` no script da página indica o id da
sua secção, `load()` (obter com os filtros e a vista atuais e desenhar) e
`render()` (redesenhar a partir dos dados carregados, p. ex. ao mudar de
idioma), pelo que os painéis podem ser reorganizados sem se afetarem.
`EkteCharts.heatmap` desenha a grelha dia da semana × hora (escala sequencial
de um tom em cinco níveis por tema, células tracejadas para `low_n`, células
vazias só com contorno), `EkteCharts.stackBars` as barras de erros empilhadas,
e `timeChart` aceita uma linha `ref` (rácio de faturação de 100%).
`EkteCharts.donut` (um anel de partes de um todo com um número HTML no centro)
e `EkteCharts.meter` (uma barra fina de partes) desenham o cartão Cobertura do
relatório de acessibilidade; as suas cores `k-*` (quem decide um passo: azul o
conjunto de testes, violeta uma pessoa) vêm de `tokens.css`.
`v2/chartmotion.js` (`EkteMotion.enter`) desenha um anel no sentido dos
ponteiros do relógio e faz crescer as barras a partir da esquerda, como nos
outros gráficos, só quando chegam dados novos e nunca com movimento reduzido ou
com a animação desligada no cabeçalho.

O cabeçalho da página e o painel de filtros ficam acima de cinco separadores
internos (`v2/tabs.js`, como em Conhecimento): cada
entrada de `PANELS` indica o seu `tab`, e só os painéis do separador visível
carregam; uma alteração de filtro recarrega esse separador e marca os outros
como desatualizados (`activate()` carrega-os quando mostrados). Aqui `tabs.js`
recebe `writeHash: false`, porque a página escreve ela própria toda a vista no
fragmento — `#tab=trends&range=30&suite=…&metric=…` (`stateQuery()`), que
**Copiar a ligação para esta vista** copia (um campo só de leitura selecionado
quando a API da área de transferência falta ou recusa); um fragmento sem `tab`
abre a Visão geral, e uma ligação colada (`hashchange`) volta a ler a vista. O
painel de filtros recolhível é `v2/filterpanel.js` + `v2/filterpanel.css`,
partilhado com o Histórico, Monitores e Conhecimento: `EkteFilterPanel.create(section, {label, title,
storeKey, open, onReset})` devolve `render({body, foot, count, summary})`,
`sync({count, summary})`, `setOpen()` e `focusStart()`; a página tem os seus
filtros e campos, o painel o botão com o distintivo de filtros ativos, o resumo
de uma linha mostrado quando recolhido, o estado aberto memorizado e
**Redefinir filtros**.

**Convenção de tradução.** O texto chinês escrito no HTML é o original e não se
altera; cada elemento leva o seu texto inglês em `data-en` (e
`data-en-placeholder`, `data-en-title`, `data-en-aria-label`). O texto inglês é a
chave de pesquisa para todos os outros idiomas. Os scripts usam `T(zh, en)` para
texto dinâmico e `EKTE_LANG.server(text)` para texto vindo do backend (nomes de
detectores, recomendações, frases do veredito).

### Dados locais

`ekte/datadir.py` gere `$EKTE_DATA_DIR` (por predefinição `~/.ekte`), criado com
`0700`, com ficheiros SQLite `0600`: `history.db` (`web/history.py`),
`watches.db` (`web/watches.py`, que guarda encriptadas as chaves API dos
monitores) e `kb.db` (`knowledge/store.py`). Cada chamada abre uma ligação de
curta duração, pelo que os armazenamentos são seguros no pool de threads do
FastAPI. A opção global `--data-dir` (também em `ekte serve`) limita-se a
definir `EKTE_DATA_DIR` com o caminho absoluto, e `ekte data-dir` mostra o
diretório resolvido. Um diretório que já existe mantém as suas permissões; só o
`~/.ekte` predefinido é restringido a `0700`. As linhas do histórico estão
indexadas por alvo e modelo (`idx_history_target`), que `history.latest_for()`
usa para encontrar a execução anterior de um monitor.

Desde a versão 2 do esquema (`PRAGMA user_version`), `history.db` também
contém as tabelas de análise, definidas em `web/analytics_store.py`:
`history_metrics` (uma linha de métricas extraídas por execução: hora de
início, taxas, percentis de latência/TTFT/descodificação, rácios de faturação,
número de constatações e mais; NULL onde a execução não mediu um valor),
`history_dimensions` (pontuações de dimensões e detectores) e `history_requests`
(os registos de pedidos da execução, alvo e baseline, pela ordem da lista). Os
`performance.requests` de um relatório ficam só aí: `save()` retira-os de
`report_json` (`requests_split` marca a linha) e `get()` / `latest_for()`
repõem-nos, de modo que um relatório é lido de volta idêntico ao que foi
guardado; o que as colunas não conseguem reproduzir com exatidão vai para a
coluna JSON `extra`. `extract_metrics()` é pura e versionada
(`EXTRACT_VERSION`). Após a migração, um backfill por lotes (uma transação curta
por lote, idempotente) move os registos das linhas antigas, extrai as suas
métricas e volta a extrair as linhas escritas por uma `EXTRACT_VERSION`
anterior; `history.backfill_analytics()` volta a executá-lo quando necessário.
A hora de início de uma execução é o `started_at` do relatório; os relatórios
anteriores a esse campo recebem `generated_at` menos o intervalo dos seus
registos de pedidos (`started_at_estimated` = 1).

Onde ficam as chaves de API dos monitores é escolha do utilizador
(`watches.get_key_storage()`, uma linha de `secret_meta`): `memory`, a
predefinição, não guarda nenhuma — a coluna `api_key` tem apenas o marcador
`mem:` e a chave vive em `watches._memory_keys` até o processo terminar (após um
reinício a linha fica `key_missing`, que o agendador trata como uma chave
bloqueada: a execução aguarda, sem alerta); `encrypted` guarda-as como descrito
abaixo. Sem linha, um armazenamento que já tem chaves cifradas ou um valor de
verificação, ou com `EKTE_SECRET_KEY` / um `secret.key` antigo, começa em
`encrypted`; a escolha é registada no arranque. `Vault.set_storage()`
(`POST /api/secret/storage`) muda o modo e move as chaves numa transação
(`keys_to_memory()` apaga as cifradas e o valor de verificação e limpa o
ficheiro; `keys_to_store()` sela as que estão em memória). Um pedido pode passar
`key_storage: "memory"` para manter a sua chave fora da base de dados seja qual
for a definição; nada pode forçar o armazenamento.

As chaves API guardadas são encriptadas por `ekte/secretbox.py` (Fernet,
guardadas como `enc:v1:…`; as referências `env:`/`file:` ficam como estão). A
chave mestra nunca é guardada: `web/masterkey.py` (`Vault`, partilhado pelo
servidor e pelo `ekte secret`) mantém-na na memória do servidor assim que chega
de `EKTE_SECRET_KEY`, de um `secret.key` antigo ou do utilizador na página
Monitores, e `watches.db` guarda apenas um valor de verificação (`secret_meta`)
que rejeita uma chave errada. Uma chave nova volta a encriptar cada chave
guardada e reescreve o valor de verificação numa única transação. A chave vive
na memória de um só processo, por isso execute um servidor por diretório de
dados.

`ekte/legacy.py` mantém a funcionar as instalações de antes da mudança de nome:
cada definição `EKTE_*` é lida com `legacy.getenv`, que recorre ao nome antigo
`ZING_*` (indicado uma vez no stderr), e `datadir.data_dir()` copia `~/.zing`
para `~/.ekte` uma única vez quando só existe o diretório antigo (ficheiros
SQLite através da API de backup, para um diretório temporário ao lado que depois
é renomeado). `~/.zing` nunca é alterado nem apagado. `lang.js` copia da mesma
forma as definições `zing.*` do navegador para `ekte.*`, e o servidor continua a
ler os cookies `zing_lang` / `zing_ui` enquanto os `ekte_*` não existirem. Tudo isto está obsoleto e é removido na 1.0.0 (os avisos indicam essa versão); o ekte nunca apaga um `~/.zing` antigo.

## Contribuir

### Pull requests

- Mantenha `pytest`, `ruff check ekte tests` e `mypy ekte` a verde (a CI executa
  os três com Python 3.11–3.14).
- Descreva o truque de relay ou o falso positivo que a alteração resolve.
- Atualize `CHANGELOG.md` em `[Unreleased]`.
- Atualize a documentação afetada — README, este guia, a Metodologia — em
  **todos os idiomas** (ver [Documentação](#documentação)).

Ao contribuir, aceita que as suas contribuições fiquem sob a licença
[Apache-2.0](LICENSE) do projeto.

### Adicionar um detector

1. Crie `ekte/detectors/<name>.py` e importe-o em `ekte/detectors/__init__.py`.
2. Defina a sua `SCALE` (`Scale` ou `DeductionScale` de `scale.py`) com cada
   resultado de cada verificação, e crie constatações apenas através dela.
3. Derive de `Detector`; defina `id`, `name`, `dimension`, `min_suite` e
   `cost_hint`; ponha `requires_judge = True` ou `requires_baseline = True` se
   precisar de um juiz ou de uma referência, ou redefina `applies()` para outras
   condições. Decore a classe com `@register`.
4. Implemente `async def run(self, ctx) -> DetectorResult` a partir de
   `self.new_result(scoring=SCALE.scoring())`. Envie os pedidos através de
   `ctx.client` e tire cada prompt de `ekte/prompts/en.json`.
5. Acrescente testes de comportamento para o caminho sinalizado e para o limpo,
   com o relay simulado de `tests/conftest.py`.
6. Traduza os novos títulos e resumos de constatações (ver
   [Traduções](#traduções)) e documente o detector e a sua escala em cada
   ficheiro de [Metodologia](docs/METHODOLOGY.pt.md).

### Editar a base de conhecimento

Os perfis estão em `ekte/knowledge/data/<provider>.yaml`, um ficheiro por
fornecedor. Cada modelo tem a sua janela de contexto nativa, saída máxima, data de
corte do conhecimento, tokenizer, modalidades, capacidades, parâmetros não
suportados, palavras-chave de identidade e impressões (ver
`ekte/knowledge/schema.py`). Quando alterar um campo numérico, **cite uma fonte
fidedigna** (a ficha oficial do modelo, preços ou documentação do fornecedor) no
pull request: um valor errado provoca falsos positivos contra relays honestos.
`ekte kb-import --check <ficheiro>` faz as mesmas verificações que a importação do
utilizador (esquema, limites, expressões regulares perigosas, prompts, colisões de
ids).

As `fingerprints` ao nível do fornecedor correm em cada um dos seus modelos. Uma
sonda cuja expectativa só vale para alguns modelos (uma data de corte, um teste
de conhecimento do nível Pro, uma armadilha de raciocínio) pertence às
`fingerprints` desses modelos; caso contrário, a resposta verdadeira de outro
modelo conta como divergência.

Preencha sempre `identity_keywords` com as palavras do fabricante e da família
com que o modelo se identifica. A verificação de identidade conta também a
chave do fornecedor, o nome de apresentação e o id do modelo como marca
genuína, alargados aos restantes nomes do fabricante em `VENDOR_BRANDS`
(`ekte/knowledge/identity.py`, que é também a lista de marcas rivais do
detetor); a importação preenche palavras-chave vazias a partir destes nomes com
um aviso. As palavras de marca de um novo fabricante acrescentam-se aí como um
grupo.

### Manter a base de conhecimento atualizada

Os dados de fornecedores e modelos envelhecem depressa e cada veredito depende
deles, por isso o ekte é transparente quanto à sua idade. Cada perfil de
fornecedor incluído tem `last_verified`, a data em que os seus dados foram
conferidos pela última vez com a documentação do fornecedor. A mais antiga
dessas datas é a **data da base de conhecimento**: é guardada em cada relatório
(`knowledge.kb_date`), mostrada por `ekte kb` e nos relatórios Markdown, HTML e
PDF, e exposta por `ekte kb --json`. Se for anterior a `STALE_AFTER_DAYS` (180
dias, em `ekte/knowledge/freshness.py`), o relatório recebe um aviso que remete
para atualizar o ekte ou adicionar entradas próprias. O aviso nunca altera o
veredito.

O processo de atualização:

- **Fontes.** Apenas páginas oficiais do fornecedor: lista e fichas de modelos,
  páginas de preços e limites, avisos de descontinuação e retirada e notas de
  versão. Inclua o link no pull request.
- **Quem.** Os mantenedores. Qualquer pessoa pode propor uma alteração com o
  formulário de issue «Knowledge base update» (fornecedor, id do modelo,
  alteração, link da fonte e a sua data) ou com um pull request.
- **Com que frequência.** Pelo menos antes de cada versão menor e, fora do
  calendário, numa versão de correção quando ocorre uma mudança importante de
  modelos (um lançamento principal, uma retirada, um id de modelo renomeado). A
  lista de verificação de versões inclui-o.
- **Revisão.** Um pull request que altere `ekte/knowledge/data/*.yaml` precisa de
  uma fonte citada para cada valor alterado e de uma segunda revisão, e
  `ekte kb-import --check` tem de passar. Atualize `last_verified` de um
  fornecedor só depois de conferir todo o seu ficheiro, não apenas as linhas
  alteradas.
- **Registo de alterações.** Toda a alteração aos dados incluídos consta de
  `CHANGELOG.md`, porque pode mudar vereditos.

### Alterar os prompts das sondas

Os textos das sondas são dados de calibração. Alterar um em
`ekte/prompts/en.json` pode mudar as verificações de respostas, as estimativas de
tokens e, portanto, os vereditos; ajuste o detector e os seus testes em
conformidade e mencione a alteração no CHANGELOG. Nunca faça uma sonda seguir o
idioma da interface.

### Alterar o esquema de uma base de dados

Cada base de dados SQLite criada pelo ekte (`history.db`, `watches.db`,
`kb.db`) é versionada e migrada por um único mecanismo partilhado,
`ekte/dbmigrate.py`; um armazém nunca se migra sozinho com `ALTER TABLE` ad
hoc. A versão do esquema está em `PRAGMA user_version` e
`datadir.connect(name, MIGRATIONS)` verifica-a em cada abertura.

Para alterar um esquema:

1. Adicione ao armazém (`web/history.py`, `web/watches.py`,
   `knowledge/store.py`) uma função `_vN(conn)` que faça a alteração e
   acrescente `dbmigrate.Migration(N, _vN)` ao fim do seu tuplo `MIGRATIONS`.
   Nunca edite nem reordene um passo existente: as bases em uso já o
   executaram.
2. Mantenha o passo idempotente (`CREATE ... IF NOT EXISTS` e
   `kb_snapshot.add_link_columns()` para colunas) e não faça commit nem
   rollback lá dentro. O mecanismo executa cada passo na sua própria transação
   `BEGIN IMMEDIATE`, juntamente com o aumento da versão; um passo
   interrompido ou falhado deixa por isso a base na versão anterior.
3. Uma base nova começa na versão 0 e executa todos os passos; uma base
   anterior ao versionamento também tem a versão 0, pelo que o passo 1 de um
   armazém tem de adotar um esquema existente.
4. Adicione a `tests/test_dbmigrate.py` um teste que construa o esquema na
   versão N-1, o abra e verifique a nova versão, o novo esquema e a
   integridade dos dados. Se for preciso preencher linhas de dados existentes,
   faça-o no callback `on_migrated` do armazém (veja
   `history._after_migration`), não no passo.

O que o mecanismo faz por si: uma base escrita por um ekte **mais recente** é
recusada com `DatabaseTooNewError` (nomeia as duas versões e diz o que fazer)
antes de se escrever o que quer que seja; antes do primeiro passo de uma
execução, uma base não vazia é copiada para `<db>.v<versão>.<hora UTC>.bak` ao
lado dela, e só as 3 cópias mais recentes por base são mantidas
(`dbmigrate.BACKUP_KEEP`); a versão é relida sob o bloqueio de escrita, pelo
que a CLI e o servidor nunca executam o mesmo passo duas vezes.

### Traduções

A interface e os alertas por webhook partilham um único conjunto de traduções em
`ekte/i18n/locales/<code>.json`:

- `meta` — código, o nome do idioma na própria língua para o menu, idioma
  `html`, localização das datas e ordem no menu;
- `strings` — texto inglês → tradução (`en.json` é a aplicação identidade e a
  lista de referência dos textos traduzíveis);
- `findings` — id da constatação → `[título, modelo de resumo]` (`zh.json` contém
  o catálogo chinês original).

As funcionalidades podem trazer os seus textos como fragmentos,
`ekte/i18n/locales/fragments/<feature>/<code>.json` com `{"strings": {…}}`,
fundidos no idioma ao carregar. `/locales.js` envia apenas o idioma escolhido
(`?lang=<code>` ou o cookie `ekte_lang` definido por `lang.js`; sem nenhum dos
dois, todos os idiomas), gerado e comprimido com gzip uma vez por variante e
revalidado por `ETag`; uma troca de idioma carrega o novo sob demanda.

- **Novo texto de interface:** escreva o chinês no HTML e o inglês em `data-en`
  (ou use `T(zh, en)`), depois acrescente a chave inglesa a `en.json` ou a um
  fragmento e a sua tradução em cada um dos outros idiomas.
- **Novo idioma:** acrescente `ekte/i18n/locales/<code>.json` (copie `de.json`) e
  um ficheiro por fragmento; o menu, as páginas, os alertas e `--alert-lang`
  passam a usá-lo.
- `tests/test_web_locales.py` falha até que cada texto da interface e cada
  constatação esteja traduzido com os marcadores de posição e a marcação intactos.

**Terminologia.** Cada termo tem uma única tradução por idioma. Reutilize a
terminologia que a interface já usa (nomes de páginas, nomes das dimensões,
rótulos de risco, rótulos dos botões) nos textos novos e na documentação.

### Documentação

A documentação existe em oito idiomas — inglês, chinês (`zh-CN`), francês,
espanhol, português, italiano, alemão e norueguês (bokmål, `nb`):

| Ficheiro | Público |
|---|---|
| `README.md`, `README.<lang>.md` | Utilizadores: o que o ekte faz, instalação, utilização da CLI e da interface web |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Contribuidores: arquitetura, ambiente, contribuições, Docker, versões |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Todos: cada verificação, a sua escala de pontuação e as suas ressalvas |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md`, `docs/CLI.md`, `docs/SCHEMAS.md`, `docs/STABILITY.md`, `docs/ACCESSIBILITY.md`, `docs/RELEASE_CHECKLIST.md` | Páginas de referência (em inglês) |

Os ficheiros em inglês são a referência. Quando alterar um, altere os outros no
mesmo pull request e use em cada idioma a terminologia da interface (procure o
termo em `ekte/i18n/locales/`). Os ficheiros METHODOLOGY reproduzem as escalas de
pontuação com a redação que a interface mostra em **Escala de pontuação**.

## Testes

```bash
pytest                       # tudo
pytest tests/test_billing.py # um módulo
pytest -k streaming          # por palavra-chave
pytest -n auto               # em paralelo, um worker por CPU (pytest-xdist)
```

- `tests/conftest.py` fornece `MockServer`, um endpoint compatível com OpenAI
  sobre `httpx.MockTransport` com parâmetros para cada desvio que o ekte procura
  (modelo servido, autoidentificação, truncagem do contexto, streaming falso,
  utilização ausente ou inflacionada, chamadas de ferramentas, modo JSON, …).
  Cada parâmetro tem por predefinição o comportamento de um relay honesto.
- Os clientes Anthropic e Responses têm os seus próprios testes
  (`test_anthropic.py`, `test_responses.py`); o servidor web é testado com o
  cliente de testes do FastAPI (`test_web*.py`), incluindo as proteções de
  utilização local (`test_web_security.py`).
- Os scripts do navegador (`lang.js`, `v2/relaycfg.js`, `perf.js`,
  `secretfield.js`, `v2/report.js`, as traduções) são avaliados com `node` em
  `test_web_*_js.py` e `test_web_locales.py`; são ignorados sem Node.js.
- Nenhum teste pode aceder à rede.
- `test_cli_startup.py` mantém o arranque da CLI rápido: importar `ekte.cli` não
  pode carregar os clientes HTTP, o runner, o carregador da base de
  conhecimento, os renderizadores de relatórios (ReportLab) nem o servidor web.
  Importe-os dentro do comando que precisa deles.
- `test_filler_perf.py` fixa o texto de enchimento byte a byte e falha quando a
  sonda da janela de contexto bloqueia o event loop.
- `tests/a11y/` verifica a interface web (v2) face a BITV 2.0 / EN 301 549 /
  WCAG 2.1 AA num navegador real (Playwright + axe-core), em cada idioma da
  interface e em ambos os temas:
  `pip install -e '.[web,a11y]' && playwright install chromium`, depois
  `pytest -m a11y`. Sem Playwright, o diretório é ignorado. O que está
  automatizado e o que ainda precisa de uma revisão BITV manual está em
  [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md) (em inglês).
- `EKTE_A11Y_PAGES=history,kb` executa só os testes a11y dessas páginas (e as
  verificações que abrangem todas as páginas); `python -m tests.a11y.affected
  --base origin/main --head HEAD` mostra as páginas afetadas por uma
  alteração. Ambos usam um único mapeamento, `tests/a11y/pages.py`: uma página
  nova é acrescentada aos seus `PAGES` e `RULES`
  ([tests/a11y/README.md](tests/a11y/README.md)).

## Docker

O `Dockerfile` constrói uma imagem da interface web (Python 3.12 slim com o extra
`web`; os relatórios PDF não precisam de pacotes de sistema). Corre com um
utilizador sem privilégios e o diretório de dados em `/data`.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# abra http://localhost:8000
```

**Publique sempre em `127.0.0.1`.** Um simples `-p 8000:8000` publica a interface
— e cada chave API escrita nela ou guardada num monitor — na sua rede. Dentro do
contentor, o servidor tem de escutar em todas as interfaces; isso só é permitido
se `EKTE_CONTAINER=1` estiver definido (a imagem define-o) *e* for detetado um
ambiente de contentor.

| Variável | Predefinição | Função |
|---|---|---|
| `EKTE_CONTAINER` | não definida (`1` na imagem) | Permite escutar fora de loopback dentro de um contentor detetado |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` na imagem) | Endereço de escuta; `--host` prevalece |
| `EKTE_PORT` | `8000` | Porta; `--port` prevalece |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` na imagem) | Histórico, monitores (com as suas chaves encriptadas) e as suas entradas da base de conhecimento; monte aqui um volume. `--data-dir` tem prioridade |
| `EKTE_SECRET_KEY` | não definida | Chave mestra das chaves API guardadas dos monitores (uma chave, ou `file:/run/secrets/…` / `env:VAR`); não definida, a página Monitores pede-a após cada arranque. Nunca guardada em `EKTE_DATA_DIR` |
| `EKTE_KB_DIR` | não definida | Diretório YAML adicional da base de conhecimento, p. ex. `-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb` |
| `EKTE_NO_USER_KB` | não definida | `1` ignora as suas próprias entradas da base de conhecimento (`kb.db`) |
| `EKTE_ALLOWED_HOSTS` | não definida | Nomes de anfitrião adicionais a que a interface responde, separados por vírgulas |

[docs/DOCKER.md](docs/DOCKER.md) é a referência completa (em inglês), incluindo o
que protege a interface.

## Integração contínua

| Workflow | Corre em | Faz |
|---|---|---|
| `.github/workflows/ci.yml` | push e pull request para `main` (e os branches de integração `*/integration`); todas as noites e manual (só acessibilidade) | `ruff`, `mypy` e `pytest` com Python 3.11–3.14 (Linux; em macOS e Windows 3.11 e 3.14) e os extras `dev` e `web`; constrói a wheel e a sdist e verifica que a wheel se instala e carrega a base de conhecimento; executa a suite de acessibilidade (informativa, nunca faz falhar a execução) e carrega os seus resultados: todas as páginas nos pushes e nas execuções noturnas e manuais (com o relatório de conformidade BITV), nos pull requests só as páginas afetadas pela alteração (nenhuma se só muda documentação) — exceto em pull requests para `perf/integration`, onde a lenta suite no navegador é ignorada (corre nos pushes desse branch e no seu pull request para `main`) |
| `.github/workflows/release.yml` | uma tag `v*` | constrói, executa `twine check` e publica no PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | agendamento diário, manual | exemplo de auditoria agendada de um relay com a action |

A action composta é `action.yml`, documentada em [docs/CI.md](docs/CI.md).

### Arquivos de terceiros na distribuição

A distribuição de código-fonte contém os testes, mas nenhum arquivo de terceiros incluído. `tests/a11y/vendor/axe.min.js` (axe-core, MPL-2.0) está apenas no repositório git; é excluído do sdist (`exclude` em `[tool.hatch.build.targets.sdist]` do `pyproject.toml`) e nunca fez parte do wheel.

- Os testes que precisam de um arquivo excluído são ignorados com um motivo claro quando ele falta; execute a suíte de acessibilidade a partir de um checkout git.
- `NOTICE` lista cada arquivo de terceiros e diz se é distribuído. Adicione um novo arquivo incluído à lista `exclude` e ao `NOTICE` ou, se ele precisar ser distribuído, declare isso no `NOTICE`.
- `scripts/check_dist_contents.py` constrói o wheel e o sdist (`uv build`) e falha se houver um arquivo excluído ou um arquivo que o `NOTICE` lista como não distribuído. O workflow `.github/workflows/dist.yml` o executa em um job separado.

## Publicação de versões

Uma versão é uma tag de versão; tudo o resto é automatizado e verificado. A lista
de verificação está em [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md); a
configuração única do PyPI e o procedimento manual, em
[docs/PUBLISHING.md](docs/PUBLISHING.md).

### Publicar uma versão

1. Percorrer a [lista de verificação](docs/RELEASE_CHECKLIST.md): versão e
   changelog, versões de Python e sistemas suportados, atualidade da base de
   conhecimento, fixture de atualização, revisão de acessibilidade em mudanças de
   UI, documentação em todos os idiomas, avisos de segurança.
2. Definir `version` em `pyproject.toml` e renomear `[Unreleased]` em `CHANGELOG.md`
   para `[X.Y.Z] - AAAA-MM-DD`. Verificar localmente com
   `python scripts/release_check.py version vX.Y.Z` e `... notes vX.Y.Z`.
3. Fazer o merge, etiquetar o commit e enviar a tag:
   `git tag -a vX.Y.Z -m "ekte vX.Y.Z"`, `git push origin vX.Y.Z`.
4. O `release.yml` verifica primeiro, com `scripts/release_check.py`, que a tag
   corresponde à versão do pacote, que o `CHANGELOG.md` tem uma seção para ela e que
   a CI está verde para o commit etiquetado (espera por uma CI em execução). Se uma
   verificação falhar, o workflow para e nada é publicado. Depois compila, publica no
   PyPI por Trusted Publishing com atestações de proveniência e cria a GitHub
   Release com a seção do changelog como notas.

### Release candidates

Etiquetar `vX.Y.ZrcN` (com `version = "X.Y.ZrcN"` em `pyproject.toml`). O PyPI trata-a
como pré-lançamento PEP 440: `pip install ekte` ignora-a e `pip install --pre ekte`
encontra-a; o GitHub marca a release como «Pre-release». No changelog serve a seção
`[X.Y.ZrcN]`, `[X.Y.Z]` ou `[Unreleased]`.

### Se uma publicação falhar a meio

O PyPI nunca aceita o mesmo arquivo duas vezes e uma versão não pode ser reutilizada;
o que importa é até onde a execução chegou (Actions, «Release to PyPI»):

- **Uma verificação falhou (job verify).** Nada foi publicado. Corrigir a causa
  (versão, changelog, CI), apagar a tag localmente e no origin
  (`git push origin :refs/tags/vX.Y.Z`) e etiquetar de novo o commit corrigido.
- **Build ou upload falharam antes de o PyPI ter arquivos.** Reexecutar os jobs que
  falharam; nenhuma versão foi consumida. Se o próprio commit etiquetado tiver de
  mudar, apagar a tag e criá-la de novo.
- **O PyPI tem parte dos arquivos** (ver <https://pypi.org/project/ekte/#files>).
  Reexecutar os jobs que falharam: o upload ignora arquivos já existentes. Se os
  arquivos diferem do que se quer publicar, não repetir: fazer «yank» da versão no
  PyPI e publicar a seguinte (`X.Y.Z+1` ou `rcN+1`).
- **O PyPI está completo mas a GitHub Release falhou.** Reexecutar o job
  `GitHub Release`; ele cria ou atualiza a release de forma idempotente. Ou à mão:
  `gh release create vX.Y.Z --notes-file <(python scripts/release_check.py notes vX.Y.Z)`.
- **Uma versão defeituosa já está no ar.** Fazer «yank» no PyPI (só se instala com
  versão exata), corrigir em frente com uma nova versão e registrá-lo no changelog.

## Segurança

Reporte vulnerabilidades em privado, como descrito em [SECURITY.md](SECURITY.md).
Estão no âmbito sobretudo: uma chave ou um segredo que chegue a um relatório,
texto controlado pelo relay que injete marcação num relatório ou na interface,
tráfego para algo que não os endpoints configurados, e formas de contornar as
proteções de utilização local da interface web.

## Licença

[Apache-2.0](LICENSE)
