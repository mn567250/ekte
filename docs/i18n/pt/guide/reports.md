# Relatórios

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · [🇫🇷 Français](../../fr/guide/reports.md) · [🇪🇸 Español](../../es/guide/reports.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` e `ekte compare` imprimem um veredito e escrevem o relatório em
`reports/` (`--out-dir`) como JSON, Markdown, HTML e PDF (`--format all`, o valor
por omissão); `--format json|md|html|pdf` escreve um único formato. `--json` e
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
**Dimension details**, as constatações de cada detetor com as suas evidências, a
secção de desempenho, o perfil da base de conhecimento usado e os idiomas de
sonda. O texto controlado pelo relay é ocultado e escapado antes de ser escrito.

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

As chaves e os cabeçalhos sensíveis são removidos antes de qualquer escrita
(ver [Privacidade](privacy.md)). Cada linha corresponde a
`ekte/schemas/evidence.schema.json` ([Esquemas](../../../reference/schemas.md)).
Na interface web, **Ver evidências** sob uma constatação de uma execução
guardada lista os pedidos da verificação correspondente e abre cada pedido e
resposta bruta.
