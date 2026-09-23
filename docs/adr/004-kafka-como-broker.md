# ADR-004: Apache Kafka como broker, tópicos de comandos e de eventos por contexto

**Status**: Aceito (2026-09-23, Arquiteto) — refina ADR-000.

## Contexto
A seção 5 pede demonstração clara de publicação e consumo de eventos; a seção 7 exige continuidade após falhas.
Precisamos de ordem por pedido, retenção (mensagens sobrevivem a consumidores fora do ar) e replay.

## Decisão
- Apache Kafka (KRaft, 1 broker no compose).
- Tópicos: `order.events`, `order.commands`, `inventory.commands`, `inventory.events`, `payment.commands`,
  `payment.events`, `shipping.commands`, `shipping.events`, `saga.events` — **3 partições**, RF 1 local; DLT `<tópico>.DLT`.
- Chave = `orderId` em todas as mensagens; o campo `type` do envelope distingue as mensagens num tópico.
- Consumer group = nome do serviço; `enable.auto.commit=false`, ack após commit do banco; producer idempotente, `acks=all`.

## Consequências
- (+) Ordem por pedido (comando e compensação do mesmo pedido na mesma partição).
- (+) Mensagens retidas enquanto um serviço está fora → retomada natural após reinício.
- (+) Poucos tópicos, ACL simples (só o orquestrador escreve em `*.commands`).
- (−) Consumidor precisa ignorar tipos que não conhece no tópico.
- (−) 1 broker sem replicação no ambiente local (produção: RF=3 — README §6).

## Alternativas consideradas
- **Um tópico por tipo de mensagem** (`order.created`, ...): nomes iguais aos eventos, mas ~20 tópicos e ordem entre
  comando e compensação deixa de ser garantida (tópicos diferentes).
- **RabbitMQ**: roteamento flexível, porém sem replay/retenção nativos e ordem por chave menos direta.
- **Simulação em memória**: permitida pelo desafio, mas não demonstra falhas reais de processo.
