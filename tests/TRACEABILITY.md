# Matriz de rastreabilidade — requisito → mecanismo → teste

> Fonte dos requisitos: `docs/desafio.md` §3 (funcionais), §6 (não funcionais), §7 (cenários de
> falha). Fonte dos mecanismos: ADRs e contratos (`docs/adr/`, `docs/contracts/`,
> `docs/architecture/saga.md`). Fonte dos testes: `tests/e2e/run.sh` (cenários e2e) e
> `services/*/src/test/**` (testes unitários do Backend — **a confirmar**, código ainda em
> construção em paralelo a esta suíte; ver F2/handoffs).
>
> **Status = "pendente execução"** em toda a matriz: os cenários foram escritos a partir dos
> contratos (test-first), mas só rodam de fato contra os serviços reais depois do gate G2. Ao
> executar `bash tests/e2e/run.sh`, atualizar esta coluna para `passou`/`falhou` com base em
> `tests/e2e/last-report.json`.

## 3. Requisitos funcionais obrigatórios

| Requisito | Mecanismo (doc/ADR) | Teste que prova | Status |
|---|---|---|---|
| Criar pedido | `POST /orders` (`docs/contracts/api.md` §1); outbox `order.created` (`saga.md` §3.3) | e2e: `happy_path_physical`, `happy_path_digital`, `payment_failure`, `shipping_failure`, `timeout_step`, `coordinator_restart`, `idempotency` (todos criam pedido) | pendente execução |
| Reservar estoque | `inventory.reserve`/`inventory.reserved`, tudo-ou-nada (`events.md` §4.3); tabela `stock`/`reservations` (`saga.md` §3.1) | e2e: `happy_path_physical` (reserva com sucesso, `history` `INVENTORY/SUCCEEDED`); `GET /inventory/reservations/{id}` verificado em `payment_failure`/`shipping_failure`/`timeout_step` (reserva depois liberada) | pendente execução |
| Autorizar pagamento | `payment.authorize`/`payment.authorized` (`events.md` §4.4) | e2e: `happy_path_physical`/`happy_path_digital` (`history` `PAYMENT/SUCCEEDED`); `GET /payments/{id}` `AUTHORIZED` em `coordinator_restart` | pendente execução |
| Gerar envio quando aplicável | `shipment.create`/`shipment.created`, só `deliveryType=PHYSICAL` (`events.md` §4.5; `api.md` regra de validação) | e2e: `happy_path_physical` (`GET /shipments/{id}` = `CREATED`); `happy_path_digital` (ausência: `GET /shipments/{id}` = `404`) | pendente execução |
| Confirmar pedido | `order.confirm`→`order.confirmed`, estado terminal `COMPLETED`/`CONFIRMED` (`saga.md` §1-2) | e2e: `happy_path_physical`, `happy_path_digital`, `timeout_step` (caso `TIMEOUT_ONCE`, ver `scenarios.md` §5 variante), `coordinator_restart`, `idempotency` | pendente execução |
| Cancelar pedido | `order.cancel`→`order.canceled` com `reason`/`failedStep` (`events.md` §4.1) | e2e: `payment_failure`, `shipping_failure`, `timeout_step` (verificam `status=CANCELED` + `cancellationReason`) | pendente execução |
| Consultar status do pedido | `GET /orders/{orderId}` com `history` (`api.md` §1) | e2e: todos os 7 cenários fazem poll de `GET /orders/{orderId}` via `wait_for_status` | pendente execução |

## 4. APIs por domínio (desafio §4)

| Operação | Mecanismo | Teste que prova | Status |
|---|---|---|---|
| Estoque: `reserve` | comando Kafka `inventory.reserve` (não HTTP, ADR-001) | e2e: `happy_path_physical` (sucesso), `payment_failure`/`shipping_failure`/`timeout_step` (reserva seguida de release) | pendente execução |
| Estoque: `release` | comando Kafka `inventory.release`, idempotente com tombstone `noop` (`events.md` §4.3, §5.4) | e2e: `payment_failure`, `shipping_failure`, `timeout_step` — todos checam `GET /inventory/reservations/{id}` = `RELEASED` e estoque restaurado (`wait_for_stock_value`) | pendente execução |
| Pagamento: `authorize` | comando Kafka `payment.authorize` | e2e: `happy_path_physical`, `happy_path_digital`, `coordinator_restart` | pendente execução |
| Pagamento: `refund` | comando Kafka `payment.refund`, idempotente com `noop` | e2e: `shipping_failure`, `timeout_step` — checam `GET /payments/{id}` = `REFUNDED` | pendente execução |
| Envio: solicitar entrega | comando Kafka `shipment.create` (`events.md` §4.5) | e2e: `happy_path_physical` | pendente execução |
| Envio: o que acontece se der erro | `saga.md` §5.2 (erro de negócio → `shipment.failed`/compensação; erro técnico → tratado como timeout) | e2e: `shipping_failure` (erro de negócio) + `timeout_step` (variante `simulate.shipping=TIMEOUT`, mesmo mecanismo do pagamento, não coberto por função dedicada — ver Observações) | pendente execução |

## 6. Requisitos não funcionais obrigatórios

