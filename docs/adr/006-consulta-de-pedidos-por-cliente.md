# ADR-006: Consulta de pedidos por cliente no order-service

**Status**: Aceito (2026-09-23, Arquiteto) — demanda D1 (Squad Control).

## Contexto
O solicitante precisa listar os pedidos de um cliente (`GET /orders?customerId=`), do mais recente ao mais antigo,
sem alterar eventos, a Saga ou outros serviços.

## Decisão
- Expor a consulta no **order-service**, dono do agregado Pedido, lendo apenas o database `orders`
  (status e `cancellationReason` já são mantidos lá via `order.confirm`/`order.cancel`).
- Índice `orders (customer_id, created_at DESC)`; ordenação `created_at desc, order_id desc`.
- `limit` opcional (default 50, máx. 200); sem paginação por cursor nesta versão.
- Contrato em `docs/contracts/api.md` §1.

## Consequências
- (+) Nenhuma mudança em eventos, Saga ou participantes; consulta O(log n) pelo índice.
- (+) Consistente com a fonte de verdade do status do pedido.
- (−) Status pode estar momentaneamente `PENDING` enquanto a saga roda (consistência eventual, igual ao `GET /orders/{id}`).
- (−) Clientes com mais de 200 pedidos não conseguem ver o histórico completo até existir paginação por cursor.

## Alternativas consideradas
- **Consultar a Saga (`saga_instance`)**: acopla leitura de negócio ao coordenador e mistura responsabilidades.
- **Read model/CQRS separado**: desnecessário para o volume e o prazo atuais.
- **Paginação por offset/cursor já agora**: fora dos critérios de aceite; registrada como evolução.
