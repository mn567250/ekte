# Desempenho

> [🇬🇧 English](../../../guide/performance.md) · [🇨🇳 中文](../../zh-CN/guide/performance.md) · [🇫🇷 Français](../../fr/guide/performance.md) · [🇪🇸 Español](../../es/guide/performance.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/performance.md) · [🇩🇪 Deutsch](../../de/guide/performance.md) · [🇳🇴 Norsk](../../nb/guide/performance.md)

Cada relatório inclui uma secção **performance**: latência, tempo até ao
primeiro token (TTFT), tokens/s de descodificação e ponta a ponta, latência e
jitter entre fragmentos, taxas de erro/timeout/429, uma decomposição da rede
(ligação TCP, TLS, uma ida e volta `GET /models`, tempo de servidor) e arranque a
frio, cada um como count / min / mean / p50 / p75 / p90 / p95 / p99 / max /
stdev.

Quando a sonda dedicada corre, pontua a dimensão **Desempenho**. A pontuação mede
a **constância**, não a velocidade bruta, pelo que um endpoint lento mas
constante (um modelo local ou auto-alojado) não é penalizado por não ser um
centro de dados; as verificações e os seus pontos estão na
[Metodologia](methodology.md#performance--desempenho). As constatações de
desempenho são no máximo de gravidade baixa: mexem na pontuação, nunca no veredito de risco. Sem a sonda (`standard` sem referência,
`smoke`), a dimensão não corre e sai da pontuação global.

- **standard** recolhe a secção a partir dos próprios pedidos da auditoria.
- **deep / full / custom** acrescentam uma sonda dedicada: 100 pedidos que não
  podem vir de cache, de 128 tokens de saída (um id de pedido aleatório abre cada
  prompt; não são enviados parâmetros de cache nem de raciocínio) mais uma rajada
  com `--concurrency`. Ajuste-a com `--performance-requests` (0 desativa-a) e
  `--performance-max-tokens`.
- A sonda usa streaming por omissão; `--performance-non-streaming` (ou o
  seletor **Streaming / Sem streaming** da interface web) mede relays que não
  suportam streaming. **full** mede os dois modos, intercalados, e mostra-os lado
  a lado.
- **compare** corre a sonda nos dois endpoints, alternando pedidos, e acrescenta
  uma tabela alvo-vs-referência (5 pedidos por lado em `standard`, poucos demais
  para as verificações de constância) cujas diferenças são marcadas a verde ✓
  quando o alvo é melhor e a vermelho ✗ quando é pior.

Os tokens são contados duas vezes — a partir do `usage` do relay e localmente —,
pelo que o débito pode ser medido mesmo sem `usage`. A contagem local é uma
estimativa feita com uma heurística integrada (cerca de ±15-20%; nenhum tokenizer
é usado ou descarregado), e a secção indica-o sempre. Um percentil só é mostrado
com amostras suficientes (p90 a partir de 10, p95 a partir de 20, p99 a partir de
100). O relatório JSON guarda os tempos de cada pedido (só números, sem texto); o
relatório HTML e a interface web representam-nos ao longo da linha temporal da
auditoria.

Auditorias que correm ao mesmo tempo no `ekte serve` (vários separadores do
navegador, monitores) não distorcem os tempos umas das outras: a preparação que
exige muito CPU, como construir os prompts longos da janela de contexto, corre
fora do event loop do servidor.

**Tempos limite.** `timeout_sec` (`--timeout`, 60 s por omissão) é a base; cada
pedido recebe mais tempo conforme o tamanho do prompt e o orçamento de
saída, para que uma sonda longa de janela de contexto ou um modelo auto-alojado
lento não seja interrompido ao fim de um minuto. Hosts locais e privados
(`localhost`, `127.x`, `192.168.x`, `host.docker.internal`, …) recebem pelo menos
300 s. `max_request_sec` (`--max-request-time`, 900 s por omissão) é o teto
absoluto de cada pedido, streams incluídos, para que nenhum fique pendurado
para sempre. Uma sonda de janela de contexto que ainda assim esgota o tempo é
reportada como inconclusiva, não como truncamento.
