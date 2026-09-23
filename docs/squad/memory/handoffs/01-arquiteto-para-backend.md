# Handoff 01 — Arquiteto → Backend (cc: DevOps, Observabilidade)

## Decidido
- Saga **orquestrada** (`saga-orchestrator`), comandos + eventos de resposta via Kafka (ADR-001).
- Tópicos `<ctx>.commands` / `<ctx>.events` (order, inventory, payment, shipping) + `saga.events`; 3 partições; chave `orderId`; `type` no envelope distingue mensagens (ADR-004).
- `order.confirmed`/`order.canceled` são publicados pelo **order-service** ao processar `order.confirm`/`order.cancel`; a saga só fica terminal ao consumi-los.
- Outbox transacional + relay por polling em todos os serviços (ADR-002); `processed_messages` + retry com **mesmo messageId** + tombstone de compensação (ADR-005); database por serviço (ADR-003).
- Timeouts: `deadline_at`/`next_retry_at` persistidos + scheduler; ações com 2 retries, compensações com retry infinito.
- Injeção de falha: objeto `simulate` no `POST /orders`, propagado até os participantes.

## Arquivos (fonte da verdade)
- `docs/contracts/events.md` — tópicos, envelope, todos os payloads, regras de idempotência (§5).
- `docs/contracts/api.md` — endpoints, erros, seeds de estoque, variáveis de ambiente com defaults.
- `docs/architecture/saga.md` — máquina de estados, tabela de passos, tabelas SQL sugeridas, scheduler, sequências, cenários.
- `docs/architecture/README.md` — visões + RNF → mecanismo + seção 12.
- `docs/adr/001..005`.

## Pontos de atenção para o Backend
1. `outbox.id` sequencial; `message_id` **não** é único (retry grava nova linha com o mesmo `message_id`).
2. Participante que recebe comando duplicado **re-publica a resposta** a partir do estado persistido (não reexecuta). Sem isso, retry após resposta perdida nunca conclui.
3. Orquestrador aceita resposta só se `causationId == last_command_id`; o resto vira `IGNORED_LATE_REPLY`.
4. Gravar `traceparent` na linha do outbox e em `saga_instance.trace_parent`; relay e scheduler restauram o contexto (senão o trace quebra).
5. Ack do offset **após** o commit do banco (`enable.auto.commit=false`).
6. `simulate` só afeta ações (`reserve/authorize/create`), nunca compensações nem `order.*`. `TIMEOUT` executa a ação e não responde; `TIMEOUT_ONCE` conta tentativas.
7. Payload **não** repete `orderId`/`sagaId` — use o envelope. Nomes de tópico/`type`/campos devem ser idênticos (gate G2 bloqueante).
8. Env vars de `api.md` §5 via `${VAR:default}` no `application.yml`.

## Para DevOps / Observabilidade
- DevOps: 5 databases (`saga`, `orders`, `inventory`, `payments`, `shipping`); tópicos são criados pelos serviços (`NewTopic`), mas pode-se pré-criar com 3 partições.
- Observabilidade: nomes das métricas em `docs/observability.md`; incluir alerta para log `COMPENSATION_STUCK` e contagem de `saga_timeouts_total`.

## Riscos abertos
- Cenário TIMEOUT leva ≈ 20 s com defaults (5 s × 3 tentativas + backoff); QA deve usar poll com timeout ≥ 45 s.
- `SLOW` implementado com sleep no consumidor bloqueia a partição — aceitável na demo; manter `SIMULATE_SLOW_MS` < `SAGA_STEP_TIMEOUT_MS`.
- Limpeza de `outbox`/`processed_messages` fora do escopo (documentado como evolução).
