# Base de conhecimento

> [🇬🇧 English](../../../guide/knowledge-base.md) · [🇨🇳 中文](../../zh-CN/guide/knowledge-base.md) · [🇫🇷 Français](../../fr/guide/knowledge-base.md) · [🇪🇸 Español](../../es/guide/knowledge-base.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/knowledge-base.md) · [🇩🇪 Deutsch](../../de/guide/knowledge-base.md) · [🇳🇴 Norsk](../../nb/guide/knowledge-base.md)

O ekte avalia um relay segundo o **perfil** do modelo que declara: janela de
contexto nativa, saída máxima, data de corte do conhecimento, tokenizer,
capacidades, palavras-chave de identidade e impressões comportamentais. Os perfis
integrados cobrem OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM e
Moonshot (`ekte kb` lista-os). Há três camadas; as posteriores prevalecem:

1. Perfis **integrados**, um ficheiro YAML por fornecedor em
   [`ekte/knowledge/data/`](../../../../ekte/knowledge/data).
2. **Um diretório com os seus próprios ficheiros YAML**: `--kb-dir ./my-profiles`
   (repetível) ou `EKTE_KB_DIR`.
3. **As suas entradas** (`kb.db` no diretório de dados), adicionadas sem ficheiros
   YAML nem instalação editável:
   - na página **Conhecimento** da interface web (`/kb`), com um separador
     para **Modelos**, **Fornecedores** e **Relays**. Cada separador lista o conjunto
     completo — incluídos, `EKTE_KB_DIR` e os seus (marcados **O seu**) — com um
     filtro, um interruptor por item e um formulário **Adicionar …**: **Adicionar
     um modelo** → **Copiar o prompt de pesquisa** para o assistente de IA da sua
     escolha, carregar ou colar o YAML com que ele responde e depois **Verificar e
     guardar**; **Adicionar um fornecedor** aceita YAML de fornecedor da mesma forma;
     **Adicionar um relay** pede um nome e um URL base. **Qual perfil um ID de
     modelo usa?** mostra como um id é resolvido; as suas entradas podem ser
     exportadas como YAML;
   - na página **Auditoria** da interface web: **Guardar na
     base** mantém o nome e o URL base de um relay (uma entrada de fornecedor sem
     modelos), listado em **Conhecimento → Relays**;
   - na linha de comandos: `ekte kb-prompt <model>`, `ekte kb-import <file>`
     (acrescente `--check` para apenas verificar) e `ekte kb-export`.

Antes de guardar uma entrada, o ekte verifica-a: esquema e limites, expressões
regulares perigosas, cada prompt que enviaria e ids de modelo que seriam
resolvidos para outro perfil. Um modelo seu com o id de um integrado substitui-o
(assinalado como *sombreando-o*), mas nunca altera as definições próprias de um
fornecedor integrado; as impressões são fundidas por id. Desativar um modelo,
fornecedor ou relay incluído na página **Conhecimento** também fica guardado em
`kb.db`: um id de modelo desativado deixa de ser resolvido e um fornecedor
desativado leva consigo os seus modelos e URLs base. `ekte check` e `ekte serve`
usam exatamente os mesmos perfis; `--no-user-kb` (ou `EKTE_NO_USER_KB=1`) deixa de
fora as suas entradas e interruptores.

Um modelo com `identity_keywords` vazio não é guardado assim: o ekte preenche
as suas próprias palavras de marca a partir dos nomes do fornecedor e do modelo
(por exemplo `glm` e `z.ai`) e mostra um
aviso para as verificar, pois sem elas a verificação de identidade poderia
tomar o próprio fabricante do modelo por uma marca rival. O prompt de pesquisa
pede-as explicitamente ao assistente de IA.

Cada relatório regista o perfil contra o qual auditou (`knowledge`: fornecedor,
modelo, como o id foi resolvido, a sua origem e um instantâneo completo com o seu
hash de conteúdo), pelo que um relatório continua verificável depois de a base de
conhecimento mudar.
