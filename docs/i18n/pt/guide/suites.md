# Suites e modo de comparação

> [🇬🇧 English](../../../guide/suites.md) · [🇨🇳 中文](../../zh-CN/guide/suites.md) · [🇫🇷 Français](../../fr/guide/suites.md) · [🇪🇸 Español](../../es/guide/suites.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/suites.md) · [🇩🇪 Deutsch](../../de/guide/suites.md) · [🇳🇴 Norsk](../../nb/guide/suites.md)

| Suite | Detetores | Custo |
|---|---|---|
| `smoke` | connectivity, security | muito baixo |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | baixo–médio |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (com `--judge`) | mais alto (as sondas de contexto longo e de tempos custam tokens) |
| `full` | os detetores de `deep`, com o desempenho medido com e sem streaming | o mais alto |
| `custom` | apenas as dimensões que escolher, com a profundidade de `deep` | conforme a seleção |

A sonda da janela de contexto é limitada por `--max-context-tokens` (200K por
omissão), para que auditar um modelo de 1M de tokens continue acessível.
`--only` / `--skip` executam ou excluem detetores individuais pelo seu id.
Uma janela maior do que o limite de `--max-context-tokens` é reportada como *verificada até ao limite*, nunca como truncada.

## Suite personalizada

Execute apenas as dimensões que lhe interessam, poupando tempo e tokens. Cada
detetor de cada dimensão escolhida é executado, como em `deep`:

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` é repetível ou separado por vírgulas e implica
`--suite custom`; num ficheiro de configuração use
`run.dimensions: [protocol, performance]`. As dimensões são `connectivity`,
`protocol`, `context_window`, `model_identity`, `capability`, `streaming`,
`billing`, `reliability`, `security` e `performance`. Na interface web, o botão
de suite `custom` abre a mesma escolha (**Dimensões a executar**) na página de
auditoria e nos monitores.

A **pontuação global é a média ponderada apenas das dimensões escolhidas**; as
que ficam de fora aparecem como «não selecionadas». O veredito de risco também
se baseia nas dimensões escolhidas: sem a identidade do modelo cobre apenas
essas, não qual modelo é servido, e indica-o.

## Modo de comparação e juiz LLM

O ekte tem dois modos de deteção:

- **Código puro (por omissão):** todos os detetores exceto `quality_judge`
  decidem com código determinista — impressões, varrimento de contexto,
  aritmética de faturação, tempos do streaming. Não é preciso um segundo modelo;
  os resultados são reproduzíveis.
- **Híbrido código + LLM (`--judge`):** pergunta ainda a um modelo juiz *de
  confiança* (configurado à parte, nunca o alvo) se as respostas do alvo se
  parecem com o modelo declarado — sinais difusos como a qualidade e a
  profundidade de raciocínio que o código sozinho não consegue decidir. É o
  detetor `quality_judge`.

```bash
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

O **modo de comparação** (`ekte compare`, ou **Comparar com uma referência
confiável** na interface web) executa as mesmas sondas, ao mesmo tempo, contra
uma referência de confiança do modelo declarado. É a via de confirmação mais
forte: respostas de identidade, parâmetros de pedido rejeitados, canários de
adulteração e desempenho são avaliados lado a lado, e só uma referência permite
que a confiança do veredito seja *alta*. Sem `--judge-base-url`, o modo de
comparação usa a referência como juiz.
