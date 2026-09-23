# Observabilidade — Checkout Saga

Dono: Agente de Observabilidade. Este documento é o **contrato** que o Backend deve implementar exatamente
(nomes de métricas, propriedades, MDC e propagação de trace). Divergência de nome/tag é bug de contrato (G2).

## 1. Métricas de negócio (Micrometer → Prometheus)

Micrometer converte `.` em `_` e sufixa por tipo. Implemente com `MeterRegistry` (ou anotações `@Counted`/`@Timed`
com nome explícito) — **não** deixe o Spring gerar nomes automáticos.

| Métrica Micrometer     | Tipo    | Tags                                   | Nome Prometheus resultante                                    |
|-------------------------|---------|-----------------------------------------|----------------------------------------------------------------|
| `saga.started`          | counter | —                                        | `saga_started_total`                                            |
| `saga.completed`        | counter | `outcome`=`CONFIRMED`\|`CANCELED`        | `saga_completed_total{outcome=...}`                              |
| `saga.compensations`    | counter | `step`=`INVENTORY`\|`PAYMENT`\|`SHIPPING`| `saga_compensations_total{step=...}`                             |
| `saga.timeouts`         | counter | `step`                                   | `saga_timeouts_total{step=...}`                                  |
| `saga.retries`          | counter | `step`                                   | `saga_retries_total{step=...}`                                  |
| `saga.step.duration`    | timer (histograma publicado) | `step`, `result`=`OK`\|`FAILED`\|`TIMEOUT` | `saga_step_duration_seconds_count/_sum/_bucket{step,result,le}` |
| `saga.in.flight`        | gauge   | —                                        | `saga_in_flight`                                                 |

Onde emitir cada métrica:
- `saga.started` / `saga.in.flight` (incrementa) — quando o `saga-orchestrator` cria a instância de saga (consome `order.created` ou recebe `POST /orders`, conforme desenho do Arquiteto).
- `saga.completed{outcome}` / `saga.in.flight` (decrementa) — ao transicionar a saga para `CONFIRMED` ou `CANCELED` (terminal).
- `saga.compensations{step}` — a cada compensação disparada (release de estoque, refund, cancelamento de envio).
- `saga.timeouts{step}` — quando um passo estoura o timeout configurado (ver `docs/architecture/saga.md` do Arquiteto para os valores).
- `saga.retries{step}` — a cada tentativa de retry além da primeira.
- `saga.step.duration{step,result}` — around de cada chamada de passo (`Timer.Sample` ou `@Timed`), do disparo até resposta/erro/timeout.

Todas as métricas de saga são emitidas pelo `saga-orchestrator` (é quem conhece o estado da máquina). Serviços de
domínio (`order`, `inventory`, `payment`, `shipping`) expõem apenas as métricas técnicas padrão (HTTP, JVM, Kafka).

### Propriedades obrigatórias (todos os 5 serviços)

```properties
management.endpoints.web.exposure.include=health,info,prometheus
management.metrics.distribution.percentiles-histogram.saga.step.duration=true
management.metrics.tags.application=${spring.application.name}
```

- `percentiles-histogram` habilita os buckets `_bucket` usados pelo `histogram_quantile` no dashboard (sem isso só
  existem `_count`/`_sum`, sem percentis calculáveis).
- `management.metrics.tags.application` é a tag usada pelo dashboard (`{{application}}`) para separar séries por
  serviço nos painéis de HTTP/JVM/Kafka — obrigatória em todos os módulos, inclusive `common`.
- Endpoint `/actuator/prometheus` deve responder na **mesma porta** da aplicação (8080–8084), sem porta de management separada — é o que o Prometheus faz scrape em `infra/observability/prometheus/prometheus.yml`.

## 2. Logs estruturados

Spring Boot 3.4 tem suporte nativo a logging estruturado, sem Logback XML customizado:

```properties
logging.structured.format.console=ecs
```

(alternativa aceitável: `logstash`, se o time preferir o schema Logstash; escolha um e mantenha em todos os
serviços — não misture).

- MDC obrigatório em **todo** log de domínio: `orderId`, `sagaId`. Adicione via `MDC.put("orderId", ...)` /
  `MDC.put("sagaId", ...)` no ponto de entrada da requisição/consumo de evento e limpe no `finally`.
