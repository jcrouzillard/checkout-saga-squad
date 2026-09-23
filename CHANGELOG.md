# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem SemVer.
Seções de demandas são geradas por `tools/squad/gitflow.py release-start` a partir do log da squad.

## [1.0.0] - 2026-09-23

### Produto — Checkout Saga
- Checkout distribuído com **Saga orquestrada**: order, inventory, payment e shipping + saga-orchestrator.
- Outbox transacional, consumo idempotente (`processed_messages`), retries com o mesmo `messageId`,
  timeouts persistidos e retomada após reinício do coordenador (static membership + carência).
- Compensações: liberação de estoque, estorno de pagamento, cancelamento de pedido.
- Observabilidade: OpenTelemetry → Jaeger, métricas de negócio → Prometheus/Grafana, logs JSON com `trace_id`.
- Console de Checkout (`checkout-console`) como interface do produto.
- Suíte e2e com 8 cenários, incluindo falhas de pagamento, envio, timeout e reinício do coordenador.

### Squad agêntica
- Agentes: Orquestrador, Arquiteto, Backend, DevOps, Observabilidade, QA, Frontend e **Auditor** (gatekeeper).
- Gates G1/G2/G3 com confiança e evidências; intervenção humana obrigatória abaixo de 70 %.
- Memória compartilhada (`decisions.jsonl`, handoffs, pareceres), espelhada em issues do GitHub.
- Squad Control: execução ao vivo, demandas (registrar, iniciar, pausar, repriorizar, cancelar), decisões humanas,
  observabilidade por produto e notificações.
- Git Flow com `tools/squad/gitflow.py` (merge em develop condicionado ao G3).

### Demandas entregues pela squad
- D1 — Listar os pedidos de um cliente (`GET /orders?customerId=`) — G3 aprovado pelo Auditor (88 %).
- D2 — Melhorar o visual do checkout — G3 devolvido (65 %), corrigido após decisão humana e aprovado (100 %).
