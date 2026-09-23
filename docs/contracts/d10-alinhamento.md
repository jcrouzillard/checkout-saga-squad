# D10 — Alinhamento documentação × código × infraestrutura

> Demanda `f2324e0f25de` · branch `feature/D10-alinhar-documentacao-codigo-infra` · Arquiteto, 2026-09-23.
> Hierarquia de verdade (AGENTS.md): requisitos > ADRs/contratos > código. Para cada divergência: quem estava certo,
> o que muda e quem muda. **Nenhum contrato de evento/API muda** (sem mudança em payloads, tópicos ou endpoints).

## 1. Achados e decisão por divergência

| # | Divergência | Evidência no código | Veredito | Ação (dono) |
|---|-------------|---------------------|----------|-------------|
| D1 | `saga.md` §3.2 descrevia **uma** consulta `FOR UPDATE SKIP LOCKED LIMIT 50`; o código usa **duas fases** + lock otimista | `SagaTimeoutScheduler.scan()` → `SagaRepository.findDue` (sem lock, `ORDER BY updated_at LIMIT 50`) → `SagaService.tick` → `SagaRepository.lockDue` (`FOR UPDATE SKIP LOCKED`, refaz o filtro) → `SagaRepository.update` (`WHERE version = :version`) | Código correto e melhor (1 transação por saga; falha isolada). Doc desatualizado. | `saga.md` §3.2 reescrito (**feito**, Arquiteto) |
| D2 | `saga.md` §3.5/§4.5/§5 diziam que, ao reiniciar, o scheduler "age normalmente" sobre prazos vencidos (retry); o código aplica **carência** | `SagaTimeoutScheduler.scan()` (flag `resumed`) → `SagaService.resumeAfterRestart` → `SagaRepository.lockResumable` → `SagaStateMachine.resumeAfterRestart` (`deadline = now + timeout`, tentativa mantida, `RESUMED_AFTER_RESTART`, `saga_resumed_total`) | Código correto: é o que torna o requisito "continuar após reinício" verdadeiro para quedas > timeout. Faltava a decisão formal. | **ADR-013** + `saga.md` §3.5, §4.5, §5 (**feito**, Arquiteto) |
| D3 | Contagem do `TIMEOUT_ONCE`: `events.md` §3 dizia "registro de dedupe/domínio", ambíguo | `<Repo>.incrementAttempts(orderId)` na linha de domínio (`reservations/payments/shipments.attempts`) a cada recebimento do comando de ação; `ReplyPolicy.shouldReply` → `attempts >= 2` | Código conforme o contrato; contrato ficou preciso. | `events.md` §3 (esclarecimento, sem mudança de contrato) + `saga.md` §3.7 (**feito**, Arquiteto) |
| D4 | `saga.md` §3.1 sem colunas `last_causation_id`, `step_started_at`, `failed_step`, `failure_message` e sem a ação `RESUMED_AFTER_RESTART` | `V1__saga.sql`, `Transition.RESUMED_AFTER_RESTART` | Doc desatualizado (colunas auxiliares) | `saga.md` §3.1 (**feito**, Arquiteto) |
| D5 | `saga_timeouts_total{step}` não conta o passo `ORDER` | `SagaStateMachine.onTick` (`step.isParticipant()`) | Código aceitável (confirm/cancel têm retry infinito e alerta próprio); doc explicitado | `saga.md` §3.2 (**feito**) |
| D6 | Tópicos `.DLT` dependiam de criação automática? | `KafkaCommonConfiguration.checkoutTopics()` cria via `KafkaAdmin.NewTopics` os 9 tópicos de `Topics.ALL` **e** os 9 `<tópico>.DLT`, 3 partições; nenhum serviço desliga `checkout.kafka.create-topics`. Mas `docker-compose.yml` tem `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"` | Criação explícita já existe (D6); o broker ainda permite auto-criação, então não está **provado** que não se depende dela | DevOps: `"false"` no compose (§2 CA2) |
| D7 | `observability.md` pede `OTEL_INSTRUMENTATION_LOGBACK_MDC_ENABLED=true`; o compose não define | Agente OTel 2.8.0 já injeta por padrão — log real atual do saga-orchestrator tem `trace_id`, `span_id`, `orderId`, `sagaId`, `messageId` (formato `ecs`) | Funciona por default, mas diverge do documento; explicitar | DevOps + Observabilidade (CA3) |
| D8 | Jaeger, Prometheus, Grafana e checkout-console sem healthcheck | `docker-compose.yml` | Acabamento de infra | DevOps (CA4) |
| D9 | README não diz explicitamente que o Squad Control sobe fora do compose, nem por quê | `README.md` "Fábrica × produto" só fala do console | Documentar | Orquestrador (CA5) |

**Defeito de código: nenhum** que viole requisito, ADR ou contrato. Não há change-request para o Backend.
Limitações registradas no ADR-013 (não bloqueiam a D10, topologia atual = 1 réplica): cada réplica que sobe re-arma a
carência das outras; `KAFKA_GROUP_INSTANCE_ID` precisa ser distinto por réplica; a carência trava as sagas elegíveis
numa só transação. Opcional (fora do escopo): `spring.kafka.admin.fail-fast=true` para o serviço não subir se a
criação dos tópicos falhar (hoje o `KafkaAdmin` só loga; o `depends_on: kafka: service_healthy` mitiga).

