# Se vem do zing

> [🇬🇧 English](../../../guide/migrating-from-zing.md) · [🇨🇳 中文](../../zh-CN/guide/migrating-from-zing.md) · [🇫🇷 Français](../../fr/guide/migrating-from-zing.md) · [🇪🇸 Español](../../es/guide/migrating-from-zing.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/migrating-from-zing.md) · [🇩🇪 Deutsch](../../de/guide/migrating-from-zing.md) · [🇳🇴 Norsk](../../nb/guide/migrating-from-zing.md)

O ekte continua o [zing](https://github.com/cenbonew/zing) (a última versão foi
a 0.11.0) com um novo nome. O que muda numa instalação existente:

- **Pacote e comando.** `pip install ekte` (antes `zing-audit`), o comando
  `ekte` (antes `zing`), o pacote Python `ekte`. Os extras mantêm o nome, p. ex.
  `pip install 'ekte[web]'`. Os dois pacotes não partilham comando nem módulo,
  por isso o `zing-audit` pode continuar instalado ao lado do ekte.
- **Variáveis de ambiente.** `EKTE_*` substitui `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). Uma variável `ZING_*` antiga continua a
  funcionar enquanto o seu nome `EKTE_*` não estiver definido; o ekte indica-a
  uma vez no stderr.
- **Diretório de dados.** Na primeira execução, o ekte copia `~/.zing` para
  `~/.ekte` (histórico, monitores, base de conhecimento) se `~/.ekte` ainda não
  existir, e a partir daí trabalha só com `~/.ekte`. `~/.zing` fica como está,
  para o zing se ainda estiver em uso; apague-o quando já não precisar dele. Um
  diretório definido com `EKTE_DATA_DIR`, `ZING_DATA_DIR` ou `--data-dir` é
  usado tal como está.
- **Interface web.** O idioma, o tema e os filtros e uma chave mestra guardada no
  gestor de palavras-passe do navegador mantêm-se. A interface clássica do zing
  deixou de existir: os seus endereços (`/tools`, `/console`) abrem a página de auditoria (`/`).
- **Relatórios e sondas.** Os relatórios, os webhooks e os nomes de ficheiros
  indicam `ekte` (p. ex. `"tool": "ekte"`, `ekte-report.json`), tal como as
  sondas enviadas aos relays. Os scripts que procuram `zing` neles têm de ser
  atualizados.
- **Calendário.** Toda a camada de compatibilidade (a leitura de `ZING_*`, a cópia de `~/.zing`, a transferência de definições do navegador, cookies e da chave mestra guardada, e os endereços da interface clássica) está obsoleta e é removida no ekte **1.0.0** (1.0.0rc1 é a primeira versão sem ela). Até lá cada parte continua a funcionar e o seu aviso indica esta versão; os antigos endereços de página `/v2/…` também redirecionam até à 1.0.0. O ekte nunca apaga um `~/.zing` antigo, nem quando a cópia é removida.
