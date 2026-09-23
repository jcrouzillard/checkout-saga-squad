# ADR-005: Idempotência ponta a ponta, retries com o mesmo messageId e timeouts persistidos

**Status**: Aceito (2026-09-23, Arquiteto)

## Contexto
Outbox e Kafka garantem entrega *at-least-once*; timeouts são ambíguos (o participante pode ter executado).
A seção 6 exige idempotência, retries, timeouts e recuperação.

## Decisão
1. **HTTP**: `Idempotency-Key` obrigatório no `POST /orders` (mesmo corpo → 200 com a resposta original; corpo diferente → 409).
2. **Mensagens**: `processed_messages(message_id, consumer)` gravada na mesma transação do efeito.
3. **Retries de comando** reutilizam o **mesmo `messageId`**; o participante detecta a duplicata e **re-publica a
   resposta** a partir do estado persistido (não reexecuta).
4. **Idempotência de negócio**: `UNIQUE(order_id)` em reserva, pagamento e envio.
5. **Compensações idempotentes e tolerantes a ordem**: compensar o inexistente é *no-op* registrado (tombstone);
   ação posterior ao tombstone responde `ALREADY_COMPENSATED`.
6. **Timeouts**: `deadline_at` e `next_retry_at` persistidos em `saga_instance`, varridos por scheduler. Ações:
   `SAGA_STEP_MAX_RETRIES` (default 2) com backoff exponencial; esgotado → compensação. Compensações e
   `order.confirm/cancel`: retry infinito com backoff limitado + alerta `COMPENSATION_STUCK`.
7. O orquestrador aceita resposta só se `causationId == last_command_id`; respostas tardias são registradas e ignoradas.

## Consequências
- (+) Duplicatas, reentregas após reinício e retries são inofensivos; timeouts não geram efeito duplo.
- (+) Tudo sobrevive a reinício (nada em memória).
- (−) Tabelas `processed_messages`/`outbox` crescem → limpeza por TTL em produção.
- (−) Participantes precisam guardar estado suficiente para re-publicar a resposta.

## Alternativas consideradas
- **Novo `messageId` por retry**: exigiria dedupe só por chave de negócio e dificultaria correlacionar tentativas.
- **Retry dentro do consumidor (Spring `DefaultErrorHandler`)**: útil para erros técnicos locais (usado antes da DLT),
  mas não cobre "resposta que nunca chega".
- **Timeouts em memória (`ScheduledExecutor`)**: perdidos no reinício do coordenador — viola a seção 7.
