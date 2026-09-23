# Matriz de rastreabilidade — requisito → mecanismo → teste

> Fonte dos requisitos: `docs/desafio.md` §3 (funcionais), §6 (não funcionais), §7 (cenários de
> falha), demanda D6 (`c6f83b5bb5c7`, testes de integração e timeout em toda etapa). Fonte dos
> mecanismos: ADRs e contratos (`docs/adr/`, `docs/contracts/`, `docs/architecture/saga.md`,
> `docs/architecture/testes.md`, ADR-010). Fonte dos testes: `tests/e2e/run.sh` (12 cenários e2e) e
> `services/order-service/src/test/java/com/checkout/order/it/*IT.java` (integração, Testcontainers).
>
> **Regenerada a partir do `tests/e2e/last-report.json` FINAL** (`executedAt`: 2026-09-23T20:48:07Z,
> `gitCommit`: `e2d66c5` = `HEAD`, imagens reconstruídas com `docker compose up -d --build`, `total`: 12, `passed`: 12, `failed`: 0, `skipped`: 0). Legenda: ✅ passou ·
> ⚠️ parcial · ❌ falhou.

## 3. Requisitos funcionais obrigatórios

| Requisito | Mecanismo (doc/ADR) | Teste que prova | Status |
|---|---|---|---|
| Criar pedido | `POST /orders` (`api.md` §1); outbox `order.created` (`saga.md` §3.3) | e2e: os 12 cenários criam pedido (`tests/e2e/last-report.json`); IT: `OrderApiIT` (202+Location, replay 200, 409, 400) | ✅ passou |
| Reservar estoque | `inventory.reserve`/`inventory.reserved`, tudo-ou-nada | e2e: `happy_path_physical` (`orderId=5f561c47…`); `timeout_inventory` (reserva real, depois liberada) | ✅ passou |
| Autorizar pagamento | `payment.authorize`/`payment.authorized` | e2e: `happy_path_physical`, `happy_path_digital`, `coordinator_restart` (`orderId=1716fbbc…`), `timeout_once` (`orderId=8b38fc16…`) | ✅ passou |
| Gerar envio quando aplicável | `shipment.create`/`shipment.created`, só `deliveryType=PHYSICAL` | e2e: `happy_path_physical` (`CREATED`); `happy_path_digital` (`404`); `timeout_once` (`CREATED` na 2ª tentativa) | ✅ passou |
| Confirmar pedido | `order.confirm`→`order.confirmed`, `CONFIRMED` | e2e: `happy_path_physical`, `happy_path_digital`, `timeout_once`, `coordinator_restart`, `idempotency`; IT: `IdempotentConsumerIT` (duplicata → 1 efeito) | ✅ passou |
| Cancelar pedido | `order.cancel`→`order.canceled` com `reason`/`failedStep` | e2e: `payment_failure` (`orderId=4480fb97…`), `shipping_failure` (`orderId=5eb42449…`), `timeout_step` (`orderId=f599f93a…`), `timeout_inventory` (`orderId=448e2a63…`), `timeout_shipping` (`orderId=327b12d6…`) | ✅ passou |
| Consultar status do pedido | `GET /orders/{orderId}` com `history` | e2e: os 12 cenários; IT: `OrderApiIT` (`PENDING`/`CREATED`, 404 para id inexistente) | ✅ passou |
| Listar pedidos de um cliente (D1) | `GET /orders?customerId=&limit=` | e2e: `customer_orders` (`orderId=6c40335d…`, cliente `qa-e2e-cust-9f080094…`, 3 pedidos, ordem correta, `limit=2`, cliente inexistente `[]`, sem `customerId` `400`) | ✅ passou |

## 4. APIs por domínio