- `trace_id` e `span_id`: **não** coloque manualmente. O OpenTelemetry Java Agent v2.8.0 injeta essas duas chaves
  no MDC automaticamente para todo log dentro de um span ativo, desde que:
  ```
  OTEL_LOGS_EXPORTER=none
  OTEL_INSTRUMENTATION_LOGBACK_MDC_ENABLED=true
  ```
  (ou o equivalente Log4j2, conforme a lib de logging escolhida pelo Backend). Com `format=ecs`/`logstash` e o
  agente ativo, `trace_id`/`span_id` aparecem como campos JSON de primeira classe automaticamente — não precisa de
  `MDC.put` para eles.

## 3. Traces e propagação de contexto

- Instrumentação automática via **OpenTelemetry Java Agent v2.8.0** anexado a cada JAR (`-javaagent:/otel/opentelemetry-javaagent.jar`), configurado por variáveis de ambiente padrão do ADR-000:
  ```
  OTEL_SERVICE_NAME=<nome-do-modulo>            # ex.: order-service
  OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
  OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
  OTEL_TRACES_EXPORTER=otlp
  OTEL_METRICS_EXPORTER=none        # métricas já vão por Micrometer/Prometheus, não duplicar via OTLP
  OTEL_LOGS_EXPORTER=none
  ```
- HTTP: o agente propaga `traceparent`/`tracestate` (W3C Trace Context) automaticamente em toda chamada
  RestTemplate/WebClient/servlet — nenhuma ação do Backend é necessária.
- Kafka: o agente também injeta/lê `traceparent` como **header** da mensagem automaticamente para produtores e
  consumidores Spring Kafka instrumentados — nenhuma ação do Backend é necessária **desde que o publish/consume
  aconteça na mesma thread/contexto do span ativo**.

### Atenção: outbox com relay por polling quebra a cadeia de trace

O Backend usa **outbox + relay por polling** (uma thread agendada lê a tabela `outbox` e publica no Kafka). Isso
quebra o trace em dois pontos:

1. Entre o span que **gravou** a linha de outbox (dentro da transação HTTP/consumo original) e o span que a
   **publica** no Kafka (dentro do job de polling, minutos/segundos depois, sem relação de causalidade automática).
2. O agente não tem como saber, no momento do `INSERT`, qual vai ser o span do relay — são execuções desconectadas.

**Padrão recomendado para o Backend implementar:**

1. **No momento de gravar a linha de outbox** (dentro do span de negócio ativo), capture o contexto W3C atual e
   grave como uma coluna adicional na tabela outbox:
   ```java
   String traceparent = W3CTraceContextPropagator.getInstance()
       .extractTraceparent(Context.current()); // ou monte manualmente "00-<traceId>-<spanId>-<flags>"
   ```
   Adicione a coluna `outbox.traceparent VARCHAR(55)` (formato W3C: `version-traceid-spanid-flags`).
2. **No relay, ao publicar cada linha**, restaure esse `traceparent` como **header Kafka** da mensagem, em vez de
   deixar o agente gerar um novo trace desconectado a partir do contexto do job de polling:
   ```java
   ProducerRecord<String, byte[]> record = new ProducerRecord<>(topic, key, payload);
   record.headers().add("traceparent", entity.getTraceparent().getBytes(StandardCharsets.UTF_8));
   ```
   Isso faz o consumidor do evento (instrumentado pelo agente) continuar o **mesmo** trace original, mesmo tendo
   atravessado a tabela de outbox.
3. **Alternativa/complemento** (recomendada quando o atraso do relay for grande, ex. > alguns segundos, o que
   tornaria o trace "esticado" e confuso na UI): em vez de continuar o mesmo trace, crie no relay um **span novo
   com um *link*** para o span original (`Span.addLink(originalSpanContext)`), e propague o `traceparent` do span
   **novo** para o Kafka. Isso mantém a navegabilidade (Jaeger mostra "Follows From"/link) sem distorcer a duração
   do trace de negócio com o tempo de espera do polling.
4. Registre no log do relay (`orderId`, `sagaId`, `traceparent` restaurado) para permitir correlação manual caso o
   link/propagação falhe silenciosamente.

Aplique este padrão em **todo** produtor de outbox (order, inventory, payment, shipping, saga-orchestrator).

## 4. Dashboard Grafana

- Arquivo: `infra/observability/grafana/dashboards/saga.json`, uid `checkout-saga`, pasta "Checkout Saga",
  refresh `5s`, intervalo padrão "últimos 15 minutos". Provisionado automaticamente via
  `infra/observability/grafana/provisioning/dashboards/dashboards.yml`.
