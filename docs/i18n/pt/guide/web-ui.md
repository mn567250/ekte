# Interface web (`ekte serve`)

> [🇬🇧 English](../../../guide/web-ui.md) · [🇨🇳 中文](../../zh-CN/guide/web-ui.md) · [🇫🇷 Français](../../fr/guide/web-ui.md) · [🇪🇸 Español](../../es/guide/web-ui.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/web-ui.md) · [🇩🇪 Deutsch](../../de/guide/web-ui.md) · [🇳🇴 Norsk](../../nb/guide/web-ui.md)

Prefere clicar? Uma interface web local envolve o mesmo motor — sem linha de
comandos.

```bash
pip install 'ekte[web]'     # ou: uv tool install 'ekte[web]'
ekte serve                        # abre http://localhost:8000
```

O formulário guia a configuração:

1. Escolha o **Relay / provedor**: um fornecedor da base de conhecimento ou um
   relay que guardou. O seu URL base é preenchido (os outros URL conhecidos do
   fornecedor são oferecidos como sugestões). Para qualquer outro relay escolha
   **Outro (introduzir o URL)** e introduza o **URL do intermediário**.
2. Acrescente a **Chave de API** se o relay precisar de uma.
3. O ekte lista sozinho os modelos do relay (ao escolher um relay e sempre que
   o URL ou a chave mudam; **Atualizar modelos** pergunta de novo). Escolha o
   **Modelo pedido**. Um relay sem lista de modelos recorre à introdução do id
   (**Introduzir manualmente**).
4. Opcionalmente escolha o **Modelo declarado** entre os modelos da base de
   conhecimento: o modelo que o relay diz servir. Se o modelo pedido estiver na
   base de conhecimento, fica pré-selecionado; mude-o apenas se o relay vender o
   modelo com outro nome. Dele resulta o perfil do fornecedor usado na auditoria.

Um relay que ainda não está na lista pode ser mantido com **Guardar na base** com
o nome que lhe der; da próxima vez basta escolhê-lo. A referência de confiança
(**Comparar com uma referência confiável**) e as auditorias de embeddings e rerank
são configuradas da mesma forma.

Depois, **Iniciar auditoria** e acompanhe
as verificações **ao vivo**: cada verificação mostra a sua pontuação e quanto
tempo levou, e uma verificação com constatações expande-se para mostrar as
evidências. O resultado é um relatório de veredito que pode partilhar: nota,
**Verificações por dimensão** com as suas escalas de pontuação, constatações em
linguagem clara, a secção de desempenho e um **Registo de execução** de cada
detetor.

