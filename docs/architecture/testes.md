# Estratégia de testes (D6, `c6f83b5bb5c7`, ADR-010)

> Contratos testados: [`events.md`](../contracts/events.md), [`api.md`](../contracts/api.md), [`saga.md`](saga.md).
> **Nenhum contrato de evento ou API muda nesta demanda** (critério 7): os testes verificam o contrato existente.

## 1. Camadas

| Camada | O que prova | Ferramenta | Onde mora | Como roda |
|--------|-------------|------------|-----------|-----------|
| **Unitário** | Regras puras: máquina de estados da Saga, políticas de resposta/simulate, alocação de estoque, handlers com mocks | JUnit 5 + Mockito | `services/<svc>/src/test/java/com/checkout/<ctx>/**/*Test.java` (existente) | `mvn test` (surefire), sem Docker |
| **Integração** | O serviço real (Spring context completo, Flyway, JDBC, Kafka) contra **Postgres e Kafka reais** | Testcontainers + `@ServiceConnection` + Awaitility | `services/order-service/src/test/java/com/checkout/order/it/*IT.java` | `mvn verify` (failsafe), exige Docker |
| **E2E** | O sistema inteiro em compose: Saga, compensações, falhas, reinício, rastreabilidade | `tests/e2e/run.sh` (curl + jq/python3) | `tests/e2e/` | `docker compose up -d --build && bash tests/e2e/run.sh` |

Separação unitário × integração por **sufixo de classe** (`*Test` → surefire na fase `test`; `*IT` → failsafe nas
fases `integration-test`/`verify`), não por `@Tag` (ADR-010). `mvn verify -DskipITs` pula só a integração.

## 2. Testes de integração (critério 1)

**Módulo escolhido: `order-service`** — é o único que exercita, num só contexto, HTTP com `Idempotency-Key`,
outbox + relay (publica `order.created`), consumidor idempotente (`order.commands`) e o `DefaultErrorHandler` com DLT
da lib `common`. Assim os mecanismos de `common` são testados como são usados em produção, sem app de teste artificial.

Infra de teste (classe base `AbstractIntegrationIT` no mesmo pacote):
- `@SpringBootTest(webEnvironment = RANDOM_PORT)` + `@Testcontainers(disabledWithoutDocker = false)` — sem Docker o
  build **falha** na fase `verify` (evidência honesta; `-DskipITs` é a saída explícita).
- `@Container @ServiceConnection static PostgreSQLContainer<?> pg = new PostgreSQLContainer<>("postgres:16-alpine")`
  (mesma major do compose); Flyway cria o schema.
- `@Container @ServiceConnection static KafkaContainer kafka = new KafkaContainer("apache/kafka-native:3.8.0")`
  (`org.testcontainers.kafka.KafkaContainer`). Tópicos criados pelos `NewTopic` do próprio serviço.
- Contêineres `static` compartilhados pela classe base (sobem uma vez por JVM); cada teste usa `orderId`/chaves novas
  (UUID) — sem limpeza de banco entre testes.
- Consumidor Kafka de teste (`KafkaConsumer<String,String>` puro, `auto.offset.reset=earliest`, group aleatório)
  para ler `order.events` e `order.commands.DLT`; produtor de teste para injetar comandos.
- Esperas **somente** com Awaitility (`await().atMost(Duration.ofSeconds(30))`), nunca `Thread.sleep`.
- Relay **real** (não mockado); `OUTBOX_POLL_INTERVAL_MS` default (200 ms) basta.
- O agente OTel não é usado nos ITs.

| Classe | Casos (todos obrigatórios) |
|--------|----------------------------|
| `OrderApiIT` | `POST /orders` → 202 + `Location`; mesmo `Idempotency-Key` + mesmo corpo → 200 + `Idempotent-Replayed: true` + mesmo `orderId` e **uma** linha em `orders`; mesma key + corpo diferente → 409 problem+json; sem header → 400; `GET /orders/{id}` → 200 com `status=PENDING` e `history[0].status=CREATED`; id inexistente → 404. |
| `OutboxRelayIT` | Após `POST /orders`, `order.created` chega em `order.events` com chave = `orderId`, envelope completo (`messageId`, `sagaId`, `correlationId`, `causationId=null`) e a linha do outbox fica com `published_at` preenchido. |
| `IdempotentConsumerIT` | Publicar `order.confirm` **duas vezes com o mesmo `messageId`** → pedido `CONFIRMED`, **uma** linha em `processed_messages` para esse `messageId`, **um** registro `CONFIRMED` no histórico e **um** `order.confirmed` no outbox para essa causa. |
| `DeadLetterIT` | Publicar valor não-JSON (`"isto não é json"`) com chave qualquer em `order.commands` → a mensagem aparece em `order.commands.DLT` (≤ 30 s) e o consumidor continua processando: um `order.confirm` válido enviado depois é aplicado. |