| Operação | Mecanismo | Teste que prova | Status |
|---|---|---|---|
| Estoque: `reserve`/`release` | comando Kafka, idempotente (`noop`) | e2e: `payment_failure`/`shipping_failure`/`timeout_step`/`timeout_inventory`/`timeout_shipping` — reserva seguida de release, `noop=false`, estoque restaurado a 948 na mesma execução (`last-report.json`) | ✅ passou |
| Pagamento: `authorize`/`refund` | comando Kafka, idempotente | e2e: `coordinator_restart`, `timeout_once` (autoriza), `shipping_failure`/`timeout_step`/`timeout_shipping` (`REFUNDED`) | ✅ passou |
| Envio: `create`/`cancel` | comando Kafka | e2e: `timeout_shipping` (cria de fato, depois `shipment.cancel`→`CANCELED`, `noop=false`, compensação de 3 passos na ordem `SHIPPING`→`PAYMENT`→`INVENTORY`) | ✅ passou |
| Outbox → Kafka (produção real) | Relay transacional (ADR-002) | IT: `OutboxRelayIT` — `order.created` chega em `order.events` com envelope completo (`messageId`, `sagaId`, `correlationId`, `causationId=null`), `outbox.published_at` preenchido | ✅ passou |
| Consumidor idempotente | `processed_messages`, dedupe por `messageId` | IT: `IdempotentConsumerIT` — `order.confirm` publicado 2× com o MESMO `messageId`: 1 linha em `processed_messages`, 1 `ORDER/CONFIRMED` no histórico, 1 `order.confirmed` no outbox causado por essa mensagem | ✅ passou |
| Mensagem venenosa → DLT | `DefaultErrorHandler` + `DeadLetterPublishingRecoverer` (`common`) | IT: `DeadLetterIT` — mensagem não-JSON em `order.commands` chega em `order.commands.DLT` (`Topics.DLT_SUFFIX`). Defeito `162e55358052` (recoverer publicava em `order.commands-dlt`) **corrigido em `e2d66c5`** (`destinationResolver` explícito em `KafkaCommonConfiguration`) | ✅ passou |

## 6. Requisitos não funcionais obrigatórios

| Requisito | Mecanismo (doc/ADR) | Teste que prova | Status |
|---|---|---|---|
| Idempotência | `Idempotency-Key` + `processed_messages` (ADR-005) | e2e: `idempotency` (`orderId=3b064d8b…`, `Idempotent-Replayed=true`, estoque 946→945); IT: `OrderApiIT` (replay 200/409), `IdempotentConsumerIT` | ✅ passou |
| Retries | Scheduler, `SAGA_STEP_MAX_RETRIES` (2), backoff exponencial | e2e: `timeout_step` (20s), `timeout_inventory` (20s), `timeout_shipping` (20s), `timeout_once` (retry com sucesso, 9s) | ✅ passou |
| Timeouts em qualquer etapa | `deadline_at`/`SAGA_STEP_TIMEOUT_MS` | e2e: pagamento (`timeout_step`), estoque (`timeout_inventory`), envio (`timeout_shipping`) — as 3 etapas participantes | ✅ passou |
| Recuperação após falhas | Estado em Postgres, offset após commit, scheduler retoma | e2e: `coordinator_restart` (`orderId=1716fbbc…`, 11s) | ✅ passou |
| Rastreabilidade ponta a ponta | `traceparent` W3C propagado, spans nos 5 serviços | e2e: `trace_end_to_end` (`orderId=cd1a75fc…`, trace `bf55f6fbbff8ada974c1a29d52d86ca7`, 5 serviços confirmados via API do Jaeger) | ✅ passou |
| Publicação de eventos (outbox real) | Outbox transacional + relay (ADR-002) | e2e: os 12 cenários; IT: `OutboxRelayIT` (mecanismo isolado, sem mocks) | ✅ passou |
| Mensagem venenosa não trava a fila | DLT + retomada do consumo | IT: `DeadLetterIT` — após a mensagem venenosa ir para `order.commands.DLT`, um pedido válido enviado em seguida é processado normalmente (consumidor não travou) | ✅ passou |

## 7. Cenários de falha obrigatórios

