# Início rápido

> [🇬🇧 English](../../../guide/quickstart.md) · [🇨🇳 中文](../../zh-CN/guide/quickstart.md) · [🇫🇷 Français](../../fr/guide/quickstart.md) · [🇪🇸 Español](../../es/guide/quickstart.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/quickstart.md) · [🇩🇪 Deutsch](../../de/guide/quickstart.md) · [🇳🇴 Norsk](../../nb/guide/quickstart.md)

```bash
# 1) auditar um relay face ao que declara (id do modelo + pista do fornecedor)
export EKTE_API_KEY=sk-a-sua-chave-do-relay
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) a verificação mais forte: comparar com uma referência de confiança do mesmo modelo
export OPENAI_API_KEY=sk-a-sua-chave-openai
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) auditar um relay nativo da Anthropic (API Messages) — o protocolo é detetado
#    automaticamente a partir de base_url/model, ou forçado com --api anthropic
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) confirmar uma substituição suspeita: auditar o id REAL do modelo do relay face ao
#    perfil com que é vendido (aqui: um modelo Doubao vendido como deepseek-v4-flash)
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) listar os modelos que um endpoint anuncia
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) consultar a base de conhecimento
ekte kb            # todos os perfis, com a sua origem
ekte kb deepseek   # um fornecedor

# 7) gerar uma configuração que pode versionar
ekte init          # escreve ekte.yaml
ekte check -c ekte.yaml
```

As chaves de API podem ser dadas em claro, como `env:VAR` ou como
`file:/caminho`; os relatórios contêm apenas uma impressão da chave. Um ficheiro
de configuração completo está em [`examples/ekte.yaml`](../../../../examples/ekte.yaml).

O ficheiro tem uma versão de formato (`version: 1`; um ficheiro sem versão é o formato 1). Tipos errados e valores inválidos são rejeitados indicando ficheiro, linha e chave; chaves desconhecidas são ignoradas com um aviso até ao ekte 1.0.0, que as rejeita. `ekte config migrate` atualiza um ficheiro antigo. O esquema é [`docs/schemas/config.schema.json`](../../../schemas/config.schema.json).

## Como ferramenta para um LLM / agente

O ekte foi feito para ser controlado por outro programa ou modelo. Tudo sai para
stdout em JSON, erros incluídos, e o código de saída serve de barreira.

```bash
# veredito leve, próprio para agentes (~5x mais pequeno que --json: sem as evidências volumosas)
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# relatório estruturado completo quando precisa das evidências de cada constatação
ekte check --base-url ... --model gpt-4o --json

# primeiro o orçamento: que detectores correm + chamadas à API estimadas, SEM fazer nenhuma
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# barreira pelo código de saída (1 se o risco >= medium, ou a pontuação ficar abaixo de --fail-under);
# os erros de configuração/utilização saem com 2, em JSON
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# descoberta legível por máquina
ekte kb --json                      # toda a base de conhecimento
ekte models --base-url ... --json   # o que um endpoint anuncia
```

No modo `--json`/`--compact`, uma configuração errada imprime `{"error": {...}}`
(código de saída 2) em vez de uma mensagem para pessoas, para que um pipeline
possa tratar as falhas de forma uniforme.