| Requisito | Mecanismo (doc/ADR) | Teste que prova | Status |
|---|---|---|---|
| Idempotência | `Idempotency-Key` + `UNIQUE(idempotency_key)` (`api.md` §1); `processed_messages` + retry com mesmo `messageId` (`events.md` §5, ADR-005) | e2e: `idempotency` (mesmo `orderId`, header `Idempotent-Replayed`, estoque reduz uma vez); indiretamente em `timeout_step`/`coordinator_restart` (retries não duplicam efeito) | pendente execução |
| Retries | Scheduler de timeouts, `SAGA_STEP_MAX_RETRIES` (2), backoff exponencial (`saga.md` §3.2) | e2e: `timeout_step` (`history` mostra `PAYMENT/TIMED_OUT` antes da compensação, evidenciando ao menos uma tentativa de retry) | pendente execução |
| Timeouts | `deadline_at`/`SAGA_STEP_TIMEOUT_MS` (`api.md` §5; `saga.md` §3.2) | e2e: `timeout_step` (`cancellationReason=STEP_TIMEOUT` após esgotar retries) | pendente execução |
| Recuperação após falhas | Estado 100% em Postgres, offset só avança após commit, outbox republica pendências, scheduler retoma deadlines (`saga.md` §3.5) | e2e: `coordinator_restart` (`docker compose kill`/`up -d saga-orchestrator`, saga conclui `CONFIRMED`, sem autorização duplicada) | pendente execução |
| Rastreabilidade ponta a ponta | `traceparent` W3C propagado via outbox → header Kafka → spans (ADR-002; `observability.md` §3); `correlationId` no envelope | Não coberto por asserção automatizada em `run.sh` (checagem seria visual, no Jaeger); script imprime o link do Jaeger por `orderId` em cada cenário para inspeção manual no G3 (`docs/squad/gates.md` — "Trace ponta a ponta visível no Jaeger", peso 2, não bloqueante) | pendente execução |
| Publicação de eventos | outbox transacional + relay (`events.md` §1, ADR-002); 6 eventos obrigatórios do desafio §5 | e2e: todos os cenários dependem da publicação real dos eventos para a saga progredir (`order.created`, `inventory.reserved`, `payment.authorized`, `shipment.created`, `order.confirmed`, `order.canceled`); efeito observado indiretamente via `GET /orders/{id}` e endpoints de participantes | pendente execução |

## 7. Cenários de falha obrigatórios

| Cenário | Mecanismo de continuidade | Compensações esperadas | Teste que prova | Status |
|---|---|---|---|---|
| Falha no pagamento | `payment.failed` é resposta de negócio, sem retry (`saga.md` §5) | `inventory.release` → `order.cancel(PAYMENT_DECLINED)` | e2e: `payment_failure` | pendente execução |
| Falha no envio | `shipment.failed`, sem retry (recusa de negócio) | `payment.refund` → `inventory.release` → `order.cancel(SHIPMENT_FAILED)` | e2e: `shipping_failure` | pendente execução |
| Timeout em qualquer etapa | Deadline persistido + scheduler; retry com mesmo `messageId`; esgotado → compensação (`saga.md` §3.2, §5.1) | Compensa o passo expirado + anteriores; aqui: `payment.refund` → `inventory.release` → `order.cancel(STEP_TIMEOUT)` | e2e: `timeout_step` (via `simulate.payment=TIMEOUT`) | pendente execução |
| Reinício inesperado do coordenador da Saga | Estado em Postgres; offset após commit; outbox republica; scheduler retoma (`saga.md` §3.5, §4.5) | Nenhuma extra — saga continua de onde parou | e2e: `coordinator_restart` (`docker compose kill`/`up -d`, via `simulate.payment=SLOW`) | pendente execução |

## Observações / lacunas conhecidas

1. **Timeout em INVENTORY e SHIPPING**: `timeout_step` cobre apenas `simulate.payment=TIMEOUT` (etapa
   intermediária, exercita compensação de 2 passos). O mecanismo é idêntico para `inventory`/`shipping`
   (`events.md` §3); não há função e2e dedicada para essas variantes — pode ser adicionada com o mesmo
   padrão (`order_payload ... '{"inventory":"TIMEOUT"}'` / `'{"shipping":"TIMEOUT"}'`) se o Jev exigir
   cobertura mais ampla no G3.
2. **`TIMEOUT_ONCE`** (retry bem-sucedido, sem compensação): documentado como variante manual em
   `tests/e2e/scenarios.md` §5, não automatizado como cenário próprio (os 7 cenários da suíte seguem
   exatamente a lista de `.claude/agents/qa.md`).
3. **Rastreabilidade no Jaeger**: verificação é visual/manual (o script apenas imprime o link); não há
   dependência do cliente HTTP do Jaeger no `run.sh` para manter a suíte simples e sem dependências
   extras. Evidência para o G3 deve ser um screenshot/link anexado pelo Jev.
4. **Testes unitários complementares** (máquina de estados, idempotência) mencionados em
   `.claude/agents/qa.md` são de responsabilidade do Backend em `services/*/src/test/**` — ainda não
   existem no repositório nesta rodada (Backend implementando em paralelo, F3). Atualizar esta matriz
   com os caminhos exatos assim que existirem.
5. **409 em `Idempotency-Key` repetida com corpo diferente**: mencionado como verificação "bônus" em
   `scenarios.md` §7, não incluído como assert obrigatório em `scenario_idempotency` (o requisito do
   `.claude/agents/qa.md` cobre apenas "mesmo `Idempotency-Key` duas vezes → um único pedido").