- Datasources provisionados (`infra/observability/grafana/provisioning/datasources/datasources.yml`):
  Prometheus (uid `prometheus`, default) e Jaeger (uid `jaeger`, `http://jaeger:16686`).
- Painéis: sagas iniciadas/min, sagas concluídas por outcome (série e total), taxa de sucesso (%), sagas em
  andamento (gauge), compensações por passo, timeouts por passo, latência p50/p95 por passo, HTTP (taxa,
  latência p95, erros 5xx) por serviço, Kafka consumer lag (se exposto pelos consumidores via Micrometer;
  painel fica vazio sem quebrar caso a métrica não exista) e JVM heap por serviço.

## 5. Como investigar cada cenário de falha obrigatório

Em todos os casos, o ponto de partida é o **`orderId`** (vem da resposta de `POST /orders` e do log da aplicação).

### a) Falha no pagamento
- **Jaeger**: busque por tag `orderId=<id>` no serviço `saga-orchestrator` (ou `payment-service`); o span da
  chamada a `payment-service` aparece com status de erro; spans seguintes mostram a compensação (release de
  estoque, cancelamento do pedido).
- **Métricas**: `saga_compensations_total{step="PAYMENT"}` sobe; `saga_completed_total{outcome="CANCELED"}` sobe;
  `saga_step_duration_seconds{step="PAYMENT",result="FAILED"}` registra a duração até a falha.
- **Logs**: filtre por `orderId`/`sagaId` no `payment-service` (motivo da negativa) e no `saga-orchestrator`
  (decisão de compensar); `trace_id` do log bate com o trace no Jaeger.

### b) Falha no envio
- **Jaeger**: span de chamada ao `shipping-service` com erro; trace mostra se a compensação foi refund de
  pagamento + release de estoque (a saga trata envio como último passo antes da confirmação).
- **Métricas**: `saga_compensations_total{step="SHIPPING"}` (se houver compensação) ou, se o desenho do
  Arquiteto tratar falha de envio como não bloqueante/retentável, acompanhar `saga_retries_total{step="SHIPPING"}`
  antes de decidir por compensação — ver `docs/architecture/saga.md` para a política exata.
- **Logs**: `shipping-service` registra o motivo (ex.: indisponibilidade da transportadora); `saga-orchestrator`
  registra a transição de estado resultante.

### c) Timeout em qualquer etapa
- **Jaeger**: span do passo aparece com duração próxima/igual ao timeout configurado, sem span de resposta do
  serviço de domínio (ou span filho "perdido"/incompleto do lado do chamado).
- **Métricas**: `saga_timeouts_total{step=...}` sobe; painel "Latência p50/p95 por passo" mostra p95 crescendo
  para aquele `step` antes do timeout disparar (sinal de degradação); `saga_retries_total{step=...}` pode subir
  se houver retry antes de declarar timeout definitivo.
- **Logs**: buscar por `sagaId` no `saga-orchestrator` para ver a mensagem de expiração do timer e a compensação
  disparada; no serviço de domínio, verificar se a operação eventualmente completou "tarde" (indício de
  problema de idempotência a checar via `processed_messages`).

### d) Reinício inesperado do coordenador da saga
- **Jaeger**: o trace do pedido fica "cortado" no meio (falta o span de continuação); ao localizar por
  `orderId`, observe o gap de tempo entre o último span antes do restart e o próximo (deve corresponder à
  retomada do estado persistido, não a um novo trace desconexo — se vier um novo `trace_id` sem link, é sinal de
  que a retomada não está usando o `traceparent` salvo, mesmo problema descrito na seção 3).
- **Métricas**: `saga_in_flight` deve permanecer estável logo após o restart (não deve zerar, se as sagas persistidas
  forem recarregadas do banco), e depois retomar tendência normal; `up{job=~"saga-orchestrator"}` no Prometheus
  mostra o gap de scrape durante o restart (healthcheck do compose reflete o mesmo).
- **Logs**: no boot do `saga-orchestrator`, procurar log de "recuperação de sagas em andamento" (lendo estado
  persistido) com `sagaId` de cada saga retomada; comparar timestamps com o momento do timeout/compensação
  original para confirmar que nenhuma saga ficou "presa" sem novo timer agendado.
