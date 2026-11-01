# Monitorização

> [🇬🇧 English](../../../guide/monitoring.md) · [🇨🇳 中文](../../zh-CN/guide/monitoring.md) · [🇫🇷 Français](../../fr/guide/monitoring.md) · [🇪🇸 Español](../../es/guide/monitoring.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/monitoring.md) · [🇩🇪 Deutsch](../../de/guide/monitoring.md) · [🇳🇴 Norsk](../../nb/guide/monitoring.md)

Um relay pode servir hoje o modelo verdadeiro e trocá-lo discretamente na semana
seguinte. `ekte watch` volta a auditar segundo um calendário, regista cada
execução no histórico e alerta um webhook quando o risco ultrapassa um limite ou
**piora** em relação à execução anterior.

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang pt                                     # ou --once para cron
```

Os alertas são formatados para **Slack / Feishu / DingTalk / JSON genérico**,
detetados automaticamente a partir do URL do webhook, e redigidos no idioma dos
alertas — inglês por omissão; `--alert-lang en|zh|fr|es|pt|it|de|nb`. O payload
JSON genérico mantém neutras as suas chaves e valores de máquina (`risk_level`,
`score`, …), traduz os legíveis (`text`, `headline`, `key_findings`) e indica o
`language`.

**Na interface web**, `ekte serve` executa os mesmos monitores num agendador em
segundo plano dentro do processo do servidor, regista cada execução no
**Histórico** e envia os mesmos alertas por webhook. Abra uma execução no **Histórico** e escolha **Agendar como
monitor**. O ekte copia a configuração dessa execução (relay, modelo, modelo
declarado, fornecedor, suite, dimensões personalizadas) para um monitor em
pausa na página **Monitores**; defina aí o intervalo e a chave API (o Histórico
nunca guarda chaves) e ative-o. Intervalo, chave, **Limite de alerta**,
webhooks e **Idioma dos alertas** editam-se diretamente em cada monitor. Um
clique no nome recolhe o cartão para nome, estado e última execução
(**Recolher tudo** / **Expandir tudo** acima da lista; guardado por
navegador), e o painel de filtros (pesquisa, estado, último risco, tipo de
endpoint, relay, suite) restringe uma lista longa como no **Histórico**.

Cada monitor tem o seu próprio idioma de alertas (por omissão, o da
interface), pode ser executado agora, pausado ou eliminado, e fica fixado ao
perfil da base de conhecimento com que foi criado até que volte a fixá-lo.

Os monitores cuja hora chegou correm ao mesmo tempo, cada um como uma auditoria
própria, mas nunca mais de uma auditoria de cada vez por host de relay e no
máximo `EKTE_MAX_PARALLEL_AUDITS` no total; uma execução espera por uma vaga
livre (uma auditoria que inicie à mão também pode ficar em fila atrás de
monitores em execução). A hora de uma execução é o momento em que a sua
auditoria começa, depois de qualquer espera. A verificação de regressão compara
com a execução guardada mais recente do mesmo relay e modelo, por muitas outras
execuções que tenham sido guardadas entretanto. Os webhooks de alerta de uma
execução são enviados ao mesmo tempo, para que um lento ou inacessível não
atrase os outros. As chaves são guardadas cifradas no seu diretório de dados
local e nunca são devolvidas ao navegador.

**Armazenamento das chaves de API.** Por omissão, o ekte **não guarda** as
chaves de API dos monitores: uma chave introduzida fica apenas na memória do
`ekte serve` e nunca é escrita no disco. Após um reinício, a página
**Monitores** indica os monitores que precisam novamente da chave; aguardam (sem
execução falhada nem alerta) até que a introduza. Os monitores sem chave e as
referências `env:`/`file:` continuam a funcionar. Para que as chaves sobrevivam
a reinícios, escolha **Guardar cifradas neste computador** em **Armazenamento
das chaves de API** na página **Monitores**: as chaves passam a ser guardadas
em `watches.db`, cifradas com uma chave mestra. Voltar atrás move as chaves
guardadas para a memória e apaga-as de `watches.db`. O aviso da página mostra o
modo ativo, pede confirmação antes de mudar e indica o que foi movido. Uma
instalação que já
guardava chaves cifradas, ou que define `EKTE_SECRET_KEY`, continua a guardá-las
até mudar.

**Chave mestra.** As chaves API dos monitores são cifradas com uma chave
mestra que o ekte nunca escreve no disco. Da primeira vez que guarda uma chave
API, a página **Monitores** cria-a e mostra-a uma única vez: copie-a ou
transfira-a, guarde-a num gestor de palavras-passe (o seu navegador pode
guardá-la) e cole-a de novo para confirmar. Após cada reinício do `ekte serve` a
página volta a pedi-la (o navegador pode preenchê-la); até lá, os monitores que
precisam dela esperam, enquanto os monitores sem chave ou com chaves
`env:`/`file:` continuam a ser executados. A barra de estado da página oferece
também **Bloquear**, **Rodar** e **Esqueceu a chave?** (descarta as chaves API
cifradas para que as possa introduzir de novo). Para uso sem supervisão ou em
Docker, passe a chave em `EKTE_SECRET_KEY` (consulte
[Docker](docker.md)); `ekte secret status | export | rotate`
gerem-na na linha de comandos.
