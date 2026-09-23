# Handoff: Observabilidade → Backend

## O que foi feito
- `infra/observability/prometheus/prometheus.yml`: scrape 5s dos 5 serviços em `/actuator/prometheus`, label `service`. Validado com `promtool check config` (SUCCESS).
- `infra/observability/grafana/provisioning/datasources/datasources.yml` (Prometheus uid `prometheus` default; Jaeger uid `jaeger`) e `provisioning/dashboards/dashboards.yml` (aponta para `/var/lib/grafana/dashboards`).
- `infra/observability/grafana/dashboards/saga.json`: dashboard "Checkout Saga" (uid `checkout-saga`, refresh 5s, 13 painéis: sagas iniciadas/min, concluídas por outcome, taxa de sucesso, sagas em andamento, compensações/timeouts por passo, latência p50/p95 por passo, HTTP taxa/latência/5xx por serviço, Kafka lag, JVM heap). Validado com `python3 -m json.tool`.
- **Contrato completo em `docs/observability.md`** — leia antes de instrumentar.

## O que o Backend precisa implementar (resumo do contrato)
Métricas Micrometer (nomes exatos, tags obrigatórias) — só no `saga-orchestrator`:
`saga.started` (counter), `saga.completed{outcome}` (counter), `saga.compensations{step}` (counter),
`saga.timeouts{step}` (counter), `saga.retries{step}` (counter), `saga.step.duration{step,result}` (timer),
`saga.in.flight` (gauge). `step`∈{INVENTORY,PAYMENT,SHIPPING}, `outcome`∈{CONFIRMED,CANCELED}.

Propriedades obrigatórias em **todos os 5 serviços**:
```
management.endpoints.web.exposure.include=health,info,prometheus
management.metrics.distribution.percentiles-histogram.saga.step.duration=true
management.metrics.tags.application=${spring.application.name}
```

Logs: `logging.structured.format.console=ecs`; MDC `orderId`/`sagaId` manual; `trace_id`/`span_id` vêm
automaticamente do OTel Java Agent (não fazer `MDC.put` para eles).

## Ponto crítico: outbox quebra o trace
Como o Backend usa outbox + relay por polling, o trace se parte entre o `INSERT` e a publicação Kafka.
**Ação exigida**: salvar `traceparent` (W3C) como coluna na linha do outbox no momento do insert; ao publicar,
restaurar como **header Kafka** `traceparent` (ou, se o atraso for grande, criar span novo com *link* para o
original). Detalhes e código de exemplo na seção 3 de `docs/observability.md`.

## Riscos / pendências
- Nomes de tópicos/eventos e política exata de timeout/retry por passo dependem do Arquiteto
  (`docs/architecture/saga.md`, ainda em construção em paralelo — F2).
- Kafka consumer lag só aparece no dashboard se o Backend expuser `kafka_consumer_fetch_manager_records_lag_max`
  (padrão do client Kafka via Micrometer); painel não quebra se ausente.

## Referências
`docs/observability.md`, `infra/observability/**`.