## 3. E2E novos (critérios 2 e 3)

Adicionados a `tests/e2e/run.sh` (mesmo estilo: poll de 1 s com timeout, nunca sleep longo), registrados em
`tests/e2e/scenarios.md` e em `last-report.json`. O cenário existente `timeout_step` (pagamento) permanece.

| Cenário | Pedido | Esperado (tudo verificado por API) | Timeout do poll |
|---------|--------|------------------------------------|-----------------|
| `timeout_inventory` | `PHYSICAL`, `simulate.inventory=TIMEOUT` | Ver §4.1 | 60 s |
| `timeout_shipping` | `PHYSICAL`, `simulate.shipping=TIMEOUT` | Ver §4.2 | 60 s |
| `timeout_once` | `PHYSICAL`, `simulate.payment=TIMEOUT_ONCE` | `CONFIRMED`; histórico com `PAYMENT` `TIMED_OUT` (tentativa 1) seguido de `PAYMENT` `SUCCEEDED` com `attempt=2`; **uma** autorização (`GET /payments/{id}` `AUTHORIZED`, `noop=false`); shipment `CREATED` | 40 s |
| `trace_end_to_end` | caminho feliz `PHYSICAL` | Ver §5 | 30 s após `CONFIRMED` |

## 4. Comportamento contratado para TIMEOUT em estoque e envio (confirmação — sem mudança)

Fonte: `events.md` §3 (tabela `simulate`), `saga.md` §1–§2 e §5.1. Com defaults (`SAGA_STEP_TIMEOUT_MS=5000`,
`SAGA_STEP_MAX_RETRIES=2`, backoff 1 s ×2) o desfecho ocorre em ≈ 18–22 s.

### 4.1 `simulate.inventory=TIMEOUT`
- inventory-service **reserva de fato** e nunca responde (nem aos retries com o mesmo `messageId`).
- Orquestrador: 3 tentativas → `RELEASING_INVENTORY` (`failure_reason=STEP_TIMEOUT`) → `inventory.release` →
  `inventory.released` (`noop=false`) → `order.cancel` → `CANCELED`.
- Verificações: pedido `CANCELED`, `cancellationReason=STEP_TIMEOUT`; histórico contém `INVENTORY` `TIMED_OUT` e,
  depois, `INVENTORY` `COMPENSATED`, e `ORDER` `CANCELED`; `GET /inventory/reservations/{id}` → `RELEASED`,
  `noop=false`; estoque do SKU igual ao de antes; **nenhum** pagamento (`GET /payments/{id}` → 404) e nenhum envio (404).

### 4.2 `simulate.shipping=TIMEOUT`
- shipping-service **cria o envio de fato** e nunca responde.
- Orquestrador: 3 tentativas → `CANCELING_SHIPMENT` → `shipment.cancel` → `shipment.canceled` (`noop=false`) →
  `REFUNDING_PAYMENT` → `payment.refunded` (`noop=false`) → `RELEASING_INVENTORY` → `inventory.released` →
  `order.cancel` → `CANCELED`.
- Verificações: pedido `CANCELED`, `STEP_TIMEOUT`; histórico com `SHIPPING` `TIMED_OUT`, depois `SHIPPING`
  `COMPENSATED`, `PAYMENT` `COMPENSATED`, `INVENTORY` `COMPENSATED` **nesta ordem**, e `ORDER` `CANCELED`;
  `GET /shipments/{id}` → `CANCELED`, `noop=false`; `GET /payments/{id}` → `REFUNDED`; reserva `RELEASED`; estoque restaurado.

Se o histórico não trouxer os `COMPENSATED` (os `saga.step-changed` definidos em `events.md` §4.6), é **defeito do
Backend** (registrar `defect`), não ajuste do teste.

## 5. Trace ponta a ponta via Jaeger (critério 3)

1. O e2e gera um trace id W3C (32 hex) e envia `traceparent: 00-<traceId>-<spanId>-01` no `POST /orders`
   (o agente OTel continua o trace recebido; amostragem *parent-based*). Isso torna a busca determinística.
