# Executar a interface web em Docker

> [🇬🇧 English](../../../guide/docker.md) · [🇨🇳 中文](../../zh-CN/guide/docker.md) · [🇫🇷 Français](../../fr/guide/docker.md) · [🇪🇸 Español](../../es/guide/docker.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/docker.md) · [🇩🇪 Deutsch](../../de/guide/docker.md) · [🇳🇴 Norsk](../../nb/guide/docker.md)

`ekte serve` é uma ferramenta de utilizador único, sem início de sessão. Fora de
um contentor, só escuta em loopback (`127.0.0.1`, `::1`, `localhost`) e recusa
qualquer outro endereço de escuta. Um contentor é a única exceção: o servidor tem
de escutar nas interfaces do próprio contentor para que a publicação de portas
do Docker o consiga alcançar.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# abra http://localhost:8000
```

**Publique sempre em `127.0.0.1`** (`-p 127.0.0.1:8000:8000`, não `-p 8000:8000`).
Um simples `-p 8000:8000` publica a interface — e todas as chaves API nela
escritas ou guardadas num monitor — na sua rede.

## Variáveis de ambiente

| Variável | Valor por omissão | Função |
|---|---|---|
| `EKTE_CONTAINER` | não definida (`1` na imagem) | Permite escutar fora do loopback. O ekte verifica também que corre mesmo num contentor (`/.dockerenv`, `/run/.containerenv` ou Kubernetes); defini-la num anfitrião normal não abre o servidor. |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` na imagem) | Endereço de escuta. Tudo o que não seja loopback precisa de `EKTE_CONTAINER=1`. `--host` tem prioridade sobre ela. |
| `EKTE_PORT` | `8000` | Porta dentro do contentor. `--port` tem prioridade sobre ela. |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` na imagem) | Histórico de auditorias, monitores (incluindo as suas chaves API) e as suas próprias entradas da base de conhecimento. Monte aqui um volume para os conservar. |
| `EKTE_SECRET_KEY` | não definida | Chave mestra que cifra as chaves API guardadas dos monitores: a chave que a página **Monitores** (ou `ekte secret rotate`) lhe mostrou, ou `file:/run/secrets/ekte_key` / `env:VAR`. Se não estiver definida, introduz a chave na página **Monitores** após cada arranque do contentor. Nunca é guardada em `EKTE_DATA_DIR`. Defini-la num diretório de dados novo seleciona o armazenamento cifrado das chaves; sem ela, as chaves API dos monitores não são guardadas de todo e têm de ser introduzidas de novo após cada arranque do contentor. Ver abaixo. |
| `EKTE_KB_DIR` | não definida | Diretório YAML adicional da base de conhecimento, montado por exemplo só de leitura (`-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb`). |
| `EKTE_NO_USER_KB` | não definida | `1` ignora as entradas da base de conhecimento que acrescentou na interface (`kb.db`). |
| `EKTE_ALLOWED_HOSTS` | não definida | Nomes de anfitrião adicionais, separados por vírgulas, a que a interface responde, se a alcançar com um nome que não seja `localhost`/`127.0.0.1`. |

**Se vem da imagem zing.** Mude o nome das opções `-e ZING_*` para `EKTE_*`. O
ekte continua a ler uma variável `ZING_*` cujo nome `EKTE_*` não esteja definido,
mas a imagem define ela própria `EKTE_CONTAINER`, `EKTE_HOST`, `EKTE_PORT` e
`EKTE_DATA_DIR`, pelo que um antigo `ZING_HOST`, `ZING_PORT` ou `ZING_DATA_DIR`
não tem efeito no contentor. O volume de dados continua em `/data` e o
utilizador sem privilégios mantém o uid 10001, pelo que um volume `zing-data`
existente pode ser montado tal como está (`-v zing-data:/data`). O recurso às
variáveis `ZING_*` está obsoleto e é removido no ekte 1.0.0 (consulte a
[política de estabilidade](../../../reference/stability.md#deprecation-zing)).

## O que protege a interface

- **Lista de anfitriões permitidos.** Os pedidos cujo cabeçalho `Host` não seja
  `localhost`, `127.0.0.1`, `[::1]` nem conste de `EKTE_ALLOWED_HOSTS` são
  recusados. Isto impede o DNS rebinding, em que um site aponta o seu próprio
  domínio para `127.0.0.1` para falar com servidores locais. A porta não é
  verificada, pelo que qualquer porta publicada no anfitrião funciona.
- **Verificações de origem e de JSON.** Os pedidos que alteram o estado vindos
  de outra origem são recusados, e os corpos dos pedidos têm de ser
  `application/json`, pelo que outro site não consegue submeter formulários à
  API local.
- **Cabeçalhos de segurança.** A interface não pode ser incorporada noutros
  sites (`X-Frame-Options`, `frame-ancestors`), e nenhum referrer sai da página.
- **Chaves dos monitores cifradas.** As chaves API guardadas são cifradas com uma
  chave mestra que nunca é escrita no volume de dados, pelo que uma cópia do
  volume não revela nenhuma chave API. Sem `EKTE_SECRET_KEY`, a página
  **Monitores** mostra a chave uma única vez quando é criada e pede-a após cada
  arranque do contentor; os monitores que precisam dela esperam até lá. Para
  reinícios sem supervisão, passe-a como segredo Docker (o servidor guarda-a em
  memória; execute um único processo de servidor por volume de dados):

  ```bash
  # a chave que a página Monitores lhe mostrou, ou uma nova: ekte secret rotate
  docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data \
    -v "$PWD/ekte_key:/run/secrets/ekte_key:ro" \
    -e EKTE_SECRET_KEY=file:/run/secrets/ekte_key ekte
  ```

  Uma `EKTE_SECRET_KEY` que não seja a chave usada pelas chaves API guardadas é
  recusada (a interface indica-o). Rode-a com `ekte secret rotate`; uma chave
  perdida só pode ser reposta na página **Monitores**, o que descarta as chaves
  API guardadas.
- **Dados só para o proprietário.** O diretório de dados é criado com `0700` e
  cada ficheiro de base de dados com `0600`; a imagem corre como um utilizador
  sem privilégios.
