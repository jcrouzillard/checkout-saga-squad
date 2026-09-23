# ADR-001: Saga orquestrada com comandos e eventos via Kafka

**Status**: Aceito (2026-09-23, Arquiteto)

## Contexto
O checkout envolve 4 contextos (Pedido, Estoque, Pagamento, Envio) sem transação distribuída. O desafio exige
Saga, compensações, timeouts em qualquer etapa e resistência ao **reinício inesperado do coordenador** (seções 2, 6, 7).

## Decisão
- Saga **orquestrada** por um serviço dedicado, `saga-orchestrator`, com máquina de estados persistida (`docs/architecture/saga.md`).
- O orquestrador envia **comandos** (`<contexto>.commands`) e reage a **eventos de resposta** (`<contexto>.events`);
  participantes não conhecem uns aos outros.
- O `order-service` é dono do pedido: a saga começa ao consumir `order.created` e termina ao consumir
  `order.confirmed`/`order.canceled`, publicados pelo order-service em resposta a `order.confirm`/`order.cancel`.
- Compensações em ordem reversa; confirmação do pedido é o ponto sem retorno (pivot).

## Consequências
- (+) Fluxo, timeouts e compensações centralizados e testáveis; estado auditável (`GET /sagas/{id}`, `saga_step_log`).
- (+) "Reinício do coordenador" tem resposta clara: estado em banco + retomada.
- (−) O orquestrador é um componente crítico → mitigado com estado persistido, múltiplas réplicas seguras (`SKIP LOCKED`).
- (−) Mais mensagens (comando + resposta por passo).

## Alternativas consideradas
- **Coreografia**: menos um serviço, porém fluxo implícito espalhado, timeouts difíceis de detectar e compensação
  por "quem escuta o quê" — pior rastreabilidade e mais difícil de demonstrar os cenários de falha.
- **Orquestração síncrona (HTTP)**: simples, mas acopla disponibilidade e não demonstra publicação/consumo de eventos (seção 5).
- **Motor de workflow (Temporal/Camunda)**: robusto, mas esconde os mecanismos que o desafio quer ver e aumenta o custo operacional.