2. Aguarda o pedido `CONFIRMED`; então faz poll (1 s, até 30 s) em `GET ${JAEGER_URL}/api/traces/<traceId>`.
3. PASS se `data` tem **exatamente um** trace com esse id e o conjunto `data[0].processes[*].serviceName` contém
   `order-service`, `saga-orchestrator`, `inventory-service`, `payment-service`, `shipping-service`.
   `detail` do relatório registra o `traceId` e a lista de serviços (evidência para G3).
4. Se o Jaeger estiver inacessível → `FAIL` (não `SKIP`), pois a rastreabilidade é requisito (seção 6).

## 6. Relatório e rastreabilidade (critérios 4 e 5)
- `last-report.json` passa a ser um objeto: `{ "executedAt": "<ISO-8601 UTC>", "gitCommit": "<sha curto>",
  "total": N, "passed": N, "failed": 0, "skipped": 0, "scenarios": [ { "scenario", "status", "durationSeconds",
  "orderId", "detail" } ] }` — mesmos campos por cenário que hoje. (Formato do relatório de teste, não contrato de produto.)
- `tests/TRACEABILITY.md` é **regenerado a partir desse arquivo**: requisito → cenário/IT → `orderId` → status; o
  número de cenários, os `orderId`s e os valores de estoque citados devem bater com o relatório.

## 7. O que muda, por arquivo e dono

| Dono | Arquivo | Mudança |
|------|---------|---------|
| **Backend** (via `change-request` do QA) | `pom.xml` (raiz) | Declarar `maven-failsafe-plugin` em `<build><plugins>` (goals `integration-test` e `verify`; versão gerenciada pelo Spring Boot parent). |
| **Backend** (via `change-request`) | `services/order-service/pom.xml` | Dependências `test`: `org.springframework.boot:spring-boot-testcontainers`, `org.testcontainers:junit-jupiter`, `org.testcontainers:postgresql`, `org.testcontainers:kafka`, `org.awaitility:awaitility` (versões gerenciadas pelo Boot 3.4 — sem `<version>`). |
| **QA** | `services/order-service/src/test/java/com/checkout/order/it/*IT.java` | §2 (4 classes + base). |
| **QA** | `tests/e2e/run.sh`, `tests/e2e/scenarios.md`, `tests/e2e/last-report.json` | §3–§6. |
| **QA** | `tests/TRACEABILITY.md` | Regenerado (§6). |
| **Orquestrador** | `README.md` §4 e §9 | §4: como rodar `mvn verify` (Docker), os 12 cenários e2e e o cenário de trace; §9: remover a limitação "cobertura e2e de timeout". |
| **Arquiteto** | `docs/architecture/testes.md`, ADR-010 | Este documento. |
| — | `docs/contracts/**`, código de produção | **Nenhuma mudança** (critério 7). Defeito encontrado → `defect` ao Backend. |

## 8. Critérios verificáveis para os gates

| Gate | Critério | Evidência |
|------|----------|-----------|
| G2 (B) | `mvn -q verify` verde com Docker; relatório failsafe do order-service com **≥ 4 classes IT, 0 skipped** | `services/order-service/target/failsafe-reports/*.xml` |
| G2 (B) | `mvn -q test` continua verde sem Docker (unitários isolados) | saída do build |
| G2 (B) | `git diff develop -- docs/contracts services/*/src/main` vazio, exceto `pom.xml` aprovados por change-request | `git diff --stat` |
| G2 | Nenhum `Thread.sleep` nos ITs; esperas com Awaitility | `grep -rn "Thread.sleep" services/*/src/test` vazio |
| G3 (B) | `last-report.json` com `executedAt` do dia, `total=12`, `failed=0`, `skipped=0`, incluindo `timeout_inventory`, `timeout_shipping`, `timeout_once`, `trace_end_to_end` | arquivo |
| G3 (B) | `timeout_shipping` com `detail` citando shipment `CANCELED`, payment `REFUNDED`, reserva `RELEASED`, estoque restaurado | arquivo |
| G3 (B) | `trace_end_to_end` com `traceId` e os 5 serviços no `detail` | arquivo + Jaeger UI |
| G3 | `TRACEABILITY.md` coerente com o relatório (contagem, `orderId`s, estoque) | revisão cruzada |
| G3 | README §4/§9 atualizados | diff do README |