## 2. Critérios de aceite verificáveis

**CA1 — `saga.md` (Arquiteto, feito).** `docs/architecture/saga.md` §3.2 (duas fases, `findDue`/`lockDue`,
`FOR UPDATE SKIP LOCKED`, `version`), §3.5 (carência, `resumeAfterRestart`, `RESUMED_AFTER_RESTART`), §3.7
(contagem `TIMEOUT_ONCE`), §4.5 e §5 atualizados; `docs/adr/013-carencia-de-prazos-na-retomada.md` aceito.
Verificação do Auditor: cada classe/método citado existe em `services/saga-orchestrator` e nos participantes.

**CA2 — DLT explícito (DevOps).** Em `docker-compose.yml`, serviço `kafka`: `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"`.
Seguro: todos os tópicos de negócio (`Topics.ALL`) e seus `.DLT` são criados por `NewTopics` em todos os serviços;
`__consumer_offsets` é interno e não depende dessa flag. Evidência (stack atual, auto-create ligado): o broker tem
exatamente `__consumer_offsets` + os 9 tópicos + os 9 `.DLT` — nenhum tópico foi criado por auto-criação.
Verificação (QA):
```
docker compose exec kafka /opt/kafka/bin/kafka-configs.sh --bootstrap-server localhost:9092 --describe --entity-type brokers --entity-name 1 --all | grep auto.create.topics.enable   # =false
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list | grep -c '\.DLT$'   # 9
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic order.commands.DLT   # PartitionCount: 3
```
+ `DeadLetterIT` passando (QA: se possível, com o container Kafka do Testcontainers também com auto-criação desligada).

**CA3 — MDC/trace no log (DevOps + Observabilidade).** DevOps: `OTEL_INSTRUMENTATION_LOGBACK_MDC_ENABLED: "true"` no
bloco comum `x-service.environment` (vale para os 5 serviços). Observabilidade: `docs/observability.md` passa a apontar
onde a variável está e anexa **uma linha real** de log JSON capturada após o `up --build` desta branch, com
`trace_id`, `span_id`, `orderId` e `sagaId`, obtida com
`docker compose logs --no-log-prefix saga-orchestrator | grep '"sagaId"' | grep '"trace_id"' | tail -1`,
e mostra que o `trace_id` abre o mesmo trace no Jaeger.

**CA4 — Healthchecks (DevOps).** Comandos **testados** nos containers em execução (imagens: jaeger e prometheus têm
`wget` BusyBox e não têm `curl`; grafana e nginx têm ambos). Use `127.0.0.1`: no nginx `localhost` resolve para `::1`
e a conexão é recusada (verificado).

| Serviço | `test` |
|---|---|
| `jaeger` (1.62.0) | `["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:14269/"]` (porta admin/health) |
| `prometheus` (v2.54.1) | `["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:9090/-/healthy"]` |
| `grafana` (11.2.0) | `["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:3000/api/health"]` |
| `checkout-console` (nginx 1.27-alpine) | `["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/"]` |

`interval: 10s`, `timeout: 5s`, `retries: 10`, `start_period: 10s`. Recomendado: `x-service.depends_on.jaeger`
→ `condition: service_healthy` e `grafana.depends_on.prometheus` → `service_healthy`.
Verificação: `docker compose ps` mostra `(healthy)` nos 4 (e nos já existentes).

**CA5 — README (Orquestrador).** Parágrafo em "Fábrica × produto": o Squad Control (`make squad`, porta 7070) **não**
está no `docker-compose.yml` por decisão — é a fábrica (genérica, gerencia outros projetos via
`docs/squad/project.json`, precisa do repositório, do git e das CLIs dos agentes no host), enquanto o compose contém
só o produto (checkout + console + observabilidade). `docker compose up --build` sobe o produto completo sem a fábrica.

**CA6 — Regressão (QA).** Na branch, com as mudanças de CA2–CA4: `docker compose down -v && docker compose up --build -d`;
todos os containers `healthy`; `tests/e2e/run.sh` completo passando (inclui DECLINE, FAIL, TIMEOUT de cada passo,
TIMEOUT_ONCE e reinício do coordenador — este com `RESUMED_AFTER_RESTART` no `GET /sagas/{id}` ou `saga_resumed_total`
> 0); `mvn -B verify` (ITs). Evidências anexadas ao handoff.

## 3. Donos e sequência
1. **DevOps** — `docker-compose.yml`: CA2 (auto-create off), CA3 (env), CA4 (4 healthchecks + depends_on).
2. **Observabilidade** — `docs/observability.md` + evidência de log (CA3), após o up da branch. Em paralelo:
   **Orquestrador** — `README.md` (CA5).
3. **QA** — CA6 e verificações de CA2/CA4. 4. **Auditor** — G3 da D10.
