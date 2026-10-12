# zing — Guia do programador

> [🇬🇧 English](DEVELOPER_GUIDE.md) · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · **🇵🇹 Português** · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md)

Este guia é para quem altera o zing: como está construído, como preparar um
ambiente de desenvolvimento, como contribuir e como é empacotado, executado em
Docker e publicado. O que o zing faz e como usá-lo está no [README](README.pt.md);
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
  - [Auditores autónomos](#auditores-autónomos)
  - [Servidor web](#servidor-web)
  - [Frontend web](#frontend-web)
  - [Dados locais](#dados-locais)
- [Contribuir](#contribuir)
  - [Pull requests](#pull-requests)
  - [Adicionar um detector](#adicionar-um-detector)
  - [Editar a base de conhecimento](#editar-a-base-de-conhecimento)
  - [Alterar os prompts das sondas](#alterar-os-prompts-das-sondas)
  - [Traduções](#traduções)
  - [Documentação](#documentação)
- [Testes](#testes)
- [Docker](#docker)
- [Integração contínua](#integração-contínua)
- [Publicação de versões](#publicação-de-versões)
- [Segurança](#segurança)
- [Licença](#licença)

## Princípios

O zing é uma ajuda de auditoria de caixa-preta: a correção e **não acusar
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
  passar o texto controlado pelo relay por `zing.utils.redact` e escapá-lo para o
  seu formato.
- **As mesmas sondas para todos.** Os textos das sondas estão em inglês e são
  fixos, seja qual for o idioma da interface, para que o mesmo relay receba o
  mesmo veredito (ver [Biblioteca de prompts](#biblioteca-de-prompts)).
- **Apenas local.** O zing só contacta os endpoints configurados pelo utilizador,
  e a interface web só escuta em loopback (ver [Servidor web](#servidor-web)).

## Ambiente de desenvolvimento

Requer Python 3.10+. O Node.js é opcional: os testes do JavaScript do navegador
correm com `node` e são ignorados sem ele.

```bash
git clone https://github.com/cenbonew/zing
cd zing
pip install -e '.[dev,web]'   # instalação editável com as ferramentas de desenvolvimento e a interface web
pytest                        # suite de testes
ruff check zing tests         # lint
mypy zing                     # verificação de tipos
```

Com uv: `uv venv && uv pip install -e '.[dev,web]'`. Não são precisas
bibliotecas de sistema, nem para os relatórios PDF.

Execute a partir do código-fonte com `zing …` ou `python -m zing …`. `zing serve`
serve a interface web diretamente a partir de `zing/web/static/`, pelo que
recarregar o navegador apanha as alterações do frontend; não há passo de build.

## Estrutura do repositório

```text
zing/
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
  prompts/en.json      todo o texto que o zing envia a uma API de LLM
  perf/                registo por pedido e a secção de desempenho do relatório
  report/              renderizadores JSON / Markdown / HTML / PDF e escrita
  embed_audit.py       auditor autónomo de embeddings e rerank
  media_audit.py       auditor autónomo de imagem e áudio (TTS)
  notify.py            alertas por webhook (Slack / Feishu / DingTalk / JSON genérico)
  datadir.py           o diretório de dados local e os seus ficheiros SQLite
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
    masterkey.py       estados e ações da chave mestra (servidor e `zing secret`)
    static/            páginas da interface clássica e scripts partilhados (lang.js, i18n.js, …)
    static/v2/         páginas, estilos e scripts da nova interface
tests/                 suite pytest; conftest.py contém o relay simulado
docs/                  METHODOLOGY (7 idiomas), CI.md, DOCKER.md, PUBLISHING.md
examples/zing.yaml     ficheiro de configuração comentado
prototypes/            protótipos HTML estáticos do design da interface web (não distribuídos)
action.yml             a action composta do GitHub
Dockerfile             imagem da interface web
```

## Arquitetura

### Fluxo de uma auditoria

`zing check`, `zing compare`, `zing watch`, o fluxo de auditoria da interface web
e o seu agendador de monitores acabam todos na mesma função,
`zing.runner.run_audit()`:

1. **Configuração.** `zing/config.py` junta a configuração YAML e as opções de
   linha de comandos em `TargetConfig` (alvo, referência e juiz opcionais) e
   `AuditOptions` (suite, dimensões, dimensão das sondas, saída). As chaves de API
   dadas como `env:VAR` ou `file:/caminho` são resolvidas aqui.
2. **Base de conhecimento.** `load_knowledge_base()` carrega os perfis
   integrados, `--kb-dir`/`ZING_KB_DIR` e o `kb.db` do utilizador, e resolve o
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
6. **Relatório.** Tudo termina num `AuditReport` (`zing/models.py`) com o alvo
   ocultado, o instantâneo do perfil da base de conhecimento, a secção de
   desempenho e os idiomas das sondas. A CLI renderiza-o e escreve-o; a interface
   web transmite-o.

`run_audit()` aceita um callback `on_event`; o servidor web transforma os seus
eventos (detector iniciado/terminado com constatações compactas, tempos por
pedido agrupados) em Server-Sent Events para a vista ao vivo.

### Clientes

`zing/clients/` tem um cliente por protocolo — `openai_compatible.py` (Chat
Completions), `anthropic.py` (Messages) e `responses.py` (Responses) — com a
mesma interface, construídos sobre a mecânica HTTP comum de `base.py`.
`make_client()` em `clients/__init__.py` escolhe um conforme `--api` ou deteta-o a
partir do URL base e do modelo. Os detectores só falam com esta interface
(`RequestSpec` à entrada, `CompletionOutcome` à saída), pelo que são
independentes do protocolo.

### Detectores e escalas de pontuação

Um detector é um ficheiro autocontido em `zing/detectors/`: uma subclasse de
`Detector` (`base.py`) com um `id`, um `name`, uma `dimension`, a primeira suite
em que corre (`min_suite`), um `cost_hint` aproximado para `--dry-run` e
`async def run(self, ctx) -> DetectorResult`. `@register` adiciona-o ao registo;
`zing/detectors/__init__.py` importa cada módulo para que o registo fique
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
`zing serve`, pelo que o trabalho que exige muito CPU não pode correr nele: um
loop bloqueado atrasa os pedidos das outras auditorias e inflaciona as
latências que registam. `helpers.build_filler()` constrói o texto de
enchimento em tempo linear e guarda em cache os últimos tamanhos, e os
detectores da janela de contexto e da cache de prompts chamam-no (e a
`build_haystack()`) através de `asyncio.to_thread`. As contagens de tokens vêm
de `zing/utils/tokenize.py`, uma heurística só com a biblioteca padrão: o zing
não importa nenhuma biblioteca de tokenizer e não descarrega nada em tempo de
execução, pelo que funciona em ambientes restritos. O argumento `tokenizer` de
`estimate_tokens()` é aceite mas não altera a contagem, e os campos do
relatório `tokens_exact` / `exact_tokenizer` são mantidos por compatibilidade e
são sempre false.

### Pontuação e veredito

`zing/scoring.py` contém `DIMENSION_WEIGHTS` e as regras do veredito: a pontuação
de uma dimensão é a média com peso igual dos seus detectores, a pontuação global a
média ponderada das dimensões executadas, e o nível de risco segue a escala de
gravidade descrita em
[Metodologia → Como o zing pontua](docs/METHODOLOGY.pt.md#como-o-zing-pontua).
Cada dimensão regista como foi calculada em `DimensionScore.breakdown`, que
alimenta os **Dimension details** dos relatórios e as linhas expansíveis das
**Verificações por dimensão** da interface web.

### Base de conhecimento

`zing/knowledge/` define o esquema dos perfis (`schema.py`: `ProviderProfile`,
`ModelProfile`, `FingerprintProbe`), carrega e funde as camadas (`loader.py`:
YAML integrado → `ZING_KB_DIR`/`--kb-dir` → o `kb.db` do utilizador), guarda as
entradas do utilizador (`store.py`), verifica e importa YAML (`importer.py`),
constrói o prompt de pesquisa para assistentes externos (`research.py`) e tira um
instantâneo do perfil usado por uma execução (`snapshot.py`). Os ids de modelo
resolvem-se através de aliases e do fornecedor declarado; cada relatório regista
como o id foi resolvido.

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

Todo o texto que o zing envia a uma API de LLM — sondas de chat, o prompt do
juiz, esquemas de ferramentas, entradas de embeddings / rerank / imagem / áudio —
está em `zing/prompts/en.json` e lê-se com `zing.prompts.text()` / `get()`.
`{{name}}` marca um valor preenchido em tempo de execução. O idioma das sondas
está fixado em inglês (`PROBE_LANG`), independentemente do idioma da interface,
porque as verificações de respostas e as estimativas de tokens estão calibradas
para esses textos exatos. As sondas cujo idioma *é* a medida (p. ex. fluência em
chinês, tokenizer ou autoidentificação de modelos chineses) vivem com as suas
respostas esperadas na base de conhecimento e declaram `prompt_lang` e um motivo
`language_bound`. O runner regista os idiomas usados em `prompt_languages`.

### Relatórios

`zing/report/render.py` renderiza um `AuditReport` como JSON, JSON compacto para
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

### Auditores autónomos

Embeddings/rerank (`embed_audit.py`) e imagem/áudio (`media_audit.py`) não são
superfícies de chat, pelo que têm os seus próprios pequenos auditores com o seu
próprio veredito em vez do pipeline de detectores. Partilham as definições HTTP
dos clientes, a base de conhecimento (dimensões nativas, tamanhos de imagem,
vozes) e a biblioteca de prompts. Toda a descodificação (cabeçalhos de imagem,
WAV) usa apenas a biblioteca padrão.

### Servidor web

`zing/web/server.py` é uma app FastAPI criada por `create_app()`:

- **Páginas.** A interface clássica (`/`, `/console`, `/history`, `/watches`,
  `/tools`) e a nova interface (`/v2/`, `/v2/history`, `/v2/watches`,
  `/v2/tools`, `/v2/kb`) são ficheiros HTML estáticos. `?ui=v2` / `?ui=v1` muda
  de uma para a outra e um cookie memoriza a escolha, pelo que um URL clássico
  redireciona para o seu equivalente novo depois de escolhida a nova interface.
- **API.** `/api/audit/stream` executa uma auditoria e transmite os seus eventos
  por SSE; `/api/models` lista os modelos de um relay; `/api/report/export`
  renderiza um relatório; `/api/history…`, `/api/watches…`, `/api/kb…`,
  `/api/embed` e `/api/rerank` servem as restantes páginas.
- **Relays.** `POST /api/kb/relays` guarda um relay `{name, base_url}` (400 para
  dados inválidos, 409 se o nome ou o URL já forem conhecidos).
- **Análises.** `GET /api/analytics/options` (relays, modelos, suites, modos de
  stream, API e o intervalo de datas do histórico), `/api/analytics/summary`
  (KPI de `from`–`to` face ao intervalo anterior com a mesma duração),
  `/api/analytics/series` (`metric` por `group=relay|model|relay_model`, até 4
  `keys`, em intervalos `bucket=hour|day|week|dow_hour` no fuso horário do
  utilizador, `tz` ou `tz_offset`) e `/api/analytics/leaderboard` (`model=` para
  os seus relays, ou `relay=` para os seus modelos). Todos aceitam os filtros
  `from`, `to`, `suite`, `stream_mode`, `api`, `source=all|manual|monitor`,
  `relay` e `model`. `zing/web/analytics.py` calcula tudo em Python a partir de
  `history.analytics_runs()`: os ids de métrica vêm de uma lista fixa, os relays
  são agrupados pela sua entrada na base de conhecimento no momento da
  consulta, um valor que uma execução não mediu fica de fora (cada valor tem o
  seu `n` e a sua `coverage`) e os intervalos com menos de `MIN_RUNS` (3)
  execuções são marcados `low_n`. Um parâmetro inválido responde 400; as
  respostas são `Cache-Control: no-store`.
- **Auditorias em segundo plano.** `jobs.py` executa cada auditoria como um
  trabalho do servidor. `POST /api/jobs` coloca um em fila, `GET /api/jobs`
  lista os trabalhos em fila, em curso e acabados há pouco (e os monitores em
  execução) com o progresso, `GET /api/jobs/{id}/events` reproduz o registo de
  eventos e depois segue-o ao vivo por SSE, e `POST /api/jobs/{id}/cancel`
  pára-o. A nova interface usa-os, por isso uma auditoria sobrevive à página;
  `/api/audit/stream` (interface clássica) envolve o mesmo trabalho e cancela-o
  quando o fluxo fecha. Um bloqueio por relay deixa uma só auditoria (ou
  execução de monitor) usar um relay de cada vez, por nome de host, com todos os
  endereços loopback como um host; no máximo `ZING_MAX_PARALLEL_AUDITS`
  (4 por omissão) em simultâneo, por ordem de chegada.
- **Agendador de monitores.** O lifespan da app lança um ciclo em segundo plano
  que inicia cada monitor devido como uma tarefa própria, pelo que monitores em
  relays diferentes auditam ao mesmo tempo; o bloqueio por relay continua a
  aplicar-se, por isso os monitores podem ocupar as vagas de
  `ZING_MAX_PARALLEL_AUDITS` e uma auditoria manual pode ficar em fila atrás
  deles. O `last_run_ts` de uma execução é o momento em que a sua auditoria
  começa (depois de esperar pelo seu relay). Cada execução é registada no
  histórico; a verificação de regressão compara-a com a execução guardada mais
  recente do mesmo alvo e modelo (`history.latest_for()`, uma única consulta
  indexada) e envia os alertas por webhook (`zing/notify.py`) em simultâneo ao
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
  exceto num contentor detetado com `ZING_CONTAINER=1`) e instala
  `LocalOnlyMiddleware`: uma lista de anfitriões permitidos contra DNS rebinding,
  controlos de `Origin` e `Sec-Fetch-Site` contra CSRF, corpos de pedido apenas
  JSON e cabeçalhos anti-iframe / no-sniff / no-referrer. A interface não tem
  início de sessão por design.

### Frontend web

O frontend é HTML, CSS e JavaScript de navegador simples, sem módulos nem passo
de build. As páginas clássicas estão em `zing/web/static/`; a nova interface, em
`zing/web/static/v2/`, partilha um cabeçalho (`nav.js`), o renderizador de
relatórios (`report.js`), o seletor de tema (`theme.js`) e os estilos
(`zing.css`, `fields.css`, `report.css`, `perf.css`). Os scripts partilhados são
servidos a partir da raiz: `lang.js` (mudança de idioma), `locales.js` (dados de
tradução), `i18n.js` (tradução das constatações), `icons.js`, `modelpicker.js`
(**Obter modelos**), `secretfield.js` e `perf.js` (gráficos de desempenho).

As páginas v2 **Auditoria** e **Ferramentas** configuram relays com
`v2/relaycfg.js`: escolha de relay/provedor → URL base → os modelos do relay
(`/api/models`, ao mudar, em cache por URL/chave/protocolo) → modelo declarado da
base de conhecimento (`/api/kb/resolve` pré-seleciona-o) → provedor derivado,
mais **Salvar na base** (`POST /api/kb/relays`). As suas funções puras são
testadas com node; as páginas clássicas mantêm `modelpicker.js`.

A página v2 **Análises** (`v2/analytics.html`) só lê `/api/analytics/*`
(`options` também lista os pares relay × modelo, `relay_models`, para o seletor
de séries). Tem uma `<section class="card panel">` por painel sob uma única
barra de filtros, por isso podem juntar-se painéis; filtros e vista ficam no
fragmento do URL (`#range=30&metric=score&…`) e em `localStorage`. Os gráficos
vêm de `v2/charts.js` (`ZingCharts.timeChart`: SVG inline desenhado à mão com
linha mediana, faixa p25–p75, lacunas para intervalos vazios, marcadores
esbatidos para intervalos `low_n`, linhas de anotação e tooltip ao passar o
ponteiro; `fmt` / `fmtDelta` formatam valores pela unidade) e de
`v2/charts.css` (quatro cores de série validadas por tema, distinguíveis também
pela forma do marcador). Cada gráfico existe também como tabela de dados.

**Convenção de tradução.** O texto chinês escrito no HTML é o original e não se
altera; cada elemento leva o seu texto inglês em `data-en` (e
`data-en-placeholder`, `data-en-title`, `data-en-aria-label`). O texto inglês é a
chave de pesquisa para todos os outros idiomas. Os scripts usam `T(zh, en)` para
texto dinâmico e `ZING_LANG.server(text)` para texto vindo do backend (nomes de
detectores, recomendações, frases do veredito).

### Dados locais

`zing/datadir.py` gere `$ZING_DATA_DIR` (por predefinição `~/.zing`), criado com
`0700`, com ficheiros SQLite `0600`: `history.db` (`web/history.py`),
`watches.db` (`web/watches.py`, que guarda encriptadas as chaves API dos
monitores) e `kb.db` (`knowledge/store.py`). Cada chamada abre uma ligação de
curta duração, pelo que os armazenamentos são seguros no pool de threads do
FastAPI. A opção global `--data-dir` (também em `zing serve`) limita-se a
definir `ZING_DATA_DIR` com o caminho absoluto, e `zing data-dir` mostra o
diretório resolvido. Um diretório que já existe mantém as suas permissões; só o
`~/.zing` predefinido é restringido a `0700`. As linhas do histórico estão
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

As chaves API guardadas são encriptadas por `zing/secretbox.py` (Fernet,
guardadas como `enc:v1:…`; as referências `env:`/`file:` ficam como estão). A
chave mestra nunca é guardada: `web/masterkey.py` (`Vault`, partilhado pelo
servidor e pelo `zing secret`) mantém-na na memória do servidor assim que chega
de `ZING_SECRET_KEY`, de um `secret.key` antigo ou do utilizador na página
Monitores, e `watches.db` guarda apenas um valor de verificação (`secret_meta`)
que rejeita uma chave errada. Uma chave nova volta a encriptar cada chave
guardada e reescreve o valor de verificação numa única transação. A chave vive
na memória de um só processo, por isso execute um servidor por diretório de
dados.

## Contribuir

### Pull requests

- Mantenha `pytest`, `ruff check zing tests` e `mypy zing` a verde (a CI executa
  os três com Python 3.10–3.13).
- Descreva o truque de relay ou o falso positivo que a alteração resolve.
- Atualize `CHANGELOG.md` em `[Unreleased]`.
- Atualize a documentação afetada — README, este guia, a Metodologia — em
  **todos os idiomas** (ver [Documentação](#documentação)).

Ao contribuir, aceita que as suas contribuições fiquem sob a licença
[Apache-2.0](LICENSE) do projeto.

### Adicionar um detector

1. Crie `zing/detectors/<name>.py` e importe-o em `zing/detectors/__init__.py`.
2. Defina a sua `SCALE` (`Scale` ou `DeductionScale` de `scale.py`) com cada
   resultado de cada verificação, e crie constatações apenas através dela.
3. Derive de `Detector`; defina `id`, `name`, `dimension`, `min_suite` e
   `cost_hint`; ponha `requires_judge = True` ou `requires_baseline = True` se
   precisar de um juiz ou de uma referência, ou redefina `applies()` para outras
   condições. Decore a classe com `@register`.
4. Implemente `async def run(self, ctx) -> DetectorResult` a partir de
   `self.new_result(scoring=SCALE.scoring())`. Envie os pedidos através de
   `ctx.client` e tire cada prompt de `zing/prompts/en.json`.
5. Acrescente testes de comportamento para o caminho sinalizado e para o limpo,
   com o relay simulado de `tests/conftest.py`.
6. Traduza os novos títulos e resumos de constatações (ver
   [Traduções](#traduções)) e documente o detector e a sua escala em cada
   ficheiro de [Metodologia](docs/METHODOLOGY.pt.md).

### Editar a base de conhecimento

Os perfis estão em `zing/knowledge/data/<provider>.yaml`, um ficheiro por
fornecedor. Cada modelo tem a sua janela de contexto nativa, saída máxima, data de
corte do conhecimento, tokenizer, modalidades, capacidades, parâmetros não
suportados, palavras-chave de identidade e impressões (ver
`zing/knowledge/schema.py`). Quando alterar um campo numérico, **cite uma fonte
fidedigna** (a ficha oficial do modelo, preços ou documentação do fornecedor) no
pull request: um valor errado provoca falsos positivos contra relays honestos.
`zing kb-import --check <ficheiro>` faz as mesmas verificações que a importação do
utilizador (esquema, limites, expressões regulares perigosas, prompts, colisões de
ids).

Preencha sempre `identity_keywords` com as palavras do fabricante e da família
com que o modelo se identifica. A verificação de identidade conta também a
chave do fornecedor, o nome de apresentação e o id do modelo como marca
genuína, alargados aos restantes nomes do fabricante em `VENDOR_BRANDS`
(`zing/knowledge/identity.py`, que é também a lista de marcas rivais do
detetor); a importação preenche palavras-chave vazias a partir destes nomes com
um aviso. As palavras de marca de um novo fabricante acrescentam-se aí como um
grupo.

### Alterar os prompts das sondas

Os textos das sondas são dados de calibração. Alterar um em
`zing/prompts/en.json` pode mudar as verificações de respostas, as estimativas de
tokens e, portanto, os vereditos; ajuste o detector e os seus testes em
conformidade e mencione a alteração no CHANGELOG. Nunca faça uma sonda seguir o
idioma da interface.

### Traduções

A interface e os alertas por webhook partilham um único conjunto de traduções em
`zing/i18n/locales/<code>.json`:

- `meta` — código, o nome do idioma na própria língua para o menu, idioma
  `html`, localização das datas e ordem no menu;
- `strings` — texto inglês → tradução (`en.json` é a aplicação identidade e a
  lista de referência dos textos traduzíveis);
- `findings` — id da constatação → `[título, modelo de resumo]` (`zh.json` contém
  o catálogo chinês original).

As funcionalidades podem trazer os seus textos como fragmentos,
`zing/i18n/locales/fragments/<feature>/<code>.json` com `{"strings": {…}}`,
fundidos no idioma ao carregar. `/locales.js` envia apenas o idioma escolhido
(`?lang=<code>` ou o cookie `zing_lang` definido por `lang.js`; sem nenhum dos
dois, todos os idiomas), gerado e comprimido com gzip uma vez por variante e
revalidado por `ETag`; uma troca de idioma carrega o novo sob demanda.

- **Novo texto de interface:** escreva o chinês no HTML e o inglês em `data-en`
  (ou use `T(zh, en)`), depois acrescente a chave inglesa a `en.json` ou a um
  fragmento e a sua tradução em cada um dos outros idiomas.
- **Novo idioma:** acrescente `zing/i18n/locales/<code>.json` (copie `de.json`) e
  um ficheiro por fragmento; o menu, as páginas, os alertas e `--alert-lang`
  passam a usá-lo.
- `tests/test_web_locales.py` falha até que cada texto da interface e cada
  constatação esteja traduzido com os marcadores de posição e a marcação intactos.

**Terminologia.** Cada termo tem uma única tradução por idioma. Reutilize a
terminologia que a interface já usa (nomes de páginas, nomes das dimensões,
rótulos de risco, rótulos dos botões) nos textos novos e na documentação.

### Documentação

A documentação existe em sete idiomas — inglês, chinês (`zh-CN`), francês,
espanhol, português, italiano e alemão:

| Ficheiro | Público |
|---|---|
| `README.md`, `README.<lang>.md` | Utilizadores: o que o zing faz, instalação, utilização da CLI e da interface web |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Contribuidores: arquitetura, ambiente, contribuições, Docker, versões |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Todos: cada verificação, a sua escala de pontuação e as suas ressalvas |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Páginas de referência (em inglês) |

Os ficheiros em inglês são a referência. Quando alterar um, altere os outros no
mesmo pull request e use em cada idioma a terminologia da interface (procure o
termo em `zing/i18n/locales/`). Os ficheiros METHODOLOGY reproduzem as escalas de
pontuação com a redação que a interface mostra em **Escala de pontuação**.

## Testes

```bash
pytest                       # tudo
pytest tests/test_billing.py # um módulo
pytest -k streaming          # por palavra-chave
pytest -n auto               # em paralelo, um worker por CPU (pytest-xdist)
```

- `tests/conftest.py` fornece `MockServer`, um endpoint compatível com OpenAI
  sobre `httpx.MockTransport` com parâmetros para cada desvio que o zing procura
  (modelo servido, autoidentificação, truncagem do contexto, streaming falso,
  utilização ausente ou inflacionada, chamadas de ferramentas, modo JSON, …).
  Cada parâmetro tem por predefinição o comportamento de um relay honesto.
- Os clientes Anthropic e Responses têm os seus próprios testes
  (`test_anthropic.py`, `test_responses.py`); o servidor web é testado com o
  cliente de testes do FastAPI (`test_web*.py`), incluindo as proteções de
  utilização local (`test_web_security.py`).
- Os scripts do navegador (`lang.js`, `modelpicker.js`, `v2/relaycfg.js`, `perf.js`,
  `secretfield.js`, `v2/report.js`, as traduções) são avaliados com `node` em
  `test_web_*_js.py` e `test_web_locales.py`; são ignorados sem Node.js.
- Nenhum teste pode aceder à rede.
- `test_cli_startup.py` mantém o arranque da CLI rápido: importar `zing.cli` não
  pode carregar os clientes HTTP, o runner, o carregador da base de
  conhecimento, os renderizadores de relatórios (ReportLab) nem o servidor web.
  Importe-os dentro do comando que precisa deles.
- `test_filler_perf.py` fixa o texto de enchimento byte a byte e falha quando a
  sonda da janela de contexto bloqueia o event loop.
- `tests/a11y/` verifica a nova interface web (v2) face a BITV 2.0 / EN 301 549 /
  WCAG 2.1 AA num navegador real (Playwright + axe-core), em cada idioma da
  interface e em ambos os temas:
  `pip install -e '.[web,a11y]' && playwright install chromium`, depois
  `pytest -m a11y`. Sem Playwright, o diretório é ignorado. O que está
  automatizado e o que ainda precisa de uma revisão BITV manual está em
  [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md) (em inglês).

## Docker

O `Dockerfile` constrói uma imagem da interface web (Python 3.12 slim com o extra
`web`; os relatórios PDF não precisam de pacotes de sistema). Corre com um
utilizador sem privilégios e o diretório de dados em `/data`.

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# abra http://localhost:8000
```

**Publique sempre em `127.0.0.1`.** Um simples `-p 8000:8000` publica a interface
— e cada chave API escrita nela ou guardada num monitor — na sua rede. Dentro do
contentor, o servidor tem de escutar em todas as interfaces; isso só é permitido
se `ZING_CONTAINER=1` estiver definido (a imagem define-o) *e* for detetado um
ambiente de contentor.

| Variável | Predefinição | Função |
|---|---|---|
| `ZING_CONTAINER` | não definida (`1` na imagem) | Permite escutar fora de loopback dentro de um contentor detetado |
| `ZING_HOST` | `127.0.0.1` (`0.0.0.0` na imagem) | Endereço de escuta; `--host` prevalece |
| `ZING_PORT` | `8000` | Porta; `--port` prevalece |
| `ZING_DATA_DIR` | `~/.zing` (`/data` na imagem) | Histórico, monitores (com as suas chaves encriptadas) e as suas entradas da base de conhecimento; monte aqui um volume. `--data-dir` tem prioridade |
| `ZING_SECRET_KEY` | não definida | Chave mestra das chaves API guardadas dos monitores (uma chave, ou `file:/run/secrets/…` / `env:VAR`); não definida, a página Monitores pede-a após cada arranque. Nunca guardada em `ZING_DATA_DIR` |
| `ZING_KB_DIR` | não definida | Diretório YAML adicional da base de conhecimento, p. ex. `-v ./profiles:/kb:ro -e ZING_KB_DIR=/kb` |
| `ZING_NO_USER_KB` | não definida | `1` ignora as suas próprias entradas da base de conhecimento (`kb.db`) |
| `ZING_ALLOWED_HOSTS` | não definida | Nomes de anfitrião adicionais a que a interface responde, separados por vírgulas |

[docs/DOCKER.md](docs/DOCKER.md) é a referência completa (em inglês), incluindo o
que protege a interface.

## Integração contínua

| Workflow | Corre em | Faz |
|---|---|---|
| `.github/workflows/ci.yml` | push e pull request para `main` (e os branches de integração `a11y/integration`, `perf/integration`) | `ruff`, `mypy` e `pytest` com Python 3.10–3.13 e os extras `dev` e `web`; constrói a wheel e a sdist e verifica que a wheel se instala e carrega a base de conhecimento; executa a suite de acessibilidade (informativa, nunca faz falhar a execução) e carrega os seus resultados — exceto em pull requests para `perf/integration`, onde a lenta suite no navegador é ignorada (corre nos pushes desse branch e no seu pull request para `main`) |
| `.github/workflows/release.yml` | uma tag `v*` | constrói, executa `twine check` e publica no PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | agendamento diário, manual | exemplo de auditoria agendada de um relay com a action |

A action composta é `action.yml`, documentada em [docs/CI.md](docs/CI.md).

## Publicação de versões

1. Mude `[Unreleased]` em `CHANGELOG.md` para a nova versão e aumente `version`
   em `pyproject.toml`.
2. Faça commit, crie a tag `vX.Y.Z` e envie-a; `release.yml` publica no PyPI.
3. Crie a release no GitHub com as notas do CHANGELOG e atualize a versão fixada
   da action nos README e em `docs/CI.md`.

A configuração inicial do PyPI e o procedimento manual estão em
[docs/PUBLISHING.md](docs/PUBLISHING.md).

## Segurança

Reporte vulnerabilidades em privado, como descrito em [SECURITY.md](SECURITY.md).
Estão no âmbito sobretudo: uma chave ou um segredo que chegue a um relatório,
texto controlado pelo relay que injete marcação num relatório ou na interface,
tráfego para algo que não os endpoints configurados, e formas de contornar as
proteções de utilização local da interface web.

## Licença

[Apache-2.0](LICENSE)
