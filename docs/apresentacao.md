# Roteiro da apresentação (~20 min)

## Antes de começar (5 min antes)
```bash
docker compose up -d --build && docker compose ps     # tudo healthy
make squad                                             # Squad Control em http://localhost:7070
```
Abas abertas: Squad Control · GitHub (Issues/Project) · Jaeger :16686 · Grafana :3000 (ou `GRAFANA_PORT`) · terminal.

## 1. O problema e a decisão central (2 min)
- Checkout com 4 domínios + Saga. Decisão: **Saga orquestrada** (ADR-001), porque o fluxo e as compensações ficam
  explícitos numa máquina de estados testável.
- Mostrar `docs/architecture/README.md`: visão técnica (5 containers, database por serviço, Kafka, OTel).

## 2. A squad agêntica (5 min): o diferencial
1. `CLAUDE.md`: constituição com ownership single-writer, hierarquia de verdade e limites de autonomia.
2. `.claude/agents/*.md`: cada agente tem prompt, entradas, saídas, ferramentas e regras de decisão. **Auditor** é o
   agente extra: avaliador independente, somente leitura.
3. **Squad Control** (http://localhost:7070):
   - Linha do tempo F1 → G1 → F2 → G2 → F3 → G3.
   - Clicar num agente mostra o feed real das ações, lido das transcrições do Claude Code.
   - Recomendação do Auditor com confiança e evidências; botões de intervenção humana gravam no log.
4. **GitHub**: issues por agente, handoffs e pareceres como comentários, kanban por Status. Tudo é projeção do
   `decisions.jsonl`, o memory layer.
5. **Pontos para falar:**
   - Comunicação no padrão *blackboard*: os agentes nunca falam direto entre si. Por isso o modelo independe de
     fornecedor (Copilot Coding Agent ou Devin pegam uma issue e seguem o mesmo protocolo).
   - Conflitos são evitados pelo ownership e pelo contrato antes do código, e detectados pelo Auditor.
   - Paralelismo real: Arquiteto ∥ DevOps ∥ Observabilidade; Backend dividido em core ∥ participantes; QA test-first.

## 3. Demo da Saga (6 min)
Comece pelo **Console de Checkout** (http://localhost:7070/checkout.html): crie um pedido físico sem falha e veja a
Saga andar ao vivo; depois um com "Pagamento recusado" e mostre a compensação e o estoque restaurado. A lista
"Pedidos do cliente" vem do `GET /orders?customerId=`, entregue pela própria squad (demanda D1).
Em seguida, no terminal:
```bash
bash tests/e2e/run.sh happy_path_physical     # CONFIRMED + trace no Jaeger (link impresso)
bash tests/e2e/run.sh payment_failure         # libera estoque → CANCELED
bash tests/e2e/run.sh shipping_failure        # estorno + liberação → CANCELED
bash tests/e2e/run.sh coordinator_restart     # kill -9 no orquestrador no meio da saga → CONFIRMED
```
- Mostrar `GET /orders/{id}` com o histórico de etapas e compensações.
- Jaeger: um único trace atravessando HTTP → outbox → Kafka → 4 serviços (`traceparent` persistido no outbox).
- Grafana "Checkout Saga": sagas por outcome, compensações por passo, timeouts.

## 4. A história da autocorreção (3 min): o melhor momento
- 1ª execução integrada: **6/7**. O reinício do coordenador terminou em CANCELED.
- Diagnóstico: depois de SIGKILL, o Kafka só reatribui as partições após o `session.timeout` (45 s). Nesse intervalo
  os deadlines da Saga (5 s) venceram e ela compensou; as respostas chegaram depois como `IGNORED_LATE_REPLY`.
  **A compensação estava correta; o problema era o timeout cobrado pela indisponibilidade do próprio coordenador.**
- A squad seguiu o protocolo: QA registrou o `defect`, o Backend corrigiu (static membership + carência de deadlines
  no startup) e a revalidação deu **7/7**. Depois o Auditor aprovou o G2. Tudo está no log e nas issues.

## 4b. Uma demanda nova passando pela squad (2 min)
Aba **Demandas** do Squad Control: mostre a D1 registrada ("Listar os pedidos de um cliente") e a trilha completa:
Arquiteto (contrato + ADR-006) → Auditor G1 (89%) → Backend + QA em paralelo → e2e 8/8 → Auditor G2/G3. No GitHub, a
mesma trilha aparece como issues e comentários. Ponto a frisar: **quem executa é a sessão do Orquestrador no Claude
Code**; o painel é o cockpit humano.

## 5. Pergunta da seção 12 e próximos passos (2 min)
`docs/architecture/README.md` §6. A solução já nasce distribuída; para produção faltariam:
- Postgres por serviço em instâncias separadas.
- Kafka com RF=3 e schema registry.
- Service discovery via Kubernetes, com HPA por lag.
- DLQ com reprocessamento, limpeza do outbox e do dedupe.
- Réplicas do orquestrador, cada uma com seu `group.instance.id`.

## Perguntas prováveis
| Pergunta | Resposta curta | Onde |
|---|---|---|
| Por que orquestração e não coreografia? | Fluxo e compensações num lugar só; menos acoplamento temporal escondido | ADR-001 |
| E se a compensação falhar? | Retry infinito com backoff + alerta `COMPENSATION_STUCK`; nunca desiste | saga.md §5.3 |
| Timeout ambíguo (pagou tarde)? | Refund idempotente; refund sem autorização = no-op registrado (tombstone) | saga.md §5.1 |
| Exactly-once? | At-least-once + idempotência (outbox + `processed_messages` + mesmo `messageId`) | ADR-002, ADR-005 |
| Como o humano controla a squad? | Gates do Auditor; obrigatório quando confiança < 70%, risco alto ou 3º ciclo | docs/squad/gates.md |