| Cenário | Compensações esperadas | Teste que prova | Status |
|---|---|---|---|
| Falha no pagamento | `inventory.release` → `order.cancel(PAYMENT_DECLINED)` | e2e: `payment_failure` (`orderId=4480fb97…`, 1s) | ✅ passou |
| Falha no envio | `payment.refund` → `inventory.release` → `order.cancel(SHIPMENT_FAILED)` | e2e: `shipping_failure` (`orderId=5eb42449…`, 3s) | ✅ passou |
| Timeout no pagamento | `payment.refund`(real) → `inventory.release` → `order.cancel(STEP_TIMEOUT)` | e2e: `timeout_step` (`orderId=f599f93a…`, 20s) | ✅ passou |
| Timeout no estoque | `inventory.release` → `order.cancel(STEP_TIMEOUT)`; sem pagamento/envio | e2e: `timeout_inventory` (`orderId=448e2a63…`, 20s) | ✅ passou |
| Timeout no envio | `shipment.cancel` → `payment.refund` → `inventory.release` → `order.cancel(STEP_TIMEOUT)`, nesta ordem | e2e: `timeout_shipping` (`orderId=327b12d6…`, 20s, ordem verificada por índice) | ✅ passou |
| Timeout com retry bem-sucedido | Nenhuma — recuperação sem compensar | e2e: `timeout_once` (`orderId=8b38fc16…`, 9s) | ✅ passou |
| Reinício do coordenador | Nenhuma extra | e2e: `coordinator_restart` (`orderId=1716fbbc…`, 11s) | ✅ passou |
| Mensagem venenosa (poison message) | Vai para o DLT, consumidor não trava | IT: `DeadLetterIT` (defeito `162e55358052` corrigido em `e2d66c5`) | ✅ passou |

## 8. Testes de integração (D6, ADR-010, `services/order-service/src/test/java/com/checkout/order/it/`)

`mvn -B -pl services/order-service -am verify` — **9/9 `*IT` verdes** no `HEAD` `e2d66c5` (reproduzido pelo
Auditor no parecer `docs/squad/gates/G3-D6-2.json`). Correção de 2º ciclo aplicada: `AbstractIntegrationIT` passou a usar o padrão "singleton container"
(contêineres `static`, iniciados uma vez num bloco `static`, sem `@Testcontainers`/`@Container`, que
paravam os contêineres ao fim de cada classe enquanto o contexto Spring cacheado seguia com as portas
antigas — causa raiz apontada pelo Auditor no G2-D6). Testcontainers atualizado pelo Backend para 1.21.4
(compatível com o Docker Engine 29 da máquina).

| Classe | Casos | Status |
|---|---|---|
| `OrderApiIT` | 6 casos: 202+Location, replay 200, 409 (corpo diferente), 400 (sem header), `GET` 200 `PENDING`/`CREATED`, `GET` 404 | ✅ passou |
| `OutboxRelayIT` | `order.created` em `order.events` com envelope completo; `outbox.published_at` preenchido | ✅ passou |
| `IdempotentConsumerIT` | `order.confirm` 2× mesmo `messageId` → 1 efeito só (processed_messages, histórico, outbox) | ✅ passou |
| `DeadLetterIT` | Mensagem não-JSON → `order.commands.DLT`; consumidor segue processando | ✅ passou — o teste revelou o defeito de produção `162e55358052` (recoverer publicava em `order.commands-dlt`, tópico inexistente; mensagem perdida), **corrigido em `e2d66c5`** com `destinationResolver` explícito (`<tópico>` + `Topics.DLT_SUFFIX`). |

## Histórico de execução

**1ª/2ª execução (D2/D3-fase)**: 6/7 → defeito de coordinator_restart → corrigido → 7/7 (ver handoffs
04/07). **D6, 1ª rodada de e2e**: 8→12 cenários, 12/12 (`de2fd92`, 18:02:42Z). **D6, `*IT` ciclo 1**:
G2/G3 devolvidos pelo Auditor — Testcontainers 1.20.6 incompatível com Docker 29 (infra) **e** defeito de
desenho no `AbstractIntegrationIT` (`@Container`/`@Testcontainers` parando os contêineres entre classes
com o contexto Spring cacheado apontando pra portas mortas — 8 de 9 falhas eram por isso, não só infra).

