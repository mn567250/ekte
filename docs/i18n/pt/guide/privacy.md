# Privacidade e dados locais

> [🇬🇧 English](../../../guide/privacy.md) · [🇨🇳 中文](../../zh-CN/guide/privacy.md) · [🇫🇷 Français](../../fr/guide/privacy.md) · [🇪🇸 Español](../../es/guide/privacy.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/privacy.md) · [🇩🇪 Deutsch](../../de/guide/privacy.md) · [🇳🇴 Norsk](../../nb/guide/privacy.md)

- **Apenas local.** `ekte serve` só escuta em loopback (`127.0.0.1`, `::1`,
  `localhost`), só responde a esses nomes de anfitrião e recusa pedidos entre
  sites; não tem início de sessão porque nada fora da sua máquina o consegue
  alcançar. O ekte só contacta os endpoints que configura (alvo, referência,
  juiz, webhooks); não descarrega nada em tempo de execução, nem sequer
  ficheiros de tokenizer.
- **Chaves.** Os relatórios e o histórico guardam apenas uma impressão de uma
  chave API. As chaves dos monitores são guardadas cifradas em `watches.db`;
  a chave mestra que as decifra nunca é escrita no diretório de dados
  (guarde-a, consulte [Monitorização](monitoring.md)), por isso uma cópia do
  diretório não revela nenhuma chave API. Mesmo assim, só o seu utilizador tem
  acesso ao diretório.
- **Diretório de dados.** `~/.ekte` (ou `EKTE_DATA_DIR`), criado com `0700` e
  ficheiros com `0600`: `history.db` (histórico de auditorias), `watches.db`
  (monitores, com as suas chaves cifradas) e `kb.db` (as suas entradas da
  base de conhecimento). Apague o diretório para remover tudo.
  `ekte data-dir` mostra onde está; `--data-dir CAMINHO` escolhe outro para uma
  execução, p. ex. `ekte serve --data-dir .` guarda as bases de dados na pasta
  atual. São ficheiros SQLite normais que pode abrir para as suas próprias
  análises (de preferência só leitura enquanto o ekte corre). Não faça commit
  de `watches.db` se essa pasta for um repositório.
  `history_metrics` guarda uma linha de valores medidos por execução e
  `history_requests` cada registo de pedido (guardado aí uma só vez, não dentro
  de cada relatório).

## Utilização responsável

O ekte é uma ajuda de auditoria de caixa-preta. **Não consegue provar**:

- que um fornecedor guarda os seus prompts ou treina com eles,
- que encaminha sempre para um único modelo exato (os relays podem encaminhar de forma probabilística),
- fraude de faturação para lá do que a estimativa independente de tokens pode sugerir.

Use os relatórios para a sua própria diligência. **Não acuse publicamente um
fornecedor** com base numa única execução sem rever o tamanho da amostra, as
definições de custo e a lei local. Execute `ekte compare` contra uma referência
de confiança antes de tirar conclusões fortes.
