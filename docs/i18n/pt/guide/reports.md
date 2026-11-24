# Relatórios

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` e `ekte compare` imprimem um veredito e escrevem o relatório em
`reports/` (`--out-dir`) como JSON, Markdown, HTML e PDF (`--format all`, o valor
por omissão); `--format json|md|html|pdf` escreve um único formato. `--json` e
`--compact` imprimem antes em stdout.

```text
╭─ ✗ Likely substituted — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · coverage 100% · confidence medium             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

Um relatório contém o veredito (risco, confiança, pontuação, nota), as
constatações principais com recomendações, as pontuações por dimensão e os
**Dimension details**, as constatações de cada detetor com as suas evidências, a
secção de desempenho, o perfil da base de conhecimento usado e os idiomas de
sonda. O texto controlado pelo relay é ocultado e escapado antes de ser escrito.

Ao lado da pontuação, cada relatório mostra a **cobertura**: a parcela do peso
das dimensões executadas que pôde ser avaliada. O resumo do veredito nomeia a
dimensão executada que não pôde ser avaliada, e uma cobertura baixa limita a
nota ou omite-a («sem classificação: foi avaliado muito pouco»); ver [Pontuação global, nota e pesos](methodology.md#pontuação-global-nota-e-pesos).

## Ficheiros de evidências

Com `--evidence PATH` (`check`, `compare`, `image`, `audio`), e por omissão
para cada execução guardada no histórico, o ekte escreve também cada pedido e
resposta HTTP bruta da execução num ficheiro: JSON Lines num fluxo zstd,
`<run_id>.jsonl.zst` (um diretório indicado como `PATH` recebe esse nome). A
primeira linha descreve a execução; cada linha seguinte é um pedido com a sua
resposta, incluindo quando chegou cada parte da resposta. O `seq` de uma linha
é o `seq` do pedido em `performance.requests` do relatório, pelo que cada
pedido que o relatório lista pode ser consultado. O campo `evidence` do
relatório indica o ficheiro com o seu SHA-256 e o número de trocas.

```bash
ekte check --base-url https://relay.example.com/v1 --model gpt-4o --evidence reports/
zstd -dc reports/<run_id>.jsonl.zst | jq -c 'select(.seq == 12)'
```

Cada constatação indica os pedidos em que se baseia (`evidence_seqs`; vazio
quando não se baseia em nenhum, como a verificação TLS). `ekte evidence-export`
recebe o ficheiro (ou o id de uma execução guardada) e converte-o em HAR para
um visualizador HAR ou as ferramentas de programador do navegador
(`--as har`), num script curl que volta a enviar os pedidos
(`--as curl`; defina primeiro `EKTE_API_KEY`, o ficheiro nunca contém a
chave) ou num único documento JSON (`--as json`); `--seq` escolhe
pedidos.

`ekte rescore` reavalia uma execução registada com a versão do ekte
instalada: repete a mesma auditoria, mas responde a cada pedido com a resposta
registada (ao ritmo registado) em vez de contactar o intermediário, para que as
verificações melhoradas se apliquem a execuções antigas. Aceita o id de uma execução guardada ou um ficheiro de relatório com
`--evidence PATH`. Com `--replace` o resultado substitui a execução guardada
(mesmo id, hora e monitor); sem essa opção continua a ser guardado como nova
execução, o que está obsoleto e mostra um aviso (uma versão posterior do ekte
substituirá por omissão; `--no-save` não guarda nada). Uma
verificação que agora pergunta algo que a execução registada nunca perguntou
fica inconclusiva em vez de ser pontuada com base num palpite; o campo
`rescored_from` do relatório indica quantos pedidos foram reproduzidos e que
verificações não tinham nenhum.

`ekte rescore --all` reavalia, uma após outra, todas as execuções guardadas
avaliadas por outra versão do ekte, substitui cada uma e mostra o veredito
antes e depois. Uma execução sem um ficheiro de evidências utilizável não é
reavaliada: mantém o veredito e é ignorada com o motivo. O mesmo acontece a uma
execução cuja reavaliação não teria pontuação nenhuma (nenhuma das suas
verificações tem uma resposta gravada, como numa execução anterior a elas), ou a
uma execução com nota cuja reavaliação ficaria sem nota (poucas das suas
verificações têm uma resposta gravada);
`ekte rescore ID` não guarda essa reavaliação. O `ekte serve` faz o
mesmo em segundo plano no primeiro arranque após uma atualização (ver
[Interface web](web-ui.md)).

As exportações em Markdown, HTML e PDF de um relatório reavaliado indicam
as duas versões, quando foi reavaliado e o veredito anterior; o veredito
`--compact` traz essas informações como `rescored`.

As chaves e os cabeçalhos sensíveis são removidos antes de qualquer escrita
(ver [Privacidade](privacy.md)). Cada linha corresponde a
`ekte/schemas/evidence.schema.json` ([Esquemas](../../../reference/schemas.md)).
Na interface web, **Ver evidências** sob uma constatação de uma execução
guardada lista os pedidos da verificação correspondente e abre cada pedido e
resposta bruta.