**D6, `*IT` ciclo 2 (2026-09-23, commit `207adef`)**: Backend subiu o Testcontainers para 1.21.4; QA
trocou `AbstractIntegrationIT` para o padrão singleton container (`static { POSTGRES.start(); KAFKA.start(); }`,
sem `@Container`/`@Testcontainers`). Resultado: **8/9 IT verdes** — `OrderApiIT` (6 casos), `OutboxRelayIT`,
`IdempotentConsumerIT` passam limpo; `DeadLetterIT` revela um **defeito real de produção**: o tópico de
DLT que o `DeadLetterPublishingRecoverer` efetivamente usa (`order.commands-dlt`) diverge do tópico que
`Topics.DLT_SUFFIX`/`KafkaAdmin` pré-criam (`order.commands.DLT`) — mensagens venenosas são hoje
descartadas silenciosamente também em produção, não só no teste. e2e continua 12/12 sobre o `HEAD`
reconstruído (`207adef`, 18:30:38Z), incluindo os 4 cenários novos da D6.

**Aprendizado**: (1) contêineres `static` + `@Testcontainers`/`@Container` só compartilham dentro de UMA
classe de teste — para múltiplas classes `*IT` reaproveitarem o mesmo contexto Spring, é preciso o padrão
"singleton container" (sem essas anotações, `.start()` manual, sem `.stop()`); (2) escrever o teste do
caminho de erro (DLT) obrigou a olhar o comportamento REAL do `DeadLetterPublishingRecoverer` em vez de
confiar no nome de tópico assumido no código de produção — encontrou um defeito que passaria despercebido
sem esse teste.

**D6, fechamento (2026-09-23, commit `e2d66c5`)**: Backend corrigiu o destino do DLT (defeito
`162e55358052`) em `common`. `*IT` **9/9** (reproduzido pelo Auditor, G2/G3-D6-2 aprovados). Imagens
reconstruídas no `HEAD` (`docker compose up -d --build`) e e2e **12/12** (`last-report.json`,
`gitCommit` `e2d66c5`, 20:48:07Z).

## Observações / lacunas conhecidas

1. **DLT com nome de tópico divergente**: defeito `162e55358052` **corrigido em `e2d66c5`**; `DeadLetterIT`
   verde. O e2e não injeta mensagem venenosa — a garantia é provada no nível de IT.
2. **Testes unitários**: 66 testes em `services/*/src/test/**`, todos verdes (surefire); `common` continua
   sem `src/test/**` próprio.
3. **Rastreabilidade no Jaeger**: automatizada desde a D6 (`trace_end_to_end`); link manual por cenário
   continua disponível para a demo.
4. **409 em `Idempotency-Key` repetida com corpo diferente**: coberto tanto no e2e (bônus, não obrigatório)
   quanto agora em `OrderApiIT` (obrigatório, IT).

## Demandas da fábrica (Squad Control)

| Requisito | Implementação | Evidência | Status |
|---|---|---|---|
| Emoji por papel nos cards dos agentes (demanda D3, Squad Control) | `squad-control/index.html` (`docs/contracts/ui-squad-control-agentes.md`) | `tests/ui/checklist-squad-control-d3.md` + capturas 1440/390 | ✅ G3 88% |
| Tipo da demanda + validação agêntica (demanda D4, Squad Control) | `tools/squad/{server,triage,pending}.py`, `squad-control/index.html` (`docs/contracts/ui-demandas-v2.md`, ADR-008) | `tests/ui/checklist-demandas-v2.md` (API, 4 triagens reais 10–21 s, capturas) | ✅ G3 80% |
| Backlog de demandas (demanda D5, Squad Control) | `tools/squad/{server,pending,github_sync}.py`, `squad-control/index.html` (`docs/contracts/ui-backlog-de-demandas.md`, ADR-009) | `tests/ui/checklist-backlog-d5.md` (API, fila por prioridade, capturas) | ✅ G2 100% (2º ciclo) · G3 94% |
| Cancelar demanda antes do início (demanda D7, Squad Control) | `tools/squad/{server,triage,github_sync}.py`, `squad-control/index.html` (`docs/contracts/ui-cancelar-demanda.md`) | `tests/ui/checklist-cancelar-d7.md` (API, triagem, capturas) | ✅ G2 88% (2º ciclo) · G3 93% |
