# ADR-002: Outbox transacional com relay por polling

**Status**: Aceito (2026-09-23, Arquiteto)

## Contexto
Gravar no banco e publicar no Kafka são duas operações sem transação comum ("dual write"). Uma queda entre elas
perde o evento ou publica um fato que não foi persistido — inaceitável para "publicação de eventos" e
"recuperação após falhas" (seção 6) e para o reinício do coordenador (seção 7).

## Decisão
- Todo produtor grava a mensagem (envelope completo + `trace_parent`) na tabela `outbox` **na mesma transação** do
  efeito de negócio. Nenhum handler chama `KafkaTemplate.send` diretamente.
- Um **relay** por serviço (`@Scheduled`, `OUTBOX_POLL_INTERVAL_MS`) lê linhas não publicadas em ordem de `id`
  (`FOR UPDATE SKIP LOCKED`), publica de forma síncrona com chave `orderId` e header `traceparent` da linha, e marca `published_at`.
- `outbox.id` é sequencial e independente de `message_id` (retries de comando reutilizam o `message_id`).
- Implementação única na lib `common`.

## Consequências
- (+) Atomicidade estado ↔ mensagem; recuperação automática após queda (linhas pendentes são publicadas no startup).
- (+) Ordem por pedido preservada.
- (−) Entrega **at-least-once** → exige consumidores idempotentes (ADR-005).
- (−) Latência de até `OUTBOX_POLL_INTERVAL_MS`; tabela cresce → limpeza periódica de linhas publicadas (produção).
- (−) Contexto de trace precisa ser gravado e restaurado manualmente pelo relay.

## Alternativas consideradas
- **Kafka transactions** (`chainedTransactionManager`): não cobre a transação do Postgres de forma atômica real.
- **CDC com Debezium**: melhor em produção (sem polling), mas adiciona Kafka Connect ao ambiente local — registrado como evolução (README §6).
- **Publicar após commit (`@TransactionalEventListener`)**: perde mensagens se o processo cair entre o commit e o envio.