Tudo corre na sua máquina: uma chave escrita no navegador só chega ao seu
servidor ekte local e ao relay que audita, nunca a terceiros. Consulte
[Privacidade e dados locais](privacy.md#privacidade-e-dados-locais).

## Páginas

A interface web é servida na raiz do endereço que o `ekte serve` abre, com a página de auditoria em `/`. Os endereços anteriores redirecionam para a página correspondente até à 1.0.0 (consulte [Endereços da interface web](../../../reference/stability.md#surface-web-addresses)).

| Página | Endereço | Para que serve |
|---|---|---|
| **Auditoria** | `/` | Auditar um relay (opcionalmente face a uma referência) e ler o relatório; as auditorias de embeddings e rerank também começam aqui, com o seletor de tipo de endpoint |
| **Monitores** | `/watches` | Reauditorias agendadas com alertas por webhook |
| **Histórico** | `/history` | Cada auditoria executada nesta máquina, agrupada por relay + modelo declarado, com tendências |
| **Análises** | `/analytics` | Relays e modelos comparados ao longo do tempo: indicadores, gráficos com tabelas de dados, classificações |
| **Conhecimento** | `/kb` | A base de conhecimento em três separadores — modelos, fornecedores, relays: explorar, ativar/desativar, adicionar os seus |
| **Acessibilidade** | `/accessibility` | O relatório de conformidade e a declaração de acessibilidade (o ícone junto ao seletor de idioma) |

Nas páginas há ainda: filtros e tendências configuráveis (pontuação, nota,
latência p50, tokens/s) no **Histórico**; **Agendar como monitor** e **Executar auditoria novamente** em cada
execução do Histórico; **Transferir relatório** em todos os formatos; e um seletor
de tema (Automático / Claro / Escuro). Cada página
exceto Acessibilidade tem um aviso logo abaixo da introdução, colorido segundo a
importância (informação, sucesso, aviso, crítico): p. ex. a última auditoria
concluída em **Auditoria**, a chave mestra em **Monitores**, as execuções ainda
em processamento em **Histórico** e **Análises**, as entradas ignoradas em
**Conhecimento**.

**Auditorias em segundo plano.** Uma auditoria iniciada na
página **Auditoria** continua quando muda de página ou fecha o separador;
**Continuar em segundo plano** envia-a para lá de propósito. O **Histórico**
lista cada auditoria em fila e em curso (e cada monitor em execução) com o seu
progresso; **Ver em direto** reabre a vista em direto, que recupera tudo o que já
aconteceu. Auditorias do mesmo relay correm uma após a outra, para nunca
distorcerem os resultados de latência ou fiabilidade umas das outras (todos os
endereços loopback contam como um só host, por isso modelos servidos pela sua
própria máquina também esperam); auditorias de relays diferentes correm em
paralelo, no máximo quatro de cada vez (`EKTE_MAX_PARALLEL_AUDITS`). Os
monitores esperam pelo seu relay da mesma forma.

**Análises.** `/analytics` transforma o histórico local em
comparações: indicadores do período escolhido (execuções, pontuação mediana,
proporção de risco alto, taxa de sucesso, TTFT, velocidade de saída, rácios de
faturação) com a variação face ao período anterior de igual duração; um gráfico
de qualquer métrica por relay, modelo ou relay × modelo, por hora, dia ou
semana (linha mediana com a faixa p25–p75, até quatro séries, cada gráfico
também como tabela de dados); e uma classificação dos relays de um modelo ou
dos modelos de um relay. Os relays são agrupados pela sua entrada na base de
conhecimento (relays guardados e fornecedores), por isso renomear um relay
reagrupa o seu histórico. Intervalos com menos de 3 execuções aparecem
esbatidos — uma única auditoria pode ser um valor atípico; um monitor dá
medições regulares. Execuções mais antigas mostram o que mediram: a página diz
em quantas execuções um valor se baseia. Por omissão compara uma suite e um
modo de sondagem (os mais frequentes), para não misturar execuções diferentes;
filtros e vista ficam no URL, por isso uma vista pode ser guardada nos
favoritos ou partilhada. Nada sai da máquina.

Outros painéis respondem a perguntas mais concretas: **horas de ponta** (um
mapa de calor dia da semana × hora do TTFT, da latência e da velocidade de descodificação (mediana e caudas p95 /
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
relay informa mais tokens do que o ekte contou — e as proporções de tokens de
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

## Idiomas

Um menu de idioma no cabeçalho de cada página muda a interface entre
**🇬🇧 inglês** (por omissão), **🇨🇳 chinês** (a interface original),
**🇫🇷 francês**, **🇪🇸 espanhol**, **🇵🇹 português**, **🇮🇹 italiano**,
**🇩🇪 alemão** e **🇳🇴 norueguês** (bokmål); a escolha é memorizada por navegador.

Os relatórios transferidos a partir da interface (**Transferir relatório**: JSON,
Markdown, HTML ou PDF) seguem o idioma escolhido: as chaves JSON, os valores
enumerados (`risk_level`, `status`, `severity`, …), os ids e as evidências ficam
exatamente como no relatório da CLI (o JSON continua a ser um relatório ekte
válido), enquanto os valores legíveis (título e resumo do veredito, títulos e
resumos das constatações, recomendações, nomes dos detetores, notas) são
traduzidos, e o nome do ficheiro leva o idioma (`ekte-report.pt.json`,
`ekte-report.pt.pdf`). Os títulos de secção dos ficheiros Markdown/HTML/PDF
ficam em inglês. Os relatórios da CLI com `--format json|md|html|pdf` ficam em
inglês.

**Os prompts enviados ao endpoint auditado não seguem o idioma da interface.**
Todo o texto que o ekte envia a uma API de LLM está em inglês, para que o mesmo
relay receba o mesmo veredito seja quem for que leia o relatório (as verificações
de respostas e as estimativas de tokens estão calibradas para esses textos
exatos). As únicas exceções são as impressões da base de conhecimento cujo idioma
*é* a medida — por exemplo, as sondas de fluência em chinês, de tokenizer e de
autoidentificação dos modelos chineses. Cada relatório regista os idiomas de
sonda efetivamente usados (`prompt_languages`, p. ex. `["en", "zh"]`).
Cada relatório regista também como o endpoint foi interrogado: o protocolo
(`target.api`: `openai`, `anthropic` ou `responses`), se `--api auto` o detetou
(`target.api_auto`) e o modo de pedido da sonda de desempenho (`stream_mode`:
`stream`, `non_stream` ou `both` para a suíte completa). A página de histórico da
interface web pode filtrar pelos três.
`started_at` regista quando a auditoria começou (UTC); o `start_ms` de cada
registo de pedido conta a partir desse momento.
